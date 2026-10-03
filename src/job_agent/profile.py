"""Candidate profile (profile.yaml) and the compact briefs we put in prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

EXAMPLE_PROFILE = Path("profile.example.yaml")


def load_profile(path: Path) -> dict[str, Any]:
    src = path if path.exists() else EXAMPLE_PROFILE
    return yaml.safe_load(src.read_text(encoding="utf-8")) or {}


def preferences_brief(profile: dict[str, Any]) -> str:
    """What kinds of jobs the candidate wants. Short enough for every triage call."""
    prefs = profile.get("preferences", {})
    edu = profile.get("education", {})
    lines = [
        f"Candidate: {edu.get('degree', 'student')} ({edu.get('graduation', '?')}), "
        f"based in {profile.get('location', 'India')}.",
        f"Wants: {prefs.get('job_type', 'full-time')} roles.",
        f"Favourite work: {prefs.get('favourite_work', '-')}.",
        f"Also happy with: {', '.join(prefs.get('also_happy_with', []))}.",
        f"Not interested in: {', '.join(prefs.get('not_interested', []))}.",
    ]
    return "\n".join(lines)


def full_brief(profile: dict[str, Any]) -> str:
    """Everything relevant for fit assessment, as readable YAML."""
    keep = (
        "education",
        "availability",
        "experience",
        "research",
        "projects",
        "skills",
        "preferences",
    )
    return yaml.safe_dump(
        {k: profile[k] for k in keep if k in profile}, sort_keys=False, allow_unicode=True
    )
