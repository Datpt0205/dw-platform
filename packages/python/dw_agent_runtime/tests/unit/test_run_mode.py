"""Run modes and the executor's interception outside `live` (tenant-config
ticket 03: R4.2, R4.4, R5.1, R5.3-R5.6; TC9, TC11).

The executor is called directly, not through a graph node (failure-modes
#5); the agent's tool wrapper has its own case, since the rule is held at
two layers (failure-modes #3).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from test_executor import (
    EchoInput,
    EchoOutput,
    make_definition,
    make_executor,
    make_run_context,
)

from dw_agent_runtime import executor as executor_module
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.samples import SampleOutput, sample_of
from dw_kernel.errors import ApprovalRequiredError, DomainError
from dw_kernel.run_mode import RunMode, child_mode

pytestmark = pytest.mark.unit


class Spy:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, payload: EchoInput, run_context: RunContext) -> EchoOutput:
        self.calls += 1
        return EchoOutput(echoed=payload.message)


def in_mode(mode: RunMode) -> RunContext:
    return make_run_context().model_copy(update={"run_mode": mode})


async def _call(executor: Any, context: RunContext, key: str | None = "k1") -> Any:
    return await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "xin chào"},
        run_context=context,
        idempotency_key=key,
    )


def test_a_context_that_names_no_mode_is_simulate() -> None:
    """R4.2 (TC9): the closed value."""
    unnamed = RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="w",
        worker_version="1.0.0",
        channel="web",
        plan_id="p",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
    )
    assert unnamed.run_mode == "simulate"
    assert make_definition().intercepted_in(unnamed.run_mode)


@pytest.mark.parametrize(
    ("parent", "requested", "child"),
    [
        ("simulate", "simulate", "simulate"),
        ("simulate", "test", "simulate"),
        ("simulate", "live", "simulate"),
        ("test", "simulate", "simulate"),
        ("test", "test", "test"),
        ("test", "live", "test"),
        ("live", "simulate", "simulate"),
        ("live", "test", "test"),
        ("live", "live", "live"),
    ],
)
def test_a_child_runs_no_looser_than_its_parent(
    parent: RunMode, requested: RunMode, child: RunMode
) -> None:
    """R4.4 (TC9): all nine pairs."""
    assert child_mode(parent, requested) == child


@pytest.mark.parametrize("mode", ["simulate", "test"])
async def test_outside_live_an_external_call_is_answered_by_a_sample(mode: RunMode) -> None:
    """R5.1, R5.2, R5.3 (TC11): the handler does not run; one `simulated`
    row carrying the sample marked `simulated`, its `tool.simulated` audit
    written with it; nothing else is audited."""
    spy = Spy()
    executor, store, audit = make_executor(spy)
    output = await _call(executor, in_mode(mode), key=None)
    assert spy.calls == 0
    assert isinstance(output, SampleOutput)
    expected = EchoOutput.model_validate(sample_of(EchoOutput.model_json_schema()))
    assert output.model_dump() == {**expected.model_dump(mode="json"), "simulated": True}
    (row,) = store.records
    assert row["status"] == "simulated" and row["output"] == output.model_dump()
    assert row["idempotency_key"] is None
    (event,) = store.audits
    assert event.action == "tool.simulated"
    assert event.details["run_mode"] == mode and event.details["reason"] == "not_simulate_safe"
    assert audit.events == []


async def test_live_runs_the_same_call() -> None:
    """G1: a `live` call runs and records `succeeded` as before."""
    spy = Spy()
    executor, store, _ = make_executor(spy)
    output = await _call(executor, in_mode("live"))
    assert spy.calls == 1 and isinstance(output, EchoOutput)
    assert store.records[-1]["status"] == "succeeded"


async def test_a_sample_that_fails_the_output_model_is_a_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R5.3: the sample is checked as a real output is."""
    monkeypatch.setattr(executor_module, "sample_of", lambda schema: {"echoed": None})
    executor, store, _ = make_executor(Spy())
    with pytest.raises(DomainError) as refused:
        await _call(executor, in_mode("simulate"))
    assert refused.value.code == "validation_failed"
    assert store.records == []


async def test_a_simulate_safe_tool_runs_outside_live() -> None:
    """R5.4."""
    spy = Spy()
    executor, store, _ = make_executor(
        spy, make_definition(side_effect_level="none", simulate_safe=True, approval_policy="never")
    )
    await _call(executor, in_mode("simulate"), key=None)
    assert spy.calls == 1 and store.records[-1]["status"] == "succeeded"


def test_a_definition_that_does_not_say_is_intercepted() -> None:
    """R5.5 (TC11)."""
    assert make_definition().simulate_safe is False
    assert make_definition().intercepted_in("test")
    assert not make_definition().intercepted_in("live")
    assert not make_definition(simulate_safe=True).intercepted_in("simulate")


async def test_a_critical_tool_opens_no_approval_outside_live() -> None:
    """R5.6 (TC11): the mode step stands before the approval step; at
    `live` the same call asks a person."""
    definition = make_definition(side_effect_level="critical", approval_policy="always")
    spy = Spy()
    executor, store, audit = make_executor(spy, definition)
    await _call(executor, in_mode("simulate"))
    assert store.records[-1]["status"] == "simulated"
    assert "tool.approval_required" not in {e.action for e in audit.events}
    with pytest.raises(ApprovalRequiredError):
        await _call(executor, in_mode("live"))
    assert spy.calls == 0
