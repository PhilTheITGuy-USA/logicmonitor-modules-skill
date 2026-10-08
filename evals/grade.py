"""
Programmatic grader for the logicmonitor-modules evals.

    python evals/grade.py workspace/iteration-N            # content checks
    python evals/grade.py workspace/iteration-N --tools    # + lint/validator + contamination

Writes grading.json into every <eval>/<config>/run-*/ directory.
"""
import json, re, sys
from pathlib import Path

REF_KEYS = {
    "cgraph": {"description", "displaySettings", "graphInfo", "interval", "name", "theme", "timescale", "type", "version"},
    "dynamicTable": {"columns", "dataSourceFullName", "description", "displaySettings", "forecast", "interval", "name",
                     "rows", "sortOrder", "theme", "timescale", "topX", "type", "version"},
}


def load_json_files(out: Path):
    found = []
    for p in out.rglob("*.json"):
        try:
            found.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return found


def groovy_text(out: Path, module=None):
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in out.rglob("*.groovy"))
    if module:  # embedded scripts
        text += "\n" + json.dumps(module)
        ca = module.get("collectionAttrs")
        if isinstance(ca, dict):
            text += "\n" + ca.get("content", "")
        ad = (module.get("activeDiscovery") or {}).get("params") or {}
        text += "\n" + ad.get("content", "")
    return text


def find_module(out: Path):
    for p, d in load_json_files(out):
        if isinstance(d, dict) and "datapoints" in d:
            return d
        if isinstance(d, dict) and "dataPoints" in d:  # REST API DataSource model -> normalise
            adc = d.get("autoDiscoveryConfig") or {}
            return {
                "collectionMethod": d.get("collectMethod"), "multiInstance": d.get("hasMultiInstances"),
                "useWildValueAsUniqueIdentifier": d.get("useWildValueAsUUID"),
                "datapoints": [{"name": dp.get("name"), "interpretExpr": dp.get("postProcessorParam")} for dp in d["dataPoints"]],
                "activeDiscovery": {"deleteInactiveInstances": adc.get("deleteInactiveInstance"), "autoDeleteInstances": False},
                "_raw": d,
            }
    return None


def chk(text, passed, evidence):
    return {"text": text, "passed": bool(passed), "evidence": evidence}


def grade_datasource(out: Path):
    m = find_module(out)
    if not m:
        return [chk("Module JSON with datapoints exists and parses", False, "no parseable module JSON")]
    g = groovy_text(out, m)
    dps = m.get("datapoints", [])
    exprs = [dp.get("interpretExpr", "") for dp in dps]
    ad = m.get("activeDiscovery") or {}
    return [
        chk("Module JSON with datapoints exists and parses", True, f"{len(dps)} datapoints"),
        chk("batchscript + multiInstance", m.get("collectionMethod") == "batchscript" and m.get("multiInstance") is True,
            f"method={m.get('collectionMethod')} multi={m.get('multiInstance')}"),
        chk("Every datapoint interpretExpr is ##WILDVALUE##.<name>",
            dps and all(e == "##WILDVALUE##." + dp.get("name") for e, dp in zip(exprs, dps)), str(exprs)),
        chk("useWildValueAsUniqueIdentifier is true", m.get("useWildValueAsUniqueIdentifier") is True,
            str(m.get("useWildValueAsUniqueIdentifier"))),
        chk("AD never auto-deletes instances",
            ad and not ad.get("deleteInactiveInstances") and not ad.get("autoDeleteInstances"),
            f"deleteInactive={ad.get('deleteInactiveInstances')} autoDelete={ad.get('autoDeleteInstances')}"),
        chk("Credential read from a property ending in .credential",
            re.search(r"['\"][\w.]+\.credential['\"]", g) is not None,
            (re.search(r"['\"][\w.]+\.credential['\"]", g) or [None])[0] if re.search(r"['\"][\w.]+\.credential['\"]", g) else "none"),
        chk("Scripts return 2 on failure", "return 2" in g, "found" if "return 2" in g else "missing"),
        chk("Wildvalue sanitised with a character-class replace",
            re.search(r"replaceAll\(\s*['\"/]\[\^", g) is not None, "found" if re.search(r"replaceAll\(\s*['\"/]\[\^", g) else "missing"),
        chk("Groovy 4 header present", "//!/lib-groovy/v4" in g, "found" if "//!/lib-groovy/v4" in g else "missing"),
    ]


