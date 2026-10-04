"""Shared look for every chart: midnight / paper themes, one validated palette, typography.

Palette (validated for colour-vision deficiency and contrast against each surface):
    indigo · rose · amber · teal, always assigned in that order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgb  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

FONTS = ["Ubuntu", "Inter", "Segoe UI", "Noto Sans", "DejaVu Sans"]
LLM_STAGES = ("triage", "extract", "research", "assess")


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str  # figure background
    panel: str  # cards / bands
    text: str
    muted: str
    faint: str  # gridlines, hairlines
    series: tuple[str, str, str, str]  # indigo, rose, amber, teal
    ramp: tuple[str, str]  # sequential low -> high (indigo)

    @property
    def indigo(self) -> str:
        return self.series[0]

    @property
    def rose(self) -> str:
        return self.series[1]

    @property
    def amber(self) -> str:
        return self.series[2]

    @property
    def teal(self) -> str:
        return self.series[3]

    def stage_color(self, stage: str) -> str:
        return self.series[LLM_STAGES.index(stage)] if stage in LLM_STAGES else self.muted

    def cmap(self) -> LinearSegmentedColormap:
        return LinearSegmentedColormap.from_list(f"seq-{self.name}", [self.ramp[0], self.ramp[1]])


PAPER = Theme(
    "light", surface="#fbfaf7", panel="#f1efe9", text="#14161f", muted="#5d6275",
    faint="#e4e1d8", series=("#4453d6", "#d2496a", "#c47d0e", "#13917c"),
    ramp=("#eceefc", "#2b37a8"),
)  # fmt: skip
MIDNIGHT = Theme(
    "dark", surface="#0f1222", panel="#181c33", text="#eceef7", muted="#9aa0b8",
    faint="#262b45", series=("#6c79ec", "#e0587a", "#c88516", "#22a58e"),
    ramp=("#1a1f3d", "#aab3ff"),
)  # fmt: skip
THEMES = (PAPER, MIDNIGHT)


def figure(theme: Theme, width: float, height: float):
    plt.rcParams.update({
        "font.family": FONTS,
        "font.size": 10,
        "axes.edgecolor": theme.faint,
        "axes.labelcolor": theme.muted,
        "xtick.color": theme.muted,
        "ytick.color": theme.muted,
        "text.color": theme.text,
    })  # fmt: skip
    fig = plt.figure(figsize=(width, height), dpi=160)
    fig.patch.set_facecolor(theme.surface)
    return fig


def clean_axes(ax, theme: Theme, grid: str | None = "x") -> None:
    ax.set_facecolor(theme.surface)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0, labelsize=9)
    if grid:
        ax.grid(axis=grid, color=theme.faint, linewidth=0.7)
    ax.set_axisbelow(True)


def header(fig, theme: Theme, title: str, subtitle: str, eyebrow: str = "") -> None:
    """Editorial header: small caps eyebrow, bold title, muted subtitle."""
    top = 0.955
    if eyebrow:
        fig.text(0.04, top, eyebrow.upper(), color=theme.amber, fontsize=8.5, weight="bold")
        top -= 0.055
    fig.text(0.04, top, title, color=theme.text, fontsize=17, weight="bold", va="top")
    fig.text(0.04, top - 0.07, subtitle, color=theme.muted, fontsize=10, va="top")


def footer(fig, theme: Theme, text: str) -> None:
    fig.text(0.04, 0.025, text, color=theme.muted, fontsize=7.5, alpha=0.8)


def tile(fig, theme: Theme, rect: tuple[float, float, float, float], value: str, label: str,
         accent: str | None = None) -> None:  # fmt: skip
    """A KPI tile: big number, small label, thin accent bar on the left."""
    x, y, w, h = rect
    fig.patches.append(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.012", transform=fig.transFigure,
        facecolor=theme.panel, edgecolor="none", zorder=0,
    ))  # fmt: skip
    fig.patches.append(FancyBboxPatch(
        (x, y + h * 0.18), 0.004, h * 0.64, boxstyle="round,pad=0,rounding_size=0.002",
        transform=fig.transFigure, facecolor=accent or theme.indigo, edgecolor="none",
    ))  # fmt: skip
    fig.text(x + 0.018, y + h * 0.56, value, color=theme.text, fontsize=19, weight="bold",
             va="center")  # fmt: skip
    fig.text(x + 0.018, y + h * 0.24, label, color=theme.muted, fontsize=8.5, va="center")


def blend(color: str, onto: str, alpha: float) -> tuple[float, float, float]:
    """Opaque mix of `color` over `onto` (for fills that must not show what's beneath)."""
    c, b = to_rgb(color), to_rgb(onto)
    return tuple(alpha * ci + (1 - alpha) * bi for ci, bi in zip(c, b, strict=True))


def save(fig, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def fmt_seconds(s: float) -> str:
    if s >= 90:
        return f"{s / 60:.1f} min"
    return f"{s:.0f} s" if s >= 10 else f"{s:.1f} s"
