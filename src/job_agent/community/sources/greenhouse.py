"""Greenhouse public job board API: https://developers.greenhouse.io/job-board.html"""

from __future__ import annotations

import html

import httpx

from job_agent.community.models import Company, Posting
from job_agent.text import html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    resp = client.get(API.format(slug=company.slug), params={"content": "true"})
    resp.raise_for_status()
    out = []
    for job in resp.json().get("jobs", []):
        departments = ", ".join(d.get("name", "") for d in job.get("departments") or [])
        out.append(Posting(
            source="greenhouse",
            company=company.name,
            external_id=str(job["id"]),
            title=job.get("title", "").strip(),
            url=job.get("absolute_url", ""),
            location=(job.get("location") or {}).get("name", ""),
            department=departments,
            posted_at=(job.get("updated_at") or "")[:10] or None,
            description=html_to_text(html.unescape(job.get("content") or ""), 6000),
        ))  # fmt: skip
    return out
