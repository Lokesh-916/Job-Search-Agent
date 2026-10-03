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


def test_stage_cache_invalidation(tmp_path):
    with Store(tmp_path / "j.db") as s:
        s.upsert_hits("waas", [HIT], "2026-10-01T00:00:00+00:00")
        s.save_detail("7", {"job": {"salary": "100k"}}, "2026-10-01T00:00:00+00:00")
        qwen, h1 = "ollama:qwen3:14b", s.get("7")["content_hash"]
        assert s.needs_stage("7", "triage", qwen, h1)

        s.save_result("7", "triage", qwen, h1, {"keep": True})
        assert not s.needs_stage("7", "triage", qwen, h1)
        assert s.needs_stage("7", "triage", "ollama:gpt-oss:20b", h1)  # model swapped

        s.save_detail("7", {"job": {"salary": "150k"}}, "2026-10-02T00:00:00+00:00")
        h2 = s.get("7")["content_hash"]
        assert h2 != h1 and s.needs_stage("7", "triage", qwen, h2)  # posting changed

        s.save_result("7", "triage", qwen, h2, error="x")
        assert s.needs_stage("7", "triage", qwen, h2)  # failures retry


def test_user_status_roundtrip(tmp_path):
    with Store(tmp_path / "j.db") as s:
        s.save_user_status(
            {"7": {"status": "Applied", "notes": "ping founder", "applied_on": None}}
        )
        s.save_user_status({"7": {"status": "Interviewing", "notes": "ping founder"}})
        row = s.user_status()["7"]
        assert row["status"] == "Interviewing" and row["notes"] == "ping founder"
