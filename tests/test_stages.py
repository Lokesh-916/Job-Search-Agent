import asyncio

from job_agent.settings import Settings
from job_agent.stages import run_extract, run_triage, stage_result
from job_agent.store import Store
from tests.fakes import FakeStructuredLLM

HITS = [
    {"id": 1, "company_name": "Acme", "title": "AI Engineer", "remote": "only"},
    {"id": 2, "company_name": "Acme", "title": "Account Executive", "remote": "only"},
]
EXTRACTION = {
    "category": "ai_engineering",
    "builds_ai": True,
    "work_mode": "remote",
    "india_eligible": "yes",
    "relocation_abroad_required": False,
    "visa_sponsorship": "not_needed",
    "fresher_ok": "yes",
    "summary": "Agents for X.",
}


def triage_reply(messages):
    sales = "Account Executive" in messages[-1].content
    return {
        "category": "non_technical" if sales else "ai_engineering",
        "keep": not sales,
        "reason": "sales" if sales else "builds agents",
    }


def seeded_store(tmp_path) -> Store:
    store = Store(tmp_path / "j.db")
    store.upsert_hits("waas", HITS, "2026-10-01T00:00:00+00:00")
    for h in HITS:
        store.save_detail(str(h["id"]), {"job": {"title": h["title"]}}, "2026-10-01T00:00:00+00:00")
    return store


def test_triage_then_extract_only_kept(tmp_path):
    settings = Settings()
    with seeded_store(tmp_path) as store:
        report = asyncio.run(run_triage(store, settings, {}, FakeStructuredLLM(triage_reply)))
        assert (report.todo, report.ok, report.kept) == (2, 2, 1)
        assert stage_result(store, "2", "triage")["category"] == "non_technical"

        extractor = FakeStructuredLLM(lambda m: EXTRACTION)
        report = asyncio.run(run_extract(store, settings, extractor))
        assert (report.todo, report.ok) == (1, 1)
        assert "AI Engineer" in extractor.calls[0][-1].content
        assert stage_result(store, "1", "extract")["india_eligible"] == "yes"


def test_cached_results_are_not_redone(tmp_path):
    settings = Settings()
    with seeded_store(tmp_path) as store:
        asyncio.run(run_triage(store, settings, {}, FakeStructuredLLM(triage_reply)))
        again = FakeStructuredLLM(triage_reply)
        report = asyncio.run(run_triage(store, settings, {}, again))
        assert report.todo == 0 and again.calls == []


def test_failures_are_recorded_and_retried(tmp_path):
    settings = Settings()
    with seeded_store(tmp_path) as store:
        report = asyncio.run(run_triage(store, settings, {}, FakeStructuredLLM(lambda m: "junk")))
        assert len(report.failed) == 2 and report.ok == 0
        report = asyncio.run(run_triage(store, settings, {}, FakeStructuredLLM(triage_reply)))
        assert report.ok == 2
