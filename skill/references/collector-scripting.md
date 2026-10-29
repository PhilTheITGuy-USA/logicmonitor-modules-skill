# Collector Groovy scripting contract

Provenance tags: **[portal]** confirmed in a real portal/Collector; **[LM export]** read from
LogicMonitor's published modules or repos; **[LM recipes]** stated in LogicMonitor's
`monitoring-recipes` guidance (github.com/logicmonitor/monitoring-recipes @ `a7b45b6`, Apache-2.0)
but not yet observed here; **[inferred]** reasoned, not yet observed.

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
11. Collector snippets: when and how
12. ScriptCache: tokens between polls

PowerShell scripts: `powershell.md`. Module types other than DataSource / PropertySource /
TopologySource: `other-module-types.md`.

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
| `datasourceinstanceProps` | every discovered instance of this module on the resource, keyed by instance, each with `.wildvalue` **[LM recipes]** | BatchScript collection |
| `alertProps` | the triggering alert (`alert.datapoint`, `alert.instance.wildvalue`, …) **[LM recipes]** | Diagnostic / RemediationSource, alert-triggered runs only |

`datasourceinstanceProps` lets a BatchScript loop over exactly the instances discovery produced —
`datasourceinstanceProps.each { inst, props -> def wv = props.wildvalue ... }` — instead of
re-deriving them from the API. Useful when the API needs a call per instance anyway.

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
- **stderr is only seen on failure.** On exit 0 the portal shows no stderr: Poll Now and Test
  Script both leave `errOutput` empty even when the script wrote to it **[portal, 2026-10-24]**.
  Writing detail there (which guest failed, which health check fired) costs nothing and helps
  anyone running the script on a Collector, but never tell end users to read it — not in
  `technicalNotes`, a datapoint description or an alert body. Point them at the target's own UI
  or log, where the full detail lives. `lm_lint_module.py` warns on text that mentions the
  collection log, `errOutput` or stderr.
- **Fan-out over sub-objects** (one call per node/host): filter to reachable ones first, then a
  per-item `try` that logs to `System.err` and continues, so one dead member doesn't blank the rest.
- A fourth legitimate shape: **nothing to report** (feature not installed) → print nothing,
  `return 0`, and say so on stderr for AD. **Only safe for AD with auto-delete off.** LogicMonitor
  states that an AD script exiting 0 with empty output removes every previously discovered instance
  **[LM recipes]** — that is the auto-delete behaviour. With `autoDeleteInstances: false` the
  instances and their history stay **[portal]**, until an operator confirms they're retired and
  their history is no longer needed and deletes them by hand. That is the intended lifecycle: never
  let discovery retire instances on its own. When "empty" could be a transient error (a
  permissions-filtered list, a half-up API), still exit non-zero, so the log shows a failure rather
  than "nothing found".

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
- All instance properties on one resource share a **~49,000-character budget**. Limits **[LM
  recipes]**: wildvalue ≤ 1024 chars, display name ≤ 255.
- Do put stable discovery metadata (type, role, version, feature flags) on the instance as
  `auto.*` properties: AD filters and "group by instance property" key on them. Never put metrics
  there — they belong in datapoints.
- With the `lm.emit` snippet (§11), `emit.instance(wv, name[, description][, [key: value]])`
  writes this line for you, adds `auto.` to bare keys and folds the wildvalue itself. If AD uses
  `emit.instance`, collection must use `emit.dp` (or the identical fold) — see §5.
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
- **Mixed folds break silently.** `lm.emit` folds `# \ : =` and spaces in a wildvalue to `_`
  **[LM recipes]**; a hand-written fold may differ (e.g. ours also folds `.`). If discovery and
  collection fold differently, every datapoint reads No Data. One fold, used on both sides.
- BatchScript may instead print JSON — `{"data": {"<wv>": {"values": {"Name": 1}}}}` — read with
  the JSON post-processor and `interpretExpr` `data.##WILDVALUE##.values.Name` **[LM recipes]**.
  `lm_lint_module.py` understands only `namevalue`; prefer it.
- Batchscript has its own timeout, `collector.batchscript.timeout` in `agent.conf`. Budget long
  scripts against it: `Settings.getSettingInt("collector.batchscript.timeout",
  Settings.getSettingInt("collector.script.timeout", 120)) * 1000 - 2500`
  (`import com.santaba.agent.util.Settings`) **[LM recipes]**.

## 6. Values and metric types

