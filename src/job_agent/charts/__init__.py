"""Charts for the README and `job-agent stats` (light + dark PNGs)."""

from __future__ import annotations

import json
from pathlib import Path

from job_agent.charts.market import calendar_chart, market_chart
from job_agent.charts.picks import picks_chart
from job_agent.charts.run import (
    flow_chart,
    hero_chart,
    history_chart,
    latency_chart,
    timeline_chart,
)
from job_agent.charts.style import THEMES
from job_agent.store import Store


def _history(store: Store) -> list[dict]:
    rows = []
    for r in store.runs():
        s = json.loads(r["summary_json"] or "{}")
        rows.append({
            "date": s.get("run_date") or r["started_at"][:10],
            "minutes": s.get("duration_min") or 0,
            "calls": len(store.llm_calls(r["run_id"])),
            "scored": s.get("outcome", {}).get("scored", 0),
        })  # fmt: skip
    return rows


def render_all(
    store: Store,
    out_dir: Path,
    jobs: list[dict] | None = None,
    pay_floor: float = 9,
    threshold: float = 75,
) -> list[Path]:
    """Every chart that has data, in light and dark variants. Returns the files written.

    `jobs`: scored report records, for the fit × pay chart."""
    made: list[Path] = []
    hits = [json.loads(r["hit_json"] or "{}") for r in store.open_jobs()]
    runs = store.runs()
    latest = runs[-1] if runs else None
    summary = json.loads(latest["summary_json"] or "{}") if latest else {}
    calls = [dict(c) for c in store.llm_calls(latest["run_id"])] if latest else []
    model = latest["model"].split(":", 1)[-1] if latest else ""
    label = f"{summary.get('run_date') or (latest['started_at'][:10] if latest else '')} · {model}"
    history = _history(store)
    for theme in THEMES:
        sfx = f"-{theme.name}.png"
        charts = [
            calendar_chart(theme, hits, out_dir / f"calendar{sfx}"),
            market_chart(theme, hits, out_dir / f"market{sfx}"),
            picks_chart(theme, jobs or [], out_dir / f"picks{sfx}", pay_floor, threshold),
        ]
        if latest:
            charts += [
                hero_chart(theme, summary, calls, model, out_dir / f"hero{sfx}"),
                timeline_chart(theme, summary, calls, label, out_dir / f"timeline{sfx}"),
                flow_chart(theme, summary, label, out_dir / f"flow{sfx}"),
                latency_chart(theme, calls, label, out_dir / f"latency{sfx}"),
                history_chart(theme, history, out_dir / f"history{sfx}"),
            ]
        made += [p for p in charts if p]
    return made
