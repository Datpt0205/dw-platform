"""The connections' database rules and the one usable rule, against Postgres
(connections-and-vault 04: R1.15, R5.3-R5.6, R5.8, R5.9, R5.14-R5.17, R5.19,
R5.20; CV13-CV15, CV21, CV24, CV28).

Each layer is asked directly, never through the layer after it
(failure-modes #5): `connection_usable` here, not through egress;
`platform.guard_connection_status()` with `dw_app` UPDATEs, not through the
settler; `platform.revoke_connection_secrets` on a `dw_app` transaction, not
through the route. Rows are planted by the migrator; every write under test is
`dw_app`'s, bound to one company. Each test seeds its own company.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_kernel.secret import Secret
from dw_platform.adapters.kms import LocalDevKms
from dw_platform.adapters.persistence.connections_repo import SqlConnectionStore
from dw_platform.adapters.persistence.digital_workers_repo import SqlScopedAudit
from dw_platform.adapters.persistence.secret_envelopes import SqlSecretEnvelopes
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.connections import (
    CONNECTIONS_MANAGE_SCOPE,
    CONNECTIONS_READ_SCOPE,
    CONNECTIONS_USE_SCOPE,
    CallSite,
    ConnectionUsability,
    Usability,
    UsableContext,
)
from dw_platform.application.secrets import SecretCaller, SecretStore, SecretSubject
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)

pytestmark = pytest.mark.integration

CANARY = "canary-04-không-được-lộ"
MASTER = bytes(range(32))
CONNECTOR = ("probe", 1)
CALL_SITES: tuple[CallSite, ...] = ("binding_review", "run_admission", "egress")


@dataclass
class FakeCatalog:
    """`ConnectorCatalogPort` as ticket 05's manifests will answer it."""

    fields: dict[tuple[str, int], frozenset[str]]

    def secret_fields(self, connector_key: str, connector_major: int) -> frozenset[str] | None:
        return self.fields.get((connector_key, connector_major))


DECLARED = FakeCatalog({CONNECTOR: frozenset({"api_key"})})


