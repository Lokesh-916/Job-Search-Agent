import asyncio

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from job_agent import metrics


def reply(out_tokens: int) -> AIMessage:
    return AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 700, "output_tokens": out_tokens,
                        "total_tokens": 700 + out_tokens},
        response_metadata={"eval_duration": 2e9, "load_duration": 5e8},
    )  # fmt: skip


def test_calls_are_tagged_by_stage_and_summarised():
    m = metrics.RunMetrics()
    token = metrics.activate(m)
    try:
        llm = FakeMessagesListChatModel(responses=[reply(100), reply(60)])
        asyncio.run(llm.ainvoke([HumanMessage("a")], config=metrics.llm_config("triage")))
        asyncio.run(llm.ainvoke([HumanMessage("b")], config=metrics.llm_config("assess")))
        metrics.event("repair")
        with metrics.StageTimer("triage"):
            pass
    finally:
        metrics._current.reset(token)

    s = m.summary()
    assert s["llm"]["triage"]["calls"] == 1 and s["llm"]["triage"]["output_tokens"] == 100
    assert s["llm"]["triage"]["tokens_per_s"] == 50.0  # 100 tokens / 2 s
    assert s["llm"]["assess"]["load_s"] == 0.5
    assert s["events"] == {"repair": 1} and "triage" in s["stage_seconds"]
    [(name, start, end)] = s["stage_spans"]
    assert name == "triage" and 0 <= start <= end
    assert all(c.started >= 0 for c in m.calls)  # run-relative offsets
    assert any(k == "🤖 triage" for k, _ in m.log_lines())


def test_no_active_metrics_is_harmless():
    assert metrics.llm_config("x") == {"metadata": {"stage": "x"}, "callbacks": []}
    metrics.event("ignored")
