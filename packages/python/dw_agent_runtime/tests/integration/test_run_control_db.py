"""The freeze against PostgreSQL, across processes, at the runner's doors and
at the admission doors of two stand-in lanes (agent-lifecycle ticket 01:
R7.1, R7.2, R7.7, R7.8, R7.14, R9.1, R9.2; AL11, AL16, AL17).

Every case plants its own company, so a switch never outlives its test; the
one platform freeze is lifted in a `finally`. A switch is set as the code
sets it (a company's as `dw_app`, an operator's as `dw_provisioner`) and a
company's freeze is lifted only as the trigger allows: with an approved
`studio.lifecycle.unfreeze` request decided by a second person.

The lanes are stand-ins: `studio_runs` (workflow-engine/04) and
`studio_inbound` (workflow-triggers) own the real ones and the refusal table
by `trigger_kind`; here a lane is a list and the table is the rows of
workflow-engine R5.12-R5.18 this ticket's contract is tested against.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest
import sqlalchemy as sa
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pg_test_db import provisioner_url
from runtime_harness import RuntimeUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_control import SqlRunControl
from dw_agent_runtime.adapters.run_store import RunStatus, SqlWorkerRunStore, resume_context
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML, build_demo_graph
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.domain.audit import system_actor
from dw_platform.testing.rbac import PlantedTenant, plant_person, plant_tenant

pytestmark = pytest.mark.integration

LANE_ACTOR = system_actor("studio_inbound").value
HALTING = "demo_halting"


class _UnmeteredPlan:
    async def runs_per_day(self, plan_id: str) -> int | None:
        return None

    async def spend_usd_per_day(self, plan_id: str) -> Decimal | None:
        return None


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


# A run whose one node asks the tool door until a freeze set during the run
# reaches it, as the executor's step would: the refusal ends the run.
async def _acting(state: dict[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
    control = _ACTING_CONTROL[runtime.context.run_id]
    await _SET_DURING_RUN[runtime.context.run_id]()
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        await control.require_open(runtime.context, door=RunControlDoor.TOOL)
        if asyncio.get_running_loop().time() > deadline:
            return {"acted": True}
        await asyncio.sleep(0.05)


_ACTING_CONTROL: dict[uuid.UUID, SqlRunControl] = {}
_SET_DURING_RUN: dict[uuid.UUID, Callable[[], Any]] = {}


def _halting_graph() -> StateGraph:  # type: ignore[type-arg]
    graph: StateGraph = StateGraph(dict)  # type: ignore[type-arg]
    graph.add_node("act", _acting)  # type: ignore[call-overload]
    graph.add_edge(START, "act")
    graph.add_edge("act", END)
    return graph


@dataclass
class World:
    urls: RuntimeUrls
    migrator: AsyncEngine
    provisioner: AsyncEngine
    app: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    tenant: PlantedTenant
    person: uuid.UUID
    decider: uuid.UUID
    service: uuid.UUID
    config_dir: Path
    controls: list[SqlRunControl] = field(default_factory=list)

    def control(self, *, ttl: float = 5.0, listen: bool = True) -> SqlRunControl:
        control = SqlRunControl(
            self.sessions,
            clock=SystemClock(),
            telemetry=RecordingTelemetry(),
            listen_dsn=_dsn(self.urls.app) if listen else None,
            system_actors=frozenset({LANE_ACTOR}),
            ttl_seconds=ttl,
        )
        self.controls.append(control)
        return control

    def run(self, **update: Any) -> RunContext:
        base = RunContext(
            run_id=uuid.uuid4(),
            run_mode="live",
            tenant_id=self.tenant.tenant_id,
            workspace_id=self.tenant.main,
            actor_id=self.person,
            worker_id="demo_approval",
            worker_version="1.0.0",
            channel="web",
            plan_id="professional",
            roles=frozenset({"member"}),
            scopes=frozenset({"demo.write", "demo.read"}),
            trace_id=f"trace-{uuid.uuid4().hex[:8]}",
            autonomy_ceiling="A4",
            autonomy_level="A4",
        )
        return base.model_copy(update=update)

    async def sql(self, engine: AsyncEngine, statement: str, **values: Any) -> Any:
        async with engine.begin() as conn:
            result = await conn.execute(sa.text(statement), values)
            return result.first() if result.returns_rows else None

    async def freeze(self, *, tenant: uuid.UUID | None = None) -> uuid.UUID:
        """The company's own freeze, written as `dw_app` under its RLS."""
        switch = uuid.uuid4()
        target = tenant or self.tenant.tenant_id
        async with self.app.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(target)}
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                    " origin, reason_code, reason, set_by)"
                    " VALUES (:id, :t, 'tenant', 'freeze', 'tenant', 'incident', 'sự cố', :by)"
                ),
                {"id": switch, "t": target, "by": self.person},
            )
        return switch

    async def lift(self, switch: uuid.UUID) -> None:
        """As the unfreeze handler does: an approved, second-person request."""
        approval = uuid.uuid4()
        tenant = self.tenant.tenant_id
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                    " approval_type, requested_by, payload, status)"
                    " VALUES (:a, :t, :w, 'studio.lifecycle.unfreeze', :r,"
                    " jsonb_build_object('switch_id', CAST(:s AS text)), 'approved')"
                ),
                {
                    "a": approval,
                    "t": tenant,
                    "w": self.tenant.main,
                    "r": self.person,
                    "s": str(switch),
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.approval_decisions (id, request_id, tenant_id,"
                    " workspace_id, decided_by, outcome, decided_at)"
                    " VALUES (gen_random_uuid(), :a, :t, :w, :d, 'approved', now())"
                ),
                {"a": approval, "t": tenant, "w": self.tenant.main, "d": self.decider},
            )
        async with self.app.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            await conn.execute(
                sa.text(
                    "UPDATE platform.control_switches SET lifted_at = now(), lifted_by = :d,"
                    " lift_approval_id = :a WHERE id = :s"
                ),
                {"d": self.decider, "a": approval, "s": switch},
            )

    async def member(self, user: uuid.UUID, status: str | None) -> None:
        if status is None:
            await self.sql(
                self.migrator,
                "DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u",
                t=self.tenant.tenant_id,
                u=user,
            )
        else:
            await self.sql(
                self.migrator,
                "UPDATE platform.tenant_members SET status = :s WHERE tenant_id = :t"
                " AND user_id = :u",
                s=status,
                t=self.tenant.tenant_id,
                u=user,
            )

    async def company(self, status: str) -> None:
        await self.sql(
            self.migrator,
            "UPDATE platform.tenants SET status = :s WHERE id = :t",
            s=status,
            t=self.tenant.tenant_id,
        )

    async def run_row(self, run_id: uuid.UUID) -> Any:
        return await self.sql(
            self.migrator,
            "SELECT status, error FROM platform.worker_runs WHERE id = :r",
            r=run_id,
        )

    async def cancelled_audit(self, run_id: uuid.UUID) -> Any:
        return await self.sql(
            self.migrator,
            "SELECT details FROM platform.audit_events WHERE run_id = :r"
            " AND action = 'run.cancelled'",
            r=run_id,
        )

    def stack(self, control: SqlRunControl) -> Stack:
        return Stack(self, control)


