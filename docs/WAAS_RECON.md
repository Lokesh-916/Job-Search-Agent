# How Work at a Startup serves data

Observed 2026-10-03 while logged in. The site may change, so re-check this when the fetcher breaks.

## 1. Search: Algolia (structured, fast)
- The logged-in `/companies` page embeds `window.AlgoliaOpts = {app, key, tag_filters, valid_until}`. This is a **secured, per-user, expiring** search key, so read it fresh on every run.
- Endpoint: `POST https://{app}-dsn.algolia.net/1/indexes/*/queries`
- Index: `WaaSPublicCompanyJob_created_at_desc_production`. One record per job, newest first.
  The site queries it with `distinct=true` (one hit per company). Leave that off to get every job.
- Useful filter facets:
  | facet | values |
  |---|---|
  | `role` | eng, product, design, science, ... |
  | `eng_type` | fs, be, fe, ml, ai, data_sci, devops, ... |
  | `min_experience` | 0, 1, 2, 3, 5, 6, 8, 11 |
  | `remote` | yes (remote OK), only (remote only), no |
  | `job_type` | fulltime, intern, contract |
  | `us_visa_required` | yes (US auth needed), none, possible (will sponsor) |
  | `locations_for_search` | country codes (`IN`, `US`) and city strings |
  | `company_waas_stage`, `company_team_size`, `has_salary`, `has_equity` | |
- A hit includes the title, description (truncated), skills, company name, website, sector, team size and stage, plus `search_path` (a public ycombinator.com job URL). **It has no salary.**
- Example volume: `role:eng AND min_experience:0|1 AND (remote:yes|only OR locations_for_search:IN)` gives about 250 jobs at 146 companies.

## 2. Job detail: `GET /jobs/{id}` with `Accept: text/html`
Inertia page: the `data-page` attribute holds JSON. Session cookies are enough, so plain HTTP works with no browser.
- `props.job`: `salaryRange`, `equityRange`, `location`, `jobType`, `sponsorsVisa` ("US citizen/visa only", ...), `minExperience`, `skills`, `descriptionHtml`, **`interviewProcessHtml`**
- `props.companyFull`: batch, team size, location, `founders[]` (name, bio, LinkedIn), `company_news`, `tech_description`, `hiring_description`, website, all `jobs`
- `props.locationEligible`: **not reliable** for India (it was `true` for a US-citizens-only onsite role). Ignore it.
- `props.otherJobs`: the company's other openings, with salary.

## 3. Other endpoints
- `POST /companies/fetch {"ids": [...]}` returns company cards. `jobs` came back empty for our account (`isRestrictedRegion: true`), so use the job pages instead.

## Session
`job-agent login` saves Playwright `storage_state`. The `_sso.key` cookies last about a year. The short-lived session cookies are refreshed on every headless page load, so the fetcher re-saves the state after it loads `/companies`.
