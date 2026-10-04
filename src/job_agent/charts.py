"""Run-metrics charts (PNG, light + dark) for the README and for comparing runs and models."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from job_agent.store import Store  # noqa: E402

STAGE_ORDER = ["preflight", "fetch", "triage", "extract", "research", "assess", "export", "notify"]
LLM_STAGES = ["triage", "extract", "research", "assess"]


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    text: str
    muted: str
    grid: str
    series: tuple[str, ...]


LIGHT = Theme(
    "light",
    "#fcfcfb",
    "#0b0b0b",
    "#52514e",
    "#e7e6e2",
    ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"),
)
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#33332f",
             ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"))  # fmt: skip


def _axes(theme: Theme, title: str, subtitle: str, height: float):
    fig, ax = plt.subplots(figsize=(8, height), dpi=150)
    fig.patch.set_facecolor(theme.surface)
    ax.set_facecolor(theme.surface)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme.grid)
    ax.tick_params(colors=theme.muted, labelsize=9, length=0)
    ax.grid(axis="x", color=theme.grid, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.text(0.02, 0.97, title, color=theme.text, fontsize=13, weight="bold", va="top")
    fig.text(0.02, 0.97 - 0.32 / height, subtitle, color=theme.muted, fontsize=9, va="top")
    return fig, ax


def _save(fig, out: Path, height: float) -> Path:
    fig.subplots_adjust(left=0.2, right=0.95, top=1 - 0.9 / height, bottom=0.6 / height)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def _hbar(theme: Theme, labels: list[str], values: list[float], fmt, title: str, sub: str,
          out: Path, xlabel: str) -> Path:  # fmt: skip
    height = 1.6 + 0.42 * len(labels)
    fig, ax = _axes(theme, title, sub, height)
    y = list(range(len(labels)))[::-1]
    ax.barh(y, values, height=0.62, color=theme.series[0], edgecolor=theme.surface, linewidth=2)
    ax.set_yticks(y, labels, color=theme.text)
    ax.set_xlabel(xlabel, color=theme.muted, fontsize=9)
    peak = max(values) if values else 1
    for yi, v in zip(y, values, strict=True):
        ax.text(v + peak * 0.01, yi, fmt(v), va="center", color=theme.text, fontsize=9)
    ax.set_xlim(0, peak * 1.15 or 1)
    return _save(fig, out, height)


def _duration(seconds: float) -> str:
    return f"{seconds / 60:.1f} min" if seconds >= 90 else f"{seconds:.0f} s"


def funnel_chart(summary: dict, label: str, theme: Theme, out: Path) -> Path | None:
    funnel = summary.get("outcome", {}).get("funnel")
    if not funnel:
        return None
    return _hbar(theme, list(funnel), list(funnel.values()), lambda v: f"{v:g}",
                 "Where jobs drop out", f"Cumulative job counts per stage · {label}",
                 out, "jobs")  # fmt: skip


def stage_time_chart(summary: dict, label: str, theme: Theme, out: Path) -> Path | None:
    secs = summary.get("stage_seconds") or {}
    stages = [s for s in STAGE_ORDER if secs.get(s)]
    if not stages:
        return None
    total = summary.get("duration_min")
    sub = f"Wall time per pipeline stage · {label}" + (f" · total {total:.1f} min" if total else "")
    return _hbar(theme, stages, [secs[s] for s in stages], _duration,
                 "Where the time goes", sub, out, "seconds")  # fmt: skip


def latency_chart(calls: list, label: str, theme: Theme, out: Path) -> Path | None:
    by_stage: dict[str, list[float]] = defaultdict(list)
    for c in calls:
        by_stage[c["stage"]].append(c["latency_s"])
    stages = [s for s in LLM_STAGES if by_stage.get(s)]
    if not stages:
        return None
    height = 1.6 + 0.5 * len(stages)
    fig, ax = _axes(theme, "LLM call latency",
                    f"One dot per call, line = median · {label}", height)  # fmt: skip
    y_of = {s: i for i, s in enumerate(reversed(stages))}
    for s in stages:
        xs = sorted(by_stage[s])
        n = len(xs)
        jitter = [((i * 37) % 11 - 5) * 0.03 for i in range(n)]  # deterministic spread
        ax.scatter(xs, [y_of[s] + j for j in jitter], s=34, color=theme.series[0],
                   edgecolors=theme.surface, linewidths=1.5, zorder=3)  # fmt: skip
        median = xs[n // 2]
        ax.plot([median, median], [y_of[s] - 0.3, y_of[s] + 0.3], color=theme.text, linewidth=2)
        ax.text(xs[-1], y_of[s], f"   median {median:.1f}s · n={n}", va="center",
                color=theme.muted, fontsize=8)  # fmt: skip
    ax.set_yticks(list(y_of.values()), list(y_of.keys()), color=theme.text)
    ax.set_ylim(-0.6, len(stages) - 0.4)
    ax.set_xlim(0, max(max(v) for v in by_stage.values()) * 1.35)  # room for the labels
    ax.set_xlabel("seconds per call", color=theme.muted, fontsize=9)
    return _save(fig, out, height)


def history_chart(runs: list, theme: Theme, out: Path) -> Path | None:
    """Total run duration over time, one line per model. Needs at least two runs."""
    if len(runs) < 2:
        return None
    by_model: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in runs:
        s = json.loads(r["summary_json"] or "{}")
        if s.get("duration_min") is not None:
            day = s.get("run_date") or r["started_at"][:10]
            by_model[r["model"]].append((day, s["duration_min"]))
    models = list(by_model)[: len(theme.series)]
    height = 4.0
    fig, ax = _axes(theme, "Run duration over time", "Minutes per run, by model", height)
    ax.grid(axis="y", color=theme.grid, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    for i, model in enumerate(models):
        pts = by_model[model]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=theme.series[i], linewidth=2,
                marker="o", markersize=6, markeredgecolor=theme.surface, label=model)  # fmt: skip
        ax.text(len(pts) - 1, pts[-1][1], f"  {model}", color=theme.text, fontsize=8, va="center")
    ax.legend(frameon=False, labelcolor=theme.text, fontsize=8, loc="upper left")
    ax.set_ylabel("minutes", color=theme.muted, fontsize=9)
    ax.set_ylim(bottom=0)
    return _save(fig, out, height)


def render_all(store: Store, out_dir: Path) -> list[Path]:
    """Charts for the latest run (+ history), in light and dark variants."""
    runs = store.runs()
    if not runs:
        return []
    latest = runs[-1]
    summary = json.loads(latest["summary_json"] or "{}")
    day = summary.get("run_date") or latest["started_at"][:10]
    label = f"{day} · {latest['model'].split(':', 1)[-1]}"
    calls = store.llm_calls(latest["run_id"])
    made: list[Path] = []
    for theme in (LIGHT, DARK):
        suffix = f"-{theme.name}.png"
        for path in (
            funnel_chart(summary, label, theme, out_dir / f"funnel{suffix}"),
            stage_time_chart(summary, label, theme, out_dir / f"stage-time{suffix}"),
            latency_chart(calls, label, theme, out_dir / f"llm-latency{suffix}"),
            history_chart(runs, theme, out_dir / f"history{suffix}"),
        ):
            if path:
                made.append(path)
    return made
