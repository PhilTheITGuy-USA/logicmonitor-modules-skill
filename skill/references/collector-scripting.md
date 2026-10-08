# Collector Groovy scripting contract

Provenance tags: **[portal]** confirmed in a real portal/Collector; **[LM export]** read from
LogicMonitor's published modules or repos; **[inferred]** reasoned, not yet observed.

## Contents
1. Runtime
2. Bindings and property lookup
3. Script skeleton and exit codes
4. Active Discovery output
5. Collection output: Script vs BatchScript
6. Values and metric types
7. HTTP, TLS, auth
8. PropertySource output
9. Topology and ERI via `lm.topo` snippets
10. Sharing code between modules

## 1. Runtime

- Collectors run **Groovy 4** (test in `groovy:4-jdk17`). Pin with a first line of
  `//!/lib-groovy/v4`. **[LM export]**
- Groovy 2 → 4 migration: `List.push`/`pop` removed (use `add` / `remove(size-1)`); `XmlSlurper` /
  `XmlParser` moved to `groovy.xml.*`; `LazyMap` to `org.apache.groovy.json.internal.*`. LogicMonitor
  publishes `logicmonitor/GroovyRemix` to automate the migration.
- **No include mechanism.** Every script embedded in a module must be self-contained. To share
  helpers, keep a preamble file and concatenate it onto each body at build time.

## 2. Bindings and property lookup

| Binding | Contains | Available in |
|---|---|---|
| `hostProps` | resource-level properties (`system.hostname`, custom props, `*.credential`) | AD, collection, PropertySource |
| `taskProps` | instance-level properties during per-instance collection | Script collection only |
| `instanceProps` | instance properties in some contexts | varies |

- Instance properties set by Active Discovery may appear **with or without the `auto.` prefix**. Read
  them through one helper that tries `taskProps[key]`, `taskProps['auto.'+key]`,
  `instanceProps[key]`, `instanceProps['auto.'+key]`, guarded by `binding.hasVariable(...)` because
  neither exists during AD. Reading an instance property from `hostProps` returns null and fails at
  runtime. **[portal]**
- Treat blank strings as unset (`value.toString().trim().isEmpty()`).
- `##WILDVALUE##` substitution is a datapoint/post-processor feature; inside a per-instance Script
  read the instance's own properties rather than relying on token substitution in the script body.

Credential properties: name them `<vendor>.<thing>.credential` so the portal masks them. **[LM docs /
portal]** Do not add a compatibility fallback that silently reads an old non-masked name — but do
document a rename prominently, because a resource carrying only the old name goes quiet.

## 3. Script skeleton and exit codes

```groovy
//!/lib-groovy/v4
// ... preamble: property reads, config validation sets configError instead of throwing ...

if (configError) {
    System.err.println(configError)
    return 2                     // DataSource. A PropertySource returns 0 silently instead.
}

try {
    def rows = apiGet('/bulk/endpoint') ?: []
    rows.each { row -> emit(row.id, 'Status', row.state == 'up' ? 1 : 0) }

    // Optional surface that may legitimately be absent: its own try, omit its datapoints.
    try { emit(null, 'HAEnabled', apiGet('/ha/status') ? 1 : 0) }
    catch (Exception ignored) { }

    return 0
} catch (Exception e) {
    System.err.println('Collection failed: ' + e.message)
    return 2
}
```

- `return 0` success; `return 2` any API/config failure, reason on `System.err`. Non-zero makes LM
  keep existing instances through a transient outage. Never "handle" an outage with zeros.
- **Fan-out over sub-objects** (one call per node/host): filter to reachable ones first, then a
  per-item `try` that logs to `System.err` and continues, so one dead member doesn't blank the rest.
- A fourth legitimate shape: **nothing to report** (feature not installed) → print nothing,
  `return 0`, and say so on stderr for AD.

## 4. Active Discovery output

One instance per line:

```
wildvalue##displayName##description####auto.key=value&auto.key2=value2
```

- Two `#` between fields, **four** before the property list. Minimal form: `wildvalue##displayName`.
- **Wildvalue**: no spaces, `:`, `=`, `\`, `#`. Fold to `[A-Za-z0-9_-]` to also avoid `.` (it splits
  instance from datapoint in BatchScript output). Build from the target's own stable id.
- **Display name / description** may contain spaces and punctuation; strip `#`.
- **Property values**: URL-encode (`URLEncoder.encode(v, 'UTF-8')`) — LM's own reference AD scripts do
  this. **Never emit a blank value** — it logs an error on the discovery task. Prefix keys `auto.`.
- All instance properties on one resource share a **~49,000-character budget**.
- An under-privileged credential against a "filtered by permission" endpoint returns an empty list,
  not an error. Detect "returned nothing" and say on stderr that it may be permissions.
- Filter out things that can never be healthy (templates, disabled placeholders) at discovery, not
  at alert time — otherwise they alert as permanently down.

## 5. Collection output: Script vs BatchScript

| Method | Runs | Output line | Datapoint `interpretExpr` |
|---|---|---|---|
| `script` single-instance | once per resource | `Datapoint=value` | `Datapoint` |
| `script` multiInstance | once **per instance** | `Datapoint=value` | `Datapoint` |
| `batchscript` | once per resource, all instances | `wildvalue.Datapoint=value` | `##WILDVALUE##.Datapoint` |

Datapoints use `useValue: "output"`, `interpretMethod: "namevalue"`. **[portal]** — the
`##WILDVALUE##.` prefix was the fix for a suite where every batchscript datapoint read No Data while
Test Collection Script showed correct output.

