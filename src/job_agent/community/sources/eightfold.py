"""Eightfold career sites (Microsoft, Qualcomm, Vodafone...): the public PCSX search JSON.

`slug` is the company's domain (e.g. "microsoft.com") and `site` the careers host
(e.g. "apply.careers.microsoft.com"). The search returns 10 positions per page and no
job text; `describe()` fetches one position's description on demand.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from job_agent.community.models import Company, Posting
from job_agent.text import html_to_text

PAGE = 10  # fixed by the API
MAX_JOBS = 400
HEADERS = {"Accept": "application/json"}


def _date(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), UTC).date().isoformat()
    except (TypeError, ValueError):
        return None


def _place(text: str) -> str:
    """Microsoft writes "India, Telangana, Hyderabad"; read it city first like the others."""
    parts = [x.strip() for x in text.split(",")]
    if parts[0] == "India" and len(parts) > 1:
        parts = [x for x in reversed(parts) if x != "Multiple Locations"] or ["India"]
    return ", ".join(dict.fromkeys(parts))


def fetch(company: Company, client: httpx.Client) -> list[Posting]:
    host, domain = company.site, company.slug
    out: list[Posting] = []
    for start in range(0, MAX_JOBS, PAGE):
        resp = client.get(f"https://{host}/api/pcsx/search", headers=HEADERS,
                          params={"domain": domain, "query": "", "location": "India",
                                  "start": start, "sort_by": "timestamp"})  # fmt: skip
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        positions = data.get("positions") or []
        for p in positions:
            pid = str(p["id"])
            out.append(Posting(
                source="eightfold",
                company=company.name,
                external_id=pid,
                title=(p.get("name") or "").strip(),
                url=f"https://{host}{p.get('positionUrl') or '/careers/job/' + pid}",
                location="; ".join(_place(x) for x in p.get("locations") or []),
                department=p.get("department") or "",
                posted_at=_date(p.get("postedTs")),
                extra={"detail": f"https://{host}/api/pcsx/position_details?"
                                 f"position_id={pid}&domain={domain}&hl=en"},
            ))  # fmt: skip
        if len(positions) < PAGE or start + PAGE >= (data.get("count") or 0):
            break
    return out


def describe(posting: Posting, client: httpx.Client) -> str:
    resp = client.get(posting.extra["detail"], headers=HEADERS)
    resp.raise_for_status()
    return html_to_text((resp.json().get("data") or {}).get("jobDescription") or "", 6000)
