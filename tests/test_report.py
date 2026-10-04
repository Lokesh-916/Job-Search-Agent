from job_agent.report import build_report
from job_agent.settings import Settings
from job_agent.store import Store

HIT = {"id": 1, "company_id": 9, "company_name": "Acme", "title": "AI Eng",
       "created_at": "2026-10-01T10:00:00Z", "remote": "only"}  # fmt: skip
DETAIL = {
    "job": {"title": "AI Engineer", "salaryRange": "$40K - $60K"},
    "company": {"name": "Acme", "country": "US", "founders": [{"full_name": "Ada"}]},
}
TRIAGE = {"category": "ai_engineering", "keep": True, "reason": "agents"}
EXTRACT = {
    "category": "ai_engineering", "builds_ai": True, "ai_work": "LLM agents",
    "work_mode": "remote", "india_eligible": "yes", "relocation_abroad_required": False,
    "visa_sponsorship": "not_needed", "fresher_ok": "yes", "summary": "Agents for X",
    "salary_min": 40000, "salary_max": 60000, "salary_currency": "USD", "salary_period": "year",
}  # fmt: skip
ASSESS = {
    "fit_score": 90, "why_fit": "w", "dsa_risk": "low", "sponsorship_credible": "not_applicable",
    "joining_fit": "ok", "verdict": "apply_now", "pitch": "p", "company_quality": 8,
    "realistic_salary_lpa_min": 38.4, "realistic_salary_lpa_max": 45,
}  # fmt: skip


def test_build_report_full_record(tmp_path):
    with Store(tmp_path / "j.db") as s:
        s.upsert_hits("waas", [HIT], "2026-10-03T00:00:00+00:00")
        s.save_detail("1", DETAIL, "2026-10-03T00:00:00+00:00")
        h = s.get("1")["content_hash"]
        for stage, res in (("triage", TRIAGE), ("extract", EXTRACT), ("assess", ASSESS)):
            s.save_result("1", stage, "m", h, res)

        report = build_report(s, Settings(), {"USD": 96.0, "INR": 1.0}, run_date="2026-10-03")

    [job] = report.jobs
    assert job["_bucket"] == "remote_foreign" and job["Tier"] == "🔥"
    assert job["Listed (₹ LPA)"] == "₹38.4–57.6 L"
    assert job["Realistic (₹ LPA)"] == "₹38.4–45 L"
    assert job["Builds AI?"] == "Yes – LLM agents"
    assert job["New"] == "🆕" and job["Age (days)"] == 2
    assert job["Apply URL"].endswith("/jobs/1")
    assert report.companies[0]["Founders"] == "Ada"


def test_untriaged_job_is_pending_not_listed(tmp_path):
    with Store(tmp_path / "j.db") as s:
        s.upsert_hits("waas", [HIT], "2026-10-03T00:00:00+00:00")
        s.save_detail("1", DETAIL, "2026-10-03T00:00:00+00:00")
        report = build_report(s, Settings(), {"USD": 96.0}, run_date="2026-10-04")
    assert report.jobs == [] and report.pending == 1 and report.companies == []
