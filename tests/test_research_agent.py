import asyncio

import job_agent.research.agent as agent
from job_agent.schemas import CompanyResearch
from job_agent.settings import ResearchConfig
from tests.fakes import FakeStructuredLLM

COMPANY = {
    "name": "Acme",
    "website": "https://www.acme.dev",
    "one_liner": "Agents for invoices",
    "founders": [{"full_name": "Ada", "linkedin": "https://linkedin.com/in/ada"}],
}
SYNTH = {"product": "Invoice agents", "outreach_draft": "Hi Ada, ...", "dsa_heavy": "low"}


def offline(monkeypatch):
    queries = []

    def fake_search(q, n=5, searxng_url=None):
        queries.append(q)
        return [{"title": f"hit for {q}", "url": "https://x", "snippet": "4.4★"}]

    monkeypatch.setattr(agent, "search_web", fake_search)
    monkeypatch.setattr(agent, "search_hn", lambda q, n=5: "- Launch HN: Acme")
    return queries


def test_gather_builds_evidence(monkeypatch):
    queries = offline(monkeypatch)
    evidence = asyncio.run(agent.gather(COMPANY, None))
    assert "Agents for invoices" in evidence and "Ada (https://linkedin.com/in/ada)" in evidence
    assert '"Acme" acme.dev funding raised' in queries
    assert "Launch HN: Acme" in evidence and evidence.count("--- SEARCH:") == 4


def test_agent_result_is_used(monkeypatch):
    offline(monkeypatch)

    async def good_agent(llm, evidence, cfg):
        return CompanyResearch(product="From agent", outreach_draft="x")

    out = asyncio.run(agent.research_company(COMPANY, None, ResearchConfig(), good_agent))
    assert out.product == "From agent"


def test_agent_failure_falls_back_to_summary(monkeypatch):
    offline(monkeypatch)

    async def broken_agent(llm, evidence, cfg):
        raise ValueError("model emitted a malformed tool call")

    llm = FakeStructuredLLM(lambda m: SYNTH)
    out = asyncio.run(agent.research_company(COMPANY, llm, ResearchConfig(), broken_agent))
    assert out.product == "Invoice agents"
    assert "Searching is over" in llm.calls[0][0].content


def test_non_agentic_mode_skips_agent(monkeypatch):
    offline(monkeypatch)
    called = []

    async def spy(llm, evidence, cfg):
        called.append(1)

    llm = FakeStructuredLLM(lambda m: SYNTH)
    asyncio.run(agent.research_company(COMPANY, llm, ResearchConfig(agentic=False), spy))
    assert called == []