def grade_diagnosis(out: Path):
    m = find_module(out)
    expl = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in out.rglob("*.md"))
    if not m:
        return [chk("Fixed module JSON exists and parses", False, "none")]
    g = groovy_text(out, m)
    dps = m.get("datapoints", [])
    ad = m.get("activeDiscovery") or {}
    return [
        chk("Fixed JSON parses", True, ""),
        chk("All interpretExpr fixed to ##WILDVALUE##.<name>",
            dps and all(dp.get("interpretExpr") == "##WILDVALUE##." + dp["name"] for dp in dps),
            str([dp.get("interpretExpr") for dp in dps])),
        chk("Explanation names ##WILDVALUE## as the root cause", "##WILDVALUE##" in expl, "mentioned" if "##WILDVALUE##" in expl else "not mentioned"),
        chk("useWildValueAsUniqueIdentifier set true", m.get("useWildValueAsUniqueIdentifier") is True, str(m.get("useWildValueAsUniqueIdentifier"))),
        chk("Auto-delete turned off", not ad.get("deleteInactiveInstances") and not ad.get("autoDeleteInstances"),
            f"{ad.get('deleteInactiveInstances')}/{ad.get('autoDeleteInstances')}"),
        chk("State mapped to a number rather than printed raw",
            re.search(r"\?\s*1\s*:\s*0|\[\s*['\"]?\w+['\"]?\s*:\s*\d|return\s+1\b", g) is not None,
            "mapping found" if re.search(r"\?\s*1\s*:\s*0|\[\s*['\"]?\w+['\"]?\s*:\s*\d|return\s+1\b", g) else "no mapping found"),
        chk("Wildvalue sanitised in scripts", re.search(r"replaceAll\(\s*['\"/]\[\^", g) is not None,
            "found" if re.search(r"replaceAll\(\s*['\"/]\[\^", g) else "missing"),
        chk("Collect script returns 2 on failure", "return 2" in g, "found" if "return 2" in g else "missing"),
    ]


def grade_dashboard(out: Path):
    dash = None
    for p, d in load_json_files(out):
        if isinstance(d, dict) and "widgets" in d:
            dash = d
    if not dash:
        return [chk("Dashboard JSON with widgets parses", False, "none")]
    widgets = [w.get("config", w) for w in dash["widgets"]]
    types = [w.get("type") for w in widgets]
    tables = [w for w in widgets if w.get("type") == "dynamicTable"]
    graphs = [w for w in widgets if w.get("type") == "cgraph"]
    refs = set()
    for w in tables:
        refs.add(w.get("dataSourceFullName"))
    for w in graphs:
        for s in (w.get("graphInfo") or {}).get("dataPoints", []):
            refs.add(s.get("dataSourceFullName"))
    legends = [s.get("display", {}).get("legend") for w in graphs for s in (w.get("graphInfo") or {}).get("dataPoints", [])
               if s.get("display", {}).get("legend")]
    legends += [l.get("legend") for w in graphs for l in (w.get("graphInfo") or {}).get("lines", [])]
    cols = [c for w in tables for c in w.get("columns", [])]
    keysets_ok = all(set(w) == REF_KEYS[w["type"]] for w in tables + graphs)
    return [
        chk("Dashboard JSON with widgets parses", True, str(types)),
        chk("Uses legacy dynamicTable (not newer 'table') and cgraph", tables and graphs and "table" not in types, str(types)),
        chk("Module references use '<displayedAs> (<name>)'",
            refs and refs <= {"TrueNAS Pools (TrueNAS_Pools)", "TrueNAS Nodes (TrueNAS_Nodes)"}, str(refs)),
        chk("Graph legend is ##INSTANCE##", legends and all(l == "##INSTANCE##" for l in legends), str(legends)),
        chk("topX values within reference vocabulary",
            all((w.get("graphInfo") or {}).get("topX") in (10, 25) for w in graphs) and all(w.get("topX") in (25, -1) for w in tables),
            f"graphs={[ (w.get('graphInfo') or {}).get('topX') for w in graphs]} tables={[w.get('topX') for w in tables]}"),
        chk("Columns: displayType percent/raw, bounds 0/100, colorThresholds list",
            cols and all(c.get("displayType") in ("percent", "raw") and c.get("minValue") == 0 and c.get("maxValue") == 100
                         and isinstance(c.get("colorThresholds"), list) for c in cols),
            str([(c.get("displayType"), c.get("minValue"), c.get("maxValue"), type(c.get("colorThresholds")).__name__) for c in cols])),
        chk("Widget config key sets match LM reference exports exactly", keysets_ok,
            str([sorted(set(w) ^ REF_KEYS[w["type"]]) for w in tables + graphs])),
        chk("theme and timescale within reference vocabulary",
            all(w.get("theme") in ("newSolidDarkBlue", "newBorderDarkBlue") and w.get("timescale") in ("8hour", "12hour", "day", "2days", "7days") for w in tables + graphs),
            str([(w.get("theme"), w.get("timescale")) for w in tables + graphs])),
        chk("Description <= 256 chars", len(dash.get("description", "")) <= 256, str(len(dash.get("description", "")))),
    ]


