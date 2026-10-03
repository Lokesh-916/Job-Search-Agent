"""Fake chat model for tests: no Ollama, no GPU."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ValidationError


class FakeStructuredLLM:
    """Mimics `with_structured_output(..., include_raw=True)`.

    `respond(messages) -> dict | str` returns the JSON the "model" would produce;
    strings that fail validation become parsing errors, like a real model's bad output.
    """

    def __init__(self, respond: Callable[[list], dict[str, Any] | str]):
        self.respond = respond
        self.calls: list[list] = []

    def with_structured_output(self, schema: type[BaseModel], **_: Any) -> RunnableLambda:
        def run(messages: list) -> dict[str, Any]:
            self.calls.append(messages)
            out = self.respond(messages)
            raw = AIMessage(out if isinstance(out, str) else str(out))
            try:
                parsed = (
                    schema.model_validate_json(out)
                    if isinstance(out, str)
                    else schema.model_validate(out)
                )
            except ValidationError as exc:
                return {"raw": raw, "parsed": None, "parsing_error": exc}
            return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return RunnableLambda(run)
