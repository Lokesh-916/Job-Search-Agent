"""Lever public postings API: https://github.com/lever/postings-api"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from job_agent.community.models import Company, Posting

API = "https://api.lever.co/v0/postings/{slug}"


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    resp = client.get(API.format(slug=company.slug), params={"mode": "json"})
    resp.raise_for_status()
    out = []
    for job in resp.json():
        cats = job.get("categories") or {}
        created = job.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, UTC).date().isoformat() if created else None
        lists = "\n".join(
            f"{block.get('text', '')}:\n{block.get('content', '')}"
            for block in job.get("lists") or []
        )
        out.append(Posting(
            source="lever",
            company=company.name,
            external_id=job["id"],
            title=(job.get("text") or "").strip(),
            url=job.get("hostedUrl", ""),
            location=cats.get("location") or ", ".join(cats.get("allLocations") or []),
            department=cats.get("team") or cats.get("department") or "",
            employment_type=cats.get("commitment") or "",
            posted_at=posted,
            description=((job.get("descriptionPlain") or "") + "\n" + lists)[:6000],
            extra={"workplace": job.get("workplaceType")},
        ))  # fmt: skip
    return out
