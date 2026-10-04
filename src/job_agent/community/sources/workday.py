"""Workday career sites (the CXS JSON endpoint every Workday careers page uses).

`slug` is the tenant and `site` is "<cluster>/<site>", e.g. "wd5/NVIDIAExternalCareerSite".
Only the listing is fetched (title, location, posted); descriptions would need one request
per job, so classification here is title-based.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import httpx

from job_agent.community.models import Company, Posting

PAGE = 20
MAX_JOBS = 300
POSTED_DAYS = re.compile(r"(\d+)\+? Days? Ago", re.I)


def posted_date(text: str, today: date | None = None) -> str | None:
    """Parse "Posted Today" / "Posted Yesterday" / "Posted 3 Days Ago" / "Posted 30+ Days Ago"."""
    today = today or date.today()
    if not text:
        return None
    if "Today" in text:
        return today.isoformat()
    if "Yesterday" in text:
        return (today - timedelta(days=1)).isoformat()
    if m := POSTED_DAYS.search(text):
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return None


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    cluster, site = (company.site or "wd1/External").split("/", 1)
    base = f"https://{company.slug}.{cluster}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{company.slug}/{site}/jobs"
    out: list[Posting] = []
    offset = 0
    while offset < MAX_JOBS:
        resp = client.post(url, json={"appliedFacets": {}, "limit": PAGE, "offset": offset,
                                      "searchText": "India"})  # fmt: skip
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobPostings", [])
        for job in jobs:
            path = job.get("externalPath", "")
            out.append(Posting(
                source="workday",
                company=company.name,
                external_id=path.rsplit("_", 1)[-1] or path,
                title=(job.get("title") or "").strip(),
                url=f"{base}/en-US/{site}{path}",
                location=job.get("locationsText") or "",
                posted_at=posted_date(job.get("postedOn") or ""),
                extra={"bullets": job.get("bulletFields") or []},
            ))  # fmt: skip
        offset += PAGE
        if not jobs or offset >= data.get("total", 0):
            break
    return out
