# PowerShell Collector scripts

Provenance tags as in `collector-scripting.md`. Everything on this page is **[LM recipes]**
(github.com/logicmonitor/monitoring-recipes @ `a7b45b6`) unless tagged otherwise — this skill's own
portal experience is Groovy. The output contracts (AD line format, Script vs BatchScript keys,
exit codes, numeric values only, withhold rather than fabricate) are the same as Groovy's; read
`collector-scripting.md` §3–§6 first.

## When PowerShell

Embedded PowerShell runs on **Windows Collectors only**, in a separate process with a fixed,
non-configurable timeout. Use it for Windows-native work — WMI/CIM, WinRM remoting, vendor
PowerShell SDKs. Use Groovy for everything cross-platform; a module in PowerShell can't be moved to
a Linux Collector.

In the export, the script's `type` is `"powershell"` (`collectionAttrs.type`,
`activeDiscovery.params.type`, `script.type`). `lm_lint_module.py` reads PowerShell scripts for the
shared checks (secrets, exits, `Write-Host`) and skips the Groovy-4 ones.

## Properties are tokens, substituted before the script runs

PowerShell has no `hostProps`. Properties arrive as `##name##` tokens replaced in the script text:

```powershell
$hostname = '##system.hostname##'
$user     = '##wmi.user##'
$pass     = @'
##wmi.pass##
'@
```

- Use **single quotes** (no expansion), and a single-quoted here-string for passwords — a password
  containing `'` or `$` otherwise breaks the script.
- **An unset property is left as the literal token.** Test for it before use:

  ```powershell
  function Test-PropertyToken([string]$Value) {
      return [string]::IsNullOrEmpty($Value) -or $Value -match '^##.*##$'
  }
  ```
- Secrets follow the same naming rule as Groovy — `vendor.api.key.credential` — except LM's own
  built-ins (`wmi.pass`, `ssh.pass`, …), which the linter allows.
- `alertProps` doesn't exist in PowerShell; Diagnostic/RemediationSources read `##ALERT.DATAPOINT##`
  and friends as tokens, which are **empty on a manual run**.

## Output

- **`Write-Output` for every line of Collector data.** `Write-Host` writes to the host stream, not
  stdout, and slows BatchScript output enough to hit the timeout. Keep `Write-Host` for messages
  behind `if ($debug)`. The linter warns on ungated `Write-Host`.
- Same formats as Groovy: `Name=value`; BatchScript `wildvalue.Name=value`; AD
  `wv##name##description####auto.key=value&auto.key2=value`; PropertySource `auto.key=value` /
  `system.categories=Cat`.
- Fold wildvalues with `-replace '[^A-Za-z0-9_-]', '_'` — in AD **and** collection.
- Booleans to `1`/`0` (`[int]$bool`). **Don't print `Name=null`** for a missing value, as LM's WMI
  recipe does — skip the line so the datapoint reads No Data honestly (rule 5).
- Never dump every property of a WMI/CIM object as datapoints: strings read as No Data. Map the
  numeric fields you declared.
- JSON-shaped output (Diagnostic/Remediation): `@{data = $text; format = 'markdown'} |
  ConvertTo-Json -Compress | Write-Output`.

## Exit codes

`exit 0` on success; `exit 2` (any non-zero) on failure, with the reason on stderr
(`[Console]::Error.WriteLine(...)` or `Write-Error`). Same semantics as Groovy: non-zero keeps
existing instances; zero-filling on failure is wrong data.

## Remoting

- Prefer CIM (`Get-CimInstance -ComputerName $h -Credential $cred`) over the old `Get-WmiObject`.
- If `system.hostname` is an IP, resolve it to an FQDN first — Kerberos/WinRM usually need a name.
- Skip remoting when the target **is** the Collector (`##system.categories##` contains
  `collector`): run locally, without credentials.
- A WinRM session: `New-PSSession` → `Invoke-Command -Session` → **always** `Remove-PSSession`, in a
  `finally`, or sessions leak on the target until it refuses new ones **[inferred]**.
- Credential fallback order in LM's recipes: product-specific property → `wmi.user`/`wmi.pass` →
  none (Collector service account).

## Testing

There is no local harness for embedded PowerShell here. Run the script by hand on a Windows box
with the tokens replaced, then use **Test Script** in the portal on a real resource — and check that
an unset property produces a clean non-zero exit, not a stack trace.
