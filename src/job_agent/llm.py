"""Model-agnostic chat model factory.

Everything model-specific lives here; the rest of the code just asks for
`get_chat_model("extract")` and gets a LangChain BaseChatModel back.
"""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from job_agent.settings import LLMConfig, get_settings

# Keys that only make sense for Ollama; dropped for other providers.
_OLLAMA_ONLY = {"num_ctx", "keep_alive", "reasoning"}


def split_model_spec(spec: str) -> tuple[str, str]:
    """'ollama:qwen3:14b' -> ('ollama', 'qwen3:14b')."""
    provider, sep, model = spec.partition(":")
    if not sep or not model:
        raise ValueError(f"Model spec must look like '<provider>:<model>', got {spec!r}")
    return provider, model


def resolve_task_config(cfg: LLMConfig, task: str | None) -> dict[str, Any]:
    """Merge global LLM config with the per-task override block."""
    merged: dict[str, Any] = cfg.model_dump(exclude={"tasks", "max_concurrency"})
    if task:
        merged.update(cfg.tasks.get(task, {}))
    return merged


def get_chat_model(task: str | None = None, cfg: LLMConfig | None = None) -> BaseChatModel:
    cfg = cfg or get_settings().llm
    params = resolve_task_config(cfg, task)
    provider, model = split_model_spec(params.pop("model"))

    if provider != "ollama":
        params = {k: v for k, v in params.items() if k not in _OLLAMA_ONLY}
        if provider == "openai" and (key := get_settings().secrets.openai_api_key):
            params["api_key"] = key

    params = {k: v for k, v in params.items() if v is not None}
    return init_chat_model(model, model_provider=provider, **params)
