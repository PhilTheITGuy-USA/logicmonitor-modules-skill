#!/usr/bin/env python3
"""
Self-test for the skill's bundled scripts. Run before committing any change to them:

    python tests/test_tools.py

Known-good input: tests/fixtures/proxmox/ -- the Proxmox VE suite's built exports
(github.com/PhilTheITGuy-USA/Proxmox-LogicModule @ fb8aa9b), all 17 modules and both
dashboards imported and collecting in a real portal. They must lint with zero errors.

Known-bad input: each mutation below reintroduces one defect that fails silently in a
portal. Every one must make the tools fail. A checker that cannot go red is worse than none.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill" / "scripts"
GOOD = ROOT / "tests" / "fixtures" / "proxmox"
BAD_INPUT = ROOT / "evals" / "inputs" / "Acme_Array_Volumes.json"
LINT = [sys.executable, str(SCRIPTS / "lm_lint_module.py")]
DASH = [sys.executable, str(SCRIPTS / "lm_dashboards.py"), "check"]

failures: list[str] = []


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def expect(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)
        if detail:
            print("      " + detail.strip().replace("\n", "\n      ")[:1500])


def load(name: str) -> dict:
    return json.loads((GOOD / name).read_text(encoding="utf-8"))


GATE = "if (pveHostProp('pve.api.insecure', 'false').toBoolean()) {"


def in_all_scripts(module: dict, old: str, new: str) -> dict:
    m = copy.deepcopy(module)
    m["collectionAttrs"]["content"] = m["collectionAttrs"]["content"].replace(old, new)
    if "activeDiscovery" in m:
        p = m["activeDiscovery"]["params"]
        p["content"] = p["content"].replace(old, new)
    return m


def module_mutations() -> dict[str, dict]:
    nodes = load("Proxmox_VE_Nodes.json")
    m = {}

    x = copy.deepcopy(nodes); x["datapoints"][0]["interpretExpr"] = x["datapoints"][0]["name"]
    m["batchscript datapoint without ##WILDVALUE##."] = x
    x = copy.deepcopy(nodes); x["activeDiscovery"]["deleteInactiveInstances"] = True
    m["AD deleteInactiveInstances on"] = x
    x = copy.deepcopy(nodes); x["useWildValueAsUniqueIdentifier"] = False
    m["useWildValueAsUniqueIdentifier off"] = x
    x = copy.deepcopy(nodes); x["datapoints"][0]["name"] = "In"; x["datapoints"][0]["interpretExpr"] = "##WILDVALUE##.In"
    m["reserved datapoint name 'In'"] = x
    m["secret property without .credential"] = in_all_scripts(nodes, "pve.api.token.credential", "pve.api.token")
    m["TLS bypass ungated"] = in_all_scripts(nodes, GATE, "if (true) {")
    m["TLS bypass property defaults true"] = in_all_scripts(nodes, "'pve.api.insecure', 'false'", "'pve.api.insecure', 'true'")
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] = x["collectionAttrs"]["content"].replace(GATE, "{")
    m["TLS bypass ungated in one script only"] = x

    ps = load("addCategory_Proxmox_VE.json")
    x = copy.deepcopy(ps)
    x["script"]["content"] = x["script"]["content"].replace(
        "System.err.println('Proxmox detection failed: ' + exception.message)",
        "println 'system.categories=ProxmoxVE'")
    m["true() PropertySource prints from catch"] = x
    x = copy.deepcopy(ps); x["collectionInterval"] = 1800
    m["plain PropertySource carries collectionInterval"] = x

    topo = load("Proxmox_VE_Topology.json")
    x = copy.deepcopy(topo); x["collectionAttrs"] = json.loads(x["collectionAttrs"])
    m["TopologySource collectionAttrs as object"] = x
    x = copy.deepcopy(topo); x["type"] = "9"
    m["TopologySource type as string"] = x
    return m


def dashboard_mutations() -> dict[str, dict]:
    tier1 = json.loads((GOOD / "dashboards" / "Proxmox_VE_Tier1.json").read_text(encoding="utf-8"))

    def first(d: dict, kind: str) -> dict:
        return next(w for w in d["widgets"] if w["config"]["type"] == kind)["config"]

    m = {}
    x = copy.deepcopy(tier1); first(x, "cgraph")["graphInfo"]["dataPoints"][0]["dataPointName"] = "CPUPercent"
    m["widget names a datapoint the module lacks"] = x
    x = copy.deepcopy(tier1); first(x, "cgraph")["graphInfo"]["dataPoints"][0]["dataSourceFullName"] = "Proxmox VE Nodes (Proxmox_VE_Node)"
    m["widget names a module that does not exist"] = x
    x = copy.deepcopy(tier1); first(x, "cgraph")["graphInfo"]["topX"] = 20
    m["cgraph topX 20"] = x
    x = copy.deepcopy(tier1); first(x, "dynamicTable")["topX"] = 50
    m["table topX 50"] = x
    x = copy.deepcopy(tier1); first(x, "dynamicTable")["columns"][0]["displayType"] = "number"
    m["column displayType number"] = x
    x = copy.deepcopy(tier1); first(x, "dynamicTable")["columns"][0]["colorThresholds"] = None
    m["column colorThresholds null"] = x
    x = copy.deepcopy(tier1); first(x, "dynamicTable")["columns"][0]["maxValue"] = 1000
    m["column bounds not 0..100"] = x
    x = copy.deepcopy(tier1); x["widgets"][1]["position"] = dict(x["widgets"][0]["position"])
    m["overlapping widgets"] = x
    x = copy.deepcopy(tier1); x["description"] = "x" * 300
    m["description over 256 chars"] = x
    x = copy.deepcopy(tier1); x["widgets"][0]["config"]["theme"] = "newBorderTeal"
    m["invented theme"] = x
    x = copy.deepcopy(tier1); x["widgets"][0]["config"]["id"] = 1
    m["extra widget key"] = x
    x = copy.deepcopy(tier1); first(x, "alert")["displaySettings"]["sort"] = {"columnKey": "alert-severity", "order": "descending"}
    m["alert sort as an object"] = x
    x = copy.deepcopy(tier1); first(x, "alert")["displaySettings"]["playSound"] = False
    m["alert playSound as a boolean"] = x
    x = copy.deepcopy(tier1); item = first(x, "noc")["items"][0]
    item["dataSourceFullName"] = item.pop("dataSourceDisplayName")
    m["noc item names dataSourceFullName"] = x
    x = copy.deepcopy(tier1); row = first(x, "dynamicTable")["rows"][0]
    row["deviceGroupFullPath"] = row.pop("groupFullPath")
    m["table row uses deviceGroupFullPath"] = x
    x = copy.deepcopy(tier1); first(x, "cgraph")["graphInfo"]["dataPoints"][0]["instanceName"] = "*"
    m["cgraph scope as a plain string"] = x
    return m


def dashboard_corpus_values() -> dict[str, dict]:
    """Values only LM's monitoring-recipes corpus vouches for: must pass, with a WARN."""
    tier1 = json.loads((GOOD / "dashboards" / "Proxmox_VE_Tier1.json").read_text(encoding="utf-8"))

    def first(d: dict, kind: str) -> dict:
        return next(w for w in d["widgets"] if w["config"]["type"] == kind)["config"]

    m = {}
    x = copy.deepcopy(tier1); x["widgets"][0]["config"]["theme"] = "newBorderBlue"
    m["theme newBorderBlue"] = x
    x = copy.deepcopy(tier1); first(x, "dynamicTable")["columns"][0]["displayType"] = "colorBar"
    m["column displayType colorBar"] = x
    x = copy.deepcopy(tier1); first(x, "dynamicTable")["topX"] = 10
    m["table topX 10"] = x
    return m


