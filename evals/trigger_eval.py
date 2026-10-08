#!/usr/bin/env python3
"""
Measure how reliably the INSTALLED skill triggers, from a neutral directory. Windows-safe.

    python evals/trigger_eval.py [--description-file new.txt] [--runs 3] [--workers 8]
                                 [--ids 0,3,7]   # subset (e.g. a held-out split)

Each query runs as `claude -p <query> --max-turns 1` from ~/lm-eval-sandbox/trigger, so no
project CLAUDE.md loads. "Triggered" = Claude's first turn invokes the Skill tool for this skill,
or Reads its SKILL.md. With --description-file, SKILL.md's description is swapped for the run
and always restored afterwards.

Why not skill-creator's run_eval.py: it reads pipes with select(), which Windows does not
support, and it tests a temporary copy while the real installed skill competes with it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = ROOT / "skill" / "SKILL.md"
SKILL_NAME = "logicmonitor-modules"
SANDBOX = Path.home() / "lm-eval-sandbox" / "trigger"
MODEL = "claude-opus-5-5"


def triggered(stdout: str) -> bool:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            payload = json.dumps(block.get("input", {}))
            if block.get("name") == "Skill" and SKILL_NAME in payload:
                return True
            if block.get("name") == "Read" and SKILL_NAME in payload and "SKILL.md" in payload:
                return True
    return False


def run_query(query: str, timeout: int) -> bool:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        proc = subprocess.run(
            ["claude", "-p", query, "--model", MODEL, "--max-turns", "1",
             "--output-format", "stream-json", "--verbose"],
            cwd=SANDBOX, env=env, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
        return triggered(proc.stdout)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return triggered(out)


def set_description(text: str, new: str | None) -> str:
    if new is None:
        return text
    body = new.strip().replace("\n", " ")
    return re.sub(r"^description: .*$", lambda _: "description: " + body, text, count=1, flags=re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-set", default=str(ROOT / "evals" / "trigger_evals.json"))
    ap.add_argument("--description-file")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--ids", help="comma-separated query indexes to run")
    ap.add_argument("--out", help="write per-query results JSON here")
    args = ap.parse_args()

    items = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))
    ids = [int(i) for i in args.ids.split(",")] if args.ids else list(range(len(items)))
    SANDBOX.mkdir(parents=True, exist_ok=True)

    original = SKILL_MD.read_text(encoding="utf-8")
    new_desc = Path(args.description_file).read_text(encoding="utf-8") if args.description_file else None
    try:
        SKILL_MD.write_text(set_description(original, new_desc), encoding="utf-8")
        jobs = [(i, r) for i in ids for r in range(args.runs)]
        with ThreadPoolExecutor(args.workers) as pool:
            hits = list(pool.map(lambda job: run_query(items[job[0]]["query"], args.timeout), jobs))
    finally:
        SKILL_MD.write_text(original, encoding="utf-8")

    results, correct = [], 0
    for i in ids:
        rate = sum(h for (j, _), h in zip(jobs, hits) if j == i) / args.runs
        want = items[i]["should_trigger"]
        ok = (rate >= 0.5) == want
        correct += ok
        results.append({"id": i, "query": items[i]["query"], "should_trigger": want,
                        "trigger_rate": rate, "pass": ok})
        print(f"{'PASS' if ok else 'FAIL'}  [{i:2}] want={'Y' if want else 'N'} rate={rate:.2f}  "
              f"{items[i]['query'][:90]}")
    print(f"\nscore {correct}/{len(ids)}")
    if args.out:
        Path(args.out).write_text(json.dumps({"score": correct, "total": len(ids),
                                              "results": results}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
