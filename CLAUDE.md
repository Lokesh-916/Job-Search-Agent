# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A LangGraph agent that crawls workatastartup.com (YC) for fresher-friendly, full-time roles open to someone in India: India onsite/hybrid, remote-from-India, or abroad only with credible visa sponsorship. A local Ollama LLM triages, extracts and judges each listing, and the results go into a daily Excel workbook in the project root that the user reviews by hand. **No auto-apply. That feature is out of scope.**

Ranking priorities: remote, then pay, then a low-DSA interview process, then skill fit and company quality. Any development role counts; building with AI is the favourite. The candidate profile is in `profile.yaml` (gitignored). `profile.example.yaml` is the template.

Docs: `docs/PLAN.md` (architecture and milestones), `docs/WORKBOOK.md` (Excel spec), `docs/WAAS_RECON.md` (how WaaS serves data: Algolia index plus Inertia `data-page` JSON). Read the relevant one before changing a pipeline piece.

## Commands

```bash
uv sync                                  # install (Python 3.12, pinned)
uv run job-agent doctor                  # preflight: VRAM, Ollama, WaaS session (never loads a model)
uv run job-agent login                   # one-time visible-browser WaaS login -> secrets/waas_storage_state.json
uv run job-agent fetch                   # WaaS -> data/jobs.db (no LLM)
uv run job-agent report                  # data/jobs.db -> workbooks/jobs_YYYY-MM-DD.xlsx (no LLM)
uv run job-agent run --limit 25          # full pipeline (needs Ollama); --wait-gpu-until HH:MM, --skip-fetch
uv run job-agent notify-test             # Telegram test message
# Laptop-facing (forwarded over SSH to the lab box when lab.host != local; see README table):
# now, schedule <0-23> [--once], unschedule, status, logs, stats, top, show <id>,
# and the LLM helpers ask "<q>", pitch <id>, prep <id>, tailor <id>.
uv run pytest -q                         # all tests (no GPU/Ollama needed)
uv run pytest tests/test_scoring.py::test_buckets   # single test
uv run ruff check . && uv run ruff format .
```
On Windows, prefix with `PYTHONIOENCODING=utf-8` when output contains emoji or ₹.

## Architecture

Data flow (wired in `graph.py` as a LangGraph graph): `sources/waas` (fetch) → `store.py` (SQLite, the source of truth) → `stages.py` (triage → extract → research → assess) → `scoring.py` → `report.py` → `export.py` (xlsx in `workbooks/`) → `notify.py` (Telegram). `research/` holds the company research agent: fixed parallel searches, then a capped `create_agent` tool loop, with a summary-only fallback.

- `llm.py` is the **only** place that knows about providers. Stages call `get_chat_model("<stage>")`. Per-stage overrides (`reasoning`, `num_ctx`) live under `llm.tasks` in config. The model spec is `provider:model`.
- `structured.py`: every LLM call returns a Pydantic schema from `schemas.py` through Ollama JSON-schema constrained decoding, with one self-repair retry that feeds back the validation error.
- `stages.py`: triage → extract → assess. Each result is cached in `llm_results`, keyed by stage, model and an input hash. Swapping the model or changing a posting, the research or the profile triggers a redo; otherwise the work is skipped. Failures are stored and retried on the next run.
- Division of labour: the LLM makes the judgments (eligibility, DSA risk, fit, realistic pay). `scoring.py` is pure arithmetic and gating (hard rejects, tab buckets, weighted score from `config.yaml`), so rankings stay comparable across models.
- `export.py`: one workbook per day, delivered via Telegram. Nothing is read back from it (the user decided against notes and sync). Untriaged jobs count as `pending` and stay out of the tabs.
- `metrics.py`: a `RunMetrics` LangChain callback attached through `metrics.llm_config(stage)` records per-call latency, tokens, load and eval time. `StageTimer`, `event()` and `VramSampler` add stage times, repair and fallback counts and the GPU peak. Runs land in the `runs` and `llm_calls` tables. **Any new LLM call must pass `config=metrics.llm_config(stage)`.** `charts.py` renders light and dark PNGs. The lab PC writes them to `data/charts/` and `job-agent stats` copies them to `docs/metrics/` for the README.
- `lab.py` + `cli._on_lab()`: on a laptop, commands re-run themselves on the lab box via SSH (`$HOME/.local/bin/uv run job-agent ...`, wrapped in `scripts/with_ollama.sh` for LLM commands). Schedules are user crontab lines tagged `# job-agent:schedule`. `--once` lines carry a date guard. `logs/.running` prevents overlapping runs.
- `assistant.py`: on-demand helpers (`pitch`, `prep`, `tailor` = structured outputs; `ask` = `create_agent` over DB tools). They are guarded by a VRAM check.
- WaaS session: `bootstrap()` loads `/companies` headless to get a fresh, per-user Algolia key and re-saves cookies. Job detail pages are fetched with plain httpx using those cookies.
- Tests use `tests/fakes.py::FakeStructuredLLM`. Never write a test that needs a live Ollama.

## Environment notes

- Lab PC: Ubuntu 24.04, Xeon w5-2565X (36 threads), 62 GB RAM, RTX 2000 Ada 16 GB, CUDA 13, only ~66 GB disk free. Docker is installed but its daemon is off. sudo needs a password, so ask the user to run sudo commands.
- From this Windows laptop, SSH to the lab PC only works with the **Windows OpenSSH client**. From the Bash tool call `/c/Windows/System32/OpenSSH/ssh.exe`, which keeps bash quoting sane. Git Bash's own `ssh` fails auth, and PowerShell mangles nested quotes.
- Lab PC layout: repo at `~/projects/Job-Search-Agent` (own `config.yaml`: localhost Ollama, `min_free_mib: 13000`), uv at `~/.local/bin/uv`, user-space Ollama at `~/.local/ollama/bin/ollama` (no system service). Models live in `~/.ollama/models`. `scripts/lab_run.sh` starts Ollama, runs `job-agent run "$@"` and always stops Ollama. Scheduled runs are user crontab entries. Logs go to `logs/`.
- To pull a model without touching VRAM, run `ollama serve` with `CUDA_VISIBLE_DEVICES=-1`.
- The Playwright Chromium download times out here, so config uses `browser.channel: chrome` (the installed Chrome).
- Don't write Python containing escape sequences through bash heredocs. Use the Edit/Write tools.

## Hard rules

- **Never** add Claude as co-author (no `Co-Authored-By` trailer) and never mention Claude or AI in commits, PRs, README or code. The user is the sole author.
- Make small, frequent commits and push each one to `origin main`.
- **The LLM host is off-limits for inference until the user says go.** The lab PC (`amaloch@100.104.107.17` over Tailscale) runs other heavy GPU jobs. Do not pull, load or run models there and do not run anything that hits Ollama.
- The model must stay swappable through config. Don't hard-code model-specific behavior outside `llm.py`.
