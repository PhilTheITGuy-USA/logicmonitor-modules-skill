---
name: logicmonitor-modules
description: Build, fix, test and publish LogicMonitor LogicModules — DataSources, PropertySources (including ERI), TopologySources and dashboards — as Groovy scripts plus importable module JSON, to a standard fit for the LM Exchange / LogicMonitor Community. Use this whenever the user is writing or debugging Collector Groovy (Active Discovery, Script or BatchScript collection), editing module or dashboard JSON, choosing datapoint types or thresholds, wiring AppliesTo / categories / PropertySources, calling or authenticating to the LogicMonitor REST API (v3, LMv1 HMAC signing and its 401 errors, bearer tokens, Logic.Monitor PowerShell), importing modules into a portal, or diagnosing "instances discovered but every datapoint No Data", widgets missing after a dashboard import, or a module that silently stopped applying — even if they only say "LM", "santaba", "collector script", "wildvalue" or name a monitored product (Proxmox, VMware, a REST API) they want to monitor.
---

# Building LogicMonitor modules

Most LogicMonitor failures are **silent**: the module imports, discovery populates, Test Script output
looks correct in the portal — and every datapoint reads No Data, or a dashboard drops widgets without
naming them, or the suite stops applying with no error. So the job is mostly about getting a short
list of contracts exactly right and building local checks for the ones the portal won't report.

This skill was distilled from building a 17-module Proxmox VE suite to Exchange standard
(github.com/PhilTheITGuy-USA/Proxmox-LogicModule). Every claim in the references is marked by how it
was established — **portal-confirmed**, **from LM's published exports**, or **inferred**. Keep that
distinction when you report your own work: a green local test is not a portal import, and a portal
import is not a working live target.

## The rules that fail silently

Read these before writing any module. Each one shipped broken at least once.

1. **BatchScript datapoint keys need `##WILDVALUE##.`** A BatchScript prints `instanceId.Datapoint=value`
   for every instance in one stream, so each datapoint's post-processor must be
   `namevalue` with `interpretExpr` `##WILDVALUE##.Datapoint`. A Script (per-instance) module uses the
   bare name. Get this backwards and everything looks right except that no data is ever recorded.
   First thing to check when a batchscript module collects nothing.
2. **The wildvalue is the instance's identity — make it stable and safe.** Set
   `useWildValueAsUniqueIdentifier: true`. Build it from the target's own durable id, never from
   something that moves (the host a VM currently runs on). Fold it to `[A-Za-z0-9_-]`: spaces, `:`,
   `=`, `\`, `#` are illegal, and `.` is ambiguous in BatchScript output. Changing a wildvalue scheme
   later orphans every instance and its history in every customer portal.
3. **Exit non-zero on failure; never zero-fill.** `return 0` on success; on any API/config failure
   write the reason to `System.err` and `return 2`. A non-zero exit keeps existing instances through
   an outage. Returning 0 with zeros produces confident wrong data. Pair this with
   `deleteInactiveInstances: false` / `autoDeleteInstances: false` in Active Discovery.
4. **Every value printed must be numeric.** Strings ("running", "N/A", string-typed numbers) reach
   LogicMonitor as No Data. Map or convert before printing.
5. **Withhold, don't fabricate.** If the source genuinely has no value (feature not configured,
   attribute unreadable), print nothing for that datapoint so it reads No Data. A `0` that means
   "unknown" alerts like a real failure, or hides one.
6. **Secrets end in `.credential`** (e.g. `vendor.api.token.credential`). That suffix is what makes the
   portal mask the value. Renaming a property later breaks every existing deployment quietly — the
   module stops applying rather than erroring — so pick the name once.
7. **A PropertySource with `AppliesTo: true()` must be completely silent** (exit 0, no output) on any
   host that isn't the target or lacks credentials. It runs on every resource in the portal; if it
   ever prints a category on the wrong host, the whole suite applies itself to unrelated machines.
8. **Copy formats from LogicMonitor's own exports — keys, value types and value vocabularies.** An
   unexpected key, a string where an integer belongs, or an enum value LM's exports never use is
   dropped at import, often without naming what was dropped. Never invent a field or a value.
9. **Declare what you print and print what you declare.** A printed name with no datapoint is lost; a
   declared datapoint never printed is permanently empty. Keep the two mechanically checked.
10. **Dashboards reference modules by plain string** `"<displayedAs> (<name>)"`. Rename a module, its
    display name or a datapoint and every widget pointing at it is discarded at import. Import the
    modules before the dashboard.

## Bundled scripts — use them, don't re-derive them

