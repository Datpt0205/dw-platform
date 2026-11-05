# ruff: noqa: F811  (the world of test_run_control is imported by name)
"""A kill at every door and the `control_switch` lane, without a database
(agent-lifecycle ticket 05: R8.1, R8.2, R8.5, R8.10, R8.11; AL13, AL15,
AL29).

The doors ask `SqlRunControl` over the fake session factory of
`test_run_control` (its `world` fixture): the run's own component is named by
`RunContext.artifact_id`, read where a Studio run is taken and resumed, so no
door has to pass it; a linked agent's component is named by its sub-agent
stack. The lane runs over an in-memory store and hooks that record what they
were handed and when.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from fakes import NOW
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from test_agent_factory import _spec
from test_run_control import (  # noqa: F401  (the fixture, used by name)
    _World,
    world,
)

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.run_control import reached_components
from dw_agent_runtime.adapters.run_control_middleware import RunControlMiddleware
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec, sub_agent_spec
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.control_switch_lane import (
    LANE,
    ControlSwitchLane,
    OpenKillOfRuns,
    ParkedRun,
    RunCancelHooks,
)
from dw_agent_runtime.ports import RunCancelUnit
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_platform.domain.approval import ApprovalRequest, ApprovalStatus
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

# Every door a running run asks; `admission` has its own precedence.
RUNNING_DOORS = [d for d in RunControlDoor if d is not RunControlDoor.ADMISSION]


# ---------------------------------------------------- the doors (R8.1, R8.11) --


@pytest.mark.parametrize("door", list(RunControlDoor))
async def test_a_kill_of_the_runs_own_component_refuses_every_door_naming_its_setter(
    world: _World, door: RunControlDoor
) -> None:
    """R8.1, R8.11 (AL29): the door names nothing; the run's own component
    refuses it, with the kill's `set_by` and id."""
    component = uuid.uuid4()
    kill = world.db.kill(world.tenant, component)
    halted = await world.refused(door, run=world.run(artifact_id=component))
    assert halted is not None and halted.reason is HaltReason.ARTIFACT_KILLED
    assert (halted.set_by, halted.switch_id) == (kill.set_by, kill.id)
    assert await world.refused(door, run=world.run(artifact_id=uuid.uuid4())) is None
    assert await world.refused(door, run=world.run()) is None


@pytest.mark.parametrize("door", list(RunControlDoor))
async def test_a_simulate_run_is_refused_by_no_kill_but_still_by_a_freeze(
    world: _World, door: RunControlDoor
) -> None:
    """R8.1: "still allows `simulate` runs so a fix can be evaluated"
    (ADR-0120 decision 7), its own component and a linked one alike."""
    component, linked = uuid.uuid4(), uuid.uuid4()
    world.db.kill(world.tenant, component)
    world.db.kill(world.tenant, linked)
    run = world.run(artifact_id=component, run_mode="simulate")
    assert await world.refused(door, run=run, artifacts=[linked]) is None

    world.db.freeze(world.tenant)
    world.control.invalidate(f'{{"tenant_id": "{world.tenant}", "id": "{uuid.uuid4()}"}}')
    halted = await world.refused(door, run=run)
    assert halted is not None and halted.reason is HaltReason.TENANT_FROZEN


@pytest.mark.parametrize("mode", ["live", "test"])
def test_the_reached_components_are_the_runs_own_then_the_doors(mode: Any) -> None:
    component, linked = uuid.uuid4(), uuid.uuid4()
    run = _run(artifact_id=component, run_mode=mode)
    assert reached_components(run, [linked]) == (component, linked)
    assert reached_components(_run(run_mode=mode), [linked]) == (linked,)
    assert reached_components(_run(artifact_id=component, run_mode="simulate"), [linked]) == ()


async def test_the_runs_own_component_is_named_before_a_linked_agent(world: _World) -> None:
    """R8.1: two kills open, the root's is the reason."""
    component, linked = uuid.uuid4(), uuid.uuid4()
    linked_kill = world.db.kill(world.tenant, linked)
    own_kill = world.db.kill(world.tenant, component)
    run = world.run(artifact_id=component)
    halted = await world.refused(RunControlDoor.MODEL, run=run, artifacts=[linked])
    assert halted is not None and halted.switch_id == own_kill.id != linked_kill.id


