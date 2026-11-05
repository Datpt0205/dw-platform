"""A Studio run on PostgreSQL (workflow-engine ticket 03: R1.7, R3.13-R3.16,
R3.23, R4.11, R4.22, R4.25, R4.29, R6.14; WE26, WE38-WE40).

The run door is the real `RunRequestService` over `SqlArtifactStore` as
`dw_app`, the `workflow` kind built over the fixture step types; runs are run
by `LangGraphWorkflowRunner.run_studio` with the real `SqlStudioRunStore` and
checkpoint saver, and doors that keep their sends in a file
(`tests/support/studio_run_stack.py`). A run's reads are `dw_app` queries of
`studio.records` under the context the runner binds for a workflow
(`act_as_run(kind="workflow")`, the binder the record doors of
workflow-nodes/04 will use). Each run gets its `deadline_at` from the
migrator, as workflow-engine/04's lane sets it when it takes the run.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
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
from studio_run_stack import DIED, FileDoor, build_runner

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.domain.audit import system_actor
from dw_platform.testing.rbac import assign, plant_membership, plant_person, plant_role
from dw_platform.testing.record_objects import plant_object
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import (
    PersonRequester,
    RunLaneRegistry,
    RunRequest,
    RunRequestService,
)
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import WORKFLOWS_TEST_SCOPE, run_boundary_derivers, run_pinnable_steps
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.testing.bindings import unasked_pins
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import move_for_test
from dw_studio.testing.records import act_as_run, plant_record
from dw_studio.testing.run_manifests import (
    draft_of,
    fixture_document,
    published,
    sealed,
    shipped_models,
)
from dw_studio.testing.workflows import (
    WORKFLOW_KEYS,
    FakeTriggerActivation,
    studio_document,
    studio_step,
    workflow_entry,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REF = "sha256:" + "f" * 64
REGISTRY = fixture_node_registry()
CHILD = Path(__file__).resolve().parent / "studio_run_child.py"
LANES = {"studio_gate": ("eval",)}


# ---- the world ----------------------------------------------------------------


@dataclass
class World:
    studio: StudioWorld
    # the workflow keys in the main workspace, and read on Lead at own depth.
    tester: Person
    # another member, owner of `x2`.
    stranger: Person
    lead: uuid.UUID
    x1: uuid.UUID
    x2: uuid.UUID

    @property
    def tenant(self) -> uuid.UUID:
        return self.tester.tenant_id


async def _plant_tester(conn: Any, tenant: Any, lead: uuid.UUID) -> Person:
    t = tenant.tenant_id
    user = await plant_person(conn, t)
    membership = await plant_membership(conn, t, tenant.main, user)
    role = await plant_role(
        conn, t, f"wf_run_{user.hex[:10]}", dict.fromkeys(WORKFLOW_KEYS, "workspace")
    )
    for action in ("read", "update"):
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_object_privileges"
                " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, 'own')"
            ),
            {"t": t, "r": role, "o": lead, "a": action},
        )
    await assign(conn, t, tenant.main, membership, role)
    return Person(user, t, tenant.main)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_engine(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(migrator: AsyncEngine) -> AsyncIterator[World]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            studio = await plant_world(conn)
            tenant = studio.tenant
            lead = (await plant_object(conn, tenant, "mkt_lead", {"ghi_chu": "none"})).object_id
            tester = await _plant_tester(conn, tenant, lead)
            stranger = await _plant_tester(conn, tenant, lead)
            x1 = await plant_record(conn, tenant.tenant_id, lead, tenant.main, tester.id)
            x2 = await plant_record(conn, tenant.tenant_id, lead, tenant.main, stranger.id)
        yield World(studio, tester, stranger, lead, x1, x2)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def store(sessions: async_sessionmaker[AsyncSession], world: World) -> SqlArtifactStore:
    return SqlArtifactStore(sessions, Uuid7Generator())


def registry_of() -> ArtifactKindRegistry:
    return ArtifactKindRegistry((*FIXTURE_KINDS, workflow_entry(FakeTriggerActivation())))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(store: SqlArtifactStore) -> ArtifactService:
    return ArtifactService(store, registry_of(), SystemClock(), store.ids)


def door_of(store: Any, *, derivers: Mapping[str, Any] | None = None) -> RunRequestService:
    registry = registry_of()
    return RunRequestService(
        store,
        registry,
        RunManifestBuilder(registry, REF, shipped_models()),
        {("workflow", "test"): WORKFLOWS_TEST_SCOPE},
        RunLaneRegistry(LANES),
        SystemClock(),
        Uuid7Generator(),
        bindings=unasked_pins(),
        boundaries=SqlActorBoundaries(),
        boundary_derivers=run_boundary_derivers(REGISTRY) if derivers is None else derivers,
        pinnable=run_pinnable_steps(REGISTRY),
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def source(service: ArtifactService, migrator: AsyncEngine, world: World) -> uuid.UUID:
    """The trigger's data source every document names, live."""
    artifact, _ = await published(service, migrator, world.studio["writer"], fixture_document())
    return artifact


