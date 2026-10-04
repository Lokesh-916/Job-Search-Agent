from job_agent.community.classify import Verdict
from job_agent.community.events import Event
from job_agent.community.models import Posting
from job_agent.community.store import CommunityStore

P = Posting("lever", "CRED", "1", "SDE I", "https://x/1", location="Bengaluru",
            extra={"pay": None, "deadline": None})  # fmt: skip
V = Verdict(True, "Entry level", "job", "Entry level", "Software engineering")
E = Event("devfolio", "h1", "Hackathon", "HackX", "IIT", "In person", "Hyderabad",
          "2026-10-20", "2026-10-21", "2026-10-15", "", "https://hackx.devfolio.co")  # fmt: skip


def test_postings_new_then_seen(tmp_path):
    with CommunityStore(tmp_path / "c.db") as s:
        assert s.upsert_posting(P, V, "unicorn", "2026-10-05T00:00:00+00:00")
        assert not s.upsert_posting(P, V, "unicorn", "2026-10-06T00:00:00+00:00")
        [row] = s.live_postings("2026-10-06T00:00:00+00:00")
        assert row["first_seen"].startswith("2026-10-05") and row["tier"] == "unicorn"
        assert s.live_postings("2026-10-07T00:00:00+00:00") == []


def test_past_events_hidden(tmp_path):
    with CommunityStore(tmp_path / "c.db") as s:
        s.upsert_event(E, "2026-10-05T00:00:00+00:00")
        assert len(s.live_events("2026-10-05T00:00:00+00:00", "2026-10-10")) == 1
        assert s.live_events("2026-10-05T00:00:00+00:00", "2026-10-16") == []


def test_user_lifecycle_and_suggestions(tmp_path):
    with CommunityStore(tmp_path / "c.db") as s:
        s.register(42, "Asha", "asha", "CS23B1001")
        assert s.user(42)["status"] == "pending" and [
            u["telegram_id"] for u in s.users("pending")
        ] == [42]
        s.set_status(42, "approved")
        s.suggest(42, "Add Zoho jobs please")
        assert s.suggestions()[0]["roll_no"] == "CS23B1001"
        s.forget(42)
        assert s.user(42) is None and s.suggestions() == []
