"""Assemble one flat record per job (and per company) from everything the pipeline stored."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from job_agent.schemas import Assessment, Extraction, Triage
from job_agent.scoring import Scored, score_job
from job_agent.settings import Settings
from job_agent.stages import stage_result
from job_agent.store import Store

WAAS_JOB_URL = "https://www.workatastartup.com/jobs/{id}"
CompanyResearch = Callable[[str], dict[str, Any] | None]  # company_id -> research fields


@dataclass
class Report:
    jobs: list[dict[str, Any]] = field(default_factory=list)
    companies: list[dict[str, Any]] = field(default_factory=list)
    pending: int = 0  # fetched but not triaged yet (e.g. a --limit test run)


def _join(items: list[str] | None) -> str:
    return ", ".join(items or [])


def _lpa_range(lo: float | None, hi: float | None) -> str:
    if lo is None and hi is None:
        return ""
    if lo is None or hi is None or lo == hi:
        return f"₹{lo or hi:g} L"
    return f"₹{lo:g}–{hi:g} L"


def _tier(score: float | None, threshold: float) -> str:
    if score is None:
        return ""
    return "🔥" if score >= threshold else "✅" if score >= 60 else "🤔"


def _founders(company: dict) -> str:
    return "; ".join(
        f"{f.get('full_name')}" + (f" ({f['linkedin']})" if f.get("linkedin") else "")
        for f in company.get("founders") or []
    )


def _parse[T](model: type[T], raw: dict | None) -> T | None:
    return model.model_validate(raw) if raw else None  # type: ignore[attr-defined]


def job_record(
    row: sqlite3.Row,
    triage: Triage | None,
    ex: Extraction | None,
    a: Assessment | None,
    scored: Scored,
    research: dict[str, Any] | None,
    run_date: str,
    threshold: float,
) -> dict[str, Any]:
    hit = json.loads(row["hit_json"] or "{}")
    detail = json.loads(row["detail_json"] or "{}")
    job, company = detail.get("job") or {}, detail.get("company") or {}
    posted = (hit.get("created_at") or "")[:10]
    age = (
        (datetime.fromisoformat(run_date) - datetime.fromisoformat(posted)).days if posted else None
    )
    research = research or {}
    return {
        # Tracking
        "Score": scored.score,
        "Tier": _tier(scored.score, threshold),
        "New": "🆕" if row["first_seen"][:10] == run_date else "",
        "Status": "",  # a dropdown for the reader's own copy; not read back
        # Role
        "Title": job.get("title") or row["title"],
        "Company": row["company_name"],
        "Category": (ex.category if ex else triage.category if triage else ""),
        "Builds AI?": ("Yes – " + (ex.ai_work or ""))
        if ex and ex.builds_ai
        else ("No" if ex else ""),
        "Apply URL": WAAS_JOB_URL.format(id=row["job_id"]),
        "Job URL": row["url"],
        "Posted": posted,
        "Age (days)": age,
        "Openings at company": len(company.get("open_jobs") or []),
        # Location
        "Work mode": ex.work_mode if ex else hit.get("remote"),
        "Locations": _join(ex.locations) if ex else job.get("location"),
        "India eligible": ex.india_eligible if ex else "",
        "Eligibility evidence": ex.india_evidence if ex else "",
        "Timezone / hours": ex.timezone_overlap if ex else "",
        "Visa": job.get("sponsorsVisa") or "",
        # Pay
        "Listed salary": job.get("salaryRange") or "",
        "Listed (₹ LPA)": _lpa_range(*scored.listed_lpa),
        "Equity": job.get("equityRange") or (ex.equity if ex else "") or "",
        "Realistic (₹ LPA)": _lpa_range(a.realistic_salary_lpa_min, a.realistic_salary_lpa_max)
        if a
        else "",
        "Pay confidence": a.salary_confidence if a else "",
        "Pay basis": a.salary_basis if a else "",
        # Requirements
        "Experience": job.get("minExperience") or "",
        "Fresher OK?": ex.fresher_ok if ex else "",
        "Must-have skills": _join(ex.must_have_skills) if ex else "",
        "Nice-to-have": _join(ex.nice_to_have_skills) if ex else "",
        "Tech stack": _join(ex.tech_stack) if ex else "",
        "Gaps": _join(a.gaps) if a else "",
        # Interview
        "Interview process": ex.interview_process if ex else "",
        "DSA risk": a.dsa_risk if a else "",
        "DSA evidence": a.dsa_evidence if a else "",
        "Take-home / practical?": {True: "Yes", False: "No"}.get(ex.take_home_or_practical, "")
        if ex
        else "",
        # Fit
        "Verdict": a.verdict if a else "",
        "Fit score": a.fit_score if a else None,
        "Why I fit": a.why_fit if a else "",
        "Pitch": a.pitch if a else "",
        "Learning upside": a.learning_upside if a else "",
        "Joining fit": a.joining_fit if a else "",
        "Red flags": _join(ex.red_flags) if ex else "",
        # Company
        "What they do": ex.summary if ex else company.get("one_liner") or "",
        "YC batch": company.get("batch") or "",
        "Stage": hit.get("company_waas_stage") or "",
        "Team size": company.get("team_size") or hit.get("company_team_size"),
        "HQ": company.get("pretty_location") or "",
        "Employee sentiment": research.get("employee_sentiment") or "",
        "Founders": _founders(company),
        # Meta
        "Reject reason": scored.reject_reason or "",
        "First seen": row["first_seen"][:10],
        "Job ID": row["job_id"],
        "_bucket": scored.bucket,
        "_company_id": row["company_id"],
        "_pay_lpa": _midpoint(
            (a.realistic_salary_lpa_min, a.realistic_salary_lpa_max) if a else (None, None),
            scored.listed_lpa,
        ),
    }


def _midpoint(*ranges: tuple[float | None, float | None]) -> float | None:
    """Middle of the first range that has a number (realistic pay before listed pay)."""
    for lo, hi in ranges:
        nums = [x for x in (lo, hi) if x is not None]
        if nums:
            return sum(nums) / len(nums)
    return None


def company_record(company: dict, research: dict[str, Any] | None, open_fit: int) -> dict:
    research = research or {}
    news = company.get("company_news") or []
    return {
        "Company": company.get("name"),
        "Website": company.get("website") or company.get("website_url") or "",
        "What they do": research.get("product")
        or company.get("one_liner")
        or company.get("description")
        or "",
        "YC batch": company.get("batch") or "",
        "Team size": company.get("team_size"),
        "HQ": company.get("pretty_location") or "",
        "Founders": _founders(company),
        "Open roles": len(company.get("open_jobs") or []),
        "Roles in this sheet": open_fit,
        "Funding / stage": research.get("funding") or "",
        "Employee sentiment": research.get("employee_sentiment") or "",
        "Pros": research.get("pros") or "",
        "Cons": research.get("cons") or "",
        "Interview experiences": research.get("interview_experiences") or "",
        "Salary data points": research.get("salary_data") or "",
        "Recent news": "; ".join(n.get("title", "") for n in news[:3] if isinstance(n, dict))
        or research.get("news")
        or "",
        "Outreach draft": research.get("outreach_draft") or "",
        "Sources": research.get("sources") or "",
    }


def research_columns(store: Store) -> CompanyResearch:
    """Stored research (lists and all) -> the flat text fields the workbook shows."""

    def lookup(company_id: str) -> dict[str, Any] | None:
        r = store.get_research(company_id)
        if not r:
            return None
        sentiment = " · ".join(x for x in (r.get("rating"), r.get("employee_sentiment")) if x)
        return {
            "product": r.get("product"),
            "funding": "; ".join(x for x in (r.get("funding"), r.get("traction")) if x),
            "employee_sentiment": sentiment,
            "pros": "; ".join(r.get("pros") or []),
            "cons": "; ".join(r.get("cons") or []),
            "interview_experiences": " ".join(
                x for x in (r.get("interview_experiences"), f"(DSA: {r.get('dsa_heavy')})") if x
            ),
            "salary_data": "; ".join(r.get("salary_data") or []),
            "news": "; ".join(r.get("news") or []),
            "outreach_draft": r.get("outreach_draft"),
            "sources": "\n".join(r.get("sources") or []),
        }

    return lookup


def build_report(
    store: Store,
    settings: Settings,
    rates: dict[str, float],
    research: CompanyResearch = lambda company_id: None,
    run_date: str | None = None,
) -> Report:
    run_date = run_date or datetime.now(UTC).date().isoformat()
    report = Report()
    companies: dict[str, tuple[dict, int]] = {}
    for row in store.open_jobs():
        job_id = row["job_id"]
        triage = _parse(Triage, stage_result(store, job_id, "triage"))
        if triage is None:
            report.pending += 1
            continue
        ex = _parse(Extraction, stage_result(store, job_id, "extract"))
        a = _parse(Assessment, stage_result(store, job_id, "assess"))
        detail = json.loads(row["detail_json"] or "{}")
        company = detail.get("company") or {}
        scored = score_job(
            job_id, triage, ex, a, company.get("country"), rates,
            settings.preferences, settings.scoring,
        )  # fmt: skip
        rec = job_record(
            row, triage, ex, a, scored,
            research(row["company_id"]), run_date, settings.scoring.top_pick_threshold,
        )  # fmt: skip
        report.jobs.append(rec)
        if scored.bucket != "rejected":
            prev = companies.get(row["company_id"], (company, 0))
            companies[row["company_id"]] = (company, prev[1] + 1)
    report.jobs.sort(key=lambda r: (r["Score"] is None, -(r["Score"] or 0)))
    report.companies = sorted(
        (company_record(c, research(cid), n) for cid, (c, n) in companies.items()),
        key=lambda r: -r["Roles in this sheet"],
    )
    return report


def drop_reason(rec: dict[str, Any]) -> str:
    """Short, chart-friendly label for why a rejected job was dropped."""
    reason = rec.get("Reject reason") or ""
    if reason.startswith("Triage"):
        return "Non-technical" if rec.get("Category") == "non_technical" else "Not entry-level"
    if "India" in reason:
        return "Not open to India"
    if "pay" in reason.lower():
        return "Pay below floor"
    if "years" in reason:
        return "Not entry-level"
    if "sponsorship" in reason.lower():
        return "No visa sponsorship"
    return "Other"


def job_flow(report: Report, threshold: float) -> list[tuple[str, str, int]]:
    """(source, target, count) links from fetch to top picks, for the Sankey chart."""
    links: Counter = Counter()
    if report.pending:
        links[("Fetched", "Not processed yet")] += report.pending
    for rec in report.jobs:
        links[("Fetched", "Triaged")] += 1
        bucket, score = rec["_bucket"], rec["Score"]
        if bucket == "rejected" and (rec.get("Reject reason") or "").startswith("Triage"):
            links[("Triaged", drop_reason(rec))] += 1
            continue
        links[("Triaged", "Passed triage")] += 1
        if bucket == "rejected":
            links[("Passed triage", drop_reason(rec))] += 1
        elif score is None:
            links[("Passed triage", "Needs review")] += 1
        else:
            links[("Passed triage", "Scored")] += 1
            links[("Scored", "Top picks" if score >= threshold else "Worth a look")] += 1
    return [(a, b, n) for (a, b), n in links.items()]
