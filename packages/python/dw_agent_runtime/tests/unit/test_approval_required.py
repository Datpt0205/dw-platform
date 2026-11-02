"""One answer to "does this call wait for a person" (tools-and-skills ticket 01:
R2.5; TS5; ADR-0116 decision 3, amended 2026-11-02).

`ToolExecutor.approval_required` is asked by the agent's tool wrapper, by
`OneApprovalPerStepMiddleware` and by the executor's own approval step. The
spy below answers `True` where the autonomy policy would not ask: a gate that
still read the policy (or the run mode) itself would not ask either.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from test_agent_factory import THREAD
from test_autonomy_in_agent import QUOTE, _at, _calls_quote, _spec
from test_executor import echo_handler, make_definition, make_executor, make_run_context

from dw_agent_runtime.adapters.agent_factory import build_agent
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_kernel.errors import ApprovalRequiredError

pytestmark = pytest.mark.unit


class Spy:
    """Answers `answer` and records which function asked."""

    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.askers: list[str] = []

    def __call__(self, definition: ToolDefinition, run_context: RunContext) -> bool:
        self.askers.append(sys._getframe(1).f_code.co_name)
        return self.answer


def spied(executor: ToolExecutor, answer: bool) -> Spy:
    spy = Spy(answer)
    executor.approval_required = spy  # type: ignore[method-assign]
    return spy


async def test_the_executor_refuses_an_unapproved_call_without_the_wrapper() -> None:
    """R2.5 (TS5): called directly, `approved=False`, a tool that needs a
    person: `approval_required`, and the handler does not run."""
    ran: list[str] = []

    async def handler(payload: Any, run_context: RunContext) -> Any:
        ran.append("ran")
        return await echo_handler(payload, run_context)

    executor, store, _ = make_executor(handler, make_definition(side_effect_level="critical"))
    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k1",
            approved=False,
        )
    assert ran == [] and store.records == []


async def test_the_executors_approval_step_asks_the_one_question() -> None:
    """R2.5: a tool the policy lets through at A4 waits when the one answer
    says so."""
    executor, _, _ = make_executor(echo_handler, make_definition(side_effect_level="internal"))
    spy = spied(executor, True)
    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k1",
        )
    assert spy.askers == ["step_approval"]


async def test_the_wrapper_asks_the_executor_for_each_call() -> None:
    """R2.5 (TS5): at A3 the policy runs this write unasked; the one answer
    says wait, and the wrapper pauses the run."""
    spec = _spec(_calls_quote())
    spy = spied(spec.executor, True)
    result = await build_agent(spec, checkpointer=InMemorySaver()).ainvoke(
        {"messages": [HumanMessage("lưu báo giá")]}, THREAD, context=_at("A3")
    )
    assert "__interrupt__" in result
    assert "call" in spy.askers  # the tool wrapper's coroutine
    assert spec.executor.approval_policy.decide(QUOTE, _at("A3")) is False


async def test_the_middleware_asks_the_executor_for_each_call() -> None:
    """R2.5 (TS5): two sibling calls the one answer gates: the middleware
    lets the first ask and defers the second, so one card, not two. A
    middleware reading the policy itself would gate nothing at A3, and both
    calls would pause."""
    spec = _spec(_calls_quote("q2"))
    spy = spied(spec.executor, True)
    result = await build_agent(spec, checkpointer=InMemorySaver()).ainvoke(
        {"messages": [HumanMessage("lưu hai báo giá")]}, THREAD, context=_at("A3")
    )
    assert len(result.get("__interrupt__", ())) == 1
    assert "awrap_tool_call" in spy.askers


async def test_a_call_the_one_answer_lets_through_runs_unasked() -> None:
    """The other side: the answer is `False`, at A1 where the policy would
    ask, and no gate pauses."""
    spec = _spec(_calls_quote("q2"))
    spied(spec.executor, False)
    result = await build_agent(spec, checkpointer=InMemorySaver()).ainvoke(
        {"messages": [HumanMessage("lưu hai báo giá")]}, THREAD, context=_at("A1")
    )
    assert "__interrupt__" not in result