# ---- helpers --------------------------------------------------------------------


def reads_lead(step_id: str = "doc", **policy: Any) -> dict[str, Any]:
    return {
        **studio_step(step_id, "fixture.records@1", object="mkt_lead", command="read"),
        **policy,
    }


def send(step_id: str) -> dict[str, Any]:
    return studio_step(step_id, "fixture.effect@1")


def doc(source: uuid.UUID, *steps: dict[str, Any]) -> dict[str, Any]:
    return {
        **studio_document(*steps, source=str(source)),
        "decision_classes": [
            {"key": "lead.send", "effect_level": "internal", "reversible": True, "ceiling": "A2"}
        ],
    }


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def provisional_of(migrator: AsyncEngine, run_id: uuid.UUID) -> list[Any]:
    return await rows(
        migrator,
        "SELECT id, kind, source_id, source_version FROM studio.actor_boundaries WHERE run_id = :r",
        r=run_id,
    )


async def with_deadline(migrator: AsyncEngine, run_id: uuid.UUID, minutes: int = 30) -> None:
    await rows(
        migrator,
        "UPDATE platform.worker_runs SET deadline_at = now() + make_interval(mins => :m)"
        " WHERE id = :r",
        m=minutes,
        r=run_id,
    )


async def visible(app_engine: AsyncEngine, world: World, run_id: uuid.UUID) -> set[uuid.UUID]:
    """The Lead records a query reads under the run's workflow context."""
    async with app_engine.begin() as conn:
        await act_as_run(
            conn,
            world.tenant,
            world.tester.id,
            run_id,
            kind="workflow",
            workspace_id=world.tester.workspace_id,
        )
        found = await conn.execute(
            sa.text("SELECT id FROM studio.records WHERE object_id = :o"), {"o": world.lead}
        )
        return {row.id for row in found}


async def read_as(
    app_engine: AsyncEngine, world: World, boundary: uuid.UUID, mode: str
) -> set[uuid.UUID]:
    """A query bound by hand to `boundary` in `mode`: what a run of another
    mode carrying that id would read."""
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true),"
                " set_config('app.workspace_id', :w, true),"
                " set_config('app.actor_kind', 'workflow', true),"
                " set_config('app.boundary_id', :b, true), set_config('app.run_mode', :m, true)"
            ),
            {
                "t": str(world.tenant),
                "u": str(world.tester.id),
                "w": str(world.tester.workspace_id),
                "b": str(boundary),
                "m": mode,
            },
        )
        (await conn.execute(sa.text("SELECT studio.ensure_principal_scope()"))).first()
        found = await conn.execute(
            sa.text("SELECT id FROM studio.records WHERE object_id = :o"), {"o": world.lead}
        )
        return {row.id for row in found}


def ask(world: World, version_id: uuid.UUID, **fields: Any) -> RunRequest:
    return RunRequest(
        requester=PersonRequester(world.tester.context()),
        version_id=version_id,
        trigger_kind="test",
        source_key=uuid.uuid4().hex,
        **fields,
    )


async def a_draft(
    service: ArtifactService, world: World, document: dict[str, Any]
) -> tuple[uuid.UUID, uuid.UUID, int]:
    return await draft_of(service, world.tester, document, kind="workflow")