@dataclass
class Stack:
    """One process's runner and approval flow over one `SqlRunControl`."""

    world: World
    control: SqlRunControl
    runner: LangGraphWorkflowRunner = field(init=False)
    approvals: ApproveAndResumeService = field(init=False)
    run_store: SqlWorkerRunStore = field(init=False)

    def __post_init__(self) -> None:
        sessions = self.world.sessions
        graphs = GraphRegistry()
        graphs.register("demo_approval", "1.0.0", build_demo_graph)
        graphs.register(HALTING, "1.0.0", _halting_graph)
        workers = WorkerRegistry(graph_registry=graphs)
        workers.load_file(self.world.config_dir / "demo_approval.yaml")
        workers.load_file(self.world.config_dir / f"{HALTING}.yaml")
        uow = SqlPlatformUnitOfWorkFactory(sessions)
        self.run_store = SqlWorkerRunStore(sessions, stale_run_after_seconds=3600)
        self.runner = LangGraphWorkflowRunner(
            worker_registry=workers,
            graph_registry=graphs,
            checkpoint_saver=SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
            run_store=self.run_store,
            uow_factory=uow,
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
            allowance=_UnmeteredPlan(),
            budget=RunBudgetLedger(),
            approval_policy=AutonomyApprovalPolicy(),
            run_control=self.control,
        )
        self.approvals = ApproveAndResumeService(
            uow_factory=uow,
            runner=self.runner,
            run_store=self.run_store,
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
            run_control=self.control,
        )

    async def paused(self) -> tuple[RunContext, uuid.UUID, uuid.UUID]:
        """A run of the person waiting for an approval, and the approval."""
        context = self.world.run()
        run_id = await self.runner.start(run_context=context, input_payload={"subject": "x"})
        record = await self.run_store.get(context, run_id)
        assert record.status is RunStatus.WAITING_APPROVAL
        assert record.approval_request_id is not None
        return context, run_id, record.approval_request_id

    async def decide(self, approval: uuid.UUID) -> Any:
        decider = AccessContext(
            tenant_id=self.world.tenant.tenant_id,
            workspace_id=self.world.tenant.main,
            principal_id=self.world.decider,
            roles=frozenset({"approver"}),
            scopes=frozenset({"approvals.decide"}),
            plan_id="professional",
        )
        return await self.approvals.decide(
            approval_id=approval,
            approve=True,
            comment="đồng ý",
            context=decider,
            authorization=ScopeAuthorizationService(),
        )


