"""Research one company: deterministic evidence gathering, then a capped tool-using agent.

The gather phase guarantees useful evidence even when a small local model is bad at tool
calling; the agent phase digs further; and if the agent fails, a single structured call
summarises the gathered evidence instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from job_agent.prompts import RESEARCH_SYNTH_SYSTEM, RESEARCH_SYSTEM
from job_agent.research.tools import format_results, make_tools, search_hn, search_web
from job_agent.schemas import CompanyResearch
from job_agent.settings import ResearchConfig
from job_agent.structured import ainvoke_structured
from job_agent.text import html_to_text

AgentRunner = Callable[[BaseChatModel, str, ResearchConfig], Awaitable[CompanyResearch | None]]


def company_profile(company: dict) -> str:
    founders = ", ".join(
        f"{f.get('full_name')}" + (f" ({f['linkedin']})" if f.get("linkedin") else "")
        for f in company.get("founders") or []
    )
    news = "; ".join(n.get("title", "") for n in (company.get("company_news") or [])[:5])
    return "\n".join([
        f"Company: {company.get('name')} — {company.get('one_liner') or ''}",
        f"Website: {company.get('website') or company.get('website_url') or '?'}",
        f"YC batch: {company.get('batch') or '?'} | team size: {company.get('team_size') or '?'}"
        f" | HQ: {company.get('pretty_location') or company.get('location') or '?'}",
        f"Founders: {founders or '?'}",
        f"About: {html_to_text(company.get('description'), 800)}",
        f"Tech: {html_to_text(company.get('tech_description'), 400)}",
        f"News on YC profile: {news or '-'}",
    ])  # fmt: skip


def gather_queries(company: dict) -> dict[str, str]:
    name = company.get("name") or ""
    site = urlparse(company.get("website") or company.get("website_url") or "").netloc
    site = site.removeprefix("www.")
    tag = f'"{name}" {site}'.strip()
    return {
        "Reviews": f'"{name}" reviews glassdoor OR ambitionbox',
        "Interviews": f'"{name}" interview experience engineer',
        "Salaries": f'"{name}" software engineer salary',
        "Funding": f"{tag} funding raised",
    }


async def gather(company: dict, searxng_url: str | None) -> str:
    """Company profile + fixed searches + HN, all in parallel, as one evidence block."""
    queries = gather_queries(company)
    results = await asyncio.gather(
        *(asyncio.to_thread(search_web, q, 5, searxng_url) for q in queries.values()),
        asyncio.to_thread(search_hn, company.get("name") or "", 5),
    )
    sections = [f"--- COMPANY PROFILE ---\n{company_profile(company)}"]
    for (label, query), found in zip(queries.items(), results[:-1], strict=True):
        sections.append(f"--- SEARCH: {label} ({query}) ---\n{format_results(found)}")
    sections.append(f"--- HACKER NEWS ---\n{results[-1]}")
    return "\n\n".join(sections)


async def run_tool_agent(
    llm: BaseChatModel, evidence: str, cfg: ResearchConfig
) -> CompanyResearch | None:
    agent = create_agent(
        llm,
        tools=make_tools(cfg.searxng_url),
        system_prompt=RESEARCH_SYSTEM,
        response_format=CompanyResearch,
        middleware=[
            ToolCallLimitMiddleware(run_limit=cfg.max_tool_calls, exit_behavior="continue"),
            ModelCallLimitMiddleware(run_limit=cfg.max_tool_calls + 3, exit_behavior="end"),
        ],
    )
    result = await agent.ainvoke({"messages": [HumanMessage(evidence)]})
    return result.get("structured_response")


async def research_company(
    company: dict,
    llm: BaseChatModel,
    cfg: ResearchConfig,
    run_agent: AgentRunner = run_tool_agent,
) -> CompanyResearch:
    evidence = await gather(company, cfg.searxng_url)
    if cfg.agentic:
        try:
            found = await run_agent(llm, evidence, cfg)
            if found is not None:
                return found
        except Exception:  # small models fumble tool calls; the evidence is still good
            pass
    messages = [SystemMessage(RESEARCH_SYNTH_SYSTEM), HumanMessage(evidence)]
    return await ainvoke_structured(llm, CompanyResearch, messages)
