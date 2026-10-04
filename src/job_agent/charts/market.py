"""Charts about the job market itself, from fetched postings (no LLM output needed)."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from matplotlib.patches import FancyBboxPatch

from job_agent.charts.style import Theme, blend, figure, footer, header, save

ROLE_NAMES = {
    "fs": "Full-stack", "be": "Backend", "fe": "Frontend", "ml": "ML", "ai": "AI",
    "data_sci": "Data science", "devops": "DevOps", "ios": "Mobile", "android": "Mobile",
    "hw": "Hardware", "robotics": "Robotics", "embedded": "Embedded", "qa": "QA",
}  # fmt: skip
WHERE = ("Remote only", "Remote OK", "India office", "Abroad · visa")


def role_of(hit: dict) -> str:
    if hit.get("role") == "eng":
        types = hit.get("eng_type") or []
        return ROLE_NAMES.get(types[0], "Other eng") if types else "Other eng"
    return (hit.get("role") or "other").replace("_", " ").capitalize()


def where_of(hit: dict) -> str:
    if hit.get("remote") == "only":
        return "Remote only"
    if hit.get("remote") == "yes":
        return "Remote OK"
    if "IN" in (hit.get("locations_for_search") or []):
        return "India office"
    return "Abroad · visa"


def calendar_chart(theme: Theme, hits: list[dict], out: Path, weeks: int = 26):
    days = Counter(h["created_at"][:10] for h in hits if h.get("created_at"))
    if not days:
        return None
    last = max(date.fromisoformat(d) for d in days)
    start = last - timedelta(days=last.weekday() + 7 * (weeks - 1))
    grid = np.zeros((7, weeks))
    for d, n in days.items():
        day = date.fromisoformat(d)
        if day >= start:
            grid[day.weekday(), (day - start).days // 7] = n
    fig = figure(theme, 11, 3.9)
    header(fig, theme, "When startups post",
           f"Postings per day over the last {weeks} weeks · {int(grid.sum())} of {len(hits)} jobs",
           eyebrow="Posting calendar")  # fmt: skip
    ax = fig.add_axes((0.08, 0.1, 0.84, 0.56))
    ax.set_facecolor(theme.surface)
    peak = grid.max() or 1
    cmap = theme.cmap()
    for wk in range(weeks):
        for wd in range(7):
            n = grid[wd, wk]
            color = theme.panel if n == 0 else cmap(0.25 + 0.75 * (n / peak) ** 0.5)
            ax.add_patch(FancyBboxPatch((wk + 0.08, 6 - wd + 0.08), 0.84, 0.84,
                                        boxstyle="round,pad=0,rounding_size=0.18",
                                        facecolor=color, edgecolor="none"))  # fmt: skip
    for wk in range(weeks):
        first = start + timedelta(weeks=wk)
        if first.day <= 7:
            ax.text(wk + 0.1, 7.35, first.strftime("%b"), fontsize=8.5, color=theme.muted)
    for wd, name in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
        ax.text(-0.3, 6 - wd + 0.5, name, ha="right", va="center", fontsize=8, color=theme.muted)
    for i, f in enumerate((0, 0.25, 0.5, 0.75, 1.0)):
        color = theme.panel if f == 0 else cmap(0.25 + 0.75 * f**0.5)
        ax.add_patch(FancyBboxPatch((weeks - 5.2 + i * 0.9, -1.15), 0.7, 0.7,
                                    boxstyle="round,pad=0,rounding_size=0.15",
                                    facecolor=color, edgecolor="none"))  # fmt: skip
    ax.text(weeks - 5.5, -0.8, "fewer", ha="right", va="center", fontsize=7.5, color=theme.muted)
    ax.text(weeks - 0.5, -0.8, f"more (peak {int(peak)})", va="center", fontsize=7.5,
            color=theme.muted)  # fmt: skip
    ax.set_xlim(-1, weeks + 2)
    ax.set_ylim(-1.4, 7.9)
    ax.set_aspect("equal")
    ax.axis("off")
    return save(fig, out)


def market_chart(theme: Theme, hits: list[dict], out: Path, top: int = 9):
    if not hits:
        return None
    counts = Counter((role_of(h), where_of(h)) for h in hits)
    roles = [r for r, _ in Counter(role_of(h) for h in hits).most_common(top)]
    matrix = np.array([[counts[(r, w)] for w in WHERE] for r in roles], dtype=float)
    fig = figure(theme, 9.5, 1.9 + 0.5 * len(roles))
    header(
        fig,
        theme,
        "What's open, and where",
        f"Role × work arrangement across {len(hits)} postings",
        eyebrow="Market map",
    )
    ax = fig.add_axes((0.2, 0.08, 0.66, 0.62 + 0.01 * (top - len(roles))))
    ax.set_facecolor(theme.surface)
    peak = matrix.max() or 1
    cmap = theme.cmap()
    for i, _ in enumerate(roles):
        for j, _ in enumerate(WHERE):
            n = matrix[i, j]
            y = len(roles) - 1 - i
            color = theme.panel if n == 0 else cmap(0.2 + 0.8 * (n / peak) ** 0.6)
            ax.add_patch(FancyBboxPatch((j + 0.05, y + 0.07), 0.9, 0.86,
                                        boxstyle="round,pad=0,rounding_size=0.08",
                                        facecolor=color, edgecolor="none"))  # fmt: skip
            if n:
                dark_cell = (n / peak) ** 0.6 > 0.55
                ink = theme.surface if (dark_cell == (theme.name == "light")) else theme.text
                ax.text(j + 0.5, y + 0.5, f"{int(n)}", ha="center", va="center", fontsize=9,
                        color=ink, weight="bold")  # fmt: skip
    for i, r in enumerate(roles):
        ax.text(-0.08, len(roles) - 1 - i + 0.5, r, ha="right", va="center", fontsize=9,
                color=theme.text)  # fmt: skip
    for j, w in enumerate(WHERE):
        ax.text(j + 0.5, len(roles) + 0.25, w, ha="center", fontsize=8.5, color=theme.muted)
    totals = matrix.sum(axis=1)
    for i, t in enumerate(totals):
        y = len(roles) - 1 - i
        ax.barh(y + 0.5, 0.6 * t / totals.max(), left=len(WHERE) + 0.15, height=0.34,
                color=blend(theme.indigo, theme.surface, 0.55))  # fmt: skip
        ax.text(len(WHERE) + 0.2 + 0.6 * t / totals.max(), y + 0.5, f" {int(t)}", va="center",
                fontsize=8, color=theme.muted)  # fmt: skip
    ax.set_xlim(0, len(WHERE) + 1.1)
    ax.set_ylim(0, len(roles) + 0.6)
    ax.axis("off")
    footer(fig, theme, "Bars on the right: total postings per role")
    return save(fig, out)