GRADERS = {"truenas-batchscript-datasource": grade_datasource, "nodata-diagnosis": grade_diagnosis,
           "truenas-dashboard": grade_dashboard}

it = Path(sys.argv[1])
for ev in sorted(it.glob("eval-*")):
    name = ev.name[len("eval-"):]
    for run in sorted(ev.glob("*/run-*")):
        results = GRADERS[name](run / "outputs")
        passed = sum(r["passed"] for r in results)
        (run / "grading.json").write_text(json.dumps({
            "expectations": results,
            "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results),
                        "pass_rate": round(passed / len(results), 3)}}, indent=2))
        print(f"{name:34} {run.parent.name:14} {passed}/{len(results)}")


# ---- iteration 2+: tool-backed checks (applied to both configurations) ----
import subprocess
SCRIPTS = Path(__file__).resolve().parent.parent / "skill" / "scripts"
INPUTS = Path(__file__).resolve().parent / "inputs"


def lint_check(out: Path):
    files = [str(p) for p in out.rglob("*.json")]
    if not files:
        return chk("Module JSON lints with 0 errors (lm_lint_module.py)", False, "no json")
    r = subprocess.run([sys.executable, str(SCRIPTS / "lm_lint_module.py"), *files],
                       capture_output=True, text=True)
    errs = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("ERROR")]
    return chk("Module JSON lints with 0 errors (lm_lint_module.py)", not errs,
               "; ".join(errs)[:400] or "0 errors")


def dash_check(out: Path):
    dashes = [str(p) for p, d in load_json_files(out) if isinstance(d, dict) and "widgets" in d]
    if not dashes:
        return chk("Dashboard passes lm_dashboards.py check with module references", False, "none")
    r = subprocess.run([sys.executable, str(SCRIPTS / "lm_dashboards.py"), "check", *dashes,
                        "--modules", str(INPUTS / "modules_for_dashboard.json")],
                       capture_output=True, text=True)
    return chk("Dashboard passes lm_dashboards.py check with module references", r.returncode == 0,
               r.stdout.strip()[:400])


def contamination(run: Path):
    t = run / "transcript.jsonl"
    if run.parent.name != "without_skill" or not t.exists():
        return None
    # The session's init event lists installed slash commands; that is not use. Look elsewhere.
    hit = any("logicmonitor-modules" in line and '"subtype": "init"' not in line
              and '"subtype":"init"' not in line
              for line in t.read_text(encoding="utf-8", errors="ignore").splitlines())
    return chk("Baseline never touched the skill (contamination check)", not hit,
               "skill path appears in transcript" if hit else "clean")


if len(sys.argv) > 2 and sys.argv[2] == "--tools":
    for ev in sorted(it.glob("eval-*")):
        name = ev.name[len("eval-"):]
        for run in sorted(ev.glob("*/run-*")):
            g = json.loads((run / "grading.json").read_text())
            extra = [lint_check(run / "outputs") if name != "truenas-dashboard" else dash_check(run / "outputs")]
            c = contamination(run)
            if c:
                extra.append(c)
            g["expectations"] += extra
            p = sum(e["passed"] for e in g["expectations"])
            g["summary"] = {"passed": p, "failed": len(g["expectations"]) - p,
                            "total": len(g["expectations"]), "pass_rate": round(p / len(g["expectations"]), 3)}
            (run / "grading.json").write_text(json.dumps(g, indent=2))
            print(f"  +tools {name:30} {run.parent.name:14} {p}/{len(g['expectations'])}")
