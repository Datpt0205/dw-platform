"""The freeze at every door, and `SqlRunControl`'s snapshot (agent-lifecycle
ticket 01: R7.1, R7.3, R9.1, R9.2; AL11, AL17).

Each door is called directly, never through the layer above it, so removing
the check at that door turns its own test red (failure-modes #5). The
snapshot is driven over a fake session factory and a clock the test moves:
the TTL, the NOTIFY, the 30-second grace and the refusal past it, and which
reason answers when several hold.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import NOW, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import ToolException
from pydantic import BaseModel
from test_agent_factory import _spec
from test_executor import make_definition, make_run_context
from test_prompts_profiles_gateway import make_gateway

from dw_agent_runtime.adapters import run_control as run_control_module
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.langchain_tools import PlatformToolErrorsMiddleware
from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.adapters.run_control import SqlRunControl
from dw_agent_runtime.adapters.run_control_middleware import RunControlMiddleware
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec, sub_agent_spec
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.ports import ModelRequest
from dw_agent_runtime.run_control import (
    RUN_REQUESTING_LANES,
    HaltReason,
    RunControlDoor,
    RunHaltedError,
    lane_actors,
)
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.tools import ToolRegistry
from dw_kernel.errors import ConflictError, PermissionDeniedError
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_observability.metrics import DW_CONTROL_REFUSALS_TOTAL
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.domain.audit import system_actor

pytestmark = pytest.mark.unit


# ------------------------------------------------------------ the doors --


def _executor(control: OpenRunControl) -> tuple[ToolExecutor, FakeExecutionStore, Any]:
    store = FakeExecutionStore()
    uow = FakeUoWFactory()
    executor = ToolExecutor(
        registry=ToolRegistry(),
        execution_store=store,
        uow_factory=uow,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
        steps=build_tool_executor_steps(),
        run_control=control,
    )
    return executor, store, uow.audit_repo


@pytest.mark.parametrize(
    ("reason", "decision"),
    [
        (HaltReason.TENANT_FROZEN, "deny_frozen"),
        (HaltReason.PLATFORM_FROZEN, "deny_frozen"),
        (HaltReason.ARTIFACT_KILLED, "deny_killed"),
        (HaltReason.CONTROL_STATE_UNAVAILABLE, "deny_control_state"),
    ],
)
async def test_a_tool_call_under_a_switch_is_halted_before_anything_resolves(
    reason: HaltReason, decision: str
) -> None:
    """R7.1, R7.3 (AL11): the control-switch step refuses first, a tool that
    does not even exist included: `tool.denied` under the name and version the
    call asked for, no execution row, and `RunHaltedError`, never a permission
    refusal, so the runner cancels the run."""
    control = OpenRunControl()
    control.refuse(reason)
    executor, store, audit = _executor(control)

    with pytest.raises(RunHaltedError) as halted:
        await executor.execute(
            name="crm.unknown", version="2.1.0", raw_input={"x": 1}, run_context=make_run_context()
        )

    assert not isinstance(halted.value, PermissionDeniedError)
    assert halted.value.details["reason_code"] == reason.value
    assert control.doors() == [RunControlDoor.TOOL]
    assert store.records == []
    [event] = audit.events
    assert event.action == "tool.denied"
    assert event.resource_id == "crm.unknown@2.1.0"
    assert event.policy_decision == decision
    assert event.details["reason_code"] == reason.value


async def test_an_open_tool_door_lets_the_call_reach_the_next_step() -> None:
    """The step asks and passes: an unknown tool is then refused by `resolve`."""
    control = OpenRunControl()
    executor, _, audit = _executor(control)
    with pytest.raises(Exception) as refused:
        await executor.execute(
            name="crm.unknown", version="2.1.0", raw_input={}, run_context=make_run_context()
        )
    assert not isinstance(refused.value, RunHaltedError)
    assert control.doors() == [RunControlDoor.TOOL]
    assert audit.events == []


class _Out(BaseModel):
    answer: str


async def test_the_structured_gateway_refuses_before_the_prompt_is_rendered() -> None:
    """R7.1 (AL11): the gateway's first door. The prompt named does not
    exist, so a gateway that rendered first would raise NotFound instead."""
    control = OpenRunControl()
    control.refuse(HaltReason.PLATFORM_FROZEN)
    gateway = make_gateway(MockModelAdapter())
    gateway.run_control = control
    request = ModelRequest(task="t", prompt_id="no.such.prompt", prompt_version="9.9.9")

    with pytest.raises(RunHaltedError) as halted:
        await gateway.generate_structured(request, _Out, run_context=make_run_context())
    assert halted.value.reason is HaltReason.PLATFORM_FROZEN
    assert control.doors() == [RunControlDoor.MODEL]


async def test_the_agent_model_door_refuses_before_the_model_is_called() -> None:
    """R7.1: `RunControlMiddleware` on its own, in a bare agent."""
    control = OpenRunControl()
    control.refuse(HaltReason.TENANT_FROZEN)
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    agent: Any = create_agent(
        model=model, tools=[], middleware=[RunControlMiddleware(control)], context_schema=RunContext
    )
    with pytest.raises(RunHaltedError):
        await agent.ainvoke({"messages": [HumanMessage("x")]}, context=make_run_context())
    assert model.calls == []


async def test_a_delegated_turn_asks_the_parents_port_at_its_model_call() -> None:
    """R7.1 (AL11): the sub-agent's stack carries its own `RunControlMiddleware`
    over the parent executor's port, since the parent's middleware does not
    run for a child turn; a frozen child turn calls no model."""
    parent = _spec(MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]"))
    child = SubAgentSpec(name="helper", description="d", offered=list(parent.offered)[:1])
    built = sub_agent_spec(parent, child)
    doors = [m for m in built["middleware"] if isinstance(m, RunControlMiddleware)]
    assert len(doors) == 1

    control = OpenRunControl()
    control.refuse(HaltReason.TENANT_FROZEN)
    doors[0]._control = control
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    agent: Any = create_agent(
        model=model, tools=[], middleware=built["middleware"], context_schema=RunContext
    )
    with pytest.raises(RunHaltedError):
        await agent.ainvoke({"messages": [HumanMessage("x")]}, context=make_run_context())
    assert model.calls == []


def test_the_tool_errors_middleware_never_tells_the_model_about_a_halt() -> None:
    """R7.1: a refusal is re-raised (None), not turned into a sentence, unlike
    another conflict, which the model is told about."""
    from test_langchain_tools import COPY

    middleware = PlatformToolErrorsMiddleware([make_definition()], copy=COPY)
    request: Any = SimpleNamespace(tool_call={"name": "test__echo"})
    halted = RunHaltedError(HaltReason.TENANT_FROZEN, door=RunControlDoor.TOOL)
    assert middleware._on_error(halted, request) is None
    assert middleware._on_error(ConflictError("x"), request) is not None
    assert not isinstance(halted, ToolException)


def test_a_halt_is_a_409_carrying_its_reason_and_the_switch_that_set_it() -> None:
    by, switch = uuid.uuid4(), uuid.uuid4()
    halted = RunHaltedError(
        HaltReason.ARTIFACT_KILLED, door=RunControlDoor.NODE, set_by=by, switch_id=switch
    )
    assert isinstance(halted, ConflictError)
    assert halted.details == {"reason_code": "artifact_killed", "door": "node"}
    assert (halted.set_by, halted.switch_id) == (by, switch)


def test_the_lane_actors_are_the_registered_lanes_fixed_ids() -> None:
    assert lane_actors() == {system_actor(lane).value for lane in RUN_REQUESTING_LANES}
    assert lane_actors(frozenset({"studio_inbound"})) == {system_actor("studio_inbound").value}


# ------------------------------------------------------- the snapshot --


@dataclass
class _Clock:
    at: datetime = NOW

    def now(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


@dataclass
class _Db:
    """What `SqlRunControl` reads, per company, and whether it answers."""

    switches: dict[uuid.UUID, list[SimpleNamespace]] = field(default_factory=dict)
    platform: SimpleNamespace | None = None
    tenant_status: dict[uuid.UUID, str] = field(default_factory=dict)
    members: dict[tuple[uuid.UUID, uuid.UUID], str] = field(default_factory=dict)
    down: bool = False
    reads: list[str] = field(default_factory=list)

    def __call__(self) -> _Session:
        return _Session(self)

    def freeze(self, tenant: uuid.UUID, *, origin: str = "tenant") -> SimpleNamespace:
        row = SimpleNamespace(
            id=uuid.uuid4(), scope_type="tenant", target_id=None, origin=origin, set_by=uuid.uuid4()
        )
        self.switches.setdefault(tenant, []).append(row)
        return row

    def kill(self, tenant: uuid.UUID, target: uuid.UUID) -> SimpleNamespace:
        row = SimpleNamespace(
            id=uuid.uuid4(),
            scope_type="agent",
            target_id=target,
            origin="tenant",
            set_by=uuid.uuid4(),
        )
        self.switches.setdefault(tenant, []).append(row)
        return row


@dataclass
class _Session:
    db: _Db
    tenant: uuid.UUID | None = None

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def begin(self) -> _Session:
        return self

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        if self.db.down:
            raise OSError("the database is not answering")
        if "set_config" in str(statement):
            self.tenant = uuid.UUID(str((params or {})["tenant_id"]))
            return SimpleNamespace(all=list)
        assert self.tenant is not None
        if statement is run_control_module._OPEN_SWITCHES:
            self.db.reads.append("switches")
            rows = list(self.db.switches.get(self.tenant, []))
            if self.db.platform is not None:
                rows.append(self.db.platform)
            return SimpleNamespace(all=lambda: rows)
        assert statement is run_control_module._STANDING
        self.db.reads.append("standing")
        status = self.db.tenant_status.get(self.tenant)
        principal = (params or {}).get("principal")
        member = self.db.members.get((self.tenant, principal)) if principal else None
        rows = (
            [] if status is None else [SimpleNamespace(tenant_status=status, member_status=member)]
        )
        return SimpleNamespace(all=lambda: rows)


@dataclass
class _World:
    db: _Db
    clock: _Clock
    telemetry: RecordingTelemetry
    control: SqlRunControl
    tenant: uuid.UUID
    person: uuid.UUID

    def run(self, **update: Any) -> RunContext:
        base = make_run_context().model_copy(
            update={"tenant_id": self.tenant, "actor_id": self.person}
        )
        return base.model_copy(update=update)

    async def refused(
        self,
        door: RunControlDoor,
        *,
        artifacts: Sequence[uuid.UUID] = (),
        run: RunContext | None = None,
    ) -> RunHaltedError | None:
        try:
            await self.control.require_open(run or self.run(), door=door, artifacts=artifacts)
        except RunHaltedError as halted:
            return halted
        return None


LANE_ACTOR = system_actor("studio_inbound").value


@pytest.fixture
def world() -> _World:
    db, clock, telemetry = _Db(), _Clock(), RecordingTelemetry()
    tenant, person = uuid.uuid4(), uuid.uuid4()
    db.tenant_status[tenant] = "active"
    db.members[(tenant, person)] = "active"
    control = SqlRunControl(
        db,  # type: ignore[arg-type]
        clock=clock,
        telemetry=telemetry,
        listen_dsn=None,
        system_actors=frozenset({LANE_ACTOR}),
    )
    return _World(db, clock, telemetry, control, tenant, person)


async def test_an_open_company_passes_every_door(world: _World) -> None:
    for door in RunControlDoor:
        assert await world.refused(door) is None


async def test_a_freeze_is_seen_within_the_ttl_and_at_once_after_its_notification(
    world: _World,
) -> None:
    """R7.1: a cached snapshot holds for 5 s; the NOTIFY carrying the company
    drops it, so the next door reads again; past the TTL it is read again
    even when the notification was lost."""
    assert await world.refused(RunControlDoor.MODEL) is None
    switch = world.db.freeze(world.tenant)
    assert await world.refused(RunControlDoor.MODEL) is None  # within the TTL

    world.control.invalidate(f'{{"tenant_id": "{world.tenant}", "id": "{switch.id}"}}')
    halted = await world.refused(RunControlDoor.MODEL)
    assert halted is not None and halted.reason is HaltReason.TENANT_FROZEN
    assert (halted.set_by, halted.switch_id) == (switch.set_by, switch.id)

    world.db.switches.clear()
    world.clock.advance(4)
    assert await world.refused(RunControlDoor.MODEL) is not None
    world.clock.advance(1.5)  # the lost notification: the TTL reads again
    assert await world.refused(RunControlDoor.MODEL) is None


async def test_a_notification_for_another_company_keeps_this_snapshot(world: _World) -> None:
    assert await world.refused(RunControlDoor.MODEL) is None
    world.db.freeze(world.tenant)
    world.control.invalidate(f'{{"tenant_id": "{uuid.uuid4()}", "id": "{uuid.uuid4()}"}}')
    assert await world.refused(RunControlDoor.MODEL) is None


async def test_a_platform_freeze_notification_drops_every_snapshot(world: _World) -> None:
    """R7.1: a platform freeze reaches every company of the process."""
    assert await world.refused(RunControlDoor.MODEL) is None
    operator = uuid.uuid4()
    world.db.platform = SimpleNamespace(
        id=uuid.uuid4(), scope_type="platform", target_id=None, origin="platform", set_by=operator
    )
    world.control.invalidate('{"platform": true}')
    halted = await world.refused(RunControlDoor.TOOL)
    assert halted is not None and halted.reason is HaltReason.PLATFORM_FROZEN
    assert halted.set_by == operator


async def test_an_unreadable_notification_drops_every_snapshot(world: _World) -> None:
    assert await world.refused(RunControlDoor.MODEL) is None
    world.db.freeze(world.tenant)
    world.control.invalidate("not json")
    assert await world.refused(RunControlDoor.MODEL) is not None


async def test_past_thirty_seconds_without_a_refresh_every_door_refuses(world: _World) -> None:
    """R7.3 (AL11): a failed refresh is answered from the last snapshot while
    it is at most 30 s old, then `control_state_unavailable`, the tool door
    included: fail closed."""
    assert await world.refused(RunControlDoor.TOOL) is None
    world.db.down = True
    world.clock.advance(10)
    assert await world.refused(RunControlDoor.TOOL) is None
    world.clock.advance(20)
    assert await world.refused(RunControlDoor.TOOL) is None
    world.clock.advance(1)
    halted = await world.refused(RunControlDoor.TOOL)
    assert halted is not None and halted.reason is HaltReason.CONTROL_STATE_UNAVAILABLE
    assert halted.set_by is None


async def test_a_snapshot_a_notification_dropped_is_not_a_fallback(world: _World) -> None:
    """Known stale is not reused: refused at once when the read fails."""
    assert await world.refused(RunControlDoor.TOOL) is None
    world.db.down = True
    world.control.invalidate(f'{{"tenant_id": "{world.tenant}", "id": "{uuid.uuid4()}"}}')
    halted = await world.refused(RunControlDoor.TOOL)
    assert halted is not None and halted.reason is HaltReason.CONTROL_STATE_UNAVAILABLE


async def test_with_no_snapshot_a_failed_read_refuses_at_once(world: _World) -> None:
    world.db.down = True
    halted = await world.refused(RunControlDoor.MODEL)
    assert halted is not None and halted.reason is HaltReason.CONTROL_STATE_UNAVAILABLE


async def test_a_freeze_of_one_company_leaves_another_open(world: _World) -> None:
    """R7.1 (AL16)."""
    other = uuid.uuid4()
    world.db.tenant_status[other] = "active"
    world.db.freeze(other)
    assert await world.refused(RunControlDoor.TOOL) is None
    assert await world.refused(RunControlDoor.TOOL, run=world.run(tenant_id=other)) is not None


async def test_an_operator_freeze_answers_before_the_companys_own(world: _World) -> None:
    """The precedence ticket 05 builds on: platform, then the operator's
    freeze of the company, then the company's; a kill after a freeze, except
    at admission, where a killed component's run is cancelled, not held."""
    own = world.db.freeze(world.tenant)
    operator = world.db.freeze(world.tenant, origin="platform")
    agent = uuid.uuid4()
    kill = world.db.kill(world.tenant, agent)

    halted = await world.refused(RunControlDoor.MODEL, artifacts=[agent])
    assert halted is not None and halted.reason is HaltReason.TENANT_FROZEN
    assert halted.switch_id == operator.id != own.id

    admitted = await world.refused(RunControlDoor.ADMISSION, artifacts=[agent])
    assert admitted is not None and admitted.reason is HaltReason.ARTIFACT_KILLED
    assert admitted.switch_id == kill.id
    assert await world.control.admission_state(world.tenant, [agent]) is HaltReason.ARTIFACT_KILLED
    assert await world.control.admission_state(world.tenant) is HaltReason.TENANT_FROZEN