async def a_candidate(
    service: ArtifactService, migrator: AsyncEngine, world: World, document: dict[str, Any]
) -> tuple[uuid.UUID, uuid.UUID, str]:
    artifact, _, row_version = await a_draft(service, world, document)
    result = await sealed(service, world.tester, artifact, row_version)
    await move_for_test(migrator, result.version_id, "evaluating")
    (row,) = await rows(
        migrator,
        "SELECT definition_hash FROM studio.artifact_versions WHERE id = :v",
        v=result.version_id,
    )
    return artifact, result.version_id, str(row.definition_hash)


class _RolledBackError(Exception):
    pass


class RollingBack:
    """The store, with each transaction rolled back after the door is done."""

    def __init__(self, inner: SqlArtifactStore) -> None:
        self.inner = inner

    @asynccontextmanager
    async def for_person(self, context: Any) -> AsyncIterator[Any]:
        async with self.inner.for_person(context) as tx:
            yield tx
            raise _RolledBackError

    def for_lane(self, lane: Any) -> Any:
        return self.inner.for_lane(lane)


# ---- R3.16, R3.23: the pinned results column ---------------------------------------


_INSERT_RUN = (
    "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id, worker_id,"
    " worker_version, graph_version, requested_by, run_mode, pinned_results)"
    " VALUES (:r, :r, :t, :w, 'studio', '1', '1', :u, :m, CAST(:p AS jsonb))"
)


async def _as_app(app_engine: AsyncEngine, world: World, statement: str, **values: Any) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(world.tenant)}
        )
        await conn.execute(sa.text(statement), values)


def _constraint(error: BaseException) -> str | None:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


async def test_r3_16_a_live_row_never_carries_pinned_results(
    app_engine: AsyncEngine, world: World
) -> None:
    values = {"t": world.tenant, "w": world.tester.workspace_id, "u": world.tester.id}
    with pytest.raises(DBAPIError) as refused:
        await _as_app(
            app_engine,
            world,
            _INSERT_RUN,
            r=uuid.uuid4(),
            m="live",
            p='{"a": {"output": {}}}',
            **values,
        )
    assert _constraint(refused.value) == "ck_worker_runs_pinned_results_simulate"
    # The control: the same row in `simulate` is taken.
    await _as_app(
        app_engine,
        world,
        _INSERT_RUN,
        r=uuid.uuid4(),
        m="simulate",
        p='{"a": {"output": {}}}',
        **values,
    )


async def test_r3_23_pinned_results_never_change_once_inserted(
    app_engine: AsyncEngine, world: World
) -> None:
    run_id = uuid.uuid4()
    values = {"t": world.tenant, "w": world.tester.workspace_id, "u": world.tester.id}
    await _as_app(
        app_engine, world, _INSERT_RUN, r=run_id, m="simulate", p='{"a": {"output": {}}}', **values
    )
    with pytest.raises(DBAPIError) as refused:
        await _as_app(
            app_engine,
            world,
            "UPDATE platform.worker_runs SET pinned_results = '{}'::jsonb WHERE id = :r",
            r=run_id,
        )
    assert _constraint(refused.value) == "ck_worker_runs_pinned_results_immutable"
    # Another column of the row still changes.
    await _as_app(
        app_engine,
        world,
        "UPDATE platform.worker_runs SET status = 'running' WHERE id = :r",
        r=run_id,
    )


