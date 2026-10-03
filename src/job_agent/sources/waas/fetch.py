"""Search -> store hits -> download details for new/stale jobs -> report what changed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from job_agent.settings import Settings
from job_agent.sources.waas.detail import fetch_details
from job_agent.sources.waas.search import bootstrap, build_filters, search_jobs
from job_agent.store import Store, now_iso

SOURCE = "waas"


@dataclass
class FetchResult:
    found: int = 0
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # new or edited postings: need LLM work
    fetched: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    closed: int = 0


def fetch_waas(settings: Settings, store: Store) -> FetchResult:
    cfg = settings.sources.waas
    run_started = now_iso()

    opts = bootstrap(settings.browser, settings.paths.session)
    hits = search_jobs(opts, build_filters(cfg))
    result = FetchResult(found=len(hits))
    result.new = store.upsert_hits(SOURCE, hits, run_started)

    todo = store.ids_needing_detail([str(h["id"]) for h in hits], cfg.refetch_after_days)
    details = asyncio.run(
        fetch_details(todo, settings.paths.session, cfg.concurrency, cfg.request_delay_s)
    )
    fetched_at = now_iso()
    for job_id, detail in details.items():
        if isinstance(detail, Exception):
            result.failed[job_id] = f"{type(detail).__name__}: {detail}"
        elif detail.get("closed"):
            store.mark_closed([job_id])
        else:
            result.fetched += 1
            if store.save_detail(job_id, detail, fetched_at):
                result.changed.append(job_id)

    result.closed = store.close_unseen(SOURCE, run_started)
    return result
