"""amazon.jobs search JSON (India only)."""

from __future__ import annotations

from datetime import datetime

import httpx

from job_agent.community.models import Company, Posting

API = "https://www.amazon.jobs/en/search.json"
CATEGORIES = ["software-development", "machine-learning-science", "data-science",
              "solutions-architect", "business-intelligence"]  # fmt: skip
PAGE = 100


def _date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _describe(job: dict) -> str:
    short = job.get("description_short") or ""
    basics = job.get("basic_qualifications") or ""
    return f"{short}\n\nBasic qualifications:\n{basics}"[:6000]


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    out: list[Posting] = []
    seen: set[str] = set()
    for category in CATEGORIES:
        for offset in range(0, 500, PAGE):
            resp = client.get(API, params={"country": "IND", "result_limit": PAGE,
                                           "offset": offset, "category[]": category,
                                           "sort": "recent"},
                              headers={"Accept-Encoding": "gzip"})  # fmt: skip
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
            for job in jobs:
                jid = str(job.get("id_icims") or job.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                out.append(Posting(
                    source="amazon",
                    company=company.name,
                    external_id=jid,
                    title=(job.get("title") or "").strip(),
                    url=f"https://www.amazon.jobs{job.get('job_path', '')}",
                    location=job.get("normalized_location") or job.get("location") or "",
                    department=job.get("job_category") or "",
                    employment_type=job.get("job_schedule_type") or "",
                    posted_at=_date(job.get("posted_date") or ""),
                    description=_describe(job),
                ))  # fmt: skip
            if len(jobs) < PAGE:
                break
    return out
