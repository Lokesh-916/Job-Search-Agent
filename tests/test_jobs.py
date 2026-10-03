import json

from job_agent.jobs import render_job

ROW = {
    "hit_json": json.dumps({"company_name": "Acme", "remote": "only", "title": "AI Eng"}),
    "detail_json": json.dumps(
        {
            "job": {
                "title": "AI Engineer",
                "salaryRange": "₹12L - ₹20L",
                "descriptionHtml": "<p>Build agents.</p>",
                "interviewProcessHtml": "<ul><li>Take-home</li></ul>",
            },
            "company": {"one_liner": "Agents for X", "batch": "W26"},
        }
    ),
}


def test_render_job_has_key_facts():
    text = render_job(ROW)
    assert "Title: AI Engineer" in text
    assert "Acme — Agents for X" in text
    assert "(remote only)" in text
    assert "₹12L - ₹20L" in text
    assert text.endswith("Interview process:\n- Take-home")


def test_render_job_without_detail():
    row = {"hit_json": json.dumps({"title": "SWE", "description": "Code"}), "detail_json": None}
    assert "Title: SWE" in render_job(row) and "Code" in render_job(row)
