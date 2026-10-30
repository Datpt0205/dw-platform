import asyncio
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fakes import NOW, FakeAuditRepo, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from pydantic import BaseModel

from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import (
    ApprovalRequiredError,
    ConflictError,
    DomainError,
    IdempotencyConflictError,
    InfrastructureError,
    PermissionDeniedError,
)
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_observability.metrics import DW_TOOL_CALL_TOTAL
from dw_observability.semconv import contract_violations, load_snapshot, snapshot_path
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.application.digital_workers import DwBoundary

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]

# A call that stays inside the platform: retried when idempotent, `failed` when it
# fails. An `external` call logs its dispatch and is never retried after it.
INTERNAL = "internal"


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
        claims=FakeToolClaims(store),
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

    executor, store, _ = make_executor(flaky_handler, make_definition(side_effect_level=INTERNAL))
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

    definition = make_definition(timeout_seconds=1, max_retries=0, side_effect_level=INTERNAL)
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

    executor, store, audit = make_executor(
        crashing_handler, make_definition(max_retries=2, side_effect_level=INTERNAL)
    )
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

    executor, _, _ = make_executor(bad_output_handler, make_definition(side_effect_level=INTERNAL))
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
    executor, _, _ = make_executor(boom, make_definition(side_effect_level=INTERNAL))
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


# ---- claims and the dispatch log (runtime-hardening R6; ADR-0108 decision 5) ----


def _statuses(store: FakeExecutionStore) -> list[str]:
    return [row["status"] for row in store.records]


async def _call(executor: ToolExecutor, message: str = "x", key: str = "k") -> BaseModel:
    return await executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"message": message},
        run_context=make_run_context(),
        idempotency_key=key,
    )


async def test_an_external_call_logs_its_dispatch_then_its_outcome() -> None:
    executor, store, _ = make_executor(echo_handler)
    await _call(executor)
    dispatched, finished = store.records
    assert _statuses(store) == ["dispatched", "succeeded"]
    assert finished["dispatch_id"] == dispatched["execution_id"]


async def test_an_internal_call_logs_no_dispatch() -> None:
    executor, store, _ = make_executor(echo_handler, make_definition(side_effect_level=INTERNAL))
    await _call(executor)
    assert _statuses(store) == ["succeeded"]
    assert store.records[0]["dispatch_id"] is None


