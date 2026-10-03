"""Job detail pages (`/jobs/{id}`): salary, interview process, founders, company news."""

from __future__ import annotations

import asyncio
import html
import json
import re
from pathlib import Path
from typing import Any

import httpx

from job_agent.sources.waas.search import WAAS_URL, SessionExpiredError

_DATA_PAGE_RE = re.compile(r'data-page="(.*?)"', re.S)

# Bulky or useless-to-the-LLM company fields.
_COMPANY_DROP = {
    "lat", "lng", "logo_url", "small_logo_url", "event_video_urls", "hiring_video_url",
    "waas_company_videos", "fb_url", "_type",
}  # fmt: skip


def parse_inertia_props(page_html: str) -> dict[str, Any]:
    match = _DATA_PAGE_RE.search(page_html)
    if not match:
        raise ValueError("No Inertia data-page payload in HTML")
    return json.loads(html.unescape(match.group(1)))["props"]


def slim_detail(props: dict[str, Any]) -> dict[str, Any]:
    """Keep the parts of a job page worth storing and showing to the LLM."""
    company = {k: v for k, v in (props.get("companyFull") or {}).items() if k not in _COMPANY_DROP}
    jobs = company.pop("jobs", None) or []
    company["open_jobs"] = [{"id": j.get("id"), "title": j.get("title")} for j in jobs]
    for founder in company.get("founders") or []:
        for key in ("avatar_medium", "avatar_thumb"):
            founder.pop(key, None)
    return {"job": props.get("job") or {}, "company": company, "other_jobs": props.get("otherJobs")}


def cookies_from_storage_state(session_path: Path) -> httpx.Cookies:
    state = json.loads(session_path.read_text(encoding="utf-8"))
    jar = httpx.Cookies()
    for c in state.get("cookies", []):
        jar.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    return jar


async def _fetch_one(client: httpx.AsyncClient, job_id: str, delay_s: float) -> dict[str, Any]:
    resp = await client.get(f"{WAAS_URL}/jobs/{job_id}", headers={"Accept": "text/html"})
    await asyncio.sleep(delay_s)
    if resp.status_code == 404:
        return {"closed": True}
    resp.raise_for_status()
    props = parse_inertia_props(resp.text)
    if not props.get("job"):
        raise SessionExpiredError(f"Job {job_id} page has no job data; session may be logged out")
    return slim_detail(props)


async def fetch_details(
    job_ids: list[str],
    session_path: Path,
    concurrency: int = 4,
    delay_s: float = 0.5,
    client: httpx.AsyncClient | None = None,
) -> dict[str, dict[str, Any] | Exception]:
    """Fetch many job pages politely. Per-job failures are returned, not raised."""
    client = client or httpx.AsyncClient(
        cookies=cookies_from_storage_state(session_path), timeout=30, follow_redirects=True
    )
    sem = asyncio.Semaphore(concurrency)

    async def guarded(job_id: str) -> tuple[str, dict[str, Any] | Exception]:
        async with sem:
            try:
                return job_id, await _fetch_one(client, job_id, delay_s)
            except SessionExpiredError:
                raise
            except Exception as exc:  # one bad page shouldn't sink the run
                return job_id, exc

    async with client:
        results = await asyncio.gather(*(guarded(j) for j in job_ids))
    return dict(results)