async def test_r3_16_the_door_refuses_pinned_results_on_a_live_run(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version, _ = await a_draft(service, world, doc(source, send("gui")))
    request = RunRequest(
        requester=PersonRequester(world.tester.context()),
        version_id=version,
        trigger_kind="manual",
        source_key=uuid.uuid4().hex,
        pinned_results={"gui": {"output": {"done": True}}},
    )
    with pytest.raises(DomainError) as refused:
        await door_of(store).request(request)
    assert refused.value.details["reason_code"] == "pinned_result_invalid"
    assert (
        await rows(
            migrator, "SELECT 1 FROM platform.worker_runs WHERE artifact_version_id = :v", v=version
        )
        == []
    )


@pytest.mark.parametrize(
    ("pinned", "accepted"),
    [
        ({"khong_co": {"output": {}}}, False),
        ({"re": {"output": {"case": "a"}}}, False),
        ({"duyet": {"output": {"approved": True}}}, False),
        ({"gui": {"oops": {}}}, False),
        ({"gui": {"output": {"done": True}}}, True),
        ({"soan": {"error": {"code": "rejected", "message": "Từ chối"}}}, True),
    ],
)
async def test_r3_23_a_pinned_result_names_a_step_with_a_door(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
    pinned: dict[str, Any],
    accepted: bool,
) -> None:
    document = doc(
        source,
        send("gui"),
        studio_step(
            "soan",
            "ai.llm@1",
            prompt="lead.reply@1.0.0",
            inputs={},
            output_schema={"type": "object", "properties": {}},
        ),
        studio_step("re", "logic.switch@1", on="{{ steps.gui.done }}", cases={"a": []}, default=[]),
        studio_step(
            "duyet",
            "human.approval@1",
            decision_class="lead.send",
            proposal="x",
            approved=[],
            rejected=[],
        ),
    )
    _, version, _ = await a_draft(service, world, document)
    request = ask(world, version, pinned_results=pinned)
    if accepted:
        result = await door_of(store).request(request)
        (row,) = await rows(
            migrator,
            "SELECT pinned_results FROM platform.worker_runs WHERE id = :r",
            r=result.run_id,
        )
        assert row.pinned_results == pinned
        return
    with pytest.raises(DomainError) as refused:
        await door_of(store).request(request)
    assert refused.value.details["reason_code"] == "pinned_result_invalid"
    assert (
        await rows(
            migrator, "SELECT 1 FROM platform.worker_runs WHERE artifact_version_id = :v", v=version
        )
        == []
    )


# ---- R3.13, R3.15: the provisional boundary of a run not yet live ----------------


async def test_r3_13_a_drafts_simulated_run_reads_under_its_provisional_boundary(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version, _ = await a_draft(service, world, doc(source, reads_lead()))
    result = await door_of(store).request(ask(world, version))
    ((boundary, kind, source_id, pinned),) = await provisional_of(migrator, result.run_id)
    (manifest,) = await rows(
        migrator,
        "SELECT m.body -> 'root' ->> 'definition_hash' AS h FROM platform.worker_runs r"
        " JOIN platform.run_manifests m"
        " ON m.tenant_id = r.tenant_id AND m.hash = r.run_manifest_hash"
        " WHERE r.id = :r",
        r=result.run_id,
    )
    assert (kind, source_id, pinned) == ("workflow", version, manifest.h)
    # The tester reads their own Lead and not the stranger's.
    assert await visible(app_engine, world, result.run_id) == {world.x1}
    # A live run carrying that id reads nothing (record-access R6.13).
    assert await read_as(app_engine, world, boundary, "live") == set()
    assert await read_as(app_engine, world, boundary, "simulate") == {world.x1}


async def test_r3_13_a_rolled_back_door_leaves_no_provisional_boundary(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version, _ = await a_draft(service, world, doc(source, reads_lead()))
    with pytest.raises(_RolledBackError):
        await door_of(RollingBack(store)).request(ask(world, version))
    assert (
        await rows(
            migrator, "SELECT 1 FROM studio.actor_boundaries WHERE source_id = :v", v=version
        )
        == []
    )


async def test_r3_13_a_kind_without_a_deriver_is_refused_before_any_row(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version, _ = await a_draft(service, world, doc(source, reads_lead()))
    with pytest.raises(ConflictError) as refused:
        await door_of(store, derivers={}).request(ask(world, version))
    assert refused.value.details["reason_code"] == "boundary_deriver_missing"
    assert (
        await rows(
            migrator, "SELECT 1 FROM platform.worker_runs WHERE artifact_version_id = :v", v=version
        )
        == []
    )


async def test_r3_13_another_tenants_run_takes_no_provisional_boundary(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version, _ = await a_draft(service, world, doc(source, reads_lead()))
    result = await door_of(store).request(ask(world, version))
    other = world.studio.other.tenant_id
    with pytest.raises(DBAPIError):
        async with tenant_session(sessions, TenantScope(tenant_id=other)) as session:
            await SqlActorBoundaries().record_provisional(
                session, "workflow", result.run_id, version, "sha256:" + "1" * 64, (), ()
            )
    assert len(await provisional_of(migrator, result.run_id)) == 1


async def test_r3_15_a_candidates_gate_trial_reads_what_its_submitter_sees(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    _, version, definition = await a_candidate(service, migrator, world, doc(source, reads_lead()))
    lanes = RunLaneRegistry(LANES)
    request = RunRequest(
        requester=lanes.requester("studio_gate", world.tenant),
        version_id=version,
        trigger_kind="eval",
        source_key=uuid.uuid4().hex,
        run_as_principal_id=world.tester.id,
    )
    result = await door_of(store).request(request)
    ((boundary, _, source_id, pinned),) = await provisional_of(migrator, result.run_id)
    assert (source_id, pinned) == (version, definition)
    assert await visible(app_engine, world, result.run_id) == {world.x1}
    assert await read_as(app_engine, world, boundary, "live") == set()


# ---- R3.14: the provisional boundary ends with its run -----------------------------


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "dead_lettered"])
async def test_r3_14_a_runs_end_deletes_its_provisional_boundary_and_nothing_else(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
    status: str,
) -> None:
    _, draft_version, _ = await a_draft(service, world, doc(source, reads_lead()))
    draft_run = (await door_of(store).request(ask(world, draft_version))).run_id
    _, candidate, definition = await a_candidate(
        service, migrator, world, doc(source, reads_lead())
    )
    lanes = RunLaneRegistry(LANES)
    gate_run = (
        await door_of(store).request(
            RunRequest(
                requester=lanes.requester("studio_gate", world.tenant),
                version_id=candidate,
                trigger_kind="eval",
                source_key=uuid.uuid4().hex,
                run_as_principal_id=world.tester.id,
            )
        )
    ).run_id
    # A published boundary of the candidate's version, which no run end touches.
    async with tenant_session(sessions, TenantScope(tenant_id=world.tenant)) as session:
        published_id = await SqlActorBoundaries().record(
            session, "workflow", candidate, definition, (), ()
        )
    for run_id in (draft_run, gate_run):
        assert len(await provisional_of(migrator, run_id)) == 1
        # As the kill lane writes it: one UPDATE of the status, as `dw_app`.
        await _as_app(
            app_engine,
            world,
            "UPDATE platform.worker_runs SET status = :s WHERE id = :r",
            s=status,
            r=run_id,
        )
        assert await provisional_of(migrator, run_id) == []
    assert await rows(
        migrator, "SELECT 1 FROM studio.actor_boundaries WHERE id = :b", b=published_id
    )


# ---- R1.7: the published version's boundary ----------------------------------------


async def test_r1_7_the_publish_hook_records_the_versions_boundary_on_its_transaction(
    store: SqlArtifactStore,
    service: ArtifactService,
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
) -> None:
    creates = studio_step("tao", "fixture.records@1", object="mkt_lead", command="create")
    risky = {**send("thu"), "on_error": "route", "error_lane": [creates]}
    artifact, version, definition = await a_candidate(
        service, migrator, world, doc(source, reads_lead(), risky)
    )
    entry = workflow_entry(
        FakeTriggerActivation(versions={version: artifact}), SqlActorBoundaries()
    )
    publish_hook = entry.publish_hook
    assert publish_hook is not None
    # Rolled back: nothing stays.
    with pytest.raises(_RolledBackError):
        async with store.transaction(world.tester.context()) as tx:
            await publish_hook(tx, version)
            raise _RolledBackError
    assert (
        await rows(
            migrator, "SELECT 1 FROM studio.actor_boundaries WHERE source_id = :v", v=version
        )
        == []
    )
    async with store.transaction(world.tester.context()) as tx:
        await publish_hook(tx, version)
    found = await rows(
        migrator,
        "SELECT b.kind, b.source_version, o.object_id, o.can_read, o.can_create, o.can_update,"
        " o.can_delete, o.can_assign FROM studio.actor_boundaries b"
        " JOIN studio.actor_boundary_objects o"
        " ON o.tenant_id = b.tenant_id AND o.boundary_id = b.id"
        " WHERE b.source_id = :v AND b.run_id IS NULL",
        v=version,
    )
    assert [tuple(row) for row in found] == [
        ("workflow", definition, world.lead, True, True, False, False, False)
    ]
    # A live run of that version reads under it, and cannot update.
    run_id = uuid.uuid4()
    manifest = "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex
    await rows(
        migrator,
        "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
        " VALUES (:t, :h, CAST(:b AS jsonb))",
        b='{"run_mode": "live"}',
        t=world.tenant,
        h=manifest,
    )
    await rows(
        migrator,
        "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id, worker_id,"
        " worker_version, graph_version, requested_by, run_as_principal_id, run_mode,"
        " run_manifest_hash, artifact_kind, artifact_id, artifact_version_id, definition_hash,"
        " trigger_kind, request_key) VALUES (:r, :r, :t, :w, 'studio', '1', '1', :u, :u, 'live',"
        " :m, 'workflow', :a, :v, :h, 'manual', :k)",
        r=run_id,
        t=world.tenant,
        w=world.tester.workspace_id,
        u=world.tester.id,
        m=manifest,
        a=artifact,
        v=version,
        h=definition,
        k=uuid.uuid4().hex,
    )
    assert await visible(app_engine, world, run_id) == {world.x1}
    async with app_engine.begin() as conn:
        await act_as_run(
            conn,
            world.tenant,
            world.tester.id,
            run_id,
            kind="workflow",
            workspace_id=world.tester.workspace_id,
        )
        changed = await conn.execute(
            sa.text("UPDATE studio.records SET name = 'đổi' WHERE id = :x"), {"x": world.x1}
        )
        assert changed.rowcount == 0


# ---- R6.14, R4.11, R4.29: run_studio on the real row -------------------------------


async def test_r6_14_a_draft_edited_after_the_door_blocks_its_run_and_compiles_nothing(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
    tmp_path: Path,
) -> None:
    artifact, version, row_version = await a_draft(service, world, doc(source, send("gui")))
    edited = (await door_of(store).request(ask(world, version))).run_id
    _unchanged_artifact, unchanged_version, _ = await a_draft(
        service, world, doc(source, send("gui"))
    )
    unchanged = (await door_of(store).request(ask(world, unchanged_version))).run_id
    for run_id in (edited, unchanged):
        await with_deadline(migrator, run_id)
    await service.save_draft(
        world.tester.context(),
        artifact,
        ExpectedVersion(row_version),
        doc(source, send("gui"), send("them")),
    )
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door})
    assert await runner.run_studio(tenant_id=world.tenant, run_id=edited) == RunStatus.BLOCKED
    (row,) = await rows(
        migrator, "SELECT status, error FROM platform.worker_runs WHERE id = :r", r=edited
    )
    assert (row.status, row.error) == ("blocked", {"code": "incompatible_resume"})
    assert door.calls() == [] and runner._compiled == {}
    assert await runner.run_studio(tenant_id=world.tenant, run_id=unchanged) == RunStatus.COMPLETED
    assert [c[1].split(":")[2] for c in door.calls()] == ["gui"]


async def test_r4_11_past_its_deadline_a_run_is_cancelled_and_audited_by_its_lane(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
    tmp_path: Path,
) -> None:
    _, version, _ = await a_draft(service, world, doc(source, send("gui")))
    run_id = (await door_of(store).request(ask(world, version))).run_id
    await with_deadline(migrator, run_id, minutes=-1)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door})
    assert await runner.run_studio(tenant_id=world.tenant, run_id=run_id) == RunStatus.CANCELLED
    (row,) = await rows(
        migrator, "SELECT status, error FROM platform.worker_runs WHERE id = :r", r=run_id
    )
    assert (row.status, row.error) == ("cancelled", {"code": "deadline_exceeded"})
    audits = await rows(
        migrator,
        "SELECT actor_id, details FROM platform.audit_events"
        " WHERE action = 'run.deadline_exceeded' AND run_id = :r",
        r=run_id,
    )
    assert [(a.actor_id, a.details["actor"]) for a in audits] == [
        (system_actor("studio_runs").value, "system:studio_runs")
    ]
    assert door.calls() == []


