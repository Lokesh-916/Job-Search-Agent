"""Community database (data/community.db): curated postings, events, users, suggestions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from job_agent.community.classify import Verdict
from job_agent.community.events import Event
from job_agent.community.models import Posting
from job_agent.store import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    key        TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    company    TEXT NOT NULL,
    tier       TEXT,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    location   TEXT,
    category   TEXT,
    level      TEXT,
    kind       TEXT NOT NULL,          -- job | internship
    pay        TEXT,                   -- stipend / CTC when stated
    deadline   TEXT,
    posted_at  TEXT,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    key        TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    organizer  TEXT,
    mode       TEXT,
    city       TEXT,
    starts     TEXT,
    ends       TEXT,
    deadline   TEXT,
    prize      TEXT,
    url        TEXT,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    name        TEXT,
    username    TEXT,
    roll_no     TEXT,
    status      TEXT NOT NULL,          -- pending | approved | rejected | left
    joined_at   TEXT NOT NULL,
    decided_at  TEXT,
    last_active TEXT,
    digests     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class CommunityStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> CommunityStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- postings and events -------------------------------------------------------------
    def upsert_posting(self, p: Posting, v: Verdict, tier: str, seen_at: str) -> bool:
        """Returns True if the posting is new."""
        is_new = self.db.execute("SELECT 1 FROM postings WHERE key=?", (p.key,)).fetchone() is None
        with self.db:
            self.db.execute(
                """INSERT INTO postings (key, source, company, tier, title, url, location,
                       category, level, kind, pay, deadline, posted_at, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET title=excluded.title, url=excluded.url,
                       location=excluded.location, category=excluded.category,
                       level=excluded.level, pay=excluded.pay, deadline=excluded.deadline,
                       last_seen=excluded.last_seen""",
                (p.key, p.source, p.company, tier, p.title, p.url, p.location, v.category,
                 v.level, v.kind, p.extra.get("pay"), p.extra.get("deadline"), p.posted_at,
                 seen_at, seen_at),
            )  # fmt: skip
        return is_new

    def upsert_event(self, e: Event, seen_at: str) -> bool:
        is_new = self.db.execute("SELECT 1 FROM events WHERE key=?", (e.key,)).fetchone() is None
        with self.db:
            self.db.execute(
                """INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET name=excluded.name, starts=excluded.starts,
                       ends=excluded.ends, deadline=excluded.deadline, prize=excluded.prize,
                       last_seen=excluded.last_seen""",
                (e.key, e.source, e.kind, e.name, e.organizer, e.mode, e.city, e.starts,
                 e.ends, e.deadline, e.prize, e.url, seen_at, seen_at),
            )  # fmt: skip
        return is_new

    def live_postings(self, since: str) -> list[sqlite3.Row]:
        """Postings seen in the latest fetch (last_seen >= since), newest first."""
        return self.db.execute(
            "SELECT * FROM postings WHERE last_seen >= ? ORDER BY first_seen DESC, posted_at DESC",
            (since,),
        ).fetchall()

    def live_events(self, since: str, today: str) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT * FROM events WHERE last_seen >= ?
                 AND COALESCE(ends, starts, deadline, '9999') >= ?
                 AND (deadline IS NULL OR deadline >= ?)
               ORDER BY COALESCE(deadline, starts, '9999')""",
            (since, today, today),
        ).fetchall()

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    # --- users ---------------------------------------------------------------------------
    def user(self, telegram_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()

    def register(self, telegram_id: int, name: str, username: str | None, roll_no: str) -> None:
        with self.db:
            self.db.execute(
                """INSERT INTO users (telegram_id, name, username, roll_no, status, joined_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)
                   ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name,
                       username=excluded.username, roll_no=excluded.roll_no, status='pending',
                       joined_at=excluded.joined_at, decided_at=NULL""",
                (telegram_id, name, username, roll_no, now_iso()),
            )

    def set_status(self, telegram_id: int, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE users SET status=?, decided_at=? WHERE telegram_id=?",
                            (status, now_iso(), telegram_id))  # fmt: skip

    def touch(self, telegram_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE users SET last_active=? WHERE telegram_id=?",
                            (now_iso(), telegram_id))  # fmt: skip

    def forget(self, telegram_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM users WHERE telegram_id=?", (telegram_id,))
            self.db.execute("DELETE FROM suggestions WHERE telegram_id=?", (telegram_id,))

    def users(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.db.execute(
                "SELECT * FROM users WHERE status=? ORDER BY joined_at", (status,)
            ).fetchall()
        return self.db.execute("SELECT * FROM users ORDER BY status, joined_at").fetchall()

    def count_digest(self, telegram_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE users SET digests = digests + 1 WHERE telegram_id=?",
                            (telegram_id,))  # fmt: skip

    # --- suggestions ---------------------------------------------------------------------
    def suggest(self, telegram_id: int, text: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO suggestions (telegram_id, text, created_at) VALUES (?, ?, ?)",
                (telegram_id, text, now_iso()),
            )

    def suggestions(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT s.*, u.name, u.roll_no FROM suggestions s
               LEFT JOIN users u USING (telegram_id) ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
