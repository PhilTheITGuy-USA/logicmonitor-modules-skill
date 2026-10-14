# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The workspace-level `..\CLAUDE.md` already covers how this repo relates to the suites and the
`~\.claude\skills\logicmonitor-modules` junction. This file covers working *on* the skill.

## Three parts, one shipped

- `skill/` is the only part Claude Code loads, and it is live everywhere the moment you save (the
  junction). A broken edit breaks every open suite session, not just this one.
  - `SKILL.md` stays short: the silent-failure rules, the workflow, a table pointing into
    `references/*.md`. Detail goes in the references.
  - `scripts/lm_lint_module.py` and `scripts/lm_dashboards.py` are standalone, stdlib-only Python 3
    so they run from any suite without installing anything. Keep them that way.
- `tests/` is the self-test for those two scripts.
- `evals/` measures whether the skill helps (with vs without) and whether it triggers.

## Commands

```sh
python tests/test_tools.py                       # must end with ALL PASSED; run after any skill/scripts/ change
python skill/scripts/lm_lint_module.py <file|dir> [--strict]
python skill/scripts/lm_dashboards.py check <dashboard.json ...> --modules <files|dirs>

bash evals/run_isolated.sh iteration-N           # needs the claude CLI; ~6 parallel sessions
python evals/grade.py workspace/iteration-N [--tools]
python evals/trigger_eval.py [--description-file new.txt] [--runs 3] [--workers 8] [--ids 0,3,7]
```

`test_tools.py` has no per-case filter; it is one fast run of everything. To debug a single case,
write that mutation to a file and run the relevant script on it directly.

## How the self-test works

`tests/test_tools.py` runs the scripts as subprocesses against:

1. **Known-good** — `tests/fixtures/proxmox/` (17 modules + 2 dashboards, portal-verified). Must lint
   with zero ERRORs and pass `check` with reference resolution. A new check that fires on these
   fixtures is wrong, or the fixtures need a deliberate, portal-verified refresh.
2. **Planted bugs** — `evals/inputs/Acme_Array_Volumes.json` must fail lint with ≥5 ERRORs. This file
   is shared with the `nodata-diagnosis` eval; changing it changes both.
3. **Mutations** — `module_mutations()`, `other_module_mutations()` and `dashboard_mutations()` each
   build a module or dashboard with exactly one silent-failure defect and require exit 1. Adding a
   check means adding a mutation here; a check that cannot go red is treated as worse than none.
4. **Must-pass** — `module_must_pass()` (e.g. LM's built-in `ssh.pass`) must exit 0, and
   `dashboard_corpus_values()` must exit 0 *with* a `WARN`. These guard against false positives
   when tightening a check.

New cases all passing proves nothing: confirm each fails for its intended reason (read its ERROR
line) and that the pre-change script let it through (`git show HEAD:skill/scripts/<script>`).

Lint output contract: `ERROR` lines and exit 1 for defects; `WARN` is heuristic (exit 1 only with
`--strict`). The tests key on exit code and on lines starting `ERROR`.

## Evals

- `run_isolated.sh` copies inputs into `~/lm-eval-sandbox/<iteration>/` and runs `claude -p` there,
  outside any repo, so no CLAUDE.md leaks into the baseline. The baseline also has the Skill tool and
  the skill/repo paths denied. Paths and the model id are hard-coded at the top of the script.
  Iteration 1 ran inside the Proxmox repo and its baseline was contaminated (85% vs 50% isolated) —
  don't run evals from inside a repo.
- `grade.py` writes `grading.json` into each `workspace/<iter>/eval-*/<config>/run-*/`; `--tools`
  also runs the bundled scripts on outputs and checks for contamination.
- `trigger_eval.py` tests the *installed* skill and, with `--description-file`, temporarily swaps
  SKILL.md's `description` (always restored). It exists because skill-creator's `run_eval.py` uses
  `select()` on pipes, which fails on Windows.
- Record new results in the README's "Results so far" table.

## Writing rules into the skill

- Tag every claim by provenance — **portal-confirmed**, **from LM's published exports**,
  **[LM recipes]** (LogicMonitor's `monitoring-recipes` guidance @ `a7b45b6`), or **inferred** — and
  never upgrade a claim without evidence. Portal experience beats LM recipes where they conflict.
- The dashboard checker has two tiers: first-tier tuples (import-tested; anything else is an error)
  and `UNVERIFIED_*` (LM corpus; warn only). Promote a value only after a portal keeps it on
  import/export; values a portal dropped stay errors regardless of any corpus.
- Schema and vocabularies (`REFERENCE_KEYS`, enum tuples in `lm_dashboards.py`) are copied from
  LogicMonitor's published exports (`github.com/logicmonitor/dashboards`), never invented. Keep that
  sourcing when extending them.
- Changing the SKILL.md `description` changes triggering: rerun `trigger_eval.py` afterwards.
