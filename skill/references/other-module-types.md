# Other module types: Log, Event, Config, Diagnostic, Remediation

Everything here is **[LM recipes]** — from LogicMonitor's `monitoring-recipes` docs and templates
(github.com/logicmonitor/monitoring-recipes @ `a7b45b6`) — not yet imported or run in a portal by
this skill. `lm_lint_module.py` gives these types the shared checks only (secrets, snippets, exit
codes, discovery flags) and says so. Import one, export it again and diff before trusting a shape.

## Choosing a module type

| Collecting | Module | `type` | Import API type |
|---|---|---|---|
| Numeric time series | DataSource | `0` | `datasources` |
| Resource properties / categories / ERIs | PropertySource | `5` | `propertyrules` |
| Relationships | TopologySource | `9` | `topologysources` |
| Searchable logs | **LogSource** — preferred for anything log-like | `10` | `logsources` |
| Alert-only events, never searched | EventSource | `1` | `eventsources` |
| Config file contents, diffed | ConfigSource | `6` | `configsources` |
| Troubleshooting data, on demand or on alert | DiagnosticSource | `11` | `diagnosticsources` |
| A corrective action, on demand or on alert | RemediationSource | `12` | — (not in the import list in `api-and-tooling.md`) |

**LogSource vs EventSource**: prefer LogSource for new work — LM Logs can query, aggregate and alert
on it. EventSource data can only alert; use it only when there is no LM Logs or search is never
needed.

## Output contracts

All JSON output: build it with `groovy.json.JsonOutput.toJson(...)` (or `emit.events(...)`),
never by string concatenation.

| Module | Script prints | Exit code |
|---|---|---|
| LogSource (Script Logs) | `{"events": [{"message": "...", "timestamp": "...", <any fields>}]}` — `message` mandatory, events without one are discarded; `timestamp` optional (defaults to receive time) | **Non-zero discards the whole run's output.** Exit 0 whenever you have events to keep |
| EventSource (`scriptevent`) | `{"events": [{"happenedOn": "...", "severity": "warn\|error\|critical", "message": "...", "Source": "..."}]}` — first three required, `message` ≤ 2000 chars | non-zero = failure |
| ConfigSource, Script | the raw config text | non-zero = failure |
| ConfigSource, BatchScript | `{"data": {"<wildvalue>": {"configuration": "..."}}}` | non-zero = failure |
| DiagnosticSource | `{"data": "...", "format": "markdown"}` (`format` optional; plain text otherwise) | non-zero = failure |
| RemediationSource | as Diagnostic, plus `"remediationStatus": "true"` — a **string**, shown separately in the UI | non-zero = failure |

Limits: EventSource ≤ 50 events per run and ≤ 100 per Collector per minute; ConfigSource ≤ 3 MiB per
config. EventSource `happenedOn` accepts ISO-8601 (with or without zone), HTTP date, ctime and
common-logfile formats.

ConfigSource wildvalues obey the same rules as DataSource wildvalues — fold them, or the instance
reads No Data.

## JSON shapes (from LM's templates)

Common to all: `name`, `description`, `appliesTo`, `group`, `technicalNotes`, plus the
`searchKeywords`/`tags` the template carries. Don't copy `version`, `registryMetadata` or
`integrationMetadata` from an export into a new module.

- **DiagnosticSource / RemediationSource** — no datapoints, no `collectionAttrs`; one
  `"script": {"type": "groovy", "content": "..."}` like a PropertySource.
- **EventSource** — `"collectionMethod": "scriptevent"`, `"collectionAttrs": {"type": "groovy",
  "content": ...}`, plus alert behaviour: `severity`, `clearAfterAck` (bool), `clearAfterMin` (int),
  `doMapping` (bool), optional `alertSubject` / `alertBody`. Non-script EventSources (`wineventlog`,
  …) — clone a portal export, don't hand-author.
- **ConfigSource** — DataSource-like: `"dataSourceType": 2`, `collectionMethod`, `collectionInterval`,
  `collectionAttrs`, `multiInstance`, `activeDiscovery` (same rules: **auto-delete off**,
  `discoveryInterval` one of `0m`/`15m`/`60m`/`1440m`), `fileFormat` (`arbitrary`, `json`, …) and
  `configChecks`. Ship at least a retrieval check — `{"type": "fetch", "name": "RetrievalTest",
  "severity": "warn", "triggerInterval": 0, "description": ""}` — and an ignore rule for volatile
  lines (timestamps) so every poll isn't a "change". Schedules: 1h default; 4h, 8h, 1d.
- **LogSource** — `"type": 10`, `"collectionMethod": "script"`, an **integer** `collectionInterval`
  in the template (unit unconfirmed), `"collectionAttrs": {"type": "groovy", "content": ...,
  "filterOp": "AND", "resourceMappingOp": "AND"}`, `filters`, `logFields` and **`resourceMapping`** —
  keep the `system.deviceId` mapping (`{"key": "system.deviceId", "method": "literal", "value":
  "##system.deviceId##"}`) or imported logs aren't tied to the resource. The linter warns when it is
  missing.

## Diagnostic and Remediation runs

Triggered manually from a resource or by an alert's action chain. Only the alert-triggered run has
alert context:

```groovy
if (binding.hasVariable('alertProps') && alertProps.containsKey('alert.datapoint')) {
    def value = alertProps.get('alert.datapoint.value')?.toDouble()
    // targeted path
} else {
    // manual run: no alert context -- do something sensible, don't throw
}
```

Keys include `alert.datapoint`, `alert.datapoint.value`, `alert.severity`, `alert.instance`,
`alert.instance.wildvalue`, `alert.datasource`, `alert.id`, `alert.threshold`, `alert.resource.id`,
`alert.resource.name`, `alert.start.epoch`. Inline `##ALERT.DATAPOINT##`-style tokens also work (and
are the only way in PowerShell); they are empty on manual runs.

A RemediationSource changes the target. Make it idempotent, report what it did in `data`, and say
in `technicalNotes` exactly what it touches and what permission it needs.
