"""SQLite store: the source of truth. The daily workbook is a view generated from it."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    company_id        TEXT,
    company_name      TEXT,
    title             TEXT,
    url               TEXT,
    hit_json          TEXT,
    detail_json       TEXT,
    content_hash      TEXT,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    detail_fetched_at TEXT,
    changed_at        TEXT,
    closed            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_id);

-- One row per (job, pipeline stage). `input_hash` + `model` make results cacheable:
-- a stage is redone only when the posting changed or a different model is configured.
CREATE TABLE IF NOT EXISTS llm_results (
    job_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    model       TEXT NOT NULL,
    input_hash  TEXT,
    result_json TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (job_id, stage)
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def content_hash(detail: dict[str, Any]) -> str:
    """Hash of the job posting itself, so company-side noise doesn't count as a change."""
    payload = json.dumps(detail.get("job", detail), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def upsert_hits(self, source: str, hits: list[dict], seen_at: str) -> list[str]:
        """Record search hits; returns ids that are new to the store."""
        known = {r[0] for r in self.db.execute("SELECT job_id FROM jobs WHERE source=?", (source,))}
        new_ids = []
        with self.db:
            for h in hits:
                job_id = str(h["id"])
                if job_id not in known:
                    new_ids.append(job_id)
                self.db.execute(
                    """INSERT INTO jobs (job_id, source, company_id, company_name, title, url,
                                         hit_json, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(job_id) DO UPDATE SET
                         title=excluded.title, url=excluded.url, hit_json=excluded.hit_json,
                         last_seen=excluded.last_seen, closed=0""",
                    (job_id, source, str(h.get("company_id")), h.get("company_name"),
                     h.get("title"), h.get("search_path"), json.dumps(h), seen_at, seen_at),
                )  # fmt: skip
        return new_ids

    def ids_needing_detail(self, job_ids: list[str], refetch_after_days: int) -> list[str]:
        if not job_ids:
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=refetch_after_days)).isoformat("T", "seconds")
        rows = self.db.execute(
            f"SELECT job_id FROM jobs WHERE job_id IN ({','.join('?' * len(job_ids))})"
            " AND (detail_fetched_at IS NULL OR detail_fetched_at < ?)",
            (*job_ids, cutoff),
        )
        return [r[0] for r in rows]

    def save_detail(self, job_id: str, detail: dict[str, Any], fetched_at: str) -> bool:
        """Store a job's detail; returns True if the posting is new or changed."""
        new_hash = content_hash(detail)
        row = self.db.execute("SELECT content_hash FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        changed = row is None or row["content_hash"] != new_hash
        with self.db:
            self.db.execute(
                """UPDATE jobs SET detail_json=?, content_hash=?, detail_fetched_at=?,
                                   changed_at=CASE WHEN ? THEN ? ELSE changed_at END
                   WHERE job_id=?""",
                (json.dumps(detail), new_hash, fetched_at, changed, fetched_at, job_id),
            )
        return changed

    def mark_closed(self, job_ids: list[str]) -> None:
        with self.db:
            self.db.executemany("UPDATE jobs SET closed=1 WHERE job_id=?", [(j,) for j in job_ids])

    def close_unseen(self, source: str, run_started: str) -> int:
        """Jobs from this source that didn't show up in this run's search are closed."""
        with self.db:
            cur = self.db.execute(
                "UPDATE jobs SET closed=1 WHERE source=? AND last_seen < ? AND closed=0",
                (source, run_started),
            )
        return cur.rowcount

    def open_jobs(self, source: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM jobs WHERE closed=0 AND detail_json IS NOT NULL"
        args: tuple = ()
        if source:
            sql, args = sql + " AND source=?", (source,)
        return self.db.execute(sql + " ORDER BY first_seen DESC", args).fetchall()

    def needs_stage(self, job_id: str, stage: str, model: str, input_hash: str) -> bool:
        """True unless a successful result exists for these exact inputs and model."""
        res = self.get_result(job_id, stage)
        return not (
            res
            and res["error"] is None
            and res["model"] == model
            and res["input_hash"] == input_hash
        )

    def get_result(self, job_id: str, stage: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM llm_results WHERE job_id=? AND stage=?", (job_id, stage)
        ).fetchone()

    def save_result(
        self,
        job_id: str,
        stage: str,
        model: str,
        input_hash: str | None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO llm_results
                   (job_id, stage, model, input_hash, result_json, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (job_id, stage, model, input_hash,
                 json.dumps(result) if result is not None else None, error, now_iso()),
            )  # fmt: skip

    def get(self, job_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
