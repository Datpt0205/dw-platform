"""Bindings and their configuration versions against PostgreSQL (tenant-config
ticket 05: R2.18, R3.7, R3.8, R7.1-R7.6, R8.1-R8.19; TC15-TC20, TC22, TC23,
TC25, TC26, TC29, TC31, TC33, TC34).

Every case calls a door directly: `ConfigVersionService` (propose, withdraw),
the approval flow's own `decide` with the composition root's strict prefix and
guard, `ConfigSettlement` as the worker's handler calls it, `BindingStatus`,
the run door `RunRequestService` and `SqlRunBindings`, each over the real SQL
adapters as `dw_app` and the real `ConnectionUsability`. The database's own
rules (the transition trigger, the composite keys, the CHECKs, the delete
guard, the grants) are tested by writing past every service.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.config_versions_repo import (
    SqlConfigVersionStore,
    SqlConfigVersionTx,
)
from dw_platform.adapters.persistence.connections_repo import SqlConnectionStore
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.config_versions import (
    CONFIG_PREFIX,
    CONFIG_VERSION,
    ConfigKindRegistry,
    ConfigSettlement,
    ConfigVersionDecisions,
    ConfigVersionRow,
    ConfigVersionService,
    NewConfigVersion,
)
from dw_platform.application.connections import (
    CONNECTIONS_READ_SCOPE,
    CONNECTIONS_USE_SCOPE,
    ConnectionUsability,
    NoConnectorCatalog,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest, ProposedDecision
from dw_platform.testing.rbac import (
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.run_bindings import SqlRunBindings
from dw_studio.core.application.bindings import (
    BINDING_SET,
    BINDINGS_APPROVE_SCOPE,
    BINDINGS_PROPOSE_SCOPE,
    BindingConnectionDependents,
    BindingPins,
    BindingSets,
    BindingsReader,
    BindingStatus,
    BindingTypes,
    platform_binding_types,
)
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import (
    PersonRequester,
    RunLaneRegistry,
    RunRequest,
    RunRequestService,
)
from dw_studio.core.application.service import ArtifactService
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.core.domain.bindings import BindingKind
from dw_studio.core.domain.run_manifest import RunManifest
from dw_studio.testing.fixture_kinds import (
    FIXTURE_KINDS,
    FIXTURE_READ,
    FIXTURE_RUN,
    FIXTURE_SUBMIT,
    FIXTURE_WRITE,
    planted_fixture_kinds,
)
from dw_studio.testing.lifecycle import move_for_test
from dw_studio.testing.run_manifests import draft_of, published, sealed, shipped_models
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REF = "sha256:" + "e" * 64
CONNECTOR = ("smtp", 1)


def _connection(name: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "connection",
        "required": required,
        "connector_key": CONNECTOR[0],
        "connector_major": CONNECTOR[1],
        "required_scopes": [],
    }


def _variable(name: str, *, required: bool = True, default: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "kind": "variable",
        "required": required,
        "schema": {"type": "integer", "minimum": 0, "maximum": 100},
    }
    if default is not None:
        body["default"] = default
    return body


def _principal(name: str, *, required: bool = True) -> dict[str, Any]:
    return {"name": name, "kind": "principal", "required": required}


def _doc(
    *bindings: dict[str, Any], uses: tuple[uuid.UUID, ...] = (), title: str = "Gửi"
) -> dict[str, Any]:
    return {
        "title": title,
        "uses": [str(u) for u in uses],
        "size": 0,
        "bindings": list(bindings),
    }


# ---- the world ----------------------------------------------------------------


@dataclass
class World:
    studio: StudioWorld
    # read, write, submit, run, propose, connections.use and read in ws1.
    proposer: Person
    # read and approve in ws1.
    approver: Person
    # approve in ws2 alone, reads nothing: no checker anywhere.
    approve_only_ws2: Person
    # read in ws1, propose in ws2 only.
    reads_ws1_proposes_ws2: Person
    # read and propose in ws2 only.
    ws2_proposer: Person
    # read and propose in ws1, no connections.use.
    no_use: Person
    # read in ws1 only.
    read_only: Person
    # write and read in ws2, propose and approve there: no other checker.
    ws2_alone: Person
    # a suspended member of the company.
    suspended: uuid.UUID
    connection: uuid.UUID
    other_connector: uuid.UUID
    foreign_connection: uuid.UUID
    outsider: Person

    @property
    def tenant(self) -> uuid.UUID:
        return self.studio.tenant.tenant_id


async def _plant(conn: Any, tenant: Any, ws: uuid.UUID, keys: dict[str, str]) -> Person:
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, ws, user)
    role = await plant_role(conn, tenant.tenant_id, f"bind_t_{user.hex[:12]}", keys)
    await assign(conn, tenant.tenant_id, ws, membership, role)
    return Person(user, tenant.tenant_id, ws)


async def _connection_row(
    conn: Any, tenant_id: uuid.UUID, workspace: uuid.UUID, connector: tuple[str, int] = CONNECTOR
) -> uuid.UUID:
    connection = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO platform.connections (id, tenant_id, owning_workspace_id, name,"
            " connector_key, connector_major, share_scope, external_account, status)"
            " VALUES (:c, :t, :w, 'Hộp thư', :k, :m, 'workspace', :a, 'active')"
        ),
        {
            "c": connection,
            "t": tenant_id,
            "w": workspace,
            "k": connector[0],
            "m": connector[1],
            "a": f"{connection.hex[:10]}@acme.vn",
        },
    )
    return connection


_W = "workspace"
_AUTHOR = {FIXTURE_READ: _W, FIXTURE_WRITE: _W, FIXTURE_SUBMIT: _W, FIXTURE_RUN: _W}


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
            tenant, ws1, ws2 = studio.tenant, studio.ws1, studio.ws2
            suspended = await plant_person(conn, tenant.tenant_id, status="suspended")
            yield_world = World(
                studio=studio,
                proposer=await _plant(
                    conn,
                    tenant,
                    ws1,
                    {
                        **_AUTHOR,
                        BINDINGS_PROPOSE_SCOPE: _W,
                        CONNECTIONS_USE_SCOPE: _W,
                        CONNECTIONS_READ_SCOPE: _W,
                    },
                ),
                approver=await _plant(
                    conn, tenant, ws1, {FIXTURE_READ: _W, BINDINGS_APPROVE_SCOPE: _W}
                ),
                approve_only_ws2=await _plant(conn, tenant, ws2, {BINDINGS_APPROVE_SCOPE: _W}),
                reads_ws1_proposes_ws2=await _plant(
                    conn, tenant, ws2, {FIXTURE_READ: "tenant", BINDINGS_PROPOSE_SCOPE: _W}
                ),
                ws2_proposer=await _plant(
                    conn, tenant, ws2, {FIXTURE_READ: _W, BINDINGS_PROPOSE_SCOPE: _W}
                ),
                no_use=await _plant(
                    conn, tenant, ws1, {FIXTURE_READ: _W, BINDINGS_PROPOSE_SCOPE: _W}
                ),
                read_only=await _plant(conn, tenant, ws1, {FIXTURE_READ: _W}),
                ws2_alone=await _plant(
                    conn,
                    tenant,
                    ws2,
                    {
                        **_AUTHOR,
                        BINDINGS_PROPOSE_SCOPE: _W,
                        BINDINGS_APPROVE_SCOPE: _W,
                    },
                ),
                suspended=suspended,
                connection=await _connection_row(conn, tenant.tenant_id, ws1),
                other_connector=await _connection_row(conn, tenant.tenant_id, ws1, ("zalo", 1)),
                foreign_connection=await _connection_row(
                    conn, studio.other.tenant_id, studio.other.main
                ),
                outsider=await _plant(
                    conn,
                    studio.other,
                    studio.other.main,
                    {**_AUTHOR, BINDINGS_PROPOSE_SCOPE: _W, BINDINGS_APPROVE_SCOPE: "tenant"},
                ),
            )
        yield yield_world
        # The fixture kinds' artifacts go when the companies move to offboarding.
        async with migrator.begin() as conn:
            for tenant_id in (studio.tenant.tenant_id, studio.other.tenant_id):
                await conn.execute(
                    sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
                    {"t": tenant_id},
                )
                for table in ("run_manifest_keys", "config_versions"):
                    await conn.execute(
                        sa.text(f"DELETE FROM platform.{table} WHERE tenant_id = :t"),
                        {"t": tenant_id},
                    )


@dataclass
class Doors:
    artifacts: ArtifactService
    versions: ConfigVersionService
    guard: ConfigVersionDecisions
    flow: ApproveAndResumeService
    settle: ConfigSettlement
    status: BindingStatus
    reader: BindingsReader
    dependents: BindingConnectionDependents
    runs: RunRequestService
    run_bindings: SqlRunBindings
    types: BindingTypes


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def doors(sessions: async_sessionmaker[AsyncSession], world: World) -> Doors:
    ids, clock = Uuid7Generator(), SystemClock()
    registry = ArtifactKindRegistry(FIXTURE_KINDS)
    store = SqlArtifactStore(sessions, ids)
    usability = ConnectionUsability(
        store=SqlConnectionStore(sessions), catalog=NoConnectorCatalog()
    )
    types = platform_binding_types(usability)
    kinds = ConfigKindRegistry([BindingSets(store, registry, types, usability)])
    config_store = SqlConfigVersionStore(sessions)
    guard = ConfigVersionDecisions(kinds, config_store)
    flow = ApproveAndResumeService(
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        # A Binding set's request has no run: neither is asked.
        runner=cast(Any, None),
        run_store=cast(Any, None),
        clock=clock,
        id_generator=ids,
        run_control=OpenRunControl(),
        strict_approval_prefixes=frozenset({CONFIG_PREFIX}),
        decision_guards={CONFIG_VERSION: guard},
    )
    return Doors(
        artifacts=ArtifactService(store, registry, clock, ids),
        versions=ConfigVersionService(kinds, config_store, clock, ids),
        guard=guard,
        flow=flow,
        settle=ConfigSettlement(config_store, clock, ids),
        status=BindingStatus(store, types),
        reader=BindingsReader(store, registry),
        dependents=BindingConnectionDependents(store, registry),
        runs=RunRequestService(
            store,
            registry,
            RunManifestBuilder(registry, REF, shipped_models()),
            {
                ("fixture_gateless", "manual"): FIXTURE_RUN,
                ("fixture_gateless", "test"): FIXTURE_RUN,
            },
            RunLaneRegistry({}),
            clock,
            ids,
            bindings=BindingPins(types, usability),
        ),
        run_bindings=SqlRunBindings(sessions),
        types=types,
    )


# ---- helpers ------------------------------------------------------------------


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(sa.text(statement), values)).all())


async def live_root(
    doors: Doors,
    migrator: AsyncEngine,
    who: Person,
    *bindings: Any,
    uses: tuple[uuid.UUID, ...] = (),
) -> uuid.UUID:
    artifact_id, _ = await published(doors.artifacts, migrator, who, _doc(*bindings, uses=uses))
    return artifact_id


def decider(who: Person, workspace: uuid.UUID | None = None) -> AccessContext:
    return AccessContext(
        tenant_id=who.tenant_id,
        workspace_id=workspace or who.workspace_id,
        principal_id=who.id,
        roles=frozenset(),
        scopes=frozenset({"approvals.decide", BINDINGS_APPROVE_SCOPE}),
        plan_id="professional",
    )


async def propose(
    doors: Doors, who: Person, artifact_id: uuid.UUID, values: dict[str, Any]
) -> ConfigVersionRow:
    return await doors.versions.propose(
        who.context(), BINDING_SET, str(artifact_id), {"values": values}
    )


async def decide(doors: Doors, row: ConfigVersionRow, who: Person, *, approve: bool = True) -> None:
    await doors.flow.decide(
        approval_id=row.approval_id,
        approve=approve,
        comment="đã xem",
        context=decider(who, row.workspace_id),
        authorization=ScopeAuthorizationService(),
    )


async def settle(doors: Doors, row: ConfigVersionRow) -> str:
    return await doors.settle.settle(WorkScope(row.tenant_id, row.workspace_id), row.approval_id)


async def approved(
    doors: Doors, world: World, artifact_id: uuid.UUID, values: dict[str, Any]
) -> ConfigVersionRow:
    row = await propose(doors, world.proposer, artifact_id, values)
    await decide(doors, row, world.approver)
    assert await settle(doors, row) == "approved"
    return row


async def status_of(migrator: AsyncEngine, config_version_id: uuid.UUID) -> str:
    found = (
        await rows(
            migrator,
            "SELECT status FROM platform.config_versions WHERE id = :i",
            i=config_version_id,
        )
    )[0]
    return str(found.status)


async def request_status(migrator: AsyncEngine, approval_id: uuid.UUID) -> str:
    found = (
        await rows(
            migrator, "SELECT status FROM platform.approval_requests WHERE id = :i", i=approval_id
        )
    )[0]
    return str(found.status)


async def config_rows(migrator: AsyncEngine, artifact_id: uuid.UUID) -> int:
    found = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.config_versions WHERE key = :k",
        k=str(artifact_id),
    )
    return int(found[0].n)


async def audits(migrator: AsyncEngine, action: str, resource: uuid.UUID) -> list[Any]:
    return await rows(
        migrator,
        "SELECT actor_id, details FROM platform.audit_events"
        " WHERE action = :a AND resource_id = :r",
        a=action,
        r=str(resource),
    )


def refused_by(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None) or getattr(cause, "sqlstate", None)


def problems(caught: pytest.ExceptionInfo[DocumentInvalidError]) -> list[tuple[str, str]]:
    return [(p.pointer, p.code) for p in caught.value.problems]


def reason(caught: pytest.ExceptionInfo[Any]) -> object:
    return caught.value.details.get("reason_code")


# ---- R8.1-R8.7: the proposal ------------------------------------------------------


async def test_r8_1_a_proposal_writes_its_row_its_request_and_its_audit(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _connection("email_sender"))
    row = await propose(doors, world.proposer, artifact_id, {"email_sender": str(world.connection)})

    assert (row.status, row.version_no, row.base_version, row.workspace_id) == (
        "proposed",
        1,
        1,
        world.studio.ws1,
    )
    request = (
        await rows(
            migrator,
            "SELECT approval_type, required_scope, workspace_id, status, payload"
            " FROM platform.approval_requests WHERE id = :i",
            i=row.approval_id,
        )
    )[0]
    assert (request.approval_type, request.required_scope, request.workspace_id) == (
        CONFIG_VERSION,
        BINDINGS_APPROVE_SCOPE,
        world.studio.ws1,
    )
    # Identifiers only: no value rides in the request.
    assert set(request.payload) == {
        "config_version_id",
        "kind",
        "key",
        "version_no",
        "document_hash",
    }
    assert str(world.connection) not in str(request.payload)
    [audit] = await audits(migrator, "config.version.proposed", row.id)
    assert audit.actor_id == world.proposer.id


async def test_r8_2_r8_17_who_may_propose_where_the_artifact_lives(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """403 without the propose key at the owning workspace; 404 for a caller
    who cannot read it there (TC25, TC34); nothing is written."""
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    with pytest.raises(PermissionDeniedError):
        await propose(doors, world.read_only, artifact_id, {"score": 5})
    with pytest.raises(PermissionDeniedError):
        # Reads ws1 (tenant depth), proposes only in ws2.
        await propose(doors, world.reads_ws1_proposes_ws2, artifact_id, {"score": 5})
    with pytest.raises(NotFoundError):
        await propose(doors, world.ws2_proposer, artifact_id, {"score": 5})
    assert await config_rows(migrator, artifact_id) == 0


async def test_r8_3_another_companys_artifact_or_connection_is_not_found(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _connection("email_sender"))
    with pytest.raises(NotFoundError):
        await propose(doors, world.outsider, artifact_id, {"email_sender": str(world.connection)})
    with pytest.raises(NotFoundError):
        await propose(
            doors, world.proposer, artifact_id, {"email_sender": str(world.foreign_connection)}
        )
    assert await config_rows(migrator, artifact_id) == 0


async def test_r8_4_a_value_its_declaration_refuses(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(
        doors,
        migrator,
        world.proposer,
        _connection("email_sender"),
        _variable("score"),
        _principal("fallback"),
    )
    with pytest.raises(DocumentInvalidError) as caught:
        await propose(
            doors,
            world.proposer,
            artifact_id,
            {
                "email_sender": str(world.other_connector),
                "score": "nhiều",
                "fallback": str(world.suspended),
                "unknown": 1,
            },
        )
    assert sorted(problems(caught)) == [
        ("/values/email_sender", "binding_connector_mismatch"),
        ("/values/fallback", "principal_inactive"),
        ("/values/score", "binding_value_invalid"),
        ("/values/unknown", "binding_unknown"),
    ]
    # Usable by its proposer: without `connections.use` at the workspace, 422.
    with pytest.raises(DocumentInvalidError) as caught:
        await propose(doors, world.no_use, artifact_id, {"email_sender": str(world.connection)})
    assert problems(caught) == [("/values/email_sender", "connection_unusable")]
    # A principal of another company is not found.
    with pytest.raises(NotFoundError):
        await propose(doors, world.proposer, artifact_id, {"fallback": str(world.outsider.id)})
    assert await config_rows(migrator, artifact_id) == 0


async def test_r8_4_a_connection_with_scopes_is_refused_at_the_seal(
    doors: Doors, world: World
) -> None:
    declared = {**_connection("zalo_oa"), "required_scopes": ["oa.message"]}
    artifact_id, _, row_version = await draft_of(
        doors.artifacts, world.proposer, _doc(declared), kind="fixture_gateless"
    )
    with pytest.raises(DocumentInvalidError) as caught:
        await sealed(doors.artifacts, world.proposer, artifact_id, row_version)
    assert ("/bindings/0/required_scopes", "binding_scopes_unsupported") in problems(caught)


def test_r8_4_a_binding_kind_without_a_proposal_check_fails_at_startup() -> None:
    usability = cast(Any, None)
    checks = dict(platform_binding_types(usability)._checks)
    del checks[BindingKind.PRINCIPAL]
    with pytest.raises(ValueError, match="principal"):
        BindingTypes(checks)


async def test_r8_5_no_one_else_could_approve(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """In ws2 only the proposer holds the approve key with a read; the
    holder of the approve key who cannot read the artifact is no checker
    (gate 4/11/2026 (r))."""
    artifact_id = await live_root(doors, migrator, world.ws2_alone, _variable("score"))
    with pytest.raises(ConflictError) as caught:
        await propose(doors, world.ws2_alone, artifact_id, {"score": 5})
    assert reason(caught) == "no_checker_available"
    assert await config_rows(migrator, artifact_id) == 0


async def test_r8_6_one_open_proposal_per_key(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    await propose(doors, world.proposer, artifact_id, {"score": 1})
    with pytest.raises(ConflictError) as caught:
        await propose(doors, world.proposer, artifact_id, {"score": 2})
    assert reason(caught) == "proposal_open"
    assert await config_rows(migrator, artifact_id) == 1


async def _raw_proposal(tx: SqlConfigVersionTx, world: World, artifact_id: uuid.UUID) -> None:
    approval_id = uuid.uuid4()
    await tx.open_approval(
        ApprovalRequest(
            id=approval_id,
            tenant_id=TenantId(world.tenant),
            workspace_id=WorkspaceId(world.studio.ws1),
            approval_type=CONFIG_VERSION,
            requested_by=UserId(world.proposer.id),
            reason="thử",
            required_scope=BINDINGS_APPROVE_SCOPE,
        )
    )
    await tx.insert(
        NewConfigVersion(
            id=uuid.uuid4(),
            workspace_id=world.studio.ws1,
            kind=BINDING_SET,
            key=str(artifact_id),
            version_no=1,
            base_version=1,
            base_bindings_hash="sha256:" + "0" * 64,
            base_approved_id=None,
            document={"values": {}},
            document_hash="sha256:" + "1" * 64,
            approval_id=approval_id,
            proposed_by=world.proposer.id,
        )
    )


async def test_r8_6_two_proposals_at_once_one_is_open_the_other_409(
    sessions: async_sessionmaker[AsyncSession], world: World, migrator: AsyncEngine
) -> None:
    """Two transactions: the second waits on the first's index entry
    (`pg_locks`), then meets the constraint, read back as `proposal_open`."""
    artifact_id = uuid.uuid4()
    store = SqlConfigVersionStore(sessions)
    first = store.transaction(
        world.tenant, workspace_id=world.studio.ws1, principal_id=world.proposer.id
    )
    tx1 = await first.__aenter__()
    await _raw_proposal(tx1, world, artifact_id)

    async def second() -> None:
        async with store.transaction(
            world.tenant, workspace_id=world.studio.ws1, principal_id=world.proposer.id
        ) as tx2:
            await _raw_proposal(tx2, world, artifact_id)

    racing = asyncio.create_task(second())
    for _ in range(200):
        waiting = await rows(
            migrator,
            "SELECT count(*) AS n FROM pg_locks WHERE NOT granted AND locktype = 'transactionid'",
        )
        if waiting[0].n:
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("the second proposal never waited")
    await first.__aexit__(None, None, None)
    with pytest.raises(ConflictError) as caught:
        await racing
    assert reason(caught) == "proposal_open"
    assert await config_rows(migrator, artifact_id) == 1


async def test_r8_7_an_unregistered_kind_is_refused_and_the_check_holds(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    with pytest.raises(DomainError) as caught:
        await doors.versions.propose(world.proposer.context(), "prompt", str(artifact_id), {})
    assert reason(caught) == "config_kind_unknown"
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    with pytest.raises(DBAPIError, match="ck_config_versions_kind"):
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.config_versions (id, tenant_id, workspace_id, kind, key,"
                    " action, version_no, base_version, base_bindings_hash, document,"
                    " document_hash, status, approval_id, proposed_by)"
                    " SELECT gen_random_uuid(), tenant_id, workspace_id, 'prompt', key, action,"
                    " 99, base_version, base_bindings_hash, document, document_hash, 'proposed',"
                    " approval_id, proposed_by FROM platform.config_versions WHERE id = :i"
                ),
                {"i": row.id},
            )


async def test_no_proposal_before_a_version_is_sealed(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """R7.2 (TC22): before the first submit nothing is sealed to check a value
    against (gate 4/11/2026 (a))."""
    artifact_id, _, _ = await draft_of(
        doors.artifacts, world.proposer, _doc(_connection("email_sender")), kind="fixture_gateless"
    )
    with pytest.raises(ConflictError) as caught:
        await propose(doors, world.proposer, artifact_id, {"email_sender": str(world.connection)})
    assert reason(caught) == "no_sealed_version"


# ---- R8.8-R8.12, R8.15: deciding and settling ----------------------------------------


async def test_r8_8_the_proposer_never_decides_their_own(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    with pytest.raises(ConflictError) as caught:
        await decide(doors, row, world.proposer)
    assert reason(caught) == "second_person_required"
    assert await request_status(migrator, row.approval_id) == "pending"
    with pytest.raises(DBAPIError, match="ck_config_versions_checker_not_maker"):
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.config_versions SET status = 'rejected',"
                    " decided_by = proposed_by, decided_at = now() WHERE id = :i"
                ),
                {"i": row.id},
            )


async def test_r8_10_r8_15_approved_settled_once_in_the_deciders_name(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    first = await approved(doors, world, artifact_id, {"score": 3})
    second = await propose(doors, world.proposer, artifact_id, {"score": 4})
    await decide(doors, second, world.approver)
    assert await settle(doors, second) == "approved"

    assert await status_of(migrator, first.id) == "superseded"
    assert await status_of(migrator, second.id) == "approved"
    [audit] = await audits(migrator, "config.version.approved", second.id)
    assert audit.actor_id == world.approver.id
    assert audit.details["lane"] == "outbox"
    assert audit.details["superseded_id"] == str(first.id)
    # R8.15: a redelivery changes nothing and audits nothing.
    assert await settle(doors, second) == "unchanged"
    assert len(await audits(migrator, "config.version.approved", second.id)) == 1


async def test_r8_11_a_rejection_is_settled_in_the_deciders_name(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    await decide(doors, row, world.approver, approve=False)
    assert await settle(doors, row) == "rejected"
    assert await status_of(migrator, row.id) == "rejected"
    [audit] = await audits(migrator, "config.version.rejected", row.id)
    assert (audit.actor_id, audit.details["lane"]) == (world.approver.id, "outbox")


async def test_r8_11_a_key_approved_otherwise_meanwhile_settles_as_a_conflict(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    first = await approved(doors, world, artifact_id, {"score": 3})
    second = await propose(doors, world.proposer, artifact_id, {"score": 4})
    await decide(doors, second, world.approver)
    # What was approved when it was proposed is no longer in force.
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.config_versions SET status = 'superseded',"
                " superseded_at = now() WHERE id = :i"
            ),
            {"i": first.id},
        )
    assert await settle(doors, second) == "settlement_conflict"
    assert await status_of(migrator, second.id) == "rejected"
    [audit] = await audits(migrator, "config.version.rejected", second.id)
    assert audit.details["reason"] == "settlement_conflict"


async def test_r8_12_the_database_holds_the_moves(
    doors: Doors, world: World, migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})

    async def as_app(statement: str) -> None:
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(world.tenant)}
            )
            await conn.execute(sa.text(statement), {"i": row.id, "u": world.approver.id})

    with pytest.raises(DBAPIError) as caught:
        await as_app(
            "UPDATE platform.config_versions SET status = 'approved', decided_by = :u,"
            " decided_at = now() WHERE id = :i"
        )
    assert refused_by(caught.value) == "ck_config_versions_approved_by_approval"
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_app("UPDATE platform.config_versions SET document = '{}' WHERE id = :i")
    await decide(doors, row, world.approver)
    await settle(doors, row)
    with pytest.raises(DBAPIError) as moved:
        await as_app("UPDATE platform.config_versions SET status = 'proposed' WHERE id = :i")
    assert refused_by(moved.value) == "ck_config_versions_status_transition"


# ---- R8.9, R8.11, R8.17: the decision guard ---------------------------------------


async def seal_again(
    doors: Doors,
    world: World,
    migrator: AsyncEngine,
    artifact_id: uuid.UUID,
    document: dict[str, Any],
    *,
    stage: str = "awaiting_approval",
) -> uuid.UUID:
    """A new draft of the artifact, saved, sealed and moved to `stage`."""
    context = world.proposer.context()
    row = await doors.artifacts.get(context, artifact_id)
    draft = await doors.artifacts.create_draft(
        context, artifact_id, ExpectedVersion(row.row_version)
    )
    saved = await doors.artifacts.save_draft(
        context, artifact_id, ExpectedVersion(draft.row_version), document
    )
    result = await sealed(doors.artifacts, world.proposer, artifact_id, saved.version.row_version)
    await move_for_test(migrator, result.version_id, stage)
    return result.version_id


async def fresh_connection(migrator: AsyncEngine, world: World) -> uuid.UUID:
    async with migrator.begin() as conn:
        return await _connection_row(conn, world.tenant, world.studio.ws1)


async def stale(doors: Doors, row: ConfigVersionRow, who: Person) -> object:
    with pytest.raises(ConflictError) as caught:
        await decide(doors, row, who)
    return caught.value.details.get("reason_code")


async def supersede(migrator: AsyncEngine, config_version_id: uuid.UUID) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.config_versions SET status = 'superseded',"
                " superseded_at = now() WHERE id = :i"
            ),
            {"i": config_version_id},
        )


async def test_r8_9_a_new_seal_keeping_the_bindings_keeps_the_proposal_current(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    await seal_again(doors, world, migrator, artifact_id, _doc(_variable("score"), title="Mới"))
    await decide(doors, row, world.approver)
    assert await settle(doors, row) == "approved"


async def test_r8_9_a_new_seal_changing_the_bindings_makes_the_decision_stale(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    await seal_again(
        doors, world, migrator, artifact_id, _doc(_variable("score"), _variable("cap"))
    )
    assert await stale(doors, row, world.approver) == "decision_stale"
    assert await request_status(migrator, row.approval_id) == "pending"
    assert await status_of(migrator, row.id) == "proposed"


async def test_r8_9_a_base_taken_back_to_its_draft_makes_the_decision_stale(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """Gate 4/11/2026 (p): v2 has the bindings of v1, so only its return to
    the draft makes the proposal stale."""
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    v2 = await seal_again(doors, world, migrator, artifact_id, _doc(_variable("score")))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    assert row.base_version == 2
    await move_for_test(migrator, v2, "draft")
    assert await stale(doors, row, world.approver) == "decision_stale"


async def test_r8_9_an_unusable_connection_stops_an_approval_not_a_rejection(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    connection = await fresh_connection(migrator, world)
    artifact_id = await live_root(doors, migrator, world.proposer, _connection("email_sender"))
    row = await propose(doors, world.proposer, artifact_id, {"email_sender": str(connection)})
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.connections SET status = 'disabled' WHERE id = :c"),
            {"c": connection},
        )
    assert await stale(doors, row, world.approver) == "decision_stale"
    assert await request_status(migrator, row.approval_id) == "pending"
    assert await status_of(migrator, row.id) == "proposed"
    await decide(doors, row, world.approver, approve=False)
    assert await request_status(migrator, row.approval_id) == "rejected"


async def test_r8_11_the_approved_version_changed_since_the_proposal_is_stale(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    first = await approved(doors, world, artifact_id, {"score": 3})
    second = await propose(doors, world.proposer, artifact_id, {"score": 4})
    await supersede(migrator, first.id)
    assert await stale(doors, second, world.approver) == "decision_stale"


async def test_r8_17_a_decider_who_cannot_read_the_artifact_is_not_shown_it(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    request = ApprovalRequest(
        id=row.approval_id,
        tenant_id=TenantId(world.tenant),
        workspace_id=WorkspaceId(row.workspace_id),
        approval_type=CONFIG_VERSION,
        requested_by=UserId(world.proposer.id),
        reason="",
    )
    with pytest.raises(NotFoundError):
        await doors.guard.check(
            request,
            ProposedDecision(approve=True),
            decider(world.approve_only_ws2, world.studio.ws1),
        )
    with pytest.raises(NotFoundError):
        await decide(doors, row, world.approve_only_ws2)
    assert await request_status(migrator, row.approval_id) == "pending"


# ---- R8.13, R8.14, R8.18, R8.19: withdrawing -------------------------------------------


async def test_r8_13_r8_14_only_the_proposer_withdraws(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    with pytest.raises(PermissionDeniedError):
        await doors.versions.withdraw(world.approver.context(), BINDING_SET, row.key, row.id)
    assert await status_of(migrator, row.id) == "proposed"
    assert await request_status(migrator, row.approval_id) == "pending"
    with pytest.raises(NotFoundError):
        await doors.versions.withdraw(world.outsider.context(), BINDING_SET, row.key, row.id)

    withdrawn = await doors.versions.withdraw(
        world.proposer.context(), BINDING_SET, row.key, row.id
    )
    assert withdrawn.status == "withdrawn"
    assert await request_status(migrator, row.approval_id) == "cancelled"
    assert len(await audits(migrator, "config.version.withdrawn", row.id)) == 1


async def test_r8_18_r8_19_decided_is_not_withdrawn_and_withdrawn_is_not_settled(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    row = await propose(doors, world.proposer, artifact_id, {"score": 3})
    await decide(doors, row, world.approver)
    with pytest.raises(ConflictError) as caught:
        await doors.versions.withdraw(world.proposer.context(), BINDING_SET, row.key, row.id)
    assert reason(caught) == "proposal_decided"
    assert await status_of(migrator, row.id) == "proposed"
    assert await settle(doors, row) == "approved"

    # A withdrawn row meets a decision anyway (written past the flow): no change.
    other = await live_root(doors, migrator, world.proposer, _variable("score"))
    gone = await propose(doors, world.proposer, other, {"score": 3})
    await doors.versions.withdraw(world.proposer.context(), BINDING_SET, gone.key, gone.id)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_decisions (id, request_id, tenant_id,"
                " workspace_id, decided_by, outcome, comment, decided_at)"
                " VALUES (gen_random_uuid(), :r, :t, :w, :u, 'approved', 'muộn', now())"
            ),
            {
                "r": gone.approval_id,
                "t": world.tenant,
                "w": gone.workspace_id,
                "u": world.approver.id,
            },
        )
    assert await settle(doors, gone) == "unchanged"
    assert await status_of(migrator, gone.id) == "withdrawn"
    assert await audits(migrator, "config.version.approved", gone.id) == []


# ---- the keys: R8.16, R2.18, R3.8 ---------------------------------------------------


_RAW_VERSION = (
    "INSERT INTO platform.config_versions (id, tenant_id, workspace_id, kind,"
    " key, action, version_no, base_version, base_bindings_hash, document,"
    " document_hash, status, approval_id, proposed_by)"
    " VALUES (gen_random_uuid(), :t, :w, 'binding_set', :k, 'set', 9, 1,"
    " :h, '{}', :h, 'proposed', :a, :u)"
)


async def test_r8_16_r2_18_no_key_points_into_another_company_or_workspace(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """As the migrator, past RLS: only the composite keys stop the rows."""
    artifact_id = await live_root(doors, migrator, world.proposer, _variable("score"))
    mine = await propose(doors, world.proposer, artifact_id, {"score": 3})
    theirs_request = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, reason)"
                " VALUES (:i, :t, :w, 'config.version', :u, '')"
            ),
            {
                "i": theirs_request,
                "t": world.outsider.tenant_id,
                "w": world.outsider.workspace_id,
                "u": world.outsider.id,
            },
        )
    for approval, workspace in (
        (theirs_request, world.studio.ws1),
        (mine.approval_id, world.studio.ws2),
    ):
        with pytest.raises(DBAPIError, match="fk_config_versions_approval_id_approval_requests"):
            async with migrator.begin() as conn:
                await conn.execute(
                    sa.text(_RAW_VERSION),
                    {
                        "t": world.tenant,
                        "w": workspace,
                        "k": str(uuid.uuid4()),
                        "h": "sha256:" + "2" * 64,
                        "a": approval,
                        "u": world.proposer.id,
                    },
                )
    # R2.18: a key row of the other company's manifest naming this one's version.
    manifest = "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.run_manifests (tenant_id, hash, body) VALUES (:t, :h, '{}')"
            ),
            {"t": world.outsider.tenant_id, "h": manifest},
        )
    with pytest.raises(DBAPIError, match="fk_run_manifest_keys_config_version_id_config_versions"):
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.run_manifest_keys (id, tenant_id, manifest_hash,"
                    " config_version_id) VALUES (gen_random_uuid(), :t, :h, :c)"
                ),
                {"t": world.outsider.tenant_id, "h": manifest, "c": mine.id},
            )


async def test_r3_8_dw_app_deletes_a_config_version_only_while_offboarding(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A company of its own, which this test moves to `offboarding` for good."""
    async with migrator.begin() as conn:
        leaving = await plant_tenant(conn)
        who = await plant_person(conn, leaving.tenant_id)
        approval_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, reason)"
                " VALUES (:i, :t, :w, 'config.version', :u, '')"
            ),
            {"i": approval_id, "t": leaving.tenant_id, "w": leaving.main, "u": who},
        )
        await conn.execute(
            sa.text(_RAW_VERSION),
            {
                "t": leaving.tenant_id,
                "w": leaving.main,
                "k": str(uuid.uuid4()),
                "h": "sha256:" + "3" * 64,
                "a": approval_id,
                "u": who,
            },
        )

    async def delete() -> None:
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(leaving.tenant_id)},
            )
            await conn.execute(
                sa.text("DELETE FROM platform.config_versions WHERE tenant_id = :t"),
                {"t": leaving.tenant_id},
            )

    async def count() -> int:
        found = await rows(
            migrator,
            "SELECT count(*) AS n FROM platform.config_versions WHERE tenant_id = :t",
            t=leaving.tenant_id,
        )
        return int(found[0].n)

    with pytest.raises(DBAPIError) as caught:
        await delete()
    assert refused_by(caught.value) == "ck_delete_outside_offboarding"
    assert await count() == 1
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": leaving.tenant_id},
        )
    await delete()
    assert await count() == 0


