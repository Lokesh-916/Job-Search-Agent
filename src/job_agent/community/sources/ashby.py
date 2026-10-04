"""Ashby public job board API: https://developers.ashbyhq.com/docs/public-job-posting-api"""

from __future__ import annotations

import httpx

from job_agent.community.models import Company, Posting

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    resp = client.get(API.format(slug=company.slug), params={"includeCompensation": "true"})
    resp.raise_for_status()
    out = []
    for job in resp.json().get("jobs", []):
        locs = [job.get("location") or ""] + [
            s.get("location", "") for s in job.get("secondaryLocations") or []
        ]
        pay = (job.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(Posting(
            source="ashby",
            company=company.name,
            external_id=str(job.get("id")),
            title=(job.get("title") or "").strip(),
            url=job.get("jobUrl") or job.get("applyUrl") or "",
            location="; ".join(x for x in locs if x),
            department=job.get("department") or job.get("team") or "",
            employment_type=job.get("employmentType") or "",
            posted_at=(job.get("publishedAt") or "")[:10] or None,
            description=(job.get("descriptionPlain") or "")[:6000],
            extra={"remote": job.get("isRemote"), "pay": pay},
        ))  # fmt: skip
    return out
