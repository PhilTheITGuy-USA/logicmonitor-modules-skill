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
  `technicalNotes`, which grows as a module accumulates rationale and limitations. Past
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
- **An open alert outlives its datapoint** **[portal, 2026-10-29]**. An alert clears only when a
  new value falls below the threshold, so a datapoint that stops being printed keeps every alert
  it raised open indefinitely. Proxmox v2 moved LVM volume groups from `UsedPercent` (thresholded) to
  an unthresholded `AllocatedPercent`. Both volume groups' `UsedPercent` criticals stayed
  open for 15 hours of No Data on the fixed module, until the instances were deleted and Active
  Discovery recreated them (same wildvalue, new instance, history lost). When a release stops
  printing a thresholded datapoint for some instances, say in its upgrade notes that alerts
  already open stay open and how to clear them.
- **Status datapoints** — give the codes names so alerts read as words **[LM recipes; portal-confirmed
  2026-10-27]** (Proxmox v2: imported, shown on the datapoint, and an alert on a stopped guest
  read "Not running (0)"; only `"operator": "EQ"` has been seen):
  ```json
  "statusDisplayNames": [
    {"statusDisplayName": "Offline", "metricValue": "0", "operator": "EQ"},
    {"statusDisplayName": "Online",  "metricValue": "1", "operator": "EQ"}
  ],
  "alertBody": "Node ##INSTANCE## on ##HOST## is ##ALERTVALUEDISPLAYSTATUSNAME## (##VALUE##). ..."
  ```
  Objects, not strings; `metricValue` is a string. Without a mapping, state it in the description.
  Name a value only if the script prints it, and every value it prints. `lm_lint_module.py`
  checks the shape and warns when an alert body doesn't use the name.
- Every datapoint should feed something — a graph, an alert, a dashboard. Description includes the
  unit and, for status codes, the mapping.

### Graphs and overview graphs **[LM export, portal]**

**Always ship `graphs`.** A DataSource with none gets the portal's default view: every datapoint on
one chart, unreadable past four or five lines and meaningless when a 0/1 state shares an axis with
a byte count **[portal, 2026-10-24]**. Split the datapoints into graphs by subject (recipe below). The
shapes below are copied from LogicMonitor's own `VMware_ESXi_VirtualMachinePerformance` export (15
graphs, 7 overview graphs); a 9-graph DataSource built to them imported and rendered as intended.

`graphs` — one chart per instance, on the instance's Graphs tab:

```json
{"name": "Memory", "title": "Memory", "verticalLabel": "bytes", "min": 0,
 "rigid": false, "scale1024": true, "timeScale": "1day", "displayPriority": 2,
 "datapoints": [{"name": "Used",  "datapointName": "MemoryUsedBytes",     "consolidationFn": "average"},
                {"name": "Total", "datapointName": "MemoryCapacityBytes", "consolidationFn": "average"}],
 "lines": [{"datapointName": "Used",  "legend": "Used",  "color": "blue", "type": "line", "isVirtual": false},
           {"datapointName": "Total", "legend": "Total", "color": "gray", "type": "line", "isVirtual": false}]}
```