# ---- R3.7: who uses a connection -------------------------------------------------------


async def test_r3_7_a_connection_is_used_while_an_approved_set_binds_it(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    connection = await fresh_connection(migrator, world)
    optional = _connection("email_sender", required=False)
    artifact_id = await live_root(doors, migrator, world.proposer, optional)
    await approved(doors, world, artifact_id, {"email_sender": str(connection)})
    found = await doors.dependents.dependents(world.proposer.context(), connection)
    assert found.total == 1
    assert [ref.id for ref in found.visible] == [artifact_id]
    # Counted, not named, for someone who cannot read the artifact.
    hidden = await doors.dependents.dependents(world.approve_only_ws2.context(), connection)
    assert (hidden.total, hidden.visible) == (1, ())

    await approved(doors, world, artifact_id, {})
    assert (await doors.dependents.dependents(world.proposer.context(), connection)).total == 0

    again = await live_root(doors, migrator, world.proposer, optional)
    await approved(doors, world, again, {"email_sender": str(connection)})
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE studio.artifacts SET deleted_at = now() WHERE id = :a"), {"a": again}
        )
    assert (await doors.dependents.dependents(world.proposer.context(), connection)).total == 0


# ---- R7.1, R7.6 at the seal ------------------------------------------------------------


async def test_r7_1_a_document_naming_a_connection_is_not_sealed(
    doors: Doors, world: World
) -> None:
    document = {**_doc(_connection("email_sender")), "note": {"to": [str(world.connection)]}}
    artifact_id, _, row_version = await draft_of(
        doors.artifacts, world.proposer, document, kind="fixture_gateless"
    )
    with pytest.raises(DocumentInvalidError) as caught:
        await sealed(doors.artifacts, world.proposer, artifact_id, row_version)
    assert problems(caught) == [("/note/to/0", "connection_id_in_document")]
    # Another company's connection id is only a string here.
    plain = {**_doc(), "note": str(world.foreign_connection)}
    artifact_id, _, row_version = await draft_of(
        doors.artifacts, world.proposer, plain, kind="fixture_gateless"
    )
    await sealed(doors.artifacts, world.proposer, artifact_id, row_version)


