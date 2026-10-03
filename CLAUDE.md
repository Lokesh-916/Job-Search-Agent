# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A LangGraph agent that crawls workatastartup.com (YC) for fresher or intern-level roles. A local Ollama LLM extracts and scores each listing, and the results are exported to a local Excel sheet that the user reviews by hand. **No auto-apply. That feature is out of scope.**

Ranking priorities, in order: remote/WFH, high pay, non-DSA interview process, then no or internship-only experience required.

The full plan is in `docs/PLAN.md` and the Excel output spec is in `docs/WORKBOOK.md`. Read both before building pipeline pieces.

## Commands

```bash
uv sync                                  # install (Python 3.12, pinned)
uv run job-agent doctor                  # preflight: VRAM, Ollama, WaaS session (never loads a model)
uv run pytest -q                         # all tests (no GPU/Ollama needed)
uv run pytest tests/test_llm.py::test_task_override_wins   # single test
uv run ruff check . && uv run ruff format .
```

## Architecture

- `src/job_agent/settings.py`: typed config from `config.yaml` (falls back to `config.example.yaml`). Secrets come from `.env`.
- `src/job_agent/llm.py`: the **only** place that knows about providers. Nodes call `get_chat_model("<task>")`. Per-task overrides (`reasoning`, `num_ctx`, ...) live under `llm.tasks` in config. The model spec is `provider:model`, e.g. `ollama:qwen3:14b`.
- `src/job_agent/preflight.py`: cheap pre-run checks. The VRAM guard only runs where `nvidia-smi` exists, which means the lab PC.
- Planned pipeline: LangGraph pipeline (fetch → dedupe → triage → extract → company research → assess → score → SQLite → daily xlsx → Telegram). The LLM does the judgment work. Code does arithmetic, gating and IO.
- Tests use fake/stub chat models. Never write a test that needs a live Ollama.

## Environment notes

- Lab PC: Ubuntu 24.04, Xeon w5-2565X (36 threads), 62 GB RAM, RTX 2000 Ada 16 GB, CUDA 13, only ~66 GB disk free. Docker is installed but its daemon is off. sudo needs a password, so ask the user to run sudo commands.
- From this Windows laptop, SSH to the lab PC only works with the **Windows OpenSSH client** (the PowerShell tool), not Git Bash's `ssh`.
- `.github/workflows/ci.yml` stays uncommitted until git's credential has the `workflow` scope.

## Hard rules

- **Never** add Claude as co-author (no `Co-Authored-By` trailer) and never mention Claude or AI in commits, PRs, README or code. The user is the sole author.
- Make small, frequent commits and push each one to `origin main`.
- **The LLM host is off-limits for inference until the user says go.** The lab PC (`amaloch@100.104.107.17` over Tailscale, RTX 2000 Ada 16 GB) runs other heavy GPU jobs. Do not pull, load or run models there and do not run tests that hit Ollama. Build the harness only.
- The model must stay swappable through config (an Ollama model tag). Don't hard-code model-specific behavior outside the LLM adapter layer.
