# Dashboard exports

A dashboard is a different resource from a LogicModule: import via **Dashboards → Add → From File**,
not My Module Toolbox.

**Use `scripts/lm_dashboards.py`** (in this skill) rather than writing widget JSON by hand: its
builders emit exactly the shapes below, and `python lm_dashboards.py check <dash.json> --modules
<modules>` enforces every rule on this page. This page is the reasoning behind that code. Schema source: `github.com/logicmonitor/dashboards` (Apache-2.0) —
`Virtualization/Hyper-V.json` for cgraph, dynamicTable, noc, alert; `Virtualization/Nutanix.json`
for bigNumber. Build dashboards from code with helpers that emit exactly those shapes, and validate.

## The failure mode **[portal]**

A widget carrying any key or value absent from the reference exports is **silently discarded** at
import. The portal shows one unspecific warning on first load — `Some widgets could not be created due
to incompatible version or configuration errors` — naming no widget, and the grid floats the rest
up to close the gap, so the dashboard looks complete. One dashboard ran missing 4 of 20 widgets for a
week. **Count widgets after import; better, export and count.**

## Allowed vocabularies (anything else was dropped or is unproven)

| Field | Allowed |
|---|---|
| widget `type` | `cgraph`, `dynamicTable`, `bigNumber`, `noc`, `alert` |
| `theme` | `newSolidDarkBlue`, `newBorderDarkBlue` |
| `timescale` | `8hour`, `12hour`, `day`, `2days`, `7days` |
| cgraph series `display.type` | `line`, `area`, `stack` |
| cgraph `graphInfo.topX` | `10`, `25` (20 was dropped) |
| dynamicTable `topX` | `25`, `-1` (= all rows; 50/100 dropped) |
| column `displayType` | `percent`, `raw` (`number` dropped) |
| column `minValue` / `maxValue` | always `0` / `100`, even on `raw` columns |
| column `colorThresholds` | always a list, `[]` when none — never `null` |
| threshold `level` | `2` warn, `3` error (only these seen) |
| dashboard `description` | ≤ 256 chars (portal truncates silently) |

### Second tier: in LM's corpus, not import-tested here **[LM recipes]**

LogicMonitor's `monitoring-recipes` dashboard skill (@ `a7b45b6`) publishes a schema built from its
own export corpus. It allows more than the table above: 16 more themes (`newBorderBlue`,
`newSolidGray`, `borderBlue`, … `newSimpleDarkBlue`), cgraph series type `column`, column
`displayType` `colorBar`, table `topX` `10`, and widget types `gauge`, `pieChart`, `text`,
`deviceSLA`, `gmap`. `lm_dashboards.py check` **warns** on these rather than failing — better
evidence than an invention, weaker than an import. When a portal keeps one (export after import and
`check` the export), move it into the first-tier tuples in `lm_dashboards.py`. Values a portal has
dropped (`topX` 20/50/100, `displayType` `number`) stay errors whatever any corpus says.

Cloud widgets (`billing`, `cloudRecommendation`, `viz`) carry portal-specific config: only ever
start from a portal export of one.

## Exact key sets per widget config

- **cgraph**: `description, displaySettings, graphInfo, interval, name, theme, timescale, type, version`
- **dynamicTable**: `columns, dataSourceFullName, description, displaySettings, forecast, interval, name, rows, sortOrder, theme, timescale, topX, type, version`
- **bigNumber**: `bigNumberInfo, description, displaySettings, interval, name, theme, timescale, type, version`
- **noc**: `ackChecked, description, displayColumn, displayCriticalAlert, displayErrorAlert, displaySettings, displayWarnAlert, interval, items, name, sdtChecked, sortBy, theme, timescale, type, version`
- **alert**: `description, displaySettings, filters, interval, name, theme, timescale, type, version`