@pytest.fixture
async def world(urls: RuntimeUrls, tmp_path: Path) -> AsyncIterator[World]:
    (tmp_path / "demo_approval.yaml").write_text(DEMO_WORKER_YAML, encoding="utf-8")
    (tmp_path / f"{HALTING}.yaml").write_text(
        DEMO_WORKER_YAML.replace("demo_approval", HALTING), encoding="utf-8"
    )
    migrator = create_async_engine(urls.migrator, poolclass=NullPool)
    provisioner = create_async_engine(provisioner_url(urls.migrator), poolclass=NullPool)
    app = create_async_engine(urls.app, poolclass=NullPool)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        person = await plant_person(conn, tenant.tenant_id)
        decider = await plant_person(conn, tenant.tenant_id)
        service = await plant_person(conn, tenant.tenant_id, kind="service")
    world = World(
        urls=urls,
        migrator=migrator,
        provisioner=provisioner,
        app=app,
        sessions=async_sessionmaker(app, expire_on_commit=False),
        tenant=tenant,
        person=person,
        decider=decider,
        service=service,
        config_dir=tmp_path,
    )
    try:
        yield world
    finally:
        for control in world.controls:
            await control.close()
        for engine in (app, provisioner, migrator):
            await engine.dispose()


async def _refused(
    control: SqlRunControl, run: RunContext, door: RunControlDoor
) -> HaltReason | None:
    try:
        await control.require_open(run, door=door)
    except RunHaltedError as halted:
        return halted.reason
    return None


async def _until_refused(
    control: SqlRunControl, run: RunContext, door: RunControlDoor, *, within: float
) -> float:
    started = asyncio.get_running_loop().time()
    while (await _refused(control, run, door)) is None:
        assert asyncio.get_running_loop().time() - started < within, "the switch was not seen"
        await asyncio.sleep(0.05)
    return asyncio.get_running_loop().time() - started


# ---- R7.1: seen by every process -----------------------------------------------


async def test_process_b_sees_a_freeze_process_a_set_through_its_notification(
    world: World,
) -> None:
    """R7.1 (AL11): B holds a snapshot it would keep for ten minutes; the
    NOTIFY naming the company drops it, so B refuses well within 5 s."""
    b = world.control(ttl=600)
    run = world.run()
    assert await _refused(b, run, RunControlDoor.TOOL) is None
    await asyncio.sleep(0.5)  # B's listener is up
    await world.freeze()
    assert await _until_refused(b, run, RunControlDoor.TOOL, within=5) < 5


async def test_with_its_notification_lost_a_freeze_is_seen_within_the_ttl(world: World) -> None:
    """R7.1: no listener at all, the TTL alone."""
    b = world.control(listen=False)
    run = world.run()
    assert await _refused(b, run, RunControlDoor.MODEL) is None
    await world.freeze()
    assert await _refused(b, run, RunControlDoor.MODEL) is None  # the cached snapshot
    assert await _until_refused(b, run, RunControlDoor.MODEL, within=6) <= 6


