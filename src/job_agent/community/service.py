"""Operations shared by the CLI, the daily cron job and the community bot."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from job_agent.community.digest import big_picks, digest_text, write_workbook
from job_agent.community.feed import FeedStats, ranked, refresh
from job_agent.community.store import CommunityStore
from job_agent.community.telegram import Sender
from job_agent.settings import Settings

ROSTER = Path("data/roster.csv")  # roll_no,name (private; never committed)
CHECK = "Check experience"
SHEET_CAPTION = "📊 Everything in one sheet: jobs, internships, hackathons and events"
PICK_MEMORY_DAYS = 14  # a featured big-company role is not featured again for this long


def db_path(settings: Settings) -> Path:
    return settings.paths.data_dir / "community.db"


def with_notes(row, notes: dict | None) -> dict | None:
    """Fold optional LLM notes into a posting; None when the notes rule it out."""
    r = {**dict(row), "eligibility": "", "skills": "", "summary": ""}
    if not notes:
        return r
    if notes.get("fresher_ok") == "no" and r["kind"] == "job":
        return None
    if r["level"] in (CHECK, "Not specified") and notes.get("fresher_ok") == "yes":
        r["level"] = "Entry level"
    bits = [b for b in (notes.get("batches"), notes.get("eligibility")) if b]
    r["eligibility"] = " · ".join(bits)
    r["skills"] = ", ".join(notes.get("skills") or [])
    r["summary"] = notes.get("summary") or ""
    if notes.get("pay") and (not r["pay"] or r["pay"].startswith("Paid")):
        r["pay"] = notes["pay"]
    r["deadline"] = r["deadline"] or notes.get("apply_by")
    return r


def _postings(store: CommunityStore) -> list[dict]:
    since = store.get_meta("last_refresh") or "9999"
    notes = store.all_notes()
    rows = (with_notes(r, notes.get(r["key"])) for r in store.live_postings(since))
    return ranked([r for r in rows if r is not None])


def current(store: CommunityStore) -> tuple[list, list, list]:
    """Jobs, internships and upcoming events from the latest refresh."""
    rows = _postings(store)
    jobs = [r for r in rows if r["kind"] == "job" and r["level"] != CHECK]
    interns = [r for r in rows if r["kind"] == "internship"]
    since = store.get_meta("last_refresh") or "9999"
    return jobs, interns, store.live_events(since, date.today().isoformat())


def needs_checking(store: CommunityStore) -> list:
    """Roles whose experience bar we couldn't read (no job text, no LLM verdict)."""
    return [r for r in _postings(store) if r["level"] == CHECK]


def rebuild(settings: Settings, store: CommunityStore) -> Path:
    """Rewrite today's sheet from the database (after enrichment), without refetching."""
    jobs, interns, events = current(store)
    today = date.today().isoformat()
    out = settings.paths.data_dir / "community" / f"placement_feed_{today}.xlsx"
    since = store.get_meta("last_refresh") or today
    picks = todays_picks(store, jobs, interns, today)
    write_workbook(out, jobs, interns, events, today, needs_checking(store), since, picks)
    store.set_meta("last_workbook", str(out))
    return out


def latest_workbook(store: CommunityStore) -> Path | None:
    path = store.get_meta("last_workbook")
    return Path(path) if path and Path(path).exists() else None


def refresh_and_build(settings: Settings, store: CommunityStore) -> tuple[FeedStats, Path]:
    stats = refresh(settings, store)
    store.set_meta("last_refresh", stats.run_at)
    store.delete_meta(f"picks:{date.today().isoformat()}")  # re-pick from the fresh data
    return stats, rebuild(settings, store)


def todays_picks(store: CommunityStore, jobs: list, interns: list, today: str) -> list:
    """Today's "Big names" (fixed once chosen, so /today matches the morning message)."""
    live = {r["key"]: r for r in jobs + interns}
    chosen = store.get_meta(f"picks:{today}")
    if chosen is not None:
        return [live[k] for k in json.loads(chosen) if k in live]
    since = store.get_meta("last_refresh") or today
    two_weeks_ago = (date.fromisoformat(today) - timedelta(days=PICK_MEMORY_DAYS)).isoformat()
    recent = {k for day, keys in store.meta_with_prefix("picks:").items()
              if day >= two_weeks_ago for k in json.loads(keys)}  # fmt: skip
    picks = big_picks(jobs, interns, since, recent)
    store.set_meta(f"picks:{today}", json.dumps([r["key"] for r in picks]))
    return picks


def todays_digest(store: CommunityStore) -> str:
    jobs, interns, events = current(store)
    since = store.get_meta("last_refresh")
    today = date.today().isoformat()
    picks = todays_picks(store, jobs, interns, today)
    return digest_text(jobs, interns, events, today, new_since=since, picks=picks)


def deliver(settings: Settings, store: CommunityStore, chat_ids: list[int] | None = None):
    """Send today's digest + workbook to approved users (or the given chats)."""
    token = settings.secrets.community_bot_token
    if not token:
        raise RuntimeError("COMMUNITY_BOT_TOKEN missing in .env")
    if chat_ids is None:  # every approved member, plus the coordinator
        owner = settings.secrets.telegram_chat_id
        approved = [u["telegram_id"] for u in store.users("approved")]
        chat_ids = list(dict.fromkeys(approved + ([int(owner)] if owner else [])))
    targets = chat_ids
    failed = Sender(token).broadcast(targets, todays_digest(store), latest_workbook(store),
                                     caption=SHEET_CAPTION)  # fmt: skip
    for chat_id in targets:
        if chat_id not in failed:
            store.count_digest(chat_id)
    return len(targets) - len(failed), failed


def load_roster(path: Path = ROSTER) -> dict[str, str]:
    """roll number (upper-case) -> name; empty when no roster file exists."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if rows and rows[0] and not any(ch.isdigit() for ch in rows[0][0]):
        rows = rows[1:]  # header
    return {r[0].strip().upper(): (r[1].strip() if len(r) > 1 else "") for r in rows if r}
