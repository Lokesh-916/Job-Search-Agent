"""Deterministic gating, bucketing and scoring on top of the LLM's judgments.

The LLM reads and judges; this module only does arithmetic, so rankings stay explainable
and comparable across models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from job_agent.fx import to_lpa
from job_agent.schemas import Assessment, Extraction, Triage
from job_agent.settings import Preferences, Scoring

Bucket = Literal[
    "remote_foreign", "remote_india", "india_onsite", "abroad_sponsored", "needs_review", "rejected"
]

ELIGIBILITY = {
    "remote_india_ok": 1.0,
    "india_office": 0.7,  # wanted, but ranked below remote; preferred cities add a bonus
    "remote_unclear": 0.5,
    "abroad_credible": 0.45,
    "abroad_unclear": 0.25,
}
CITY_BONUS = (0.15, 0.1, 0.05)  # 1st, 2nd, 3rd... preferred city (never beats remote)
CITY_ALIASES = {
    "bengaluru": ("bengaluru", "bangalore", "blr"),
    "hyderabad": ("hyderabad", "secunderabad", "hitec city", "hyd"),
    "mumbai": ("mumbai", "bombay", "navi mumbai"),
    "delhi": ("delhi", "new delhi", "gurgaon", "gurugram", "noida", "ncr"),
    "chennai": ("chennai", "madras"),
}
DSA = {"low": 1.0, "unknown": 0.55, "medium": 0.45, "high": 0.1}
JOINING_PENALTY = {"conflict": 10, "tight": 4}
RED_FLAG_PENALTY, MAX_RED_FLAG_PENALTY = 5, 15


@dataclass
class Scored:
    job_id: str
    bucket: Bucket
    score: float | None = None
    components: dict[str, float] = field(default_factory=dict)
    reject_reason: str | None = None
    listed_lpa: tuple[float | None, float | None] = (None, None)
    pay_lpa: float | None = None  # the figure used for the pay score


def listed_lpa(ex: Extraction, rates: dict[str, float]) -> tuple[float | None, float | None]:
    lo = to_lpa(ex.salary_min, ex.salary_currency, ex.salary_period, rates)
    hi = to_lpa(ex.salary_max, ex.salary_currency, ex.salary_period, rates)
    return lo, hi or lo


def hard_reject(
    triage: Triage | None,
    ex: Extraction | None,
    listed: tuple[float | None, float | None],
    prefs: Preferences,
) -> str | None:
    """Reasons a job can be dropped before the expensive assessment."""
    if triage and not triage.keep:
        return f"Triage: {triage.reason}"
    if ex is None:
        return None
    if ex.india_eligible == "no" and ex.visa_sponsorship != "offered":
        return "Not open to candidates in India and no visa sponsorship"
    if listed[1] is not None and listed[1] < prefs.salary_floor_lpa:
        return f"Pay tops out at {listed[1]} LPA (floor {prefs.salary_floor_lpa})"
    if ex.fresher_ok == "no" and (ex.min_years_experience or 0) > prefs.max_experience_years + 1:
        return f"Needs {ex.min_years_experience:g}+ years of experience"
    return None


def pay_score(lpa: float | None, prefs: Preferences, usd_inr: float) -> float:
    """Piecewise-linear: floor -> 0.3, good -> 0.55, foreign target -> 0.8, stretch -> 1.0."""
    if lpa is None:
        return 0.35
    stretch = prefs.salary_stretch_usd * usd_inr / 100_000
    points = [
        (prefs.salary_floor_lpa, 0.3),
        (prefs.salary_good_lpa, 0.55),
        (prefs.salary_foreign_target_lpa, 0.8),
        (stretch, 1.0),
    ]
    if lpa <= points[0][0]:
        return 0.0 if lpa < points[0][0] else points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if lpa <= x1:
            return round(y0 + (y1 - y0) * (lpa - x0) / (x1 - x0), 3)
    return 1.0


def _eligibility(ex: Extraction, a: Assessment | None) -> str:
    if ex.relocation_abroad_required:
        return "abroad_credible" if a and a.sponsorship_credible == "yes" else "abroad_unclear"
    if ex.work_mode == "remote":
        return "remote_india_ok" if ex.india_eligible == "yes" else "remote_unclear"
    return "india_office"


def _location_value(ex: Extraction, a: Assessment | None, prefs: Preferences) -> float:
    kind = _eligibility(ex, a)
    value = ELIGIBILITY[kind]
    if kind == "india_office":
        rank = city_rank(ex.locations, prefs.preferred_cities)
        if rank is not None:
            value += CITY_BONUS[min(rank, len(CITY_BONUS) - 1)]
    return value


def city_rank(locations: list[str], preferred: list[str]) -> int | None:
    """Index of the best preferred city among the job's locations (0 = favourite)."""
    text = " ".join(locations).lower()
    for rank, city in enumerate(preferred):
        if any(alias in text for alias in CITY_ALIASES.get(city.lower(), (city.lower(),))):
            return rank
    return None


def bucket_for(ex: Extraction, company_country: str | None) -> Bucket:
    if ex.relocation_abroad_required:
        return "abroad_sponsored"
    if ex.india_eligible == "unclear":
        return "needs_review"
    if ex.work_mode == "remote":
        return "remote_india" if company_country == "IN" else "remote_foreign"
    return "india_onsite"


def score_job(
    job_id: str,
    triage: Triage | None,
    ex: Extraction | None,
    a: Assessment | None,
    company_country: str | None,
    rates: dict[str, float],
    prefs: Preferences,
    weights: Scoring,
) -> Scored:
    listed = listed_lpa(ex, rates) if ex else (None, None)
    if reason := hard_reject(triage, ex, listed, prefs):
        return Scored(job_id, "rejected", reject_reason=reason, listed_lpa=listed)
    if ex is None or a is None:
        return Scored(job_id, "needs_review", listed_lpa=listed)
    if ex.relocation_abroad_required and a.sponsorship_credible == "no":
        return Scored(job_id, "rejected", reject_reason="Relocation needed, sponsorship unlikely")
    if (
        a.realistic_salary_lpa_max is not None
        and a.realistic_salary_lpa_max < prefs.salary_floor_lpa
    ):
        return Scored(
            job_id,
            "rejected",
            reject_reason=f"Realistic pay ~{a.realistic_salary_lpa_max} LPA, below floor",
            listed_lpa=listed,
        )

    realistic = [v for v in (a.realistic_salary_lpa_min, a.realistic_salary_lpa_max) if v]
    pay = sum(realistic) / len(realistic) if realistic else listed[0]
    components = {
        "remote_eligibility": _location_value(ex, a, prefs),
        "pay": pay_score(pay, prefs, rates.get("USD", 90.0)),
        "low_dsa": DSA[a.dsa_risk],
        "fit": a.fit_score / 100,
        "company": (a.company_quality / 10) if a.company_quality is not None else 0.5,
    }
    total = sum(getattr(weights, k) * v for k, v in components.items())
    total -= JOINING_PENALTY.get(a.joining_fit, 0)
    total -= min(RED_FLAG_PENALTY * len(ex.red_flags), MAX_RED_FLAG_PENALTY)
    return Scored(
        job_id,
        bucket_for(ex, company_country),
        score=round(max(total, 0.0), 1),
        components=components,
        listed_lpa=listed,
        pay_lpa=round(pay, 1) if pay else None,
    )
