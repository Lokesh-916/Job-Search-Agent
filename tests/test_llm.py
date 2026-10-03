import pytest

from job_agent.llm import get_chat_model, resolve_task_config, split_model_spec
from job_agent.settings import LLMConfig


def test_split_model_spec_keeps_tag():
    assert split_model_spec("ollama:qwen3:14b") == ("ollama", "qwen3:14b")


def test_split_model_spec_rejects_bare_name():
    with pytest.raises(ValueError):
        split_model_spec("qwen3")


def test_task_override_wins():
    cfg = LLMConfig(num_ctx=16384, tasks={"research": {"num_ctx": 32768, "reasoning": True}})
    merged = resolve_task_config(cfg, "research")
    assert merged["num_ctx"] == 32768
    assert merged["reasoning"] is True
    assert resolve_task_config(cfg, "extract")["num_ctx"] == 16384


def test_builds_ollama_model_without_contacting_server():
    cfg = LLMConfig(model="ollama:qwen3:14b", tasks={"extract": {"reasoning": False}})
    model = get_chat_model("extract", cfg)
    assert model.model == "qwen3:14b"
    assert model.reasoning is False