@pytest.mark.parametrize("door", RUNNING_DOORS)
async def test_a_freeze_by_q_answers_before_a_kill_by_p_with_q_as_setter(
    world: _World, door: RunControlDoor
) -> None:
    """R8.1, R8.11: the company frozen by Q and the component killed by P:
    `tenant_frozen`, `set_by` Q, at every door but admission."""
    component = uuid.uuid4()
    world.db.kill(world.tenant, component)
    freeze = world.db.freeze(world.tenant)
    halted = await world.refused(door, run=world.run(artifact_id=component))
    assert halted is not None and halted.reason is HaltReason.TENANT_FROZEN
    assert halted.set_by == freeze.set_by


async def test_at_admission_a_kill_by_p_answers_before_a_freeze_by_q(world: _World) -> None:
    """R8.1: a killed component's queued run is cancelled, not held by the
    freeze, so the kill is the reason there, with P as setter."""
    component = uuid.uuid4()
    kill = world.db.kill(world.tenant, component)
    world.db.freeze(world.tenant)
    halted = await world.refused(RunControlDoor.ADMISSION, run=world.run(artifact_id=component))
    assert halted is not None and halted.reason is HaltReason.ARTIFACT_KILLED
    assert halted.set_by == kill.set_by


async def test_a_platform_freeze_names_the_operator_and_its_own_id(world: _World) -> None:
    """R8.11 (H-32): `platform_frozen` carries the operator who set it and the
    freeze's id, which ticket 08's audit writes as `platform_freeze_id`."""
    operator, freeze_id = uuid.uuid4(), uuid.uuid4()
    world.db.platform = _platform_row(freeze_id, operator)
    halted = await world.refused(RunControlDoor.NODE, run=world.run(artifact_id=uuid.uuid4()))
    assert halted is not None and halted.reason is HaltReason.PLATFORM_FROZEN
    assert (halted.set_by, halted.switch_id) == (operator, freeze_id)


@pytest.mark.parametrize(
    ("status", "reason"),
    [("locked", HaltReason.TENANT_LOCKED), ("offboarding", HaltReason.TENANT_OFFBOARDING)],
)
async def test_a_reason_that_is_no_switch_carries_no_setter(
    world: _World, status: str, reason: HaltReason
) -> None:
    """R8.11: `tenant_locked` and the other reasons that are not a person's
    switch carry no `set_by`."""
    world.db.tenant_status[world.tenant] = status
    halted = await world.refused(RunControlDoor.START)
    assert halted is not None and halted.reason is reason
    assert (halted.set_by, halted.switch_id) == (None, None)


# ------------------------------------------------- the linked agent (R8.5) --


async def test_a_killed_linked_agent_is_refused_in_its_sub_agent_stack(world: _World) -> None:
    """R8.5 (AL15): the child stack names the linked agent's component; its
    kill refuses the delegated turn while the run's own component is open,
    and no model is called."""
    linked = uuid.uuid4()
    kill = world.db.kill(world.tenant, linked)
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    agent = _child_agent(world, model, SubAgentSpec("helper", "d", [], artifact_id=linked))

    with pytest.raises(RunHaltedError) as halted:
        await agent.ainvoke(
            {"messages": [HumanMessage("x")]}, context=world.run(artifact_id=uuid.uuid4())
        )
    assert halted.value.reason is HaltReason.ARTIFACT_KILLED
    assert halted.value.switch_id == kill.id
    assert model.calls == []


async def test_a_sub_agent_that_is_no_component_asks_only_the_runs_own(world: _World) -> None:
    """The same stack without a linked component: the other agent's kill does
    not reach it, the model answers."""
    world.db.kill(world.tenant, uuid.uuid4())
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    agent = _child_agent(world, model, SubAgentSpec("helper", "d", []))
    await agent.ainvoke(
        {"messages": [HumanMessage("x")]}, context=world.run(artifact_id=uuid.uuid4())
    )
    assert len(model.calls) == 1


def _child_agent(world: _World, model: MockChatModel, child: SubAgentSpec) -> Any:
    parent = _spec(MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]"))
    built = sub_agent_spec(parent, child)
    [door] = [m for m in built["middleware"] if isinstance(m, RunControlMiddleware)]
    door._control = world.control
    return create_agent(
        model=model, tools=[], middleware=built["middleware"], context_schema=RunContext
    )


# ------------------------------------------------- the lane (R8.2, R8.10) --


@dataclass
class _Run:
    workspace_id: uuid.UUID
    status: str = "waiting_approval"