- Every value must match `^-?\d+(\.\d+)?([eE][-+]?\d+)?$`. Convert string-typed numbers
  (`toString().toDouble()`), map states to integers (`running` → 1).
- Cumulative counters from the source (bytes since boot/start) → datapoint `type: derive` with
  `min: 0` so a counter reset is dropped rather than graphing a negative spike. Point-in-time
  readings → `gauge`. Declaring a counter as gauge graphs an ever-climbing line.
- **Units — two defensible choices; pick one per suite and write it down.**
  - *Canonical units* (bytes, bytes/s, seconds), unrounded — LogicMonitor's own guidance **[LM
    recipes]**. Keeps full precision and lets graphs auto-scale; but a dashboard table or big
    number can render a raw byte count in E-notation (`5.001E11`) **[portal]** unless the widget
    scales it.
  - *Display units* (GB, MB/s), rounded (`Math.round(v * 100) / 100`) — what the Proxmox suite
    does **[portal]**. Reads well everywhere with no widget work; loses precision and auto-scaling,
    and a graph of TB-scale data shows `124.5K` GB **[LM recipes]**.
  - Either way the datapoint name carries the unit (`CapacityGB`, `UsedBytes`) and the description
    states it, decimal vs binary included. Fixing display on the dashboard side (an RPN multiply in
    the widget) is in `dashboards.md`.
  - Never change a deployed datapoint's unit in place: history mixes both. Add a new datapoint.

## 7. HTTP, TLS, auth

- Three clients; choose deliberately and record the choice in `technicalNotes`:
  - **Plain `HttpURLConnection`** — testable off-Collector against a mock API (the Proxmox suite's
    harness), per-request timeout and TLS control. **Ignores the Collector's proxy settings**: a
    Collector that reaches the internet only through a proxy can't reach a SaaS API this way.
    Default for an on-prem REST target where local testing matters.
  - **`proto.http` snippet** (§11) — honours the resource's and the Collector's `proxy.enable`
    and `proxy.exclude` **[LM recipes]**. LogicMonitor's recommended client; use it for SaaS/
    cloud targets or whenever a proxy may sit in the path. Collector-only.
  - `com.santaba.agent.groovyapi.http.HTTP` (`HTTP.open(host, port)`, `.get(url)`,
    `.getStatusCode()`, `.getResponseBody()`, `.close()`) — older LM reference modules
    **[LM export]**. Collector-only and no proxy story; don't start new work on it.
- Set connect and read timeouts from a property with a default (e.g. 10000 ms).
- Call out 401/403 distinctly in the error — "credential rejected / missing ACL" is the most common
  misconfiguration and otherwise looks like an empty result.
- A TLS bypass for self-signed lab targets must be **opt-in via a property and default off**.
- Use `groovy.json.JsonSlurper` to parse; unwrap any response envelope in one helper.
- Session tokens that outlive a poll: cache them (§12) rather than logging in every interval. On a
  401 with a cached token, drop it, re-authenticate and retry **once** — never loop on an auth
  failure **[LM recipes]**.

## 8. PropertySource output

- Prints `key=value` lines; each becomes a resource property. `system.categories=Foo` *adds* a
  category (this is how a suite becomes self-applying).
- **Every property a PropertySource creates is stored as `auto.<key>`** — a printed
  `pve.version=8.2.2` lands on the resource as `auto.pve.version` **[portal, LM docs]**. The one
  exception is `system.categories`; no other `system.*` property can be set **[LM docs]**. So
  AppliesTo expressions, other modules and install docs must say `auto.pve.version`, never the
  bare name — a bare reference matches nothing, silently. Printing the prefix yourself
  (`auto.vendor.version=…`) is what LM's own recipes do and makes the script read like the result
  **[LM recipes]**. `lm_lint_module.py` notes each bare key with the name it will get, and warns on
  any other `system.*` key.
- A PropertySource on `AppliesTo: true()` must **return 0 and print nothing** when the host isn't the
  target or credentials are missing — on every error path too. Use the cheapest authenticated
  endpoint that proves identity (a `/version`-style call).
- Publish facts other modules' AppliesTo can key on (e.g. `auto.vendor.version`,
  `auto.vendor.clustered`) so they don't need their own probe.
- A PropertySource that sets **only** a category can add `&& !hasCategory("Foo")` to its
  AppliesTo so it stops re-running once applied; don't, if it also maintains other properties
  **[LM recipes]**.

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

TopologySource — **two documented call shapes; start from LM's catalog form**:

