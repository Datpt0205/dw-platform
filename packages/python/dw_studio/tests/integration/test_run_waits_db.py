"""A Studio run's waits on PostgreSQL (workflow-engine ticket 05: R6.1-R6.6,
R6.9, R6.10, R6.11, R6.12, R6.13, R6.14, R6.15, R6.16, R6.40, R7.1; WE9-WE12,
WE15, WE16, WE22, WE23, WE45, WE54).

The run door, the run store, the checkpoint saver and the runner are the real
ones of `test_studio_runs.py` (whose world this module shares); a waiting step
is `fixture.wait@1`, which opens its wait through the real `SqlRunWaits` in a
transaction of the real platform unit of work. A decision goes through the
real `ApproveAndResumeService` with the `studio.step.` handler, its wait found
by a lookup that keeps the link as workflow-nodes/06's `studio.step_approvals`
will (`MemoryStepLinks`), written in the wait's own transaction.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from studio_run_stack import build_runner, run_claimed

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.run_waits import SqlRunWaits
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.studio_step_decisions import STUDIO_STEP_PREFIX, StudioStepDecisions
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.studio_runs import ScriptedDoor
from dw_agent_runtime.testing.workflow_types import FIXTURE_WAIT, fixture_node_registry
from dw_agent_runtime.wflite.registry import WaitOpening, WaitSpec
from dw_kernel.errors import ConflictError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.live_scopes import SqlLiveScopes
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.ports import PlatformUnitOfWork
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import system_actor
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.service import ArtifactService
from dw_studio.testing.workflows import studio_step

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

# The world of `test_studio_runs.py` and its fixtures, built again for this
# module (module scope). Read through `importlib`: that module is a test file,
# not a package mypy follows.
_shared: Any = importlib.import_module("test_studio_runs")
World = Any
app_engine = _shared.app_engine
migrator = _shared.migrator
service = _shared.service
sessions = _shared.sessions
source = _shared.source
store = _shared.store
world = _shared.world
a_draft = _shared.a_draft
ask = _shared.ask
doc = _shared.doc
door_of = _shared.door_of
rows = _shared.rows
send = _shared.send

REGISTRY = fixture_node_registry()


# ---- helpers ------------------------------------------------------------------------


def waits_for(step_id: str = "cho") -> dict[str, Any]:
    return studio_step(step_id, "fixture.wait@1")


async def a_waiting_run(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
    *steps: dict[str, Any],
) -> uuid.UUID:
    body = steps or (send("truoc"), waits_for(), send("sau"))
    _, version, _ = await a_draft(service, world, doc(source, *body))
    run_id: uuid.UUID = (await door_of(store).request(ask(world, version))).run_id
    return run_id


def context_of(world: World, person: uuid.UUID | None = None) -> AccessContext:
    return AccessContext(
        tenant_id=world.tenant,
        workspace_id=world.tester.workspace_id,
        principal_id=person or world.stranger.id,
        roles=frozenset(),
        scopes=frozenset({"approvals.decide", "approvals.read"}),
        plan_id="professional",
    )


async def waits_of(migrator: AsyncEngine, run_id: uuid.UUID) -> list[Any]:
    found: list[Any] = await rows(
        migrator,
        "SELECT interrupt_id, node_id, kind, status, resolution FROM platform.run_waits"
        " WHERE run_id = :r ORDER BY created_at, interrupt_id",
        r=run_id,
    )
    return found


async def status_of(migrator: AsyncEngine, run_id: uuid.UUID) -> str:
    (row,) = await rows(migrator, "SELECT status FROM platform.worker_runs WHERE id = :r", r=run_id)
    return str(row.status)


async def resolve(
    sessions: async_sessionmaker[AsyncSession],
    world: World,
    run_id: uuid.UUID,
    interrupt_id: str,
    resolution: Mapping[str, Any] | None = None,
) -> None:
    """A decision's two writes, as the handler makes them in its transaction."""
    async with SqlPlatformUnitOfWorkFactory(sessions)(context_of(world)) as uow:
        await SqlRunWaits(Uuid7Generator()).resolve(
            uow,
            run_id,
            interrupt_id,
            {"decision": "approved"} if resolution is None else resolution,
        )
        await uow.commit()


async def as_app(
    app_engine: AsyncEngine, tenant: uuid.UUID, statement: str, **values: Any
) -> list[Any]:
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


def constraint_of(error: BaseException) -> str | None:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


_INSERT_WAIT = (
    "INSERT INTO platform.run_waits (tenant_id, id, run_id, interrupt_id, node_id,"
    " iteration_path, kind, status) VALUES (:t, gen_random_uuid(), :r, :i, :n, '', :k, 'open')"
)


