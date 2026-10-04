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
USER_AGENT = "job-agent-community/0.1 (batch placement feed)"


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
        return SourceResult(company, [], f"{type(exc).__name__}: {exc}"[:300])


def fetch_all(companies: list[Company], workers: int = 6) -> list[SourceResult]:
    headers = {"User-Agent": USER_AGENT}
    with (
        httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        return list(pool.map(lambda co: fetch_company(co, client), companies))