```groovy
// LM's snippet catalog form [LM recipes] -- the general starting point:
def edges = []
lmTopo.registerEdge(edges, fromEri, toEri, 'dependsOn')
print lmTopo.generateTopology(edges, 'myNamespace', [], false)

// The form the Proxmox suite ships, inside LM's ERI-namespace/blacklist plumbing [portal]:
lmTopo.registerEdge('Compute', parentEri, childEri, edges)   // edge type e.g. 'Cluster', 'Compute'
println lmTopo.generateTopology(edges, keyNamespace, keyBlacklist, null, debug)
```

Argument order is a property of the `lm.topo` snippet, not of the target API, so these are either
two overloads or one source is wrong; the Proxmox form is the only one observed working here. The
catalog also documents extended `registerEdge` overloads (display type, instances, health). Whichever
you use, confirm with **Test Script** on the TopologySource that edges come out before trusting the
map. `lmTopo.isMac(mac, lmTopoData.blockedKeys, false)` validates a MAC before using it as a key.

The raw output those helpers produce is `{"edges": [{"type", "from", "to"}]}` keyed by ERI (plus
vertices from `generateTopology`) **[LM recipes]** — still don't hand-write it; the helpers apply
namespace and blacklist rules a hand-built payload skips.

ERI PropertySource:
```groovy
import org.json.JSONArray
def eriArray = new JSONArray()
lmTopo.emitEri('<category>', 1, keys, 'PhysicalServer', eriArray)   // category, priority, keys, ERT
lmTopo.printEriArray(eriArray, keyNamespace, keyBlacklist)
```

Behaviour **[portal]**:
- The map draws **only vertices whose key matches an ERI** — a monitored resource's, or a
  DataSource instance's (next bullet). A child that is emitted but matches neither simply isn't
  drawn. Use Test Script on the TopologySource to separate "not emitted" from "not drawn".
- **Objects that are only instances can be mapped** **[portal, 2026-10-19]**. A DataSource whose
  Active Discovery sets the *instance* properties `predef.externalResourceID` (e.g. a guest MAC) and
  `predef.externalResourceType` (e.g. `VirtualMachine`) makes that instance a vertex the map draws —
  a ping-only container with no LM resource of its own was drawn under its host node. LM's own
  `VMware_vSphere_VirtualMachineStatus` does the same **[LM export]**. So an object needs neither its
  own resource nor an ERI PropertySource to appear on the map.
- Monitored hosts typically get MAC-keyed ERIs from SNMP discovery (`predef.externalResourceID`). A VM
  that doesn't answer SNMP has no MAC ERI and won't match as a resource — give it an instance-level
  ERI instead (previous bullet).
- **The ERT comes from the highest-priority ERI entry across *all* categories; keys from every
  category merge into the ID** **[portal, 2026-10-19]**. LM's built-in `addERI_Linux` /
  `addERI_Windows` emit `net.l2` at **priority 2**. A second ERI PropertySource emitting category
  `virt.proxmoxve` at priority 1 had its key merged into `predef.externalResourceID` while
  `predef.externalResourceType` stayed `PhysicalServer`; at priority 3 the type became
  `VirtualMachineResource`. To override the type, emit at **priority 3 or more**; to only add keys,
  any priority works. `lm_lint_module.py` warns on a non-`PhysicalServer` ERT below priority 3.
- When the source API exposes no hardware id for an object, synthesise a key with one shared helper
  and stamp the same key via an ERI PropertySource on that object's resource. Both sides must produce
  byte-identical, lowercased keys.
- Use your own ERI category so you merge with, rather than fight, the MAC keys already present
  (the priority then decides only the ERT, above).
- **A vertex with several keys matches only a resource carrying all of them** **[portal,
  2026-10-21]**. `lm.topo` joins a vertex's keys into one ID with `_`
  (`keyA_keyB`), and the portal matches that ID against a resource only when the resource carries
  every key — not any one. A node vertex given both a cluster-scoped and an IP key left the node
  carrying only the IP key on the map with no edges. Give a vertex **one** key, chosen by a shared
  helper, unless every resource it should match carries every key. `lm_lint_module.py` warns on a
  vertex built from a multi-element list literal.
