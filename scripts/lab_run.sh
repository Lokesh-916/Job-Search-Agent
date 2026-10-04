#!/usr/bin/env bash
# One pipeline run on the GPU box, logged to logs/run-*.log. Used by `job-agent now`
# and by the cron entries `job-agent schedule` installs.
#
#   scripts/lab_run.sh --limit 25 --wait-gpu-until 09:00     # test run
#   scripts/lab_run.sh --wait-gpu-until 09:00                # full run
set -uo pipefail
cd "$(dirname "$0")/.."

UV="${UV:-$HOME/.local/bin/uv}"
mkdir -p logs
exec >>"logs/run-$(date +%F-%H%M).log" 2>&1
echo "== $(date) start: $*"

if [ -e logs/.running ] && kill -0 "$(cat logs/.running)" 2>/dev/null; then
    echo "== another run (pid $(cat logs/.running)) is in progress; skipping"
    exit 0
fi
echo $$ > logs/.running
trap 'rm -f logs/.running; echo "== $(date) finished"' EXIT

git pull -q --ff-only || echo "git pull failed; using the current checkout"
"$UV" sync -q
scripts/with_ollama.sh "$UV" run job-agent run "$@"
echo "== $(date) job-agent exit code $?"