async def test_a_kill_refuses_only_the_component_it_names(world: _World) -> None:
    agent = uuid.uuid4()
    world.db.kill(world.tenant, agent)
    assert await world.refused(RunControlDoor.NODE, artifacts=[uuid.uuid4()]) is None
    halted = await world.refused(RunControlDoor.NODE, artifacts=[agent])
    assert halted is not None and halted.reason is HaltReason.ARTIFACT_KILLED


@pytest.mark.parametrize(
    ("member", "refused"),
    [("active", False), ("suspended", True), ("invited", True), (None, True)],
)
async def test_the_principal_must_be_an_active_member_at_the_principal_doors(
    world: _World, member: str | None, refused: bool
) -> None:
    """R9.1 (AL17): no row is not active (closed when missing); read at
    admission, start and resume only, never at a call inside a run."""
    if member is None:
        del world.db.members[(world.tenant, world.person)]
    else:
        world.db.members[(world.tenant, world.person)] = member
    for door in (RunControlDoor.ADMISSION, RunControlDoor.START, RunControlDoor.RESUME):
        halted = await world.refused(door)
        assert (halted is not None and halted.reason is HaltReason.PRINCIPAL_INACTIVE) is refused
    world.db.reads.clear()
    for door in (RunControlDoor.MODEL, RunControlDoor.TOOL, RunControlDoor.DECIDE):
        assert await world.refused(door) is None
    assert "standing" not in world.db.reads


