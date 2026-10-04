"""Shared shapes: a curated company and a normalised job posting from any source."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

Tier = Literal["big_tech", "mnc", "unicorn", "startup"]
TIER_LABEL = {"big_tech": "🏛️ Big Tech", "mnc": "🏢 MNC", "unicorn": "🦄 Unicorn",
              "startup": "🚀 Startup"}  # fmt: skip


@dataclass(frozen=True)
class Company:
    name: str
    tier: Tier
    ats: str  # greenhouse | lever | ashby | workday | smartrecruiters | ...
    slug: str  # the company's board id on that platform
    india: bool = False  # has offices / hires in India
    site: str | None = None  # Workday-style extra path, when the platform needs one


@dataclass
class Posting:
    source: str  # e.g. "greenhouse"
    company: str
    external_id: str
    title: str
    url: str
    location: str = ""
    department: str = ""
    employment_type: str = ""
    posted_at: str | None = None  # ISO date when known
    description: str = ""  # plain text
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company}:{self.external_id}"


def load_companies(path: Path) -> list[Company]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for tier, entries in raw.items():
        for e in entries or []:
            out.append(Company(name=e["name"], tier=tier, ats=e["ats"], slug=e["slug"],
                               india=bool(e.get("india")), site=e.get("site")))  # fmt: skip
    return out
