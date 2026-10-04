"""Run a chat model with a Pydantic output schema, with one self-repair attempt."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from job_agent import metrics


class StructuredOutputError(RuntimeError):
    pass


def _raw_text(raw: object) -> str:
    content = getattr(raw, "content", raw)
    return content if isinstance(content, str) else str(content)


async def ainvoke_structured[T: BaseModel](
    llm: BaseChatModel,
    schema: type[T],
    messages: Sequence[BaseMessage],
    repairs: int = 1,
    stage: str = "other",
) -> T:
    """Constrained JSON output; on a validation error, show the model its mistake and retry."""
    runnable = llm.with_structured_output(schema, method="json_schema", include_raw=True)
    convo = list(messages)
    for attempt in range(repairs + 1):
        out = await runnable.ainvoke(convo, config=metrics.llm_config(stage))
        if out.get("parsed") is not None and out.get("parsing_error") is None:
            return out["parsed"]
        error = out.get("parsing_error") or "empty output"
        if attempt == repairs:
            metrics.event(f"{stage}:invalid_json")
            raise StructuredOutputError(f"{schema.__name__}: {error}")
        metrics.event(f"{stage}:repair")
        convo += [
            AIMessage(_raw_text(out.get("raw"))),
            HumanMessage(
                f"That output did not match the schema: {error}. "
                "Reply again with ONLY the corrected JSON object."
            ),
        ]
    raise AssertionError("unreachable")


async def abatch_structured[T: BaseModel](
    llm: BaseChatModel,
    schema: type[T],
    batches: dict[str, Sequence[BaseMessage]],
    max_concurrency: int = 2,
    stage: str = "other",
) -> dict[str, T | Exception]:
    """Run many prompts with bounded concurrency; per-item failures are returned, not raised."""
    sem = asyncio.Semaphore(max_concurrency)

    async def one(key: str, msgs: Sequence[BaseMessage]) -> tuple[str, T | Exception]:
        async with sem:
            try:
                return key, await ainvoke_structured(llm, schema, msgs, stage=stage)
            except Exception as exc:
                return key, exc

    results = await asyncio.gather(*(one(k, m) for k, m in batches.items()))
    return dict(results)
