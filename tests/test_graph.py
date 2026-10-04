import asyncio
from pathlib import Path

import job_agent.graph as graph
import job_agent.research.agent as research_agent
import job_agent.stages as stages
from job_agent.preflight import Check
from job_agent.settings import Paths, Settings
from job_agent.sources.waas.fetch import FetchResult
from tests.fakes import FakeStructuredLLM
from tests.test_stages import ASSESSMENT, EXTRACTION, HITS


def fake_llm_reply(messages):
    system = messages[0].content
    if "screen startup job postings" in system:
        sales = "Account Executive" in messages[-1].content
        return {"category": "non_technical" if sales else "ai_engineering", "keep": not sales,
                "reason": "r"}  # fmt: skip
    if "You research one startup" in system:
        return {"product": "Invoice agents", "outreach_draft": "Hi", "rating": "4.6/5"}
    if "extract facts" in system:
        return {**EXTRACTION, "salary_min": 40000, "salary_max": 60000, "salary_currency": "USD"}
    return {**ASSESSMENT, "realistic_salary_lpa_min": 40, "realistic_salary_lpa_max": 50}


class FakeTelegram:
    sent: list = []

    def __init__(self, secrets):
        pass

    def send_message(self, text):
        FakeTelegram.sent.append(("msg", text))

    def send_document(self, path, caption=""):
        FakeTelegram.sent.append(("doc", Path(path).name))


def setup(tmp_path, monkeypatch, vram_ok=True):
    settings = Settings(paths=Paths(data_dir=tmp_path / "data", output_dir=tmp_path / "wb",
                                    profile=tmp_path / "none.yaml"))  # fmt: skip
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fx.json").write_text(
        '{"fetched_on": "2999-01-01", "inr_per_unit": {"USD": 96.0, "INR": 1.0}}'
    )
    monkeypatch.setattr(graph, "load_inr_rates", lambda p: {"USD": 96.0, "INR": 1.0})

    def fake_fetch(settings, store):
        store.upsert_hits("waas", HITS, "2026-10-04T00:00:00+00:00")
        for h in HITS:
            store.save_detail(str(h["id"]), {"job": {"title": h["title"]}}, "2026-10-04T00:00:00")
        return FetchResult(found=2, new=["1", "2"], changed=["1", "2"], fetched=2)

    monkeypatch.setattr(graph, "fetch_waas", fake_fetch)
    monkeypatch.setattr(graph, "check_vram", lambda s: Check("vram", vram_ok, "x"))
    monkeypatch.setattr(graph, "check_ollama", lambda s: Check("ollama", True, "x"))
    monkeypatch.setattr(graph, "check_session", lambda s: Check("session", True, "x"))
    monkeypatch.setattr(graph, "Telegram", FakeTelegram)
    monkeypatch.setattr(research_agent, "search_web", lambda q, n=5, searxng_url=None: [])
    monkeypatch.setattr(research_agent, "search_hn", lambda q, n=5: "No HN results.")
    monkeypatch.setattr(stages, "get_chat_model", lambda stage: FakeStructuredLLM(fake_llm_reply))
    FakeTelegram.sent = []
    return settings


def test_full_run_writes_workbook_and_notifies(tmp_path, monkeypatch):
    settings = setup(tmp_path, monkeypatch)
    state = asyncio.run(graph.run_pipeline(settings))

    assert state.get("abort") is None
    assert Path(state["workbook"]).exists()
    assert [j["Title"] for j in state["top"]] == ["AI Engineer"]
    log = dict(state["log"])
    assert log["Triage"].startswith("2/2 done") and "1 kept" in log["Triage"]
    assert log["Research"].startswith("1/1 companies")
    assert log["Assess"].startswith("1/1 done")
    kinds = [k for k, _ in FakeTelegram.sent]
    assert kinds == ["msg", "doc"] and "AI Engineer" in FakeTelegram.sent[0][1]

    # Second run: nothing new for the LLM.
    state = asyncio.run(graph.run_pipeline(settings, {"notify": False}))
    assert dict(state["log"])["Triage"].startswith("0/0 done")


def test_preflight_failure_skips_work_but_tells_user(tmp_path, monkeypatch):
    settings = setup(tmp_path, monkeypatch, vram_ok=False)
    state = asyncio.run(graph.run_pipeline(settings))
    assert state["abort"].startswith("vram")
    assert not state.get("workbook")
    assert FakeTelegram.sent[0][0] == "msg" and "skipped" in FakeTelegram.sent[0][1]


def test_run_metrics_are_saved(tmp_path, monkeypatch):
    import json

    from job_agent.store import Store

    settings = setup(tmp_path, monkeypatch)
    asyncio.run(graph.run_pipeline(settings, {"notify": False}))
    with Store(settings.paths.data_dir / "jobs.db") as store:
        [run] = store.runs()
        summary = json.loads(run["summary_json"])
    assert set(summary["stage_seconds"]) >= {"preflight", "fetch", "triage", "assess", "export"}
    assert summary["outcome"]["scored"] == 1 and summary["outcome"]["pending"] == 0
    assert summary["outcome"]["buckets"] == {"remote_foreign": 1, "rejected": 1}
    assert "research:summary_fallback" in summary["events"]  # fake model can't call tools
    assert summary["outcome"]["funnel"]["Passed triage"] == 1