async def test_a_service_principal_is_asked_rather_than_the_lane(world: _World) -> None:
    """R9.1: the run's principal is `run_as_principal_id` when it has one."""
    service = uuid.uuid4()
    world.db.members[(world.tenant, service)] = "suspended"
    halted = await world.refused(
        RunControlDoor.ADMISSION, run=world.run(run_as_principal_id=service)
    )
    assert halted is not None and halted.reason is HaltReason.PRINCIPAL_INACTIVE


async def test_a_lanes_own_actor_is_not_asked_for_a_membership(world: _World) -> None:
    """R9.1 (AL17): `system_actor(<lane>)` of a registered lane passes with no
    row; any other id without a row, a name-based one included, does not."""
    assert await world.refused(RunControlDoor.ADMISSION, run=world.run(actor_id=LANE_ACTOR)) is None
    unregistered = system_actor("not_a_registered_lane").value
    halted = await world.refused(RunControlDoor.ADMISSION, run=world.run(actor_id=unregistered))
    assert halted is not None and halted.reason is HaltReason.PRINCIPAL_INACTIVE


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("locked", HaltReason.TENANT_LOCKED),
        ("offboarding", HaltReason.TENANT_OFFBOARDING),
        ("offboarded", HaltReason.TENANT_OFFBOARDING),
    ],
)
async def test_a_company_not_active_is_refused_at_the_principal_doors(
    world: _World, status: str, reason: HaltReason
) -> None:
    """R9.2 (AL17), before the principal is asked, and at admission for a
    trigger's event too."""
    world.db.tenant_status[world.tenant] = status
    world.db.members[(world.tenant, world.person)] = "suspended"
    for door in (RunControlDoor.ADMISSION, RunControlDoor.START, RunControlDoor.RESUME):
        halted = await world.refused(door)
        assert halted is not None and halted.reason is reason
    assert await world.control.admission_state(world.tenant) is reason