async def test_a_live_claim_turns_a_second_call_into_a_conflict() -> None:
    """R6.1: while the first call holds the key, the second does not run."""
    calls = 0
    release = asyncio.Event()

    async def slow(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal calls
        calls += 1
        await release.wait()
        return EchoOutput(echoed=payload.message)

    executor, _, _ = make_executor(slow)
    first = asyncio.create_task(_call(executor))
    await asyncio.sleep(0)
    with pytest.raises(ConflictError):
        await _call(executor)
    release.set()
    await first
    assert calls == 1
    assert await _call(executor) == EchoOutput(echoed="x"), "after success: replay"
    assert calls == 1


@pytest.mark.parametrize(
    ("raised", "status", "error"),
    [
        (NotDispatchedError("no byte left"), "failed", "not_dispatched"),
        (
            RejectedError("refused", provider_code="550 Bearer abcdefghijk"),
            "failed",
            "rejected:550 Bearer [REDACTED]",
        ),
        (OutcomeUnknownError("reset after DATA"), "outcome_unknown", "outcome_unknown"),
        (TypeError("untyped"), "outcome_unknown", "outcome_unknown"),
        (InfrastructureError("upstream"), "outcome_unknown", "outcome_unknown"),
    ],
)
async def test_each_send_ends_in_one_row_its_typed_result_decides(
    raised: Exception, status: str, error: str
) -> None:
    """R6.12: only a typed "nothing applied" is `failed`; anything else after the
    send may have been applied, so it is `outcome_unknown` and never retried."""
    calls = 0

    async def handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal calls
        calls += 1
        raise raised

    executor, store, audit = make_executor(handler)
    expected = OutcomeUnknownError if status == "outcome_unknown" else type(raised)
    with pytest.raises(expected):
        await _call(executor)
    assert calls == 1, "a call that left is never retried by the executor"
    dispatched, finished = store.records
    assert (finished["status"], finished["error"]) == (status, error)
    assert finished["dispatch_id"] == dispatched["execution_id"]
    assert audit.events[-1].action == "tool.failed"


async def test_a_timeout_after_the_send_is_unknown_not_failed() -> None:
    """R6.12, case T: the provider applied the call and the answer never came."""

    async def hanging(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        await asyncio.sleep(60)
        return EchoOutput(echoed="never")

    executor, store, _ = make_executor(hanging, make_definition(timeout_seconds=1))
    with pytest.raises(OutcomeUnknownError):
        await _call(executor)
    assert _statuses(store) == ["dispatched", "outcome_unknown"]


async def test_a_send_with_no_known_outcome_is_never_made_again() -> None:
    """R6.9: neither a new claim nor a takeover runs the handler again."""
    calls = 0

    async def flaky(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal calls
        calls += 1
        raise OutcomeUnknownError("reset")

    executor, store, audit = make_executor(flaky)
    with pytest.raises(OutcomeUnknownError):
        await _call(executor)
    with pytest.raises(OutcomeUnknownError):
        await _call(executor)
    assert calls == 1
    assert audit.events[-1].details["reason"] == "unresolved_dispatch"
    assert _statuses(store) == ["dispatched", "outcome_unknown"]


async def test_a_failed_send_may_be_made_again_under_a_new_claim() -> None:
    """R6.10: every earlier send of the key has a known outcome, so the next runs."""
    outcomes: list[Exception | None] = [NotDispatchedError("refused locally"), None]

    async def handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return EchoOutput(echoed=payload.message)

    executor, store, _ = make_executor(handler)
    with pytest.raises(NotDispatchedError):
        await _call(executor)
    assert await _call(executor) == EchoOutput(echoed="x")
    assert _statuses(store) == ["dispatched", "failed", "dispatched", "succeeded"]


async def test_a_holder_taken_over_before_its_dispatch_does_not_send() -> None:
    """R6.13: the dispatch row is fenced by the caller's own live claim."""
    calls = 0

    async def handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        nonlocal calls
        calls += 1
        return EchoOutput(echoed=payload.message)

    executor, store, _ = make_executor(handler)
    claims = executor.claims
    assert isinstance(claims, FakeToolClaims)
    original_dispatch = claims.dispatch

    async def stall_then_dispatch(*args: Any, **kwargs: Any) -> bool:
        # The old holder stalls past `expires_at`; a new one takes over and sends.
        claims.now = claims.now + timedelta(hours=1)
        claims.dispatch = original_dispatch  # type: ignore[method-assign]
        await _call(executor)
        return await original_dispatch(*args, **kwargs)

    claims.dispatch = stall_then_dispatch  # type: ignore[method-assign]
    with pytest.raises(ConflictError):
        await _call(executor)
    assert calls == 1
    assert _statuses(store) == ["dispatched", "succeeded"]


async def test_a_second_success_refused_by_the_index_replays_the_first() -> None:
    """Step 5 of the ticket: the unique index is the backstop behind the claim."""
    executor, store, audit = make_executor(echo_handler)
    first = await _call(executor)
    earlier = store.succeeded[("test.echo", "k")]
    store.succeeded.clear()  # the claim's lookup misses; the index still holds it
    original_record = store.record

    async def index_answers(run_context: Any, **kwargs: Any) -> Any:
        if kwargs["status"] == "succeeded":
            store.succeeded[("test.echo", "k")] = earlier
        return await original_record(run_context, **kwargs)

    store.record = index_answers  # type: ignore[method-assign]
    assert await _call(executor) == first
    assert audit.events[-1].action == "tool.replayed"


async def test_a_secret_in_a_list_is_redacted_in_the_failure_audit() -> None:
    """R6.5: `tool.failed` carries the input, masked at any depth."""

    class ItemsInput(BaseModel):
        items: list[dict[str, str]]

    async def boom(payload: BaseModel, run_context: RunContext) -> EchoOutput:
        raise NotDispatchedError("refused")

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=make_definition(),
            input_model=ItemsInput,
            output_model=EchoOutput,
            handler=boom,
        )
    )
    store = FakeExecutionStore()
    uow_factory = FakeUoWFactory()
    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=uow_factory,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
    )
    with pytest.raises(NotDispatchedError):
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"items": [{"api_key": "sk-123"}]},
            run_context=make_run_context(),
            idempotency_key="k",
        )
    failed = uow_factory.audit_repo.events[-1]
    assert failed.action == "tool.failed"
    assert failed.details["input"] == {"items": [{"api_key": "[REDACTED]"}]}


