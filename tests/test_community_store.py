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


def test_roster_with_and_without_header(tmp_path):
    from job_agent.community.service import load_roster

    (tmp_path / "a.csv").write_text("Roll No,Name\ncs23b1001,Asha\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("CS23B1002,Ravi\n", encoding="utf-8")
    assert load_roster(tmp_path / "a.csv") == {"CS23B1001": "Asha"}
    assert load_roster(tmp_path / "b.csv") == {"CS23B1002": "Ravi"}
    assert load_roster(tmp_path / "missing.csv") == {}


def test_meta(tmp_path):
    with CommunityStore(tmp_path / "c.db") as s:
        assert s.get_meta("last_refresh") is None
        s.set_meta("last_refresh", "2026-10-05T02:00:00+00:00")
        assert s.get_meta("last_refresh").startswith("2026-10-05")


def test_events_already_started_without_deadline_are_hidden(tmp_path):
    past = Event("gdg", "9", "Meetup / workshop", "Old jam", "GDG", "Online", "Pune",
                 "2025-12-29", None, None, "", "u")  # fmt: skip
    with CommunityStore(tmp_path / "c.db") as s:
        s.upsert_event(past, "2026-10-05T00:00:00+00:00")
        assert s.live_events("2026-10-05T00:00:00+00:00", "2026-10-05") == []


def test_digest_caps_each_company():
    from job_agent.community.digest import per_company

    rows = [{"company": c} for c in ["Amazon"] * 5 + ["CRED"]]
    assert [r["company"] for r in per_company(rows, 2)] == ["Amazon", "Amazon", "CRED"]


def test_upcoming_keeps_open_registration_and_future_starts():
    from job_agent.community.digest import upcoming

    ev = [
        {"name": "ongoing", "deadline": None, "starts": "2025-12-29"},
        {"name": "open", "deadline": "2026-10-07", "starts": "2026-10-01"},
        {"name": "future", "deadline": None, "starts": "2026-10-09"},
    ]
    assert [e["name"] for e in upcoming(ev, "2026-10-05")] == ["open", "future"]


def test_batch_roll_rule():
    from job_agent.settings import CommunityConfig

    c = CommunityConfig()
    assert (
        c.roll_allowed("123AD0001") and c.roll_allowed("123ad0061") and c.roll_allowed("123AD0021")
    )
    for bad in (
        "123AD0000",
        "123AD0062",
        "123AD0022",
        "123AD0027",
        "123AD0029",
        "123AD0044",
        "123AD001",
        "124AD0005",
        "123AD00X1",
        "",
    ):
        assert not c.roll_allowed(bad), bad


def test_failed_board_keeps_its_recent_listings(tmp_path):
    from job_agent.community.classify import Verdict
    from job_agent.community.models import Posting
    from job_agent.community.store import CommunityStore

    with CommunityStore(tmp_path / "c.db") as s:
        v = Verdict(True, "", "job", "Entry level", "Data")
        s.upsert_posting(Posting("eightfold", "Microsoft", "1", "SWE", "u"), v, "big_tech",
                         "2026-10-04T02:30:00+00:00")  # fmt: skip
        s.upsert_posting(Posting("eightfold", "Microsoft", "2", "Old", "u"), v, "big_tech",
                         "2026-09-01T02:30:00+00:00")  # fmt: skip
        s.keep_live("Microsoft", "2026-10-05T02:30:00+00:00")
        assert [r["title"] for r in s.live_postings("2026-10-05T02:30:00+00:00")] == ["SWE"]