async def test_r7_6_one_set_per_root_covers_its_closure_and_the_live_version(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    agent = await live_root(doors, migrator, world.proposer, _connection("zalo_oa"))
    root = await live_root(
        doors, migrator, world.proposer, _connection("email_sender"), uses=(agent,)
    )
    both = {"email_sender": str(world.connection), "zalo_oa": str(world.connection)}
    row = await propose(doors, world.proposer, root, both)
    await doors.versions.withdraw(world.proposer.context(), BINDING_SET, row.key, row.id)
    # A name declared with two kinds in one closure is refused at the seal.
    clash = _doc(_variable("zalo_oa"), uses=(agent,))
    artifact_id, _, row_version = await draft_of(
        doors.artifacts, world.proposer, clash, kind="fixture_gateless"
    )
    with pytest.raises(DocumentInvalidError) as caught:
        await sealed(doors.artifacts, world.proposer, artifact_id, row_version)
    assert ("/bindings/0", "binding_conflict") in problems(caught)
    # o: the candidate drops the agent, the live version still needs `zalo_oa`.
    await seal_again(doors, world, migrator, root, _doc(_connection("email_sender")))
    await propose(doors, world.proposer, root, both)


# ---- R7.2: the publish check -----------------------------------------------------------


async def test_r7_2_publish_needs_every_required_binding_approved(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    document = _doc(
        _connection("zalo_oa"),
        _variable("score", default="10"),
        _variable("cap", required=False),
    )
    artifact_id, v1 = await published(doors.artifacts, migrator, world.proposer, document)
    verdict = await doors.status.satisfied(world.tenant, v1.version_id)
    assert verdict.unset == ("zalo_oa",)
    await approved(doors, world, artifact_id, {"zalo_oa": str(world.connection)})
    assert (await doors.status.satisfied(world.tenant, v1.version_id)).satisfied


async def test_r7_2_a_first_version_is_proposed_after_its_seal_then_published(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """Gate 4/11/2026 (a): no deadlock: the submit seals, the set is proposed
    against what it sealed, approved, and the publish check passes."""
    artifact_id, _, row_version = await draft_of(
        doors.artifacts, world.proposer, _doc(_connection("email_sender")), kind="fixture_gateless"
    )
    result = await sealed(doors.artifacts, world.proposer, artifact_id, row_version)
    await move_for_test(migrator, result.version_id, "awaiting_approval")
    verdict = await doors.status.satisfied(world.tenant, result.version_id)
    assert verdict.unset == ("email_sender",)
    await approved(doors, world, artifact_id, {"email_sender": str(world.connection)})
    assert (await doors.status.satisfied(world.tenant, result.version_id)).satisfied


# ---- R7.3-R7.6: admission and the run's pins -------------------------------------------


def run_of(who: Person, version_id: uuid.UUID, trigger: str = "manual") -> RunRequest:
    return RunRequest(
        requester=PersonRequester(who.context()),
        version_id=version_id,
        trigger_kind=trigger,
        source_key=uuid.uuid4().hex,
    )


async def manifests_of(migrator: AsyncEngine, tenant_id: uuid.UUID) -> int:
    found = await rows(
        migrator,
        "SELECT count(*) AS n FROM platform.run_manifests WHERE tenant_id = :t",
        t=tenant_id,
    )
    return int(found[0].n)


_KEY_ROWS = (
    # Both targets.
    "INSERT INTO platform.run_manifest_keys (id, tenant_id, manifest_hash,"
    " artifact_version_id, config_version_id) SELECT gen_random_uuid(), tenant_id,"
    " manifest_hash, :v, config_version_id FROM platform.run_manifest_keys"
    " WHERE config_version_id = :c",
    # Neither.
    "INSERT INTO platform.run_manifest_keys (id, tenant_id, manifest_hash)"
    " SELECT gen_random_uuid(), tenant_id, manifest_hash FROM platform.run_manifest_keys"
    " WHERE config_version_id = :c",
    # The same set twice under one manifest.
    "INSERT INTO platform.run_manifest_keys (id, tenant_id, manifest_hash,"
    " config_version_id) SELECT gen_random_uuid(), tenant_id, manifest_hash,"
    " config_version_id FROM platform.run_manifest_keys WHERE config_version_id = :c",
)


async def test_r7_4_a_run_pins_the_set_its_connections_and_hashes_never_a_secret(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    document = _doc(_connection("email_sender"), _variable("score", default="10"))
    artifact_id, v1 = await published(doors.artifacts, migrator, world.proposer, document)
    row = await approved(doors, world, artifact_id, {"email_sender": str(world.connection)})
    run = await doors.runs.request(run_of(world.proposer, v1.version_id))
    body = (
        await rows(
            migrator,
            "SELECT m.body FROM platform.worker_runs r JOIN platform.run_manifests m"
            " ON m.tenant_id = r.tenant_id AND m.hash = r.run_manifest_hash WHERE r.id = :r",
            r=run.run_id,
        )
    )[0].body
    pins = body["bindings"]
    assert pins["config_version_id"] == str(row.id)
    assert pins["values"]["email_sender"] == {
        "kind": "connection",
        "connection_id": str(world.connection),
    }
    assert set(pins["values"]["score"]) == {"kind", "content_hash"}
    assert "secret_version" not in str(body)
    keys = await rows(
        migrator,
        "SELECT artifact_version_id, config_version_id FROM platform.run_manifest_keys"
        " WHERE config_version_id = :c",
        c=row.id,
    )
    assert [(k.artifact_version_id, k.config_version_id) for k in keys] == [(None, row.id)]
    with pytest.raises(ValidationError):
        RunManifest.model_validate({**body, "bindings": {**pins, "secret_version": 3}})
    for statement in _KEY_ROWS:
        with pytest.raises(
            DBAPIError, match=r"ck_run_manifest_keys_one_target|uq_run_manifest_keys"
        ):
            async with migrator.begin() as conn:
                await conn.execute(sa.text(statement), {"c": row.id, "v": v1.version_id})


async def test_r7_6_admission_checks_the_set_against_the_runs_own_version(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    """TC33: the set approved against candidate v2, which dropped `zalo_oa`,
    lacks the value live v1 requires: v1's run is refused, nothing is pinned;
    a simulated draft lacking a required value is admitted (gate (s))."""
    document = _doc(_connection("email_sender"), _connection("zalo_oa"))
    artifact_id, v1 = await published(doors.artifacts, migrator, world.proposer, document)
    await seal_again(doors, world, migrator, artifact_id, _doc(_connection("email_sender")))
    await approved(doors, world, artifact_id, {"email_sender": str(world.connection)})
    before = await manifests_of(migrator, world.tenant)
    with pytest.raises(ConflictError) as caught:
        await doors.runs.request(run_of(world.proposer, v1.version_id))
    assert caught.value.details == {"reason_code": "binding_unset", "bindings": ["zalo_oa"]}
    assert await manifests_of(migrator, world.tenant) == before

    _, draft_id, _ = await draft_of(
        doors.artifacts, world.proposer, _doc(_connection("email_sender")), kind="fixture_gateless"
    )
    assert (await doors.runs.request(run_of(world.proposer, draft_id, "test"))).created


async def test_r7_3_a_bound_connection_no_longer_usable_refuses_the_run(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    connection = await fresh_connection(migrator, world)
    artifact_id, v1 = await published(
        doors.artifacts, migrator, world.proposer, _doc(_connection("email_sender"))
    )
    await approved(doors, world, artifact_id, {"email_sender": str(connection)})
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.connections SET status = 'revoked' WHERE id = :c"),
            {"c": connection},
        )
    before = await manifests_of(migrator, world.tenant)
    with pytest.raises(ConflictError) as caught:
        await doors.runs.request(run_of(world.proposer, v1.version_id))
    assert caught.value.details == {
        "reason_code": "binding_degraded",
        "bindings": ["email_sender"],
    }
    assert await manifests_of(migrator, world.tenant) == before


async def test_r7_5_a_run_reads_its_pinned_connection_whatever_is_approved_later(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    second = await fresh_connection(migrator, world)
    artifact_id, v1 = await published(
        doors.artifacts, migrator, world.proposer, _doc(_connection("email_sender"))
    )
    await approved(doors, world, artifact_id, {"email_sender": str(world.connection)})
    run = await doors.runs.request(run_of(world.proposer, v1.version_id))
    await approved(doors, world, artifact_id, {"email_sender": str(second)})

    bound = await doors.run_bindings.connection(world.tenant, run.run_id, "email_sender")
    assert bound is not None
    created = (
        await rows(
            migrator,
            "SELECT created_at, workspace_id FROM platform.worker_runs WHERE id = :r",
            r=run.run_id,
        )
    )[0]
    assert (bound.connection_id, bound.principal_id) == (world.connection, world.proposer.id)
    assert (bound.workspace_id, bound.run_requested_at) == (
        created.workspace_id,
        created.created_at,
    )
    other_tenant = world.outsider.tenant_id
    assert await doors.run_bindings.connection(other_tenant, run.run_id, "email_sender") is None
    assert await doors.run_bindings.connection(world.tenant, run.run_id, "zalo_oa") is None


# ---- the read ---------------------------------------------------------------------------


async def test_the_bindings_read_hides_what_the_caller_may_not_read(
    doors: Doors, world: World, migrator: AsyncEngine
) -> None:
    artifact_id = await live_root(
        doors,
        migrator,
        world.proposer,
        _connection("email_sender"),
        _variable("score", default="1"),
    )
    await approved(doors, world, artifact_id, {"email_sender": str(world.connection)})
    await propose(
        doors, world.proposer, artifact_id, {"email_sender": str(world.connection), "score": 5}
    )

    seen = await doors.reader.overview(world.proposer.context(), artifact_id)
    assert {i.decl.name: (i.state, i.has_proposed) for i in seen.items} == {
        "email_sender": ("set", True),
        "score": ("default", True),
    }
    assert world.connection in seen.readable_connections
    # Reads the artifact, not the connection: the id alone.
    hidden = await doors.reader.overview(world.approver.context(), artifact_id)
    assert hidden.readable_connections == {}
    for who in (world.outsider, world.ws2_proposer):
        with pytest.raises(NotFoundError):
            await doors.reader.overview(who.context(), artifact_id)


# ---- R3.6: offboarding ------------------------------------------------------------------


async def test_r3_6_offboarding_purges_the_config_versions_its_manifests_pin(
    doors: Doors,
    world: World,
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A company of its own with an approved Binding set a run's manifest pins,
    and its request: the lane purges them in the catalog's order, after the
    manifest's keys and before the requests; the other company keeps its own."""
    async with migrator.begin() as conn:
        leaving = await plant_tenant(conn)
        author = await _plant(
            conn,
            leaving,
            leaving.main,
            {**_AUTHOR, BINDINGS_PROPOSE_SCOPE: _W, CONNECTIONS_USE_SCOPE: _W},
        )
        checker = await _plant(
            conn, leaving, leaving.main, {FIXTURE_READ: _W, BINDINGS_APPROVE_SCOPE: _W}
        )
        connection = await _connection_row(conn, leaving.tenant_id, leaving.main)
    artifact_id, v1 = await published(
        doors.artifacts, migrator, author, _doc(_connection("email_sender"))
    )
    row = await doors.versions.propose(
        author.context(),
        BINDING_SET,
        str(artifact_id),
        {"values": {"email_sender": str(connection)}},
    )
    await decide(doors, row, checker)
    assert await settle(doors, row) == "approved"
    await doors.runs.request(run_of(author, v1.version_id))
    count = (
        "SELECT (SELECT count(*) FROM platform.config_versions WHERE tenant_id = :t) AS c,"
        " (SELECT count(*) FROM platform.run_manifest_keys WHERE tenant_id = :t"
        "  AND config_version_id IS NOT NULL) AS k"
    )
    assert tuple((await rows(migrator, count, t=leaving.tenant_id))[0]) == (1, 1)
    theirs = tuple((await rows(migrator, count, t=world.tenant))[0])
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": leaving.tenant_id},
        )
    lane = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    async with migrator.connect() as conn, AsyncSession(bind=conn) as session:
        order = await lane.purge_order(session)
    await lane.purge_rows(leaving.tenant_id)

    assert tuple((await rows(migrator, count, t=leaving.tenant_id))[0]) == (0, 0)
    assert tuple((await rows(migrator, count, t=world.tenant))[0]) == theirs
    at = {table: order.index(table) for table in order}
    assert at["platform.run_manifest_keys"] < at["platform.config_versions"]
    assert at["platform.config_versions"] < at["platform.approval_requests"]