async def test_a_platform_freeze_is_seen_by_every_process_within_five_seconds(
    world: World,
) -> None:
    """R7.1 (AL11): set by `dw_provisioner`, seen by a process caching the
    company's snapshot for ten minutes."""
    b = world.control(ttl=600)
    run = world.run()
    assert await _refused(b, run, RunControlDoor.MODEL) is None
    await asyncio.sleep(0.5)
    freeze = uuid.uuid4()
    await world.sql(
        world.provisioner,
        "INSERT INTO platform.platform_freezes (id, reason_code, reason, set_by)"
        " VALUES (:id, 'maintenance', 'bảo trì', :by)",
        id=freeze,
        by=world.decider,
    )
    try:
        await _until_refused(b, run, RunControlDoor.MODEL, within=5)
        assert await _refused(b, run, RunControlDoor.MODEL) is HaltReason.PLATFORM_FROZEN
    finally:
        await world.sql(
            world.provisioner,
            "UPDATE platform.platform_freezes SET lifted_at = now(), lifted_by = :by"
            " WHERE id = :id",
            id=freeze,
            by=world.decider,
        )


async def test_a_freeze_of_one_company_never_refuses_another(world: World) -> None:
    """R7.1 (AL16)."""
    async with world.migrator.begin() as conn:
        other = await plant_tenant(conn)
        stranger = await plant_person(conn, other.tenant_id)
    control = world.control()
    await world.freeze()
    run = world.run()
    theirs = world.run(tenant_id=other.tenant_id, workspace_id=other.main, actor_id=stranger)
    assert await _refused(control, run, RunControlDoor.START) is HaltReason.TENANT_FROZEN
    assert await _refused(control, theirs, RunControlDoor.START) is None


# ---- R7.1: a running run ends cancelled with its reason --------------------------


async def test_a_freeze_set_during_a_run_cancels_it_at_its_next_door(world: World) -> None:
    """R7.1 (AL11), R7.14: the door inside the run refuses within 5 s, the
    runner records `cancelled` with the reason in `error` and in the
    `run.cancelled` audit."""
    control = world.control()
    stack = world.stack(control)
    context = world.run(worker_id=HALTING)
    _ACTING_CONTROL[context.run_id] = control
    _SET_DURING_RUN[context.run_id] = world.freeze

    with pytest.raises(RunHaltedError):
        await stack.runner.start(run_context=context, input_payload={})

    row = await world.run_row(context.run_id)
    assert row.status == "cancelled"
    assert row.error["reason_code"] == "tenant_frozen"
    audit = await world.cancelled_audit(context.run_id)
    assert audit.details == {"reason_code": "tenant_frozen", "door": "tool"}


async def test_a_new_run_of_a_frozen_company_is_cancelled_at_its_start(world: World) -> None:
    """R7.1: the start door, before the graph runs."""
    control = world.control()
    stack = world.stack(control)
    await world.freeze()
    context = world.run()
    with pytest.raises(RunHaltedError):
        await stack.runner.start(run_context=context, input_payload={"subject": "x"})
    row = await world.run_row(context.run_id)
    assert (row.status, row.error["reason_code"]) == ("cancelled", "tenant_frozen")


# ---- R7.14: paused runs stay paused ----------------------------------------------


async def test_a_decision_on_a_paused_run_is_refused_while_frozen_then_resumes(
    world: World,
) -> None:
    """R7.14 (AL11): 409 `tenant_frozen`, the request still `pending`, the run
    still `waiting_approval`; lifted, the same decision resumes the run."""
    control = world.control()
    stack = world.stack(control)
    _, run_id, approval = await stack.paused()
    switch = await world.freeze()
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')

    with pytest.raises(RunHaltedError) as halted:
        await stack.decide(approval)
    assert halted.value.details["reason_code"] == "tenant_frozen"
    pending = await world.sql(
        world.migrator, "SELECT status FROM platform.approval_requests WHERE id = :a", a=approval
    )
    assert pending.status == "pending"
    assert (await world.run_row(run_id)).status == "waiting_approval"

    await world.lift(switch)
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')
    await stack.decide(approval)
    assert (await world.run_row(run_id)).status == "completed"


async def test_a_timer_due_while_frozen_keeps_its_run_waiting_then_runs_on(
    world: World,
) -> None:
    """R7.14 (AL11): the resume door holds a `waiting_timer` run unchanged;
    after the lift the same resume runs it on."""
    control = world.control()
    stack = world.stack(control)
    context, run_id, _ = await stack.paused()
    await world.sql(
        world.migrator,
        "UPDATE platform.worker_runs SET status = 'waiting_timer' WHERE id = :r",
        r=run_id,
    )
    switch = await world.freeze()
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')
    record = await stack.run_store.get(context, run_id)
    woken = resume_context(record, tenant_id=world.tenant.tenant_id, channel="dw_timers")

    with pytest.raises(RunHaltedError):
        await stack.runner.resume(run_context=woken, run_id=run_id, resume_payload={})
    assert (await world.run_row(run_id)).status == "waiting_timer"

    await world.lift(switch)
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')
    await stack.runner.resume(run_context=woken, run_id=run_id, resume_payload={"approved": True})
    assert (await world.run_row(run_id)).status == "completed"


