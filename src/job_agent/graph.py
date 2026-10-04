"""The daily pipeline as a LangGraph graph.

preflight -> fetch -> triage -> extract -> research -> assess -> export -> notify

Every LLM stage is cached in SQLite (see stages.py), so a crashed or interrupted run
simply resumes on the next invocation without redoing finished work.
"""

from __future__ import annotations

import asyncio
import operator
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from job_agent import metrics
from job_agent.export import workbook_path, write_workbook
from job_agent.fx import load_inr_rates
from job_agent.notify import NotifyError, Telegram
from job_agent.preflight import check_ollama, check_session, check_vram
from job_agent.profile import load_profile
from job_agent.report import build_report, research_columns
from job_agent.settings import Settings
from job_agent.sources.waas.fetch import fetch_waas
from job_agent.stages import (
    kept_jobs,
    research_brief,
    run_assess,
    run_extract,
    run_research,
    run_triage,
    stage_result,
)
from job_agent.store import Store


class RunOptions(TypedDict, total=False):
    limit: int | None  # cap jobs per LLM stage (test runs)
    skip_fetch: bool
    notify: bool


class PipelineState(TypedDict, total=False):
    options: RunOptions
    run_date: str
    started: float
    log: Annotated[list[tuple[str, Any]], operator.add]  # (key, value) lines for the Run Log tab
    abort: str | None
    workbook: str | None
    top: list[dict]
    outcome: dict[str, Any]


def build_graph(settings: Settings, store: Store):
    profile = load_profile(settings.paths.profile)
    rates_path = settings.paths.data_dir / "fx.json"

    def preflight(state: PipelineState) -> dict:
        checks = [check_vram(settings), check_ollama(settings), check_session(settings)]
        failed = [f"{c.name}: {c.detail}" for c in checks if c.fatal and not c.ok]
        log = [(f"Preflight · {c.name}", c.detail) for c in checks]
        return {"log": log, "abort": "; ".join(failed) or None}

    def fetch(state: PipelineState) -> dict:
        if state["options"].get("skip_fetch"):
            return {"log": [("Fetch", "skipped")]}
        r = fetch_waas(settings, store)
        summary = (
            f"{r.found} found, {len(r.new)} new, {len(r.changed)} new/changed, {r.closed} closed"
        )
        return {"log": [("Fetch", summary), ("Fetch failures", len(r.failed))]}

    async def triage(state: PipelineState) -> dict:
        r = await run_triage(store, settings, profile, limit=state["options"].get("limit"))
        return {"log": [("Triage", f"{r.ok}/{r.todo} done, {len(r.failed)} failed, {r.kept} kept")]}

    async def extract(state: PipelineState) -> dict:
        r = await run_extract(store, settings, limit=state["options"].get("limit"))
        return {"log": [("Extract", f"{r.ok}/{r.todo} done, {len(r.failed)} failed")]}

    async def research(state: PipelineState) -> dict:
        rates = load_inr_rates(rates_path)
        r = await run_research(store, settings, rates, limit=state["options"].get("limit"))
        return {"log": [("Research", f"{r.ok}/{r.todo} companies, {len(r.failed)} failed")]}

    async def assess(state: PipelineState) -> dict:
        rates = load_inr_rates(rates_path)
        r = await run_assess(
            store, settings, profile, rates,
            research=lambda row: research_brief(store.get_research(row["company_id"])),
            limit=state["options"].get("limit"),
        )  # fmt: skip
        return {"log": [("Assess", f"{r.ok}/{r.todo} done, {len(r.failed)} failed")]}

    def export(state: PipelineState) -> dict:
        out_dir = settings.paths.output_dir
        rates = load_inr_rates(rates_path)
        report = build_report(
            store, settings, rates, research_columns(store), run_date=state["run_date"]
        )
        minutes = round((time.monotonic() - state["started"]) / 60, 1)
        m = metrics.current()
        info = [
            ("Run date", state["run_date"]),
            ("Model", settings.llm.model),
            ("USD → INR", round(rates.get("USD", 0), 2)),
            ("Duration (min)", minutes),
            *state.get("log", []),
            *(m.log_lines() if m else []),
        ]
        path = write_workbook(
            report,
            workbook_path(out_dir, state["run_date"]),
            settings.scoring.top_pick_threshold,
            info,
        )
        live = [j for j in report.jobs if j["_bucket"] != "rejected" and j["Score"] is not None]
        outcome = {
            "buckets": dict(Counter(j["_bucket"] for j in report.jobs)),
            "verdicts": dict(Counter(j["Verdict"] for j in report.jobs if j["Verdict"])),
            "scored": len(live),
            "top_picks": sum(1 for j in live if j["Score"] >= settings.scoring.top_pick_threshold),
            "pending": report.pending,
        }
        top_picks = outcome["top_picks"]
        outcome["funnel"] = pipeline_funnel(store, report.pending, len(live), top_picks)
        return {
            "workbook": str(path),
            "top": live[:5],
            "outcome": outcome,
            "log": [("Workbook", path.name)],
        }

    def notify(state: PipelineState) -> dict:
        if not state["options"].get("notify", True):
            return {}
        try:
            tg = Telegram(settings.secrets)
            if state.get("abort"):
                tg.send_message(f"⚠️ <b>Job run skipped</b>\n{state['abort']}")
                return {}
            tg.send_message(_digest(state))
            if state.get("workbook"):
                tg.send_document(Path(state["workbook"]), caption="Today's workbook")
        except NotifyError as exc:
            return {"log": [("Notify", f"failed: {exc}")]}
        return {"log": [("Notify", "sent")]}

    g = StateGraph(PipelineState)
    for name, fn in [("preflight", preflight), ("fetch", fetch), ("triage", triage),
                     ("extract", extract), ("research", research), ("assess", assess),
                     ("export", export), ("notify", notify)]:  # fmt: skip
        g.add_node(name, _timed(name, fn))
    g.add_edge(START, "preflight")
    g.add_conditional_edges("preflight", lambda s: "notify" if s.get("abort") else "fetch")
    for a, b in [("fetch", "triage"), ("triage", "extract"), ("extract", "research"),
                 ("research", "assess"), ("assess", "export"), ("export", "notify"),
                 ("notify", END)]:  # fmt: skip
        g.add_edge(a, b)
    return g.compile()


