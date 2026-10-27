import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from fakes import NOW, FakeAuditRepo, FakeExecutionStore, FakeUoWFactory
from pydantic import BaseModel

from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import (
    ApprovalRequiredError,
    DomainError,
    IdempotencyConflictError,
    InfrastructureError,
    PermissionDeniedError,
)
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_observability.metrics import DW_TOOL_CALL_TOTAL
from dw_observability.semconv import contract_violations, load_snapshot, snapshot_path
from dw_observability.telemetry import RecordingTelemetry

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


class EchoInput(BaseModel):
    message: str


class EchoOutput(BaseModel):
    echoed: str


def make_definition(**overrides: object) -> ToolDefinition:
    defaults: dict[str, object] = {
        "name": "test.echo",
        "version": "1.0.0",
        "description": "Echo",
        "input_schema_ref": "contracts/tools/test.echo/input.json",
        "output_schema_ref": "contracts/tools/test.echo/output.json",
        "required_scopes": frozenset({"demo.write"}),
        "side_effect_level": "external",
        "approval_policy": "conditional",
        "timeout_seconds": 2,
        "max_retries": 2,
        "idempotent": True,
        "data_classification": frozenset({"internal"}),
    }
    defaults.update(overrides)
    return ToolDefinition(**defaults)


def make_run_context(scopes: frozenset[str] = frozenset({"demo.write"})) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="demo_approval",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=scopes,
        trace_id="trace-1",
        # A4, stated: it is exactly the old approval rule (`always` or `critical`)
        # these tests were written against. Left unset, the policy fails closed and
        # every call here would stop for approval — which is what it did, and is
        # the proof that the closed default is real.
        autonomy_level="A4",
        autonomy_ceiling="A4",
    )


def make_executor(
    handler: Any, definition: ToolDefinition | None = None
) -> tuple[ToolExecutor, FakeExecutionStore, FakeAuditRepo]:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=definition or make_definition(),
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=handler,
        )
    )
    store = FakeExecutionStore()
    uow_factory = FakeUoWFactory()

    async def no_sleep(_: float) -> None: ...

    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=uow_factory,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        sleep=no_sleep,
    )
    return executor, store, uow_factory.audit_repo


async def echo_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
    return EchoOutput(echoed=payload.message)


async def test_happy_path_returns_typed_output_and_audits() -> None:
    executor, store, audit = make_executor(echo_handler)
    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "xin chào"},
        run_context=make_run_context(),
        idempotency_key="k1",
    )
    assert isinstance(output, EchoOutput) and output.echoed == "xin chào"
    assert store.records[-1]["status"] == "succeeded"
    assert [e.action for e in audit.events] == ["tool.executed"]
    assert audit.events[0].policy_decision == "allow"


async def test_missing_scope_denied_and_audited() -> None:
    executor, _, audit = make_executor(echo_handler)
    with pytest.raises(PermissionDeniedError, match="scopes"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(scopes=frozenset({"demo.read"})),
            idempotency_key="k1",
        )
    assert [e.action for e in audit.events] == ["tool.denied"]
    assert audit.events[0].policy_decision == "deny_missing_scope"


async def test_critical_tool_requires_approval() -> None:
    definition = make_definition(side_effect_level="critical")
    executor, _, _audit = make_executor(echo_handler, definition)
    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k1",
        )
    # With explicit approval it executes.
    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "x"},
        run_context=make_run_context(),
        idempotency_key="k1",
        approved=True,
    )
    assert isinstance(output, EchoOutput)


# The executor is the last gate: the place the tool actually runs. On the agent
# path the tool wrapper asks first, so a test through the agent cannot tell
# whether this gate still holds — measured: reverting it to decide from the tool
# alone left every agent-level test green. These call it directly, the way any
# caller that does not come through the wrapper would.


async def test_the_executor_refuses_a_call_its_run_is_not_autonomous_enough_for() -> None:
    """External and idempotent: asks at A1, runs at A3. The same rule as the wrapper,
    enforced again where the write happens rather than trusted to upstream."""
    definition = make_definition(side_effect_level="external", idempotent=True)
    executor, _, audit = make_executor(echo_handler, definition)

    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context().model_copy(update={"autonomy_level": "A1"}),
            idempotency_key="k1",
        )
    # Says what decided it, so "why did this pause" does not need the code.
    [refused] = [e for e in audit.events if e.action == "tool.approval_required"]
    assert refused.details["autonomy_level"] == "A1"

    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "x"},
        run_context=make_run_context().model_copy(update={"autonomy_level": "A3"}),
        idempotency_key="k2",
    )
    assert isinstance(output, EchoOutput)


async def test_the_executor_fails_closed_for_a_run_with_no_resolved_level() -> None:
    definition = make_definition(side_effect_level="none")
    executor, _, _audit = make_executor(echo_handler, definition)

    with pytest.raises(ApprovalRequiredError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context().model_copy(update={"autonomy_level": None}),
            idempotency_key="k1",
        )


async def test_side_effect_requires_idempotency_key() -> None:
    executor, _, _ = make_executor(echo_handler)
    with pytest.raises(DomainError, match="idempotency"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
        )


