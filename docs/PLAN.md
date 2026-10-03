# Implementation Plan

## Goal
Every day, find fresher-friendly jobs on Work at a Startup (WaaS) that are open to someone in India. Research each company, then rank the jobs for an **AI engineer** profile in this order: remote first, then high pay, then a low-DSA interview process. Deliver **one Excel workbook per day**. No auto-apply.

## Deployment
| Where | What |
|---|---|
| Laptop | Development, one-off runs, one-time WaaS login in a visible browser (exports `storage_state.json`) |
| Lab PC (Ubuntu, RTX 2000 Ada 16 GB) | Ollama, SearXNG (Docker), scheduled runs (systemd timer), Telegram delivery |

The laptop reaches Ollama on the lab PC over Tailscale. The session file and `.env` are never committed.
**Rollout:** manual one-off runs until the output is right, then the schedule is turned on.

## Pipeline (LangGraph)
```
preflight (VRAM guard, session valid?)
 → fetch_listings (Playwright, logged in; capture JSON responses if available)
 → dedupe (content hash; only new/changed jobs continue)
 → triage (LLM, cheap: obviously senior / clearly not eligible → reject with reason)
 → extract (LLM, JSON-schema constrained, one call per job, parallel)
 → company_research (ReAct sub-agent, cached 14 days per company)
 → assess (LLM: India eligibility, DSA risk, fit, realistic salary, all with evidence)
 → score (weights from config) → persist (SQLite)
 → export (daily .xlsx) → notify (Telegram + file)
```
- **LLM vs code split.** The LLM handles judgment: triage, extraction, eligibility, DSA risk, fit, salary estimate, summaries and outreach drafts. Code handles arithmetic and plumbing: currency conversion, weighted score, dedupe, storage and export.
- **Hard gates:** not open to India → `Rejected` tab. Below 9 LPA → `Rejected`. Unclear eligibility → `Needs Review` (never silently dropped).
- **Failure handling:** a schema-validation failure gets one retry with the error passed back to the model, then the job goes to `Needs Review`. LangGraph checkpoints (SQLite) let a crashed run resume.

## Company research sub-agent
A tool-calling agent, capped at about 8 tool calls per company, run only for companies that pass triage.

| Tool | Source |
|---|---|
| `web_search` | Self-hosted SearXNG (free, no rate limits). DuckDuckGo as fallback |
| `fetch_page` | Crawl4AI page → markdown |
| `yc_directory` | ycombinator.com/companies: batch, team size, status, founders |
| `hn_search` | HN Algolia API: launches, "Who's hiring", discussions |
| MCP tools | Playwright MCP via `langchain-mcp-adapters` for pages that need JavaScript or interaction |

It collects: what the company does, stage and funding, team size, founders and their LinkedIn, employee sentiment (Glassdoor, AmbitionBox, Reddit, Blind snippets), interview experiences, and salary data points (Levels.fyi, AmbitionBox, Glassdoor). Every claim keeps its source URL.

## Models
- Default: `qwen3:14b` (Q4_K_M, about 9.3 GB). Thinking is off for extraction and on for assessment and research.
- Contender: `gpt-oss:20b`. Also benchmarked: `deepseek-r1:14b` and `qwen2.5-coder:14b`.
- Context: 16k by default. Use `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` to fit 32k when needed.
- Swapped in `config.yaml` (`provider:model`). Any OpenAI-compatible server also works.
- **Eval harness:** about 50 hand-labeled listings, measuring per-field accuracy, JSON validity rate and seconds per job for each model.

## Stack
Python 3.12, uv, LangGraph, langchain-ollama, langchain-mcp-adapters, Playwright, Crawl4AI, Pydantic, SQLite, xlsxwriter, Typer, pytest (fake LLM, no GPU in tests), ruff, GitHub Actions.

## Milestones
| # | Milestone | GPU |
|---|---|---|
| 0 | Scaffold: uv, config, CLI, CI | – |
| 1 | WaaS inspection, login session export, fetcher → SQLite | – |
| 2 | Schemas, triage/extract nodes, prompts, fake-LLM tests | – |
| 3 | Scoring, FX conversion, daily workbook export, status round-trip | – |
| 4 | Company research sub-agent + tools, SearXNG setup | – |
| 5 | LangGraph wiring, checkpoints, VRAM guard, CLI `run` | – |
| 6 | Ollama install, model pulls, eval harness, **first one-off run** | ✅ on go |
| 7 | Tune prompts and weights until the output is right | ✅ |
| 8 | systemd timer + Telegram delivery | ✅ |

**Later:** a user-agnostic profile (onboarding), multi-source universal search (Wellfound, HN, Remote OK and others) through source adapters, and a chat agent over the job database.
