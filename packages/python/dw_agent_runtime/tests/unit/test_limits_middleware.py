"""`LimitsMiddleware` at the agent loop's model call (usage-and-limits R5.2,
R5.5, R5.11): the call is sent with the permit's `max_tokens`, its usage is
recorded keyed by the permit, and the invocation's usage meter does not record
the same tokens a second time; a refused call never reaches the model."""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import Field
from test_agent_factory import PROFILE_ID, _models
from test_langchain_tools import make_run_context

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.langchain_usage import LangchainUsageMeter
from dw_agent_runtime.adapters.limits_middleware import LimitsMiddleware
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_kernel.limits import LimitExceededError

pytestmark = pytest.mark.unit


class _Recording(MockChatModel):
    """Keeps the keyword arguments of every call: what the provider is sent."""

    sent: list[dict[str, Any]] = Field(default_factory=list)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        self.sent.append(dict(kw))
        return super()._generate(messages, stop, run_manager, **kw)


def _agent(model: MockChatModel, limits: OpenLimits, recorder: InMemoryUsageRecorder) -> Any:
    return create_agent(
        model=model,
        tools=[],
        middleware=[LimitsMiddleware(limits, _models(), PROFILE_ID, FlatPricing(), recorder)],
        context_schema=RunContext,
    )


async def test_the_call_carries_the_permits_max_tokens_and_is_recorded_once() -> None:
    model = _Recording(responses=[AIMessage(content="xong")], mock_reply="x")
    limits, recorder = OpenLimits(max_output_tokens=42), InMemoryUsageRecorder()
    meter = LangchainUsageMeter(models=_models(), recorder=recorder, pricing=FlatPricing())
    run = make_run_context()

    async with meter.track(
        run, profile_id=PROFILE_ID, task="agent_loop", prompt_id="p", prompt_version="1.0.0"
    ) as callbacks:
        await _agent(model, limits, recorder).ainvoke(
            {"messages": [HumanMessage("chào")]},
            RunnableConfig(callbacks=list(callbacks)),
            context=run,
        )

    assert model.sent[0]["max_tokens"] == 42
    # One record, the middleware's, keyed by its permit: the meter claimed
    # nothing left to record (R5.11, no second row for the same tokens).
    ((_, usage),) = recorder.records
    assert usage.permit == limits.permits[0]
    assert usage.input_tokens > 0


async def test_a_refused_call_never_reaches_the_model() -> None:
    model = _Recording(responses=[AIMessage(content="xong")], mock_reply="x")
    limits = OpenLimits(
        refuse_calls=LimitExceededError("spent", metric="cost_usd", scope_type="run")
    )
    recorder = InMemoryUsageRecorder()

    with pytest.raises(LimitExceededError):
        await _agent(model, limits, recorder).ainvoke(
            {"messages": [HumanMessage("chào")]}, context=make_run_context()
        )

    assert model.sent == []
    assert recorder.records == []
