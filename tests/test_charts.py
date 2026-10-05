from job_agent.charts import render_all
from job_agent.metrics import LLMCall
from job_agent.store import Store

SUMMARY = {
    "run_date": "2026-10-04",
    "duration_min": 8.7,
    "stage_spans": [["fetch", 0, 5], ["triage", 5, 107], ["assess", 107, 205]],
    "outcome": {
        "scored": 1,
        "top_picks": 0,
        "funnel": {"Fetched": 30},
        "flow": [["Fetched", "Not processed yet", 25], ["Fetched", "Triaged", 5],
                 ["Triaged", "Non-technical", 3], ["Triaged", "Passed triage", 2],
                 ["Passed triage", "Scored", 1], ["Passed triage", "Not open to India", 1],
                 ["Scored", "Worth a look", 1]],
    },
}  # fmt: skip
HITS = [
    {"id": i, "company_name": "Acme", "title": "Eng", "role": "eng", "eng_type": ["fs"],
     "remote": "yes" if i % 2 else "no", "locations_for_search": ["IN"],
     "created_at": f"2026-09-{10 + i % 15:02d}T10:00:00Z"}
    for i in range(30)
]  # fmt: skip


def test_render_all_light_and_dark(tmp_path):
    with Store(tmp_path / "j.db") as s:
        assert render_all(s, tmp_path / "charts") == []
        s.upsert_hits("waas", HITS, "2026-10-04T00:00:00+00:00")
        for h in HITS:
            s.save_detail(str(h["id"]), {"job": {"title": "Eng"}}, "2026-10-04T00:00:00+00:00")
        assert {p.name for p in render_all(s, tmp_path / "charts")} == {
            f"{c}-{t}.png" for c in ("calendar", "market") for t in ("light", "dark")
        }
        calls = [LLMCall("triage", 5 + i * 3, 3.1 + i) for i in range(6)]
        calls += [LLMCall("assess", 110, 41), LLMCall("assess", 112, 57)]
        s.save_run("r1", "2026-10-03T23:05:00+00:00", "ollama:qwen3:14b", {}, SUMMARY, calls)
        names = {p.name for p in render_all(s, tmp_path / "charts")}
        for chart in ("hero", "timeline", "flow", "latency"):
            assert f"{chart}-dark.png" in names and f"{chart}-light.png" in names
        assert "history-dark.png" not in names  # needs two runs
        s.save_run("r2", "2026-10-05T23:05:00+00:00", "ollama:qwen3:14b", {}, SUMMARY, calls)
        assert any(p.name == "history-light.png" for p in render_all(s, tmp_path / "charts"))


def test_picks_chart_needs_scored_jobs_with_pay(tmp_path):
    from job_agent.charts.picks import picks_chart
    from job_agent.charts.style import THEMES

    buckets = ["remote_india", "remote_foreign", "india_onsite", "abroad_sponsored", "needs_review"]
    jobs = [{"_pay_lpa": 6 + i * 2.5, "Score": 40 + i * 5, "_bucket": buckets[i % 5],
             "Company": f"Co {i}"} for i in range(12)]  # fmt: skip
    jobs.append({"_pay_lpa": 30, "Score": 99, "_bucket": "rejected", "Company": "Gone"})
    for theme in THEMES:
        assert picks_chart(theme, jobs, tmp_path / f"picks-{theme.name}.png").exists()
    assert picks_chart(THEMES[0], jobs[:2], tmp_path / "none.png") is None
