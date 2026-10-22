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
  required** for import — don't fabricate them. **[portal]** Nor copy them, or `version`, or a
  datapoint's `originId`, from an export into a new module: the portal assigns those **[LM recipes]**.
- **Every metadata text field is capped at 4096 characters [portal]** — in practice
  `technicalNotes`, which grows as a module accumulates rationale and UNVERIFIED paragraphs. Past
  the cap, **Save** in My Module Toolbox fails with "Field value cannot contain more than 4096
  characters" and names no field (a TopologySource, 2026-10-21, at 4302). Scripts are not capped.
  `lm_lint_module.py` errors on it; trim the notes rather than split them.
- `displayedAs` uses spaces, `name` underscores. A trailing `-` on `displayedAs` (`Nginx-`) is LM's
  convention for multi-instance modules and shows up in dashboard references; avoid internal
  hyphens **[LM recipes]**.

Other module types (Log, Event, Config, Diagnostic, Remediation): `other-module-types.md`.
Provenance tag **[LM recipes]** = LogicMonitor's `monitoring-recipes` guidance @ `a7b45b6`, not yet
observed in a portal here.

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
  `UpTimeSeconds`, `UsedPercent`, `CapacityGB`, `Status`). Never rename a deployed datapoint —
  history doesn't follow, and dashboards drop the widget.
- **Status datapoints** — give the codes names so alerts read as words **[LM recipes]**:
  ```json
  "statusDisplayNames": [
    {"statusDisplayName": "Offline", "metricValue": "0", "operator": "EQ"},
    {"statusDisplayName": "Online",  "metricValue": "1", "operator": "EQ"}
  ],
  "alertBody": "Node ##INSTANCE## on ##HOST## is ##ALERTVALUEDISPLAYSTATUSNAME## (##VALUE##). ..."
  ```
  Objects, not strings; `metricValue` is a string. Without a mapping, state it in the description.
- Every datapoint should feed something — a graph, an alert, a dashboard. Description includes the
  unit and, for status codes, the mapping.

### Graphs and overview graphs **[LM recipes]**

`graphs` (per instance) and `overviewGraphs` (one line per instance, across all instances) share
one shape; overview datapoints add `aggregateMethod` (`sum` for counts, `average` for comparable
measures, `min`/`max` for bounds) and set `"aggregated": false` to keep a line per instance with
`legend` `##INSTANCE##`:

```json
{"name": "CPU by node", "title": "CPU by node", "verticalLabel": "%", "min": 0,
 "timeScale": "1day", "displayPriority": 1, "aggregated": false, "scale1024": false, "rigid": false,
 "lines": [{"datapointName": "CPUUsagePercent", "legend": "##INSTANCE##", "color": "blue",
            "type": "line", "isVirtual": false}],
 "datapoints": [{"name": "CPUUsagePercent", "datapointName": "CPUUsagePercent",
                 "aggregateMethod": "average", "consolidationFn": "average"}]}
```

Line `type`: `line`, `stack`, `area`. `datapointName` is the short datapoint `name`, never the
`##WILDVALUE##.` key. The Proxmox suite ships without module graphs (dashboards instead), so these
shapes are unverified here.

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
(LogicMonitor's own templates set `autoDeleteInstances: true`; this skill deliberately doesn't.)
With auto-delete off, instances discovery no longer reports stay, history intact **[portal]**;
retiring them is an operator's decision, made by hand once the object is confirmed gone and its
history no longer needed.

`discoveryInterval` takes only **`0m`** (on demand / property change only), **`15m`**, **`60m`**
or **`1440m`** — not `"1d"` **[LM recipes]**; `lm_lint_module.py` errors on anything else. Use 15m
for fast-changing sets (VMs), 1440m for slow ones (disks, certs). AD also re-runs when a resource or
its properties change, and on demand from the resource tree.

Instances an operator shouldn't monitor are best excluded by AD `filters` keyed on instance
properties discovery emits (`auto.*`), with `groupMethod` set to group by one of them. Ship
`"filters": []` / `"groupMethod": "none"` and document in `technicalNotes` which properties operators
can filter on. All filters must match (AND) — when instances go missing, check the filters first.

**Grouping instances by a property** **[portal export, 2026-10-22]**: `"groupMethod": "ilp"`
(Instance Level Property) with `"groupExpr": "auto.<key>"` — the stored name of a property
discovery emits, `auto.` prefix included, or nothing is grouped. Each discovery run regroups: an
instance whose property changes (a VM migrating to another host) moves to the new group and keeps
its history, since its wildvalue is unchanged. Use it for readability wherever a resource carries
many instances per parent object (guests, disks or services per host); a property with one instance
per value gains nothing. `lm_lint_module.py` errors on `ilp` without `groupExpr` and warns on a
name without `auto.`.

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
