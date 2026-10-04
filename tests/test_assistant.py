import asyncio

import pytest

from job_agent.assistant import UnknownJobError, job_context, job_helper, make_db_tools
from job_agent.store import Store
from tests.fakes import FakeStructuredLLM

HIT = {"id": 1, "company_id": 9, "company_name": "Acme", "title": "AI Engineer"}
DETAIL = {"job": {"title": "AI Engineer", "descriptionHtml": "<p>Build agents</p>"}}
PITCH = {"subject_line": "Agents for invoices", "founder_message": "Hi Ada", "cover_note": "..."}


def seeded(tmp_path) -> Store:
    s = Store(tmp_path / "j.db")
    s.upsert_hits("waas", [HIT], "2026-10-04T00:00:00+00:00")
    s.save_detail("1", DETAIL, "2026-10-04T00:00:00+00:00")
    s.save_result("1", "assess", "m", s.get("1")["content_hash"], {"fit_score": 88})
    s.save_research("9", "Acme", "m", {"product": "Invoice agents", "rating": "4.6/5"})
    return s


def test_job_context_includes_judgment_and_research(tmp_path):
    with seeded(tmp_path) as s:
        ctx = job_context(s, "1")
        assert "Build agents" in ctx and '"fit_score": 88' in ctx and "4.6/5" in ctx
        with pytest.raises(UnknownJobError):
            job_context(s, "404")


def test_pitch_uses_profile_and_job(tmp_path):
    llm = FakeStructuredLLM(lambda m: PITCH)
    with seeded(tmp_path) as s:
        out = asyncio.run(job_helper("pitch", s, {"projects": [{"name": "ProtoFlow"}]}, "1", llm))
    assert out.subject_line == "Agents for invoices"
    prompt = llm.calls[0][-1].content
    assert "ProtoFlow" in prompt and "Build agents" in prompt
    assert "Never invent" in llm.calls[0][0].content


def test_db_tools(tmp_path):
    records = [
        {"Job ID": "1", "Score": 82.0, "Title": "AI Engineer", "Company": "Acme",
         "Tech stack": "Python, LangGraph", "_bucket": "remote_india", "Builds AI?": "Yes – agents",
         "Realistic (₹ LPA)": "₹14–18 L", "Listed (₹ LPA)": "", "DSA risk": "low",
         "Verdict": "apply_now", "_company_id": "9"},
        {"Job ID": "2", "Score": 55.0, "Title": "Backend Engineer", "Company": "Beta",
         "Tech stack": "Go", "_bucket": "india_onsite", "Builds AI?": "No",
         "Realistic (₹ LPA)": "", "Listed (₹ LPA)": "₹10 L", "DSA risk": "high",
         "Verdict": "stretch", "_company_id": "8"},
    ]  # fmt: skip
    with seeded(tmp_path) as s:
        search, details, research = make_db_tools(records, s)
        assert search.invoke({"text": "langgraph"}).startswith("1 | 82 | AI Engineer @ Acme")
        assert search.invoke({"bucket": "india_onsite"}).startswith("2 |")
        assert search.invoke({"builds_ai_only": True, "min_score": 90}) == "No matching jobs."
        assert "Tech stack: Go" in details.invoke({"job_id": "2"})
        assert "Invoice agents" in research.invoke({"company": "acme"})