# ------------------------------------------- digital-worker R6.1-R6.3 --


class _Boundary:
    """Answers one DW boundary, or raises when told the state is unreadable."""

    def __init__(self, boundary: DwBoundary | None, *, fails: bool = False) -> None:
        self.found = boundary
        self.fails = fails

    async def boundary(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, principal_id: uuid.UUID
    ) -> DwBoundary | None:
        if self.fails:
            raise InfrastructureError("database unavailable")
        return self.found


OPERATING = DwBoundary(
    operating=True, allowed_tools=frozenset({"test.echo"}), scopes=frozenset({"demo.write"})
)


def _dw_run() -> RunContext:
    principal = uuid.uuid4()
    return make_run_context().model_copy(
        update={"actor_id": principal, "run_as_principal_id": principal}
    )


async def _dw_call(port: _Boundary | None) -> tuple[list[str], FakeExecutionStore, FakeAuditRepo]:
    ran: list[str] = []

    async def handler(payload: EchoInput, run_context: RunContext) -> EchoOutput:
        ran.append(payload.message)
        return EchoOutput(echoed=payload.message)

    executor, store, audit = make_executor(handler)
    executor.dw_boundary = port
    try:
        await executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"message": "x"},
            run_context=_dw_run(),
            idempotency_key="k1",
        )
    except PermissionDeniedError as refused:
        ran.append(f"refused:{refused.details['reason_code']}")
    return ran, store, audit


@pytest.mark.parametrize(
    ("port", "reason"),
    [
        (_Boundary(replace(OPERATING, operating=False)), "dw_not_operating"),  # DWK16
        (_Boundary(OPERATING, fails=True), "dw_not_operating"),  # DWK16, unreadable
        (_Boundary(None), "dw_not_operating"),
        (None, "dw_not_operating"),
        (_Boundary(replace(OPERATING, allowed_tools=frozenset({"other"}))), "tool_not_allowed"),
        (_Boundary(replace(OPERATING, scopes=frozenset())), "scope_lost"),  # DWK34
    ],
    ids=["paused", "unreadable", "no-dw", "no-port", "outside-allowed", "scope-lost"],
)
async def test_a_dw_run_outside_its_boundary_reaches_nothing(
    port: _Boundary | None, reason: str
) -> None:
    """DWK16, DWK26, DWK34: refused before the tool runs, with one `refused`
    execution row and a `tool.denied` audit event."""
    ran, store, audit = await _dw_call(port)
    assert ran == [f"refused:{reason}"]
    assert [(r["status"], r["error"], r["idempotency_key"]) for r in store.records] == [
        ("refused", reason, None)
    ]
    assert [(e.action, e.policy_decision) for e in audit.events] == [("tool.denied", reason)]


async def test_a_dw_run_inside_its_boundary_runs() -> None:
    ran, store, _ = await _dw_call(_Boundary(OPERATING))
    assert ran == ["x"]
    assert store.records[-1]["status"] == "succeeded"
