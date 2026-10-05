"""Where the scored jobs sit: realistic pay against overall score, one dot per job."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_agent.charts.style import Theme, clean_axes, figure, footer, header, save

# Fixed order: colour follows the work arrangement, never its rank.
WHERE = [
    ("remote_india", "Remote from India", "teal"),
    ("remote_foreign", "Remote (global)", "indigo"),
    ("india_onsite", "India office", "amber"),
    ("abroad_sponsored", "Abroad · visa", "rose"),
]
LABELS = 5  # direct-label only the best few


def picks_chart(
    theme: Theme,
    jobs: list[dict[str, Any]],
    out: Path,
    pay_floor: float = 9,
    threshold: float = 75,
):
    pts = [j for j in jobs if j.get("_pay_lpa") and j.get("Score") is not None
           and j.get("_bucket") != "rejected"]  # fmt: skip
    if len(pts) < 3:
        return None
    fig = figure(theme, 12, 6.4)
    header(fig, theme, "Fit × pay",
           f"{len(pts)} scored jobs with a pay estimate · realistic ₹ LPA vs overall score",
           eyebrow="The picks")  # fmt: skip
    ax = fig.add_axes((0.07, 0.12, 0.88, 0.62))
    clean_axes(ax, theme, grid="y")
    xmax = max(j["_pay_lpa"] for j in pts) * 1.12
    ax.axvspan(0, pay_floor, color=theme.panel, zorder=0, linewidth=0)
    ax.text(pay_floor / 2, 2, f"below {pay_floor:g} LPA", ha="center", fontsize=8,
            color=theme.muted)  # fmt: skip
    ax.axhline(threshold, color=theme.muted, linewidth=0.8, linestyle=(0, (4, 4)), zorder=1)
    ax.text(xmax, threshold + 1, "top-pick line ", ha="right", va="bottom", fontsize=8,
            color=theme.muted)  # fmt: skip
    for key, name, color in WHERE:
        group = [j for j in pts if j["_bucket"] == key]
        if not group:
            continue
        ax.scatter([j["_pay_lpa"] for j in group], [j["Score"] for j in group], s=70,
                   color=getattr(theme, color), edgecolors=theme.surface, linewidths=2,
                   label=f"{name} ({len(group)})", zorder=3)  # fmt: skip
    other = [j for j in pts if j["_bucket"] not in {k for k, _, _ in WHERE}]
    if other:
        ax.scatter([j["_pay_lpa"] for j in other], [j["Score"] for j in other], s=55,
                   color=theme.muted, edgecolors=theme.surface, linewidths=2,
                   label=f"Needs review ({len(other)})", zorder=2)  # fmt: skip
    for j in sorted(pts, key=lambda j: -j["Score"])[:LABELS]:
        ax.annotate(f"{j['Company']}"[:22], (j["_pay_lpa"], j["Score"]), xytext=(7, 4),
                    textcoords="offset points", fontsize=8.5, color=theme.text)  # fmt: skip
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Realistic pay (₹ LPA, midpoint)", fontsize=9)
    ax.set_ylabel("Score", fontsize=9)
    leg = ax.legend(loc="lower right", frameon=False, fontsize=8.5, labelcolor=theme.text)
    for h in leg.legend_handles:
        h.set_sizes([60])
    footer(fig, theme, "Score = remote › pay › low-DSA interviews › fit, from the LLM's judgments")
    return save(fig, out)
