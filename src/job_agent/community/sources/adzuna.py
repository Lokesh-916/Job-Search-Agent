"""Adzuna India search API: a broad net over many Indian job boards and companies.

Needs ADZUNA_APP_ID / ADZUNA_APP_KEY. Runs a fixed set of fresher-oriented queries.
"""

from __future__ import annotations

import httpx

from job_agent.community.models import Posting
from job_agent.text import html_to_text

API = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
QUERIES = [
    "software engineer fresher", "graduate engineer trainee", "software developer entry level",
    "full stack developer fresher", "backend developer fresher", "frontend developer fresher",
    "data scientist fresher", "data analyst fresher", "machine learning engineer",
    "devops engineer fresher", "software engineer intern", "data science internship",
    "web development internship", "ai ml internship",
]  # fmt: skip


def fetch_all(app_id: str, app_key: str, client: httpx.Client, max_days_old: int = 7,
              pages: int = 1) -> list[Posting]:  # fmt: skip
    out: list[Posting] = []
    seen: set[str] = set()
    for query in QUERIES:
        for page in range(1, pages + 1):
            resp = client.get(API.format(page=page), params={
                "app_id": app_id, "app_key": app_key, "results_per_page": 50, "what": query,
                "max_days_old": max_days_old, "sort_by": "date",
                "content-type": "application/json",
            })  # fmt: skip
            resp.raise_for_status()
            for job in resp.json().get("results", []):
                jid = str(job.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                lo, hi = job.get("salary_min"), job.get("salary_max")
                out.append(Posting(
                    source="adzuna",
                    company=(job.get("company") or {}).get("display_name") or "Unknown",
                    external_id=jid,
                    title=html_to_text(job.get("title") or "").strip(),
                    url=job.get("redirect_url") or "",
                    location=(job.get("location") or {}).get("display_name") or "India",
                    employment_type=job.get("contract_time") or "",
                    posted_at=(job.get("created") or "")[:10] or None,
                    description=html_to_text(job.get("description") or "", 3000),
                    extra={"salary": (lo, hi) if lo or hi else None, "query": query},
                ))  # fmt: skip
    return out