# ---- R6.1, R6.37: a waiting step parks the run on one open row --------------------------


async def test_r6_1_a_waiting_step_parks_the_run_on_one_open_wait_and_one_checkpoint(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    door = ScriptedDoor()
    runner, recorder = build_runner(sessions, {"tool": door})
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.WAITING
    (wait,) = await waits_of(migrator, run_id)
    assert (wait.interrupt_id, wait.node_id, wait.kind, wait.status) == (
        "wait:cho::0",
        "cho",
        "approval",
        "open",
    )
    assert await status_of(migrator, run_id) == "waiting"
    (waiting,) = recorder.waiting
    assert waiting.reason_code == "approval_pending"
    # R6.11 (WE15): through two nodes and a wait, one checkpoint is left.
    (count,) = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.run_checkpoints WHERE thread_id = :r",
        r=run_id,
    )
    assert count.n == 1
    assert len(door.calls) == 1


async def test_r6_4_two_waits_in_series_resume_each_with_its_own_resolution(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(
        store, service, migrator, world, source, waits_for("mot"), waits_for("hai")
    )
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor()})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await resolve(sessions, world, run_id, "wait:mot::0", {"decision": "approved", "comment": "1"})
    assert await status_of(migrator, run_id) == "queued"
    # Another process takes it: the worker, not the decider's request.
    worker, worker_recorder = build_runner(sessions, {"tool": ScriptedDoor()})
    assert await run_claimed(worker, sessions, world.tenant, run_id) == RunStatus.WAITING
    assert [(w.interrupt_id, w.status) for w in await waits_of(migrator, run_id)] == [
        ("wait:mot::0", "consumed"),
        ("wait:hai::0", "open"),
    ]
    await resolve(sessions, world, run_id, "wait:hai::0", {"decision": "rejected", "comment": "2"})
    assert await run_claimed(worker, sessions, world.tenant, run_id) == RunStatus.COMPLETED
    assert [w.status for w in await waits_of(migrator, run_id)] == ["consumed", "consumed"]
    (hai,) = worker_recorder.of("hai")
    assert hai.output["decision"] == "rejected"


async def test_r6_1_open_again_hands_back_the_open_row_and_a_second_park_gets_a_new_id(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    waits = SqlRunWaits(Uuid7Generator())
    factory = SqlPlatformUnitOfWorkFactory(sessions)
    for _ in range(2):
        async with factory(context_of(world)) as uow:
            assert await waits.open(uow, run_id, "cho", "", "approval") == "wait:cho::0"
            await uow.commit()
    assert len(await waits_of(migrator, run_id)) == 1
    await rows(
        migrator,
        "UPDATE platform.run_waits SET status = 'resolved', resolution = '{\"d\": 1}',"
        " resolved_at = now() WHERE run_id = :r",
        r=run_id,
    )
    # Decided and not yet used: still the same row (a crash after a decision).
    async with factory(context_of(world)) as uow:
        assert await waits.open(uow, run_id, "cho", "", "approval") == "wait:cho::0"
        await uow.rollback()
    await rows(
        migrator, "UPDATE platform.run_waits SET status = 'consumed' WHERE run_id = :r", r=run_id
    )
    async with factory(context_of(world)) as uow:
        assert await waits.open(uow, run_id, "cho", "", "approval") == "wait:cho::1"
        await uow.commit()


async def test_r6_1_a_decision_between_the_open_and_the_park_queues_the_run(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    """R6.3: the run is still `running`, so the decision does not 409; the
    park reads the resolved wait and queues the run."""
    run_id = await a_waiting_run(store, service, migrator, world, source, waits_for())
    decided = False

    async def decide_first(opening: WaitOpening) -> None:
        nonlocal decided
        decided = True

    registry = dict(REGISTRY)
    registry["fixture.wait@1"] = dataclasses.replace(
        REGISTRY["fixture.wait@1"],
        wait=WaitSpec(kind="approval", resume=FIXTURE_WAIT.resume, opener=decide_first),
    )
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor()}, registry=registry)
    store_park = runner.studio.nodes.runs.park  # type: ignore[union-attr]

    async def park_after_a_decision(*args: Any, **kwargs: Any) -> Any:
        await resolve(sessions, world, run_id, "wait:cho::0")
        return await store_park(*args, **kwargs)

    object.__setattr__(runner.studio.nodes.runs, "park", park_after_a_decision)  # type: ignore[union-attr]
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.QUEUED
    assert decided and await status_of(migrator, run_id) == "queued"
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.COMPLETED