- **Two layers of names.** `datapoints[].datapointName` is the module datapoint; `datapoints[].name`
  is a graph-local alias, and `lines[].datapointName` refers to that **alias** (or to a virtual
  datapoint's name). LM's export mostly sets alias = datapoint name; keep them equal unless you need
  the same datapoint twice. Never the `##WILDVALUE##.` key.
- **Keys:** graph `name`, `title`, `verticalLabel`, `min`, `rigid`, `scale1024`, `timeScale`,
  `displayPriority`, `datapoints`, `lines`, optional `max` and `virtualDatapoints`. Line `datapointName`,
  `legend`, `color`, `type`, `isVirtual`. Graph datapoint `name`, `datapointName`, `consolidationFn`.
- **Values seen in LM's export:** `type` `line` / `area` / `stack`; `consolidationFn` `average` /
  `max`; `timeScale` `1day` / `1hour`; `color` `blue`, `green`, `orange`, `red`, `teal`, `fuchsia`,
  `navy`, `olive`, `maroon`, `aqua`, `lime`, `yellow`, `gray`, `black`, `orange2`, `red1`, and
  `silver` / `Auto` (overview graphs). Use nothing else.
- **`max` with `rigid: true`** pins the axis: `100` for a percentage, `1` for a 0/1 state. Without
  `max`, leave `rigid: false` so the axis follows the data.
- **`scale1024: true` only for raw bytes**, so the axis reads KiB/MiB/GiB. Leave it false for values
  already in decimal MB/GB, or the axis rescales a figure that is already scaled.
- **`displayPriority`** orders the graphs (1 first). Put the graph an operator looks at first — state,
  or utilisation — at the top.
- **Virtual datapoints** compute a line from others: `"virtualDatapoints": [{"name": "CPUPercent",
  "expr": "CpuUsage/100"}]` plus a line with that `datapointName` and `"isVirtual": true`. The `expr`
  operands are graph datapoint aliases.
- Colour by meaning, consistently across the suite, from colours that stay distinct (below).

`overviewGraphs` — one chart across all instances of the module on a resource (the "Top 10" view).
Same shape plus `"aggregated": false`, an `aggregateMethod` on each graph datapoint (`sum` in LM's
export; `average` for comparable measures **[LM recipes]**), and a line legend of `##INSTANCE##` with
`color` `Auto` so each instance gets its own colour.

**How to choose the graphs.** List the datapoints with their units, then group **[user preference,
portal-reviewed, Proxmox suite]**:
1. 0/1 states of the same object → one "State" graph, `max` 1, each flag its own colour.
2. The absolute figures about one subject → one graph in their unit: memory used and total; root
   disk used and size; a storage pool's used, free and size. Title it by the subject ("Memory").
3. **Each percentage → a graph of its own**, `max` 100 ("Memory Usage"). Never put a % line on an
   axis with bytes, MB or GB: one axis cannot read both, and the % line flattens against the floor.
4. Paired rates (read/write, rx/tx) → one graph. Load averages 1/5/15 → one graph.
5. Anything left over with its own unit (uptime, days to expiry, key size) → a graph of its own.
A datapoint that duplicates another in a different unit (`SizeBytes` beside `SizeGB`) need not be
plotted. Aim for ≤ 5 lines per graph.

**Give a percentage its weight through the instance name, not a graph line.** "72% used" means little
without the size it is a share of, but a size line cannot share the % graph: on a 0-100 axis it is
drawn off the scale, and an axis scaled to it flattens the % **[portal, 2026-10-24]**. Put the size
where every graph of the instance already shows it — the Active Discovery display name for objects
whose size is their identity (`local-lvm on node-a (1.8 TB)`, `osd.3 (4.0 TB)`), the description
for objects where it would be noise in a list (a guest's root disk, a node's root filesystem). The
display name also lands in dashboard legends that use `##INSTANCE##`. It costs nothing when discovery
already reads the size, and history survives because the wildvalue, not the name, is the identity;
the name follows a resize at the next discovery. Omit the size when the source reports none (an
unavailable store reports 0), rather than printing "0 GB".

**Colours must be told apart at a glance.** In the portal's legend and hover, `gray` beside `green`
and `navy` beside `blue` read as the same colour **[portal, 2026-10-24]**; the same goes for the
other near pairs (`teal`/`green`, `olive`/`green`, `lime`/`green`, `aqua`/`blue`, `maroon`/`red`,
`red1`/`red`, `orange2`/`orange`, `yellow`/`orange`, `silver`/`gray`, `black`/`navy`). Draw from a
short set of far-apart colours — `blue`, `orange`, `green`, `red`, `fuchsia`, `black` — and never
use one twice in a graph. That leaves meaning intact: main measure blue, good/free/up green,
failed/down red, warning orange, totals and capacities black, anything else fuchsia.

**`multiInstance` is fixed when a DataSource is created** **[portal, 2026-10-22]**. Importing a
module that flips it over an existing one fails with "Field value cannot be modified" — the portal
names no field. The only path is to delete the old module (and its instance history) and import
anew; dashboards that referenced it need re-importing too. Decide single- vs multi-instance before
first release, and give an upgrade note when it must change.

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
`collectionIntervalSec` and `type` are integers. **`collectionIntervalSec` must be 1800, 3600,
14400 or 43200** — the import refused 900 with "Invalid Duration offset, must be one of [1800,
3600, 14400, 43200]" **portal-confirmed** (2026-10-29), so a map changes at most every half hour.

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
  - required keys per module type, reported as validation errors naming the file;
  - every graph line names a declared datapoint, and every graph key, colour and line type is one
    LM's exports use (§2). Let the definition carry only `title`, `verticalLabel`, an optional
    `max` / `scale1024` and `lines` of datapoint + legend (+ colour); the build fills in the rest —
    `name` = `title`, `min` 0, `rigid` = has `max`, `timeScale` `1day`, `displayPriority` from
    the order, alias = datapoint name, `consolidationFn` `average`, `isVirtual` false.
- Wipe the output directory on each build so a renamed or removed script can't linger and be imported.
