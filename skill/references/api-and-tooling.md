# LogicMonitor REST API, tooling and sources

## REST API v3

- Base: `https://<portal>.logicmonitor.com/santaba/rest`
- Header: `X-Version: 3`, `Content-Type: application/json`
- Auth, either:
  - **Bearer**: `Authorization: Bearer <token>`
  - **LMv1** (access id + key):
    1. `requestVars = METHOD + epochMillis + body + resourcePath`
       — body omitted for GET/DELETE; `resourcePath` is the path after `/santaba/rest`, **without the
       query string** (e.g. `/setting/datasources`).
    2. HMAC-SHA256 of `requestVars` with the access key.
    3. **Lowercase hex** the digest, then **Base64-encode the hex string** (not the raw bytes — the
       most common LMv1 bug).
    4. `Authorization: LMv1 <accessId>:<base64>:<epochMillis>`

```python
import base64, hashlib, hmac, time, requests
def lm_request(portal, access_id, access_key, method, path, body="", params=None):
    epoch = str(int(time.time() * 1000))
    digest = hmac.new(access_key.encode(), (method + epoch + body + path).encode(),
                      hashlib.sha256).hexdigest()
    sig = base64.b64encode(digest.encode()).decode()
    return requests.request(method, f"https://{portal}.logicmonitor.com/santaba/rest{path}",
        params=params, data=body or None,
        headers={"Authorization": f"LMv1 {access_id}:{sig}:{epoch}",
                 "Content-Type": "application/json", "X-Version": "3"})
```

- List endpoints paginate with `size` (max typically 1000) and `offset`; filter with
  `filter=name:"Foo"` style expressions **[LM docs]**.

## Module import API

Import takes a module **type** — `datasources`, `propertyrules` (PropertySources), `configsources`,
`eventsources`, `batchjobs`, `logsources`, `oids`, `topologysources`, `functions`,
`diagnosticsources` — a conflict policy (`FORCE_OVERWRITE` / `ERROR`), and a `FieldsToPreserve`
list: `NAME`, `APPLIES_TO_SCRIPT`, `COLLECTION_INTERVAL`, `ACTIVE_DISCOVERY_INTERVAL`,
`MODULE_GROUP`, `DISPLAY_NAME`, `USE_WILD_VALUE_AS_UUID`, `DATAPOINT_ALERT_THRESHOLDS`, `TAGS`.
Preserving end-user-tuned thresholds and AppliesTo on re-import is what makes updates safe for users.

## `Logic.Monitor` PowerShell module (community, PSGallery)

Implements LMv1 for you. Most useful cmdlets for module work:

- `Connect-LMAccount` — authenticate to a portal
- `Export-LMLogicModule` / `Import-LMLogicModuleFromFile` — move modules
- `Invoke-LMActiveDiscovery` — re-run AD on a resource
- **`Invoke-LMCollectorDebugCommand`** — runs Collector debug commands such as `!groovy` on a real
  Collector: the closest thing to a live test harness, and the way to exercise Collector-only
  classes (`santaba` HTTP, `lm.topo` snippets) outside the portal UI.

## In the portal

- **Test Script** (AD and collection) on a module, against a chosen resource, shows raw output. It does
  **not** show whether datapoints parse — a module can pass Test Script and record No Data.
- Resource → instance → **Raw Data** tab shows what was actually recorded. Use **Poll Now** rather than
  waiting out a long interval; a module not yet due looks identical to a broken one.
- Resource → **Info** shows properties, including `system.categories` set by PropertySources.
- Collector debug console (`!groovy`, `!adlist`, `!tlist` etc.) — see below for how to reach it.

### Opening the Collector debug console (new UI, portal-confirmed 2026-10)

LogicMonitor's own docs give the path as Collectors → More (⋮) → **Run Debug Command**. In a
current portal that entry **does not exist** until debug access is turned on, and nothing says so:

1. **Settings → Security → enable Collector Debug.** Without it the debug entry point is absent.
2. Then open the debug window for the Collector from **Settings → Collectors** (which control
   appears there once debug is enabled was not recorded — ask the user what they see).
3. In the debug window type `!groovy` on its own and press Enter; an input box opens. Paste the script
   **without** a `!groovy` line and submit. The script's return value and stdout are shown.

Do not guess at the Collectors row icons: the globe-with-magnifier in the Actions column is
**Schedule NetScan**, not debug, and the ⋮ menu holds logs, events, status, configuration,
download, delete and restart — no debug command. When walking a user through the UI, give one
step at a time and confirm before the next; menus differ by portal version and permissions.

A `!groovy` script has no resource bound, so snippets that read `hostProps` at load time
(`lm.topo`, `lm.data.topo`) need it to exist first:
`if (!binding.hasVariable('hostProps')) { binding.setVariable('hostProps', [:]) }`, then load the
snippets `.withBinding(getBinding())` as usual. This is how `lm.data.topo`'s OUI and keyword tables
were dumped from a live Collector.

## LogicMonitor GitHub repos worth mining

| Repo | Use |
|---|---|
| `logicmonitor/dashboards` | Real dashboard exports with real module/datapoint names — schema source and parity reference for naming |
| `logicmonitor/monitoring-recipes` | LM's authoring guidance: `recipes/` (SNMP, SSH, HTTP, JDBC, WinRM, WMI starter scripts), `docs/` (module types, output formats), `skills/` (module + dashboard skills with templates and a corpus-derived dashboard schema). Distilled into this skill as **[LM recipes]** at `a7b45b6`; check it for changes when refreshing |
| `logicmonitor/GroovyRemix` | Groovy 2 → 4 migration tooling |
| `logicmonitor/lm-sdk-python`, `lm-sdk-go` etc. | Generated REST clients |

Published modules (VMware vSphere/vCenter, Hyper-V, Nutanix, `addERI_*`, `addCategory_*`) can be
exported from any portal's Exchange to read their exact JSON — the most reliable schema source.
Prefer those over documentation when they disagree.
