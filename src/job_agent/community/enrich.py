"""Optional LLM pass over the community feed: read each posting's text and note what the
rules can't see (is it really fresher-friendly, which batches, CTC, deadline, key skills).

Runs only when the GPU is free; the feed works without it. Results are cached per posting,
model and description, so a daily pass only reads new postings.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from job_agent.community.store import CommunityStore
from job_agent.llm import get_chat_model
from job_agent.settings import Settings
from job_agent.structured import abatch_structured

STAGE = "community"
MAX_TEXT = 3000

SYSTEM = """You read one job or internship posting from an Indian careers page and note facts
for final-year B.Tech students (graduating 2027) deciding whether to apply.
Only use what the posting says; never guess. Leave a field empty when the posting is silent.
- fresher_ok: "yes" if new graduates / freshers / students can apply (or 0-1 years asked),
  "no" if it asks for 2+ years of full-time experience or is clearly a senior role,
  "unclear" otherwise.
- min_years: the smallest full-time experience asked for, in years (null if not stated).
- batches: graduation years accepted, e.g. "2026, 2027" (empty if not stated).
- eligibility: degree, branches and CGPA cut-off in a few words (empty if not stated).
- pay: CTC or stipend exactly as stated, e.g. "₹12-18 LPA" or "₹25,000/month" (empty if none).
- apply_by: application deadline as YYYY-MM-DD (null if none).
- skills: up to 6 key skills or technologies asked for.
- summary: one plain sentence on what the person will actually do."""


class PostingNotes(BaseModel):
    fresher_ok: Literal["yes", "no", "unclear"]
    min_years: int | None = None
    batches: str = ""
    eligibility: str = ""
    pay: str = ""
    apply_by: str | None = Field(None, description="YYYY-MM-DD")
    skills: list[str] = Field(default_factory=list, max_length=6)
    summary: str = ""


def input_hash(row, text: str) -> str:
    payload = "|".join([row["title"], row["company"], row["location"] or "", text[:MAX_TEXT]])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def messages(row, text: str) -> list:
    body = (f"Company: {row['company']}\nRole: {row['title']}\nLocation: {row['location']}\n"
            f"Type: {row['kind']}\n\n{text[:MAX_TEXT]}")  # fmt: skip
    return [SystemMessage(SYSTEM), HumanMessage(body)]


async def enrich(
    settings: Settings,
    store: CommunityStore,
    rows: list,
    llm: BaseChatModel | None = None,
    limit: int | None = None,
) -> Counter:
    """Note every posting in `rows` that has job text and no up-to-date notes."""
    model = settings.llm.model
    stats: Counter = Counter()
    todo: dict[str, list] = {}
    hashes: dict[str, str] = {}
    for row in rows:
        text = store.description(row["key"])
        if not text:
            stats["no text"] += 1
            continue
        h = input_hash(row, text)
        if store.notes_fresh(row["key"], model, h):
            stats["cached"] += 1
            continue
        todo[row["key"]], hashes[row["key"]] = messages(row, text), h
    if limit is not None:
        todo = dict(list(todo.items())[:limit])
    if not todo:
        return stats
    results = await abatch_structured(
        llm or get_chat_model(STAGE), PostingNotes, todo,
        max_concurrency=settings.llm.max_concurrency, stage=STAGE,
    )  # fmt: skip
    for key, out in results.items():
        if isinstance(out, Exception):
            stats["failed"] += 1
            continue
        store.save_notes(key, model, hashes[key], out.model_dump())
        stats["noted"] += 1
    return stats
