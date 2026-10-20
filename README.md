# logicmonitor-modules — a Claude Code skill

A skill that teaches Claude Code to build, debug and publish LogicMonitor LogicModules —
DataSources, PropertySources (including ERI), TopologySources and dashboards — to LM Exchange /
Community standard, and to avoid the defects that import cleanly and then fail silently.

Distilled from building the Proxmox VE suite
([Proxmox-LogicModule](https://github.com/PhilTheITGuy-USA/Proxmox-LogicModule)): 18 modules and 2
dashboards, verified in a real portal and against a live cluster.

Extended with LogicMonitor's own authoring guidance,
[logicmonitor/monitoring-recipes](https://github.com/logicmonitor/monitoring-recipes) at commit
`a7b45b6` (Apache-2.0, © LogicMonitor): Collector snippets, ScriptCache, PowerShell, the
Log/Event/Config/Diagnostic/Remediation module types, and a second, warn-only tier of dashboard
vocabulary from LM's export corpus. That material is paraphrased, not copied, and tagged
**[LM recipes]** wherever it is used — LogicMonitor's word, not yet observed in a portal here. Where
it conflicts with portal experience (e.g. its templates auto-delete instances), the skill keeps the
portal's answer and says so. To refresh, diff the repo from `a7b45b6` and re-tag what changed.

## Layout

```
skill/                       the installable skill -- the only part Claude Code loads
  SKILL.md                   rules that fail silently, workflow, pointers
  references/*.md            scripting contract, PowerShell, other module types, export schema,
                             dashboards, API, suite design
  scripts/lm_lint_module.py  lints module JSON for silent failures
  scripts/lm_dashboards.py   dashboard builder + validator (from LM's published exports)
tests/
  test_tools.py              self-test for the two scripts: known-good, mutation, must-pass cases
  fixtures/proxmox/          known-good exports (Proxmox-LogicModule @ 1543b58, portal-verified)
evals/
  evals.json                 test prompts for skill-vs-no-skill comparison
  inputs/                    files those prompts use
  run_isolated.sh            runs each eval as an isolated `claude -p` from an empty directory
  grade.py                   programmatic grader
  trigger_evals.json         should/shouldn't-trigger queries for description tuning
workspace/                   eval results (gitignored)
```

## Install

The skill is a directory under `~/.claude/skills/`. On this machine it is a junction to `skill/`,
so edits here are live immediately:

```powershell
New-Item -ItemType Junction -Path "$HOME\.claude\skills\logicmonitor-modules" -Target "<repo>\skill"
```

(macOS/Linux: `ln -s <repo>/skill ~/.claude/skills/logicmonitor-modules`.) Or copy `skill/` there.

## Improving it

1. **Edit** `skill/`. Keep SKILL.md short; detail goes in `references/`. Tag claims by provenance
   (portal-confirmed / from LM exports / inferred) and never upgrade an inferred claim without
   evidence.
2. **Self-test the scripts** after touching `skill/scripts/`:
   `python tests/test_tools.py` — must print `ALL PASSED`. When a portal teaches you a new silent
   failure, add a check to the script *and* a mutation case to `tests/test_tools.py`.
3. **Compare with and without the skill** (needs the `claude` CLI; ~6 parallel sessions):
   ```sh
   bash evals/run_isolated.sh iteration-3
   python evals/grade.py workspace/iteration-3
   python evals/grade.py workspace/iteration-3 --tools
   ```
   Runs execute in `~/lm-eval-sandbox/`, outside any repo, so no project CLAUDE.md leaks into the
   no-skill baseline (which also has the Skill tool and the skill's paths denied).
4. **Tune triggering** after changing the description — see `evals/trigger_evals.json` and the
   skill-creator `run_loop` script.

## Results so far

| Iteration | Setup | With skill | Without |
|---|---|---|---|
| 1 | subagents inside the Proxmox repo (its CLAUDE.md leaked into the baseline) | 100% | 85% |
| 2 | isolated `claude -p`, empty directories | 100% | 50% |

Trigger accuracy (`evals/trigger_eval.py`, 20 queries × 3 runs, 2026-10-08): **20/20** with the
original description (LMv1 REST-signing query weakest, 2 of 3 runs). After adding LMv1/401 and
bearer-token wording to the description: **20/20**, LMv1 query 3 of 3. After adding the
monitoring-recipes material (other module types, PowerShell, snippets) to the description, with 4
new queries (LogSource and PowerShell should-trigger; plain PowerShell and Fluent Bit near-misses),
2026-10-14: **24/24**, every query 3 of 3.
