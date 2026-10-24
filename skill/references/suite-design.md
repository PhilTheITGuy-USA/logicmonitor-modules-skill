# Suite design, testing and Exchange readiness

## Contents
1. Naming and module split
2. Cost tiers — the axis that decides architecture
3. Instance identity
4. Making the suite self-applying
5. Where to put the credentials (one resource vs many)
6. Conditional datapoints
7. Topology
8. Local testing
9. Verification discipline
10. Exchange / Community readiness checklist

## 1. Naming and module split

Mirror LogicMonitor's own suite for the nearest product (VMware vSphere, Hyper-V, Nutanix):
- `Vendor_Product_Component` names with human `displayedAs` ("Vendor Product Guest Performance").
- **Capacity, performance and status are separate modules** — they want different intervals and alert
  postures (status flaps matter immediately; CPU spikes need a trigger interval).
- PascalCase datapoints; camelCase gets flagged in review.
- One `group` for the suite; ERI PropertySources go in group `ERI`.

## 2. Cost tiers

Classify every candidate metric by API calls per collection interval:

| Cost | Meaning | Treatment |
|---|---|---|
| O(1) | one call, any size | can join any module already making that call |
| O(members) | one call per host/node | fine; filter to reachable members, per-member `try` |
| O(instances) | one call per VM/object | its own module, long interval (≥15m), ideally opt-in |

Scope ("is it worth monitoring") and cost ("what does it do to the architecture") are independent —
sort the backlog on both. The single biggest win is usually finding the **bulk endpoint** that returns
every object with its metrics in one call, and building BatchScripts on it. Also mine responses you
already fetch: fields parsed and discarded are free datapoints.

If an endpoint returns cluster-wide data from any member, call it once (first member that answers,
then `break`) — it's O(1) even though it looks like fan-out.

## 3. Instance identity

- Wildvalue from the target's own stable, unique id; never from location (current host) for things
  that move. A migrating VM whose id embeds the host is deleted and rediscovered on every move —
  history, SDTs and thresholds lost.
- Things that are physically bound (a disk, a cert, a service on a host) **should** include the host,
  or they collide across hosts.
- Carry mutable context (current host, pool, tags) as **instance properties**, which may change freely.
- Changing a scheme orphans every existing instance in every customer portal: change AD and collection
  together, and call it out in release notes.

## 4. Making the suite self-applying

Published modules don't ask users to hand-set a flag on every resource. Pattern:
- `addCategory_<Product>` PropertySource, `AppliesTo: true()`, probes the target with the configured
  credential and prints `system.categories=<Product>` plus useful facts (version, clustered).
- Completely silent (exit 0, no output) on non-targets, missing credentials and every error path.
- Every other module: `AppliesTo: hasCategory("<Product>")`, optionally `&& vendor.clustered == "true"`.
- **A PropertySource can add a category but never remove one** **[portal, 2026-10-21]**. Once
  `addCategory_<Product>` has set it, the category stays when the PropertySource later goes silent
  (its credential removed, the host repurposed), so every module keeps applying and failing there,
  and its old instances stay. Document the manual removal step for anything that moves the
  credential, or design the category to follow something set explicitly (a NetScan, an operator)
  rather than inferred.
- **The same holds for ERI keys** **[portal, 2026-10-25]**. Keys an ERI PropertySource stamped stay
  in the resource's `predef.externalResourceID` after its AppliesTo stops matching (an opt-in flag
  set to `false` for over 14 hours left both Proxmox node keys in place, across runs of the other
  ERI modules on that resource, so no rebuild drops them), and the portal refuses to delete
  that auto property. So **don't make an ERI module, or the TopologySource it serves, opt-in**: a
  flag is an on-switch, never an off-switch. LogicMonitor's own topology modules have no flag
  (`VMware_vSphere_VirtualMachine_Topology`, `addERI_ESXi`, `HyperV_Topology`, `addERI_HyperV`,
  `addERI_Linux`, `addERI_Windows` all apply on what already marks the host as the product), so
  stale keys arise only when a host stops being that product. Select the resources by something
  intrinsic instead (a category, `system.virtualization`, a kernel string in `system.sysinfo`),
  check the selector against guests that share the host's kernel (LXC containers do), and keep keys
  specific enough that a stale one cannot match another object.
- Net effect: **setting the credential property on a resource is the on-switch.**
- Optional / expensive modules: gate on an explicit property (`&& vendor.perguest.enabled == "true"`)
  rather than shipping them on by default — DataSources only, never topology or ERI modules (above).
  "Expensive" means O(instances) per poll; an hourly O(instances) read is not reason enough.

## 5. Where to put the credentials

When one member answers for the whole cluster, setting the credential on one resource monitors
everything with minimal load; setting it on every member duplicates every instance and every API call
N times. Document the trade-off in the install guide; recommend one resource per cluster, or a
resource group carrying the property.

## 6. Conditional datapoints

Mark a datapoint conditional only when the source genuinely has no value (feature absent, attribute
unreadable, not applicable to this object type). Print nothing → No Data. Pair with an always-emitted
indicator (`FeatureAvailable`, `SmartHealthKnown`) so "unknown" never alerts like "bad". Document each
in `technicalNotes`. Never print 0 to keep a build check quiet.

## 7. Topology