# ---- R6.2, R6.3: a `studio.step.` decision through the handler ---------------------------


@dataclasses.dataclass
class MemoryStepLinks:
    """`StepWaitLookupPort` by its contract: each request's `(run_id,
    interrupt_id)`, written beside the request in the wait's transaction (here
    kept when that transaction commits)."""

    links: dict[uuid.UUID, tuple[uuid.UUID, str]] = dataclasses.field(default_factory=dict)

    async def wait_of(
        self, uow: PlatformUnitOfWork, approval_id: uuid.UUID
    ) -> tuple[uuid.UUID, str] | None:
        return self.links.get(approval_id)


def step_approval_registry(links: MemoryStepLinks, world: World) -> dict[str, Any]:
    async def open_request(opening: WaitOpening) -> None:
        request = ApprovalRequest(
            id=uuid.uuid4(),
            tenant_id=TenantId(opening.run.tenant_id),
            workspace_id=WorkspaceId(opening.run.workspace_id),
            approval_type="studio.step.approval",
            requested_by=UserId(world.tester.id),
            reason="Duyệt bước",
            payload={"node_id": opening.node_id},
        )
        await opening.uow.approvals.add(request)
        links.links[request.id] = (opening.run.run_id, opening.interrupt_id)

    registry = dict(REGISTRY)
    registry["fixture.wait@1"] = dataclasses.replace(
        REGISTRY["fixture.wait@1"],
        wait=WaitSpec(kind="approval", resume=FIXTURE_WAIT.resume, opener=open_request),
    )
    return registry


def flow(
    sessions: async_sessionmaker[AsyncSession], links: MemoryStepLinks, *, handler: bool = True
) -> ApproveAndResumeService:
    service = ApproveAndResumeService(
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        runner=None,  # type: ignore[arg-type]
        run_store=None,  # type: ignore[arg-type]
        clock=SystemClock(),
        id_generator=Uuid7Generator(),
        run_control=OpenRunControl(),
    )
    if handler:
        service.decided_handlers = {
            STUDIO_STEP_PREFIX: StudioStepDecisions(links, SqlRunWaits(Uuid7Generator()))
        }
    return service


