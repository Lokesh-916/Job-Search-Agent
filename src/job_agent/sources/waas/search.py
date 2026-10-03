"""Job search through WaaS's Algolia index (see docs/WAAS_RECON.md)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx
from playwright.sync_api import sync_playwright

from job_agent.settings import BrowserConfig, WaasSourceConfig

WAAS_URL = "https://www.workatastartup.com"
JOBS_INDEX = "WaaSPublicCompanyJob_created_at_desc_production"
HITS_PER_PAGE = 200

_ALGOLIA_OPTS_RE = re.compile(r"window\.AlgoliaOpts = (\{.*?\});")


class SessionExpiredError(RuntimeError):
    """The saved WaaS session no longer logs in; run `job-agent login` again."""


@dataclass
class AlgoliaOpts:
    app: str
    key: str

    @property
    def url(self) -> str:
        return f"https://{self.app.lower()}-dsn.algolia.net/1/indexes/*/queries"

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Algolia-Application-Id": self.app, "X-Algolia-API-Key": self.key}


def parse_algolia_opts(page_html: str) -> AlgoliaOpts:
    match = _ALGOLIA_OPTS_RE.search(page_html)
    if not match:
        raise SessionExpiredError("No search key on /companies; the session is probably logged out")
    data = json.loads(match.group(1))
    return AlgoliaOpts(app=data["app"], key=data["key"])


def bootstrap(browser_cfg: BrowserConfig, session_path: Path) -> AlgoliaOpts:
    """Load /companies headless to get a fresh search key, and re-save refreshed cookies."""
    if not session_path.exists():
        raise SessionExpiredError(f"{session_path} missing; run `job-agent login`")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=browser_cfg.channel or None, headless=True)
        context = browser.new_context(storage_state=str(session_path))
        page = context.new_page()
        page.goto(f"{WAAS_URL}/companies", wait_until="domcontentloaded", timeout=60_000)
        opts = parse_algolia_opts(page.content())
        context.storage_state(path=str(session_path))
        browser.close()
    return opts


def _any_of(facet: str, values: list[str]) -> str:
    return "(" + " OR ".join(f"{facet}:{v}" for v in values) + ")"


def build_filters(cfg: WaasSourceConfig) -> str:
    """Algolia filter string for fresher-friendly jobs that are remote or in our locations."""
    where = [f"remote:{r}" for r in cfg.remote] + [
        f"locations_for_search:{loc}" for loc in cfg.locations
    ]
    local = [f"locations_for_search:{loc}" for loc in cfg.locations]
    clauses = [
        _any_of("job_type", cfg.job_types),
        _any_of("min_experience", [str(n) for n in range(cfg.max_min_experience + 1)]),
        "(" + " OR ".join(where) + ")",
    ]
    if cfg.roles:
        clauses.insert(0, _any_of("role", cfg.roles))
    if cfg.exclude_us_auth_required:
        # Algolia can't nest NOT inside OR, so whitelist the other values instead.
        allowed = ["us_visa_required:none", "us_visa_required:possible", *local]
        clauses.append("(" + " OR ".join(allowed) + ")")
    return " AND ".join(clauses)


def search_jobs(opts: AlgoliaOpts, filters: str, client: httpx.Client | None = None) -> list[dict]:
    """Every matching job hit, newest first."""
    client = client or httpx.Client(timeout=30)
    hits: list[dict] = []
    page = 0
    while True:
        params = urlencode(
            {
                "query": "",
                "filters": filters,
                "hitsPerPage": HITS_PER_PAGE,
                "page": page,
                "attributesToHighlight": "[]",
                "distinct": "false",  # the index groups by company by default
            }
        )
        body = {"requests": [{"indexName": JOBS_INDEX, "params": params}]}
        resp = client.post(opts.url, headers=opts.headers, json=body)
        if resp.status_code in (401, 403):
            raise SessionExpiredError("Algolia rejected the search key")
        resp.raise_for_status()
        result = resp.json()["results"][0]
        hits.extend(result["hits"])
        page += 1
        if page >= result["nbPages"]:
            return hits
