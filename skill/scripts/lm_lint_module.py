#!/usr/bin/env python3
"""
Lint LogicModule JSON for the defects that fail SILENTLY in a portal. Standalone: stdlib only.

    python lm_lint_module.py <module.json|dir> [...] [--strict]

Each check here exists because the defect it catches imports cleanly and then misbehaves
without an error: datapoints that record No Data, secrets shown in plain text, instance
history deleted during an outage, a PropertySource that applies a suite to every host.

ERROR  will break collection, identity, security or import -- fix before importing.
WARN   likely wrong or below Exchange standard; heuristic, so read it, don't obey it.
Exit 1 if any ERROR (or any WARN with --strict).

Understands DataSources, PropertySources (plain and ERI) and TopologySources, in the
My Module Toolbox export format. The REST API model (dataPoints / postProcessorParam /
useWildValueAsUUID) is normalised and linted too, with a warning that it is not the
format the Toolbox exports. ConfigSources, EventSources, LogSources, DiagnosticSources
and RemediationSources get the shared checks (secrets, snippets, exits, discovery) only.
Groovy and PowerShell scripts are both read; Groovy-4 checks apply to Groovy only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WILDVALUE_PREFIX = "##WILDVALUE##."
# Names a portal has actually refused on import. Extend when a portal rejects another.
RESERVED_DATAPOINT_NAMES = {"in"}
# The suffix confirmed in a portal to mask a property's value. Other suffixes may also be
# masked by LogicMonitor, but this is the one known to work, so the linter asks for it.
CREDENTIAL_SUFFIX = ".credential"
SECRET_WORDS = re.compile(r"(token|secret|pass(word)?|api[._-]?key|apikey|\.key$|private)", re.I)
# LogicMonitor's own credential property names. LM's snippets read exactly these (lm.remote
# reads ssh.pass, lm.sql examples read jdbc.pass), so a module that interoperates with them
# cannot rename them to *.credential. [LM recipes; that the portal masks them is inferred]
BUILTIN_CREDENTIAL_PROPERTIES = {
    "ssh.pass", "ssh.cert.pass", "ssh.publickey.pass", "config.pass", "wmi.pass",
    "jdbc.pass", "jmx.pass", "esx.pass", "snmp.authtoken", "snmp.privtoken",
}
PROPERTY_LITERAL = re.compile(r"""['"]([a-z][\w-]*(?:\.[\w-]+)+)['"]""")
# PowerShell reads properties as ##name## tokens substituted before the script runs.
PROPERTY_TOKEN = re.compile(r"##([a-z][\w-]*(?:\.[\w-]+)+)##")
# The only Active Discovery schedules the portal takes. [LM recipes]
DISCOVERY_INTERVALS = ("0m", "15m", "60m", "1440m")
MODULE_TYPES = {0: "datasource", 1: "eventsource", 5: "propertysource", 6: "configsource",
                9: "topologysource", 10: "logsource", 11: "diagnosticsource",
                12: "remediationsource"}
SHARED_CHECKS_ONLY = ("eventsource", "configsource", "logsource", "diagnosticsource",
                      "remediationsource")