SNIPPET_BOOTSTRAP_UNBOUND = (
    "import com.santaba.agent.groovy.utils.GroovyScriptHelper as GSH\n"
    "import com.logicmonitor.mod.Snippets\n"
    "def modLoader = GSH.getInstance(GroovySystem.version).getScript('Snippets', Snippets.getLoader())\n"
    "def emit = modLoader.load('lm.emit', '0')\n")


def other_module(kind: int, **extra) -> dict:
    """A minimal module of a type the linter gives shared checks only."""
    m = {"name": "Vendor_Product_Thing", "displayedAs": "Vendor Product Thing",
         "description": "x", "technicalNotes": "x", "appliesTo": 'hasCategory("VendorProduct")',
         "type": kind}
    m.update(extra)
    return m


def other_module_mutations() -> dict[str, dict]:
    nodes = load("Proxmox_VE_Nodes.json")
    groovy = {"type": "groovy", "content": "//!/lib-groovy/v4\nprintln 'x'\nreturn 0\n"}
    m = {}
    x = copy.deepcopy(nodes); x["activeDiscovery"]["discoveryInterval"] = "1d"
    m["discoveryInterval outside 0m/15m/60m/1440m"] = x
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] = x["collectionAttrs"]["content"].replace(
        "//!/lib-groovy/v4\n", "//!/lib-groovy/v4\n" + SNIPPET_BOOTSTRAP_UNBOUND, 1)
    m["snippets loaded without withBinding"] = x
    x = copy.deepcopy(nodes)
    x["collectionAttrs"] = {"type": "powershell",
                            "content": "$secret = '##vendor.api.password##'\nWrite-Output 'x'\nexit 0\n"}
    m["PowerShell token for a secret without .credential"] = x
    m["DiagnosticSource script not an object"] = other_module(11, script="println 'x'")
    m["ConfigSource auto-deletes instances"] = other_module(
        6, collectionMethod="script", multiInstance=True, collectionAttrs=groovy,
        activeDiscovery={"discoveryMethod": "ad_script", "discoveryInterval": "60m",
                         "deleteInactiveInstances": False, "autoDeleteInstances": True,
                         "params": groovy})
    return m


