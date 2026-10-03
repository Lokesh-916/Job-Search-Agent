#!/usr/bin/env bash
# Run the pipeline on the GPU box: start a user-space Ollama, run, and always stop Ollama
# afterwards so the VRAM goes back to whatever else runs on the machine.
#
#   scripts/lab_run.sh --limit 25 --wait-gpu-until 09:00     # test run
#   scripts/lab_run.sh --wait-gpu-until 09:00                # full run
set -uo pipefail
cd "$(dirname "$0")/.."

OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/ollama/bin/ollama}"
UV="${UV:-$HOME/.local/bin/uv}"
mkdir -p logs
exec >>"logs/run-$(date +%F-%H%M).log" 2>&1
echo "== $(date) start: $*"

git pull -q --ff-only || echo "git pull failed; using the current checkout"
"$UV" sync -q

export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_NUM_PARALLEL=2 OLLAMA_MAX_LOADED_MODELS=1
"$OLLAMA_BIN" serve >>logs/ollama-serve.log 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null; wait "$OLLAMA_PID" 2>/dev/null; echo "== $(date) ollama stopped"' EXIT
sleep 5

"$UV" run job-agent run "$@"
echo "== $(date) job-agent exit code $?"
