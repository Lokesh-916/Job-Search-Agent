"""Run metrics: per-call LLM latency and tokens, stage timings, events and GPU memory.

A `RunMetrics` callback is attached to every LLM invocation through `llm_config(stage)`,
so stages, the structured runner and the research agent all report without extra plumbing.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections import Counter, defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

_current: ContextVar[RunMetrics | None] = ContextVar("job_agent_metrics", default=None)


@dataclass
class LLMCall:
    stage: str
    started: float
    latency_s: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    load_s: float | None = None  # model (re)load time reported by Ollama
    eval_s: float | None = None  # pure generation time reported by Ollama
    ok: bool = True


@dataclass
class RunMetrics(BaseCallbackHandler):
    run_inline = True  # record on the event loop, not in a thread pool

    calls: list[LLMCall] = field(default_factory=list)
    events: Counter = field(default_factory=Counter)
    stage_seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    vram_peak_mib: int | None = None
    _open: dict[UUID, tuple[float, str]] = field(default_factory=dict)
    _tools: dict[UUID, str] = field(default_factory=dict)

    # --- LangChain callback hooks -------------------------------------------------------
    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kw) -> None:
        self._open[run_id] = (time.perf_counter(), (metadata or {}).get("stage", "other"))

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kw: Any) -> None:
        started, stage = self._open.pop(run_id, (time.perf_counter(), "other"))
        call = LLMCall(stage, started, time.perf_counter() - started)
        gen = (
            response.generations[0][0] if response.generations and response.generations[0] else None
        )
        msg = getattr(gen, "message", None)
        if msg is not None:
            usage = getattr(msg, "usage_metadata", None) or {}
            meta = getattr(msg, "response_metadata", None) or {}
            call.input_tokens = usage.get("input_tokens") or meta.get("prompt_eval_count")
            call.output_tokens = usage.get("output_tokens") or meta.get("eval_count")
            if meta.get("load_duration"):
                call.load_s = meta["load_duration"] / 1e9
            if meta.get("eval_duration"):
                call.eval_s = meta["eval_duration"] / 1e9
        self.calls.append(call)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        started, stage = self._open.pop(run_id, (time.perf_counter(), "other"))
        self.calls.append(LLMCall(stage, started, time.perf_counter() - started, ok=False))

    def on_tool_start(self, serialized, input_str, *, run_id, **kw) -> None:
        self._tools[run_id] = (serialized or {}).get("name", "tool")

    def on_tool_end(self, output: Any, *, run_id: UUID, **kw: Any) -> None:
        self.events[f"tool:{self._tools.pop(run_id, 'tool')}"] += 1

    # --- summaries ----------------------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        by_stage: dict[str, dict[str, Any]] = {}
        for stage in sorted({c.stage for c in self.calls}):
            calls = [c for c in self.calls if c.stage == stage]
            lat = sorted(c.latency_s for c in calls)
            out_tok = sum(c.output_tokens or 0 for c in calls)
            eval_s = sum(c.eval_s or 0 for c in calls)
            by_stage[stage] = {
                "calls": len(calls),
                "errors": sum(not c.ok for c in calls),
                "p50_s": round(lat[len(lat) // 2], 2),
                "p95_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2),
                "input_tokens": sum(c.input_tokens or 0 for c in calls),
                "output_tokens": out_tok,
                "tokens_per_s": round(out_tok / eval_s, 1) if eval_s else None,
                "load_s": round(sum(c.load_s or 0 for c in calls), 1),
            }
        return {
            "stage_seconds": {k: round(v, 1) for k, v in self.stage_seconds.items()},
            "llm": by_stage,
            "events": dict(self.events),
            "vram_peak_mib": self.vram_peak_mib,
        }

    def log_lines(self) -> list[tuple[str, Any]]:
        """Flat (key, value) rows for the workbook's Run Log tab."""
        s = self.summary()
        rows: list[tuple[str, Any]] = [(f"⏱ {k} (s)", v) for k, v in s["stage_seconds"].items()]
        for stage, m in s["llm"].items():
            rows.append((
                f"🤖 {stage}",
                f"{m['calls']} calls, p50 {m['p50_s']}s, p95 {m['p95_s']}s, "
                f"{m['input_tokens']}→{m['output_tokens']} tok, {m['tokens_per_s']} tok/s, "
                f"{m['errors']} errors",
            ))  # fmt: skip
        rows += [(f"📌 {k}", v) for k, v in sorted(s["events"].items())]
        if s["vram_peak_mib"] is not None:
            rows.append(("🎮 GPU memory peak (MiB)", s["vram_peak_mib"]))
        return rows


def current() -> RunMetrics | None:
    return _current.get()


def activate(metrics: RunMetrics | None):
    return _current.set(metrics)


def event(name: str) -> None:
    if (m := _current.get()) is not None:
        m.events[name] += 1


def llm_config(stage: str) -> dict[str, Any]:
    """RunnableConfig that tags calls with their stage and reports to the active metrics."""
    m = _current.get()
    return {"metadata": {"stage": stage}, "callbacks": [m] if m is not None else []}


class StageTimer:
    def __init__(self, name: str):
        self.name = name

    def __enter__(self) -> StageTimer:
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        if (m := _current.get()) is not None:
            m.stage_seconds[self.name] += time.perf_counter() - self.t0


class VramSampler:
    """Background thread sampling total GPU memory in use; no-op without nvidia-smi."""

    def __init__(self, metrics: RunMetrics, every_s: float = 5.0):
        self.metrics, self.every_s = metrics, every_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self) -> int | None:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout  # fmt: skip
        return max((int(x) for x in out.split()), default=None)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                used = self._sample()
            except (OSError, subprocess.SubprocessError, ValueError):
                return
            if used is not None:
                self.metrics.vram_peak_mib = max(self.metrics.vram_peak_mib or 0, used)
            self._stop.wait(self.every_s)

    def __enter__(self) -> VramSampler:
        if shutil.which("nvidia-smi"):
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
