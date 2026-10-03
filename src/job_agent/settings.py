"""Typed configuration loaded from config.yaml (+ secrets from .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG_PATH = Path("config.example.yaml")


class LLMConfig(BaseModel):
    model: str = "ollama:qwen3:14b"
    base_url: str | None = "http://localhost:11434"
    temperature: float = 0.0
    num_ctx: int = 16384
    keep_alive: str = "5m"
    max_concurrency: int = 2
    tasks: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WaasSourceConfig(BaseModel):
    roles: list[str] = Field(default_factory=list)
    job_types: list[str] = Field(default_factory=lambda: ["fulltime"])
    max_min_experience: int = 1
    remote: list[str] = Field(default_factory=lambda: ["yes", "only"])
    locations: list[str] = Field(default_factory=lambda: ["IN"])
    exclude_us_auth_required: bool = True
    include_visa_sponsored: bool = True
    concurrency: int = 4
    request_delay_s: float = 0.5
    refetch_after_days: int = 3


class SourcesConfig(BaseModel):
    waas: WaasSourceConfig = Field(default_factory=WaasSourceConfig)


class Preferences(BaseModel):
    salary_floor_lpa: float = 9
    salary_good_lpa: float = 12
    salary_foreign_target_lpa: float = 20
    salary_stretch_usd: float = 120_000
    include_onsite_india: bool = True
    preferred_cities: list[str] = Field(default_factory=lambda: ["Hyderabad", "Bengaluru"])
    max_experience_years: float = 1


class Scoring(BaseModel):
    remote_eligibility: float = 30
    pay: float = 25
    low_dsa: float = 15
    fit: float = 20
    company: float = 10
    top_pick_threshold: float = 75


class ResearchConfig(BaseModel):
    cache_days: int = 14
    max_tool_calls: int = 8
    searxng_url: str | None = None


class BrowserConfig(BaseModel):
    channel: str | None = None
    headless: bool = True


class VramConfig(BaseModel):
    min_free_mib: int = 11000


class Paths(BaseModel):
    data_dir: Path = Path("data")
    output_dir: Path = Path("workbooks")
    profile: Path = Path("profile.yaml")
    session: Path = Path("secrets/waas_storage_state.json")


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    openai_api_key: str | None = None


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    preferences: Preferences = Field(default_factory=Preferences)
    scoring: Scoring = Field(default_factory=Scoring)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    vram: VramConfig = Field(default_factory=VramConfig)
    paths: Paths = Field(default_factory=Paths)
    secrets: Secrets = Field(default_factory=Secrets)


def load_settings(path: Path | None = None) -> Settings:
    """Load config.yaml, falling back to config.example.yaml."""
    path = path or (CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return Settings(**(data or {}))


@lru_cache
def get_settings() -> Settings:
    return load_settings()