PRINTED_NAME = re.compile(r"""['"]\.?([A-Z][A-Za-z0-9_]*)=['"]""")
EMIT_CALL = re.compile(r"""\w+\(\s*[^,()]+,\s*['"]([A-Z][A-Za-z0-9_]*)['"]""")
# lm.emit snippet, Script form: emit.dp("Name", value)
EMIT_DP = re.compile(r"""\.dp\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")
CATCH_RETURN_ZERO = re.compile(r"catch\s*\([^)]*\)\s*\{[^{}]*?return\s+0\b", re.S)
THRESHOLD = re.compile(r"^\s*(>|>=|<|<=|=|==|!=)\s*-?[\d.]+(\s+-?[\d.]+){0,2}\s*$")
PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
MODULE_NAME = re.compile(r"^[A-Za-z0-9]+(_[A-Za-z0-9]+)+$")


class Report:
    def __init__(self, label: str) -> None:
        self.label = label
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


# ------------------------------------------------------------------ normalising

def normalise(raw: dict, report: Report) -> dict:
    """Return the module in export-format field names."""
    if "dataPoints" in raw and "datapoints" not in raw:
        report.warn("this is the REST API DataSource model (dataPoints, postProcessorParam, "
                    "useWildValueAsUUID), not the My Module Toolbox export format; build "
                    "exports from a real exported module")
        adc = raw.get("autoDiscoveryConfig") or {}
        method = adc.get("method") or {}
        attrs = raw.get("collectorAttribute") or {}
        module = {
            "name": raw.get("name"),
            "displayedAs": raw.get("displayName"),
            "description": raw.get("description"),
            "technicalNotes": raw.get("technicalNotes") or raw.get("technology"),
            "appliesTo": raw.get("appliesTo"),
            "collectionMethod": raw.get("collectMethod"),
            "multiInstance": raw.get("hasMultiInstances"),
            "useWildValueAsUniqueIdentifier": raw.get("useWildValueAsUUID"),
            "collectionAttrs": {"content": attrs.get("groovyScript", "")},
            "datapoints": [{
                "name": dp.get("name"),
                "type": dp.get("type"),
                "dataType": dp.get("dataType"),
                "interpretMethod": dp.get("postProcessorMethod"),
                "interpretExpr": dp.get("postProcessorParam"),
                "threshold": dp.get("alertExpr", ""),
                "min": dp.get("minValue", ""),
                "description": dp.get("description"),
            } for dp in raw["dataPoints"]],
        }
        if raw.get("enableAutoDiscovery"):
            module["activeDiscovery"] = {
                "params": {"content": method.get("groovyScript", "")},
                "deleteInactiveInstances": adc.get("deleteInactiveInstance"),
                "autoDeleteInstances": False,
            }
        return module
    return raw


def kind_of(module: dict) -> str | None:
    if isinstance(module.get("type"), int) and module["type"] in MODULE_TYPES:
        return MODULE_TYPES[module["type"]]
    if "propertySourceType" in module or ("script" in module and "datapoints" not in module):
        return "propertysource"
    if "collectionIntervalSec" in module:
        return "topologysource"
    if "datapoints" in module:
        return "datasource"
    return None


def scripts_of(module: dict) -> dict[str, tuple[str, str]]:
    """slot -> (language, text). Language is the export's script `type`, lowercased."""
    out: dict[str, tuple[str, str]] = {}
    attrs = module.get("collectionAttrs")
    if isinstance(attrs, dict):
        out["collect"] = ((attrs.get("type") or "groovy").lower(), attrs.get("content", "") or "")
    elif isinstance(attrs, str):
        try:
            out["collect"] = ("groovy", json.loads(attrs).get("scriptgroovy", ""))
        except ValueError:
            out["collect"] = ("groovy", attrs)
    ad = ((module.get("activeDiscovery") or {}).get("params") or {})
    if isinstance(ad, dict) and ad.get("content"):
        out["discovery"] = ((ad.get("type") or "groovy").lower(), ad["content"])
    script = module.get("script")
    if isinstance(script, dict):
        out["script"] = ((script.get("type") or "groovy").lower(), script.get("content", "") or "")
    return out


# ---------------------------------------------------------------- shared checks

# The portal refuses to save a module whose text field passes 4096 characters ("Field value
# cannot contain more than 4096 characters"), naming no field [portal]. Scripts are exempt:
# collectionAttrs is a script container (a JSON string on a TopologySource), and every other
# script sits inside an object, so only top-level metadata strings are measured.
MAX_FIELD_CHARS = 4096
SCRIPT_FIELDS = {"collectionAttrs"}


def check_common(module: dict, report: Report) -> None:
    for key, value in module.items():
        if key not in SCRIPT_FIELDS and isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
            report.error(f"{key} is {len(value)} characters; the portal refuses to save a "
                         f"field over {MAX_FIELD_CHARS}")
    name = module.get("name") or ""
    if not MODULE_NAME.match(name):
        report.warn(f"name {name!r} is not Vendor_Product_Component form")
    if not (module.get("technicalNotes") or "").strip():
        report.warn("no technicalNotes -- Exchange review expects per-module rationale")
    if not (module.get("description") or "").strip():
        report.warn("no description")
    if not (module.get("appliesTo") or "").strip():
        report.error("empty appliesTo -- the module will apply to nothing")


def check_scripts(module: dict, scripts: dict[str, tuple[str, str]], kind: str,
                  report: Report) -> None:
    combined = "\n".join(text for _, text in scripts.values())
    if not combined.strip():
        report.error("no embedded script found")
        return
    groovy = {slot: text for slot, (lang, text) in scripts.items() if lang == "groovy"}
    powershell = {slot: text for slot, (lang, text) in scripts.items() if lang == "powershell"}

    # Secrets. A property that holds a secret must end in .credential or the portal shows
    # its value in plain text -- and renaming it later breaks every deployment quietly.
    found = set(PROPERTY_LITERAL.findall(combined)) | set(PROPERTY_TOKEN.findall(combined))
    for prop in sorted(found):
        if prop.startswith(("system.", "auto.", "predef.", "topo.")):
            continue
        if prop.lower() in BUILTIN_CREDENTIAL_PROPERTIES:
            continue
        last = prop.rsplit(".", 1)[-1]
        if SECRET_WORDS.search(prop) and not prop.endswith(CREDENTIAL_SUFFIX) and last not in (
                "url", "port", "timeout", "insecure", "realm", "id", "user", "username"):
            report.error(f"property {prop!r} looks like a secret but does not end in "
                         f"{CREDENTIAL_SUFFIX!r}; the portal-confirmed masking suffix is "
                         f"{CREDENTIAL_SUFFIX!r} -- pick the name once, renames go quiet")

    for slot, text in groovy.items():
        if text.strip() and "//!/lib-groovy/v4" not in text.splitlines()[0:3].__str__():
            report.warn(f"{slot} script has no '//!/lib-groovy/v4' first line to pin Groovy 4")
        # A snippet loaded without the script's binding runs detached from it: emit.dp()
        # then exits 0 and prints nothing the Collector can see. [LM recipes]
        if "Snippets.getLoader()" in text and not re.search(
                r"\.withBinding\(\s*(getBinding\(\)|binding)\s*\)|\.binding\s*=\s*binding", text):
            report.error(f"{slot} script loads Collector snippets without "
                         f".withBinding(getBinding()) -- emit.dp() and friends will exit 0 "
                         f"and print nothing the Collector can parse")

    groovy_text = "\n".join(groovy.values())
    if re.search(r"\.(push|pop)\(", groovy_text):
        report.warn("List.push/pop were removed in Groovy 4; use add / remove(size-1)")
    if re.search(r"\bnew\s+XmlSlurper|\bnew\s+XmlParser", groovy_text) and \
            "groovy.xml" not in groovy_text:
        report.warn("XmlSlurper/XmlParser moved to groovy.xml.* in Groovy 4")

    for slot, text in powershell.items():
        # Write-Host does not reliably reach stdout and slows BatchScript; debug-gated use
        # is fine. [LM recipes]
        for line in text.splitlines():
            if re.search(r"\bWrite-Host\b", line) and not re.search(r"debug", line, re.I):
                report.warn(f"{slot} script writes with Write-Host -- Collector data must go "
                            f"through Write-Output; keep Write-Host for debug-gated messages")
                break

    # Per script, not over the joined text: each embedded script runs on its own, so a gate
    # in the discovery script does not protect a bypass in the collection script.
    for slot, text in groovy.items():
        check_tls_bypass(slot, text, report)


def check_active_discovery(module: dict, report: Report) -> None:
    ad = module.get("activeDiscovery") or {}
    for flag in ("deleteInactiveInstances", "autoDeleteInstances"):
        if ad.get(flag):
            report.error(f"activeDiscovery.{flag} is true -- an outage that makes discovery "
                         f"fail or return nothing will delete instances and their history")
    interval = ad.get("discoveryInterval")
    if ad and interval is not None and interval not in DISCOVERY_INTERVALS:
        report.error(f"activeDiscovery.discoveryInterval is {interval!r}; the portal takes "
                     f"only {', '.join(DISCOVERY_INTERVALS)}")


TLS_BYPASS = re.compile(r"X509TrustManager|setDefaultHostnameVerifier|TrustAll|"
                        r"checkServerTrusted", re.I)
# A property that turns validation OFF when true (must default false) ...
BYPASS_PROPERTY = re.compile(
    r"""['"]([\w.-]*(?:insecure|skip|ignore|trustall|trust\.all|selfsigned|self\.signed|"""
    r"""noverify|no\.verify|disable)[\w.-]*)['"]""", re.I)
# ... or one that turns validation ON when true (must default true, or be unset = on).
VERIFY_PROPERTY = re.compile(r"""['"]([\w.-]*(?:verify|validate|strict)[\w.-]*)['"]""", re.I)
IF_CONDITION = re.compile(r"\bif\s*\((.+)\)\s*\{?\s*$", re.M)


def _dotted(found: list[str]) -> set[str]:
    return {p for p in found if "." in p and not p.lower().startswith(("javax.", "java."))}


def _default_is(prop: str, value: str, text: str) -> bool:
    return re.search(re.escape(prop) + r"""['"]\s*,\s*['"]?""" + value + r"""['"]?\s*\)""",
                     text, re.I) is not None


def check_tls_bypass(slot: str, text: str, report: Report) -> None:
    """
    A certificate-validation bypass is fine for lab targets only when a property switches it
    on and it is off by default. Silent when the bypass in this script sits behind an `if`
    on such a property (directly, or via a variable assigned from it) with a safe default.
    A plain "use https" property such as vendor.ssl is not a gate and is ignored.
    """
    if not TLS_BYPASS.search(text):
        return
    bypass = _dotted(BYPASS_PROPERTY.findall(text))
    verify = _dotted(VERIFY_PROPERTY.findall(text))
    if not bypass and not verify:
        report.error(f"{slot} script bypasses TLS verification with no property gate -- make "
                     f"it opt-in via a property (e.g. vendor.api.insecure) that defaults off")
        return
    for prop in sorted(bypass):
        if _default_is(prop, "true", text):
            report.error(f"{slot} script: TLS bypass property {prop!r} defaults to true -- "
                         f"it must default off")
            return
    for prop in sorted(verify):
        if _default_is(prop, "false", text):
            report.error(f"{slot} script: TLS verification property {prop!r} defaults to "
                         f"false -- verification must default on")
            return
    props = bypass | verify
    # A variable assigned from a gate property counts as the gate too.
    names: set[str] = set()
    for prop in props:
        names.update(re.findall(r"(\w+)\s*=\s*[^\n=]*" + re.escape(prop), text))
    gated = any(any(p in cond for p in props) or
                any(re.search(r"\b" + re.escape(n) + r"\b", cond) for n in names)
                for cond in IF_CONDITION.findall(text))
    if not gated:
        report.warn(f"{slot} script: TLS bypass present and {sorted(props)} exist, but no `if` "
                    f"on them was found -- confirm the bypass only runs when the property is set")


def check_datasource(module: dict, scripts: dict[str, tuple[str, str]], report: Report) -> None:
    method = module.get("collectionMethod")
    batch = method == "batchscript"
    multi = module.get("multiInstance") is True
    datapoints = module.get("datapoints") or []

    if method not in ("script", "batchscript"):
        report.warn(f"collectionMethod {method!r} -- this linter only understands Groovy "
                    f"script / batchscript collection")
    if batch and not multi:
        report.error("batchscript collection requires multiInstance: true")
    if multi and not module.get("activeDiscovery"):
        report.error("multiInstance module has no Active Discovery")
    if multi and module.get("useWildValueAsUniqueIdentifier") is not True:
        report.error("useWildValueAsUniqueIdentifier is not true -- the wildvalue is not the "
                     "instance identity, so instances can be re-created and lose history")

    check_active_discovery(module, report)

    names: list[str] = []
    for dp in datapoints:
        dp_name = dp.get("name") or ""
        names.append(dp_name)
        expr = dp.get("interpretExpr") or ""
        if dp.get("interpretMethod") not in (None, "namevalue"):
            report.warn(f"datapoint {dp_name!r} post-processor is {dp.get('interpretMethod')!r}, "
                        f"not namevalue")
        elif batch and not expr.startswith(WILDVALUE_PREFIX):
            report.error(f"datapoint {dp_name!r} interpretExpr is {expr!r}; batchscript output "
                         f"is '<wildvalue>.<name>=value' so it must be "
                         f"'{WILDVALUE_PREFIX}{dp_name}' -- as written it records No Data on "
                         f"every instance while Test Script output looks correct")
        elif not batch and expr.startswith(WILDVALUE_PREFIX):
            report.error(f"datapoint {dp_name!r} uses {WILDVALUE_PREFIX} but this is not a "
                         f"batchscript module -- script output keys are bare names")
        elif expr and expr.removeprefix(WILDVALUE_PREFIX) != dp_name:
            report.warn(f"datapoint {dp_name!r} reads key {expr!r}; keeping key and name "
                        f"identical is what makes print/declare drift checkable")

        if dp_name.lower() in RESERVED_DATAPOINT_NAMES:
            report.error(f"datapoint name {dp_name!r} is reserved -- a portal refused it")
        if not PASCAL.match(dp_name):
            report.warn(f"datapoint name {dp_name!r} is not PascalCase")
        if dp.get("dataType") not in (None, 1, 2, 3, 4, 5, 6, 7, 8):
            report.error(f"datapoint {dp_name!r} dataType {dp.get('dataType')!r} is not 1..8")
        if dp.get("type") in ("derive", 3) and str(dp.get("min", "")).strip() not in ("0", "0.0"):
            report.warn(f"derive datapoint {dp_name!r} has no min of 0 -- a counter reset "
                        f"graphs as a negative spike")
        threshold = (dp.get("threshold") or "").strip()
        if threshold and not THRESHOLD.match(threshold):
            report.warn(f"datapoint {dp_name!r} threshold {threshold!r} is not "
                        f"'<op> warn [error [critical]]'")
        if threshold and not (dp.get("alertBody") or "").strip():
            report.warn(f"datapoint {dp_name!r} alerts but has no alertBody")

    for dup in sorted({n for n in names if names.count(n) > 1}):
        report.error(f"datapoint {dup!r} is declared more than once")

    collect = scripts.get("collect", ("groovy", ""))[1]
    if collect:
        if not re.search(r"\b(return|exit)\s+[1-9]", collect):
            report.warn("collection script has no non-zero exit; on API failure it must write "
                        "the reason to stderr and exit 2 so instances survive")
        if CATCH_RETURN_ZERO.search(collect):
            report.error("a catch block in the collection script returns 0 -- failures will "
                         "look like success (and zero-filled values like real data)")
        # Only lines that print count -- a literal like 'Bearer=' in a header is not output.
        print_lines = '\n'.join(line for line in collect.splitlines()
                                if re.search(r'\bprint(ln)?\b|\bemit\w*\(|Emit\(|\.dp\(|'
                                             r'\bWrite-Output\b', line))
        printed = (set(PRINTED_NAME.findall(print_lines)) | set(EMIT_CALL.findall(print_lines))
                   | set(EMIT_DP.findall(print_lines)))
        if printed:
            for extra in sorted(printed - set(names)):
                report.warn(f"script appears to print {extra!r} but no datapoint declares it")
            for missing in sorted(set(names) - printed):
                report.warn(f"datapoint {missing!r} is never visibly printed (heuristic: names "
                            f"built dynamically are invisible -- use string literals)")
    discovery = scripts.get("discovery", ("groovy", ""))[1]
    snippet_fold = "emit.instance" in discovery and ".dp(" in collect
    if batch and discovery and not snippet_fold and \
            "replaceAll" not in discovery and "replaceAll" not in collect and \
            "-replace" not in discovery and "-replace" not in collect:
        report.warn("no character fold visible on the wildvalue -- '.', spaces, ':', '=', '\\' "
                    "and '#' in an id break discovery or batchscript parsing")
    if ("emit.instance" in discovery) != (".dp(" in collect) and batch and discovery:
        report.warn("only one of discovery (emit.instance) and collection (emit.dp) uses the "
                    "lm.emit snippet -- it folds wildvalues its own way, so the other side "
                    "must fold identically or every datapoint reads No Data")
    if discovery and "####" not in discovery and "##" in discovery and \
            "emit.instance" not in discovery:
        report.warn("discovery prints no '####' property separator -- fine for the minimal "
                    "'wildvalue##name' form, but instance properties need it")


# emitEri('<category>', <priority>, <keys>, <ERT>, ...) -- the ERT as a literal or a variable.
EMIT_ERI = re.compile(r"""emitEri\(\s*(['"])([^'"]*)\1\s*,\s*(\d+)\s*,\s*"""
                      r"""(?:\[[^\]]*\]|[^,()]+)\s*,\s*(?:(['"])([^'"]*)\4|(\w+))""")


def check_eri_priority(text: str, report: Report) -> None:
    # The resource's ERT comes from the highest-priority ERI entry across ALL categories,
    # while keys from every category merge into the ID [portal, 2026-10-19]. LM's built-in
    # addERI_Linux / addERI_Windows emit net.l2 at priority 2, so a type override below
    # priority 3 merges its keys but leaves the type PhysicalServer.
    for match in EMIT_ERI.finditer(text):
        category, priority, ert = match.group(2), int(match.group(3)), match.group(5)
        if ert is None:
            # A variable ERT: resolve it only from an unambiguous string assignment.
            assigned = set(re.findall(r"""\b%s\s*=\s*['"]([^'"]*)['"]"""
                                      % re.escape(match.group(6)), text))
            ert = assigned.pop() if len(assigned) == 1 else None
        if ert is None or ert == "PhysicalServer" or priority >= 3:
            continue
        report.warn(f"emitEri({category!r}, {priority}, ..., {ert!r}): the ERT comes from the "
                    f"highest-priority ERI entry across all categories, so this type will not "
                    f"override the built-in net.l2 entry (priority 2) -- it needs priority 3 "
                    f"or more (its keys still merge into the ID)")


def check_propertysource(module: dict, scripts: dict[str, tuple[str, str]],
                         report: Report) -> None:
    if module.get("type") != 5:
        report.error(f"PropertySource type is {module.get('type')!r}; exports carry the integer 5")
    script = module.get("script")
    if not (isinstance(script, dict) and "content" in script):
        report.error("PropertySource script must be {\"type\": \"groovy\", \"content\": ...}")
    eri = "propertySourceType" in module
    if eri:
        if module.get("propertySourceType") != 1:
            report.error("ERI PropertySource propertySourceType must be the integer 1")
        if not isinstance(module.get("collectionInterval"), int):
            report.error("ERI PropertySource needs an integer collectionInterval (seconds)")
    elif "collectionInterval" in module:
        report.error("a plain PropertySource carries no collectionInterval -- only ERI ones do")

    text = scripts.get("script", ("groovy", ""))[1]
    if eri:
        check_eri_priority(text, report)
    if not eri:
        # A PropertySource's properties are stored as auto.<key> [portal, LM docs]; the only
        # system.* it can set is system.categories [LM docs].
        printed = set(re.findall(r"""(?:println|print|Write-Output)\s*\(?\s*['"]([\w.-]+)=""",
                                 text))
        printed |= set(re.findall(r"""\.property\(\s*['"]([\w.-]+)['"]""", text))
        for key in sorted(printed):
            if key == "system.categories" or key.startswith("auto."):
                continue
            if key.startswith("system."):
                report.warn(f"PropertySource sets {key!r}: system.categories is the only "
                            f"system.* property a PropertySource can set")
            else:
                report.warn(f"PropertySource sets {key!r}, which the portal stores as "
                            f"'auto.{key}' -- AppliesTo, other modules and docs must use "
                            f"that name (a bare reference matches nothing)")
    if (module.get("appliesTo") or "").replace(" ", "") == "true()":
        if re.search(r"\b(return|exit)\s+[1-9]", text):
            report.error("PropertySource on AppliesTo true() has a non-zero exit -- it runs on "
                         "every resource and must exit 0 silently on non-targets and errors")
        if any(re.search(r'(?<!System\.err\.)\bprintln\b|System\.out\.', body)
               for body in re.findall(r"catch\s*\([^)]*\)\s*\{([^{}]*)\}", text, re.S)):
            report.error("PropertySource on AppliesTo true() prints from a catch block -- it "
                         "must stay silent on failure or it tags unrelated hosts")
        report.warn("AppliesTo true(): verify by hand that EVERY non-target path exits 0 with "
                    "no stdout, or the suite applies itself to unrelated resources")


def check_topologysource(module: dict, scripts: dict[str, tuple[str, str]],
                         report: Report) -> None:
    if module.get("type") != 9:
        report.error(f"TopologySource type is {module.get('type')!r}; exports carry the integer 9")
    if not isinstance(module.get("collectionIntervalSec"), int):
        report.error("collectionIntervalSec must be an integer number of seconds")
    attrs = module.get("collectionAttrs")
    if not isinstance(attrs, str):
        report.error("collectionAttrs must be a JSON-ENCODED STRING, not an object -- a portal "
                     "refused the object form with 'non empty field value required'")
    else:
        try:
            decoded = json.loads(attrs)
        except ValueError:
            report.error("collectionAttrs is not valid JSON")
            return
        if decoded.get("scripttype") != "embed":
            report.error("collectionAttrs.scripttype must be 'embed'")
        if not decoded.get("scriptgroovy"):
            report.error("collectionAttrs.scriptgroovy is empty")
    text = scripts.get("collect", ("groovy", ""))[1]
    if "generateTopology" not in text:
        report.warn("topology output is not produced via lm.topo generateTopology -- hand-written "
                    "topology output means inventing a format")
    check_vertex_keys(text, report)


# A vertex built from a list literal: eriPreProcessor([...], ...) or a wrapper such as eri([...]).
VERTEX_KEYS = re.compile(r"\b(?:eriPreProcessor|eri)\(\s*\[")


def check_vertex_keys(text: str, report: Report) -> None:
    # lm.topo joins a vertex's keys into one ID with '_', and the portal then matches only a
    # resource carrying ALL of them, not any one [portal, 2026-10-21]: a node vertex given a
    # cluster-scoped and an IP key left the node that carried only the IP key unmatched.
    for match in VERTEX_KEYS.finditer(text):
        depth, commas, i = 0, 0, match.end()
        while i < len(text):
            c = text[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                commas += 1
            i += 1
        if commas:
            report.warn(f"topology vertex built from {commas + 1} keys "
                        f"({text[match.start():i + 1]}): lm.topo joins them into one ID and the "
                        f"portal matches only a resource carrying all of them -- give a vertex "
                        f"one key unless every matching resource carries every key")


def check_shared_only(kind: str, module: dict, scripts: dict[str, tuple[str, str]],
                      report: Report) -> None:
    """Module types whose shapes come from LM's recipes, not from a portal import here."""
    report.warn(f"{kind}: only the shared checks run on this module type (secrets, snippets, "
                f"exits, discovery); its JSON shape is from LM's monitoring-recipes templates, "
                f"not a portal import -- confirm by importing and exporting it")
    if module.get("activeDiscovery"):
        check_active_discovery(module, report)
    if kind in ("diagnosticsource", "remediationsource") and not isinstance(
            module.get("script"), dict):
        report.error(f"{kind} script must be {{\"type\": ..., \"content\": ...}}")
    if kind == "logsource" and not module.get("resourceMapping"):
        report.warn("LogSource has no resourceMapping -- logs it imports are not tied to the "
                    "monitored resource (map system.deviceId)")
    if kind == "logsource":
        text = scripts.get("collect", ("groovy", ""))[1]
        if re.search(r"\b(return|exit)\s+[1-9]", text):
            report.warn("LogSource exits non-zero somewhere: that discards ALL output of the "
                        "run -- intended for failures only, never for partial results")


# ------------------------------------------------------------------------- main

def lint(path: Path) -> Report | None:
    report = Report(str(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        report.error(f"not valid JSON: {exc}")
        return report
    if not isinstance(raw, dict):
        return None
    module = normalise(raw, report)
    kind = kind_of(module)
    if kind is None:
        return None  # not a LogicModule (dashboard, fixture, etc.)
    scripts = scripts_of(module)
    check_common(module, report)
    check_scripts(module, scripts, kind, report)
    if kind in SHARED_CHECKS_ONLY:
        check_shared_only(kind, module, scripts, report)
    else:
        {"datasource": check_datasource, "propertysource": check_propertysource,
         "topologysource": check_topologysource}[kind](module, scripts, report)
    report.label = f"{path} [{kind}]"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint LogicModule JSON for silent failures.")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    args = parser.parse_args(argv)

    files: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        files.extend(sorted(path.rglob("*.json")) if path.is_dir() else [path])

    errors = warnings = linted = 0
    for file in files:
        report = lint(file)
        if report is None:
            continue
        linted += 1
        status = "FAIL" if report.errors else ("WARN" if report.warnings else "OK  ")
        print(f"{status}  {report.label}")
        for message in report.errors:
            print(f"  ERROR  {message}")
        for message in report.warnings:
            print(f"  WARN   {message}")
        errors += len(report.errors)
        warnings += len(report.warnings)

    print(f"\n{linted} module(s): {errors} error(s), {warnings} warning(s). "
          f"A clean lint is not a portal import: verify with Poll Now / Raw Data.")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
