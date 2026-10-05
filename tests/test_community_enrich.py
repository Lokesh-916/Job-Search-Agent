import asyncio

from job_agent.community.classify import Verdict
from job_agent.community.enrich import enrich
from job_agent.community.models import Posting
from job_agent.community.service import current, needs_checking
from job_agent.community.store import CommunityStore
from job_agent.settings import Settings
from tests.fakes import FakeStructuredLLM

NOTES = {
    "senior": {"fresher_ok": "no", "min_years": 4},
    "fresh": {"fresher_ok": "yes", "batches": "2026, 2027", "eligibility": "B.Tech CSE/AI",
              "pay": "₹14 LPA", "skills": ["Python", "SQL"], "summary": "Builds data pipelines."},
    "intern": {"fresher_ok": "yes", "pay": "₹40,000/month", "apply_by": "2026-10-20"},
}  # fmt: skip


def seed(store: CommunityStore) -> str:
    run = "2026-10-05T08:00:00"
    rows = [
        ("senior", Verdict(True, "", "job", "Not specified", "Backend"), "Backend Engineer"),
        ("fresh", Verdict(True, "", "job", "Check experience", "Data"), "Data Engineer"),
        ("intern", Verdict(True, "", "internship", "Internship", "ML / AI"), "ML Intern"),
        ("silent", Verdict(True, "", "job", "Check experience", "Data"), "Analyst"),
    ]
    for ext, verdict, title in rows:
        p = Posting("workday", "Acme", ext, title, f"https://x/{ext}", location="Pune, India",
                    extra={"pay": "Paid (amount not listed)"} if ext == "intern" else {})  # fmt: skip
        store.upsert_posting(p, verdict, "mnc", run)
        if ext != "silent":  # one posting has no job text: nothing to read
            store.save_description(p.key, f"posting text for {ext}")
    store.set_meta("last_refresh", run)
    return run


def respond(messages):
    text = messages[-1].content
    return next(v for k, v in NOTES.items() if f"text for {k}" in text)


def test_enrich_notes_postings_and_reshapes_the_feed(tmp_path):
    llm = FakeStructuredLLM(respond)
    with CommunityStore(tmp_path / "c.db") as store:
        seed(store)
        jobs, interns, _ = current(store)
        rows = jobs + interns + needs_checking(store)
        stats = asyncio.run(enrich(Settings(), store, rows, llm=llm))
        assert stats == {"noted": 3, "no text": 1}

        jobs, interns, _ = current(store)
        assert [j["title"] for j in jobs] == ["Data Engineer"]  # senior dropped, check promoted
        fresh = jobs[0]
        assert fresh["level"] == "Entry level" and fresh["pay"] == "₹14 LPA"
        assert fresh["eligibility"] == "2026, 2027 · B.Tech CSE/AI"
        assert fresh["skills"] == "Python, SQL"
        [intern] = interns
        assert intern["pay"] == "₹40,000/month" and intern["deadline"] == "2026-10-20"
        assert [r["title"] for r in needs_checking(store)] == ["Analyst"]

        again = asyncio.run(enrich(Settings(), store, rows, llm=llm))
        assert again["cached"] == 3 and len(llm.calls) == 3


def test_failed_notes_are_counted_not_raised(tmp_path):
    llm = FakeStructuredLLM(lambda m: "not json")
    with CommunityStore(tmp_path / "c.db") as store:
        seed(store)
        jobs, interns, _ = current(store)
        stats = asyncio.run(enrich(Settings(), store, jobs + interns, llm=llm, limit=1))
        assert stats["failed"] == 1