@dataclass
class _Store:
    """`KilledRunsPort` in memory: one company, its runs, their requests and
    the audit rows; a transaction keeps its writes only when it commits."""

    kill: OpenKillOfRuns | None
    runs: dict[uuid.UUID, _Run] = field(default_factory=dict)
    requests: dict[uuid.UUID, ApprovalRequest] = field(default_factory=dict)
    audits: list[AuditEvent] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    async def open_kill(self, tenant_id: uuid.UUID, switch_id: uuid.UUID) -> OpenKillOfRuns | None:
        return self.kill if self.kill is not None and self.kill.switch_id == switch_id else None

    async def parked_runs(self, tenant_id: uuid.UUID, target_id: uuid.UUID) -> list[uuid.UUID]:
        return [run_id for run_id, run in self.runs.items() if run.status != "cancelled"]

    @asynccontextmanager
    async def transaction(self, tenant_id: uuid.UUID) -> AsyncIterator[_Tx]:
        tx = _Tx(self)
        yield tx
        tx.commit()


@dataclass
class _Tx:
    store: _Store
    audits: list[AuditEvent] = field(default_factory=list)
    cancelled: list[uuid.UUID] = field(default_factory=list)
    saved: list[ApprovalRequest] = field(default_factory=list)

    async def kill_open(self, switch_id: uuid.UUID) -> bool:
        return self.store.kill is not None

    async def parked(self, run_id: uuid.UUID) -> ParkedRun | None:
        run = self.store.runs[run_id]
        return None if run.status == "cancelled" else ParkedRun(run_id, run.workspace_id)

    async def pending_approvals(self, run_id: uuid.UUID) -> list[ApprovalRequest]:
        return [
            ApprovalRequest(
                id=r.id,
                tenant_id=r.tenant_id,
                workspace_id=r.workspace_id,
                approval_type=r.approval_type,
                requested_by=r.requested_by,
                reason=r.reason,
                run_id=r.run_id,
                status=r.status,
                version=r.version,
            )
            for r in self.store.requests.values()
            if r.run_id == run_id and r.status is ApprovalStatus.PENDING
        ]

    async def save_approval(self, request: ApprovalRequest) -> None:
        self.saved.append(request)

    async def cancel(self, run_id: uuid.UUID, *, switch_id: uuid.UUID) -> None:
        self.store.log.append(f"cancel {run_id}")
        self.cancelled.append(run_id)

    async def audit(self, event: AuditEvent) -> None:
        self.audits.append(event)

    def commit(self) -> None:
        for run_id in self.cancelled:
            self.store.runs[run_id].status = "cancelled"
        for request in self.saved:
            self.store.requests[request.id] = request
        self.store.audits.extend(self.audits)


@dataclass
class _Hook:
    """Records each call, writes one audit row through the unit it is handed,
    and raises when told to."""

    store: _Store
    calls: list[tuple[uuid.UUID, uuid.UUID, str]] = field(default_factory=list)
    fail: bool = False

    async def on_cancel(
        self, unit: RunCancelUnit, run_id: uuid.UUID, *, actor: uuid.UUID, lane: str
    ) -> None:
        self.calls.append((run_id, actor, lane))
        self.store.log.append(f"hook {run_id}")
        await unit.audit(
            AuditEvent(
                id=uuid.uuid4(),
                tenant_id=TenantId(TENANT),
                workspace_id=WorkspaceId(WORKSPACE),
                actor_id=UserId(actor),
                action="run.effect_unresolved",
                resource_type="worker_run",
                resource_id=str(run_id),
                occurred_at=NOW,
                details={"lane": lane},
            )
        )
        if self.fail:
            raise RuntimeError("the hook could not record")


TENANT, WORKSPACE, SETTER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _world(*hooks: str) -> tuple[_Store, ControlSwitchLane, dict[str, _Hook]]:
    kill = OpenKillOfRuns(switch_id=uuid.uuid4(), target_id=uuid.uuid4(), set_by=SETTER)
    store = _Store(kill)
    registry = RunCancelHooks()
    made = {name: _Hook(store) for name in hooks}
    for name, hook in made.items():
        registry.register(name, hook)
    lane = ControlSwitchLane(
        store=store, hooks=registry.freeze(), clock=FixedClock(NOW), ids=SequentialIdGenerator()
    )
    return store, lane, made


def _waiting(store: _Store, *, with_request: bool = True) -> tuple[uuid.UUID, uuid.UUID | None]:
    run_id = uuid.uuid4()
    store.runs[run_id] = _Run(WORKSPACE)
    if not with_request:
        return run_id, None
    request = ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        approval_type="demo.review",
        requested_by=UserId(uuid.uuid4()),
        reason="x",
        run_id=run_id,
    )
    store.requests[request.id] = request
    return run_id, request.id