async def test_an_unreadable_standing_refuses_as_unavailable(world: _World) -> None:
    world.db.down = True
    halted = await world.refused(RunControlDoor.START)
    assert halted is not None and halted.reason is HaltReason.CONTROL_STATE_UNAVAILABLE
    assert await world.control.admission_state(world.tenant) is (
        HaltReason.CONTROL_STATE_UNAVAILABLE
    )


async def test_every_refusal_is_counted_by_door_and_reason_never_by_company(
    world: _World,
) -> None:
    """R7.1 (AL11): `dw_control_refusals_total{door, reason_code}`."""
    world.db.freeze(world.tenant)
    await world.refused(RunControlDoor.TOOL)
    await world.refused(RunControlDoor.COMPACTION)
    await world.control.admission_state(world.tenant)
    counted = [m for m in world.telemetry.metrics if m[0] == DW_CONTROL_REFUSALS_TOTAL]
    assert [dict(m[2]) for m in counted] == [
        {"door": "tool", "reason_code": "tenant_frozen"},
        {"door": "compaction", "reason_code": "tenant_frozen"},
        {"door": "admission", "reason_code": "tenant_frozen"},
    ]
    assert all(set(m[2]) == {"door", "reason_code"} for m in counted)


async def test_admission_state_is_none_for_an_open_company(world: _World) -> None:
    """R7.2: the trigger's event is admitted once nothing holds the company."""
    assert await world.control.admission_state(world.tenant) is None
    world.db.freeze(world.tenant)
    world.clock.advance(6)
    assert await world.control.admission_state(world.tenant) is HaltReason.TENANT_FROZEN


async def test_snapshots_older_than_the_grace_are_forgotten(world: _World) -> None:
    """failure-modes #6: the map holds the companies in use, not every one
    ever asked about."""
    others = [uuid.uuid4() for _ in range(3)]
    for other in others:
        world.db.tenant_status[other] = "active"
        assert await world.refused(RunControlDoor.TOOL, run=world.run(tenant_id=other)) is None
    world.clock.advance(31)
    assert await world.refused(RunControlDoor.TOOL) is None
    assert set(world.control._snapshots) == {world.tenant}