async def test_r4_29_a_pinned_approval_written_past_the_door_fails_at_that_step(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    app_engine: AsyncEngine,
    world: World,
    source: uuid.UUID,
    tmp_path: Path,
) -> None:
    approval = studio_step(
        "duyet",
        "human.approval@1",
        decision_class="lead.send",
        proposal="x",
        approved=[send("gui")],
        rejected=[],
    )
    _, version, _ = await a_draft(service, world, doc(source, send("truoc"), approval))
    decided = {"approval_decisions": {"duyet": "rejected"}}
    honest = (await door_of(store).request(ask(world, version, input=decided))).run_id
    # A copy of its row written straight by `dw_app`, with a pinned result
    # for the approval that the door refuses (R3.23).
    bent = uuid.uuid4()
    await _as_app(
        app_engine,
        world,
        "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id, worker_id,"
        " worker_version, graph_version, requested_by, run_as_principal_id, run_mode,"
        " run_manifest_hash, artifact_kind, artifact_id, artifact_version_id, trigger_kind,"
        " request_key, input, pinned_results, status, actor_record_visibility)"
        " SELECT :b, :b, tenant_id, workspace_id, worker_id, worker_version, graph_version,"
        " requested_by, run_as_principal_id, run_mode, run_manifest_hash, artifact_kind,"
        " artifact_id, artifact_version_id, trigger_kind, :k, input,"
        " '{\"duyet\": {\"output\": {\"approved\": true}}}'::jsonb, 'queued', 'restricted'"
        " FROM platform.worker_runs WHERE id = :h",
        b=bent,
        k=uuid.uuid4().hex,
        h=honest,
    )
    for run_id in (honest, bent):
        await with_deadline(migrator, run_id)
    door = FileDoor(tmp_path / "door.json")
    runner, _ = build_runner(sessions, {"tool": door})
    assert await runner.run_studio(tenant_id=world.tenant, run_id=bent) == RunStatus.FAILED
    (row,) = await rows(migrator, "SELECT error FROM platform.worker_runs WHERE id = :r", r=bent)
    assert row.error == {"code": "pinned_result_invalid", "step_id": "duyet"}
    assert [c[1].split(":")[1:3] for c in door.calls()] == [[str(bent), "truoc"]]
    assert (
        await rows(migrator, "SELECT 1 FROM platform.approval_requests WHERE run_id = :r", r=bent)
        == []
    )
    # The honest run takes the rejected lane by its simulated decision.
    assert await runner.run_studio(tenant_id=world.tenant, run_id=honest) == RunStatus.COMPLETED
    assert [c[1].split(":")[2] for c in door.calls()][1:] == ["truoc"]