# ---- R9: the principal and the company -------------------------------------------


@pytest.mark.parametrize("status", [None, "suspended"])
async def test_a_paused_run_of_a_removed_or_suspended_member_is_cancelled_at_resume(
    world: World, status: str | None
) -> None:
    """R9.1 (AL17): the resume door reads the run's principal now."""
    stack = world.stack(world.control())
    context, run_id, _ = await stack.paused()
    await world.member(world.person, status)
    record = await stack.run_store.get(context, run_id)
    with pytest.raises(RunHaltedError) as halted:
        await stack.runner.resume(
            run_context=resume_context(record, tenant_id=world.tenant.tenant_id, channel="web"),
            run_id=run_id,
            resume_payload={"approved": True},
        )
    assert halted.value.reason is HaltReason.PRINCIPAL_INACTIVE
    row = await world.run_row(run_id)
    assert (row.status, row.error["reason_code"]) == ("cancelled", "principal_inactive")


async def test_a_new_run_of_a_suspended_member_is_cancelled_before_any_model_call(
    world: World,
) -> None:
    """R9.1 (AL17): `suspended` set by SQL, then a new run."""
    stack = world.stack(world.control())
    await world.member(world.person, "suspended")
    context = world.run()
    with pytest.raises(RunHaltedError):
        await stack.runner.start(run_context=context, input_payload={"subject": "x"})
    row = await world.run_row(context.run_id)
    assert (row.status, row.error["reason_code"]) == ("cancelled", "principal_inactive")


async def test_a_new_run_of_a_locked_company_is_cancelled(world: World) -> None:
    """R9.2 (AL17)."""
    stack = world.stack(world.control())
    await world.company("locked")
    context = world.run()
    with pytest.raises(RunHaltedError):
        await stack.runner.start(run_context=context, input_payload={"subject": "x"})
    row = await world.run_row(context.run_id)
    assert (row.status, row.error["reason_code"]) == ("cancelled", "tenant_locked")


async def test_a_paused_run_of_a_company_offboarding_is_cancelled_at_resume(
    world: World,
) -> None:
    """R9.2 (AL17)."""
    stack = world.stack(world.control())
    _, run_id, approval = await stack.paused()
    await world.company("offboarding")
    with pytest.raises(RunHaltedError) as halted:
        await stack.decide(approval)
    assert halted.value.reason is HaltReason.TENANT_OFFBOARDING
    row = await world.run_row(run_id)
    assert (row.status, row.error["reason_code"]) == ("cancelled", "tenant_offboarding")


# ---- the admission contract, with stand-in lanes ---------------------------------

Trigger = Literal[
    "chat",
    "manual",
    "test",
    "replay",
    "eval",
    "datahub",
    "provider_app",
    "record_event",
    "schedule",
]
INTERACTIVE = frozenset({"chat", "manual", "test", "replay", "eval"})
SERVICE_TRIGGERED = frozenset({"datahub", "provider_app", "record_event"})


def _dispatch(trigger: Trigger, reason: HaltReason) -> Literal["cancel", "hold"]:
    """workflow-engine R5.12-R5.18, the rows this ticket's port answers for."""
    if reason in (HaltReason.TENANT_FROZEN, HaltReason.PLATFORM_FROZEN):
        return "cancel" if trigger in INTERACTIVE else "hold"
    if reason is HaltReason.PRINCIPAL_INACTIVE:
        return "hold" if trigger in SERVICE_TRIGGERED else "cancel"
    if reason is HaltReason.CONTROL_STATE_UNAVAILABLE:
        return "hold"
    return "cancel"


@dataclass
class QueuedRun:
    trigger: Trigger
    run: RunContext
    status: str = "queued"
    reason: str | None = None


@dataclass
class StudioRunsLane:
    """Takes queued runs in order; asks the admission door of each."""

    control: SqlRunControl
    queue: list[QueuedRun] = field(default_factory=list)
    model_calls: list[uuid.UUID] = field(default_factory=list)

    async def tick(self) -> None:
        for queued in [q for q in self.queue if q.status == "queued"]:
            try:
                await self.control.require_open(queued.run, door=RunControlDoor.ADMISSION)
            except RunHaltedError as halted:
                if _dispatch(queued.trigger, halted.reason) == "cancel":
                    queued.status, queued.reason = "cancelled", halted.reason.value
                else:
                    queued.reason = halted.reason.value
                continue
            queued.status = "ran"
            self.model_calls.append(queued.run.run_id)


