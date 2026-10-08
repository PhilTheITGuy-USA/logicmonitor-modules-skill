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
    x = copy.deepcopy(tier1); x["widgets"][0]["config"]["theme"] = "newBorderBlue"
    m["invented theme"] = x
    x = copy.deepcopy(tier1); x["widgets"][0]["config"]["id"] = 1
    m["extra widget key"] = x
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

    r = run(LINT + [str(BAD_INPUT)])
    expect("planted-bug eval input fails lint", r.returncode == 1 and r.stdout.count("ERROR") >= 5, r.stdout)

    with tempfile.TemporaryDirectory() as tmp:
        for name, module in module_mutations().items():
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps(module), encoding="utf-8")
            r = run(LINT + [str(path)])
            expect(f"lint catches: {name}", r.returncode == 1, r.stdout)
        for name, dash in dashboard_mutations().items():
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(dash), encoding="utf-8")
            r = run(DASH + [str(path), "--modules", str(GOOD)])
            expect(f"dashboard check catches: {name}", r.returncode == 1, r.stdout)

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
