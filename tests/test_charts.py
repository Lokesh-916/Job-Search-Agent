from job_agent.charts import render_all
from job_agent.metrics import LLMCall
from job_agent.store import Store

SUMMARY = {
    "stage_seconds": {"fetch": 5, "triage": 102, "assess": 98},
    "duration_min": 3.4,
    "outcome": {"funnel": {"Fetched": 442, "Triaged": 25, "Passed triage": 4}},
}


def test_render_all_light_and_dark(tmp_path):
    with Store(tmp_path / "j.db") as s:
        assert render_all(s, tmp_path / "charts") == []
        calls = [LLMCall("triage", 0, 3.1), LLMCall("triage", 0, 4.2), LLMCall("assess", 0, 41)]
        s.save_run("r1", "2026-10-04T00:00:00+00:00", "ollama:qwen3:14b", {}, SUMMARY, calls)
        made = render_all(s, tmp_path / "charts")
        assert {p.name for p in made} == {
            f"{c}-{t}.png"
            for c in ("funnel", "stage-time", "llm-latency")
            for t in ("light", "dark")
        }
        s.save_run("r2", "2026-10-05T00:00:00+00:00", "ollama:gpt-oss:20b", {}, SUMMARY, calls)
        assert any(p.name == "history-dark.png" for p in render_all(s, tmp_path / "charts"))