- **Edges between two other resources are drawn** **[portal, 2026-10-22]**. A TopologySource on one
  resource (a cluster's token holder) emitted an edge from a second node's resource to a guest's
  resource; the map drew it, though neither end was the resource running the module. So one
  TopologySource can draw a whole cluster, provided every vertex matches.
- **A resource wins over an instance carrying the same key** **[portal, 2026-10-22]**. A guest that
  was its own resource *and* an instance (with an instance-level ERI) on another node's resource
  got its edge from its real node to the resource.
- **An instance vertex takes edges from any matched resource** **[portal, 2026-10-22]**. A
  container with no resource, carried only as an instance (with instance-level ERI) on node A's
  resource, was drawn under node B, where it runs, from A's TopologySource. A cluster vertex carried
  by one instance on node A (ERT `Cluster`, which renders the cluster icon; `VirtualCluster` renders
  "??") was drawn with edges to both nodes. So guests and clusters need no resources of their own.
  An earlier run that joined the cluster to A only was confounded by an unmatched node vertex (the
  multi-key rule above): when an edge is missing, check both ends match before blaming the instance.
- **`VMDatastore` and `HyperVisorCluster` instance vertices take no edges** **[portal,
  2026-10-28]**. On one portal, from a third-party TopologySource:
  - Store vertices stamped `VMDatastore` on a capacity DataSource's instances resolved to those
    instances, yet took none of the edges the TopologySource printed for them (Test Script listed
    every one), before and after the instances were deleted and rediscovered. Retyped
    `StorageVolume`, with key and edges unchanged, every edge drew.
  - A cluster vertex stamped `HyperVisorCluster` under a fresh key took no Manage edges across
    several runs; retyped `Cluster`, same key, both drew on the first run.
  - `StorageVolume`, `StorageAggregate`, `StorageNode`, `PhysicalDisk`, `VirtualSwitch`, `Cluster`,
    `VirtualMachine` and `HyperVisor` (the last on a resource) all took edges there.
  LM's own vSphere suite uses both refused types on its instances; its datastores draw as "??" on
  vSphere maps **[inferred: these types may be reserved to LM's own modules]**. `lm_lint_module.py`
  warns on `'VMDatastore'` or `'HyperVisorCluster'` in a discovery script.
- **A vertex record is made per key when an edge first attaches, and keeps that first type**
  **[portal, 2026-10-28]**. A cluster vertex drawn as `Cluster` kept its record ID and type after
  its carrier was retyped, and after the carrier instance was deleted and rediscovered: the new
  instance re-attached to the old record. A key whose type refuses edges gets no record at all;
  the topology API answers with a placeholder ID, `instance.<id>`, carrying the instance's type.
  To change a drawn vertex's type, give it a new key (and stamp the new type before the first run).
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

## 11. Collector snippets: when and how

Snippets are LogicMonitor-maintained Groovy libraries the Collector downloads from the portal and
loads at run time **[LM recipes]**. End users can't write or deploy their own.

**When to use them.** Two styles are both legitimate; choose per suite and record it:

| Style | Use for | Cost |
|---|---|---|
| **Self-contained Groovy** (plain `HttpURLConnection`, own `println`) | REST-API suites where a local mock-API harness matters (the Proxmox suite) | No proxy support; you own retries, folding and output formatting |
| **Snippet-first** (`lm.emit`, `proto.http`, `proto.snmp`, `lm.remote`, `lm.sql`) | SNMP, SSH, JDBC; SaaS/cloud APIs; any Collector behind a proxy | Scripts can't run off-Collector — keep target logic in plain helpers you can test, and keep the snippet calls thin |

`lm.topo` (§9) is effectively mandatory for topology and ERI either way.

**Prerequisites**: the `LogicMonitor_Collector_Snippets` module installed, and monitoring enabled
on the **Collector's own resource**. A missing prerequisite shows as `Unable to load Snippet -
<name>`, or exit 0 with no output.

**Bootstrap — bind it or get silent nothing:**

```groovy
import com.santaba.agent.groovy.utils.GroovyScriptHelper as GSH
import com.logicmonitor.mod.Snippets

def modLoader = GSH.getInstance(GroovySystem.version)
    .getScript('Snippets', Snippets.getLoader())
    .withBinding(getBinding())          // without this, emit.dp() exits 0 and prints nothing
def emit = modLoader.load('lm.emit', '0')
```

A loaded snippet runs as a separate script object; without the parent binding its output never
reaches the Collector — exit 0, empty output, no error **[LM recipes]**. `lm_lint_module.py`
errors on a `Snippets.getLoader()` without `.withBinding(...)`.

- **Version pins** are a *minimum within the same major*: `load('lm.emit', '0')` = latest 0.x;
  `load('lm.remote', '0.7.1')` = latest 0.x ≥ 0.7.1; `'-1'` = latest active **[LM recipes]**.
- **Helpers don't see locals.** A top-level `def helper() {}` is a method on the script class, so it
  can't see `def emit` — `MissingPropertyException: No such property: emit`. Pass the handle in as a
  parameter.
- Don't call `clearCacheForUpdate()` from a module; it is an operator action.

**Main snippets** (min versions per LM's catalog **[LM recipes]**):

| Snippet | Use | Entry point |
|---|---|---|
| `lm.emit` | Collector-parseable output | `emit.dp(name, v)` / `emit.dp(wv, name, v)` / `emit.instance(wv, name[, desc][, props])` / `emit.property(key, v)` / `emit.events(list)`. Booleans → `1.0`/`0.0`; wildvalues folded (§5) |
| `proto.http` `1.0.0` | Proxy-aware HTTP | `.create(hostProps).withHeaders([...]).GET(url, connectMs, readMs)` → `conn.responseCode`, `conn.inputStream.text`. Honours `proxy.enable` / `proxy.exclude` on the resource and the Collector |
| `proto.snmp` `0.2.0` | SNMP get/walk with retries and a time budget | `.create(host, lowercasedProps, startMs).withRetries(n).walk(oid)` → map index → value; `.get(oid)` |
| `lm.remote` `0.7.1` | SSH (SSHJ) | `.exec(hostProps, cmd)`; `.create(hostProps).exec(cmd)`; `.sftp` / `.scp` / `.shell`. Reads `ssh.user` / `ssh.pass` (fallback `config.user` / `config.pass`), `ssh.cert`, `ssh.port` |
| `lm.sql` `0.1.0` | JDBC | `.attemptConnection(user, pass, url)` → `.status` `success`/`failed`; `.runQuery(sql, conn)` → `success` / `no data` / `failed` |
| `lm.cache` `0.3.1` | ScriptCache wrapper (§12) | `.cacheSnippetFactory(debugAdapter, keySuffix)` → `cacheGet` / `cacheSet(key, v, expirySeconds)` |
| `lm.debug` `2.0.0` | Diagnostics routed by `debug.log*` resource properties | `.create(hostProps, debug, out)` → `.debug/.info/.warn/.error` |
| `lm.topo` | Topology / ERI (§9) | `registerEdge`, `generateTopology`, `emitEri` |

SNMP props are case-sensitive in the snippet's eyes: pass
`hostProps.toProperties().collectEntries { k, v -> [(k.toLowerCase()): v] }`.

LM's own credential property names (`ssh.pass`, `wmi.pass`, `jdbc.pass`, `snmp.authToken`, …) are
read by these snippets, so modules that use them keep those names rather than `*.credential`;
`lm_lint_module.py` allows them. That the portal masks them is **[inferred]**.

LogicMonitor's own recipe scripts are starting points, not finished modules: e.g. their HTTP recipe
emits every response field including strings (No Data, rule 4) and reads `api.token` (unmasked,
rule 6). Apply the rules in `SKILL.md` to anything you copy.

## 12. ScriptCache: tokens between polls

Collector **29.100+** keeps an in-memory key/value cache across runs **[LM recipes]**:

```groovy
def cache = this.class.classLoader
    .loadClass('com.santaba.agent.util.script.ScriptCache').getCache()
String key = "vendor.session.${hostProps.get('system.hostname')}"   // scope the key!
String token = cache.get(key)
if (token == null) {
    token = login()
    cache.set(key, token, 25 * 60 * 1000L)                          // expireIn: MILLISECONDS
}
```

- `set(key, value[, expireInMs])`, `get(key)` (null when missing/expired), `remove(key)`. Default TTL
  `collector.script.cache.timeout` in `agent.conf`, in **minutes**. The `lm.cache` snippet's
  `cacheSet` takes **seconds** — don't mix them up.
- **Scope every key by target (and module).** The cache is shared by every script on the Collector
  **[inferred from "reuse across modules"]**; LM's HTTP recipe caches under the fixed key
  `authToken`, which would hand one device's token to another.
- Set the expiry below the token's real lifetime (its `expires_in` minus a margin); on a 401 drop the
  key, re-authenticate, retry once.
- Collectors older than 29.100 can't load the class: wrap the load in `try` and fall back to logging
  in each poll. Don't cache secrets you wouldn't want resident in Collector memory.