Both are standalone Python 3 (stdlib only) in this skill's `scripts/` directory. Run them on every
module or dashboard JSON you write, edit or are asked to debug, and report what they found.

- **`scripts/lm_lint_module.py <file.json|dir> ...`** — lints DataSource, PropertySource (plain and
  ERI) and TopologySource JSON for the silent failures above: batchscript keys missing
  `##WILDVALUE##.`, `useWildValueAsUniqueIdentifier` off, auto-delete on, secrets not ending
  `.credential`, reserved datapoint names, catch blocks returning 0, a `true()` PropertySource that
  can print or fail, TopologySource `collectionAttrs` as an object, REST-model JSON passed off as an
  export, and more. `ERROR` = fix before import; `WARN` = heuristic, read and judge. Exit 1 on errors.
  On a "No Data" report, run this first.
- **`scripts/lm_dashboards.py`** — build dashboards with it instead of hand-writing widget JSON. Its
  `Dashboard` class (`graph`, `table`, `numbers`, `alert_status`, `alert_table`, plus `series` /
  `column` / `module_ref`) emits only key sets and values copied from LM's published exports; usage
  is in the file's docstring (`sys.path.insert` the scripts dir, then import). Validate any
  dashboard — generated, hand-written or a portal export — with
  `python lm_dashboards.py check <dashboard.json> --modules <module JSONs or dir>`, which also
  resolves every `"<displayedAs> (<name>)"` reference and datapoint and checks the grid.

Both were mutation-tested against a 17-module suite that works in a portal: it lints with zero
errors, and each defect class above makes the tools fail. A clean run is still not a portal import.

## Workflow for a new module or suite

1. **Find the cheapest source.** Map every metric to an API call and classify it O(1) per target,
   O(sub-objects) or O(instances). One bulk call per interval feeding a BatchScript beats a call per
   instance — at 500 instances that is 1 request instead of 500. Anything O(instances) becomes its
   own opt-in module on a long interval. See `references/suite-design.md`.
2. **Mirror LogicMonitor's own suite for the nearest product** (VMware, Hyper-V, Nutanix) for naming,
   module split and datapoints. Look at `logicmonitor/dashboards` on GitHub — those exports reference
   real module and datapoint names.
3. **Write the scripts to the Collector contract** — bindings, Active Discovery line format, output
   format per collection method, exit codes. See `references/collector-scripting.md`.
4. **Generate the module JSON from a small definition** rather than hand-editing exports; the build
   is where the cross-checks live. See `references/module-export-schema.md`. Then run
   `scripts/lm_lint_module.py` on the result.
5. **Test locally against a mock API** in the Collector's runtime (Groovy 4, JDK 17), asserting
   output shape, not just "it ran". See the testing section of `references/suite-design.md`.
6. **Verify in a portal**, then against a real target, and record which layer proved what.
   Dashboards: build with `scripts/lm_dashboards.py`, `check` before import, count the widgets after
   import — better, export it and run `check` on the export.
7. **Prepare for Exchange**: `technicalNotes` on every module, PascalCase datapoints,
   `Vendor_Product_Component` names, self-applying via a category PropertySource, alert bodies and
   thresholds that make sense out of the box. See `references/suite-design.md`.

## Reference files — read the one you need

| File | Read it when |
|---|---|
| `references/collector-scripting.md` | Writing any Groovy: bindings (`hostProps`, `taskProps`, `instanceProps`), AD output, Script vs BatchScript output, exit codes, HTTP/TLS, Groovy 4 migration, the `lm.topo` snippets for ERI/topology |
| `references/module-export-schema.md` | Producing or editing module JSON: DataSource, PropertySource (plain and ERI), TopologySource shapes; datapoint `type`/`dataType` enums, thresholds, alert bodies, AD block, reserved names |
| `references/dashboards.md` | Building or debugging a dashboard export: widget key sets, the allowed value vocabularies, `##INSTANCE##` vs `##HOSTNAME##`, why not the newer `table` widget |
| `references/api-and-tooling.md` | Talking to a portal programmatically: REST v3, LMv1 HMAC signing, bearer tokens, module import API, the `Logic.Monitor` PowerShell module, running `!groovy` on a Collector, useful LogicMonitor GitHub repos |
| `references/suite-design.md` | Planning a suite, cost tiers, instance-ID design, self-applying categories, topology/ERI identity, local test harness design, verification discipline, Exchange readiness checklist |

When the user's repo already has its own CLAUDE.md or design record, that wins over this skill for
project specifics; this skill supplies the platform knowledge underneath it.
