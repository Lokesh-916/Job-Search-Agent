"""Daily community feed: fetch every source, curate, store, and summarise what's new."""

from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from job_agent.community.classify import classify
from job_agent.community.events import fetch_all as fetch_events
from job_agent.community.models import Posting, load_companies
from job_agent.community.sources import adzuna, unstop
from job_agent.community.sources.registry import DESCRIBERS, USER_AGENT, fetch_all
from job_agent.community.store import CommunityStore
from job_agent.settings import Settings
from job_agent.store import now_iso

COMPANIES = Path("config/companies.yaml")
OPEN_MARKETPLACES = {"unstop", "adzuna"}  # anyone can post here: demand a stated stipend
MIN_STIPEND = 5000  # ₹/month for marketplace internships
MAX_DESCRIPTION_FETCHES = 600  # per run; the cache makes later runs cheap
TIER_RANK = {"big_tech": 0, "mnc": 1, "unicorn": 2, "startup": 3, "other": 4}


@dataclass
class FeedStats:
    run_at: str
    fetched: Counter = field(default_factory=Counter)  # postings per source
    kept: Counter = field(default_factory=Counter)  # job / internship
    new: Counter = field(default_factory=Counter)  # job / internship / event
    dropped: Counter = field(default_factory=Counter)  # reason
    events: int = 0
    described: int = 0  # job texts fetched for listing-only sources
    errors: dict[str, str] = field(default_factory=dict)


def _stipend_ok(p: Posting) -> bool:
    if p.source not in OPEN_MARKETPLACES:
        return True
    pay = p.extra.get("pay") or ""
    amounts = [int(x.replace(",", "")) for x in re.findall(r"[\d,]{4,}", pay)]
    return bool(amounts) and max(amounts) >= MIN_STIPEND


def _clean_city(city: str) -> str:
    """'on Campus XYZ University - Bhubaneswar, India' -> 'Bhubaneswar (XYZ University)'."""
    m = re.match(r"(?:on campus )?(.*?)\s+-\s+(.+?)(?:, india)?$", city.strip(), re.I)
    return f"{m.group(2)} ({m.group(1)})" if m else city


def gather(settings: Settings) -> tuple[list[tuple[Posting, str]], dict[str, str]]:
    """All raw postings with their company tier, plus per-source errors."""
    companies = load_companies(COMPANIES)
    tier_of = {c.name: c.tier for c in companies}
    out: list[tuple[Posting, str]] = []
    errors: dict[str, str] = {}
    for res in fetch_all(companies):
        if res.error:
            errors[res.company.name] = res.error
        out += [(p, res.company.tier) for p in res.postings]
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        for kind in ("internship", "job"):
            try:
                out += [(p, tier_of.get(p.company, "other")) for p in unstop.fetch(kind, client)]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                errors[f"unstop {kind}s"] = f"{type(exc).__name__}: {exc}"[:200]
        sec = settings.secrets
        if sec.adzuna_app_id and sec.adzuna_app_key:
            try:
                found = adzuna.fetch_all(sec.adzuna_app_id, sec.adzuna_app_key, client)
                out += [(p, tier_of.get(p.company, "other")) for p in found]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                errors["adzuna"] = f"{type(exc).__name__}: {exc}"[:200]
    return out, errors


def fill_descriptions(postings: list[Posting], store: CommunityStore) -> int:
    """Fetch job text for listings that have none (cached per posting). Returns fetch count."""
    for p in postings:
        if cached := store.description(p.key):
            p.description = cached
    todo = [p for p in postings if not p.description][:MAX_DESCRIPTION_FETCHES]

    def one(p: Posting) -> tuple[Posting, str | None]:
        try:
            return p, DESCRIBERS[p.source](p, client)
        except (httpx.HTTPError, ValueError, KeyError):
            return p, None

    headers = {"User-Agent": USER_AGENT}
    with (
        httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=6) as pool,
    ):
        results = list(pool.map(one, todo))
    for p, text in results:
        if text:
            p.description = text
            store.save_description(p.key, text)
    return sum(1 for _, text in results if text)


def refresh(settings: Settings, store: CommunityStore) -> FeedStats:
    stats = FeedStats(run_at=now_iso())
    postings, stats.errors = gather(settings)
    # Listing-only sources: read the job text when the title can't settle the level.
    unclear = [p for p, _ in postings
               if p.source in DESCRIBERS and classify(p).level == "Check experience"]  # fmt: skip
    stats.described = fill_descriptions(unclear, store)
    for p, tier in postings:
        stats.fetched[p.source] += 1
        v = classify(p)
        if not v.keep:
            stats.dropped[v.reason] += 1
            continue
        if v.kind == "internship" and not _stipend_ok(p):
            stats.dropped["Internship without stipend"] += 1
            continue
        if v.kind == "internship" and not p.extra.get("pay"):
            p.extra["pay"] = "Paid (amount not listed)"
        stats.kept[v.kind] += 1
        if p.description and p.source not in DESCRIBERS:  # describers cache their own text
            store.save_description(p.key, p.description)
        if store.upsert_posting(p, v, tier, stats.run_at):
            stats.new[v.kind] += 1
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        events, errors = fetch_events(client)
    stats.errors.update({f"events:{k}": v for k, v in errors.items()})
    for e in events:
        if e.source == "gdg":
            e.city = _clean_city(e.city)
        stats.events += 1
        if store.upsert_event(e, stats.run_at):
            stats.new["event"] += 1
    return stats


def ranked(rows: list) -> list:
    """New first, then company tier, then clearer entry-level signal."""
    latest = max((r["first_seen"][:10] for r in rows), default="")
    return sorted(rows, key=lambda r: (
        r["first_seen"][:10] != latest,
        TIER_RANK.get(r["tier"] or "other", 4),
        r["level"] != "Entry level",
    ))  # fmt: skip