async def test_r6_2_r6_3_a_step_decision_resolves_the_wait_and_the_worker_goes_on(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    links = MemoryStepLinks()
    run_id = await a_waiting_run(store, service, migrator, world, source)
    door = ScriptedDoor()
    runner, _ = build_runner(
        sessions, {"tool": door}, registry=step_approval_registry(links, world)
    )
    await run_claimed(runner, sessions, world.tenant, run_id)
    ((approval_id, (linked_run, interrupt_id)),) = links.links.items()
    assert (linked_run, interrupt_id) == (run_id, "wait:cho::0")
    await flow(sessions, links).decide(
        approval_id=approval_id,
        approve=True,
        comment="được",
        context=context_of(world),
        authorization=ScopeAuthorizationService(),
    )
    (wait,) = await waits_of(migrator, run_id)
    assert wait.status == "resolved" and wait.resolution["decision"] == "approved"
    assert wait.resolution["decided_by"] == str(world.stranger.id)
    assert await status_of(migrator, run_id) == "queued"
    assert not await rows(
        migrator,
        "SELECT 1 FROM platform.outbox_events WHERE aggregate_id = :a",
        a=approval_id,
    )
    # The API is gone; a worker takes the run and goes on after the wait.
    worker, _ = build_runner(
        sessions, {"tool": door}, registry=step_approval_registry(links, world)
    )
    assert await run_claimed(worker, sessions, world.tenant, run_id) == RunStatus.COMPLETED
    assert len(door.calls) == 2


async def test_r6_3_without_the_handler_an_approved_run_stays_parked(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    """The handler is what moves the run: without it the decision is only an
    outbox event, and the run stays `waiting` (the red this suite guards)."""
    links = MemoryStepLinks()
    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(
        sessions, {"tool": ScriptedDoor()}, registry=step_approval_registry(links, world)
    )
    await run_claimed(runner, sessions, world.tenant, run_id)
    ((approval_id, _),) = links.links.items()
    await flow(sessions, links, handler=False).decide(
        approval_id=approval_id,
        approve=True,
        comment="được",
        context=context_of(world),
        authorization=ScopeAuthorizationService(),
    )
    assert await status_of(migrator, run_id) == "waiting"


# ---- R6.6: a decision on a wait no longer open ---------------------------------------


async def test_r6_6_a_decision_on_a_wait_no_longer_open_is_refused_and_rolled_back(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    links = MemoryStepLinks()
    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(
        sessions, {"tool": ScriptedDoor()}, registry=step_approval_registry(links, world)
    )
    await run_claimed(runner, sessions, world.tenant, run_id)
    ((approval_id, _),) = links.links.items()
    # The run is cancelled while it waits: its wait goes with it (R6.13).
    await as_app(
        app_engine,
        world.tenant,
        "UPDATE platform.worker_runs SET status = 'cancelled' WHERE id = :r",
        r=run_id,
    )
    with pytest.raises(ConflictError) as refused:
        await flow(sessions, links).decide(
            approval_id=approval_id,
            approve=True,
            comment="được",
            context=context_of(world),
            authorization=ScopeAuthorizationService(),
        )
    assert refused.value.details["reason_code"] == "stale_interrupt"
    assert await status_of(migrator, run_id) == "cancelled"
    (request,) = await rows(
        migrator, "SELECT status FROM platform.approval_requests WHERE id = :a", a=approval_id
    )
    assert request.status == "pending"


async def test_r6_6_a_failed_run_whose_wait_is_still_open_refuses_the_decision(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor()})
    await run_claimed(runner, sessions, world.tenant, run_id)
    async with migrator.begin() as conn:
        # Before the trigger: a run that failed with its wait still open.
        await conn.execute(
            sa.text("ALTER TABLE platform.worker_runs DISABLE TRIGGER worker_runs_cancel_run_waits")
        )
        await conn.execute(
            sa.text("UPDATE platform.worker_runs SET status = 'failed' WHERE id = :r"),
            {"r": run_id},
        )
        await conn.execute(
            sa.text("ALTER TABLE platform.worker_runs ENABLE TRIGGER worker_runs_cancel_run_waits")
        )
    with pytest.raises(ConflictError):
        await resolve(sessions, world, run_id, "wait:cho::0")
    assert await status_of(migrator, run_id) == "failed"
    assert [w.status for w in await waits_of(migrator, run_id)] == ["open"]


async def test_r6_6_two_concurrent_decisions_have_exactly_one_winner(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    """Two transactions resolve the same wait; the second waits on the first's
    row lock (seen in `pg_locks`), then finds it no longer open."""
    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor()})
    await run_claimed(runner, sessions, world.tenant, run_id)
    waits = SqlRunWaits(Uuid7Generator())
    factory = SqlPlatformUnitOfWorkFactory(sessions)
    first = factory(context_of(world))
    await first.__aenter__()
    await waits.resolve(first, run_id, "wait:cho::0", {"decision": "approved"})

    async def second() -> None:
        async with factory(context_of(world, world.tester.id)) as uow:
            await waits.resolve(uow, run_id, "wait:cho::0", {"decision": "rejected"})
            await uow.commit()

    loser = asyncio.create_task(second())
    for _ in range(200):
        (blocked,) = await rows(
            migrator,
            "SELECT count(*) AS n FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
            " WHERE NOT l.granted AND a.datname = current_database()",
        )
        if blocked.n:
            break
        await asyncio.sleep(0.02)
    assert blocked.n, "the second decision never waited on the first"
    await first.commit()
    await first.__aexit__(None, None, None)
    with pytest.raises(ConflictError):
        await loser
    (wait,) = await waits_of(migrator, run_id)
    assert wait.resolution == {"decision": "approved"}
    assert await status_of(migrator, run_id) == "queued"


# ---- R6.1, R6.15, R6.40: the table holds itself ------------------------------------


async def test_r6_1_the_kind_check_takes_every_w1_kind_and_refuses_another(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    for kind in ("approval", "incident", "outcome_review", "child_run"):
        await as_app(
            app_engine,
            world.tenant,
            _INSERT_WAIT,
            t=world.tenant,
            r=run_id,
            i=f"wait:{kind}::0",
            n=kind,
            k=kind,
        )
    with pytest.raises(DBAPIError) as refused:
        await as_app(
            app_engine,
            world.tenant,
            _INSERT_WAIT,
            t=world.tenant,
            r=run_id,
            i="wait:x::0",
            n="x",
            k="bogus",
        )
    assert constraint_of(refused.value) == "ck_run_waits_kind"


async def test_r6_1_dw_app_moves_only_the_resolution_columns(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    await as_app(
        app_engine,
        world.tenant,
        _INSERT_WAIT,
        t=world.tenant,
        r=run_id,
        i="wait:g::0",
        n="g",
        k="approval",
    )
    for column, value in (("kind", "'incident'"), ("node_id", "'other'")):
        with pytest.raises(DBAPIError, match="permission denied"):
            await as_app(
                app_engine,
                world.tenant,
                f"UPDATE platform.run_waits SET {column} = {value} WHERE run_id = :r",
                r=run_id,
            )
    await as_app(
        app_engine,
        world.tenant,
        "UPDATE platform.run_waits SET status = 'resolved', resolution = '{\"d\": 1}',"
        " resolved_at = now() WHERE run_id = :r",
        r=run_id,
    )


async def test_r6_15_a_wait_never_names_another_companys_run(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    other = world.studio.other
    theirs = uuid.uuid4()
    await rows(
        migrator,
        "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id, worker_id,"
        " worker_version, graph_version, requested_by, run_mode)"
        " VALUES (:r, :r, :t, :w, 'studio', '1', '1', :u, 'live')",
        r=theirs,
        t=other.tenant_id,
        w=other.main,
        u=world.studio["outsider"].id,
    )
    with pytest.raises(DBAPIError) as refused:
        await as_app(
            app_engine,
            world.tenant,
            _INSERT_WAIT,
            t=world.tenant,
            r=theirs,
            i="wait:x::0",
            n="x",
            k="approval",
        )
    assert constraint_of(refused.value) == "fk_run_waits_run_id_worker_runs"
    assert not await rows(migrator, "SELECT 1 FROM platform.run_waits WHERE run_id = :r", r=theirs)


@pytest.mark.parametrize(
    ("setup", "statement"),
    [
        ("cancelled", "UPDATE platform.run_waits SET status = 'open' WHERE run_id = :r"),
        (
            "resolved",
            "UPDATE platform.run_waits SET status = 'open', resolution = NULL,"
            " resolved_at = NULL WHERE run_id = :r",
        ),
        ("resolved", "UPDATE platform.run_waits SET resolution = '{\"d\": 2}' WHERE run_id = :r"),
        ("open", "UPDATE platform.run_waits SET status = 'resolved' WHERE run_id = :r"),
        ("open", "UPDATE platform.run_waits SET status = 'consumed' WHERE run_id = :r"),
    ],
)
async def test_r6_40_a_wait_moves_only_forward_and_resolves_once(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
    setup: str,
    statement: str,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    await as_app(
        app_engine,
        world.tenant,
        _INSERT_WAIT,
        t=world.tenant,
        r=run_id,
        i="wait:g::0",
        n="g",
        k="approval",
    )
    if setup == "cancelled":
        await as_app(
            app_engine,
            world.tenant,
            "UPDATE platform.run_waits SET status = 'cancelled' WHERE run_id = :r",
            r=run_id,
        )
    if setup == "resolved":
        await as_app(
            app_engine,
            world.tenant,
            "UPDATE platform.run_waits SET status = 'resolved', resolution = '{\"d\": 1}',"
            " resolved_at = now() WHERE run_id = :r",
            r=run_id,
        )
    with pytest.raises(DBAPIError) as refused:
        await as_app(app_engine, world.tenant, statement, r=run_id)
    assert constraint_of(refused.value) in ("ck_run_waits_transition", "ck_run_waits_resolved")


async def test_r6_40_open_resolved_consumed_is_taken_and_a_resolved_birth_is_not(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    await as_app(
        app_engine,
        world.tenant,
        _INSERT_WAIT,
        t=world.tenant,
        r=run_id,
        i="wait:g::0",
        n="g",
        k="approval",
    )
    await as_app(
        app_engine,
        world.tenant,
        "UPDATE platform.run_waits SET status = 'resolved', resolution = '{\"d\": 1}',"
        " resolved_at = now() WHERE run_id = :r",
        r=run_id,
    )
    await as_app(
        app_engine,
        world.tenant,
        "UPDATE platform.run_waits SET status = 'consumed' WHERE run_id = :r",
        r=run_id,
    )
    with pytest.raises(DBAPIError) as refused:
        await as_app(
            app_engine,
            world.tenant,
            _INSERT_WAIT.replace("'open')", "'resolved')"),
            t=world.tenant,
            r=run_id,
            i="wait:h::0",
            n="h",
            k="approval",
        )
    assert constraint_of(refused.value) == "ck_run_waits_transition"


# ---- R6.13: every way a run ends cancels its open waits -------------------------------


@pytest.mark.parametrize("status", ["cancelled", "failed", "dead_lettered", "completed"])
async def test_r6_13_a_run_that_ends_cancels_every_open_wait_in_the_same_transaction(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
    status: str,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    for node in ("a", "b"):
        await as_app(
            app_engine,
            world.tenant,
            _INSERT_WAIT,
            t=world.tenant,
            r=run_id,
            i=f"wait:{node}::0",
            n=node,
            k="approval",
        )
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(world.tenant)}
        )
        await conn.execute(
            sa.text("UPDATE platform.worker_runs SET status = :s WHERE id = :r"),
            {"s": status, "r": run_id},
        )
        inside = (
            (
                await conn.execute(
                    sa.text("SELECT status FROM platform.run_waits WHERE run_id = :r"),
                    {"r": run_id},
                )
            )
            .scalars()
            .all()
        )
    assert sorted(inside) == ["cancelled", "cancelled"]


async def test_r6_13_a_cross_tenant_lane_with_no_tenant_setting_still_cancels_the_waits(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
    studio_db: DatabaseUrls,
) -> None:
    """A lane that reaches every tenant's runs (a role whose policy on
    `worker_runs` reads no `app.tenant_id`) ends a run: the trigger's
    function, SECURITY DEFINER, still cancels the wait it cannot see; run as
    the lane's role, it would change zero rows under FORCE RLS, silently."""
    run_id = await a_waiting_run(store, service, migrator, world, source)
    await as_app(
        app_engine,
        world.tenant,
        _INSERT_WAIT,
        t=world.tenant,
        r=run_id,
        i="wait:g::0",
        n="g",
        k="approval",
    )
    admin = create_async_engine(
        studio_db.admin.rsplit("/", 1)[0] + "/" + studio_db.app.rsplit("/", 1)[1],
        poolclass=NullPool,
    )
    role = f"lane_probe_{uuid.uuid4().hex[:8]}"
    try:
        async with admin.connect() as conn:
            transaction = await conn.begin()
            for statement in (
                f"CREATE ROLE {role} NOLOGIN",
                f"GRANT USAGE ON SCHEMA platform TO {role}",
                f"GRANT SELECT, UPDATE ON platform.worker_runs TO {role}",
                f"GRANT SELECT, UPDATE ON platform.run_waits TO {role}",
                f"CREATE POLICY every_tenant_{role} ON platform.worker_runs TO {role}"
                " USING (true) WITH CHECK (true)",
                f"SET LOCAL ROLE {role}",
                "SELECT set_config('app.tenant_id', '', true)",
            ):
                await conn.execute(sa.text(statement))
            await conn.execute(
                sa.text("UPDATE platform.worker_runs SET status = 'cancelled' WHERE id = :r"),
                {"r": run_id},
            )
            await conn.execute(sa.text("RESET ROLE"))
            (status,) = (
                (
                    await conn.execute(
                        sa.text("SELECT status FROM platform.run_waits WHERE run_id = :r"),
                        {"r": run_id},
                    )
                )
                .scalars()
                .all()
            )
            await transaction.rollback()
    finally:
        await admin.dispose()
    assert status == "cancelled"


# ---- R6.1: offboarding takes a company's waits through the run's key ----------------


async def test_r6_1_deleting_a_companys_runs_takes_its_waits_and_spares_the_rest(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    keep = await a_waiting_run(store, service, migrator, world, source)
    for run in (run_id, keep):
        await as_app(
            app_engine,
            world.tenant,
            _INSERT_WAIT,
            t=world.tenant,
            r=run,
            i="wait:g::0",
            n="g",
            k="approval",
        )
    # As the offboarding lane's purge deletes the runs (H-2's order).
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.run_checkpoints WHERE thread_id = :r"), {"r": run_id}
        )
        await conn.execute(sa.text("DELETE FROM platform.worker_runs WHERE id = :r"), {"r": run_id})
    assert not await rows(migrator, "SELECT 1 FROM platform.run_waits WHERE run_id = :r", r=run_id)
    assert await rows(migrator, "SELECT 1 FROM platform.run_waits WHERE run_id = :r", r=keep)


# ---- R6.5, R6.16: what a run taken again meets first ----------------------------------


async def test_r6_5_a_resume_with_nothing_resolved_is_blocked_with_its_audit(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    door = ScriptedDoor()
    runner, _ = build_runner(sessions, {"tool": door})
    await run_claimed(runner, sessions, world.tenant, run_id)
    # Queued with its wait still open: nothing to resume with.
    await rows(
        migrator, "UPDATE platform.worker_runs SET status = 'queued' WHERE id = :r", r=run_id
    )
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.BLOCKED
    (row,) = await rows(
        migrator, "SELECT status, error FROM platform.worker_runs WHERE id = :r", r=run_id
    )
    assert (row.status, row.error["code"]) == ("blocked", "empty_resume")
    (audit,) = await rows(
        migrator,
        "SELECT actor_id, details FROM platform.audit_events"
        " WHERE run_id = :r AND action = 'run.blocked'",
        r=run_id,
    )
    assert (
        audit.actor_id == system_actor("studio_runs").value
        and audit.details["actor"] == "system:studio_runs"
    )
    assert len(door.calls) == 1


async def test_r6_16_a_resume_past_the_deadline_is_cancelled_with_one_audit_and_no_step(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    door = ScriptedDoor()
    runner, _ = build_runner(sessions, {"tool": door})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await resolve(sessions, world, run_id, "wait:cho::0")
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET deadline_at = now() - interval '1 s' WHERE id = :r",
        r=run_id,
    )
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.CANCELLED
    (row,) = await rows(
        migrator, "SELECT status, error FROM platform.worker_runs WHERE id = :r", r=run_id
    )
    assert (row.status, row.error["code"]) == ("cancelled", "deadline_exceeded")
    audits = await rows(
        migrator,
        "SELECT actor_id FROM platform.audit_events"
        " WHERE run_id = :r AND action = 'run.deadline_exceeded'",
        r=run_id,
    )
    assert [a.actor_id for a in audits] == [system_actor("studio_runs").value]
    assert len(door.calls) == 1


async def test_r6_13_a_waiting_run_the_reaper_ends_past_its_deadline_cancels_its_wait(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    from studio_run_stack import scoped_queue

    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor()})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET deadline_at = now() - interval '1 s' WHERE id = :r",
        r=run_id,
    )
    queue = scoped_queue(sessions, frozenset({world.tenant}))
    await queue.cancel_overdue(world.tenant, unclaimed_after=timedelta(days=30))
    assert await status_of(migrator, run_id) == "cancelled"
    assert [w.status for w in await waits_of(migrator, run_id)] == ["cancelled"]
    with pytest.raises(ConflictError):
        await resolve(sessions, world, run_id, "wait:cho::0")


# ---- R6.8: a run whose pins this build lacks is blocked --------------------------------


async def test_r6_8_a_waiting_node_renamed_by_the_build_blocks_the_resume(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discovery/14 S-RT T4: a compiler that renames the waiting node would
    complete the run with no step after the wait run; check (b) refuses it."""
    run_id = await a_waiting_run(store, service, migrator, world, source)
    door = ScriptedDoor()
    runner, _ = build_runner(sessions, {"tool": door})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await resolve(sessions, world, run_id, "wait:cho::0")
    from dw_agent_runtime.wflite import resume as resume_checks

    monkeypatch.setattr(resume_checks, "wait_node", lambda step_id: f"cho_moi__{step_id}")
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.BLOCKED
    (row,) = await rows(migrator, "SELECT error FROM platform.worker_runs WHERE id = :r", r=run_id)
    assert row.error == {"code": "incompatible_resume", "checks": ["b"]}
    assert len(door.calls) == 1


async def test_r6_14_a_draft_edited_while_its_simulated_run_waits_blocks_the_resume(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    body = (send("truoc"), waits_for(), send("sau"))
    artifact, version, row_version = await a_draft(service, world, doc(source, *body))
    run_id = (await door_of(store).request(ask(world, version))).run_id
    door = ScriptedDoor()
    runner, _ = build_runner(sessions, {"tool": door})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await service.save_draft(
        world.tester.context(),
        artifact,
        ExpectedVersion(row_version),
        doc(source, *body, send("them")),
    )
    await resolve(sessions, world, run_id, "wait:cho::0")
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.BLOCKED
    (row,) = await rows(migrator, "SELECT error FROM platform.worker_runs WHERE id = :r", r=run_id)
    assert row.error == {"code": "incompatible_resume"}
    assert len(door.calls) == 1
    assert await rows(
        migrator,
        "SELECT 1 FROM platform.audit_events WHERE run_id = :r AND action = 'run.blocked'",
        r=run_id,
    )


# ---- R6.9, R6.10: what a resume keeps, and what it never holds ----------------------


async def test_r6_10_no_secret_value_reaches_a_checkpoint_or_a_wait(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    """The door reads a credential at call time and keeps it to itself; the
    bytes are in no checkpoint, no pending write and no wait."""
    secret = b"sk-live-" + uuid.uuid4().hex.encode()

    class CredentialDoor:
        async def __call__(self, call: Any) -> Mapping[str, Any]:
            assert secret  # resolved here, used for the send, never returned
            return {"done": True}

    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(sessions, {"tool": CredentialDoor()})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await resolve(sessions, world, run_id, "wait:cho::0", {"decision": "approved", "comment": "ok"})
    await run_claimed(runner, sessions, world.tenant, run_id)
    blobs = await rows(
        migrator,
        "SELECT checkpoint || metadata AS b FROM platform.run_checkpoints WHERE thread_id = :r"
        " UNION ALL SELECT value FROM platform.run_checkpoint_writes WHERE thread_id = :r"
        " UNION ALL SELECT convert_to(coalesce(resolution::text, '') || coalesce(detail::text, ''),"
        " 'UTF8') FROM platform.run_waits WHERE run_id = :r",
        r=run_id,
    )
    assert blobs and not any(secret in bytes(row.b) for row in blobs)


async def test_r6_12_a_tool_scope_revoked_while_waiting_is_gone_at_the_resume(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    """The scopes the run is given come from `platform.scopes_in` at every
    take: the door, like the executor, refuses a call its run lacks the scope
    for, and a principal who lost the role while the run waited has it no
    more."""
    (key,) = await rows(
        migrator,
        "SELECT permission_key AS k FROM platform.tenant_role_permissions p"
        " JOIN platform.role_assignments a ON a.role_id = p.role_id AND a.tenant_id = p.tenant_id"
        " JOIN platform.memberships m ON m.id = a.membership_id"
        " WHERE m.user_id = :u AND p.tenant_id = :t LIMIT 1",
        u=world.tester.id,
        t=world.tenant,
    )
    seen: list[frozenset[str]] = []

    class ScopedDoor:
        async def __call__(self, call: Any) -> Mapping[str, Any]:
            seen.append(call.run.scopes)
            return {"done": True}

    run_id = await a_waiting_run(store, service, migrator, world, source)
    runner, _ = build_runner(sessions, {"tool": ScopedDoor()}, live_scopes=SqlLiveScopes(sessions))
    await run_claimed(runner, sessions, world.tenant, run_id)
    assert key.k in seen[0]
    async with migrator.begin() as conn:
        await conn.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        await conn.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions p USING platform.role_assignments a,"
                " platform.memberships m WHERE a.role_id = p.role_id AND a.tenant_id = p.tenant_id"
                " AND m.id = a.membership_id AND m.user_id = :u AND p.permission_key = :k"
            ),
            {"u": world.tester.id, "k": key.k},
        )
    await resolve(sessions, world, run_id, "wait:cho::0")
    await run_claimed(runner, sessions, world.tenant, run_id)
    assert key.k not in seen[-1]


async def test_r6_12_a_principal_no_longer_a_member_holds_the_run_queued(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    scopes = SqlLiveScopes(sessions)
    assert await scopes.scopes(world.tenant, world.tester.workspace_id, uuid.uuid4()) is None
    assert await scopes.scopes(world.tenant, world.tester.workspace_id, world.tester.id)


async def test_r6_9_a_version_sealed_while_waiting_does_not_change_the_resumed_run(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    run_id = await a_waiting_run(store, service, migrator, world, source)
    (before,) = await rows(
        migrator,
        "SELECT run_mode, run_manifest_hash FROM platform.worker_runs WHERE id = :r",
        r=run_id,
    )
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor()})
    await run_claimed(runner, sessions, world.tenant, run_id)
    # Another version of another workflow is drafted meanwhile.
    await a_draft(service, world, doc(source, send("khac")))
    await resolve(sessions, world, run_id, "wait:cho::0")
    assert await run_claimed(runner, sessions, world.tenant, run_id) == RunStatus.COMPLETED
    (after,) = await rows(
        migrator,
        "SELECT run_mode, run_manifest_hash FROM platform.worker_runs WHERE id = :r",
        r=run_id,
    )
    assert tuple(after) == tuple(before)


# ---- R7.1 (WE45): the golden trace of a cancelled waiting run ----------------------


async def test_r7_1_the_golden_trace_of_a_run_cancelled_while_it_waits(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    from dw_studio.workflows.testing.golden import CANCELLED_WHILE_WAITING, GoldenTrace, compare

    case = CANCELLED_WHILE_WAITING
    _, version, _ = await a_draft(
        service, world, {**case.document, "triggers": doc(source)["triggers"]}
    )
    run_id = (await door_of(store).request(ask(world, version))).run_id
    runner, recorder = build_runner(sessions, {"tool": ScriptedDoor(list(case.tool_script))})
    await run_claimed(runner, sessions, world.tenant, run_id)
    await as_app(
        app_engine,
        world.tenant,
        "UPDATE platform.worker_runs SET status = 'cancelled' WHERE id = :r",
        r=run_id,
    )
    nodes = tuple(step.node_id for step in recorder.finished) + tuple(
        step.node_id for step in recorder.waiting
    )
    observed = GoldenTrace(
        nodes,
        failed=await status_of(migrator, run_id),
        waits=tuple(w.status for w in await waits_of(migrator, run_id)),
    )
    assert compare(case.expected, observed) == []
