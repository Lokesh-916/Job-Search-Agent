"""SmartRecruiters public postings API (India only): https://developers.smartrecruiters.com/"""

from __future__ import annotations

import httpx

from job_agent.community.models import Company, Posting
from job_agent.text import html_to_text

API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE = 100
MAX_PAGES = 10


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    out: list[Posting] = []
    for page in range(MAX_PAGES):
        resp = client.get(
            API.format(slug=company.slug),
            params={"limit": PAGE, "offset": page * PAGE, "country": "in"},
        )
        resp.raise_for_status()
        data = resp.json()
        for job in data.get("content", []):
            loc = job.get("location") or {}
            place = ", ".join(x for x in (loc.get("city"), loc.get("region"), "India") if x)
            out.append(Posting(
                source="smartrecruiters",
                company=company.name,
                external_id=str(job["id"]),
                title=(job.get("name") or "").strip(),
                url=f"https://jobs.smartrecruiters.com/{company.slug}/{job['id']}",
                location=place + (" (remote)" if loc.get("remote") else ""),
                department=(job.get("department") or {}).get("label", ""),
                employment_type=(job.get("typeOfEmployment") or {}).get("label", ""),
                posted_at=(job.get("releasedDate") or "")[:10] or None,
                extra={"level": (job.get("experienceLevel") or {}).get("label", ""),
                       "detail": f"{API.format(slug=company.slug)}/{job['id']}"},
            ))  # fmt: skip
        if (page + 1) * PAGE >= data.get("totalFound", 0):
            break
    return out


def describe(posting: Posting, client: httpx.Client) -> str:
    """Job description and qualifications from the single-posting endpoint."""
    resp = client.get(posting.extra["detail"])
    resp.raise_for_status()
    sections = (resp.json().get("jobAd") or {}).get("sections") or {}
    keys = ("jobDescription", "qualifications")
    parts = [(sections.get(k) or {}).get("text") or "" for k in keys]
    return html_to_text("\n".join(parts), 6000)
