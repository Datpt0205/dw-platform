"""`RunRequestService` against PostgreSQL (workflow-engine ticket 02: R3.3,
R3.4, R3.6, R3.9-R3.11, R3.17-R3.22; WE19, WE20, WE49-WE51).

Every case calls the door directly, never a route: the route is not the only
caller (failure-modes #5), so what the door refuses is what it refuses for an
in-process caller too. The store is the real `SqlArtifactStore` as `dw_app`;
the run-key table and the lane registry are this module's, the way a
composition root builds them.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_kernel.canonical import content_hash
from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.audit import system_actor
from dw_platform.testing.rbac import assign, plant_membership, plant_person, plant_role
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import (
    LaneRequester,
    PersonRequester,
    QueuedRun,
    Requester,
    RunIntakeTx,
    RunLaneRegistry,
    RunRequest,
    RunRequestService,
)
from dw_studio.core.application.service import ArtifactService
from dw_studio.core.domain.artifacts import DocumentInvalidError, definition_body, definition_hash
from dw_studio.testing.bindings import unasked_pins
from dw_studio.testing.fixture_kinds import (
    FIXTURE,
    FIXTURE_GATELESS,
    FIXTURE_READ,
    FIXTURE_RUN,
    FIXTURE_SUBMIT,
    FIXTURE_WRITE,
    planted_fixture_kinds,
)
from dw_studio.testing.run_manifests import draft_of, fixture_document, published
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REF = "sha256:" + "f" * 64

# The composition root's tables, for the fixture kinds: `fixture` runs `test`
# only, so (`fixture`, `manual`) has no entry (R3.17).
RUN_KEYS = {
    ("fixture", "test"): FIXTURE_RUN,
    ("fixture_gateless", "test"): FIXTURE_RUN,
    ("fixture_gateless", "manual"): FIXTURE_RUN,
}
LANES = {"studio_inbound": ("datahub",), "studio_gate": ("eval",)}


# ---- the world ----------------------------------------------------------------


@dataclass
class RunWorld:
    studio: StudioWorld
    # read, write, submit and run in ws1: the author and the runner.
    runner: Person
    # the same, a second person in ws1.
    runner_two: Person
    # the run key in ws2 only (and read in ws1).
    ws2_runner: Person
    # `platform.admin` at tenant depth and read in ws1, no run key.
    admin: Person
    # the run key in the other company.
    outsider: Person


async def _plant(conn: Any, tenant: Any, ws: uuid.UUID, keys: dict[str, str]) -> Person:
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, ws, user)
    role = await plant_role(conn, tenant.tenant_id, f"run_t_{user.hex[:12]}", keys)
    await assign(conn, tenant.tenant_id, ws, membership, role)
    return Person(user, tenant.tenant_id, ws)


_AUTHOR = {FIXTURE_READ: "workspace", FIXTURE_WRITE: "workspace", FIXTURE_SUBMIT: "workspace"}


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
async def world(migrator: AsyncEngine) -> AsyncIterator[RunWorld]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            studio = await plant_world(conn)
            ws1, ws2 = studio.ws1, studio.ws2
            run = {**_AUTHOR, FIXTURE_RUN: "workspace"}
            planted = RunWorld(
                studio=studio,
                runner=await _plant(conn, studio.tenant, ws1, run),
                runner_two=await _plant(conn, studio.tenant, ws1, run),
                ws2_runner=await _plant(conn, studio.tenant, ws2, {FIXTURE_RUN: "workspace"}),
                admin=await _plant(
                    conn,
                    studio.tenant,
                    ws1,
                    {"platform.admin": "tenant", FIXTURE_READ: "workspace"},
                ),
                outsider=await _plant(conn, studio.other, studio.other.main, run),
            )
        yield planted


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def store(sessions: async_sessionmaker[AsyncSession], world: RunWorld) -> SqlArtifactStore:
    return SqlArtifactStore(sessions, Uuid7Generator())


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(store: SqlArtifactStore) -> ArtifactService:
    return ArtifactService(
        store, ArtifactKindRegistry((FIXTURE, FIXTURE_GATELESS)), SystemClock(), store.ids
    )


def door_of(
    store: Any,
    *,
    entries: Sequence[ArtifactKindEntry] = (FIXTURE, FIXTURE_GATELESS),
    run_keys: dict[tuple[str, str], str] | None = None,
) -> RunRequestService:
    registry = ArtifactKindRegistry(entries)
    return RunRequestService(
        store,
        registry,
        RunManifestBuilder(registry, REF),
        RUN_KEYS if run_keys is None else run_keys,
        RunLaneRegistry(LANES),
        SystemClock(),
        Uuid7Generator(),
        bindings=unasked_pins(),
    )


@pytest.fixture
def door(store: SqlArtifactStore) -> RunRequestService:
    return door_of(store)


# ---- helpers ------------------------------------------------------------------


def person(who: Person, **context: Any) -> PersonRequester:
    return PersonRequester(who.context(**context))


def as_admin(who: Person) -> PersonRequester:
    """`platform_admin` on the verified context: `authz.require` lets it by."""
    return PersonRequester(
        AccessContext(
            tenant_id=who.tenant_id,
            workspace_id=who.workspace_id,
            principal_id=who.id,
            roles=frozenset({"platform_admin"}),
            plan_id="professional",
        )
    )


def ask(
    requester: Requester,
    version_id: uuid.UUID,
    trigger: str = "test",
    *,
    key: str | None = None,
    **fields: Any,
) -> RunRequest:
    return RunRequest(
        requester=requester,
        version_id=version_id,
        trigger_kind=trigger,
        source_key=key or uuid.uuid4().hex,
        **fields,
    )


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def run_row(migrator: AsyncEngine, run_id: uuid.UUID) -> Any:
    (row,) = await rows(migrator, "SELECT * FROM platform.worker_runs WHERE id = :r", r=run_id)
    return row


async def runs_of(migrator: AsyncEngine, artifact_id: uuid.UUID) -> int:
    (row,) = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.worker_runs WHERE artifact_id = :a",
        a=artifact_id,
    )
    return int(row.n)


async def manifests_of(migrator: AsyncEngine, tenant: uuid.UUID) -> int:
    (row,) = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.run_manifests WHERE tenant_id = :t",
        t=tenant,
    )
    return int(row.n)


async def started(migrator: AsyncEngine, run_id: uuid.UUID) -> list[Any]:
    return await rows(
        migrator,
        "SELECT actor_id, workspace_id, details FROM platform.audit_events"
        " WHERE action = 'run.started' AND run_id = :r",
        r=run_id,
    )


async def a_draft(
    service: ArtifactService, who: Person, document: dict[str, Any] | None = None
) -> tuple[uuid.UUID, uuid.UUID, int]:
    return await draft_of(service, who, document or fixture_document(title="nháp"))


async def a_sealed(
    service: ArtifactService, migrator: AsyncEngine, who: Person, stage: str
) -> tuple[uuid.UUID, uuid.UUID]:
    artifact_id, sealed = await published(
        service, migrator, who, fixture_document(title=f"bản {stage}"), stage=stage
    )
    return artifact_id, sealed.version_id


class Unchanged:
    """Counts of rows and manifests, taken before and compared after."""

    def __init__(self, migrator: AsyncEngine, tenant: uuid.UUID, artifact_id: uuid.UUID) -> None:
        self.migrator, self.tenant, self.artifact_id = migrator, tenant, artifact_id
        self.before: tuple[int, int] | None = None

    async def take(self) -> Unchanged:
        self.before = (
            await runs_of(self.migrator, self.artifact_id),
            await manifests_of(self.migrator, self.tenant),
        )
        return self

    async def holds(self) -> None:
        after = (
            await runs_of(self.migrator, self.artifact_id),
            await manifests_of(self.migrator, self.tenant),
        )
        assert after == self.before, "a refused request wrote a run or a manifest"


async def refused(
    door: RunRequestService, request: RunRequest, error: type[Exception], reason: str
) -> None:
    with pytest.raises(error) as caught:
        await door.request(request)
    assert getattr(caught.value, "details", {}).get("reason_code") == reason


# ---- R3.3, R3.18: the row and where each value comes from ----------------------


async def test_r3_3_the_door_queues_one_row_with_every_value_it_decides(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    result = await door.request(
        ask(person(world.runner), version_id, "manual", key="k-r33", input={"x": 1})
    )
    assert result.created
    row = await run_row(migrator, result.run_id)
    (version,) = await rows(
        migrator,
        "SELECT version_no, definition_hash FROM studio.artifact_versions WHERE id = :v",
        v=version_id,
    )
    assert row.status == "queued"
    assert (row.run_mode, row.trigger_kind, row.priority) == ("live", "manual", 0)
    assert row.request_key == f"manual:{world.runner.id}:k-r33"
    assert (row.requested_by, row.run_as_principal_id) == (world.runner.id, world.runner.id)
    assert row.run_manifest_hash.startswith("sha256:")
    assert (row.artifact_kind, row.artifact_id, row.artifact_version_id) == (
        "fixture_gateless",
        artifact_id,
        version_id,
    )
    assert row.definition_hash == version.definition_hash
    assert (row.worker_id, row.worker_version, row.graph_version) == (
        f"studio:fixture_gateless:{artifact_id}",
        str(version.version_no),
        version.definition_hash,
    )
    assert (row.thread_id, row.root_run_id, row.parent_run_id, row.chain_depth) == (
        row.id,
        row.id,
        None,
        0,
    )
    assert row.inbound_event_id is None and row.deadline_at is None
    assert (row.attempt, row.lease_owner, row.lease_until) == (0, None, None)
    assert row.input == {"x": 1}
    assert row.release_manifest_ref == REF


async def test_r3_18_identity_comes_from_the_rows_read_never_from_the_caller(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    """WE50: a caller acting in ws2, asking with an input that names other
    values, gets the root's workspace, kind and hash; the actor stamp is the
    narrowest, never the DEFAULT `open`."""
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    lying = {"workspace_id": str(world.studio.ws2), "artifact_kind": "object"}
    result = await door.request(
        ask(
            person(world.runner, workspace_id=world.studio.ws2),
            version_id,
            "manual",
            input=lying,
        )
    )
    row = await run_row(migrator, result.run_id)
    assert row.workspace_id == world.studio.ws1 != world.studio.ws2
    assert row.artifact_kind == "fixture_gateless"
    assert row.artifact_id == artifact_id
    assert (row.actor_record_visibility, row.actor_scopes, row.actor_roles) == (
        "restricted",
        [],
        [],
    )
    assert (row.actor_visible_owners, row.actor_clearance, row.actor_plan_id) == (
        [],
        "internal",
        "",
    )


async def test_r3_18_a_data_hub_run_is_the_inbound_lanes_acting_as_the_subscriptions_principal(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    _, version_id = await a_sealed(service, migrator, world.runner, "live")
    lane = RunLaneRegistry(LANES).requester("studio_inbound", world.studio.tenant.tenant_id)
    event = uuid.uuid4()
    result = await door.request(
        ask(
            lane,
            version_id,
            "datahub",
            key=f"{event}:sub-1",
            run_as_principal_id=world.runner_two.id,
            inbound_event_id=event,
        )
    )
    row = await run_row(migrator, result.run_id)
    inbound = system_actor("studio_inbound").value
    assert (row.requested_by, row.run_as_principal_id) == (inbound, world.runner_two.id)
    assert (row.run_mode, row.priority, row.inbound_event_id) == ("live", 1, event)
    assert row.request_key == f"datahub:{inbound}:{event}:sub-1"
    (audit,) = await started(migrator, result.run_id)
    assert audit.actor_id == inbound
    assert audit.details["actor"] == "system:studio_inbound"


async def test_r3_18_an_eval_run_is_the_submitters_carried_out_by_the_gate(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    _, version_id = await a_sealed(service, migrator, world.runner, "evaluating")
    lane = RunLaneRegistry(LANES).requester("studio_gate", world.studio.tenant.tenant_id)
    result = await door.request(
        ask(lane, version_id, "eval", key="gate-1:case-1", run_as_principal_id=world.runner.id)
    )
    row = await run_row(migrator, result.run_id)
    assert (row.requested_by, row.run_as_principal_id) == (world.runner.id, world.runner.id)
    assert (row.run_mode, row.priority, row.trigger_kind) == ("simulate", 2, "eval")
    (audit,) = await started(migrator, result.run_id)
    assert audit.actor_id == world.runner.id
    assert audit.details["lane"] == "studio_gate"
    assert "actor" not in audit.details


# ---- R3.17 (WE49): the door checks the person's run key itself -------------------


async def test_r3_17_the_run_key_is_checked_at_the_runs_workspace_by_the_door(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, draft_id, _ = await a_draft(service, world.runner)
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    # No run key anywhere: the author who may write it may not run it.
    await refused(
        door,
        ask(person(world.studio["writer"]), draft_id),
        PermissionDeniedError,
        "permission_denied",
    )
    # The key in ws2 of the same company, the run's workspace being ws1.
    await refused(
        door, ask(person(world.ws2_runner), draft_id), PermissionDeniedError, "permission_denied"
    )
    # `platform_admin`, which `authz.require` would let by, without the key.
    await refused(
        door, ask(as_admin(world.admin), draft_id), PermissionDeniedError, "permission_denied"
    )
    await unchanged.holds()
    # The holder at the run's workspace: one queued row.
    result = await door.request(ask(person(world.runner), draft_id))
    assert (await run_row(migrator, result.run_id)).status == "queued"


async def test_r3_17_a_pair_without_a_run_key_is_refused(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, sealed = await published(
        service, migrator, world.runner, fixture_document(title="gated"), stage="evaluating"
    )
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    # (`fixture`, `manual`) has no entry; the runner holds the key the others name.
    await refused(
        door,
        ask(person(world.runner), sealed.version_id, "manual"),
        PermissionDeniedError,
        "permission_denied",
    )
    await unchanged.holds()


async def test_r3_17_another_companys_version_is_not_found_before_any_key(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, draft_id, _ = await a_draft(service, world.runner)
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    with pytest.raises(NotFoundError):
        await door.request(ask(person(world.outsider), draft_id))
    await unchanged.holds()
    (row,) = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.worker_runs WHERE tenant_id = :t",
        t=world.outsider.tenant_id,
    )
    assert row.n == 0


# ---- R3.19 (WE50): who may ask, and as whom -------------------------------------


async def test_r3_19_a_person_runs_only_as_themself(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    await refused(
        door,
        ask(person(world.runner), version_id, "manual", run_as_principal_id=world.runner_two.id),
        PermissionDeniedError,
        "run_as_mismatch",
    )
    for trigger in ("datahub", "eval"):
        await refused(
            door,
            ask(person(world.runner), version_id, trigger, run_as_principal_id=world.runner.id),
            PermissionDeniedError,
            "run_as_mismatch",
        )
    await unchanged.holds()
    # Naming themself is the same as naming no one.
    named = await door.request(
        ask(person(world.runner), version_id, "manual", run_as_principal_id=world.runner.id)
    )
    assert (await run_row(migrator, named.run_id)).run_as_principal_id == world.runner.id


async def test_r3_19_a_lane_asks_only_for_its_own_kinds_and_names_its_principal(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "evaluating")
    tenant = world.studio.tenant.tenant_id
    unchanged = await Unchanged(migrator, tenant, artifact_id).take()
    lanes = RunLaneRegistry(LANES)
    principal = world.runner.id
    # The inbound lane asks for the gate's kind.
    await refused(
        door,
        ask(
            lanes.requester("studio_inbound", tenant),
            version_id,
            "eval",
            run_as_principal_id=principal,
        ),
        PermissionDeniedError,
        "run_as_mismatch",
    )
    # A lane the door's registry does not list, built by hand.
    await refused(
        door,
        ask(
            LaneRequester("studio_rogue", tenant), version_id, "eval", run_as_principal_id=principal
        ),
        PermissionDeniedError,
        "run_as_mismatch",
    )
    # A registered lane asking for a person's kind.
    await refused(
        door,
        ask(
            lanes.requester("studio_gate", tenant),
            version_id,
            "test",
            run_as_principal_id=principal,
        ),
        PermissionDeniedError,
        "run_as_mismatch",
    )
    # A lane naming no principal.
    await refused(
        door,
        ask(lanes.requester("studio_gate", tenant), version_id, "eval"),
        PermissionDeniedError,
        "run_as_mismatch",
    )
    await unchanged.holds()


# ---- R3.20, R3.6 (WE51): one key, one run ------------------------------------------


async def test_r3_20_the_same_request_twice_is_one_run_and_one_audit(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    _, version_id = await a_sealed(service, migrator, world.runner, "live")
    request = ask(person(world.runner), version_id, "manual", key="k-twice", input={"a": [1]})
    first = await door.request(request)
    second = await door.request(request)
    assert (first.created, second.created) == (True, False)
    assert first.run_id == second.run_id
    assert len(await started(migrator, first.run_id)) == 1


async def test_r3_20_a_reused_key_with_other_content_is_refused_and_changes_nothing(
    door: RunRequestService,
    service: ArtifactService,
    store: SqlArtifactStore,
    migrator: AsyncEngine,
    world: RunWorld,
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    _, other_version = await a_sealed(service, migrator, world.runner, "live")
    first = await door.request(
        ask(person(world.runner), version_id, "manual", key="k-reused", input={"a": 1})
    )
    before = await run_row(migrator, first.run_id)
    for request in (
        ask(person(world.runner), other_version, "manual", key="k-reused", input={"a": 1}),
        ask(person(world.runner), version_id, "manual", key="k-reused", input={"a": 2}),
    ):
        await refused(door, request, ConflictError, "request_key_reused")
    assert await run_row(migrator, first.run_id) == before
    assert await runs_of(migrator, artifact_id) == 1

    # Another run mode under the key: one trigger kind has one mode at the
    # door, so the row is written as the store writes it, in `simulate`.
    async with store.for_person(world.runner.context()) as tx:
        manifest = await RunManifestBuilder(ArtifactKindRegistry((FIXTURE_GATELESS,)), REF).build(
            tx, version_id, "simulate"
        )
        planted = replace(
            await _queued_like(migrator, first.run_id),
            id=uuid.uuid4(),
            run_mode="simulate",
            run_manifest_hash=manifest,
            request_key=f"manual:{world.runner.id}:k-mode",
        )
        assert await tx.insert_queued_run(planted)
    await refused(
        door,
        ask(person(world.runner), version_id, "manual", key="k-mode"),
        ConflictError,
        "request_key_reused",
    )


async def _queued_like(migrator: AsyncEngine, run_id: uuid.UUID) -> QueuedRun:
    row = await run_row(migrator, run_id)
    return QueuedRun(
        id=row.id,
        workspace_id=row.workspace_id,
        worker_id=row.worker_id,
        worker_version=row.worker_version,
        graph_version=row.graph_version,
        requested_by=row.requested_by,
        run_as_principal_id=row.run_as_principal_id,
        run_mode=row.run_mode,
        run_manifest_hash=row.run_manifest_hash,
        definition_hash=row.definition_hash,
        artifact_kind=row.artifact_kind,
        artifact_id=row.artifact_id,
        artifact_version_id=row.artifact_version_id,
        trigger_kind=row.trigger_kind,
        inbound_event_id=row.inbound_event_id,
        request_key=row.request_key,
        priority=row.priority,
        input=row.input,
        release_manifest_ref=row.release_manifest_ref,
    )


async def test_r3_20_two_people_with_one_idempotency_key_get_two_runs(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    mine = await door.request(ask(person(world.runner), version_id, "manual", key="same-key"))
    theirs = await door.request(ask(person(world.runner_two), version_id, "manual", key="same-key"))
    assert mine.created and theirs.created and mine.run_id != theirs.run_id
    assert await runs_of(migrator, artifact_id) == 2


async def test_r3_6_two_concurrent_requests_with_one_key_make_one_row(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    request = ask(person(world.runner), version_id, "manual", key="k-race")
    results = list(await asyncio.gather(door.request(request), door.request(request)))
    assert {r.run_id for r in results} == {results[0].run_id}
    assert sorted(r.created for r in results) == [False, True]
    assert await runs_of(migrator, artifact_id) == 1
    assert len(await started(migrator, results[0].run_id)) == 1


# ---- R3.21: the audit is written with the row -------------------------------------


@dataclass
class _Failing:
    """A store whose transaction raises on the way out: what it wrote rolls back."""

    inner: SqlArtifactStore

    @asynccontextmanager
    async def _failing(self, opened: AbstractAsyncContextManager[Any]) -> AsyncIterator[Any]:
        async with opened as tx:
            yield tx
            raise RuntimeError("the caller's transaction fails after the door")

    def for_person(self, context: AccessContext) -> AbstractAsyncContextManager[RunIntakeTx]:
        return self._failing(self.inner.for_person(context))

    def for_lane(self, lane: LaneRequester) -> AbstractAsyncContextManager[RunIntakeTx]:
        return self._failing(self.inner.for_lane(lane))


async def test_r3_21_a_rolled_back_request_leaves_neither_row_nor_audit(
    store: SqlArtifactStore, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, "live")
    with pytest.raises(RuntimeError):
        await door_of(_Failing(store)).request(ask(person(world.runner), version_id, "manual"))
    assert await runs_of(migrator, artifact_id) == 0
    (row,) = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.audit_events WHERE action = 'run.started'"
        " AND details->>'artifact_version_id' = :v",
        v=str(version_id),
    )
    assert row.n == 0


async def test_r3_21_a_new_row_has_one_run_started_in_the_requesters_name(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    _, version_id = await a_sealed(service, migrator, world.runner, "live")
    result = await door.request(ask(person(world.runner), version_id, "manual"))
    (audit,) = await started(migrator, result.run_id)
    assert (audit.actor_id, audit.workspace_id) == (world.runner.id, world.studio.ws1)
    assert audit.details["trigger_kind"] == "manual"
    assert audit.details["run_mode"] == "live"


# ---- R3.22, R3.4 ---------------------------------------------------------------------


@dataclass
class _Untouched:
    """A store any read of which fails the test."""

    opened: int = 0

    def for_person(self, context: AccessContext) -> AbstractAsyncContextManager[RunIntakeTx]:
        self.opened += 1
        raise AssertionError("the door read before refusing")

    def for_lane(self, lane: LaneRequester) -> AbstractAsyncContextManager[RunIntakeTx]:
        self.opened += 1
        raise AssertionError("the door read before refusing")


@pytest.mark.parametrize("trigger", ["agent_node", "schedule", "subworkflow", "bogus"])
async def test_r3_22_a_kind_outside_w1_is_refused_before_any_read(
    world: RunWorld, trigger: str
) -> None:
    untouched = _Untouched()
    with pytest.raises(DomainError) as caught:
        await door_of(untouched).request(ask(person(world.runner), uuid.uuid4(), trigger))
    assert caught.value.details["reason_code"] == "trigger_kind_unsupported"
    assert untouched.opened == 0


async def test_an_inbound_event_belongs_to_a_data_hub_run_only(world: RunWorld) -> None:
    untouched = _Untouched()
    with pytest.raises(DomainError) as caught:
        await door_of(untouched).request(
            ask(person(world.runner), uuid.uuid4(), "manual", inbound_event_id=uuid.uuid4())
        )
    assert caught.value.details["reason_code"] == "inbound_event_unexpected"
    assert untouched.opened == 0


async def test_r3_4_the_door_calls_no_runner(
    door: RunRequestService,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: RunWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the door ran the run")

    for name in ("start", "stream", "resume"):
        monkeypatch.setattr(LangGraphWorkflowRunner, name, forbidden)
    _, version_id = await a_sealed(service, migrator, world.runner, "live")
    result = await door.request(ask(person(world.runner), version_id, "manual"))
    assert (await run_row(migrator, result.run_id)).status == "queued"


# ---- R3.10 (WE19): live runs only the live version ---------------------------------


@pytest.mark.parametrize("stage", ["awaiting_approval", "retired"])
async def test_r3_10_a_live_request_for_a_version_not_live_is_refused(
    door: RunRequestService,
    service: ArtifactService,
    migrator: AsyncEngine,
    world: RunWorld,
    stage: str,
) -> None:
    artifact_id, version_id = await a_sealed(service, migrator, world.runner, stage)
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    await refused(
        door, ask(person(world.runner), version_id, "manual"), ConflictError, "version_not_live"
    )
    await unchanged.holds()


async def test_r3_10_a_live_request_for_a_draft_is_refused_with_no_manifest(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    artifact_id, draft_id, _ = await draft_of(
        service, world.runner, fixture_document(title="nháp sống"), kind="fixture_gateless"
    )
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    await refused(
        door,
        ask(person(world.runner), draft_id, "manual"),
        ConflictError,
        "draft_root_not_simulate",
    )
    await unchanged.holds()


# ---- R3.9, R3.11 (WE20): a draft is validated once, then pinned ---------------------


async def test_r3_9_a_simulated_draft_pins_the_seals_hash_of_the_content_received(
    door: RunRequestService, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    document = fixture_document(title="nháp ghim")
    artifact_id, draft_id, row_version = await a_draft(service, world.runner, document)
    result = await door.request(ask(person(world.runner), draft_id))
    row = await run_row(migrator, result.run_id)
    assert row.definition_hash is None and row.run_mode == "simulate"
    assert (row.worker_version, row.graph_version) == ("draft", row.run_manifest_hash)
    (manifest,) = await rows(
        migrator, "SELECT body FROM platform.run_manifests WHERE hash = :h", h=row.run_manifest_hash
    )
    expected = definition_hash(definition_body("fixture", artifact_id, content_hash(document), []))
    assert manifest.body["root"]["stage"] == "draft"
    assert manifest.body["root"]["definition_hash"] == expected

    await service.save_draft(
        world.runner.context(),
        artifact_id,
        ExpectedVersion(row_version),
        fixture_document(title="sửa sau"),
    )
    (again,) = await rows(
        migrator, "SELECT body FROM platform.run_manifests WHERE hash = :h", h=row.run_manifest_hash
    )
    assert again.body == manifest.body
    assert (await run_row(migrator, result.run_id)).run_manifest_hash == row.run_manifest_hash


def _spied(entry: ArtifactKindEntry) -> tuple[ArtifactKindEntry, list[Any]]:
    seen: list[Any] = []

    def validate(document: Any) -> Any:
        seen.append(document)
        return entry.validate(document)

    return replace(entry, validate=validate), seen


async def test_r3_11_a_failing_draft_is_refused_with_every_problem_by_the_door_itself(
    store: SqlArtifactStore, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    spied, seen = _spied(FIXTURE)
    door = door_of(store, entries=(spied, FIXTURE_GATELESS))
    artifact_id, draft_id, _ = await a_draft(service, world.runner)
    # Saved past the envelope's own check: the door must find both problems.
    await rows(
        migrator,
        "UPDATE studio.artifact_versions SET document = :d WHERE id = :v",
        d='{"title": 7, "uses": [], "size": -1}',
        v=draft_id,
    )
    unchanged = await Unchanged(migrator, world.studio.tenant.tenant_id, artifact_id).take()
    with pytest.raises(DocumentInvalidError) as caught:
        await door.request(ask(person(world.runner), draft_id))
    assert sorted((p.pointer, p.code) for p in caught.value.problems) == [
        ("/size", "size_invalid"),
        ("/title", "title_required"),
    ]
    assert len(seen) == 1
    await unchanged.holds()

    await rows(
        migrator,
        "UPDATE studio.artifact_versions SET document = :d WHERE id = :v",
        d='{"title": "sửa rồi", "uses": [], "size": 0}',
        v=draft_id,
    )
    result = await door.request(ask(person(world.runner), draft_id))
    assert (await run_row(migrator, result.run_id)).status == "queued"
    assert len(seen) == 2


@dataclass
class _PausedTx:
    """The real transaction, paused once right after the door's first read of
    the root, so a `save_draft` can be started against it."""

    inner: Any
    read: asyncio.Event
    proceed: asyncio.Event
    reads: int = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def root_version(self, version_id: uuid.UUID) -> Any:
        found = await self.inner.root_version(version_id)
        self.reads += 1
        if self.reads == 1:
            self.read.set()
            await self.proceed.wait()
        return found


@dataclass
class _Paused:
    inner: SqlArtifactStore
    read: asyncio.Event
    proceed: asyncio.Event

    @asynccontextmanager
    async def _paused(self, opened: AbstractAsyncContextManager[Any]) -> AsyncIterator[Any]:
        async with opened as tx:
            yield _PausedTx(tx, self.read, self.proceed)

    def for_person(self, context: AccessContext) -> AbstractAsyncContextManager[RunIntakeTx]:
        return self._paused(self.inner.for_person(context))

    def for_lane(self, lane: LaneRequester) -> AbstractAsyncContextManager[RunIntakeTx]:
        return self._paused(self.inner.for_lane(lane))


async def _waiting_or_done(migrator: AsyncEngine, task: asyncio.Task[Any]) -> None:
    """Until another session of this database waits on a lock, or the task
    finished without waiting (a sleep alone passes for a slow statement)."""
    for _ in range(200):
        if task.done():
            return
        (row,) = await rows(
            migrator,
            "SELECT count(*) AS n FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
            " WHERE NOT l.granted AND a.datname = current_database()",
        )
        if row.n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the save neither waited nor finished")


async def test_r3_11_a_concurrent_save_waits_and_the_manifest_hashes_what_was_validated(
    store: SqlArtifactStore, service: ArtifactService, migrator: AsyncEngine, world: RunWorld
) -> None:
    validated = fixture_document(title="đã kiểm")
    artifact_id, draft_id, row_version = await a_draft(service, world.runner, validated)
    read, proceed = asyncio.Event(), asyncio.Event()
    door = door_of(_Paused(store, read, proceed))
    asking = asyncio.create_task(door.request(ask(person(world.runner), draft_id)))
    await asyncio.wait_for(read.wait(), timeout=10)
    saving = asyncio.create_task(
        service.save_draft(
            world.runner.context(),
            artifact_id,
            ExpectedVersion(row_version),
            fixture_document(title="chưa kiểm"),
        )
    )
    try:
        await _waiting_or_done(migrator, saving)
        assert not saving.done(), "the save did not wait for the door"
    finally:
        proceed.set()
        result = await asking
        await saving
    row = await run_row(migrator, result.run_id)
    (manifest,) = await rows(
        migrator, "SELECT body FROM platform.run_manifests WHERE hash = :h", h=row.run_manifest_hash
    )
    expected = definition_hash(definition_body("fixture", artifact_id, content_hash(validated), []))
    assert manifest.body["root"]["definition_hash"] == expected