def pipeline_funnel(store: Store, pending: int, scored: int, top_picks: int) -> dict[str, int]:
    """How many open jobs reached each stage (cumulative database state, not just this run)."""
    open_jobs = store.open_jobs()

    def with_result(stage: str) -> int:
        return sum(1 for r in open_jobs if stage_result(store, r["job_id"], stage) is not None)

    return {
        "Fetched": len(open_jobs),
        "Triaged": len(open_jobs) - pending,
        "Passed triage": len(kept_jobs(store)),
        "Extracted": with_result("extract"),
        "Assessed": with_result("assess"),
        "Scored": scored,
        "Top picks": top_picks,
    }


def _timed(name: str, fn):
    """Wrap a node so its wall time lands in the active run metrics."""
    if asyncio.iscoroutinefunction(fn):

        async def run_async(state: PipelineState) -> dict:
            with metrics.StageTimer(name):
                return await fn(state)

        return run_async

    def run_sync(state: PipelineState) -> dict:
        with metrics.StageTimer(name):
            return fn(state)

    return run_sync


def _perf_line(m: metrics.RunMetrics | None, started: float) -> str:
    minutes = (time.monotonic() - started) / 60
    if m is None or not m.calls:
        return f"⏱ {minutes:.1f} min"
    out_tok = sum(c.output_tokens or 0 for c in m.calls)
    eval_s = sum(c.eval_s or 0 for c in m.calls)
    speed = f" · {out_tok / eval_s:.0f} tok/s" if eval_s else ""
    return f"⏱ {minutes:.1f} min · {len(m.calls)} LLM calls{speed}"


def _digest(state: PipelineState) -> str:
    lines = [f"🗂 <b>Job picks · {state['run_date']}</b>"]
    for j in state.get("top", []):
        pay = j.get("Realistic (₹ LPA)") or j.get("Listed (₹ LPA)") or "pay n/a"
        lines.append(
            f"{j.get('Tier', '')} <b>{j['Score']:.0f}</b> · "
            f'<a href="{j["Apply URL"]}">{j["Title"]}</a> @ {j["Company"]} · '
            f"{j.get('Work mode', '')} · {pay}"
        )
    if len(lines) == 1:
        lines.append("No scored jobs this run.")
    lines.append(_perf_line(metrics.current(), state["started"]))
    return "\n".join(lines)


async def run_pipeline(settings: Settings, options: RunOptions | None = None) -> PipelineState:
    options = options or {}
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    run_metrics = metrics.RunMetrics()
    token = metrics.activate(run_metrics)
    try:
        with Store(settings.paths.data_dir / "jobs.db") as store, metrics.VramSampler(run_metrics):
            graph = build_graph(settings, store)
            started = time.monotonic()
            state = await graph.ainvoke(
                {
                    "options": options,
                    "run_date": date.today().isoformat(),
                    "started": started,
                    "log": [],
                }
            )
            summary = {
                **run_metrics.summary(),
                "duration_min": round((time.monotonic() - started) / 60, 2),
                "outcome": state.get("outcome", {}),
                "aborted": state.get("abort"),
            }
            store.save_run(
                started_at, started_at, settings.llm.model, dict(options), summary,
                run_metrics.calls,
            )  # fmt: skip
            return state
    finally:
        metrics._current.reset(token)
