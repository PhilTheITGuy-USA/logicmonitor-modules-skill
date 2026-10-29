#!/usr/bin/env python3
"""
Self-test for the skill's bundled scripts. Run before committing any change to them:

    python tests/test_tools.py

Known-good input: tests/fixtures/proxmox/ -- the Proxmox VE v2 suite's built exports
(github.com/PhilTheITGuy-USA/Proxmox-LogicModule.v2, 2026-10-27), all 19 modules imported and
collecting in a real portal, and its two dashboards as the portal exported them. They must
lint with zero errors. tests/fixtures/proxmox-v1/ keeps v1's addCategory_Proxmox_VE, a
known-good PropertySource on AppliesTo true(), a kind v2 does not have.

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
GOOD_V1 = ROOT / "tests" / "fixtures" / "proxmox-v1"
NODES = "Proxmox_VE_Cluster_Nodes.json"
TOPOLOGY = "Proxmox_VE_Cluster_Topology.json"
DASHBOARD = GOOD / "dashboards" / "Proxmox_VE.json"
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


def load(name: str, where: Path = GOOD) -> dict:
    return json.loads((where / name).read_text(encoding="utf-8"))


GATE = "if (pveHostProp('pve.api.insecure', 'false').toBoolean()) {"


def in_all_scripts(module: dict, old: str, new: str) -> dict:
    m = copy.deepcopy(module)
    m["collectionAttrs"]["content"] = m["collectionAttrs"]["content"].replace(old, new)
    if "activeDiscovery" in m:
        p = m["activeDiscovery"]["params"]
        p["content"] = p["content"].replace(old, new)
    return m


def module_mutations() -> dict[str, dict]:
    nodes = load(NODES)
    m = {}

    x = copy.deepcopy(nodes); x["datapoints"][0]["interpretExpr"] = x["datapoints"][0]["name"]
    m["batchscript datapoint without ##WILDVALUE##."] = x
    x = copy.deepcopy(nodes); x["activeDiscovery"]["deleteInactiveInstances"] = True
    m["AD deleteInactiveInstances on"] = x
    x = copy.deepcopy(nodes); x["useWildValueAsUniqueIdentifier"] = False
    m["useWildValueAsUniqueIdentifier off"] = x
    x = copy.deepcopy(nodes); x["datapoints"][0]["name"] = "In"; x["datapoints"][0]["interpretExpr"] = "##WILDVALUE##.In"
    m["reserved datapoint name 'In'"] = x
    m["secret property without .credential"] = in_all_scripts(nodes, "pve.token.credential", "pve.token")
    m["TLS bypass ungated"] = in_all_scripts(nodes, GATE, "if (true) {")
    m["TLS bypass property defaults true"] = in_all_scripts(nodes, "'pve.api.insecure', 'false'", "'pve.api.insecure', 'true'")
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] = x["collectionAttrs"]["content"].replace(GATE, "{")
    m["TLS bypass ungated in one script only"] = x

    ps = load("addCategory_Proxmox_VE.json", GOOD_V1)
    x = copy.deepcopy(ps)
    x["script"]["content"] = x["script"]["content"].replace(
        "System.err.println('Proxmox detection failed: ' + exception.message)",
        "println 'system.categories=ProxmoxVE'")
    m["true() PropertySource prints from catch"] = x
    x = copy.deepcopy(ps); x["collectionInterval"] = 1800
    m["plain PropertySource carries collectionInterval"] = x

    topo = load(TOPOLOGY)
    x = copy.deepcopy(topo); x["collectionAttrs"] = json.loads(x["collectionAttrs"])
    m["TopologySource collectionAttrs as object"] = x
    x = copy.deepcopy(topo); x["type"] = "9"
    m["TopologySource type as string"] = x
    # The portal refused to save a TopologySource whose technicalNotes ran to 4302
    # characters: "Field value cannot contain more than 4096 characters" [portal].
    x = copy.deepcopy(topo); x["technicalNotes"] = "x" * 4097
    m["technicalNotes over 4096 characters"] = x
    x = copy.deepcopy(nodes); x["description"] = "x" * 4097
    m["description over 4096 characters"] = x
    # Instance grouping by instance-level property is the pair groupMethod "ilp" +
    # groupExpr <property> [portal export, 2026-10-22]; ilp with no property groups nothing.
    x = copy.deepcopy(nodes); x["activeDiscovery"]["groupMethod"] = "ilp"
    m["groupMethod ilp without groupExpr"] = x
    # Graph lines refer to the graph's own datapoint aliases, which read module datapoints
    # [LM export, portal 2026-10-24]: a broken link at either layer draws nothing.
    x = copy.deepcopy(nodes); x["graphs"][0]["datapoints"][0]["datapointName"] = "NoSuchDatapoint"
    m["graph reads an undeclared datapoint"] = x
    x = copy.deepcopy(nodes); x["graphs"][0]["lines"][0]["datapointName"] = "NoSuchAlias"
    m["graph line names no graph datapoint"] = x
    # statusDisplayNames [LM recipes, portal 2026-10-27]: objects, metricValue a string.
    x = copy.deepcopy(nodes); x["datapoints"][0]["statusDisplayNames"] = [
        {"statusDisplayName": "Offline", "metricValue": 0, "operator": "EQ"}]
    m["status name metricValue as a number"] = x
    x = copy.deepcopy(nodes); x["datapoints"][0]["statusDisplayNames"] = ["Offline", "Online"]
    m["status names as plain strings"] = x
    return m


STATUS_NAMES = [{"statusDisplayName": "Offline", "metricValue": "0", "operator": "EQ"},
                {"statusDisplayName": "Online", "metricValue": "1", "operator": "EQ"}]


def dashboard_mutations() -> dict[str, dict]:
    tier1 = json.loads(DASHBOARD.read_text(encoding="utf-8"))

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
    x = copy.deepcopy(tier1); first(x, "cgraph")["displayClearedAlert"] = True
    m["noc-only portal key on a cgraph"] = x
    return m


def dashboard_portal_export_keys() -> dict[str, dict]:
    """Keys a release-246 portal writes into its own export: must pass cleanly."""
    tier1 = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    m = {}
    # The fixture is itself a release-246 export, so it carries these keys already; strip
    # them and put them back, so the case still proves they are accepted, not just present.
    x = copy.deepcopy(tier1)
    for widget in x["widgets"]:
        for key in ("isSupportCustomProperty", "supportCustomProperty", "displayClearedAlert"):
            widget["config"].pop(key, None)
    r = copy.deepcopy(x)
    m["the reference key set alone, without the portal's extra keys"] = r
    for widget in x["widgets"]:
        widget["config"]["isSupportCustomProperty"] = False
        widget["config"]["supportCustomProperty"] = False
        if widget["config"]["type"] == "noc":
            widget["config"]["displayClearedAlert"] = True
    m["isSupportCustomProperty, supportCustomProperty, noc displayClearedAlert"] = x
    return m


def dashboard_corpus_values() -> dict[str, dict]:
    """Values only LM's monitoring-recipes corpus vouches for: must pass, with a WARN."""
    tier1 = json.loads(DASHBOARD.read_text(encoding="utf-8"))

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
    nodes = load(NODES)
    groovy = {"type": "groovy", "content": "//!/lib-groovy/v4\nprintln 'x'\nreturn 0\n"}
    m = {}
    x = copy.deepcopy(nodes); x["activeDiscovery"]["discoveryInterval"] = "1d"
    m["discoveryInterval outside 0m/15m/60m/1440m"] = x
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] = x["collectionAttrs"]["content"].replace(
        "//!/lib-groovy/v4\n", "//!/lib-groovy/v4\n" + SNIPPET_BOOTSTRAP_UNBOUND, 1)
    m["snippets loaded without withBinding"] = x
    # Per loader: the fixture's own bound loader (lower-case `snippets`) with its binding cut.
    bound = "snippets.getLoader()).withBinding(getBinding())"
    assert bound in nodes["collectionAttrs"]["content"], "Nodes fixture no longer carries " + bound
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] = x["collectionAttrs"]["content"].replace(bound, "snippets.getLoader())")
    m["the script's own snippet loader with its binding removed"] = x
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
    nodes = load(NODES)
    groovy = {"type": "groovy", "content": "//!/lib-groovy/v4\nprintln 'x'\nreturn 0\n"}
    m = {}
    x = copy.deepcopy(nodes)
    x["collectionAttrs"]["content"] += "\ndef sshPass = hostProps.get('ssh.pass')\n"
    m["LM built-in credential property ssh.pass"] = x
    m["minimal DiagnosticSource"] = other_module(11, script=groovy)
    x = copy.deepcopy(load(TOPOLOGY)); x["technicalNotes"] = "x" * 4096
    m["technicalNotes of exactly 4096 characters"] = x
    x = copy.deepcopy(nodes)
    x["activeDiscovery"].update(groupMethod="ilp", groupExpr="auto.pve_node")
    m["instances grouped by auto.pve_node (ilp)"] = x
    x = copy.deepcopy(nodes); dp = x["datapoints"][0]
    dp["statusDisplayNames"] = copy.deepcopy(STATUS_NAMES)
    dp["alertBody"] += "\n\nStatus: ##ALERTVALUEDISPLAYSTATUSNAME## (##VALUE##)."
    m["status names, with the name in the alert body"] = x
    return m


