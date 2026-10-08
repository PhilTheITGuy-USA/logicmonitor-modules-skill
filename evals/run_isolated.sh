#!/usr/bin/env bash
# Run each eval as an isolated `claude -p` process from an empty directory outside any repo,
# so no project CLAUDE.md or project memory loads. Usage: evals/run_isolated.sh <iteration-N>
# Results land in workspace/<iteration-N>/; then run evals/grade.py on that directory.
set -u
ITER="$1"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WS="$REPO/workspace"
INPUTS="$REPO/evals/inputs"
SKILL="$REPO/skill"
SANDBOX_ROOT=/c/Users/philt/lm-eval-sandbox/$ITER
MODEL=claude-opus-5-5
TOOLS="Read Write Edit Bash Glob Grep"

declare -A PROMPTS FILES
PROMPTS[truenas-batchscript-datasource]="Write a LogicMonitor BatchScript DataSource that monitors TrueNAS SCALE storage pool capacity and health using the TrueNAS REST API (GET /api/v2.0/pool returns every pool). I need the Active Discovery Groovy, the collection Groovy, and an importable module JSON. Save them as files in ./outputs/ along with a short NOTES.md explaining your choices."
FILES[truenas-batchscript-datasource]=""
PROMPTS[nodata-diagnosis]="My new LogicMonitor DataSource (./Acme_Array_Volumes.json) discovers volume instances fine and 'Test Collection Script' in the portal shows output that looks right, but every datapoint on every instance shows No Data. What's wrong? Save a fixed Acme_Array_Volumes.json and an EXPLANATION.md in ./outputs/. Do not modify the original file."
FILES[nodata-diagnosis]="$INPUTS/Acme_Array_Volumes.json"
PROMPTS[truenas-dashboard]="Build me an importable LogicMonitor dashboard JSON for my TrueNAS modules (definitions in ./modules_for_dashboard.json): a table showing every pool's used percent, capacity and free space, and a line graph of CPU usage for all nodes. Everything lives on one TrueNAS resource as instances. Save the dashboard JSON and a short NOTES.md with import instructions in ./outputs/."
FILES[truenas-dashboard]="$INPUTS/modules_for_dashboard.json"

COMMON="Work only inside the current directory. Do not ask questions; make reasonable assumptions and note them."

run_one() {
    local eval="$1" config="$2"
    local box="$SANDBOX_ROOT/$eval-$config"
    local dest="$WS/$ITER/eval-$eval/$config/run-1"
    rm -rf "$box"; mkdir -p "$box/outputs" "$dest"
    for f in ${FILES[$eval]}; do cp "$f" "$box/"; done

    local prompt extra=()
    if [ "$config" = with_skill ]; then
        prompt="Use the logicmonitor-modules skill (installed at $SKILL; read its SKILL.md and use its scripts). ${PROMPTS[$eval]} $COMMON"
        extra=(--add-dir "$SKILL")
    else
        prompt="${PROMPTS[$eval]} $COMMON Work from your own knowledge only: do not use any skill and do not read anything under ~/.claude or $REPO."
        extra=(--disallowedTools "Skill" "Read(~/.claude/**)" "Glob(~/.claude/**)" "Grep(~/.claude/**)"
                     "Read(/$REPO/**)" "Glob(/$REPO/**)" "Grep(/$REPO/**)")
    fi

    local start=$(date +%s%3N)
    (cd "$box" && claude -p "$prompt" --model "$MODEL" --output-format stream-json --verbose \
        --permission-mode acceptEdits --allowedTools $TOOLS "${extra[@]}" \
        > "$dest/transcript.jsonl" 2> "$dest/stderr.txt")
    local end=$(date +%s%3N)

    rm -rf "$dest/outputs"; cp -r "$box/outputs" "$dest/outputs"
    python - "$dest" "$start" "$end" <<'PY'
import json, sys
dest, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
tokens = 0
for line in open(dest + "/transcript.jsonl", encoding="utf-8", errors="ignore"):
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "result":
        u = ev.get("usage") or {}
        tokens = sum(u.get(k, 0) or 0 for k in ("input_tokens", "output_tokens",
                     "cache_read_input_tokens", "cache_creation_input_tokens"))
json.dump({"total_tokens": tokens, "duration_ms": end - start,
           "total_duration_seconds": round((end - start) / 1000, 1)},
          open(dest + "/timing.json", "w"), indent=2)
PY
    echo "done: $eval/$config ($(( (end - start) / 1000 ))s)"
}

for eval in truenas-batchscript-datasource nodata-diagnosis truenas-dashboard; do
    mkdir -p "$WS/$ITER/eval-$eval"
    python - "$REPO/evals/evals.json" "$eval" "$WS/$ITER/eval-$eval/eval_metadata.json" <<'PY'
import json, sys
evals = json.load(open(sys.argv[1]))["evals"]
names = {1: "truenas-batchscript-datasource", 2: "nodata-diagnosis", 3: "truenas-dashboard"}
e = next(e for e in evals if names[e["id"]] == sys.argv[2])
json.dump({"eval_id": e["id"], "eval_name": sys.argv[2], "prompt": e["prompt"],
           "assertions": e.get("assertions", [])}, open(sys.argv[3], "w"), indent=2)
PY
    for config in with_skill without_skill; do
        run_one "$eval" "$config" &
    done
done
wait
echo ALL DONE