- `batchscript` requires `multiInstance: true` and an Active Discovery script.
- The wildvalue in collection output must be byte-identical to the one AD emitted — use the same fold
  function in both. Assert both directions in tests: every discovered instance collects, nothing
  collects for an undiscovered id.
- Prefer BatchScript whenever one call returns every instance. Per-instance Script multiplies API
  calls by instance count.

## 6. Values and metric types

- Every value must match `^-?\d+(\.\d+)?([eE][-+]?\d+)?$`. Convert string-typed numbers
  (`toString().toDouble()`), map states to integers (`running` → 1).
- Cumulative counters from the source (bytes since boot/start) → datapoint `type: derive` with
  `min: 0` so a counter reset is dropped rather than graphing a negative spike. Point-in-time
  readings → `gauge`. Declaring a counter as gauge graphs an ever-climbing line.
- LM renders large raw numbers in E-notation on dashboards (`5.001E11`). Emit capacity in GB and
  rates in MB (decide decimal vs binary once and say so in the description).
- Round to a sane precision (`Math.round(v * 100) / 100`).

## 7. HTTP, TLS, auth

- LM's reference modules use `com.santaba.agent.groovyapi.http.HTTP` (`HTTP.open(host, port)`,
  `.get(url)`, `.getStatusCode()`, `.getResponseBody()`, `.close()`). It is **Collector-only**:
  scripts using it cannot compile or run anywhere else. Plain `HttpURLConnection` keeps scripts
  testable off-Collector and gives per-request timeout and TLS control. Choose deliberately and
  document the choice; for Exchange either is acceptable **[inferred]**.
- Set connect and read timeouts from a property with a default (e.g. 10000 ms).
- Call out 401/403 distinctly in the error — "credential rejected / missing ACL" is the most common
  misconfiguration and otherwise looks like an empty result.
- A TLS bypass for self-signed lab targets must be **opt-in via a property and default off**.
- Use `groovy.json.JsonSlurper` to parse; unwrap any response envelope in one helper.

## 8. PropertySource output

- Prints `key=value` lines; each becomes a resource property. `system.categories=Foo` *adds* a
  category (this is how a suite becomes self-applying).
- A PropertySource on `AppliesTo: true()` must **return 0 and print nothing** when the host isn't the
  target or credentials are missing — on every error path too. Use the cheapest authenticated
  endpoint that proves identity (a `/version`-style call).
- Publish facts other modules' AppliesTo can key on (e.g. `vendor.version`, `vendor.clustered`) so
  they don't need their own probe.

## 9. Topology and ERI via `lm.topo` snippets

LogicMonitor's own TopologySources and ERI PropertySources produce their output through Collector
snippets. The formats are not documented well enough to hand-write — **don't**. **[LM export]**

```groovy
import com.logicmonitor.mod.Snippets
import com.santaba.agent.groovy.utils.GroovyScriptHelper as GSH

def modLoader = GSH.getInstance(GroovySystem.version)
    .getScript('Snippets', Snippets.getLoader()).withBinding(getBinding())
def lmTopo     = modLoader.load('lm.topo', '0')
def lmTopoData = modLoader.load('lm.data.topo', '1').create()

def keyNamespace = hostProps.get('topo.namespace') ? hostProps.get(hostProps.get('topo.namespace')) : ''
def keyBlacklist = (hostProps.get('topo.blacklist') ?: '').tokenize(',')
def eri = { List keys -> lmTopo.eriPreProcessor(keys, lmTopoData.blockedKeys, keyNamespace, keyBlacklist) }
```

TopologySource:
```groovy
def edges = []
lmTopo.registerEdge('Compute', parentEri, childEri, edges)   // edge type e.g. 'Cluster', 'Compute'
println lmTopo.generateTopology(edges, keyNamespace, keyBlacklist, null, false)
```
`lmTopo.isMac(mac, lmTopoData.blockedKeys, false)` validates a MAC before using it as a key.

ERI PropertySource:
```groovy
import org.json.JSONArray
def eriArray = new JSONArray()
lmTopo.emitEri('<category>', 1, keys, 'PhysicalServer', eriArray)   // category, priority, keys, ERT
lmTopo.printEriArray(eriArray, keyNamespace, keyBlacklist)
```

Behaviour **[portal]**:
- The map draws **only vertices whose key matches a monitored resource's ERI**. A child that is
  emitted but matches nothing simply isn't drawn. Use Test Script on the TopologySource to separate
  "not emitted" from "not drawn".
- Monitored hosts typically get MAC-keyed ERIs from SNMP discovery (`predef.externalResourceID`). A VM
  that doesn't answer SNMP has no MAC ERI and won't match.
- When the source API exposes no hardware id for an object, synthesise a key with one shared helper
  and stamp the same key via an ERI PropertySource on that object's resource. Both sides must produce
  byte-identical, lowercased keys.
- Use your own ERI category so you merge with, rather than fight, the MAC keys already present.
- Use a synthesised fallback key only for **permanent** absence (no NIC). On a transient read failure
  skip the edge — otherwise identity flips for one run.

These scripts can't compile off-Collector. Keep their target-API logic in testable preamble helpers
and exclude the snippet-dependent scripts from local compile/test.

## 10. Sharing code between modules

- One preamble (properties, HTTP, output helpers) concatenated onto every body at build time.
- AD bodies can be shared: two modules over the same instance set (performance + status) should use
  the same AD script so they discover identical wildvalues.
- When two AD variants exist for the same object type (e.g. all nodes vs online-only nodes), make
  both emit the same wildvalue so a module can switch between them without orphaning instances.
- Split modules by alert posture and interval (capacity vs performance vs status), as LM's VMware
  suite does — not one fat module.