@dataclass(frozen=True)
class World:
    tenant: PlantedTenant
    # `connections.use` at workspace depth in the main workspace.
    user_main: uuid.UUID
    # `connections.use` at workspace depth in the second workspace only.
    user_second: uuid.UUID
    # `connections.use` at tenant depth.
    user_tenant: uuid.UUID
    # A member holding nothing.
    user_none: uuid.UUID
    connection: uuid.UUID
    other_connection: uuid.UUID

    @property
    def main(self) -> uuid.UUID:
        return self.tenant.main

    @property
    def second(self) -> uuid.UUID:
        return self.tenant.workspaces[1]


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessions(db_urls: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _member(
    conn: object, tenant: PlantedTenant, workspace: uuid.UUID, role: uuid.UUID | None
) -> uuid.UUID:
    user = await plant_person(conn, tenant.tenant_id)  # type: ignore[arg-type]
    membership = await plant_membership(conn, tenant.tenant_id, workspace, user)  # type: ignore[arg-type]
    if role is not None:
        await assign(conn, tenant.tenant_id, workspace, membership, role)  # type: ignore[arg-type]
    return user


async def plant_connection(
    conn: object,
    tenant_id: uuid.UUID,
    workspace: uuid.UUID,
    *,
    status: str = "active",
    share_scope: str = "workspace",
    account: str | None = None,
) -> uuid.UUID:
    connection = uuid.uuid4()
    await conn.execute(  # type: ignore[attr-defined]
        sa.text(
            "INSERT INTO platform.connections (id, tenant_id, owning_workspace_id, name,"
            " connector_key, connector_major, share_scope, external_account, status)"
            " VALUES (:c, :t, :w, 'Thử', :k, :m, :s, :a, :st)"
        ),
        {
            "c": connection,
            "t": tenant_id,
            "w": workspace,
            "k": CONNECTOR[0],
            "m": CONNECTOR[1],
            "s": share_scope,
            "a": account or f"{connection.hex[:10]}@acme.vn",
            "st": status,
        },
    )
    return connection


async def _world(migrator: AsyncEngine) -> World:
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        t = tenant.tenant_id
        tag = t.hex[:8]
        at_workspace = await plant_role(
            conn, t, f"cn_ws_{tag}", {CONNECTIONS_USE_SCOPE: "workspace"}
        )
        at_tenant = await plant_role(conn, t, f"cn_t_{tag}", {CONNECTIONS_USE_SCOPE: "tenant"})
        world = World(
            tenant=tenant,
            user_main=await _member(conn, tenant, tenant.main, at_workspace),
            user_second=await _member(conn, tenant, tenant.workspaces[1], at_workspace),
            user_tenant=await _member(conn, tenant, tenant.main, at_tenant),
            user_none=await _member(conn, tenant, tenant.main, None),
            connection=await plant_connection(conn, t, tenant.main),
            other_connection=await plant_connection(conn, t, tenant.main),
        )
    return world


def _store(sessions: async_sessionmaker[AsyncSession]) -> SecretStore:
    return SecretStore(
        kms=LocalDevKms(MASTER),
        audit=SqlScopedAudit(sessions),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


async def put_secret(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    connection: uuid.UUID,
    secret_field: str,
    value: str = CANARY,
) -> int:
    async with tenant_session(sessions, TenantScope(tenant_id=tenant_id)) as session:
        return await _store(sessions).put(
            SqlSecretEnvelopes(session),
            SecretCaller(tenant_id=tenant_id, actor_id=uuid.uuid4()),
            SecretSubject("connection", connection),
            secret_field,
            Secret(value),
        )


async def usable(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    connection: uuid.UUID,
    *,
    principal: uuid.UUID | None,
    workspace: uuid.UUID,
    call_site: CallSite = "run_admission",
    run_requested_at: datetime | None = None,
    purpose: str = "tool",
    catalog: FakeCatalog = DECLARED,
) -> Usability:
    rule = ConnectionUsability(store=SqlConnectionStore(sessions), catalog=catalog)
    return await rule.connection_usable(
        connection,
        UsableContext(
            tenant_id=tenant_id,
            principal_id=principal,
            workspace_id=workspace,
            call_site=call_site,
            run_requested_at=run_requested_at,
        ),
        purpose,
    )


async def as_app(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, sql: str, **values: object
) -> None:
    async with tenant_session(sessions, TenantScope(tenant_id=tenant_id)) as session:
        await session.execute(sa.text(sql), values)


async def _scalar(migrator: AsyncEngine, sql: str, **values: object) -> object:
    async with migrator.connect() as conn:
        return await conn.scalar(sa.text(sql), values)


async def _status(migrator: AsyncEngine, connection: uuid.UUID) -> str:
    found = await _scalar(
        migrator, "SELECT status FROM platform.connections WHERE id = :c", c=connection
    )
    assert isinstance(found, str)
    return found


async def _now(migrator: AsyncEngine) -> datetime:
    found = await _scalar(migrator, "SELECT now()")
    assert isinstance(found, datetime)
    return found


def _refused_by(caught: pytest.ExceptionInfo[IntegrityError]) -> str:
    refused = refusal(caught.value)
    assert refused is not None, caught.value
    return refused[0]


# -- R5.3 (CV13) -----------------------------------------------------------------


async def test_another_company_asking_about_a_connection_finds_none(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    a, b = await _world(migrator), await _world(migrator)

    answer = await usable(
        sessions, b.tenant.tenant_id, a.connection, principal=b.user_tenant, workspace=a.main
    )

    assert answer == Usability(False, "connection_not_found")
    # The same question in A's own name is answered: the refusal is the company's.
    assert (
        await usable(
            sessions, a.tenant.tenant_id, a.connection, principal=a.user_tenant, workspace=a.main
        )
    ).usable


async def test_revoking_with_another_company_id_writes_nothing(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    a, b = await _world(migrator), await _world(migrator)
    await put_secret(sessions, a.tenant.tenant_id, a.connection, "api_key")

    async with tenant_session(sessions, TenantScope(tenant_id=b.tenant.tenant_id)) as session:
        rows = (
            await session.execute(
                sa.text("SELECT * FROM platform.revoke_connection_secrets(:c)"), {"c": a.connection}
            )
        ).all()

    assert rows == []
    assert (
        await _scalar(
            migrator,
            "SELECT count(*) FROM platform.secret_envelopes"
            " WHERE connection_id = :c AND revoked_at IS NOT NULL",
            c=a.connection,
        )
        == 0
    )
    assert (
        await _scalar(
            migrator,
            "SELECT compromised_at FROM platform.connections WHERE id = :c",
            c=a.connection,
        )
        is None
    )


# -- R5.4, R5.20 (CV14) ----------------------------------------------------------


async def test_a_connection_is_usable_only_in_its_own_workspace(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id

    elsewhere = await usable(
        sessions, t, world.connection, principal=world.user_tenant, workspace=world.second
    )
    at_home = await usable(
        sessions, t, world.connection, principal=world.user_tenant, workspace=world.main
    )

    assert elsewhere == Usability(False, "connection_out_of_scope")
    assert at_home == Usability(True)


@pytest.mark.parametrize("share_scope", ["owner", "workspace_subtree"])
async def test_a_connection_written_with_another_share_scope_is_not_usable(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession], share_scope: str
) -> None:
    world = await _world(migrator)
    async with migrator.begin() as conn:
        written = await plant_connection(
            conn, world.tenant.tenant_id, world.main, share_scope=share_scope
        )

    answer = await usable(
        sessions, world.tenant.tenant_id, written, principal=world.user_tenant, workspace=world.main
    )

    assert answer == Usability(False, "connection_out_of_scope")


# -- R5.5 (CV15) -----------------------------------------------------------------


async def test_a_disabled_connection_is_refused_at_every_call_site(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    await put_secret(sessions, t, world.connection, "api_key")
    await as_app(
        sessions,
        t,
        "UPDATE platform.connections SET status = 'disabled' WHERE id = :c",
        c=world.connection,
    )

    for call_site in CALL_SITES:
        answer = await usable(
            sessions,
            t,
            world.connection,
            principal=world.user_tenant,
            workspace=world.main,
            call_site=call_site,
            run_requested_at=await _now(migrator),
        )
        assert answer == Usability(False, "connection_disabled"), call_site


# -- R5.6 (CV15) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "path", "to"),
    [
        ("revoked", ("active", "revoked"), "active"),
        ("revoked", ("active", "revoked"), "disabled"),
        ("disabled", ("active", "disabled"), "pending"),
    ],
)
async def test_the_status_trigger_refuses_a_move_off_its_table(
    migrator: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    start: str,
    path: tuple[str, ...],
    to: str,
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    for step in path[1:]:
        await as_app(
            sessions,
            t,
            "UPDATE platform.connections SET status = :s WHERE id = :c",
            s=step,
            c=world.connection,
        )
    assert await _status(migrator, world.connection) == start

    with pytest.raises(IntegrityError) as caught:
        await as_app(
            sessions,
            t,
            "UPDATE platform.connections SET status = :s WHERE id = :c",
            s=to,
            c=world.connection,
        )

    assert _refused_by(caught) in {
        "ck_connections_status_transition",
        "ck_connections_enable_approved",
    }
    assert getattr(caught.value.orig, "sqlstate", None) == "23514" or "23514" in str(caught.value)
    assert await _status(migrator, world.connection) == start


async def test_a_connection_is_never_inserted_disabled(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)

    with pytest.raises(IntegrityError) as caught:
        await as_app(
            sessions,
            world.tenant.tenant_id,
            "INSERT INTO platform.connections (id, tenant_id, owning_workspace_id, name,"
            " connector_key, connector_major, share_scope, external_account, status)"
            " VALUES (:c, :t, :w, 'Thử', 'probe', 1, 'workspace', 'x@acme.vn', 'disabled')",
            c=uuid.uuid4(),
            t=world.tenant.tenant_id,
            w=world.main,
        )

    assert _refused_by(caught) == "ck_connections_status_transition"


async def test_disabling_stamps_disabled_at(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)

    await as_app(
        sessions,
        world.tenant.tenant_id,
        "UPDATE platform.connections SET status = 'disabled' WHERE id = :c",
        c=world.connection,
    )

    assert await _status(migrator, world.connection) == "disabled"
    assert isinstance(
        await _scalar(
            migrator,
            "SELECT disabled_at FROM platform.connections WHERE id = :c",
            c=world.connection,
        ),
        datetime,
    )


async def test_dw_app_cannot_write_disabled_at_or_compromised_at(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    for column in ("disabled_at", "compromised_at"):
        with pytest.raises(DBAPIError, match="permission denied"):
            await as_app(
                sessions,
                world.tenant.tenant_id,
                f"UPDATE platform.connections SET {column} = now() WHERE id = :c",
                c=world.connection,
            )


# -- R5.19 (CV21): the trigger, asked directly -----------------------------------


async def _approval(
    migrator: AsyncEngine,
    world: World,
    connection: uuid.UUID,
    *,
    status: str = "approved",
    created_at: datetime | None = None,
) -> uuid.UUID:
    approval = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, reason, payload, status, required_scope,"
                " created_at)"
                " VALUES (:id, :t, :w, 'connections.enable', :u, 'thử',"
                " jsonb_build_object('connection_id', CAST(:c AS text)), :s,"
                " 'connections.manage', coalesce(CAST(:at AS timestamptz), clock_timestamp()))"
            ),
            {
                "id": approval,
                "t": world.tenant.tenant_id,
                "w": world.main,
                "u": world.user_main,
                "c": str(connection),
                "s": status,
                "at": created_at,
            },
        )
    return approval


async def _enable_with(
    sessions: async_sessionmaker[AsyncSession],
    world: World,
    connection: uuid.UUID,
    approval: str | None,
) -> None:
    async with tenant_session(sessions, TenantScope(tenant_id=world.tenant.tenant_id)) as session:
        if approval is not None:
            await session.execute(
                sa.text("SELECT set_config('app.connection_enable_approval', :a, true)"),
                {"a": approval},
            )
        await session.execute(
            sa.text("UPDATE platform.connections SET status = 'active' WHERE id = :c"),
            {"c": connection},
        )


async def _disabled(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession], world: World
) -> datetime:
    for connection in (world.connection, world.other_connection):
        await as_app(
            sessions,
            world.tenant.tenant_id,
            "UPDATE platform.connections SET status = 'disabled' WHERE id = :c",
            c=connection,
        )
    found = await _scalar(
        migrator, "SELECT disabled_at FROM platform.connections WHERE id = :c", c=world.connection
    )
    assert isinstance(found, datetime)
    return found


async def test_enabling_without_an_approved_request_of_this_connection_is_refused(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    disabled_at = await _disabled(migrator, sessions, world)
    pending = await _approval(migrator, world, world.connection, status="pending")
    of_another = await _approval(migrator, world, world.other_connection)
    too_early = await _approval(
        migrator, world, world.connection, created_at=disabled_at - timedelta(seconds=1)
    )

    for approval in (None, "not-a-uuid", str(pending), str(of_another), str(too_early)):
        with pytest.raises(IntegrityError) as caught:
            await _enable_with(sessions, world, world.connection, approval)
        assert _refused_by(caught) == "ck_connections_enable_approved", approval
        assert await _status(migrator, world.connection) == "disabled"

    approved = await _approval(migrator, world, world.connection)
    await _enable_with(sessions, world, world.connection, str(approved))
    assert await _status(migrator, world.connection) == "active"


# -- R5.8 ------------------------------------------------------------------------


async def test_a_deleted_connection_is_not_found(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    await as_app(
        sessions,
        world.tenant.tenant_id,
        "DELETE FROM platform.connections WHERE id = :c",
        c=world.connection,
    )

    answer = await usable(
        sessions,
        world.tenant.tenant_id,
        world.connection,
        principal=world.user_tenant,
        workspace=world.main,
    )

    assert answer == Usability(False, "connection_not_found")


# -- R5.9 (CV14) -----------------------------------------------------------------


async def test_using_a_connection_takes_connections_use_reaching_the_workspace(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    await put_secret(sessions, t, world.connection, "api_key")
    requested = await _now(migrator)

    async def ask(principal: uuid.UUID | None, call_site: CallSite) -> Usability:
        return await usable(
            sessions,
            t,
            world.connection,
            principal=principal,
            workspace=world.main,
            call_site=call_site,
            run_requested_at=requested,
        )

    for call_site in CALL_SITES:
        assert await ask(world.user_none, call_site) == Usability(False, "connection_use_denied"), (
            call_site
        )
        assert await ask(world.user_second, call_site) == Usability(
            False, "connection_use_denied"
        ), call_site
        assert await ask(None, call_site) == Usability(False, "connection_use_denied"), call_site
        assert await ask(world.user_main, call_site) == Usability(True), call_site
        assert await ask(world.user_tenant, call_site) == Usability(True), call_site


# -- R5.14 (CV14) ----------------------------------------------------------------


@pytest.mark.parametrize("purpose", ["model", "anything", ""])
async def test_a_purpose_other_than_tool_is_refused(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession], purpose: str
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id

    refused = await usable(
        sessions,
        t,
        world.connection,
        principal=world.user_main,
        workspace=world.main,
        purpose=purpose,
    )
    allowed = await usable(
        sessions,
        t,
        world.connection,
        principal=world.user_main,
        workspace=world.main,
        purpose="tool",
    )

    assert refused == Usability(False, "purpose_not_allowed")
    assert allowed == Usability(True)


# -- R5.15 (CV24) ----------------------------------------------------------------


async def test_a_field_with_no_version_left_unrevoked_refuses_the_egress_call(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    await put_secret(sessions, t, world.connection, "api_key")
    await put_secret(sessions, t, world.connection, "api_key")
    requested = await _now(migrator)

    async def ask(call_site: CallSite = "egress", **overrides: object) -> Usability:
        return await usable(
            sessions,
            t,
            world.connection,
            principal=world.user_main,
            workspace=world.main,
            call_site=call_site,
            run_requested_at=overrides.get("run_requested_at", requested),  # type: ignore[arg-type]
            catalog=overrides.get("catalog", DECLARED),  # type: ignore[arg-type]
        )

    # One version not revoked: usable; no catalogue entry, or no request time: not.
    assert await ask() == Usability(True)
    assert await ask(catalog=FakeCatalog({})) == Usability(False, "credential_revoked")
    assert await ask(run_requested_at=None) == Usability(False, "credential_revoked")

    # Every version revoked, as a rotation's replaced versions are (not compromise).
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.secret_envelopes SET revoked_at = now() - interval '1 second'"
                " WHERE connection_id = :c AND revoked_at IS NULL"
            ),
            {"c": world.connection},
        )
    assert await ask() == Usability(False, "credential_revoked")
    # The secret branch is the egress call's alone.
    assert await ask("run_admission") == Usability(True)
    assert await ask("binding_review") == Usability(True)

    # No row left at all reads as revoked (closed while missing).
    async with tenant_session(sessions, TenantScope(tenant_id=t)) as session:
        await session.execute(
            sa.text("SELECT platform.delete_secret('connection', :c, 'api_key')"),
            {"c": world.connection},
        )
    assert await ask() == Usability(False, "credential_revoked")
    assert await ask("run_admission") == Usability(True)


# -- R5.16, R5.17 (CV24, CV28) ---------------------------------------------------


async def test_a_run_requested_before_a_revocation_for_compromise_stays_refused(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    await put_secret(sessions, t, world.connection, "api_key")
    t0 = await _now(migrator)
    async with tenant_session(sessions, TenantScope(tenant_id=t)) as session:
        await session.execute(
            sa.text("SELECT * FROM platform.revoke_connection_secrets(:c)"),
            {"c": world.connection},
        )
    compromised_at = await _scalar(
        migrator,
        "SELECT compromised_at FROM platform.connections WHERE id = :c",
        c=world.connection,
    )
    assert isinstance(compromised_at, datetime) and compromised_at > t0
    # A new value after the revocation: a version not revoked exists again.
    await put_secret(sessions, t, world.connection, "api_key", "a new value")

    async def at(requested: datetime) -> Usability:
        return await usable(
            sessions,
            t,
            world.connection,
            principal=world.user_main,
            workspace=world.main,
            call_site="egress",
            run_requested_at=requested,
        )

    assert await at(t0) == Usability(False, "credential_revoked")
    assert await at(compromised_at) == Usability(False, "credential_revoked")
    assert await at(compromised_at + timedelta(microseconds=1)) == Usability(True)


async def test_a_rotation_alone_stops_no_run(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    await put_secret(sessions, t, world.connection, "api_key")
    t0 = await _now(migrator)
    await put_secret(sessions, t, world.connection, "api_key", "rotated")

    answer = await usable(
        sessions,
        t,
        world.connection,
        principal=world.user_main,
        workspace=world.main,
        call_site="egress",
        run_requested_at=t0,
    )

    assert answer == Usability(True)


# -- R1.15 (CV28) ----------------------------------------------------------------


async def test_revoking_for_compromise_revokes_every_live_version_and_stamps_the_connection(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    t = world.tenant.tenant_id
    for secret_field in ("api_key", "api_key", "password"):
        await put_secret(sessions, t, world.connection, secret_field)
    await put_secret(sessions, t, world.other_connection, "api_key")

    async def versions(connection: uuid.UUID) -> dict[tuple[str, int], tuple[object, object]]:
        async with migrator.connect() as conn:
            rows = await conn.execute(
                sa.text(
                    "SELECT field, secret_version, revoked_at, replaced_at"
                    " FROM platform.secret_envelopes WHERE connection_id = :c"
                ),
                {"c": connection},
            )
            return {(r.field, r.secret_version): (r.revoked_at, r.replaced_at) for r in rows}

    before = await versions(world.connection)
    other_before = await versions(world.other_connection)
    async with tenant_session(sessions, TenantScope(tenant_id=t)) as session:
        revoked = (
            await session.execute(
                sa.text(
                    "SELECT compromised_on, versions, now() AS tx_now"
                    " FROM platform.revoke_connection_secrets(:c)"
                ),
                {"c": world.connection},
            )
        ).one()
    after = await versions(world.connection)

    assert revoked.versions == 2
    assert revoked.compromised_on == revoked.tx_now
    # The two live versions: revoked at the transaction's time, never replaced.
    for live in (("api_key", 2), ("password", 1)):
        assert after[live] == (revoked.tx_now, None), live
    # The version a rotation replaced keeps its own dates.
    assert after[("api_key", 1)] == before[("api_key", 1)]
    assert (
        await _scalar(
            migrator,
            "SELECT compromised_at FROM platform.connections WHERE id = :c",
            c=world.connection,
        )
        == revoked.tx_now
    )
    assert await versions(world.other_connection) == other_before
    # Nothing opens any more, the latest version included.
    async with tenant_session(sessions, TenantScope(tenant_id=t)) as session:
        opened = (
            await session.execute(
                sa.text(
                    "SELECT secret_version FROM platform.open_secret('connection', :c,"
                    " 'api_key', NULL)"
                ),
                {"c": world.connection},
            )
        ).all()
    assert opened == []


async def test_the_compromise_mark_is_never_cleared_or_moved_back(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    world = await _world(migrator)
    async with tenant_session(sessions, TenantScope(tenant_id=world.tenant.tenant_id)) as session:
        await session.execute(
            sa.text("SELECT * FROM platform.revoke_connection_secrets(:c)"),
            {"c": world.connection},
        )

    for value in ("NULL", "compromised_at - interval '1 second'"):
        with pytest.raises(IntegrityError) as caught:
            async with migrator.begin() as conn:
                await conn.execute(
                    sa.text(
                        f"UPDATE platform.connections SET compromised_at = {value} WHERE id = :c"
                    ),
                    {"c": world.connection},
                )
        assert _refused_by(caught) == "ck_connections_compromised_at_forward", value
    # Moving it forward (a second revocation) is allowed.
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.connections SET compromised_at = compromised_at"
                " + interval '1 second' WHERE id = :c"
            ),
            {"c": world.connection},
        )


async def test_only_dw_app_may_call_the_revocation(migrator: AsyncEngine) -> None:
    function = "platform.revoke_connection_secrets(uuid)"
    async with migrator.connect() as conn:
        holders = {
            role: await conn.scalar(
                sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                {"r": role, "f": function},
            )
            for role in ("dw_app", "dw_provisioner", "dw_agent_ro", "public")
        }
        shape = (
            await conn.execute(
                sa.text(
                    "SELECT prosecdef, proconfig FROM pg_proc WHERE oid = CAST(:f AS regprocedure)"
                ),
                {"f": function},
            )
        ).one()

    assert holders == {
        "dw_app": True,
        "dw_provisioner": False,
        "dw_agent_ro": False,
        "public": False,
    }
    assert shape.prosecdef is True
    assert shape.proconfig == ["search_path=pg_catalog, platform"]


# -- R5.9 (CV14): the catalogue --------------------------------------------------


async def test_the_three_keys_are_in_the_catalogue_at_workspace_depth(
    migrator: AsyncEngine,
) -> None:
    async with migrator.connect() as conn:
        rows = {
            row.key: (row.scope_kind, row.risk, row.status, row.tenant_grantable, row.area)
            for row in await conn.execute(
                sa.text(
                    "SELECT key, scope_kind, risk, status, tenant_grantable, area"
                    " FROM platform.permissions WHERE key LIKE 'connections.%'"
                )
            )
        }

    assert rows == {
        CONNECTIONS_READ_SCOPE: ("workspace", "standard", "active", True, "connections"),
        CONNECTIONS_MANAGE_SCOPE: ("workspace", "elevated", "active", True, "connections"),
        CONNECTIONS_USE_SCOPE: ("workspace", "standard", "active", True, "connections"),
    }
