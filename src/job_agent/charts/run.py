"""Charts about one pipeline run (and the run history)."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath

from job_agent.charts.style import (
    LLM_STAGES,
    Theme,
    blend,
    clean_axes,
    figure,
    fmt_seconds,
    footer,
    header,
    save,
    tile,
)

STAGE_ORDER = ["preflight", "fetch", "triage", "extract", "research", "assess", "export", "notify"]
LAT_TICKS = [(1, "1 s"), (3, "3 s"), (10, "10 s"), (30, "30 s"), (60, "1 min"), (180, "3 min")]


# --- timeline -----------------------------------------------------------------------------


def _lanes(calls: list[tuple[float, float]]) -> list[int]:
    """Greedy lane per call so overlapping (parallel) calls stack instead of hiding."""
    ends: list[float] = []
    lanes = []
    for start, dur in calls:
        for i, end in enumerate(ends):
            if start >= end - 1e-6:
                ends[i] = start + dur
                lanes.append(i)
                break
        else:
            ends.append(start + dur)
            lanes.append(len(ends) - 1)
    return lanes


def draw_timeline(ax, theme: Theme, spans: list, calls: list[dict]) -> None:
    present = [s for s in STAGE_ORDER if any(n == s for n, _, _ in spans)]
    y_of = {s: len(present) - 1 - i for i, s in enumerate(present)}
    total = max(end for _, _, end in spans) / 60
    by_stage: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for c in calls:
        if c.get("started_s") is not None:
            by_stage[c["stage"]].append((c["started_s"] / 60, c["latency_s"] / 60))
    for name, start, end in spans:
        y, color = y_of[name], theme.stage_color(name)
        s, e = start / 60, end / 60
        llm = name in LLM_STAGES
        ax.barh(y, max(e - s, total * 0.004), left=s, height=0.72, linewidth=0,
                color=blend(color, theme.surface, 0.14 if llm else 0.35))  # fmt: skip
        ax.text(e + total * 0.012, y, fmt_seconds(end - start), va="center", fontsize=8.5,
                color=theme.muted)  # fmt: skip
        stage_calls = sorted(by_stage.get(name, []))
        if stage_calls:
            lanes = _lanes(stage_calls)
            n = max(lanes) + 1
            lane_h = 0.6 / n
            for (cs, cd), lane in zip(stage_calls, lanes, strict=True):
                y0 = y - 0.3 + lane * lane_h + lane_h * 0.15
                ax.barh(y0 + lane_h * 0.35, max(cd, total * 0.002), left=cs, height=lane_h * 0.7,
                        color=color, edgecolor=theme.surface, linewidth=0.6)  # fmt: skip
    ax.set_yticks(list(y_of.values()), list(y_of.keys()))
    for label in ax.get_yticklabels():
        label.set_color(theme.text)
    ax.set_ylim(-0.6, len(present) - 0.4)
    ax.set_xlim(0, total * 1.1)
    ax.set_xlabel("minutes into the run", fontsize=8.5)
    clean_axes(ax, theme, grid="x")


def timeline_chart(theme: Theme, summary: dict, calls: list[dict], label: str, out: Path):
    spans = summary.get("stage_spans")
    if not spans:
        return None
    fig = figure(theme, 10, 5.2)
    header(fig, theme, "Anatomy of a run",
           f"Each sliver is one LLM call; stacked slivers ran in parallel · {label}",
           eyebrow="Pipeline timeline")  # fmt: skip
    ax = fig.add_axes((0.12, 0.13, 0.84, 0.6))
    draw_timeline(ax, theme, spans, calls)
    return save(fig, out)


# --- sankey -------------------------------------------------------------------------------


def _node_color(theme: Theme, name: str, continues: bool) -> str:
    if name == "Top picks":
        return theme.amber
    if name in ("Worth a look", "Scored"):
        return theme.teal
    if name in ("Not processed yet", "Needs review"):
        return theme.muted
    return theme.indigo if continues else theme.rose


def draw_flow(ax, theme: Theme, flow: list) -> None:
    links = [(a, b, n) for a, b, n in flow if n > 0]
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for a, b, n in links:
        outgoing[a].append((b, n))
        incoming[b].append((a, n))
    nodes = list(dict.fromkeys([x for a, b, _ in links for x in (a, b)]))
    depth = {n: 0 for n in nodes if not incoming[n]}
    frontier = list(depth)
    while frontier:
        nxt = []
        for a in frontier:
            for b, _ in outgoing[a]:
                if depth.get(b, -1) < depth[a] + 1:
                    depth[b] = depth[a] + 1
                    nxt.append(b)
        frontier = nxt
    value = {n: max(sum(v for _, v in incoming[n]), sum(v for _, v in outgoing[n])) for n in nodes}
    cols: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        cols[depth[n]].append(n)
    for d in cols:  # continuing nodes first, then drop-outs by size
        cols[d].sort(key=lambda n: (not outgoing[n], -value[n]))

    gap, min_h = 0.035, 0.014
    biggest = max(sum(value[n] for n in col) for col in cols.values())
    scale = (1 - gap * (max(len(c) for c in cols.values()) - 1)) / biggest
    max_d = max(cols)
    width = 0.012
    pos: dict[str, tuple[float, float, float]] = {}  # x, y_top, height
    for d, col in cols.items():
        x = 0.02 + d * (0.74 / max(max_d, 1))
        heights = [max(value[n] * scale, min_h) for n in col]
        y = 0.5 + (sum(heights) + gap * (len(col) - 1)) / 2
        for n, h in zip(col, heights, strict=True):
            pos[n] = (x, y, h)
            y -= h + gap

    out_cursor = {n: pos[n][1] for n in nodes}
    in_cursor = {n: pos[n][1] for n in nodes}
    for a in nodes:
        xa, _, ha = pos[a]
        out_total = sum(v for _, v in outgoing[a]) or 1
        for b, v in sorted(outgoing[a], key=lambda t: cols[depth[t[0]]].index(t[0])):
            xb, _, hb = pos[b]
            in_total = sum(w for _, w in incoming[b]) or 1
            ts, th = ha * v / out_total, hb * v / in_total
            y0, y1 = out_cursor[a], in_cursor[b]
            out_cursor[a] -= ts
            in_cursor[b] -= th
            x0, x1 = xa + width, xb
            mid = (x0 + x1) / 2
            verts = [(x0, y0), (mid, y0), (mid, y1), (x1, y1), (x1, y1 - th),
                     (mid, y1 - th), (mid, y0 - ts), (x0, y0 - ts), (x0, y0)]  # fmt: skip
            codes = [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                     MplPath.LINETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
                     MplPath.CLOSEPOLY]  # fmt: skip
            color = _node_color(theme, b, bool(outgoing[b]))
            fill = blend(color, theme.surface, 0.3)
            ax.add_patch(
                PathPatch(MplPath(verts, codes), facecolor=fill, edgecolor="none", zorder=1)
            )
    for n in nodes:
        x, y, h = pos[n]
        color = _node_color(theme, n, bool(outgoing[n]))
        box = "round,pad=0,rounding_size=0.003"
        ax.add_patch(FancyBboxPatch((x, y - h), width, h, boxstyle=box, facecolor=color,
                                    edgecolor="none", zorder=2))  # fmt: skip
        ax.text(x + width + 0.008, y - h / 2, n, va="center", fontsize=8.5, color=theme.text,
                zorder=3)  # fmt: skip
        ax.text(x + width + 0.008, y - h / 2 - 0.028, f"{value[n]:,}", va="center", fontsize=8,
                color=theme.muted, weight="bold", zorder=3)  # fmt: skip
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.05, 1.05)
    ax.axis("off")


def flow_chart(theme: Theme, summary: dict, label: str, out: Path):
    flow = summary.get("outcome", {}).get("flow")
    if not flow:
        return None
    fig = figure(theme, 11, 5.8)
    header(fig, theme, "Where the jobs go",
           f"Every fetched job, followed to its fate · rose = dropped, amber = top pick · {label}",
           eyebrow="Job flow")  # fmt: skip
    ax = fig.add_axes((0.04, 0.06, 0.92, 0.7))
    ax.set_facecolor(theme.surface)
    draw_flow(ax, theme, flow)
    return save(fig, out)


# --- latency ridgeline --------------------------------------------------------------------


def _kde(samples: np.ndarray, grid: np.ndarray) -> np.ndarray:
    n = len(samples)
    bw = max(0.06, 1.06 * (samples.std() or 0.15) * n ** (-1 / 5))
    dens = np.exp(-0.5 * ((grid[:, None] - samples[None, :]) / bw) ** 2).sum(axis=1)
    return dens / dens.max()


def latency_chart(theme: Theme, calls: list[dict], label: str, out: Path):
    by_stage: dict[str, list[float]] = defaultdict(list)
    for c in calls:
        if c["latency_s"] > 0:
            by_stage[c["stage"]].append(c["latency_s"])
    stages = [s for s in LLM_STAGES if by_stage.get(s)]
    if not stages:
        return None
    every = [v for s in stages for v in by_stage[s]]
    lo, hi = math.log10(min(every) * 0.6), math.log10(max(every) * 1.8)
    grid = np.linspace(lo, hi, 400)
    fig = figure(theme, 10, 1.9 + 1.0 * len(stages))
    header(fig, theme, "How long one LLM call takes",
           f"Distribution per stage on a log scale; ticks are individual calls · {label}",
           eyebrow="Latency")  # fmt: skip
    ax = fig.add_axes((0.12, 0.14, 0.82, 0.62 - 0.02 * (4 - len(stages))))
    clean_axes(ax, theme, grid="x")
    for i, stage in enumerate(stages):
        y = len(stages) - 1 - i
        xs = np.log10(np.array(by_stage[stage]))
        dens = _kde(xs, grid) * 0.85
        color = theme.stage_color(stage)
        ax.fill_between(grid, y, y + dens, color=blend(color, theme.surface, 0.45), zorder=2 + i,
                        linewidth=0)  # fmt: skip
        ax.plot(grid, y + dens, color=color, linewidth=1.6, zorder=3 + i)
        ax.vlines(xs, y - 0.12, y - 0.02, color=color, linewidth=1, alpha=0.9, zorder=3 + i)
        med = float(np.median(by_stage[stage]))
        ax.vlines(math.log10(med), y, y + float(np.interp(math.log10(med), grid, dens)),
                  color=theme.text, linewidth=1.4, zorder=4 + i)  # fmt: skip
        ax.text(hi, y + 0.18, f"median {fmt_seconds(med)} · {len(xs)} calls  ", ha="right",
                fontsize=8.5, color=theme.muted, zorder=5 + i)  # fmt: skip
    ax.set_yticks(range(len(stages)), list(reversed(stages)))
    for t in ax.get_yticklabels():
        t.set_color(theme.text)
    ticks = [(math.log10(v), s) for v, s in LAT_TICKS if lo <= math.log10(v) <= hi]
    ax.set_xticks([t for t, _ in ticks], [s for _, s in ticks])
    ax.set_xlim(lo, hi)
    ax.set_ylim(-0.3, len(stages) - 0.05)
    return save(fig, out)


# --- hero card ----------------------------------------------------------------------------


def hero_chart(theme: Theme, summary: dict, calls: list[dict], model: str, out: Path):
    spans = summary.get("stage_spans")
    if not spans:
        return None
    out_ = summary.get("outcome", {})
    funnel = out_.get("funnel", {})
    eval_s = sum(c.get("eval_s") or 0 for c in calls)
    tokens = sum(c.get("output_tokens") or 0 for c in calls)
    speed = f"{tokens / eval_s:.0f}" if eval_s else "—"
    fig = figure(theme, 12, 6.4)
    header(fig, theme, f"Run of {summary.get('run_date', '')}",
           f"{model} on one RTX 2000 Ada · fetch → triage → extract → research → assess",
           eyebrow="Job-Search-Agent · run report")  # fmt: skip
    kpis = [
        (f"{funnel.get('Fetched', 0):,}", "jobs scanned", theme.indigo),
        (f"{len(calls)}", "LLM calls", theme.rose),
        (f"{summary.get('duration_min', 0):.1f} min", "wall time", theme.amber),
        (speed, "tokens / second", theme.teal),
        (f"{out_.get('scored', 0)} · {out_.get('top_picks', 0)}", "scored · top picks",
         theme.amber),
    ]  # fmt: skip
    w, gap = 0.172, 0.0125
    for i, (value, label, accent) in enumerate(kpis):
        tile(fig, theme, (0.04 + i * (w + gap), 0.6, w, 0.15), value, label, accent)
    ax = fig.add_axes((0.11, 0.1, 0.85, 0.42))
    draw_timeline(ax, theme, spans, calls)
    footer(fig, theme, "Each sliver in the timeline is one LLM call · generated by job-agent stats")
    return save(fig, out)


# --- history ------------------------------------------------------------------------------


def history_chart(theme: Theme, runs: list[dict[str, Any]], out: Path):
    if len(runs) < 2:
        return None
    labels = [r["date"][5:] for r in runs]
    panels = [("Wall time", "min", [r["minutes"] for r in runs], theme.amber),
              ("LLM calls", "calls", [r["calls"] for r in runs], theme.rose),
              ("Jobs scored", "jobs", [r["scored"] for r in runs], theme.teal)]  # fmt: skip
    fig = figure(theme, 12, 4.6)
    header(fig, theme, "Run over run", "How each run compares, newest on the right",
           eyebrow="History")  # fmt: skip
    for i, (title, unit, values, color) in enumerate(panels):
        ax = fig.add_axes((0.05 + i * 0.32, 0.14, 0.27, 0.5))
        clean_axes(ax, theme, grid="y")
        x = list(range(len(values)))
        ax.fill_between(x, values, color=blend(color, theme.surface, 0.18), linewidth=0)
        ax.plot(x, values, color=color, linewidth=2, marker="o", markersize=5,
                markeredgecolor=theme.surface, markeredgewidth=1.5)  # fmt: skip
        ax.set_xticks(x, labels, fontsize=8)
        ax.set_title(f"{title}", loc="left", fontsize=10, color=theme.text, weight="bold")
        ax.text(x[-1], values[-1], f"  {values[-1]:g} {unit}", va="bottom", fontsize=8.5,
                color=theme.text)  # fmt: skip
        ax.set_ylim(0, max(values) * 1.3 or 1)
    return save(fig, out)
