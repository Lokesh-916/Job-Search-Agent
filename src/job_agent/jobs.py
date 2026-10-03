"""A stored job row -> the text an LLM reads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from job_agent.text import html_to_text

REMOTE_LABEL = {"yes": "remote OK", "only": "remote only", "no": "onsite"}


def _parts(row: Mapping[str, Any]) -> tuple[dict, dict, dict]:
    hit = json.loads(row["hit_json"] or "{}")
    detail = json.loads(row["detail_json"] or "{}")
    return hit, detail.get("job") or {}, detail.get("company") or {}


def render_job(row: Mapping[str, Any], max_desc_chars: int | None = None) -> str:
    hit, job, company = _parts(row)
    about = company.get("one_liner") or hit.get("company_description") or ""
    pay = f"{job.get('salaryRange') or 'not listed'} | Equity: {job.get('equityRange') or '-'}"
    lines = [
        f"Title: {job.get('title') or hit.get('title')}",
        f"Company: {hit.get('company_name')} — {about}",
        f"Company HQ: {company.get('pretty_location') or company.get('location') or '?'} "
        f"| team size {company.get('team_size') or hit.get('company_team_size') or '?'} "
        f"| stage {hit.get('company_waas_stage') or '?'} | YC {company.get('batch') or '?'}",
        f"Location: {job.get('location') or ', '.join(hit.get('locations_for_search') or [])} "
        f"({REMOTE_LABEL.get(hit.get('remote'), hit.get('remote'))})",
        f"Visa: {job.get('sponsorsVisa') or hit.get('us_visa_required')}",
        f"Experience: {job.get('minExperience') or hit.get('min_experience')}",
        f"Salary: {pay}",
        f"Skills tagged: {', '.join(job.get('skills') or hit.get('skills') or []) or '-'}",
        "",
        "Description:",
        html_to_text(job.get("descriptionHtml") or hit.get("description"), max_desc_chars),
    ]
    interview = html_to_text(job.get("interviewProcessHtml"))
    if interview:
        lines += ["", "Interview process:", interview]
    return "\n".join(lines)
