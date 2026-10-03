"""Typed LLM outputs. Field descriptions are part of the JSON schema the model is constrained to."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RoleCategory = Literal[
    "ai_engineering",  # building agents, LLM apps, AI-powered products
    "ml_research",
    "backend",
    "fullstack",
    "frontend",
    "devops_platform",
    "data_engineering",
    "mobile",
    "other_engineering",  # hardware, robotics, embedded, QA, ...
    "non_technical",  # sales, marketing, ops, support, recruiting, ...
]
YesNoUnclear = Literal["yes", "no", "unclear"]


class Triage(BaseModel):
    """Quick screen on title + snippet: is this worth a full read?"""

    category: RoleCategory = Field(
        description="What the job actually is, judged from the work, not the title"
    )
    keep: bool = Field(
        description=(
            "True if it's a software/technical role a fresher could do; "
            "False for non-technical or clearly senior roles"
        )
    )
    reason: str = Field(description="One short sentence explaining the decision")


class Extraction(BaseModel):
    """Facts read from the full posting. Use null when the posting doesn't say."""

    category: RoleCategory
    builds_ai: bool = Field(
        description="Does the day-to-day work involve building with LLMs/agents/ML?"
    )
    ai_work: str | None = Field(None, description="If builds_ai, what AI work exactly, in one line")

    work_mode: Literal["remote", "hybrid", "onsite", "unclear"]
    locations: list[str] = Field(
        default_factory=list, description="Office cities/countries mentioned"
    )
    india_eligible: YesNoUnclear = Field(
        description="Can someone living in India take this job without relocating abroad?"
    )
    india_evidence: str | None = Field(
        None, description="Short quote or fact supporting india_eligible"
    )
    relocation_abroad_required: bool = Field(
        description="True if the job needs moving outside India"
    )
    visa_sponsorship: Literal["offered", "not_needed", "not_offered", "unclear"]
    timezone_overlap: str | None = Field(
        None, description="Required working hours / timezone overlap, if stated"
    )

    salary_min: float | None = Field(
        None, description="Lower bound as a plain number in salary_currency"
    )
    salary_max: float | None = None
    salary_currency: str | None = Field(None, description="ISO code: USD, INR, EUR, GBP, CAD, ...")
    salary_period: Literal["year", "month", "hour"] | None = None
    equity: str | None = None

    min_years_experience: float | None = Field(
        None, description="Minimum years required; 0 if new grads are welcome"
    )
    fresher_ok: YesNoUnclear
    education: str | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)

    interview_process: str | None = Field(
        None, description="Interview steps if described, in one line"
    )
    dsa_signals: list[str] = Field(
        default_factory=list,
        description="Quotes hinting at LeetCode/DSA rounds or explicitly avoiding them",
    )
    take_home_or_practical: bool | None = Field(
        None, description="True if a take-home, project, pairing or work-trial round is mentioned"
    )
    start_date: str | None = Field(
        None, description="Required start / joining date if stated (e.g. 'immediate')"
    )
    red_flags: list[str] = Field(
        default_factory=list, description="Unpaid, commission-only, 996 hours, vague role, etc."
    )
    summary: str = Field(
        description="Two lines: what the company does and what this person would do"
    )
