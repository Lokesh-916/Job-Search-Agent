"""On-demand LLM helpers over the job database: pitch, prep, tailor and free-form ask."""

from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from job_agent import metrics
from job_agent.jobs import render_job
from job_agent.llm import get_chat_model
from job_agent.profile import full_brief
from job_agent.prompts import (
    ASK_SYSTEM,
    PITCH_SYSTEM,
    PREP_SYSTEM,
    TAILOR_SYSTEM,
    job_help_messages,
)
from job_agent.schemas import InterviewPrep, Pitch, ResumeTailoring
from job_agent.stages import research_brief, stage_result
from job_agent.store import Store
from job_agent.structured import ainvoke_structured

HELPERS: dict[str, tuple[str, type[BaseModel]]] = {
    "pitch": (PITCH_SYSTEM, Pitch),
    "prep": (PREP_SYSTEM, InterviewPrep),
    "tailor": (TAILOR_SYSTEM, ResumeTailoring),
}


class UnknownJobError(LookupError):
    pass


def job_context(store: Store, job_id: str) -> str:
    """Posting + what the pipeline already concluded about it + company research."""
    row = store.get(job_id)
    if row is None or not row["detail_json"]:
        raise UnknownJobError(f"No fetched job {job_id}")
    parts = [render_job(row)]
    for stage in ("extract", "assess"):
        if result := stage_result(store, job_id, stage):
            parts.append(f"--- {stage.upper()} NOTES ---\n{json.dumps(result, ensure_ascii=False)}")
    if research := research_brief(store.get_research(row["company_id"])):
        parts.append(f"--- COMPANY RESEARCH ---\n{research}")
    return "\n\n".join(parts)


async def job_helper(
    kind: str,
    store: Store,
    profile: dict,
    job_id: str,
    llm: BaseChatModel | None = None,
    extra: str = "",
) -> BaseModel:
    system, schema = HELPERS[kind]
    messages = job_help_messages(system, full_brief(profile), job_context(store, job_id), extra)
    return await ainvoke_structured(llm or get_chat_model(kind), schema, messages, stage=kind)


def job_rows(records: list[dict[str, Any]]) -> str:
    lines = [
        f"{j['Job ID']} | {j['Score']:.0f} | {j['Title']} @ {j['Company']} | {j['_bucket']} | "
        f"{j['Realistic (₹ LPA)'] or j['Listed (₹ LPA)'] or 'pay n/a'} | DSA {j['DSA risk']} | "
        f"{j['Verdict']}"
        for j in records
    ]
    return "\n".join(lines) or "No matching jobs."


def make_db_tools(records: list[dict[str, Any]], store: Store) -> list:
    """Tools over the already-built report records (scored jobs) and stored research."""
    scored = [j for j in records if j["Score"] is not None]

    @tool
    def search_jobs(
        text: str = "",
        bucket: str = "",
        min_score: float = 0,
        builds_ai_only: bool = False,
        limit: int = 10,
    ) -> str:
        """Find scored jobs. text matches title/company/stack; bucket is one of remote_foreign,
        remote_india, india_onsite, abroad_sponsored. Returns: id | score | title @ company |
        bucket | pay | DSA risk | verdict, best first."""
        needle = text.lower()
        hits = [
            j for j in scored
            if (not needle or needle in f"{j['Title']} {j['Company']} {j['Tech stack']}".lower())
            and (not bucket or j["_bucket"] == bucket)
            and j["Score"] >= min_score
            and (not builds_ai_only or str(j["Builds AI?"]).startswith("Yes"))
        ]  # fmt: skip
        return job_rows(hits[: max(1, min(limit, 25))])

    @tool
    def job_details(job_id: str) -> str:
        """All known fields for one job ID: facts, judgment, pay, interview, company."""
        job = next((j for j in records if j["Job ID"] == job_id), None)
        if job is None:
            return f"No processed job {job_id}."
        return "\n".join(f"{k}: {v}" for k, v in job.items() if v not in (None, "") and k[0] != "_")

    @tool
    def company_research(company: str) -> str:
        """Stored research (reviews, interviews, salaries, funding) for a company name."""
        for j in records:
            if j["Company"].lower() == company.lower():
                found = research_brief(store.get_research(j["_company_id"]))
                return found or f"No research stored for {j['Company']}."
        return f"Unknown company {company}."

    return [search_jobs, job_details, company_research]


async def ask(
    question: str, records: list[dict[str, Any]], store: Store, llm: BaseChatModel | None = None
) -> str:
    agent = create_agent(
        llm or get_chat_model("ask"),
        tools=make_db_tools(records, store),
        system_prompt=ASK_SYSTEM,
        middleware=[ModelCallLimitMiddleware(run_limit=8, exit_behavior="end")],
    )
    result = await agent.ainvoke(
        {"messages": [HumanMessage(question)]}, config=metrics.llm_config("ask")
    )
    return str(result["messages"][-1].content).strip()