async def test_the_lane_cancels_each_parked_run_and_its_request_in_the_setters_name() -> None:
    """R8.2 (AL13): the run cancelled, its pending request cancelled, both
    audited with the setter as actor and `details.lane` `control_switch`."""
    store, lane, _ = _world()
    run_id, request_id = _waiting(store)
    assert store.kill is not None
    assert await lane.handle(TENANT, store.kill.switch_id) == 1

    assert store.runs[run_id].status == "cancelled"
    assert request_id is not None
    assert store.requests[request_id].status is ApprovalStatus.CANCELLED
    actions = [(a.action, a.actor_id.value, a.details["lane"]) for a in store.audits]
    assert actions == [
        ("approval.cancelled", SETTER, LANE),
        ("run.cancelled", SETTER, LANE),
    ]
    assert store.audits[1].details["reason_code"] == "artifact_killed"


async def test_a_request_already_decided_is_left_and_the_run_still_cancelled() -> None:
    """R8.3: `decide` committed its decision first; the lane leaves it and
    cancels the run, whose resume then finds it no longer waiting."""
    store, lane, _ = _world()
    run_id, request_id = _waiting(store)
    assert request_id is not None and store.kill is not None
    store.requests[request_id].status = ApprovalStatus.APPROVED
    await lane.handle(TENANT, store.kill.switch_id)
    assert store.runs[run_id].status == "cancelled"
    assert store.requests[request_id].status is ApprovalStatus.APPROVED
    assert [a.action for a in store.audits] == ["run.cancelled"]


async def test_a_lifted_or_unknown_switch_changes_nothing() -> None:
    store, lane, _ = _world()
    run_id, _ = _waiting(store)
    assert await lane.handle(TENANT, uuid.uuid4()) == 0
    store.kill = None
    assert await lane.handle(TENANT, uuid.uuid4()) == 0
    assert store.runs[run_id].status == "waiting_approval"
    assert store.audits == []


async def test_every_hook_is_called_once_in_the_cancel_before_the_run_is_cancelled() -> None:
    """R8.10 (AL29): each registered hook once per run, with the run, the
    setter and the lane, before the cancel; what it writes through the unit
    commits with the cancel."""
    store, lane, hooks = _world("effects", "waits")
    run_id, _ = _waiting(store, with_request=False)
    assert store.kill is not None
    await lane.handle(TENANT, store.kill.switch_id)

    for hook in hooks.values():
        assert hook.calls == [(run_id, SETTER, LANE)]
    assert store.log == [f"hook {run_id}", f"hook {run_id}", f"cancel {run_id}"]
    assert [a.action for a in store.audits].count("run.effect_unresolved") == 2


async def test_a_hook_that_raises_leaves_the_run_parked_and_fails_the_event() -> None:
    """R8.10 (AL29): the cancel is rolled back with what the hook wrote; the
    event fails, so the outbox delivers it again, and then it goes through."""
    store, lane, hooks = _world("effects")
    run_id, request_id = _waiting(store)
    hooks["effects"].fail = True
    assert store.kill is not None and request_id is not None
    with pytest.raises(RuntimeError):
        await lane.handle(TENANT, store.kill.switch_id)
    assert store.runs[run_id].status == "waiting_approval"
    assert store.requests[request_id].status is ApprovalStatus.PENDING
    assert store.audits == []

    hooks["effects"].fail = False
    assert await lane.handle(TENANT, store.kill.switch_id) == 1
    assert store.runs[run_id].status == "cancelled"


def test_the_hook_register_takes_a_name_once_and_nothing_once_frozen() -> None:
    hooks = RunCancelHooks()
    store = _Store(None)
    hooks.register("effects", _Hook(store))
    with pytest.raises(ValueError, match="twice"):
        hooks.register("effects", _Hook(store))
    hooks.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        hooks.register("other", _Hook(store))
    assert hooks.names() == ["effects"]


def test_the_worker_registers_no_hook_by_default() -> None:
    from dw_worker.main import build_run_cancel_hooks

    assert build_run_cancel_hooks().names() == []


# ---- helpers -------------------------------------------------------------------


def _run(**update: Any) -> RunContext:
    from test_executor import make_run_context

    return make_run_context().model_copy(update=update)


def _platform_row(freeze_id: uuid.UUID, operator: uuid.UUID) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=freeze_id, scope_type="platform", target_id=None, origin="platform", set_by=operator
    )
