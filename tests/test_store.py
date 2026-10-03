from job_agent.store import Store

HIT = {"id": 7, "company_id": 3, "company_name": "Acme", "title": "AI Eng", "search_path": "u"}


def test_new_then_known(tmp_path):
    with Store(tmp_path / "j.db") as s:
        assert s.upsert_hits("waas", [HIT], "2026-10-01T00:00:00+00:00") == ["7"]
        assert s.upsert_hits("waas", [HIT], "2026-10-02T00:00:00+00:00") == []
        row = s.get("7")
        assert row["first_seen"].startswith("2026-10-01")
        assert row["last_seen"].startswith("2026-10-02")


def test_detail_change_detection(tmp_path):
    with Store(tmp_path / "j.db") as s:
        s.upsert_hits("waas", [HIT], "2026-10-01T00:00:00+00:00")
        assert s.ids_needing_detail(["7"], refetch_after_days=3) == ["7"]
        assert s.save_detail("7", {"job": {"salary": "100k"}}, "2026-10-01T00:00:00+00:00")
        assert not s.save_detail("7", {"job": {"salary": "100k"}}, "2026-10-02T00:00:00+00:00")
        assert s.save_detail("7", {"job": {"salary": "120k"}}, "2026-10-03T00:00:00+00:00")


def test_close_unseen(tmp_path):
    with Store(tmp_path / "j.db") as s:
        s.upsert_hits("waas", [HIT], "2026-10-01T00:00:00+00:00")
        assert s.close_unseen("waas", "2026-10-02T00:00:00+00:00") == 1
        assert s.get("7")["closed"] == 1
        s.upsert_hits("waas", [HIT], "2026-10-03T00:00:00+00:00")
        assert s.get("7")["closed"] == 0
