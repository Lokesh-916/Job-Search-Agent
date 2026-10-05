# 🎓 Placement Feed

> One Telegram message every morning with the tech jobs, paid internships, hackathons and tech events our batch should know about.

Placement season means checking a dozen career pages, Unstop, Devfolio and LinkedIn every day, and still missing things. This bot does the checking for the whole batch. Every morning at 8 it reads the career pages of 95 companies and a handful of platforms, keeps what is **in India, technical and open to freshers**, and sends everyone the same short message plus an Excel sheet with the full list.

It's free, it runs on our lab machine, and there's no personalisation or ranking of people. Everyone gets the same curated list.

## 📬 What arrives every morning

| | |
|---|---|
| 🏛️ **Big names today** | Up to three Big Tech or MNC openings at the top of every message, never the same one twice in two weeks |
| 💼 **Jobs** | Entry-level tech roles in India: SWE, full stack, backend, frontend, mobile, data, ML/AI, DevOps, security, embedded, QA |
| 🎓 **Paid internships** | Straight from company career pages (Microsoft, Qualcomm, Stripe, Rubrik…). Marketplace internship listings are left out: too many are unpaid or not genuine |
| 🏆 **Hackathons** | Open hackathons, online or in India, with dates, deadline and prizes |
| 🎤 **Tech events** | Meetups, workshops and study jams, including GDG chapters at Indian campuses |
| 📊 **The sheet** | Everything above in one workbook, with a 🆕 mark on what appeared since yesterday |

The message itself stays short: the big names, what's new today, a few highlights per category, and the hackathons closing soonest. The sheet has the rest.

## 🏢 Where it looks

| | Sources |
|---|---|
| 🏛️ Big Tech and MNCs | Microsoft, Amazon, NVIDIA, Qualcomm, Adobe, Intel, Cisco, Salesforce, HPE, Cadence, Micron, Accenture, PayPal, Mastercard, Visa, Morgan Stanley, Deutsche Bank, State Street, NXP, KLA, Bosch… |
| 🦄 Unicorns and startups | Swiggy, CRED, Meesho, Groww, Paytm, Zscaler, HighRadius, Stripe, Databricks, OpenAI, Notion, Canva, Sarvam AI, HackerRank… |
| 🌐 Everyone else | Adzuna India search, Unstop fresher jobs |
| 🏆 Events | Hack2skill (Google, AMD, Snowflake… hackathons), Devfolio, Devpost, Google Developer Groups, Unstop |

Every company in [`config/companies.yaml`](config/companies.yaml) was checked to have a live public job board with openings in India. Adding a company is one line, so if yours is missing, send `/suggest`.

## 🧹 How the list is curated

```
95 career pages + platforms ─▶ India only ─▶ tech roles only ─▶ freshers only ─▶ 📲 one message + sheet
        ~14,000 postings                                                          ~300 jobs · paid internships
```

- **India only:** any Indian city, or remote from India. Multi-city postings count if one city is in India.
- **Tech only:** sales, HR, finance, operations and support roles are dropped.
- **Freshers only:** senior, lead, manager and "II/III" titles are dropped, along with anything asking for 2+ years. The bot reads the job description, not just the title. Where a degree changes the bar ("Bachelor's + 2 years or Master's + 0"), the Bachelor's figure counts.
- **For B.Tech students:** PhD, postdoc and MBA-only roles are skipped.
- **No junk:** test postings are skipped, and internships come only from company career pages.
- **LLM notes:** when the lab GPU is free, a local LLM reads each posting and notes whether freshers really qualify, which batches and branches are eligible, the CTC, the deadline and the key skills. The model runs on our own machine, so nothing is sent to an AI service.
- **Honest about gaps:** if a big company's posting doesn't say what experience it needs, the role goes to a separate *Check experience* tab instead of being guessed.

## 🤖 Using the bot

1. Open the batch bot on Telegram and press **Start**.
2. Send `/join <your roll number>`.
3. Once the coordinator approves you, the morning message starts arriving.

| Command | What it does |
|---|---|
| `/today` | Today's message and the full sheet |
| `/jobs` | Latest jobs |
| `/internships` | Paid internships |
| `/events` | Hackathons and tech events |
| `/suggest <text>` | Missing company, wrong listing, any idea (`/suggest add Zoho jobs`) |
| `/forget` | Delete your data and leave |

**Privacy:** the bot stores your Telegram name, username and roll number, only to manage who receives the feed. `/forget` deletes all of it. Only roll numbers from the batch can join, and the coordinator approves each request.

## 🛠️ Run it for your own batch

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp config.example.yaml config.yaml    # set community: roll_prefix / roll_min / roll_max / roll_exclude
cp .env.example .env                  # COMMUNITY_BOT_TOKEN (from @BotFather), TELEGRAM_CHAT_ID (the coordinator),
                                      # optional ADZUNA_APP_ID / ADZUNA_APP_KEY (free at developer.adzuna.com)
uv run job-agent community refresh    # fetch everything and build today's sheet (no messages sent)
uv run job-agent community send --me  # preview the message in the coordinator's chat
```

Then run it for real:

- **The bot:** `deploy/job-agent-community-bot.service` is a systemd user service that runs `job-agent community bot`.
- **The morning send:** a crontab line, `0 8 * * * /path/to/scripts/community_daily.sh`. It refreshes, adds LLM notes if a GPU is free, then sends.

| Coordinator command | What it does |
|---|---|
| `job-agent community refresh` | Fetch every source, rebuild the sheet |
| `job-agent community enrich` | Add LLM notes (needs [Ollama](https://ollama.com); the model is set in `config.yaml`) |
| `job-agent community send` | Send today's feed (`--me` to preview) |
| `job-agent community users` | Who joined and their status |

The coordinator's chat also gets admin commands in the bot: `/pending` (approve or reject), `/users`, `/broadcast`, `/suggestions`, `/refresh`, `/sendnow`.

**Stack:** Python · httpx · python-telegram-bot · SQLite · xlsxwriter · LangChain + Ollama for the optional notes. Sources are the public JSON behind Greenhouse, Lever, Ashby, SmartRecruiters, Workday and amazon.jobs, the Adzuna API, and the Unstop, Devfolio, Devpost and GDG listings.

---

Made for the AI&DS batch of 2027 at IIITDM Kurnool. If it helped you land something, tell me. 🙌
