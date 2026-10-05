"""Dispatch a company to its platform's fetcher; fetch many companies politely."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from job_agent.community.models import Company, Posting
from job_agent.community.sources import amazon, ashby, greenhouse, lever, smartrecruiters, workday

Fetcher = Callable[[Company, httpx.Client], list[Posting]]
FETCHERS: dict[str, Fetcher] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workday": workday.fetch,
    "amazon": amazon.fetch,
}
# Sources whose listings carry no job text; these fetch one posting's description on demand.
DESCRIBERS: dict[str, Callable[[Posting, httpx.Client], str]] = {
    "smartrecruiters": smartrecruiters.describe,
    "workday": workday.describe,
}
USER_AGENT = "job-agent-community/0.1 (batch placement feed)"


def short_error(exc: Exception) -> str:
    """One-line error without URLs, so API keys in query strings never reach logs or chats."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} from {exc.request.url.host}"
    if isinstance(exc, httpx.RequestError):
        return f"{type(exc).__name__} reaching {exc.request.url.host}"
    return f"{type(exc).__name__}: {exc}"[:200]


@dataclass
class SourceResult:
    company: Company
    postings: list[Posting]
    error: str | None = None


def fetch_company(company: Company, client: httpx.Client) -> SourceResult:
    fetcher = FETCHERS.get(company.ats)
    if fetcher is None:
        return SourceResult(company, [], f"no fetcher for platform {company.ats!r}")
    try:
        return SourceResult(company, fetcher(company, client))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return SourceResult(company, [], short_error(exc))


def fetch_all(companies: list[Company], workers: int = 6) -> list[SourceResult]:
    headers = {"User-Agent": USER_AGENT}
    with (
        httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        return list(pool.map(lambda co: fetch_company(co, client), companies))