ERI_CALL = "emitEri('proxmoxve', 1, keys, ert"


def module_warns() -> dict[str, tuple[dict, str]]:
    """Heuristic findings: each must pass (exit 0) with a WARN containing the given text."""
    eri = load("addERI_Proxmox_VE_Node.json")
    m = {}
    x = copy.deepcopy(eri)
    assert ERI_CALL in x["script"]["content"], "addERI fixture no longer carries " + ERI_CALL
    x["script"]["content"] = x["script"]["content"].replace(
        ERI_CALL, "emitEri('virt.x', 1, keys, 'VirtualMachineResource'")
    # The ERT comes from the highest-priority ERI entry across all categories [portal]:
    # at priority 1 the built-in net.l2 entry (priority 2) keeps PhysicalServer.
    m["ERI type override below priority 3"] = (x, "priority")
    # lm.topo joins a vertex's keys into one ID, and the portal then matches only a resource
    # carrying every one of them [portal, 2026-10-21].
    topo = load(TOPOLOGY)
    one_key = "eri([pveTopoNodeVertexKey(clusterName, nodeName, nodeIps[nodeName])])"
    attrs = json.loads(topo["collectionAttrs"])
    assert one_key in attrs["scriptgroovy"], "Topology fixture no longer carries " + one_key
    attrs["scriptgroovy"] = attrs["scriptgroovy"].replace(
        one_key, "eri([pveTopoNodeVertexKey(clusterName, nodeName, nodeIps[nodeName]), pveTopoKey(clusterName, nodeName)])")
    x = copy.deepcopy(topo); x["collectionAttrs"] = json.dumps(attrs)
    m["topology vertex built from two keys"] = (x, "carrying all")
    # AD properties are stored as auto.<key>; a bare name groups nothing.
    x = copy.deepcopy(load(NODES))
    x["activeDiscovery"].update(groupMethod="ilp", groupExpr="pve_node")
    m["ilp groupExpr without the auto. prefix"] = (x, "auto.pve_node")
    x = copy.deepcopy(load(NODES)); dp = x["datapoints"][0]
    dp["statusDisplayNames"] = copy.deepcopy(STATUS_NAMES)
    dp["alertBody"] = "Proxmox node ##INSTANCE## is offline."
    m["status names the alert body never uses"] = (x, "ALERTVALUEDISPLAYSTATUSNAME")
    # On exit 0 the portal shows no stderr [portal, 2026-10-24]: end-user text must not send
    # the reader to the collection log.
    x = copy.deepcopy(load("Proxmox_VE_Node_Replication.json"))
    dp = next(d for d in x["datapoints"] if d["name"] == "Failed")
    dp["alertBody"] += " The error text is in this module's collection task log."
    m["alert body pointing at the collection log"] = (x, "stderr")
    # Without graphs the portal plots every datapoint on one chart [portal, 2026-10-24].
    x = copy.deepcopy(load("Proxmox_VE_Cluster_Ceph.json")); del x["graphs"]
    m["DataSource with many datapoints and no graphs"] = (x, "no graphs")
    # gray beside green read as one colour in the portal's legend [portal, 2026-10-24].
    x = copy.deepcopy(load("Proxmox_VE_Cluster_StorageCapacity.json"))
    cap = next(g for g in x["graphs"] if g["title"] == "Capacity")
    next(l for l in cap["lines"] if l["color"] == "black")["color"] = "gray"
    m["graph colours gray and green together"] = (x, "read as")
    # A VMDatastore vertex carried by DataSource instances took no edges; StorageVolume did
    # [portal, 2026-10-28].
    x = copy.deepcopy(load("Proxmox_VE_Cluster_StorageCapacity.json"))
    x["activeDiscovery"]["params"]["content"] += "\ndef storeErt = 'VMDatastore'\n"
    m["instance vertex typed VMDatastore"] = (x, "VMDatastore")
    # Likewise a cluster vertex typed HyperVisorCluster; Cluster drew it [portal, 2026-10-28].
    x = copy.deepcopy(load("Proxmox_VE_Cluster_Status.json"))
    x["activeDiscovery"]["params"]["content"] += "\nraw['predef.externalResourceType'] = 'HyperVisorCluster'\n"
    m["instance vertex typed HyperVisorCluster"] = (x, "HyperVisorCluster")
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

    # Proxmox's PropertySource prints bare pve.* keys, which the portal stores as
    # auto.pve.* [portal]: the lint must name the real property (a warning, not an error).
    r = run(LINT + [str(GOOD / "Proxmox_VE_Info.json")])
    expect("lint names the auto. property a bare PropertySource key becomes",
           r.returncode == 0 and "'auto.pve.version'" in r.stdout, r.stdout)

    r = run(LINT + [str(GOOD / "addERI_Proxmox_VE_Node.json")])
    expect("lint does not warn on the known-good ERI PropertySource's priority",
           r.returncode == 0 and not any(l.strip().startswith("WARN") and "priority" in l
                                         for l in r.stdout.splitlines()), r.stdout)

    r = run(LINT + [str(GOOD / TOPOLOGY)])
    expect("lint does not warn on the known-good TopologySource's one-key vertices",
           r.returncode == 0 and "carrying all" not in r.stdout, r.stdout)

    r = run(LINT + good_modules)
    expect("lint does not warn on the known-good modules' end-user text",
           "collection log" not in r.stdout, r.stdout)

    r = run(LINT + [str(GOOD_V1 / "addCategory_Proxmox_VE.json")])
    expect("known-good true() PropertySource (v1) lints with 0 errors", r.returncode == 0, r.stdout)

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
        for name, dash in dashboard_portal_export_keys().items():
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(dash), encoding="utf-8")
            r = run(DASH + [str(path), "--modules", str(GOOD)])
            expect(f"dashboard check passes a portal export's keys: {name}",
                   r.returncode == 0, r.stdout)

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
