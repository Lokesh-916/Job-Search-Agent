#!/usr/bin/env bash
# Run a command with Ollama available, starting a user-space Ollama only if none is running,
# and stopping it again afterwards so the GPU memory is released.
#
#   scripts/with_ollama.sh uv run job-agent ask "remote AI jobs above 20 LPA?"
set -uo pipefail
cd "$(dirname "$0")/.."

OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/ollama/bin/ollama}"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_NUM_PARALLEL=2 OLLAMA_MAX_LOADED_MODELS=1
mkdir -p logs

if curl -fs "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    "$@"  # already up (e.g. a scheduled run is in progress): share it
    exit $?
fi

"$OLLAMA_BIN" serve >>logs/ollama-serve.log 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null; wait "$OLLAMA_PID" 2>/dev/null' EXIT
for _ in $(seq 30); do
    curl -fs "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
    sleep 1
done
"$@"
