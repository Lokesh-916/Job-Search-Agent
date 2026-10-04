from openpyxl import load_workbook

import job_agent.community.feed as feed
from job_agent.community.digest import digest_text, write_workbook
from job_agent.community.events import Event
from job_agent.community.models import Posting
from job_agent.community.store import CommunityStore
from job_agent.settings import Settings


def p(source, company, title, location, kind_pay=None, **extra):
    return Posting(source, company, title[:3] + company, title, f"https://x/{company}",
                   location=location, extra={"pay": kind_pay, **extra})  # fmt: skip


RAW = [
    (p("lever", "CRED", "SDE I", "Bengaluru"), "unicorn"),
    (p("lever", "CRED", "Senior Software Engineer", "Bengaluru"), "unicorn"),
    (p("greenhouse", "Stripe", "Software Engineer", "Singapore"), "unicorn"),
    (p("greenhouse", "Stripe", "Software Engineering Intern", "Bengaluru"), "unicorn"),
    (p("unstop", "Acme Edu", "Python Internship", "Remote, India", internship=True), "other"),
    (p("unstop", "DataCo", "Data Science Internship", "Remote, India", "₹15,000–20,000",
       internship=True), "other"),
    (p("adzuna", "Zomato", "Account Manager", "Gurgaon"), "other"),
]  # fmt: skip
EVENTS = [Event("devfolio", "1", "Hackathon", "HackX", "IIT H", "In person", "Hyderabad",
                "2026-10-20", "2026-10-21", "2026-10-15", "", "https://hackx.devfolio.co"),
          Event("gdg", "2", "Meetup / workshop", "Gemini Study Jam", "GDG on Campus X - Pune, India",
                "Online", "on Campus X University - Pune, India", "2026-10-09", None, None, "",
                "https://gdg.community.dev/e/1/")]  # fmt: skip


def test_refresh_curates_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(feed, "gather", lambda settings: (RAW, {}))
    monkeypatch.setattr(feed, "fetch_events", lambda client: (EVENTS, {}))
    with CommunityStore(tmp_path / "c.db") as store:
        stats = feed.refresh(Settings(), store)
        assert stats.kept == {"job": 1, "internship": 2}
        assert stats.dropped["Senior role"] == 1 and stats.dropped["Not in India"] == 1
        assert stats.dropped["Internship without stipend"] == 1
        assert stats.dropped["Not a tech role"] == 1 and stats.new["event"] == 2
        rows = store.live_postings(stats.run_at)
        stripe = next(r for r in rows if r["company"] == "Stripe")
        assert stripe["kind"] == "internship" and stripe["pay"] == "Paid (amount not listed)"
        gdg = next(e for e in store.live_events(stats.run_at, "2026-10-05") if e["source"] == "gdg")
        assert gdg["city"] == "Pune (X University)"

        jobs = [r for r in rows if r["kind"] == "job"]
        interns = [r for r in rows if r["kind"] == "internship"]
        events = store.live_events(stats.run_at, "2026-10-05")
        today = stats.run_at[:10]
        text = digest_text(jobs, interns, events, today)
        assert "SDE I" in text and "₹15,000–20,000" in text and "HackX" in text
        path = write_workbook(tmp_path / "feed.xlsx", jobs, interns, events, today)
        wb = load_workbook(path)
        assert wb.sheetnames == ["📊 Today", "💼 Jobs", "🎓 Internships", "🏆 Hackathons",
                                 "🎤 Tech events", "🔍 Check experience"]  # fmt: skip
        assert wb["🎓 Internships"].cell(2, 7).value in (
            "Paid (amount not listed)",
            "₹15,000–20,000",
        )
