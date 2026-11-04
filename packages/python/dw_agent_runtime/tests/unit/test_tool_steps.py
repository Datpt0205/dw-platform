"""The ordered register of a ToolExecutor's steps (tools-and-skills ticket 01:
R2.6, R2.7, R2.8, R3.1; TS10, TS12, TS13).

The executor is called directly, never through the agent's wrapper, so each
case shows the step that refused it and that nothing after it ran: no later
step, no claim, no `dispatched` row, no handler (failure-modes #5).
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fakes import NOW, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_executor import EchoOutput, make_definition, make_run_context

from dw_agent_runtime.adapters.wflite_host import build_tool_executor, build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import MessageSpec, RunContext, ToolDefinition
from dw_agent_runtime.executor import (
    GATE_STEPS,
    PENDING_STEPS,
    TAIL_STEPS,
    TOOL_STEP_ORDER,
    DecisionCall,
    ToolCall,
    ToolExecutor,
    ToolSteps,
)
from dw_agent_runtime.run_control import HaltReason, RunHaltedError
from dw_agent_runtime.samples import SampleOutput
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_kernel.errors import (
    ApprovalRequiredError,
    ConfigError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_observability.telemetry import NullTelemetry
from dw_platform.application.marketing_send import Admission, SendRequest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]

# R2.6, written out here rather than read from the code it checks.
R2_6 = (
    "control_switch",
    "resolve",
    "validate_input",
    "dw_boundary",
    "decision_call",
    "scopes",
    "run_mode",
    "approval",
    "send_floor",
    "claim",
    "dispatched",
    "handler",
    "validate_output",
    "audit",
)


class MailInput(BaseModel):
    to: str
    message: str = "x"
    unsubscribe_url: str | None = None


async def _noop(executor: ToolExecutor, call: ToolCall) -> None:
    return None


# ------------------------------------------------------------ the register --


def test_the_register_holds_all_of_r2_6_and_nothing_waits() -> None:
    """R2.7 (TS12); agent-lifecycle R7.1: the real register, its tail, and the
    pending list empty since the control switch was registered first."""
    assert TOOL_STEP_ORDER == R2_6
    steps = build_tool_executor_steps()
    assert steps.names() == R2_6
    assert steps.names()[0] == "control_switch"
    assert dict(PENDING_STEPS) == {}
    assert TAIL_STEPS == ("claim", "dispatched", "handler", "validate_output", "audit")
    assert len(steps.seal()) == len(GATE_STEPS)


def test_the_control_switch_left_out_or_after_the_scopes_is_refused_naming_it() -> None:
    """agent-lifecycle R7.1 (AL11): a register without the control switch, not
    put back on the pending list, does not seal; nor one that asks it after
    the scope check."""
    entries = dict(build_tool_executor_steps().entries())
    without = ToolSteps()
    for name, step in entries.items():
        if name != "control_switch":
            without.register(name, step)
    with pytest.raises(ConfigError) as missing:
        without.seal()
    assert missing.value.details["step"] == "control_switch"

    late = ToolSteps()
    for name, step in entries.items():
        if name != "control_switch":
            late.register(name, step)
        if name == "scopes":
            late.register("control_switch", entries["control_switch"])
    with pytest.raises(ConfigError) as after:
        late.seal()
    assert after.value.details["step"] == "control_switch"


def test_the_send_floor_is_a_registered_step_not_a_pending_one() -> None:
    """R2.7, R2.8: the floor is registered."""
    assert "send_floor" in build_tool_executor_steps().names()
    assert "send_floor" not in PENDING_STEPS


def test_a_register_with_the_send_floor_pending_is_refused_when_built() -> None:
    """compliance-pdpl R3.12 (CP25): a pending step decides nothing, so the
    floor pending would let a message through unasked; the register refuses
    it at construction, naming it, before any step is registered."""
    with pytest.raises(ConfigError) as refused:
        ToolSteps(pending={**PENDING_STEPS, "send_floor": "compliance-pdpl/04"})
    assert refused.value.details["step"] == "send_floor"
    assert "never be pending" in refused.value.message


def _register(order: list[str], *, pending: dict[str, str] | None = None) -> ToolSteps:
    steps = ToolSteps(pending=dict(PENDING_STEPS) if pending is None else pending)
    for name in order:
        steps.register(name, _noop)
    return steps


GATES = list(R2_6[:9])


def test_two_steps_out_of_order_are_refused_naming_the_step() -> None:
    """R2.7 (TS12): the run mode after the approval, and the DW boundary after
    the scope check."""
    swapped = GATES.copy()
    at = swapped.index("run_mode")
    swapped[at], swapped[at + 1] = swapped[at + 1], swapped[at]
    with pytest.raises(ConfigError) as refused:
        _register(swapped).seal()
    assert refused.value.details["step"] == "run_mode"

    moved = [n for n in GATES if n != "dw_boundary"]
    moved.insert(moved.index("scopes") + 1, "dw_boundary")
    with pytest.raises(ConfigError) as refused:
        _register(moved).seal()
    assert refused.value.details["step"] == "dw_boundary"


def test_a_name_outside_r2_6_a_name_twice_and_a_tail_name_are_refused() -> None:
    """R2.7 (TS12)."""
    steps = ToolSteps()
    with pytest.raises(ConfigError) as unknown:
        steps.register("rate_limit", _noop)
    assert unknown.value.details["step"] == "rate_limit"
    steps.register("resolve", _noop)
    with pytest.raises(ConfigError) as twice:
        steps.register("resolve", _noop)
    assert twice.value.details["step"] == "resolve"
    for tail in TAIL_STEPS:
        with pytest.raises(ConfigError, match="tail") as from_outside:
            steps.register(tail, _noop)
        assert from_outside.value.details["step"] == tail


def test_a_missing_step_is_refused_unless_it_is_pending() -> None:
    """R2.7 (TS12): leaving out `resolve` fails; listing it as pending passes."""
    without = [n for n in GATES if n != "resolve"]
    with pytest.raises(ConfigError) as refused:
        _register(without).seal()
    assert refused.value.details["step"] == "resolve"
    pending = {**PENDING_STEPS, "resolve": "a later ticket"}
    assert len(_register(without, pending=pending).seal()) == len(without)


def test_an_executor_with_a_wrong_register_does_not_start() -> None:
    """R2.7: `seal` runs when the executor is built."""
    store = FakeExecutionStore()
    with pytest.raises(ConfigError):
        ToolExecutor(
            registry=ToolRegistry(),
            execution_store=store,
            uow_factory=FakeUoWFactory(),
            clock=FixedClock(NOW),
            id_generator=SequentialIdGenerator(),
            approval_policy=AutonomyApprovalPolicy(),
            claims=FakeToolClaims(store),
            steps=_register([n for n in GATES if n != "scopes"]),
            run_control=OpenRunControl(),
        )


def test_build_tool_executor_takes_its_register_from_the_one_function() -> None:
    """R2.7 (TS12): the shared builder's executor holds the register
    `build_tool_executor_steps` builds."""
    executor = build_tool_executor(
        tools=ToolRegistry(),
        session_factory=async_sessionmaker(),
        uow_factory=FakeUoWFactory(),
        approval_policy=AutonomyApprovalPolicy(),
        telemetry=NullTelemetry(),
        clock=FixedClock(NOW),
        ids=SequentialIdGenerator(),
        send_admission=None,
        run_control=OpenRunControl(),
    )
    assert executor.steps.names() == build_tool_executor_steps().names()


def _calls_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name | ast.Attribute)
    }


def test_both_roots_build_their_executor_only_through_the_shared_builder() -> None:
    """R2.7 (TS12): no root builds an executor or a register of its own."""
    roots = [
        REPO_ROOT / "apps/api/src/dw_api/bootstrap/runtime.py",
        REPO_ROOT / "apps/worker/src/dw_worker/composition.py",
    ]
    for root in roots:
        assert "build_tool_executor" in _calls_in(root), root
    for tree in ("apps/api/src", "apps/worker/src"):
        for path in (REPO_ROOT / tree).rglob("*.py"):
            calls = _calls_in(path)
            assert "ToolExecutor" not in calls, path
            assert "ToolSteps" not in calls, path
            assert "build_tool_executor_steps" not in calls, path


# ------------------------------------------------- each step stops the call --


@dataclass
class FakeFloor:
    """`SendAdmissionPort`: admits, or refuses with `refuse_with`."""

    refuse_with: str | None = None
    asked: list[str] = field(default_factory=list)
    sent_calls: int = 0

    async def admit(self, request: SendRequest) -> Admission:
        self.asked.append(request.address)
        if self.refuse_with is not None:
            return Admission(admitted=False, reason=self.refuse_with)
        return Admission(admitted=True, unsubscribe_url="https://app.example.com/unsubscribe/t")

    async def refuse(self, request: SendRequest, reason: str) -> Admission:
        self.asked.append(request.address)
        return Admission(admitted=False, reason=reason)

    async def sent(self, request: SendRequest, admission: Admission) -> None:
        self.sent_calls += 1


@dataclass
class Bench:
    executor: ToolExecutor
    store: FakeExecutionStore
    claims: FakeToolClaims
    audit: Any
    seen: list[str]
    handled: list[bool]

    def dispatched(self) -> list[dict[str, Any]]:
        return [r for r in self.store.records if r["status"] == "dispatched"]


def spied(seen: list[str]) -> ToolSteps:
    """The real register, each step recording that it ran."""
    steps = ToolSteps()
    for name, step in build_tool_executor_steps().entries():

        def wrap(
            name: str, step: Callable[[ToolExecutor, ToolCall], Awaitable[BaseModel | None]]
        ) -> Callable[[ToolExecutor, ToolCall], Awaitable[BaseModel | None]]:
            async def run(executor: ToolExecutor, call: ToolCall) -> BaseModel | None:
                seen.append(name)
                return await step(executor, call)

            return run

        steps.register(name, wrap(name, step))
    return steps


def bench(
    definition: ToolDefinition | None = None,
    *,
    floor: FakeFloor | None = None,
    steps: ToolSteps | None = None,
    control: OpenRunControl | None = None,
) -> Bench:
    store = FakeExecutionStore()
    claims = FakeToolClaims(store)
    uow = FakeUoWFactory()
    seen: list[str] = []
    handled: list[bool] = []

    async def handler(payload: BaseModel, run_context: RunContext) -> EchoOutput:
        # Whether the dispatch log was already written when the tool ran.
        handled.append(any(r["status"] == "dispatched" for r in store.records))
        return EchoOutput(echoed="ok")

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition or make_definition(),
            pydantic_behaviour(MailInput, EchoOutput, handler),
        )
    )

    async def no_sleep(_: float) -> None: ...

    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=uow,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=claims,
        steps=steps if steps is not None else spied(seen),
        sleep=no_sleep,
        send_admission=floor,
        run_control=control if control is not None else OpenRunControl(),
    )
    return Bench(executor, store, claims, uow.audit_repo, seen, handled)


MAIL = make_definition(
    message=MessageSpec(channel="email", recipient_fields=("to",)),
)


@dataclass(frozen=True)
class Case:
    step: str
    expected: type[Exception] | None
    definition: ToolDefinition = field(default_factory=make_definition)
    name: str = "test.echo"
    raw_input: dict[str, object] = field(default_factory=lambda: {"to": "a@b.vn"})
    context: dict[str, object] = field(default_factory=dict)
    decision: DecisionCall | None = None
    hold_claim: bool = False
    frozen: bool = False


CASES = [
    Case("control_switch", RunHaltedError, frozen=True),
    Case("resolve", NotFoundError, name="test.missing"),
    Case("validate_input", DomainError, raw_input={"to": 1, "extra": "x"}),
    Case("dw_boundary", PermissionDeniedError, context={"run_as_principal_id": uuid.uuid4()}),
    Case("decision_call", PermissionDeniedError, decision=DecisionCall("lead.reply")),
    Case("scopes", PermissionDeniedError, context={"scopes": frozenset({"demo.read"})}),
    Case("run_mode", None, context={"run_mode": "simulate"}),
    Case("approval", ApprovalRequiredError, context={"autonomy_level": "A1"}),
    Case("send_floor", PermissionDeniedError, definition=MAIL),
    Case("claim", ConflictError, hold_claim=True),
]


@pytest.mark.parametrize("case", CASES, ids=[c.step for c in CASES])
async def test_a_call_stopped_at_a_step_runs_nothing_after_it(case: Case) -> None:
    """R2.6 (TS10): the steps after the one that stopped the call never ran,
    no `dispatched` row was written, and the handler was not called."""
    control = OpenRunControl()
    if case.frozen:
        control.refuse(HaltReason.TENANT_FROZEN)
    b = bench(case.definition, control=control)
    key = "k1"
    if case.hold_claim:
        await b.claims.claim(make_run_context(), case.name, key, lease_seconds=60)
    run = make_run_context().model_copy(update=case.context)
    call = b.executor.execute(
        name=case.name,
        version="1.0.0",
        raw_input=case.raw_input,
        run_context=run,
        idempotency_key=key,
        decision=case.decision,
    )
    if case.expected is None:
        assert isinstance(await call, SampleOutput)
    else:
        with pytest.raises(case.expected):
            await call
    gates = [n for n in R2_6 if n in GATE_STEPS]
    ran_to = gates.index(case.step) if case.step in gates else len(gates) - 1
    assert b.seen == gates[: ran_to + 1]
    assert b.dispatched() == []
    assert b.handled == []


async def test_a_call_through_every_step_logs_dispatched_before_the_handler() -> None:
    """R2.6 (runtime-hardening R6.11)."""
    b = bench()
    await b.executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"to": "a@b.vn"},
        run_context=make_run_context(),
        idempotency_key="k1",
    )
    assert b.seen == list(GATE_STEPS)
    assert b.handled == [True]
    assert [r["status"] for r in b.store.records] == ["dispatched", "succeeded"]


async def test_execute_runs_only_the_steps_of_its_register() -> None:
    """R2.7 (TS12): a register whose scope step does nothing lets a call with
    no scope through, so `_execute` checks scopes nowhere but in its register."""
    steps = ToolSteps()
    for name, step in build_tool_executor_steps().entries():
        steps.register(name, _noop if name == "scopes" else step)
    b = bench(steps=steps)
    output = await b.executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"to": "a@b.vn"},
        run_context=make_run_context(scopes=frozenset()),
        idempotency_key="k1",
    )
    assert isinstance(output, EchoOutput)


async def test_outside_live_a_critical_call_never_asks_approval_required() -> None:
    """R2.6 (TS10; tenant-config R5.6): the mode step answers first, so the
    approval question is not asked and nothing waits; at `live` it is asked
    and the call waits."""
    b = bench(make_definition(side_effect_level="critical", approval_policy="always"))
    asked: list[str] = []
    real = b.executor.approval_required

    def spy(definition: ToolDefinition, run_context: RunContext) -> bool:
        asked.append(run_context.run_mode)
        return real(definition, run_context)

    b.executor.approval_required = spy  # type: ignore[method-assign]
    run = make_run_context()
    output = await b.executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"to": "a@b.vn"},
        run_context=run.model_copy(update={"run_mode": "simulate"}),
        idempotency_key="k1",
    )
    assert isinstance(output, SampleOutput)
    assert asked == []
    assert b.store.records[-1]["status"] == "simulated"
    assert "tool.approval_required" not in {e.action for e in b.audit.events}
    with pytest.raises(ApprovalRequiredError):
        await b.executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"to": "a@b.vn"},
            run_context=run,
            idempotency_key="k2",
        )
    assert asked == ["live"]
    assert b.handled == []


# --------------------------------------------------------- the Send floor --


async def test_without_a_floor_a_message_is_blocked_and_nothing_runs() -> None:
    """R2.8 (TS13): no `SendAdmissionPort`, `blocked:send_floor_unavailable`,
    no handler, no `dispatched` row."""
    b = bench(MAIL, floor=None)
    with pytest.raises(PermissionDeniedError) as refused:
        await b.executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"to": "a@b.vn"},
            run_context=make_run_context(),
            idempotency_key="k1",
        )
    assert refused.value.details["reason_code"] == "blocked:send_floor_unavailable"
    assert b.handled == [] and b.dispatched() == []
    assert [r["status"] for r in b.store.records] == ["refused"]


async def test_without_a_floor_a_tool_with_no_message_runs() -> None:
    """R2.8 (TS13)."""
    b = bench(floor=None)
    await b.executor.execute(
        name="test.echo",
        version="1.0.0",
        raw_input={"to": "a@b.vn"},
        run_context=make_run_context(),
        idempotency_key="k1",
    )
    assert b.handled == [True]


async def test_the_floor_is_asked_at_every_call() -> None:
    """R3.1 (TS6): two calls in a row to one recipient, two questions."""
    floor = FakeFloor()
    b = bench(MAIL, floor=floor)
    for key in ("k1", "k2"):
        await b.executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"to": "a@b.vn", "message": key},
            run_context=make_run_context(),
            idempotency_key=key,
        )
    assert floor.asked == ["a@b.vn", "a@b.vn"]
    assert floor.sent_calls == 2
    assert b.handled == [True, True]


async def test_an_internal_message_without_a_key_is_refused_before_the_floor() -> None:
    """R3.1 (TS6): the key is required of every tool with a `message`, at any
    level; the floor is not asked and the handler does not run."""
    floor = FakeFloor()
    internal_mail = make_definition(
        side_effect_level="internal",
        message=MessageSpec(channel="email", recipient_fields=("to",)),
    )
    b = bench(internal_mail, floor=floor)
    with pytest.raises(DomainError) as refused:
        await b.executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"to": "a@b.vn"},
            run_context=make_run_context(),
            idempotency_key=None,
        )
    assert type(refused.value) is DomainError
    assert "idempotency key" in refused.value.message
    assert b.seen[-1] == "approval"
    assert floor.asked == [] and b.handled == []


async def test_a_refusal_of_the_floor_runs_nothing_and_is_denied() -> None:
    """R3.2 (G5): the floor's refusal is the executor's `refused` row and
    `tool.denied` with `blocked:<reason>`."""
    floor = FakeFloor(refuse_with="no_consent")
    b = bench(MAIL, floor=floor)
    with pytest.raises(PermissionDeniedError) as refused:
        await b.executor.execute(
            name="test.echo",
            version="1.0.0",
            raw_input={"to": "a@b.vn"},
            run_context=make_run_context(),
            idempotency_key="k1",
        )
    assert refused.value.details["reason_code"] == "blocked:no_consent"
    assert b.handled == [] and floor.sent_calls == 0
    assert [(r["status"], r["error"]) for r in b.store.records] == [
        ("refused", "blocked:no_consent")
    ]
    [denied] = [e for e in b.audit.events if e.action == "tool.denied"]
    assert denied.details["reason_code"] == "blocked:no_consent"
    assert not [e for e in b.audit.events if e.action == "marketing.send_refused"]
