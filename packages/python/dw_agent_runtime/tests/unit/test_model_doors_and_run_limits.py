"""usage-and-limits/04, runtime half: every model door the runtime hands out
refuses a call no lease permits (R6.1, R6.2; UL4), a run's behavioural limits
are its version's clamped by the plan (R6.4), and an operation outside any run
holds a lease of its own (R6.2; gate 4/11/2026 (a)).

Each door is called directly, never through the layer that would have refused
first (failure-modes #5): the chat model with no middleware around it, the
structured gateway with no runner around it.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from test_agent_factory import PROFILE_ID, _models
from test_langchain_tools import make_run_context
from test_single_call_gateway import _REQUEST, Answer, _answering, _gateway, _run_context

from dw_agent_runtime.adapters.chat_model import (
    LimitedChatModelFactory,
    MockChatModel,
    MockChatModelFactory,
    PermitRequired,
)
from dw_agent_runtime.adapters.limits_middleware import LimitsMiddleware
from dw_agent_runtime.contracts import DeclaredLimits, RunContext
from dw_agent_runtime.leases import beating, held_operation, run_holder
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder
from dw_agent_runtime.model.limits import clamp_run_limits, permit_in_force
from dw_agent_runtime.model.single_call import SingleCallModelGateway
from dw_agent_runtime.ports import RunLimits
from dw_agent_runtime.testing.limits import TEST_CEILING, OpenLimits
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_kernel.limits import (
    BEHAVIOUR_METRICS,
    NO_LEASE,
    PERIOD_METRICS,
    LimitExceededError,
    LimitMetric,
    lease_in_force,
)

pytestmark = pytest.mark.unit

_SPENT = LimitExceededError("spent", metric="cost_usd", scope_type="tenant", window="month")


# ---- one table of metric names (step 2) --------------------------------------


def test_every_limit_exceeded_names_its_metric_from_one_table() -> None:
    from typing import get_args

    assert set(get_args(LimitMetric)) == {*PERIOD_METRICS, *BEHAVIOUR_METRICS}
    assert set(BEHAVIOUR_METRICS) == {"steps", "model_calls", "tool_calls"}
    assert set(PERIOD_METRICS) == {"cost_usd", "tokens", "runs"}


# ---- R6.4: the version's limits, clamped by the plan --------------------------


_CEILING = RunLimits(
    max_steps=50,
    max_model_calls=50,
    max_tool_calls=200,
    max_cost_usd=Decimal("2.0"),
    max_tokens=200_000,
)


def test_a_value_above_the_plans_ceiling_is_clamped_to_it() -> None:
    declared = DeclaredLimits(
        max_steps=400,
        max_model_calls=90,
        max_tool_calls=900,
        max_cost_usd=Decimal("9"),
        max_tokens=10**6,
    )
    assert clamp_run_limits(declared, _CEILING) == _CEILING


def test_a_field_the_version_does_not_declare_is_the_plans() -> None:
    limits = clamp_run_limits(DeclaredLimits(max_tool_calls=10), _CEILING)
    assert limits.max_steps == _CEILING.max_steps
    assert limits.max_tool_calls == 10
    assert limits.max_cost_usd == _CEILING.max_cost_usd


def test_a_value_below_the_ceiling_is_kept() -> None:
    declared = DeclaredLimits(max_steps=7, max_cost_usd=Decimal("0.5"))
    limits = clamp_run_limits(declared, _CEILING)
    assert (limits.max_steps, limits.max_cost_usd) == (7, Decimal("0.5"))


async def test_admit_and_resume_hand_back_the_runs_limits_clamped_by_the_plan_now() -> None:
    """R6.4: computed at each `admit` and `resume`, so a plan lowered while the
    run waits binds its resume."""
    limits = OpenLimits()
    run = make_run_context().model_copy(update={"declared_limits": DeclaredLimits(max_steps=45)})

    admitted = await limits.admit(run)
    limits.ceiling = RunLimits(
        max_steps=20,
        max_model_calls=10,
        max_tool_calls=10,
        max_cost_usd=Decimal("1"),
        max_tokens=1_000,
    )
    resumed = await limits.resume(run)

    assert admitted.run_limits is not None and admitted.run_limits.max_steps == 40
    assert TEST_CEILING.max_steps == 40
    assert resumed.run_limits is not None and resumed.run_limits.max_steps == 20


# ---- R6.1, R6.2: the chat model refuses a call no lease permitted -------------


def _limited(script: list[AIMessage] | None = None) -> MockChatModel:
    inner = MockChatModelFactory(mock_reply="x", scripts={"p": script or [AIMessage("xong")]})
    model = LimitedChatModelFactory(inner).resolve("p")
    assert isinstance(model, MockChatModel)
    return model


async def test_a_chat_model_called_directly_is_refused_before_it_is_sent() -> None:
    model = _limited()

    with pytest.raises(LimitExceededError) as refused:
        await model.ainvoke([HumanMessage("chào")])

    assert refused.value.details["reason"] == NO_LEASE
    assert model.calls == []


def test_a_bound_or_synchronous_call_is_refused_the_same_way() -> None:
    model = _limited()
    with pytest.raises(LimitExceededError):
        model.bind_tools([]).invoke([HumanMessage("chào")])
    assert model.calls == []


def test_the_guard_keeps_the_models_own_callbacks() -> None:
    class _Own(BaseCallbackHandler):
        pass

    own = _Own()

    class _Factory:
        def resolve(self, profile_id: str) -> Any:
            return MockChatModel(responses=[], mock_reply="x", callbacks=[own])

    model = LimitedChatModelFactory(_Factory()).resolve("p")
    assert isinstance(model.callbacks, list)
    assert model.callbacks[0] is own
    assert isinstance(model.callbacks[-1], PermitRequired)


async def test_the_agent_loop_sends_a_limited_model_under_its_permit() -> None:
    """Through `LimitsMiddleware` the call is permitted, and the permit is in
    force for that call only. Without `permitted` in the middleware this is
    refused like a direct call."""
    model = _limited()
    limits = OpenLimits()
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[
            LimitsMiddleware(limits, _models(), PROFILE_ID, FlatPricing(), InMemoryUsageRecorder())
        ],
        context_schema=RunContext,
    )

    answer = await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert answer["messages"][-1].content == "xong"
    assert len(model.calls) == 1
    assert len(limits.permits) == 1
    assert permit_in_force() is None


async def test_a_spent_lease_stops_the_agent_loop_before_the_limited_model() -> None:
    model = _limited()
    limits = OpenLimits(refuse_calls=_SPENT)
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[
            LimitsMiddleware(limits, _models(), PROFILE_ID, FlatPricing(), InMemoryUsageRecorder())
        ],
        context_schema=RunContext,
    )

    with pytest.raises(LimitExceededError):
        await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert model.calls == []


# ---- R6.2: the structured door, called directly ------------------------------


async def test_the_structured_gateway_called_directly_on_a_spent_lease_sends_nothing() -> None:
    adapter = _answering({"answer": "ok"})
    limits = OpenLimits(refuse_calls=_SPENT)
    gateway, recorder = _gateway(adapter, limits)

    with pytest.raises(LimitExceededError):
        await gateway.generate_structured(_REQUEST, Answer, run_context=_run_context())

    assert adapter.asked == []
    assert recorder.records == []


async def test_a_call_outside_any_run_on_a_spent_period_is_refused_at_its_operation() -> None:
    adapter = _answering({"answer": "ok"})
    limits = OpenLimits(refuse=_SPENT)
    gateway, _recorder = _gateway(adapter, limits)

    with pytest.raises(LimitExceededError):
        await SingleCallModelGateway(inner=gateway, limits=limits).generate_structured(
            _REQUEST, Answer, run_context=_run_context()
        )

    assert adapter.asked == []
    assert limits.operations == []


# ---- R6.2: an operation's lease -----------------------------------------------


_TENANT, _WORKSPACE, _ACTOR = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


async def test_an_operations_lease_is_in_force_for_its_block_and_released_completed() -> None:
    limits = OpenLimits()
    operation = uuid.uuid4()

    async with held_operation(
        limits,
        tenant_id=_TENANT,
        workspace_id=_WORKSPACE,
        purpose="retrieval",
        operation_id=operation,
        actor_id=_ACTOR,
    ):
        held = lease_in_force()

    assert held is not None
    assert (held.tenant_id, held.lease_root, held.run_id) == (_TENANT, operation, None)
    assert (held.purpose, held.actor_id, held.actor_kind) == ("retrieval", _ACTOR, "user")
    assert limits.operations == [(operation, "retrieval")]
    assert limits.released == [(operation, "completed")]
    assert lease_in_force() is None


async def test_an_operation_that_fails_gives_its_lease_back_failed() -> None:
    limits = OpenLimits()
    operation = uuid.uuid4()

    with pytest.raises(RuntimeError):
        async with held_operation(
            limits,
            tenant_id=_TENANT,
            workspace_id=_WORKSPACE,
            purpose="ingestion",
            operation_id=operation,
            actor_id=_ACTOR,
        ):
            raise RuntimeError("the provider failed")

    assert limits.released == [(operation, "failed")]
    assert lease_in_force() is None


async def test_a_refused_operation_runs_nothing_and_holds_nothing() -> None:
    limits = OpenLimits(refuse=_SPENT)
    ran = False

    with pytest.raises(LimitExceededError):
        async with held_operation(
            limits,
            tenant_id=_TENANT,
            workspace_id=_WORKSPACE,
            purpose="ingestion",
            operation_id=uuid.uuid4(),
            actor_id=_ACTOR,
        ):
            ran = True

    assert ran is False
    assert limits.released == []


async def test_a_held_lease_is_beaten_while_the_work_lasts() -> None:
    limits = OpenLimits()
    lease = await limits.admit_operation(
        tenant_id=_TENANT, workspace_id=_WORKSPACE, purpose="ingestion", operation_id=uuid.uuid4()
    )

    async with beating(lease, every_seconds=0.01):
        await asyncio.sleep(0.05)
    beaten = len(limits.beats)
    await asyncio.sleep(0.03)

    assert beaten >= 2
    assert len(limits.beats) == beaten


def test_a_runs_lease_in_force_names_its_tree_and_who_ran_it() -> None:
    run = make_run_context()
    child = run.model_copy(update={"run_id": uuid.uuid4(), "root_run_id": run.run_id})

    held = run_holder(child)

    assert (held.lease_root, held.run_id, held.purpose) == (run.run_id, child.run_id, "run")
    assert (held.actor_id, held.actor_kind) == (run.actor_id, "user")
    service = child.model_copy(update={"run_as_principal_id": uuid.uuid4()})
    assert (run_holder(service).actor_id, run_holder(service).actor_kind) == (None, "service")


async def test_a_limited_summariser_compacts_under_the_summarys_own_permit() -> None:
    """Context compaction asks the lease for each summary and sends it under
    that permit; without it a limited summariser is refused, and compaction,
    which fails open, would quietly stop compacting."""
    from test_context_compaction import _compactor, _run

    summariser = LimitedChatModelFactory(
        MockChatModelFactory(mock_reply="tóm tắt", scripts={"s": [AIMessage("tóm tắt")]})
    ).resolve("s")
    assert isinstance(summariser, MockChatModel)
    middleware, _ = _compactor(summariser)

    messages = await _run(middleware, turns=8)

    assert len(summariser.calls) >= 1
    assert "h0" not in [m.id for m in messages]
