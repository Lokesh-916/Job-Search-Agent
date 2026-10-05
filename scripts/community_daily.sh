#!/usr/bin/env bash
# Morning job for the batch feed: fetch all sources, build the sheet, add LLM notes if the GPU
# is free (skipped when busy), then send to every member.
# Installed as a crontab line by the coordinator; logs go to logs/community-*.log.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
exec >>"logs/community-$(date +%F).log" 2>&1
echo "== $(date) start"
git pull -q --ff-only || echo "git pull failed; using the current checkout"
UV="$HOME/.local/bin/uv"
"$UV" sync -q
export PYTHONIOENCODING=utf-8 COLUMNS=140
"$UV" run job-agent community refresh
scripts/with_ollama.sh "$UV" run job-agent community enrich --daily \
    || echo "enrich failed; sending without notes"
"$UV" run job-agent community send
echo "== $(date) exit $?"