# ---- R4.22, R4.25: a real process death ------------------------------------------


async def test_r4_25_a_worker_killed_after_a_send_resumes_after_it_and_replays_the_write(
    store: SqlArtifactStore,
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
    source: uuid.UUID,
    studio_db: DatabaseUrls,
    tmp_path: Path,
) -> None:
    """A child process runs `mot` (a send) then `sua` (a record update) and
    dies by `os._exit` right after `sua` applied, before its answer or its
    checkpoint (K3). Taken again (status set back to `queued`, as
    workflow-engine/04's reaper does), the run goes on after `mot`, whose
    checkpoint was durable (`durability` `sync`), and `sua` replays its key."""
    update = studio_step(
        "sua", "fixture.records@1", object="mkt_lead", command="update", record=str(world.x1)
    )
    _, version, _ = await a_draft(service, world, doc(source, send("mot"), update))
    run_id = (await door_of(store).request(ask(world, version))).run_id
    await with_deadline(migrator, run_id)
    door_file = tmp_path / "door.json"
    child = subprocess.run(
        [
            sys.executable,
            str(CHILD),
            studio_db.app,
            str(world.tenant),
            str(run_id),
            str(door_file),
            "sua",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert child.returncode == DIED, child.stderr[-2000:]
    door = FileDoor(door_file)
    assert [c[1].split(":")[2] for c in door.calls()] == ["mot", "sua"]
    await rows(
        migrator, "UPDATE platform.worker_runs SET status = 'queued' WHERE id = :r", r=run_id
    )
    runner, _ = build_runner(sessions, {"tool": door, "records": door})
    assert await runner.run_studio(tenant_id=world.tenant, run_id=run_id) == RunStatus.COMPLETED
    calls = [c[1].split(":")[2] for c in door.calls()]
    assert calls == ["mot", "sua", "sua"], "the send before the death was made again"
    assert len({c[1] for c in door.calls() if c[1].endswith(":sua:")}) == 1
