"""Cheap checks before a run: is the GPU free enough, is Ollama up, is the session there.

None of these load a model.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from job_agent.llm import split_model_spec
from job_agent.settings import Settings


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def free_vram_mib() -> int | None:
    """Free VRAM on the local GPU, or None when nvidia-smi isn't available (e.g. laptop)."""
    if not shutil.which("nvidia-smi"):
        return None
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout
    return min(int(line) for line in out.split())


def check_vram(settings: Settings) -> Check:
    free = free_vram_mib()
    need = settings.vram.min_free_mib
    if free is None:
        return Check("vram", True, "no local GPU here; skipped", fatal=False)
    return Check("vram", free >= need, f"{free} MiB free, need {need} MiB")


def check_ollama(settings: Settings) -> Check:
    provider, model = split_model_spec(settings.llm.model)
    if provider != "ollama":
        return Check("ollama", True, f"provider is {provider}; skipped", fatal=False)
    try:
        resp = httpx.get(f"{settings.llm.base_url}/api/tags", timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return Check("ollama", False, f"unreachable at {settings.llm.base_url}: {exc}")
    pulled = {m["name"] for m in resp.json().get("models", [])}
    if model not in pulled and f"{model}:latest" not in pulled:
        have = ", ".join(sorted(pulled)) or "none"
        return Check("ollama", False, f"model {model} not pulled (have: {have})")
    return Check("ollama", True, f"{model} available at {settings.llm.base_url}")


def check_session(settings: Settings) -> Check:
    path = settings.paths.session
    return Check("waas session", path.exists(), str(path))


def run_checks(settings: Settings) -> list[Check]:
    return [check_vram(settings), check_ollama(settings), check_session(settings)]


def wait_for_vram(
    settings: Settings, deadline: datetime, poll_s: float = 300, sleep=time.sleep
) -> bool:
    """Poll until enough VRAM is free or the deadline passes. True if the GPU is usable."""
    while True:
        if check_vram(settings).ok:
            return True
        if datetime.now() + timedelta(seconds=poll_s) > deadline:
            return False
        sleep(poll_s)