Second tier (from LM's templates, **[LM recipes]**):
- **gauge**: `colorThresholds, dataPoint, description, displaySettings, displayType, displayUnit, interval, legend, maxValue, minValue, name, peakTimeRange, showPeak, theme, timescale, type, version` — `dataPoint` is a single object
- **pieChart**: `description, displaySettings, interval, name, pieChartInfo, theme, timescale, type, version` — `pieChartInfo` holds both `dataPoints[]` (module + scope) and `pieChartItems[]` (slices by `dataPointName`, `color`, `legend`)
- **text**: `content, description, displaySettings, interval, name, theme, timescale, type, version` — HTML in `content`
- **deviceSLA**: `bottomLabel, calculationMethod, colorThresholds, daysInWeek, description, displayPercentageBar, displaySettings, displayType, interval, metrics, name, periodInOneDay, theme, timescale, timezone, topX, type, unmonitoredTimeType, version` — `metrics[]` use `metric`, not `dataPointName`
- **gmap**: `ackChecked, description, displayCriticalAlert, displayErrorAlert, displaySettings, displayWarnAlert, interval, mapPoints, name, sdtChecked, theme, timescale, type, version`

### Field shapes that differ by widget **[LM recipes]**, all checked by `lm_dashboards.py`

| Widget | Names its module with | Scope fields |
|---|---|---|
| cgraph, bigNumber, pieChart, gauge, dynamicTable | `dataSourceFullName` = `"<displayedAs> (<name>)"` | cgraph: glob **objects** `{"isGlob": true, "value": "*"}`; the others: plain strings |
| noc | `dataSourceDisplayName` — a display-name glob (`Proxmox VE*`, `(A*\|B*)`), **never** `dataSourceFullName` | plain strings |
| dynamicTable rows | — | **`groupFullPath`**, not `deviceGroupFullPath` |

Alert widget: `displaySettings.sort` is the **string** `"-startEpoch"` — an object
(`{"columnKey": ..., "order": ...}`) imports and then crashes the widget at render with
`TypeError: n.replace is not a function`; `displaySettings.playSound` is an **object**, not a
boolean. Start alert widgets from the builder (or a known-good export), never from scratch.

Each widget is `{"position": {"col","sizex","row","sizey"}, "config": {...}}` on a 12-column grid.
Overlapping widgets render on top of each other without error — check the grid in your build.

Top level:
```json
{
  "santabaRelease": 169,
  "widgetTokens": [{"name": "defaultResourceGroup", "value": "*"}],
  "name": "...", "description": "...",
  "overwriteGroupFields": false,
  "widgetsConfigVersion": 2,
  "type": "dashboard",
  "widgets": [ ... ],
  "version": 2,
  "group": {"name": "...", "fullPath": "...", "description": ""}
}
```

## Referencing modules and instances

- A widget names a module as the plain string **`"<displayedAs> (<name>)"`** in
  `dataSourceFullName`. Nothing enforces it; a renamed module, display name or datapoint makes the
  widget vanish at import. Resolve every reference against your module definitions in the build.
- The portal resolves the reference against **its** copy of the module, so import (or re-import)
  modules **before** the dashboard. A dashboard imported one module version early lost exactly the
  widget naming the new datapoint. **[portal]**
- Globs: `instanceName {"isGlob": true, "value": "*"}`, `deviceDisplayName` `*`,
  `deviceGroupFullPath` `##defaultResourceGroup##`. In the alert widget's filters the group token is
  URL-encoded: `%23%23defaultResourceGroup%23%23*`.
- **Legend**: LM's VMware/Hyper-V dashboards use `##HOSTNAME##` because each hypervisor is its own
  resource. If your suite puts many objects on one resource as instances, legend on
  **`##INSTANCE##`** or every series gets the same label. **[portal]**
- A widget aimed at a datapoint that is only sometimes emitted renders **blank** rather than erroring.
  Put always-emitted datapoints on headline tiles.

## Scaling units in the widget **[LM recipes]**

If a module emits GB (see the units note in `collector-scripting.md` §6), a TB-scale graph labels
its axis `124.5K`. Fix it on the dashboard without touching the module:

- **cgraph**: add a virtual datapoint `{"name": "UsedBytes", "rpn": "UsedGB*1024*1024*1024",
  "display": {"color": "Auto", "legend": "##INSTANCE##", "type": "line", "option": "custom"}}` to
  `graphInfo.virtualDataPoints`, set `scaleUnit: 1024` and `verticalLabel: "bytes"`, and hide the
  raw series with `display.option: "none"`.
- **dynamicTable**: set the column's `rpn` to the same multiply and leave `unitLabel` empty so the
  table auto-formats bytes. Percent columns need nothing.

Not yet portal-tested here — export after import and check the series survived. A module that emits
canonical bytes needs neither, but then a raw `bigNumber` may show E-notation **[portal]**.

## Don't use the newer `table` widget for shareable dashboards

A current portal builds tables as `type: "table"` with `displaySettings.columnsV4`, and serialises rows
as resolved account-specific integers (`deviceId`, `instanceId`, `dataPointId`, `dataSourceId`). Such a
dashboard can't be shipped to another portal. Legacy `dynamicTable` still imports and is the only form
that expresses "every instance, wherever it lives" as globs.

## Workflow when you need a widget type not listed

Find it in a `logicmonitor/dashboards` export, copy its key set and every value verbatim, add it to
your validator's reference set, and confirm in a portal by exporting after import.