def module_must_pass() -> dict[str, dict]:
    nodes = load("Proxmox_VE_Nodes.json")
    groovy = {"type": "groovy", "content": "//!/lib-groovy/v4\nprintln 'x'\nreturn 0\n"}
    m = {}
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] += "\ndef sshPass = hostProps.get('ssh.pass')\n"
    m["LM built-in credential property ssh.pass"] = x
    m["minimal DiagnosticSource"] = other_module(11, script=groovy)
    return m


ERI_CALL = "emitEri('proxmoxve', 1, keys, ert"


def module_warns() -> dict[str, tuple[dict, str]]:
    """Heuristic findings: each must pass (exit 0) with a WARN containing the given text."""
    eri = load("addERI_Proxmox_VE.json")
    m = {}
    x = copy.deepcopy(eri)
    assert ERI_CALL in x["script"]["content"], "addERI fixture no longer carries " + ERI_CALL
    x["script"]["content"] = x["script"]["content"].replace(
        ERI_CALL, "emitEri('virt.x', 1, keys, 'VirtualMachineResource'")
    # The ERT comes from the highest-priority ERI entry across all categories [portal]:
    # at priority 1 the built-in net.l2 entry (priority 2) keeps PhysicalServer.
    m["ERI type override below priority 3"] = (x, "priority")
    return m


def main() -> int:
    good_modules = sorted(str(p) for p in GOOD.glob("*.json"))
    r = run(LINT + good_modules)
    errors = [l for l in r.stdout.splitlines() if l.strip().startswith("ERROR")]
    expect(f"{len(good_modules)} known-good modules lint with 0 errors", r.returncode == 0 and not errors,
           "\n".join(errors) or r.stdout + r.stderr)

    good_dash = sorted(str(p) for p in (GOOD / "dashboards").glob("*.json"))
    r = run(DASH + good_dash + ["--modules", str(GOOD)])
    expect(f"{len(good_dash)} known-good dashboards pass with reference resolution", r.returncode == 0,
           r.stdout + r.stderr)

    # Proxmox's category PropertySource prints bare pve.* keys, which the portal stores as
    # auto.pve.* [portal]: the lint must name the real property (a warning, not an error).
    r = run(LINT + [str(GOOD / "addCategory_Proxmox_VE.json")])
    expect("lint names the auto. property a bare PropertySource key becomes",
           r.returncode == 0 and "'auto.pve.version'" in r.stdout, r.stdout)

    r = run(LINT + [str(GOOD / "addERI_Proxmox_VE.json")])
    expect("lint does not warn on the known-good ERI PropertySource's priority",
           r.returncode == 0 and not any(l.strip().startswith("WARN") and "priority" in l
                                         for l in r.stdout.splitlines()), r.stdout)

    r = run(LINT + [str(BAD_INPUT)])
    expect("planted-bug eval input fails lint", r.returncode == 1 and r.stdout.count("ERROR") >= 5, r.stdout)

    with tempfile.TemporaryDirectory() as tmp:
        for name, module in module_mutations().items():
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps(module), encoding="utf-8")
            r = run(LINT + [str(path)])
            expect(f"lint catches: {name}", r.returncode == 1, r.stdout)
        for name, module in other_module_mutations().items():
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps(module), encoding="utf-8")
            r = run(LINT + [str(path)])
            expect(f"lint catches: {name}", r.returncode == 1, r.stdout)
        for name, module in module_must_pass().items():
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps(module), encoding="utf-8")
            r = run(LINT + [str(path)])
            expect(f"lint accepts: {name}", r.returncode == 0, r.stdout)
        for name, (module, needle) in module_warns().items():
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps(module), encoding="utf-8")
            r = run(LINT + [str(path)])
            expect(f"lint warns but passes: {name}",
                   r.returncode == 0 and any(l.strip().startswith("WARN") and needle in l
                                             for l in r.stdout.splitlines()), r.stdout)
        for name, dash in dashboard_mutations().items():
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(dash), encoding="utf-8")
            r = run(DASH + [str(path), "--modules", str(GOOD)])
            expect(f"dashboard check catches: {name}", r.returncode == 1, r.stdout)
        for name, dash in dashboard_corpus_values().items():
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(dash), encoding="utf-8")
            r = run(DASH + [str(path), "--modules", str(GOOD)])
            expect(f"dashboard check warns but passes: {name}",
                   r.returncode == 0 and "WARN" in r.stdout, r.stdout)

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
