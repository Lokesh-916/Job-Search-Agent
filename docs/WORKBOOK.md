# Daily Workbook: `output/jobs_YYYY-MM-DD.xlsx`

## Tabs
| Tab | Contents |
|---|---|
| 📊 Dashboard | Run stats, counts per tab, top 10 picks, new today, model used |
| 🔥 Top Picks | Score ≥ threshold, across all categories |
| 🌍 Remote · Foreign | Remote roles at non-Indian companies open to India (the dollar cheat code) |
| 🏠 Remote · India | Remote roles at Indian companies |
| 🏢 India · Onsite/Hybrid | Office or hybrid roles in India |
| 🔎 Needs Review | Unclear eligibility or salary, or extraction failed |
| 🏭 Companies | One row per company: research, sentiment, founders, outreach draft |
| 🗑️ Rejected | Everything filtered out, **with the reason**, so nothing goes missing silently |
| 🧾 Run Log | Timings, model, errors, jobs per stage |

Every job tab is an Excel table with filters, frozen headers, clickable links, colour-coded scores and grouped (collapsible) column bands.

## Job columns
**Tracking:** Score (0–100) · Tier (🔥 / ✅ / 🤔) · 🆕 New · Status (a dropdown for your own copy: To Apply / Applied / Interviewing / Offer / Rejected / Skip; nothing is read back)
> Jobs a `--limit` run hasn't reached yet aren't listed. The Dashboard counts them as ⏳ Not processed yet.

**Role:** Title · Company · Category (AI/ML · LLM/Agents · Full-stack · Backend · Data · Other) · Builds AI tools? (Y/N + why) · Job URL · Apply URL · Posted · Age (days) · Openings at company

**Location:** Work mode · Locations · India eligible (Yes / No / Unclear + evidence) · Timezone / overlap hours · Relocation / visa

**Pay:** Listed salary (original) · Listed (₹ LPA) · Equity · Realistic estimate (₹ LPA) · Estimate confidence · Estimate sources · Pay tier

**Requirements:** Experience required · Fresher OK? · Education · Must-have skills · Nice-to-have · Tech stack · My skill match % · Missing skills

**Interview:** Process (as described or reported) · DSA risk (Low / Med / High) · DSA evidence · Take-home / project-based?

**Fit:** Fit score · Why I fit · Red flags

**Company (summary):** One-liner · YC batch · Stage / funding · Team size · Employee sentiment · Rating (Glassdoor / AmbitionBox) · Founders

**Meta:** First seen · Last seen · Still open? · Source · Model · Job ID

## Companies tab
Company · Website · One-liner · Product / domain · YC batch · Founded · Stage / funding · Team size · HQ · Founders (+ LinkedIn) · Open roles (all / fresher) · Employee sentiment summary · Pros · Cons · Interview experiences · Salary data points · Recent news / HN · Outreach draft (founder message) · Sources · Researched on

## Scoring (weights live in `config.yaml`)
| Component | Weight |
|---|---|
| Remote & India-eligible | 30 |
| Pay (realistic ₹ LPA vs tiers 9 / 12 / 20 / $120k) | 25 |
| Low DSA risk | 15 |
| AI-tools relevance + skill fit | 20 |
| Company quality (sentiment, stage, momentum) | 10 |