Worth building only if the related objects are also monitored — as their own resources, or as
DataSource instances carrying an instance-level ERI. Vertices match on ERI keys; the portal draws
only vertices that match a resource's ERI or an instance's (`predef.externalResourceID` /
`predef.externalResourceType` set in Active Discovery, as LM's `VMware_vSphere_VirtualMachineStatus`
does), so objects that are only instances can be mapped **[portal, 2026-10-19]**. An ERI
PropertySource that must change a resource's ERT needs priority 3 or more: the type comes from the
highest-priority entry across all categories, and the built-in `net.l2` entry is priority 2
**[portal, 2026-10-19]**. A vertex carries **one** key: lm.topo joins several into one ID the portal matches only against a resource carrying all of them **[portal, 2026-10-21]**. An edge between two resources other than the one running the TopologySource is drawn, and a resource wins over an instance with the same key; an instance-only guest is drawn under the host it runs on even when another resource holds the instance **[portal, 2026-10-22]**. See `collector-scripting.md` §9 for mechanics. Topology fan-out (per-VM config reads) is O(instances) —
hourly interval.

## 8. Local testing

Nothing about a Collector is needed to test most of a suite:

- **Compile** every assembled script with `groovyc` in `groovy:4-jdk17` (Docker if Groovy isn't local).
- **Mock API harness**: a Groovy program that starts `com.sun.net.httpserver.HttpServer` serving
  recorded responses keyed by `path + '?' + query` exactly as the script requests it; returns **501**
  (not 404) for an unknown key so a missing fixture is obviously a harness gap; checks auth headers.
- Run each assembled script with `new GroovyShell(new Binding([hostProps: ..., taskProps: ...]))
  .evaluate(file)`, capturing stdout/stderr and the return value.
- Assert the **parse contract**, not just success: AD line regex
  `^([A-Za-z0-9_.\-]+)##([^#]*)##([^#]*)####(.*)$`, `auto.key=value` non-blank properties;
  BatchScript `^([A-Za-z0-9_.\-]+)\.([A-Za-z0-9_]+)=(.*)$`; numeric values; every declared
  non-conditional datapoint present per instance; discovered ⇔ collected ids both directions.
- Pin design decisions with fixed assertions: exit 2 on a dead API and on a bad token, bulk endpoint
  used and per-instance endpoint not, templates excluded, ids stable across a simulated migration.
- **Mutation-test the harness**: deliberately reintroduce a known bug and confirm it goes red. A suite
  that can't fail is worse than none.
- Fixture design: include a mix of states (an online and an offline member, both object kinds). Every
  new endpoint needs a fixture before its module can be tested.
- Snippet-dependent scripts (topology/ERI, and any module written snippet-first — see
  `collector-scripting.md` §11) can't run here — keep their target logic in preamble helpers the
  harness can call directly, and keep the snippet calls a thin layer on top.

## 9. Verification discipline

There are three layers, and each proves something different:
1. **Local** (build checks, compile, mock harness) — proves parsing and output shape against your
   fixtures, not the real API's shape and not how the portal parses module JSON.
2. **Portal import** — proves the JSON is accepted and, with Raw Data / Poll Now, that datapoints
   actually record. Only this layer catches post-processor, reserved-name and schema-type defects.
3. **Live target** — proves the API shape, permissions, and real values (threshold directions!).

Report which layers a change went through. Keep verification status in one place (a status table in
the design doc), not scattered. A module that hasn't been run against a real target says so in its
`technicalNotes` as a customer-facing limitation ("Limitation: not yet tested with ...").
`technicalNotes` and script comments ship to every customer: they explain what the module does and
the constraints it honours, as current fact. Dates, spikes, design-doc references and verification
history belong in the design doc.

Things only a live environment shows: threshold **direction** (e.g. whether a "wearout" field is life
used or life remaining), HA/failover behaviour, permission-filtered empties, scale.

## 10. Exchange / Community readiness checklist

- [ ] `Vendor_Product_Component` names, `displayedAs`, single suite `group`, `searchKeywords`
- [ ] `description` and a substantive `technicalNotes` on every module (what it calls, cost, conditional
      datapoints and why, known limits), each field at most 4096 characters
- [ ] Self-applying via `addCategory_*` PropertySource; no manual per-resource flags
- [ ] Credentials in `*.credential` properties (or LM's built-ins like `ssh.pass`); all properties
      documented with defaults; properties a PropertySource sets are documented and referenced
      by their stored `auto.*` names
- [ ] PascalCase datapoints with descriptions and units; correct gauge/derive; no reserved names;
      status codes mapped in `statusDisplayNames`; every datapoint used by a graph, alert or dashboard
- [ ] Unit convention (canonical vs display units) chosen once and stated
- [ ] HTTP client choice recorded; proxy-aware (`proto.http`) if Collectors may sit behind a proxy
- [ ] Sensible default thresholds and `alertBody` text on the datapoints that should alert
- [ ] `useWildValueAsUniqueIdentifier: true`, stable migration-safe wildvalues
- [ ] No auto-delete of instances; non-zero exit on failure
- [ ] Groovy 4 clean, `//!/lib-groovy/v4` header
- [ ] TLS bypass (if any) opt-in and default off
- [ ] Expensive modules on long intervals and/or opt-in
- [ ] Install doc: minimal-privilege account/token on the target, required permissions, which
      resources get the credential, import order (modules → dashboards; ERI before topology),
      verification steps and a troubleshooting section keyed to symptoms
- [ ] Imported and collecting in a real portal; dashboards export-counted
- [ ] No secrets, portal names or customer data in scripts, fixtures or screenshots

The exact LM Exchange submission flow (publishing from My Module Toolbox, review, locator codes) is
portal-driven and changes; check current LogicMonitor docs rather than relying on this file.
