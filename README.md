# 🕵️ Job-Search-Agent

> A local-LLM agent that hunts YC startup jobs so I don't have to doom-scroll job boards.

It crawls [Work at a Startup](https://www.workatastartup.com) for **fresher / new-grad / intern-friendly** roles, reads every listing with a locally hosted LLM, ranks them by what actually matters to me, and drops the results into a tidy Excel sheet. I still apply myself. This is a scout, not an auto-apply bot.

## 🎯 What it optimizes for

| Priority | Signal |
|---|---|
| 🏠 1 | Remote / WFH |
| 💰 2 | High pay (US startups, salary + equity) |
| 🧠 3 | Practical interviews (take-homes, pairing) over LeetCode grinding |
| 🎓 4 | Zero experience or internship-only requirements |

## 🧩 How it works

```
 crawl ──▶ pre-filter ──▶ LLM extract & judge ──▶ score ──▶ store ──▶ 📊 jobs.xlsx
```

- **LangGraph** orchestrates the pipeline
- **Ollama** serves the model on a local GPU, so there are no API keys or bills
- **Swappable models**: Qwen3, gpt-oss, DeepSeek-R1-Distill and others, changed with one config line
- **Playwright / Crawl4AI** do the browsing

## 🚧 Status

Early days. The plan is being finalized and code is coming soon.
