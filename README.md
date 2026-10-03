# 🕵️ Job-Search-Agent

> A local-LLM agent that hunts YC startup jobs so I don't have to doom-scroll job boards.

Every day it pulls fresher-friendly roles from [Work at a Startup](https://www.workatastartup.com), digs into each company, judges every job against my profile with an LLM running on my own GPU, and hands me one tidy Excel workbook plus a Telegram ping. I still apply myself. This is a scout, not an auto-apply bot.

## 🎯 What it optimizes for

| | Signal |
|---|---|
| 🏠 | Remote from India first, then Hyderabad › Bengaluru › rest of India |
| 💰 | Realistic pay in ₹ LPA (dollar salaries converted at live rates) |
| 🧠 | Practical interviews over LeetCode marathons |
| 🤖 | Building with AI: agents, LLM apps, AI products |
| 🎓 | Roles a fresher can actually get |

## 🧩 How it works

```
fetch ─▶ triage ─▶ extract ─▶ research ─▶ assess ─▶ score ─▶ 📊 workbook ─▶ 📲 Telegram
```

- **Fetch:** reads WaaS's own search index and job pages. Fast, structured, no HTML guessing.
- **Triage / extract / assess:** typed JSON from a local LLM, with self-repair when the model slips.
- **Research:** a small tool-using agent checks reviews, interview stories, salaries and funding, and drafts a founder note.
- **Score:** plain arithmetic on the LLM's judgments, so rankings stay comparable across models.
- **Cached everywhere:** only new or changed postings cost GPU time.

**Stack:** LangGraph · Ollama (`qwen3:14b` by default, one config line to swap) · Playwright · SQLite · xlsxwriter

## ⚡ Try it

```bash
uv sync
cp config.example.yaml config.yaml && cp profile.example.yaml profile.yaml   # make them yours
uv run job-agent login      # sign in to WaaS once
uv run job-agent doctor     # GPU, Ollama and session checks
uv run job-agent run --limit 25
```

The workbook lands in `workbooks/`. Set Status and notes there and they carry over to tomorrow's file.
