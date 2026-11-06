"""The `studio_runs` lane and `studio_run_reaper` on PostgreSQL (workflow-engine
ticket 04: R1.9, R5.1-R5.3, R5.5-R5.26; WE2-WE8, WE17, WE23-WE25, WE52).

Runs are requested through the real door (`RunRequestService` as `dw_app`)
and copied by the migrator into the kinds W1 has no door for yet (`datahub`
with a service account, `eval`), then taken by the real lane over the real
`SqlStudioRunQueue`, run by `LangGraphWorkflowRunner.run_studio` with the
real `SqlStudioRunStore` and checkpoint saver. Each test plants its own
company; the queue is seen through `ScopedQueue`, so runs other suites left
in the database are never taken. Time is moved by aging rows as the
migrator, never by waiting, except where a lease must lapse, scaled to
seconds (`studio_lane_child.py`).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
import sqlalchemy as sa
from langgraph.checkpoint.base import empty_checkpoint
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from studio_run_stack import DIED, FileDoor, ScopedQueue, build_runner, scoped_queue

from dw_agent_runtime.adapters.checkpoint import (
    FENCE_RUN_ID,
    FENCE_TOKEN,
    SqlAlchemyCheckpointSaver,
)
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.run_control import SqlRunControl
from dw_agent_runtime.adapters.studio_resume import WorkflowEngineFacts
from dw_agent_runtime.ports import StudioClaim, StudioLeaseLostError
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.studio_lane import StudioRunReaper, StudioRunsLane
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.studio_runs import FakeBindingReview, ScriptedDoor
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.limits import LimitExceededError
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.adapters.persistence.held_run_alerts import SqlHeldRunAlerts
from dw_platform.adapters.persistence.notifications import SqlNotificationRepository
from dw_platform.adapters.persistence.scope_holders import SqlScopeHolders
from dw_platform.domain.audit import system_actor
from dw_platform.domain.outbox import OutboxEvent
from dw_platform.testing.rbac import assign, plant_membership, plant_person, plant_role
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.cel import CelCppEngine
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import (
    PersonRequester,
    RunLaneRegistry,
    RunRequest,
    RunRequestService,
)
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import (
    WORKFLOWS_READ_SCOPE,
    WORKFLOWS_TEST_SCOPE,
    run_boundary_derivers,
    run_pinnable_steps,
)
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.testing.bindings import unasked_pins
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.run_manifests import (
    draft_of,
    fixture_document,
    published,
    shipped_models,
)
from dw_studio.testing.workflows import (
    FakeTriggerActivation,
    plant_holder,
    studio_document,
    studio_step,
    workflow_entry,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world
from dw_worker.consumers.studio_runs import build_dead_letter_handler

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

# The engine facts a manifest pins (workflow-engine R6.7), of the fixture types.
ENGINE_FACTS = WorkflowEngineFacts(fixture_node_registry())


REF = "sha256:" + "f" * 64
REGISTRY = fixture_node_registry()
CHILD = Path(__file__).resolve().parent / "studio_lane_child.py"
RESETS = datetime(2027, 1, 1, tzinfo=UTC)
SPENT = LimitExceededError(
    "spent", metric="runs", scope_type="tenant", window="day", resets_at=RESETS
)
MEMBERS_WRITE = "platform.members.write"
BINDINGS_APPROVE = "studio.bindings.approve"
CANCEL = "UPDATE platform.worker_runs SET status = 'cancelled' WHERE id = :r"
OUTCOMES = [
    {"name": "lead_new", "when": "has(steps.gui) && steps.gui.done == true"},
    {"name": "lead_duplicate", "when": "has(steps.gui) && steps.gui.done == false"},
    {"name": "untouched", "when": "!has(steps.gui)"},
]


# ---- the world ------------------------------------------------------------------------


@dataclass
class Company:
    studio: StudioWorld
    tester: Person
    source: uuid.UUID

    @property
    def tenant(self) -> uuid.UUID:
        return self.tester.tenant_id

    @property
    def workspace(self) -> uuid.UUID:
        return self.tester.workspace_id


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    async with planted_fixture_kinds(engine):
        yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_engine(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def store(sessions: async_sessionmaker[AsyncSession]) -> SqlArtifactStore:
    return SqlArtifactStore(sessions, Uuid7Generator())


def registry_of() -> ArtifactKindRegistry:
    entry = workflow_entry(FakeTriggerActivation(), expressions=CelCppEngine())
    return ArtifactKindRegistry((*FIXTURE_KINDS, entry))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(store: SqlArtifactStore) -> ArtifactService:
    return ArtifactService(store, registry_of(), SystemClock(), store.ids)


def door_of(store: SqlArtifactStore) -> RunRequestService:
    registry = registry_of()
    return RunRequestService(
        store,
        registry,
        RunManifestBuilder(registry, REF, shipped_models(), ENGINE_FACTS),
        {("workflow", "test"): WORKFLOWS_TEST_SCOPE},
        RunLaneRegistry({"studio_gate": ("eval",)}),
        SystemClock(),
        Uuid7Generator(),
        bindings=unasked_pins(),
        boundaries=SqlActorBoundaries(),
        boundary_derivers=run_boundary_derivers(REGISTRY),
        pinnable=run_pinnable_steps(REGISTRY),
    )


Plant = Callable[[], Any]


@pytest_asyncio.fixture(loop_scope="module")
async def plant(migrator: AsyncEngine, service: ArtifactService) -> Plant:
    async def make() -> Company:
        async with migrator.begin() as conn:
            studio = await plant_world(conn)
            tester = await plant_holder(conn, studio.tenant)
        source, _ = await published(service, migrator, studio["writer"], fixture_document())
        return Company(studio, tester, source)

    return make


# ---- helpers --------------------------------------------------------------------------


def doc(source: uuid.UUID, *step_ids: str, outcomes: bool = False) -> dict[str, Any]:
    document = studio_document(*(studio_step(s) for s in step_ids), source=str(source))
    document["decision_classes"] = []
    if outcomes:
        document["outcomes"] = OUTCOMES
    return document


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def requested(
    store: SqlArtifactStore,
    service: ArtifactService,
    co: Company,
    *steps: str,
    outcomes: bool = False,
) -> uuid.UUID:
    """A `test` run (`simulate`) of a new draft, through the one door."""
    _, version, _ = await draft_of(
        service, co.tester, doc(co.source, *(steps or ("gui",)), outcomes=outcomes), kind="workflow"
    )
    request = RunRequest(
        requester=PersonRequester(co.tester.context()),
        version_id=version,
        trigger_kind="test",
        source_key=uuid.uuid4().hex,
    )
    return (await door_of(store).request(request)).run_id


async def copied(
    migrator: AsyncEngine,
    template: uuid.UUID,
    *,
    kind: str,
    mode: str | None = None,
    priority: int = 0,
    run_as: uuid.UUID | None = None,
    event: uuid.UUID | None = None,
    available: str = "now()",
) -> uuid.UUID:
    """The template's row again as a run of `kind`: what a door W1 lacks
    (a trigger's, the gate's) would write."""
    run_id = uuid.uuid4()
    async with migrator.begin() as conn:
        if mode is not None:
            # A `live` run of a draft, which no door writes: W1 reaches a live
            # workflow only through the quality gate (agent-lifecycle/06).
            # The manifest's mode check is the migrator's to set aside, in
            # this one transaction.
            await conn.execute(
                sa.text("ALTER TABLE platform.worker_runs DISABLE TRIGGER match_run_manifest")
            )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id,"
                " worker_version, graph_version, requested_by, run_as_principal_id, run_mode,"
                " run_manifest_hash, artifact_kind, artifact_id, artifact_version_id, trigger_kind,"
                " request_key, input, status, actor_record_visibility, data_route_class, priority,"
                " inbound_event_id, available_at, created_at, updated_at)"
                " SELECT :n, :n, tenant_id, workspace_id, worker_id, worker_version, graph_version,"
                " requested_by, COALESCE(CAST(:a AS uuid), run_as_principal_id),"
                " COALESCE(CAST(:m AS text), run_mode), run_manifest_hash,"
                " artifact_kind, artifact_id, artifact_version_id, :k, :key, input, 'queued',"
                f" actor_record_visibility, data_route_class, :p, :e, {available}, now(), now()"
                " FROM platform.worker_runs WHERE id = :t"
            ),
            {
                "n": run_id,
                "a": run_as,
                "m": mode,
                "k": kind,
                "key": uuid.uuid4().hex,
                "p": priority,
                "e": event,
                "t": template,
            },
        )
        if mode is not None:
            await conn.execute(
                sa.text("ALTER TABLE platform.worker_runs ENABLE TRIGGER match_run_manifest")
            )
    return run_id


async def run_row(migrator: AsyncEngine, run_id: uuid.UUID) -> Any:
    (row,) = await rows(
        migrator,
        "SELECT status, error, attempt, deadline_at, available_at, lease_owner, lease_until,"
        " outcomes, inbound_event_id, now() AS now FROM platform.worker_runs WHERE id = :r",
        r=run_id,
    )
    return row


async def queue_order(migrator: AsyncEngine, run_ids: list[uuid.UUID]) -> list[str]:
    """The runs in the order the claim takes them."""
    found = await rows(
        migrator,
        "SELECT id FROM platform.worker_runs WHERE id = ANY(:r)"
        " ORDER BY priority, available_at, created_at, id",
        r=run_ids,
    )
    return [str(row.id) for row in found]


async def due_now(migrator: AsyncEngine, *run_ids: uuid.UUID) -> None:
    """Time passes for held runs: each due, in the order it was due."""
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET available_at = available_at - interval '1 day'"
        " WHERE id = ANY(:r)",
        r=list(run_ids),
    )


def lane_of(
    sessions: async_sessionmaker[AsyncSession],
    tenants: set[uuid.UUID],
    runner: Any,
    **over: Any,
) -> StudioRunsLane:
    return StudioRunsLane(
        queue=scoped_queue(sessions, frozenset(tenants)), runner=runner, worker="w", **over
    )


async def tick(lane: StudioRunsLane) -> None:
    await lane()
    while lane.running:
        await asyncio.sleep(0.02)


def sends(door: FileDoor) -> list[str]:
    """The run id of each send the door saw, in order."""
    return [call[1].split(":")[1] for call in door.calls()]


async def audits(migrator: AsyncEngine, action: str, run_id: uuid.UUID) -> list[Any]:
    return await rows(
        migrator,
        "SELECT actor_id, details FROM platform.audit_events WHERE action = :a AND run_id = :r",
        a=action,
        r=run_id,
    )


def control(sessions: async_sessionmaker[AsyncSession]) -> SqlRunControl:
    """The real switches, read again at every ask."""
    return SqlRunControl(
        sessions,
        clock=SystemClock(),
        telemetry=RecordingTelemetry(),
        listen_dsn=None,
        system_actors=frozenset(),
        ttl_seconds=0,
    )


async def holder(
    migrator: AsyncEngine, tenant: Any, key: str, depth: str, workspace: uuid.UUID | None = None
) -> uuid.UUID:
    """A person holding `key` at `depth`, a member of `workspace` (main)."""
    async with migrator.begin() as conn:
        user = await plant_person(conn, tenant.tenant_id)
        ws = workspace or tenant.main
        membership = await plant_membership(conn, tenant.tenant_id, ws, user)
        role = await plant_role(conn, tenant.tenant_id, f"r_{user.hex[:12]}", {key: depth})
        await assign(conn, tenant.tenant_id, ws, membership, role)
    return user


async def told(migrator: AsyncEngine, user: uuid.UUID, prefix: str) -> list[Any]:
    return await rows(
        migrator,
        "SELECT source_key, workspace_id FROM platform.notifications"
        " WHERE recipient_user_id = :u AND source_key LIKE :p",
        u=user,
        p=f"{prefix}%",
    )


# ---- R5.1: a requested run waits for the worker --------------------------------------------


async def test_r5_1_a_run_requested_while_no_worker_runs_stays_queued(
    store: SqlArtifactStore, service: ArtifactService, migrator: AsyncEngine, plant: Plant
) -> None:
    co = await plant()
    run_id = await requested(store, service, co)
    await asyncio.sleep(0.2)
    row = await run_row(migrator, run_id)
    assert (row.status, row.lease_owner, row.deadline_at) == ("queued", None, None)


# ---- R5.2, R5.3, R5.8: the fair claim under each tenant's RLS --------------------------------


async def test_r5_3_the_claim_under_a_tenant_takes_only_its_runs_and_the_scan_names_tenants(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    a, b = await plant(), await plant()
    run_a = await requested(store, service, a)
    run_b = await requested(store, service, b)
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET available_at = now() - interval '1 hour' WHERE id = :r",
        r=run_b,
    )
    queue = scoped_queue(sessions, frozenset({a.tenant, b.tenant}))
    claims = await queue.claim(a.tenant, limit=10, worker="w", lease=timedelta(seconds=60))
    assert [c.run_id for c in claims] == [run_a]
    assert (await run_row(migrator, run_b)).status == "queued"
    for function in (
        "platform.studio_run_scopes_due(100)",
        "platform.studio_run_orphans_due(100)",
        "platform.studio_run_deadlines_due(100, interval '30 days')",
    ):
        async with migrator.connect() as conn:
            result = await conn.execute(sa.text(f"SELECT * FROM {function}"))
            assert list(result.keys()) == ["tenant_id"], function
    # B waited longest, so the scan names it first.
    assert (await queue.scopes_due(10))[0] == b.tenant


async def test_r5_2_behind_ten_thousand_runs_of_one_tenant_anothers_run_is_in_the_first_batch(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    """Inserted just before the claim and never analysed: the `MATERIALIZED`
    pick takes exactly its share (discovery/14 S-RT (a))."""
    a, b = await plant(), await plant()
    template = await requested(store, service, a)
    await rows(
        migrator,
        "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id, worker_id,"
        " worker_version, graph_version, requested_by, run_as_principal_id, run_mode,"
        " run_manifest_hash, artifact_kind, artifact_id, artifact_version_id, trigger_kind,"
        " request_key, input, status, actor_record_visibility, available_at,"
        " created_at, updated_at)"
        " SELECT g.id, g.id, t.tenant_id, t.workspace_id, t.worker_id, t.worker_version,"
        " t.graph_version, t.requested_by, t.run_as_principal_id, t.run_mode,"
        " t.run_manifest_hash, t.artifact_kind, t.artifact_id, t.artifact_version_id,"
        " t.trigger_kind, 'bulk:' || g.id, t.input, 'queued', t.actor_record_visibility,"
        " now() - interval '1 hour', now(), now()"
        " FROM (SELECT gen_random_uuid() AS id FROM generate_series(1, 10000)) g"
        " CROSS JOIN platform.worker_runs t WHERE t.id = :t",
        t=template,
    )
    run_b = await requested(store, service, b)
    taken: list[uuid.UUID] = []

    class Recording:
        async def run_studio(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, **_: Any) -> None:
            taken.append(run_id)

    try:
        await tick(lane_of(sessions, {a.tenant, b.tenant}, Recording()))
        # A's share is ceil(8 / 2): four of ten thousand, and B's one.
        assert run_b in taken and len(taken) == 5
        (running,) = await rows(
            migrator,
            "SELECT count(*) AS n FROM platform.worker_runs"
            " WHERE tenant_id = ANY(:t) AND status = 'running'",
            t=[a.tenant, b.tenant],
        )
        assert running.n == 5
    finally:
        await rows(
            migrator,
            "UPDATE platform.worker_runs SET status = 'cancelled', lease_owner = NULL,"
            " lease_until = NULL WHERE tenant_id = :t AND status IN ('queued', 'running')",
            t=a.tenant,
        )


async def test_r5_8_an_interactive_run_is_taken_before_an_eval_run_due_earlier(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    co = await plant()
    template = await requested(store, service, co)
    eval_run = await copied(
        migrator,
        template,
        kind="eval",
        mode="simulate",
        priority=2,
        available="now() - interval '1 hour'",
    )
    chat = await copied(migrator, template, kind="chat")
    await rows(migrator, CANCEL, r=template)
    queue = scoped_queue(sessions, frozenset({co.tenant}))
    (first,) = await queue.claim(co.tenant, limit=1, worker="w", lease=timedelta(seconds=60))
    assert first.run_id == chat
    (second,) = await queue.claim(co.tenant, limit=1, worker="w", lease=timedelta(seconds=60))
    assert second.run_id == eval_run


# ---- R5.9-R5.11, R5.24: limits at the lane ---------------------------------------------------


async def test_r5_9_a_chat_run_over_its_limit_fails_at_the_lane_with_no_step_and_no_outcome(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    template = await requested(store, service, co, outcomes=True)
    chat = await copied(migrator, template, kind="chat")
    await rows(migrator, CANCEL, r=template)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door}, limits=OpenLimits(refuse=SPENT))
    await tick(lane_of(sessions, {co.tenant}, runner))
    row = await run_row(migrator, chat)
    assert row.status == "failed"
    assert row.error["code"] == "limit_exceeded" and row.error["metric"] == "runs"
    assert row.error["resets_at"] == RESETS.isoformat()
    # Ended at dispatch, no node ran: `!has(steps.gui)` is not recorded (R5.24).
    assert row.outcomes == [] and row.deadline_at is None and door.calls() == []
    assert row.lease_owner is None


async def test_r5_10_a_datahub_run_over_its_limit_waits_for_the_reset_audited_once(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    """usage-and-limits M11: held until `resets_at`, the run is not taken
    again inside the period, so `limits.refused` is written once."""
    co = await plant()
    template = await requested(store, service, co)
    event = uuid.uuid4()
    datahub = await copied(migrator, template, kind="datahub", priority=1, event=event)
    await rows(migrator, CANCEL, r=template)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door}, limits=OpenLimits(refuse=SPENT))
    lane = lane_of(sessions, {co.tenant}, runner)
    for _ in range(3):
        await tick(lane)
    row = await run_row(migrator, datahub)
    assert (row.status, row.available_at, row.inbound_event_id) == ("queued", RESETS, event)
    assert (row.attempt, row.lease_owner, row.deadline_at) == (0, None, None)
    refused = await audits(migrator, "limits.refused", datahub)
    assert [a.details["actor"] for a in refused] == ["system:studio_runs"]
    assert door.calls() == []


async def test_r5_11_an_eval_trial_runs_without_asking_the_limits_and_a_later_take_resumes(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    template = await requested(store, service, co)
    trial = await copied(migrator, template, kind="eval", mode="simulate", priority=2)
    await rows(migrator, CANCEL, r=template)
    limits = OpenLimits()
    runner, _ = build_runner(sessions, {"tool": FileDoor(tmp_path / "d.json")}, limits=limits)
    lane = lane_of(sessions, {co.tenant}, runner)
    await tick(lane)
    assert (await run_row(migrator, trial)).status == "completed"
    assert limits.admitted == [] and limits.resumed == []

    chat = await copied(migrator, template, kind="chat")
    await tick(lane)
    first = await run_row(migrator, chat)
    assert first.status == "completed" and len(limits.admitted) == 1
    # Back in the queue three times, as a run going on after each of three
    # approvals is (ticket 05): resumed each time, admitted once, `attempt` 0.
    for _ in range(3):
        await rows(
            migrator,
            "UPDATE platform.worker_runs SET status = 'queued', available_at = now() WHERE id = :r",
            r=chat,
        )
        await tick(lane)
    again = await run_row(migrator, chat)
    assert (again.status, again.attempt, again.deadline_at) == ("completed", 0, first.deadline_at)
    assert len(limits.admitted) == 1 and limits.resumed == [chat] * 3


# ---- R5.12-R5.18: the switches at the lane ---------------------------------------------------


async def _freeze(app_engine: AsyncEngine, co: Company) -> uuid.UUID:
    switch = uuid.uuid4()
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(co.tenant)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                " origin, reason_code, reason, set_by)"
                " VALUES (:id, :t, 'tenant', 'freeze', 'tenant', 'incident', 'sự cố', :by)"
            ),
            {"id": switch, "t": co.tenant, "by": co.tester.id},
        )
    return switch


async def _lift(
    migrator: AsyncEngine, app_engine: AsyncEngine, co: Company, switch: uuid.UUID
) -> None:
    """The freeze lifted under its approved request, decided by a second
    person (agent-lifecycle R7.10), as its settler writes it."""
    approval = uuid.uuid4()
    decider = co.studio["co_writer"].id
    await rows(
        migrator,
        "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id, approval_type,"
        " requested_by, payload, status) VALUES (:a, :t, :w, 'studio.lifecycle.unfreeze', :r,"
        " jsonb_build_object('switch_id', CAST(:s AS text)), 'approved')",
        a=approval,
        t=co.tenant,
        w=co.workspace,
        r=co.tester.id,
        s=str(switch),
    )
    await rows(
        migrator,
        "INSERT INTO platform.approval_decisions (id, request_id, tenant_id, workspace_id,"
        " decided_by, outcome, decided_at)"
        " VALUES (gen_random_uuid(), :a, :t, :w, :d, 'approved', now())",
        a=approval,
        t=co.tenant,
        w=co.workspace,
        d=decider,
    )
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(co.tenant)}
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.control_switches SET lifted_at = now(), lifted_by = :d,"
                " lift_approval_id = :a WHERE id = :s"
            ),
            {"d": decider, "a": approval, "s": switch},
        )


async def test_r5_12_r5_13_a_freeze_cancels_interactive_runs_and_holds_a_triggers_in_order(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    template = await requested(store, service, co)
    chat = await copied(migrator, template, kind="chat")
    manual = await copied(migrator, template, kind="manual")
    datahub = [
        await copied(
            migrator, template, kind="datahub", priority=1, available=f"now() + interval '{n} s'"
        )
        for n in (-30, -20, -10)
    ]
    await rows(migrator, CANCEL, r=template)
    switch = await _freeze(app_engine, co)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door}, dispatch_control=control(sessions))
    lane = lane_of(sessions, {co.tenant}, runner)
    await tick(lane)
    for run_id in (chat, manual):
        row = await run_row(migrator, run_id)
        assert (row.status, row.error["code"]) == ("cancelled", "tenant_frozen")
    for run_id in datahub:
        row = await run_row(migrator, run_id)
        assert (row.status, row.lease_owner, row.deadline_at) == ("queued", None, None)
        # Waits on a person: due five minutes on.
        wait = row.available_at - row.now
        assert timedelta(minutes=4) < wait <= timedelta(minutes=5)
    assert door.calls() == []

    await _lift(migrator, app_engine, co, switch)
    await due_now(migrator, *datahub)
    expected = await queue_order(migrator, datahub)
    one_at_a_time = lane_of(sessions, {co.tenant}, runner, batch=1)
    for _ in datahub:
        await tick(one_at_a_time)
    assert sends(door) == expected


async def test_r5_14_a_kill_cancels_a_queued_live_run_and_a_simulate_run_still_runs(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    simulate = await requested(store, service, co)
    manual = await copied(migrator, simulate, kind="manual", mode="live")
    datahub = await copied(migrator, simulate, kind="datahub", mode="live", priority=1)
    (artifact,) = await rows(
        migrator, "SELECT artifact_id FROM platform.worker_runs WHERE id = :r", r=simulate
    )
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(co.tenant)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type,"
                " owning_workspace_id, target_id, action, origin, reason_code, reason, set_by)"
                " VALUES (:id, :t, 'workflow', :w, :a, 'kill', 'tenant', 'incident', 'x', :by)"
            ),
            {
                "id": uuid.uuid4(),
                "t": co.tenant,
                "w": co.workspace,
                "a": artifact.artifact_id,
                "by": co.tester.id,
            },
        )
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(
        sessions, {"tool": door}, run_control=control(sessions), dispatch_control=control(sessions)
    )
    await tick(lane_of(sessions, {co.tenant}, runner))
    for run_id in (manual, datahub):
        killed = await run_row(migrator, run_id)
        assert (killed.status, killed.error["code"]) == ("cancelled", "artifact_killed")
    assert (await run_row(migrator, simulate)).status == "completed"
    assert sends(door) == [str(simulate)]


async def test_r5_15_r5_17_r5_20_an_inactive_principal_cancels_a_manual_run_and_holds_a_triggers(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co, other = await plant(), await plant()
    async with migrator.begin() as conn:
        person = await plant_person(conn, co.tenant)
        service_account = await plant_person(conn, co.tenant, kind="service")
    told_holder = await holder(migrator, co.studio.tenant, MEMBERS_WRITE, "tenant")
    # `platform.members.write` is a tenant key: nobody holds it at workspace
    # depth. A member with another key is the one not told.
    bystander = await holder(migrator, co.studio.tenant, WORKFLOWS_READ_SCOPE, "workspace")
    other_holder = await holder(migrator, other.studio.tenant, MEMBERS_WRITE, "tenant")
    template = await requested(store, service, co)
    manual = await copied(migrator, template, kind="manual", run_as=person)
    datahub = [
        await copied(migrator, template, kind="datahub", priority=1, run_as=service_account)
        for _ in range(3)
    ]
    await rows(migrator, CANCEL, r=template)
    suspend = (
        "UPDATE platform.tenant_members SET status = :s WHERE tenant_id = :t AND user_id = ANY(:u)"
    )
    await rows(migrator, suspend, s="suspended", t=co.tenant, u=[person, service_account])
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(
        sessions,
        {"tool": door},
        dispatch_control=control(sessions),
        alerts=SqlHeldRunAlerts(sessions),
    )
    lane = lane_of(sessions, {co.tenant, other.tenant}, runner)
    for _ in range(2):
        await tick(lane)
        await due_now(migrator, *datahub)
    row = await run_row(migrator, manual)
    assert (row.status, row.error["code"]) == ("cancelled", "principal_inactive")
    for run_id in datahub:
        assert (await run_row(migrator, run_id)).status == "queued"
    assert door.calls() == []
    first = await told(migrator, told_holder, "studio.run.principal_inactive:")
    assert len(first) == 1 and str(service_account) in first[0].source_key
    assert await told(migrator, bystander, "studio.run.") == []
    assert await told(migrator, other_holder, "studio.run.") == []

    # Active again, then suspended again: one more notice, keyed by the change.
    await rows(migrator, suspend, s="active", t=co.tenant, u=[service_account])
    await rows(migrator, suspend, s="suspended", t=co.tenant, u=[service_account])
    await due_now(migrator, *datahub)
    await tick(lane)
    assert len(await told(migrator, told_holder, "studio.run.principal_inactive:")) == 2

    await rows(migrator, suspend, s="active", t=co.tenant, u=[service_account])
    await due_now(migrator, *datahub)
    await tick(lane)
    assert sorted(sends(door)) == sorted(str(r) for r in datahub)


async def test_r5_18_a_locked_company_cancels_a_chat_and_a_datahub_run(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    template = await requested(store, service, co)
    chat = await copied(migrator, template, kind="chat")
    datahub = await copied(migrator, template, kind="datahub", priority=1)
    await rows(migrator, CANCEL, r=template)
    await rows(migrator, "UPDATE platform.tenants SET status = 'locked' WHERE id = :t", t=co.tenant)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door}, dispatch_control=control(sessions))
    try:
        await tick(lane_of(sessions, {co.tenant}, runner))
    finally:
        await rows(
            migrator, "UPDATE platform.tenants SET status = 'active' WHERE id = :t", t=co.tenant
        )
    for run_id in (chat, datahub):
        row = await run_row(migrator, run_id)
        assert (row.status, row.error["code"]) == ("cancelled", "tenant_locked")
    assert door.calls() == []


# ---- R5.16, R5.25: a broken port holds, never opens ------------------------------------------


class _Unknown(OpenRunControl):
    async def require_open(self, *args: Any, door: RunControlDoor, **kwargs: Any) -> None:
        halted = RunHaltedError(HaltReason.CONTROL_STATE_UNAVAILABLE, door=door)
        setattr(halted, "reason", "workspace_archived")  # noqa: B010 - a reason W1 lacks
        raise halted


class _Unavailable(OpenRunControl):
    async def require_open(self, *args: Any, door: RunControlDoor, **kwargs: Any) -> None:
        raise RunHaltedError(HaltReason.CONTROL_STATE_UNAVAILABLE, door=door)


class _BrokenLimits(OpenLimits):
    async def admit(self, run_context: Any, *, counts_run: bool = True) -> Any:
        raise ConnectionError("the counters are gone")


@pytest.mark.parametrize(
    ("kind", "ports"),
    [
        pytest.param("chat", {"dispatch_control": _Unavailable()}, id="control unavailable"),
        pytest.param("chat", {"dispatch_control": _Unknown()}, id="unknown reason"),
        pytest.param("datahub", {"binding_review": FakeBindingReview(fails=True)}, id="review"),
        pytest.param("chat", {"limits": _BrokenLimits()}, id="limits raise"),
    ],
)
async def test_r5_16_r5_25_a_broken_port_holds_the_run_a_minute_and_runs_nothing(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
    kind: str,
    ports: Mapping[str, Any],
) -> None:
    co = await plant()
    template = await requested(store, service, co)
    run_id = await copied(migrator, template, kind=kind, priority=1 if kind == "datahub" else 0)
    await rows(migrator, CANCEL, r=template)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door}, **ports)
    await tick(lane_of(sessions, {co.tenant}, runner))
    row = await run_row(migrator, run_id)
    assert (row.status, row.deadline_at, row.lease_owner, row.attempt) == ("queued", None, None, 0)
    wait = row.available_at - row.now
    assert timedelta(seconds=50) < wait <= timedelta(seconds=60)
    assert door.calls() == []


# ---- R5.19, R5.21: a binding to approve again -----------------------------------------------


async def test_r5_19_r5_21_a_binding_to_review_holds_triggers_runs_and_tells_its_approvers_once(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co, other = await plant(), await plant()
    async with migrator.begin() as conn:
        service_account = await plant_person(conn, co.tenant, kind="service")
    approver = await holder(migrator, co.studio.tenant, BINDINGS_APPROVE, "workspace")
    bystander = await holder(migrator, co.studio.tenant, WORKFLOWS_READ_SCOPE, "workspace")
    other_approver = await holder(migrator, other.studio.tenant, BINDINGS_APPROVE, "workspace")
    template = await requested(store, service, co)
    datahub = [
        await copied(
            migrator,
            template,
            kind="datahub",
            priority=1,
            run_as=service_account,
            available=f"now() + interval '{n} s'",
        )
        for n in (-30, -20, -10)
    ]
    chat = await copied(migrator, template, kind="chat")
    await rows(migrator, CANCEL, r=template)
    review = FakeBindingReview(holds={service_account: datetime(2026, 11, 1, tzinfo=UTC)})
    limits = OpenLimits()
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(
        sessions,
        {"tool": door},
        binding_review=review,
        limits=limits,
        alerts=SqlHeldRunAlerts(sessions),
    )
    lane = lane_of(sessions, {co.tenant, other.tenant}, runner)
    for _ in range(10):
        await tick(lane)
        await due_now(migrator, *datahub)
    for run_id in datahub:
        row = await run_row(migrator, run_id)
        assert (row.status, row.deadline_at, row.attempt, row.lease_owner) == (
            "queued",
            None,
            0,
            None,
        )
    # The chat run of the same company was taken and ran meanwhile (R5.7).
    assert (await run_row(migrator, chat)).status == "completed"
    assert limits.admitted == [(chat, True)]
    assert len(await told(migrator, approver, "studio.run.binding_needs_review:")) == 1
    assert await told(migrator, bystander, "studio.run.") == []
    assert await told(migrator, other_approver, "studio.run.") == []

    review.holds[service_account] = datetime(2026, 11, 2, tzinfo=UTC)
    await tick(lane)
    assert len(await told(migrator, approver, "studio.run.binding_needs_review:")) == 2

    review.holds.clear()
    await due_now(migrator, *datahub)
    expected = await queue_order(migrator, datahub)
    one_at_a_time = lane_of(sessions, {co.tenant}, runner, batch=1)
    for _ in datahub:
        await tick(one_at_a_time)
    assert sends(door)[1:] == expected


# ---- R5.22, R5.23: the deadline ---------------------------------------------------------------


async def test_r5_22_a_run_gets_its_deadline_at_its_first_take_and_keeps_it(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    template = await requested(store, service, co)
    chat = await copied(migrator, template, kind="chat")
    await rows(migrator, CANCEL, r=template)
    runner, _ = build_runner(sessions, {"tool": FileDoor(tmp_path / "d.json")})
    lane = lane_of(sessions, {co.tenant}, runner)
    (before,) = await rows(migrator, "SELECT now() AS at")
    await tick(lane)
    (after,) = await rows(migrator, "SELECT now() AS at")
    first = (await run_row(migrator, chat)).deadline_at
    assert before.at + timedelta(days=30) <= first <= after.at + timedelta(days=30)
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET status = 'queued', available_at = now() WHERE id = :r",
        r=chat,
    )
    await tick(lane)
    assert (await run_row(migrator, chat)).deadline_at == first


async def test_r5_23_the_reaper_ends_a_waiting_run_past_its_deadline_and_nothing_else(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    co, other = await plant(), await plant()
    template = await requested(store, service, co, outcomes=True)
    waiting = await copied(migrator, template, kind="chat")
    claimed = await copied(migrator, template, kind="chat")
    unadmitted = await copied(migrator, template, kind="datahub", priority=1)
    fresh = await copied(migrator, template, kind="datahub", priority=1)
    theirs = await copied(migrator, await requested(store, service, other), kind="chat")
    await rows(migrator, CANCEL, r=template)
    past = "now() - interval '1 minute'"
    await rows(
        migrator,
        f"UPDATE platform.worker_runs SET status = 'waiting', deadline_at = {past}"
        " WHERE id = ANY(:r)",
        r=[waiting, theirs],
    )
    await rows(
        migrator,
        f"UPDATE platform.worker_runs SET status = 'running', deadline_at = {past},"
        " lease_owner = 'w:live', lease_until = now() + interval '1 minute' WHERE id = :r",
        r=claimed,
    )
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET created_at = now() - interval '31 days' WHERE id = :r",
        r=unadmitted,
    )
    queue = scoped_queue(sessions, frozenset({co.tenant}))
    # The scan names tenants; under A, B's overdue run is left alone.
    assert await queue.deadlines_due(10, unclaimed_after=timedelta(days=30)) == [co.tenant]
    await StudioRunReaper(queue)()
    for run_id in (waiting, unadmitted):
        row = await run_row(migrator, run_id)
        assert (row.status, row.error, row.outcomes) == (
            "cancelled",
            {"code": "deadline_exceeded"},
            [],
        )
        assert [
            (a.actor_id, a.details["actor"])
            for a in await audits(migrator, "run.deadline_exceeded", run_id)
        ] == [(system_actor("studio_run_reaper").value, "system:studio_run_reaper")]
    assert (await run_row(migrator, claimed)).status == "running"
    assert (await run_row(migrator, fresh)).status == "queued"
    assert (await run_row(migrator, theirs)).status == "waiting"
    await rows(
        migrator, "UPDATE platform.worker_runs SET status = 'cancelled' WHERE id = :r", r=theirs
    )


# ---- R5.5: the fence ---------------------------------------------------------------------------


def _config(run: Any, run_id: uuid.UUID, token: str) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": str(run_id),
            "checkpoint_ns": "",
            "tenant_id": str(run.tenant_id),
            "workspace_id": str(run.workspace_id),
            FENCE_RUN_ID: str(run_id),
            FENCE_TOKEN: token,
        }
    }


async def _claimed(
    queue: ScopedQueue, tenant: uuid.UUID, lease: timedelta = timedelta(seconds=60)
) -> StudioClaim:
    (claim,) = await queue.claim(tenant, limit=1, worker="w", lease=lease)
    return claim


async def test_r5_5_a_worker_that_lost_its_claim_writes_no_checkpoint(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    co = await plant()
    run_id = await requested(store, service, co)
    queue = scoped_queue(sessions, frozenset({co.tenant}))
    old = await _claimed(queue, co.tenant)
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET lease_owner = 'w:new' WHERE id = :r",
        r=run_id,
    )
    saver = SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer())
    run = co.tester
    with pytest.raises(StudioLeaseLostError):
        await saver.aput(
            cast(Any, _config(run, run_id, old.lease_token)), empty_checkpoint(), {}, {}
        )
    stale = _config(run, run_id, old.lease_token)
    stale["configurable"]["checkpoint_id"] = "x"
    with pytest.raises(StudioLeaseLostError):
        await saver.aput_writes(cast(Any, stale), [("work", {"a": 1})], "task")
    (count,) = await rows(
        migrator,
        "SELECT (SELECT count(*) FROM platform.run_checkpoints WHERE thread_id = :r)"
        " + (SELECT count(*) FROM platform.run_checkpoint_writes WHERE thread_id = :r) AS n",
        r=run_id,
    )
    assert count.n == 0
    # The holder of the claim writes.
    await saver.aput(cast(Any, _config(run, run_id, "w:new")), empty_checkpoint(), {}, {})


async def test_r5_5_a_stale_write_waiting_on_a_new_claim_rolls_back_and_the_new_holder_writes(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    studio_db: DatabaseUrls,
    plant: Plant,
) -> None:
    """Two sessions: the new claim's UPDATE holds the row; the old holder's
    write waits on its `FOR SHARE` (seen in `pg_locks`), then finds the new
    token and rolls back. A check made before the write's transaction would
    have let it through."""
    co = await plant()
    run_id = await requested(store, service, co)
    queue = scoped_queue(sessions, frozenset({co.tenant}))
    old = await _claimed(queue, co.tenant)
    saver = SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer())
    claimer = create_async_engine(studio_db.migrator, poolclass=NullPool)
    try:
        async with claimer.connect() as conn:
            tx = await conn.begin()
            await conn.execute(
                sa.text("UPDATE platform.worker_runs SET lease_owner = 'w:new' WHERE id = :r"),
                {"r": run_id},
            )
            stale = asyncio.create_task(
                saver.aput(
                    cast(Any, _config(co.tester, run_id, old.lease_token)),
                    empty_checkpoint(),
                    {},
                    {},
                )
            )
            for _ in range(200):
                (waiting,) = await rows(
                    migrator,
                    "SELECT count(*) AS n FROM pg_locks"
                    " WHERE NOT granted AND locktype IN ('transactionid', 'tuple')",
                )
                if waiting.n:
                    break
                await asyncio.sleep(0.02)
            assert waiting.n, "the stale write never waited on the claim"
            await tx.commit()
        with pytest.raises(StudioLeaseLostError):
            await stale
    finally:
        await claimer.dispose()
    checkpoint = empty_checkpoint()
    await saver.aput(cast(Any, _config(co.tester, run_id, "w:new")), checkpoint, {}, {})
    (row,) = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.run_checkpoints WHERE thread_id = :r",
        r=run_id,
    )
    assert row.n == 1


# ---- R5.6, R5.7: a dead worker, an orderly one, the dead letter ------------------------------


async def test_r5_6_a_worker_killed_mid_run_is_taken_over_once_and_its_send_is_not_made_again(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    studio_db: DatabaseUrls,
    plant: Plant,
    tmp_path: Path,
) -> None:
    """A child process (the real lane, lease 2 s) dies by `os._exit` after
    `mot` sent; once its claim lapses the reaper queues the run again with
    `attempt` 1 and another worker finishes it from `mot`'s checkpoint."""
    co = await plant()
    run_id = await requested(store, service, co, "mot", "hai")
    door_file = tmp_path / "door.json"
    child = subprocess.run(
        [sys.executable, str(CHILD), studio_db.app, str(co.tenant), str(door_file), "mot"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert child.returncode == DIED, child.stderr[-2000:]
    row = await run_row(migrator, run_id)
    assert row.status == "running" and row.lease_owner.startswith("child:")
    queue = scoped_queue(sessions, frozenset({co.tenant}))
    reaper = StudioRunReaper(queue, backoff=lambda attempt: timedelta(0))
    await reaper()  # the claim has not lapsed yet: nothing to do
    assert (await run_row(migrator, run_id)).attempt == 0
    await asyncio.sleep(2.2)
    await reaper()
    await reaper()
    requeued = await run_row(migrator, run_id)
    assert (requeued.status, requeued.attempt, requeued.lease_owner) == ("queued", 1, None)
    door = FileDoor(door_file)
    runner, _ = build_runner(sessions, {"tool": door})
    await tick(lane_of(sessions, {co.tenant}, runner))
    done = await run_row(migrator, run_id)
    assert (done.status, done.attempt) == ("completed", 1)
    # `mot` died before its checkpoint, so it ran again and its key was
    # replayed by the door, not sent a second time (R4.5).
    assert [c[1].split(":")[2] for c in door.calls()] == ["mot", "mot", "hai"]
    applied = door._load()["applied"]
    assert sorted(key.split(":")[2] for key in applied) == ["hai", "mot"]


async def test_r5_6_an_orderly_shutdown_hands_the_claim_back_and_attempt_stays(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    co = await plant()
    run_id = await requested(store, service, co)
    runner, _ = build_runner(sessions, {"tool": ScriptedDoor(hangs=True)})
    lane = lane_of(sessions, {co.tenant}, runner)
    await lane()
    for _ in range(100):
        if (await run_row(migrator, run_id)).deadline_at is not None:
            break
        await asyncio.sleep(0.05)
    await lane.close()
    row = await run_row(migrator, run_id)
    assert (row.status, row.lease_owner, row.lease_until, row.attempt) == ("queued", None, None, 0)
    assert row.available_at <= row.now
    queue = scoped_queue(sessions, frozenset({co.tenant}))
    assert [
        c.run_id
        for c in await queue.claim(co.tenant, limit=1, worker="w", lease=timedelta(seconds=60))
    ] == [run_id]


async def test_r5_6_a_batch_that_outlasts_the_lease_keeps_every_claim_by_its_heartbeat(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    """Scaled: eight runs of 2.5 s on a lease of 1.5 s beaten every 0.3 s,
    the reaper sweeping all the while; none is queued again."""
    co = await plant()
    run_ids = [await requested(store, service, co) for _ in range(8)]

    class Slow:
        async def __call__(self, call: Any) -> Mapping[str, Any]:
            await asyncio.sleep(2.5)
            return {"done": True}

    runner, _ = build_runner(sessions, {"tool": Slow()})
    lane = lane_of(
        sessions, {co.tenant}, runner, lease=timedelta(seconds=1.5), heartbeat_seconds=0.3
    )
    reaper = StudioRunReaper(scoped_queue(sessions, frozenset({co.tenant})))
    await lane()
    while lane.running:
        await reaper()
        await asyncio.sleep(0.3)
    for run_id in run_ids:
        row = await run_row(migrator, run_id)
        assert (row.status, row.attempt) == ("completed", 0)


async def test_r5_7_r5_26_the_fifth_death_dead_letters_the_run_and_tells_who_must_know(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
) -> None:
    co, other = await plant(), await plant()
    told_holder = await holder(migrator, co.studio.tenant, MEMBERS_WRITE, "tenant")
    other_holder = await holder(migrator, other.studio.tenant, MEMBERS_WRITE, "tenant")
    run_id = await requested(store, service, co)
    theirs = await requested(store, service, other)
    queue = scoped_queue(sessions, frozenset({co.tenant, other.tenant}))
    reaper = StudioRunReaper(queue, backoff=lambda attempt: timedelta(0))
    lapse = (
        "UPDATE platform.worker_runs SET lease_until = now() - interval '1 second'"
        " WHERE id = ANY(:r)"
    )
    await _claimed(queue, other.tenant)
    for attempt in range(5):
        await _claimed(queue, co.tenant)
        await rows(migrator, lapse, r=[run_id, theirs])
        # Under A, B's orphan is not queued again.
        await queue.requeue_orphans(co.tenant, max_requeues=4, backoff=lambda a: timedelta(0))
        assert (await run_row(migrator, theirs)).status == "running"
        assert (await run_row(migrator, run_id)).attempt == min(attempt + 1, 4)
    row = await run_row(migrator, run_id)
    assert (row.status, row.lease_owner) == ("dead_lettered", None)
    assert await queue.claim(co.tenant, limit=1, worker="w", lease=timedelta(seconds=60)) == []
    (audit,) = await audits(migrator, "run.dead_lettered", run_id)
    assert (audit.actor_id, audit.details["actor"]) == (
        system_actor("studio_run_reaper").value,
        "system:studio_run_reaper",
    )
    (event,) = await rows(
        migrator,
        "SELECT * FROM platform.outbox_events WHERE event_type = 'studio.run.dead_lettered'"
        " AND aggregate_id = :r",
        r=run_id,
    )
    await reaper()  # B's orphan, under B
    assert (await run_row(migrator, theirs)).attempt == 1

    handler = build_dead_letter_handler(
        SqlScopeHolders(sessions), SqlNotificationRepository(sessions)
    )
    outbox = OutboxEvent(
        id=event.id,
        tenant_id=TenantId(event.tenant_id),
        workspace_id=WorkspaceId(event.workspace_id),
        event_type=event.event_type,
        schema_version=event.schema_version,
        aggregate_id=event.aggregate_id,
        occurred_at=event.occurred_at,
        payload=dict(event.payload),
    )
    for _ in range(2):  # delivered again: nothing more
        await handler(outbox)
    key = f"studio.run.dead_lettered:{run_id}"
    assert [n.source_key for n in await told(migrator, told_holder, key)] == [key]
    assert [n.source_key for n in await told(migrator, co.tester.id, key)] == [key]
    assert await told(migrator, other_holder, "studio.run.") == []


# ---- R5.24: the outcomes a run reached -----------------------------------------------------------


async def test_r5_24_a_completed_run_records_the_outcomes_it_reached_and_a_failed_one_too(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    plant: Plant,
    tmp_path: Path,
) -> None:
    co = await plant()
    completed = await requested(store, service, co, outcomes=True)
    runner, _ = build_runner(sessions, {"tool": FileDoor(tmp_path / "d.json")})
    await tick(lane_of(sessions, {co.tenant}, runner))
    row = await run_row(migrator, completed)
    assert (row.status, row.outcomes) == ("completed", ["lead_new"])

    failed = await requested(store, service, co, outcomes=True)
    broken, _ = build_runner(
        sessions, {"tool": ScriptedDoor([RuntimeError("the provider fell over")])}
    )
    await tick(lane_of(sessions, {co.tenant}, broken))
    row = await run_row(migrator, failed)
    assert (row.status, row.outcomes) == ("failed", ["untouched"])
