#!/usr/bin/env bash
# Morning job for the batch feed: fetch all sources, build the sheet, send to every member.
# Installed as a crontab line by the coordinator; logs go to logs/community-*.log.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
exec >>"logs/community-$(date +%F).log" 2>&1
echo "== $(date) start"
git pull -q --ff-only || echo "git pull failed; using the current checkout"
"$HOME/.local/bin/uv" sync -q
PYTHONIOENCODING=utf-8 COLUMNS=140 "$HOME/.local/bin/uv" run job-agent community daily
echo "== $(date) exit $?"
