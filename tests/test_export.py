from openpyxl import load_workbook

from job_agent.export import read_user_status, workbook_path, write_workbook
from job_agent.report import Report


def job(job_id: str, bucket: str, score: float | None) -> dict:
    return {"Job ID": job_id, "_bucket": bucket, "Score": score, "Title": f"Job {job_id}",
            "Company": "Acme", "New": "", "Apply URL": f"https://x/jobs/{job_id}",
            "Work mode": "remote", "Realistic (₹ LPA)": "", "Listed (₹ LPA)": "",
            "Reject reason": "sales" if bucket == "rejected" else ""}  # fmt: skip


REPORT = Report(
    jobs=[job("1", "remote_foreign", 90), job("2", "india_onsite", 50), job("3", "rejected", None)],
    companies=[{"Company": "Acme", "Website": "https://acme.dev"}],
)


def test_tabs_and_routing(tmp_path):
    path = write_workbook(REPORT, workbook_path(tmp_path, "2026-10-03"), threshold=75)
    wb = load_workbook(path)
    assert path.name == "jobs_2026-10-03.xlsx"
    ids = lambda sheet: [r[-1] for r in wb[sheet].iter_rows(min_row=3, values_only=True)]  # noqa: E731
    assert wb["🔥 Top Picks"].cell(3, 7).value == "Job 1"
    assert ids("🗑️ Rejected") == ["3"]
    assert wb["🏢 India · Onsite"].cell(3, 7).value == "Job 2"


def test_user_edits_are_read_back_from_latest_workbook(tmp_path):
    old = write_workbook(REPORT, workbook_path(tmp_path, "2026-10-02"), threshold=75)
    wb = load_workbook(old)
    ws = wb["🌍 Remote · Foreign"]
    header = [c.value for c in ws[2]]
    ws.cell(3, header.index("Status") + 1, "Applied")
    ws.cell(3, header.index("My Notes") + 1, "emailed founder")
    wb.save(old)

    assert read_user_status(tmp_path) == {
        "1": {"status": "Applied", "notes": "emailed founder", "applied_on": None}
    }


def test_no_previous_workbook(tmp_path):
    assert read_user_status(tmp_path) == {}
