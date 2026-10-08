# LogicModule export JSON

Modules move between portals as a single `.json` via **Settings → LogicModules → My Module Toolbox →
Export / Add → Import from file** (XML is the legacy format). Field names below were taken from real
exports, and the shapes marked **[portal]** imported successfully.

**Principle: copy LM's types as well as its key names.** A TopologySource was refused with
`non empty field value required` (naming no field) because a nested block was an object where LM's
exports carry a JSON-encoded *string*, and integers were strings.

Run `scripts/lm_lint_module.py` (in this skill) on any module JSON before import; it enforces the
silent-failure rules on this page and in `collector-scripting.md`.

## Contents
1. DataSource
2. Datapoints
3. Active Discovery block
4. PropertySource (plain and ERI)
5. TopologySource
6. Generating exports from a definition

## 1. DataSource **[portal]**

```json
{
  "name": "Vendor_Product_Component",
  "displayedAs": "Vendor Product Component",
  "description": "One-line summary.",
  "appliesTo": "hasCategory(\"VendorProduct\")",
  "technicalNotes": "Per-module rationale shown in the portal; Exchange review expects it.",
  "searchKeywords": "vendor,product,component",
  "group": "Vendor Product",
  "collectionMethod": "batchscript",
  "collectionInterval": "5m",
  "collectionAttrs": { "type": "groovy", "content": "<assembled groovy>" },
  "multiInstance": true,
  "useWildValueAsUniqueIdentifier": true,
  "dataSourceType": 1,
  "type": 0,
  "datapoints": [ ... ],
  "activeDiscovery": { ... }
}
```

- `collectionMethod`: `script` or `batchscript` for Groovy.
- `collectionInterval`: string with unit (`"3m"`, `"5m"`, `"60m"`, `"720m"`).
- `useWildValueAsUniqueIdentifier: true` on every multiInstance module — this makes the wildvalue the
  instance identity. Nothing in the portal warns if it's missing.
- `registryMetadata` / `integrationMetadata` lineage blocks appear in published modules but are **not
  required** for import — don't fabricate them. **[portal]**

## 2. Datapoints

```json
{
  "name": "UsedPercent",
  "description": "Storage utilisation, percent.",
  "type": "gauge",
  "useValue": "output",
  "interpretMethod": "namevalue",
  "interpretExpr": "##WILDVALUE##.UsedPercent",
  "dataType": 7,
  "maxDigits": 4,
  "min": "", "max": "",
  "threshold": "> 80 90 95",
  "triggerInterval": 0, "clearInterval": 0,
  "noData": "Do not trigger an alert",
  "alertBody": "##INSTANCE## is ##VALUE##% full.\n\nThis started at ##START##, ##DURATION## ago."
}
```

- `interpretExpr`: `##WILDVALUE##.<name>` for batchscript, bare `<name>` for script. Validate this in
  your build against the collection method.
- Metric `type` (API enum on the datapoint object): `0 unknown, 1 counter, 2 gauge, 3 derive,
  5 status, 6 compute, 7 counter32, 8 counter64`. Exports used the strings `gauge`/`derive`.
- `dataType`: `1 boolean, 2 byte, 3 short, 4 int, 5 long, 6 float, 7 double, 8 ulong`. `7` (double) is
  a safe default — byte counts exceed int range and percentages need decimals.
- `derive` with `min: "0"` for cumulative counters.
- `threshold`: `"<op> warn error critical"`, e.g. `"> 90 95 98"`, `"< 1 1 1"` for an up/down flag.
  Empty string = no alert.
- `alertBody` tokens: `##INSTANCE##`, `##VALUE##`, `##START##`, `##DURATION##`, `##HOST##`,
  `##DATAPOINT##` **[LM convention]**. Say what's wrong *and* what it breaks.
- **Reserved names**: the portal refused a datapoint named `In` on import. **[portal]** Keep a
  reserved-name list in your build and add to it whenever the portal rejects one.
- Names: **PascalCase**, matching LM suites (`CPUUsagePercent`, `MemoryUsedMB`, `DataRateRxMB`,
  `UpTimeSeconds`, `UsedPercent`, `CapacityGB`, `Status`).

## 3. Active Discovery block **[portal]**

```json
"activeDiscovery": {
  "enabled": true,
  "discoveryMethod": "ad_script",
  "params": { "type": "groovy", "content": "<assembled AD groovy>" },
  "discoveryInterval": "60m",
  "deleteInactiveInstances": false,
  "autoDeleteInstances": false,
  "disableDiscoveredInstances": false,
  "groupMethod": "none",
  "filters": []
}
```

Never auto-delete: a collection that exits non-zero during an outage must not tear down history.
Use a short discovery interval for fast-changing sets (VMs) and 1440m for slow ones (disks, certs).

## 4. PropertySource **[LM export, portal]**

```json
{
  "name": "addCategory_VendorProduct",
  "group": "Vendor Product",
  "description": "...",
  "appliesTo": "true()",
  "technicalNotes": "...",
  "searchKeywords": "...",
  "script": { "type": "groovy", "content": "<groovy>" },
  "type": 5
}
```

ERI PropertySource adds exactly two fields, and the plain one must **omit** them:
```json
  "group": "ERI",
  "propertySourceType": 1,
  "collectionInterval": 1800
```
(From `addERI_VMware_VeloCloud` vs `addCategory_VMwareHorizonConnectionServer`.) Naming convention:
`addCategory_<Product>`, `addERI_<Product>`.

## 5. TopologySource **[portal]**

From `VMware_vCenter_Cluster_Topology` / `VMware_vSphere_VirtualMachine_Topology`:

```json
{
  "name": "Vendor_Product_Topology",
  "group": "Vendor Product",
  "description": "...",
  "appliesTo": "hasCategory(\"VendorProduct\")",
  "technicalNotes": "...",
  "searchKeywords": "...",
  "collectionMethod": "script",
  "collectionIntervalSec": 3600,
  "collectionAttrs": "{\"scriptgroovy\": \"<groovy>\", \"scripttype\": \"embed\", \"linuxscript\": \"\", \"linuxcmdline\": \"\", \"windowscmdline\": \"\", \"manualConnections\": \"\", \"windowsscript\": \"\", \"properties\": \"\"}",
  "type": 9
}
```

`collectionAttrs` is a JSON-**encoded string** carrying every slot, empty ones included;
`collectionIntervalSec` and `type` are integers.

## 6. Generating exports from a definition

Hand-editing export JSON invites drift. A small build step pays for itself:

- Keep a compact per-module definition (name, display name, appliesTo, method, interval, scripts,
  datapoints with only what deviates from defaults).
- The build supplies datapoint defaults, derives `interpretExpr` from name + method, concatenates the
  preamble onto each body, and emits importable JSON plus the assembled scripts.
- Cross-checks worth having (each caught a real defect):
  - every name the script prints is declared, and every declared one is printed (unless explicitly
    marked conditional) — find emitted names with a regex over literal calls like
    `emit(<id>, '<Name>'`, and require datapoint names to be **string literals** so the regex sees them;
  - `interpretExpr` matches the collection method;
  - `batchscript` ⇒ `multiInstance`; `multiInstance` ⇒ AD script;
  - reserved datapoint names;
  - bracket balance in assembled scripts;
  - required keys per module type, reported as validation errors naming the file.
- Wipe the output directory on each build so a renamed or removed script can't linger and be imported.