@pytest.mark.parametrize("trigger", ["chat", "replay", "eval"])
async def test_an_interactive_run_or_a_trial_at_admission_while_frozen_is_cancelled(
    world: World, trigger: Trigger
) -> None:
    """R7.7 (AL11): cancelled `tenant_frozen`, no model call."""
    lane = StudioRunsLane(world.control())
    lane.queue.append(QueuedRun(trigger, world.run()))
    await world.freeze()
    await lane.tick()
    assert (lane.queue[0].status, lane.queue[0].reason) == ("cancelled", "tenant_frozen")
    assert lane.model_calls == []


async def test_a_queued_trigger_run_is_held_while_frozen_and_runs_in_order_once_lifted(
    world: World,
) -> None:
    """R7.8 (AL11): held `queued`, never cancelled; after the lift, in order."""
    control = world.control()
    lane = StudioRunsLane(control)
    runs = [QueuedRun("datahub", world.run(run_as_principal_id=world.service)) for _ in range(3)]
    lane.queue.extend(runs)
    switch = await world.freeze()
    await lane.tick()
    assert [q.status for q in runs] == ["queued"] * 3
    assert lane.model_calls == []

    await world.lift(switch)
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')
    await lane.tick()
    assert lane.model_calls == [q.run.run_id for q in runs]


async def test_a_suspended_service_principals_datahub_run_waits_for_it_then_runs(
    world: World,
) -> None:
    """R9.1 (AL17): held `queued` with `principal_inactive`, no model call;
    the account active again, it runs in arrival order."""
    lane = StudioRunsLane(world.control())
    queued = QueuedRun("datahub", world.run(run_as_principal_id=world.service))
    lane.queue.append(queued)
    await world.member(world.service, "suspended")
    await lane.tick()
    assert (queued.status, queued.reason) == ("queued", "principal_inactive")
    assert lane.model_calls == []

    await world.member(world.service, "active")
    await lane.tick()
    assert queued.status == "ran"


async def test_a_lanes_own_run_passes_admission_without_a_member_row(world: World) -> None:
    """R9.1 (AL17): `system_actor(<lane>)`, no `tenant_members` row, runs; a
    person's id with no row does not."""
    lane = StudioRunsLane(world.control())
    own = QueuedRun("chat", world.run(actor_id=LANE_ACTOR))
    nobody = QueuedRun("chat", world.run(actor_id=uuid.uuid4()))
    lane.queue.extend([own, nobody])
    await lane.tick()
    assert own.status == "ran"
    assert (nobody.status, nobody.reason) == ("cancelled", "principal_inactive")


@dataclass
class InboundEvent:
    received_at: datetime
    requested: bool = False


@dataclass
class StudioInboundLane:
    """A trigger's stored events: asks `admission_state`, holds them all
    while it refuses, then requests runs by `received_at`."""

    control: SqlRunControl
    tenant: uuid.UUID
    events: list[InboundEvent] = field(default_factory=list)
    requested: list[datetime] = field(default_factory=list)

    async def tick(self) -> HaltReason | None:
        state = await self.control.admission_state(self.tenant)
        if state is not None:
            return state
        for event in sorted(self.events, key=lambda e: e.received_at):
            if not event.requested:
                event.requested = True
                self.requested.append(event.received_at)
        return None


async def test_a_triggers_events_are_held_while_frozen_and_requested_in_order_after(
    world: World,
) -> None:
    """R7.2: `admission_state` answers `tenant_frozen`, the lane leaves its
    events; lifted, it answers None and the runs are asked by `received_at`."""
    control = world.control()
    now = datetime.now(UTC)
    lane = StudioInboundLane(control, world.tenant.tenant_id)
    lane.events = [InboundEvent(now - timedelta(minutes=m)) for m in (1, 3, 2)]
    switch = await world.freeze()
    assert await lane.tick() is HaltReason.TENANT_FROZEN
    assert lane.requested == []

    await world.lift(switch)
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')
    assert await lane.tick() is None
    assert lane.requested == sorted(e.received_at for e in lane.events)
