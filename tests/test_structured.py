import asyncio

import pytest
from langchain_core.messages import HumanMessage

from job_agent.schemas import Triage
from job_agent.structured import StructuredOutputError, abatch_structured, ainvoke_structured
from tests.fakes import FakeStructuredLLM

GOOD = {"category": "backend", "keep": True, "reason": "Python APIs, new grads ok"}


def test_valid_first_try():
    llm = FakeStructuredLLM(lambda m: GOOD)
    out = asyncio.run(ainvoke_structured(llm, Triage, [HumanMessage("job")]))
    assert out.keep and len(llm.calls) == 1


def test_repairs_once_with_error_feedback():
    replies = iter(['{"category": "chef", "keep": true, "reason": "x"}', GOOD])
    llm = FakeStructuredLLM(lambda m: next(replies))
    out = asyncio.run(ainvoke_structured(llm, Triage, [HumanMessage("job")]))
    assert out.category == "backend"
    assert "did not match the schema" in llm.calls[1][-1].content


def test_gives_up_after_repair():
    llm = FakeStructuredLLM(lambda m: "not json")
    with pytest.raises(StructuredOutputError):
        asyncio.run(ainvoke_structured(llm, Triage, [HumanMessage("job")]))


def test_batch_isolates_failures():
    llm = FakeStructuredLLM(lambda m: GOOD if m[-1].content == "ok" else "bad")
    out = asyncio.run(
        abatch_structured(llm, Triage, {"a": [HumanMessage("ok")], "b": [HumanMessage("no")]})
    )
    assert isinstance(out["a"], Triage)
    assert isinstance(out["b"], StructuredOutputError)
