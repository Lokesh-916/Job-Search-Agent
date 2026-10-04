"""Unstop (India): open internships (with stipend) and fresher jobs, via the site's own JSON."""

from __future__ import annotations

import httpx

from job_agent.community.models import Posting

API = "https://unstop.com/api/public/opportunity/search-result"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/153", "Accept": "application/json"}
PER_PAGE = 50


def _place(item: dict) -> str:
    detail = item.get("jobDetail") or {}
    if detail.get("type") == "wfh" or item.get("region") == "online":
        return "Remote, India"
    cities = [loc.get("city") for loc in detail.get("locations") or [] if isinstance(loc, dict)]
    addr = item.get("address_with_country_logo") or {}
    cities += [addr.get("city"), addr.get("state")]
    return ", ".join(dict.fromkeys(c for c in cities if c)) + ", India"


def _pay(detail: dict) -> str | None:
    lo, hi = detail.get("min_salary"), detail.get("max_salary")
    if not (detail.get("show_salary") and (lo or hi)):
        return None
    lo, hi = int(lo or hi), int(hi or lo)
    return f"₹{lo:,}" + (f"–{hi:,}" if hi != lo else "")


def to_posting(item: dict, kind: str) -> Posting:
    detail = item.get("jobDetail") or {}
    org = (item.get("organisation") or {}).get("name") or "Unknown"
    functions = ", ".join(w.get("name", "") for w in item.get("workfunction") or [])
    deadline = (item.get("regnRequirements") or {}).get("end_regn_dt") or item.get("end_date")
    pay = _pay(detail)
    return Posting(
        source="unstop",
        company=org,
        external_id=str(item["id"]),
        title=(item.get("title") or "").strip(),
        url=item.get("seo_url") or f"https://unstop.com/{item.get('public_url', '')}",
        location=_place(item),
        department=functions,
        employment_type="Internship" if kind == "internship" else "Full-time",
        posted_at=(item.get("approved_date") or item.get("updated_at") or "")[:10] or None,
        description=", ".join(s.get("skill", "") for s in item.get("required_skills") or []
                              if isinstance(s, dict)),
        extra={"internship": kind == "internship", "pay": pay,
               "deadline": (deadline or "")[:10] or None},
    )  # fmt: skip


def fetch(kind: str, client: httpx.Client, pages: int = 6) -> list[Posting]:
    """kind: "internship" or "job"."""
    opportunity = "internships" if kind == "internship" else "jobs"
    out: list[Posting] = []
    for page in range(1, pages + 1):
        resp = client.get(API, headers=HEADERS, params={
            "opportunity": opportunity, "page": page, "per_page": PER_PAGE, "oppstatus": "open",
        })  # fmt: skip
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        out += [to_posting(item, kind) for item in data.get("data") or []]
        if page >= (data.get("last_page") or 1):
            break
    return out
