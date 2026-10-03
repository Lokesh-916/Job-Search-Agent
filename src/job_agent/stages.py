"""LLM pipeline stages over stored jobs. Each stage is cached per posting + model."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from job_agent.jobs import render_job
from job_agent.llm import get_chat_model
from job_agent.profile import full_brief, preferences_brief
from job_agent.prompts import assess_messages, extract_messages, triage_messages
from job_agent.schemas import Assessment, Extraction, Triage
from job_agent.scoring import hard_reject, listed_lpa
from job_agent.settings import Settings
from job_agent.store import Store
from job_agent.structured import abatch_structured

TRIAGE_DESC_CHARS = 1200  # triage only needs the gist

ResearchLookup = Callable[[sqlite3.Row], str | None]


@dataclass
class StageReport:
    stage: str
    todo: int = 0
    ok: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    kept: int | None = None


async def _run_stage(
    *,
    stage: str,
    schema: type[BaseModel],
    rows: list[sqlite3.Row],
    build: Callable[[sqlite3.Row], Sequence[BaseMessage]],
    store: Store,
    settings: Settings,
    llm: BaseChatModel | None,
    limit: int | None,
    input_key: Callable[[sqlite3.Row], str] = lambda r: r["content_hash"],
) -> StageReport:
    """Run `stage` for rows whose inputs (see `input_key`) changed since the last success."""
    model = settings.llm.model
    keys = {r["job_id"]: input_key(r) for r in rows}
    todo = [r for r in rows if store.needs_stage(r["job_id"], stage, model, keys[r["job_id"]])]
    todo = todo[:limit]
    report = StageReport(stage=stage, todo=len(todo))
    if not todo:
        return report
    by_id = {r["job_id"]: r for r in todo}
    results = await abatch_structured(
        llm or get_chat_model(stage),
        schema,
        {job_id: build(row) for job_id, row in by_id.items()},
        settings.llm.max_concurrency,
    )
    for job_id, out in results.items():
        input_hash = keys[job_id]
        if isinstance(out, Exception):
            error = f"{type(out).__name__}: {out}"[:500]
            report.failed[job_id] = error
            store.save_result(job_id, stage, model, input_hash, error=error)
        else:
            report.ok += 1
            store.save_result(job_id, stage, model, input_hash, out.model_dump())
    return report


def stage_result(store: Store, job_id: str, stage: str) -> dict | None:
    res = store.get_result(job_id, stage)
    return json.loads(res["result_json"]) if res and res["result_json"] else None


def kept_jobs(store: Store) -> list[sqlite3.Row]:
    """Open jobs that passed triage."""
    return [
        r
        for r in store.open_jobs()
        if (stage_result(store, r["job_id"], "triage") or {}).get("keep")
    ]


async def run_triage(
    store: Store,
    settings: Settings,
    profile: dict,
    llm: BaseChatModel | None = None,
    limit: int | None = None,
) -> StageReport:
    prefs = preferences_brief(profile)
    report = await _run_stage(
        stage="triage",
        schema=Triage,
        rows=store.open_jobs(),
        build=lambda r: triage_messages(prefs, render_job(r, TRIAGE_DESC_CHARS)),
        store=store,
        settings=settings,
        llm=llm,
        limit=limit,
    )
    report.kept = len(kept_jobs(store))
    return report


async def run_extract(
    store: Store,
    settings: Settings,
    llm: BaseChatModel | None = None,
    limit: int | None = None,
) -> StageReport:
    return await _run_stage(
        stage="extract",
        schema=Extraction,
        rows=kept_jobs(store),
        build=lambda r: extract_messages(render_job(r)),
        store=store,
        settings=settings,
        llm=llm,
        limit=limit,
    )


def _digest(*parts: str | None) -> str:
    return hashlib.sha256("|".join(p or "" for p in parts).encode()).hexdigest()[:16]


def _facts(ex: Extraction, listed: tuple[float | None, float | None]) -> str:
    lo, hi = listed
    inr = f"{lo}-{hi} LPA" if lo is not None else "not stated"
    return f"{ex.model_dump_json(exclude_none=True)}\nListed salary in INR: {inr}"


async def run_assess(
    store: Store,
    settings: Settings,
    profile: dict,
    rates: dict[str, float],
    research: ResearchLookup = lambda row: None,
    llm: BaseChatModel | None = None,
    limit: int | None = None,
) -> StageReport:
    """Judge extracted jobs that survived the hard gates, for this candidate."""
    brief = full_brief(profile)
    todo: list[sqlite3.Row] = []
    facts: dict[str, str] = {}
    for row in kept_jobs(store):
        raw = stage_result(store, row["job_id"], "extract")
        if raw is None:
            continue
        ex = Extraction.model_validate(raw)
        listed = listed_lpa(ex, rates)
        if hard_reject(None, ex, listed, settings.preferences):
            continue
        todo.append(row)
        facts[row["job_id"]] = _facts(ex, listed)

    return await _run_stage(
        stage="assess",
        schema=Assessment,
        rows=todo,
        build=lambda r: assess_messages(brief, render_job(r), facts[r["job_id"]], research(r)),
        store=store,
        settings=settings,
        llm=llm,
        limit=limit,
        input_key=lambda r: _digest(r["content_hash"], facts[r["job_id"]], research(r), brief),
    )