async def test_replay_returns_cached_output_without_reexecution() -> None:
    calls = 0

    async def counting_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal calls
        calls += 1
        return EchoOutput(echoed=payload.message)

    executor, _, audit = make_executor(counting_handler)
    context = make_run_context()
    first = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "a"},
        run_context=context,
        idempotency_key="same-key",
    )
    second = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "a"},
        run_context=context,
        idempotency_key="same-key",
    )
    assert calls == 1, "second call must be a replay, not a re-execution"
    assert first == second
    assert audit.events[-1].action == "tool.replayed"


async def test_same_key_different_payload_conflicts() -> None:
    executor, _, _ = make_executor(echo_handler)
    context = make_run_context()
    await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "a"},
        run_context=context,
        idempotency_key="key",
    )
    with pytest.raises(IdempotencyConflictError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "DIFFERENT"},
            run_context=context,
            idempotency_key="key",
        )


async def test_invalid_input_rejected_before_execution() -> None:
    executor, store, _ = make_executor(echo_handler)
    with pytest.raises(DomainError, match="input"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"wrong": 1},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    assert store.records == []


async def test_transient_failure_retries_then_succeeds() -> None:
    attempts = 0

    async def flaky_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise InfrastructureError("upstream blip")
        return EchoOutput(echoed=payload.message)

    executor, store, _ = make_executor(flaky_handler)
    output = await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "ok"},
        run_context=make_run_context(),
        idempotency_key="k",
    )
    assert isinstance(output, EchoOutput)
    assert attempts == 3
    assert store.records[-1]["attempts"] == 3


async def test_timeout_is_bounded_and_recorded_as_failure() -> None:
    async def hanging_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        await asyncio.sleep(60)
        return EchoOutput(echoed="never")

    definition = make_definition(timeout_seconds=1, max_retries=0)
    executor, store, audit = make_executor(hanging_handler, definition)
    with pytest.raises(InfrastructureError, match="failed"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    assert store.records[-1]["status"] == "failed"
    assert audit.events[-1].action == "tool.failed"


async def test_a_crashing_handler_is_recorded_like_any_other_failure() -> None:
    """A tool with a plain bug used to leave no trace at all.

    The retry loop caught only the four typed families, so a `TypeError` from a
    handler escaped `_execute` before it reached the record and the audit -
    making a crash the one failure with no execution row, no `tool.failed` and
    no attempt count, which is the opposite of what those exist for.
    """

    async def crashing_handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        raise TypeError("a real bug, not a refusal")

    executor, store, audit = make_executor(crashing_handler, make_definition(max_retries=2))
    with pytest.raises(InfrastructureError, match="failed"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    assert store.records[-1]["status"] == "failed"
    assert store.records[-1]["error"] == "TypeError"
    # Not retried: re-running a bug repeats it, and would double whatever the
    # handler managed to do before raising.
    assert store.records[-1]["attempts"] == 1
    assert audit.events[-1].action == "tool.failed"


async def test_output_schema_violation_is_domain_error() -> None:
    async def bad_output_handler(payload: EchoInput, run_context: RunContext) -> dict[str, bool]:
        return {"unexpected": True}

    executor, _, _ = make_executor(bad_output_handler)
    with pytest.raises(DomainError, match="output"):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k",
        )


async def test_tool_call_emits_span_with_names_and_no_payload() -> None:
    telemetry = RecordingTelemetry()
    executor, _, _ = make_executor(echo_handler)
    executor.telemetry = telemetry

    await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": "bí mật của khách hàng"},
        run_context=make_run_context(),
        idempotency_key="k",
    )

    assert [name for name, _ in telemetry.spans] == ["execute_tool test.echo"]
    assert telemetry.metrics == [(DW_TOOL_CALL_TOTAL, 1, {"tool": "test.echo", "status": "ok"})]
    _, attributes = telemetry.spans[0]
    assert attributes["dw.tool_name"] == "test.echo"
    assert attributes["dw.tool_version"] == "1.0.0"
    assert attributes["gen_ai.operation.name"] == "execute_tool"
    # Nội dung không được rời khỏi tiến trình — span chỉ mang tên và số đếm.
    assert "bí mật của khách hàng" not in str(attributes)
    # Every name it emitted is in the pinned GenAI snapshot (spec R1.1).
    assert contract_violations(load_snapshot(snapshot_path(REPO_ROOT)), telemetry) == []


async def test_failed_tool_still_emits_its_span() -> None:
    async def boom(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        raise InfrastructureError("provider down")

    telemetry = RecordingTelemetry()
    executor, _, _ = make_executor(boom)
    executor.telemetry = telemetry
    with pytest.raises(InfrastructureError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    assert [name for name, _ in telemetry.spans] == ["execute_tool test.echo"]
    assert telemetry.metrics == [(DW_TOOL_CALL_TOTAL, 1, {"tool": "test.echo", "status": "error"})]
    assert contract_violations(load_snapshot(snapshot_path(REPO_ROOT)), telemetry) == []
