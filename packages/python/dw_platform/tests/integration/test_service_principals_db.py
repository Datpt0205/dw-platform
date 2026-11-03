"""Integration: a company's service accounts on real PostgreSQL (org-and-principals 03).

R6.2 (no context from a dev token naming one), R6.3 (no login identity from any
writer), R6.4 (no critical role by any writer, with the role-row lock that
serialises an assignment against a critical key), R6.5, R6.15, R6.17 (the
binding guard, under the caller's RLS), R6.6 (one outbox row per growth of the
assigned grants), R6.9 (the purge function's two refusals), R6.10 (a composite
key cannot reach another tenant's account), R6.11 (a company row only in its own
tenant), R6.16 (the accountable owner), R7.1 and R7.2 (no service account among
login identities).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, provisioner_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, NotFoundError, PermissionDeniedError
from dw_platform.adapters.identity.dev_token import DEV_ISSUER
from dw_platform.adapters.persistence.directory import SqlWorkspaceDirectory
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.provisioning_repo import SqlProvisioningRepository
from dw_platform.adapters.persistence.service_principals_repo import SqlBindingFacts
from dw_platform.application.access_context import AccessContext
from dw_platform.application.identity import context_from
from dw_platform.application.service_principals import (
    SERVICE_PRINCIPALS_MANAGE_SCOPE,
    SERVICE_PRINCIPALS_USE_SCOPE,
    ServicePrincipalBindingGuard,
)
from dw_platform.testing.members import MemberStatus, add_tenant_member
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    grant_privilege,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    unregister_key,
)

pytestmark = pytest.mark.integration

_EVENT = "platform.service_principal.grants_changed"
_UNSET = uuid.UUID(int=0)


@dataclass(frozen=True)
class _Identity:
    subject: str
    email: str | None = None
    issuer: str = DEV_ISSUER
    email_verified: bool = False
    auth_methods: frozenset[str] = frozenset()
    acr: str | None = None


@dataclass
class World:
    a: PlantedTenant
    b: PlantedTenant
    std: str
    std2: str
    crit: str
    people: dict[str, uuid.UUID] = field(default_factory=dict)
    service: uuid.UUID = _UNSET
    service_membership: uuid.UUID = _UNSET
    std_role: uuid.UUID = _UNSET


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def provisioner(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(provisioner_url(db_urls.migrator), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admin(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this database: only to watch `pg_stat_activity`."""
    url = db_urls.admin.rsplit("/", 1)[0] + "/" + db_urls.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def plant_service(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    email: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A service account as the route makes one: its user, its `active` company
    row, its detail row and its membership of the owning workspace."""
    user = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO platform.users (id, subject, email, display_name, kind, owner_tenant_id)"
            " VALUES (:u, :s, :e, 'Tài khoản dịch vụ', 'service', :t)"
        ),
        {"u": user, "s": f"service:{user}", "e": email, "t": tenant_id},
    )
    await add_tenant_member(conn, tenant_id, user, "active")
    await conn.execute(
        sa.text(
            "INSERT INTO platform.service_principals"
            " (user_id, tenant_id, owning_workspace_id, name, owner_user_id)"
            " VALUES (:u, :t, :w, :n, :o)"
        ),
        {"u": user, "t": tenant_id, "w": workspace_id, "n": f"svc-{user.hex[:12]}", "o": owner_id},
    )
    membership = await plant_membership(conn, tenant_id, workspace_id, user)
    return user, membership


async def plant_dw(
    conn: AsyncConnection, tenant_id: uuid.UUID, workspace_id: uuid.UUID, owner_id: uuid.UUID
) -> uuid.UUID:
    """A Digital Worker's principal (and its DW row), in raw SQL."""
    principal, _ = await plant_service(conn, tenant_id, workspace_id, owner_id)
    await conn.execute(
        sa.text(
            "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
            " principal_user_id, key, name, mandate, work_kinds, allowed_tools,"
            " workflow_key, workflow_version, technical_owner_id, work_assigner_id,"
            " validator_id, created_by) VALUES (gen_random_uuid(), :t, :w, :u, :k, 'dw',"
            " 'dw', ARRAY['lead'], ARRAY[]::text[], 'wf', '1.0.0', :o, :o, :o, :o)"
        ),
        {
            "t": tenant_id,
            "w": workspace_id,
            "u": principal,
            "k": f"dw_{principal.hex[:12]}",
            "o": owner_id,
        },
    )
    return principal


async def _person(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    privileges: dict[str, str] | None = None,
    *,
    status: MemberStatus = "active",
    email: str | None = None,
) -> uuid.UUID:
    person = await plant_person(conn, tenant.tenant_id, status=status, email=email)
    membership = await plant_membership(conn, tenant.tenant_id, tenant.main, person)
    if privileges:
        role = await plant_role(conn, tenant.tenant_id, f"r_{person.hex[:12]}", privileges)
        await assign(conn, tenant.tenant_id, tenant.main, membership, role)
    return person


@pytest.fixture
async def world(migrator: AsyncEngine) -> AsyncIterator[World]:
    tag = uuid.uuid4().hex[:10]
    std, std2, crit = f"test.sp{tag}.std", f"test.sp{tag}.std2", f"test.sp{tag}.crit"
    async with migrator.begin() as conn:
        await register_key(conn, std)
        await register_key(conn, std2)
        await register_key(conn, crit, risk="critical")
        a = await plant_tenant(conn, workspaces=2)
        b = await plant_tenant(conn, workspaces=2)
        w = World(a=a, b=b, std=std, std2=std2, crit=crit)
        w.people["owner"] = await _person(conn, a)
        w.people["admin"] = await _person(
            conn,
            a,
            {
                SERVICE_PRINCIPALS_MANAGE_SCOPE: "tenant",
                SERVICE_PRINCIPALS_USE_SCOPE: "tenant",
                std: "tenant",
            },
        )
        w.people["narrow"] = await _person(conn, a, {SERVICE_PRINCIPALS_USE_SCOPE: "tenant"})
        w.people["nouse"] = await _person(conn, a, {std: "tenant"})
        w.people["suspended"] = await _person(conn, a, status="suspended")
        w.people["invited"] = await _person(conn, a, status="invited")
        w.people["b_person"] = await _person(conn, b)
        w.service, w.service_membership = await plant_service(
            conn, a.tenant_id, a.main, w.people["owner"]
        )
        w.std_role = await plant_role(conn, a.tenant_id, f"std_{tag}", {std: "workspace"})
        await assign(conn, a.tenant_id, a.main, w.service_membership, w.std_role)
    yield w
    async with migrator.begin() as conn:
        for key in (std, std2, crit):
            await unregister_key(conn, key)


async def context_of(app: AsyncEngine, w: World, name: str) -> AccessContext:
    lookup = SqlMembershipLookup(async_sessionmaker(app, expire_on_commit=False))
    access = await lookup.find_access(f"rbac-{w.people[name]}", DEV_ISSUER, w.a.tenant_id, w.a.main)
    assert access is not None, name
    return context_from(access)


def guard(app: AsyncEngine) -> ServicePrincipalBindingGuard:
    return ServicePrincipalBindingGuard(SqlBindingFacts(async_sessionmaker(app)))


def _refusal(exc: DBAPIError) -> tuple[str | None, str | None]:
    cause = getattr(exc.orig, "__cause__", None)
    return getattr(cause, "sqlstate", None), getattr(cause, "constraint_name", None)


async def _count(migrator: AsyncEngine, sql: str, **params: object) -> int:
    async with migrator.connect() as conn:
        return int((await conn.execute(sa.text(sql), params)).scalar_one())


async def _events(migrator: AsyncEngine, principal: uuid.UUID) -> int:
    return await _count(
        migrator,
        "SELECT count(*) FROM platform.outbox_events WHERE event_type = :e AND aggregate_id = :p",
        e=_EVENT,
        p=principal,
    )


# ---- R6.2, R6.3: never signs in -----------------------------------------------


async def test_a_dev_token_naming_a_service_account_builds_no_context(
    world: World, app: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R6.2 (OP8): `find_access` and `bootstrap` both refuse, and no user is made."""
    sessions = async_sessionmaker(app, expire_on_commit=False)
    subject = f"service:{world.service}"
    lookup = SqlMembershipLookup(sessions)
    assert await lookup.find_access(subject, DEV_ISSUER, world.a.tenant_id, world.a.main) is None
    # The same door lets the owner in: it is the kind that is refused.
    assert (
        await lookup.find_access(
            f"rbac-{world.people['owner']}", DEV_ISSUER, world.a.tenant_id, world.a.main
        )
        is not None
    )

    users = "SELECT count(*) FROM platform.users"
    before = await _count(migrator, users)
    bootstrap = SqlIdentityBootstrap(
        session_factory=sessions,
        default_tenant_id=world.a.tenant_id,
        default_workspace_id=world.a.main,
    )
    with pytest.raises(PermissionDeniedError):
        await bootstrap.bootstrap(_Identity(subject=subject))
    assert await _count(migrator, users) == before
    linked = "SELECT count(*) FROM platform.external_identities WHERE user_id = :u"
    assert await _count(migrator, linked, u=world.service) == 0


@pytest.mark.parametrize("writer", ["app", "provisioner"])
async def test_a_service_account_takes_no_login_identity_from_any_writer(
    world: World, app: AsyncEngine, provisioner: AsyncEngine, migrator: AsyncEngine, writer: str
) -> None:
    """R6.3 (OP8): `external_identities_human_only` refuses each writer."""
    engine = app if writer == "app" else provisioner
    with pytest.raises(DBAPIError, match="a service user has no login") as refused:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.external_identities (id, user_id, issuer, subject)"
                    " VALUES (:id, :u, 'https://idp.test', :s)"
                ),
                {"id": uuid.uuid4(), "u": world.service, "s": f"sp-{uuid.uuid4()}"},
            )
    assert _refusal(refused.value) == ("23514", "ck_external_identities_human_only")
    linked = "SELECT count(*) FROM platform.external_identities WHERE user_id = :u"
    assert await _count(migrator, linked, u=world.service) == 0


# ---- R6.4: no critical role, by any writer ------------------------------------


async def _refused_23514(conn: AsyncConnection, sql: str, **values: object) -> None:
    with pytest.raises(DBAPIError) as refused:
        async with conn.begin_nested():
            await conn.execute(sa.text(sql), values)
    assert _refusal(refused.value) == ("23514", "ck_role_assignments_service_not_critical")


async def test_no_critical_role_reaches_a_service_account_even_from_the_migrator(
    world: World, migrator: AsyncEngine
) -> None:
    """R6.4 (OP9) as `dw_migrator`: `tenant_owner`, a critical key into a role
    it holds, and a critical role it holds restored; a person may hold all three."""
    a = world.a.tenant_id
    async with migrator.connect() as conn, conn.begin() as tx:
        owner_role = await role_id(conn, a, "tenant_owner")
        await _refused_23514(
            conn,
            "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
            " role_id) VALUES (gen_random_uuid(), :t, :w, :m, :r)",
            t=a,
            w=world.a.main,
            m=world.service_membership,
            r=owner_role,
        )
        await _refused_23514(
            conn,
            "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key,"
            " depth) VALUES (:t, :r, :k, 'workspace')",
            t=a,
            r=world.std_role,
            k=world.crit,
        )
        # A critical role it held, soft-deleted, past the guard as only the
        # table's owner can (the state a restore would come back to).
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET deleted_at = now() WHERE id = :r"),
            {"r": world.std_role},
        )
        await conn.execute(
            sa.text(
                "ALTER TABLE platform.tenant_role_permissions"
                " DISABLE TRIGGER guard_service_principal_grants"
            )
        )
        await grant_privilege(conn, a, world.std_role, world.crit, "workspace")
        await conn.execute(
            sa.text(
                "ALTER TABLE platform.tenant_role_permissions"
                " ENABLE TRIGGER guard_service_principal_grants"
            )
        )
        await _refused_23514(
            conn,
            "UPDATE platform.tenant_roles SET deleted_at = NULL WHERE id = :r",
            r=world.std_role,
        )
        # A person takes the same role, restored, without a word.
        human_membership = (
            await conn.execute(
                sa.text("SELECT id FROM platform.memberships WHERE user_id = :u"),
                {"u": world.people["nouse"]},
            )
        ).scalar_one()
        crit_role = await plant_role(
            conn, a, f"crit_{uuid.uuid4().hex[:8]}", {world.crit: "workspace"}
        )
        await assign(conn, a, world.a.main, human_membership, crit_role)
        await tx.rollback()


async def _blocked(admin: AsyncEngine, pid: int) -> bool:
    async with admin.connect() as conn:
        waiting = await conn.scalar(
            sa.text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        )
    return bool(waiting == "Lock")


async def _until(check: Callable[[], Awaitable[bool]], *, seconds: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if await check():
            return True
        await asyncio.sleep(0.05)
    return False


async def _pid(conn: AsyncConnection) -> int:
    return int((await conn.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one())


async def _race(
    migrator: AsyncEngine,
    admin: AsyncEngine,
    first: Callable[[AsyncConnection], Awaitable[None]],
    second: Callable[[AsyncConnection], Coroutine[Any, Any, None]],
) -> list[str]:
    """`first` writes and holds its transaction open; `second` starts, waits on
    it (or does not), then `first` commits: which of them were refused."""
    refused: list[str] = []
    async with migrator.connect() as one, migrator.connect() as two:
        await one.begin()
        try:
            await first(one)
        except DBAPIError:
            refused.append("first")
            await one.rollback()
        await two.begin()
        pid = await _pid(two)
        later: asyncio.Task[None] = asyncio.create_task(second(two))
        # Waiting on the lock, or done because nothing made it wait.
        await _until(lambda: _blocked(admin, pid) if not later.done() else _true())
        if one.in_transaction():
            await one.commit()
        try:
            await later
            await two.commit()
        except DBAPIError as exc:
            assert _refusal(exc)[0] == "23514"
            refused.append("second")
            await two.rollback()
    return refused


async def _true() -> bool:
    return True


async def test_an_assignment_and_a_critical_key_on_one_role_never_both_commit(
    world: World, migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """R6.4 (OP9): two transactions on one role R, each alone acceptable; in
    either order exactly one is refused, because each branch locks R's row."""
    a = world.a.tenant_id
    async with migrator.begin() as conn:
        r1 = await plant_role(conn, a, f"race1_{uuid.uuid4().hex[:8]}", {world.std: "workspace"})
        r2 = await plant_role(conn, a, f"race2_{uuid.uuid4().hex[:8]}", {world.std: "workspace"})

    def assign_to_service(
        role: uuid.UUID,
    ) -> Callable[[AsyncConnection], Coroutine[Any, Any, None]]:
        async def run(conn: AsyncConnection) -> None:
            await assign(conn, a, world.a.main, world.service_membership, role)

        return run

    def add_critical(role: uuid.UUID) -> Callable[[AsyncConnection], Coroutine[Any, Any, None]]:
        async def run(conn: AsyncConnection) -> None:
            await grant_privilege(conn, a, role, world.crit, "workspace")

        return run

    assert await _race(migrator, admin, assign_to_service(r1), add_critical(r1)) == ["second"]
    assert await _race(migrator, admin, add_critical(r2), assign_to_service(r2)) == ["second"]


async def test_the_guard_locks_the_role_row_for_a_service_account_only(
    world: World, migrator: AsyncEngine
) -> None:
    """R6.4: assigning a role to a person takes no lock on its row (the foreign
    key's KEY SHARE lets a NO KEY UPDATE through); to a service account it does."""
    a = world.a.tenant_id
    probe = sa.text("SELECT id FROM platform.tenant_roles WHERE id = :r FOR NO KEY UPDATE NOWAIT")
    async with migrator.begin() as conn:
        role = await plant_role(conn, a, f"lock_{uuid.uuid4().hex[:8]}", {world.std: "workspace"})
        human = (
            await conn.execute(
                sa.text("SELECT id FROM platform.memberships WHERE user_id = :u"),
                {"u": world.people["owner"]},
            )
        ).scalar_one()
    async with migrator.connect() as writer, migrator.connect() as other:
        async with writer.begin() as tx:
            await assign(writer, a, world.a.main, human, role)
            async with other.begin() as probing:
                await other.execute(probe, {"r": role})
                await probing.rollback()
            await assign(writer, a, world.a.main, world.service_membership, role)
            with pytest.raises(DBAPIError) as held:
                async with other.begin():
                    await other.execute(probe, {"r": role})
            assert _refusal(held.value)[0] == "55P03"
            await tx.rollback()


async def test_the_guard_is_on_all_three_tables(migrator: AsyncEngine) -> None:
    """R6.4: the catalog holds the guard and the event trigger on each table."""
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT c.relname, t.tgname FROM pg_trigger t"
                    " JOIN pg_class c ON c.oid = t.tgrelid"
                    " WHERE t.tgname IN ('guard_service_principal_grants',"
                    "                    'service_principal_grants_changed')"
                    "   AND NOT t.tgisinternal"
                )
            )
        ).all()
    assert {(r.relname, r.tgname) for r in rows} == {
        (table, trigger)
        for table in ("role_assignments", "tenant_role_permissions", "tenant_roles")
        for trigger in ("guard_service_principal_grants", "service_principal_grants_changed")
    }


# ---- R6.6: grants that grow announce once -------------------------------------


async def test_each_growth_of_assigned_grants_announces_once_and_nothing_else_does(
    world: World, migrator: AsyncEngine
) -> None:
    """R6.6: the cases that ARE the definition of growth write one row each, in
    the write's own transaction; the others none."""
    a, s = world.a.tenant_id, world.service
    async with migrator.begin() as conn:
        grown = await plant_role(conn, a, f"grow_{uuid.uuid4().hex[:8]}", {world.std: "workspace"})
        timed = await plant_role(conn, a, f"time_{uuid.uuid4().hex[:8]}", {world.std2: "workspace"})
    later = datetime.now(UTC) + timedelta(days=1)

    async def case(name: str, expected: int, sql: str, **values: object) -> None:
        before = await _events(migrator, s)
        async with migrator.begin() as conn:
            await conn.execute(sa.text(sql), values)
        assert await _events(migrator, s) - before == expected, name

    assignment = uuid.uuid4()
    await case(
        "assigned",
        1,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id) VALUES (:id, :t, :w, :m, :r)",
        id=assignment,
        t=a,
        w=world.a.main,
        m=world.service_membership,
        r=grown,
    )
    timed_assignment = uuid.uuid4()
    await case(
        "assigned with an end",
        1,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id, expires_at) VALUES (:id, :t, :w, :m, :r, :x)",
        id=timed_assignment,
        t=a,
        w=world.a.main,
        m=world.service_membership,
        r=timed,
        x=later,
    )
    update_end = "UPDATE platform.role_assignments SET expires_at = :x WHERE id = :id"
    await case("extended", 1, update_end, x=later + timedelta(days=1), id=timed_assignment)
    await case("shortened", 0, update_end, x=later, id=timed_assignment)
    await case(
        "end removed",
        1,
        "UPDATE platform.role_assignments SET expires_at = NULL WHERE id = :id",
        id=timed_assignment,
    )
    await case(
        "only assigned_by",
        0,
        "UPDATE platform.role_assignments SET assigned_by = :u WHERE id = :id",
        u=world.people["admin"],
        id=assignment,
    )
    await case(
        "a key added",
        1,
        "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key, depth)"
        " VALUES (:t, :r, :k, 'workspace')",
        t=a,
        r=grown,
        k=world.std2,
    )
    depth = (
        "UPDATE platform.tenant_role_permissions SET depth = :d"
        " WHERE role_id = :r AND permission_key = :k"
    )
    await case("deepened", 1, depth, d="tenant", r=grown, k=world.std2)
    await case("made shallower", 0, depth, d="workspace", r=grown, k=world.std2)
    await case(
        "a key removed",
        0,
        "DELETE FROM platform.tenant_role_permissions WHERE role_id = :r AND permission_key = :k",
        r=grown,
        k=world.std2,
    )
    soft = "UPDATE platform.tenant_roles SET deleted_at = :d WHERE id = :r"
    await case("soft-deleted", 0, soft, d=datetime.now(UTC), r=grown)
    await case("restored", 1, soft, d=None, r=grown)
    status = "UPDATE platform.tenant_members SET status = :s WHERE tenant_id = :t AND user_id = :u"
    await case("suspended", 0, status, s="suspended", t=a, u=s)
    async with migrator.begin() as conn:
        third = await plant_role(conn, a, f"third_{uuid.uuid4().hex[:8]}", {world.std: "workspace"})
    await case(
        "assigned while suspended",
        1,
        "INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id,"
        " role_id) VALUES (gen_random_uuid(), :t, :w, :m, :r)",
        t=a,
        w=world.a.main,
        m=world.service_membership,
        r=third,
    )
    await case("reactivated", 0, status, s="active", t=a, u=s)

    async with migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT tenant_id, workspace_id, payload FROM platform.outbox_events"
                    " WHERE event_type = :e AND aggregate_id = :p LIMIT 1"
                ),
                {"e": _EVENT, "p": s},
            )
        ).one()
    assert (row.tenant_id, row.workspace_id) == (a, world.a.main)
    assert row.payload == {"tenant_id": str(a), "service_principal_id": str(s)}


async def test_a_role_given_to_a_person_announces_nothing(
    world: World, migrator: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        before = await _count(
            migrator, "SELECT count(*) FROM platform.outbox_events WHERE event_type = :e", e=_EVENT
        )
        role = await plant_role(
            conn, world.a.tenant_id, f"hum_{uuid.uuid4().hex[:8]}", {world.std: "workspace"}
        )
        membership = (
            await conn.execute(
                sa.text("SELECT id FROM platform.memberships WHERE user_id = :u"),
                {"u": world.people["owner"]},
            )
        ).scalar_one()
        await assign(conn, world.a.tenant_id, world.a.main, membership, role)
    after = await _count(
        migrator, "SELECT count(*) FROM platform.outbox_events WHERE event_type = :e", e=_EVENT
    )
    assert after == before


# ---- R6.5, R6.15, R6.17: the binding guard ------------------------------------


async def test_a_holder_of_every_grant_may_bind_and_one_short_is_told_what(
    world: World, app: AsyncEngine
) -> None:
    """R6.5 (OP10)."""
    admin = await context_of(app, world, "admin")
    await guard(app).require_bindable(admin, world.service)
    assert await guard(app).bindable(admin, [world.service]) == {world.service: True}

    narrow = await context_of(app, world, "narrow")
    with pytest.raises(PermissionDeniedError) as short:
        await guard(app).require_bindable(narrow, world.service)
    assert short.value.details == {
        "reason_code": "rbac_escalation",
        "missing": [
            {
                "permission_key": world.std,
                "depth": "workspace",
                "anchor_workspace_id": str(world.a.main),
            }
        ],
    }
    assert await guard(app).bindable(narrow, [world.service]) == {world.service: False}

    nouse = await context_of(app, world, "nouse")
    with pytest.raises(PermissionDeniedError) as no_use:
        await guard(app).require_bindable(nouse, world.service)
    assert no_use.value.details["reason_code"] == "rbac_escalation"
    assert [m["permission_key"] for m in no_use.value.details["missing"]] == [  # type: ignore[attr-defined]
        SERVICE_PRINCIPALS_USE_SCOPE
    ]


async def test_what_is_not_this_companys_service_account_is_not_found(
    world: World, app: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R6.15 (OP17): another company's account, a DW's principal in the
    caller's workspace and in another, a person, an unknown id: one 404, no key."""
    async with migrator.begin() as conn:
        theirs, _ = await plant_service(
            conn, world.b.tenant_id, world.b.main, world.people["b_person"]
        )
        dw_here = await plant_dw(conn, world.a.tenant_id, world.a.main, world.people["owner"])
        dw_there = await plant_dw(
            conn, world.a.tenant_id, world.a.workspaces[1], world.people["owner"]
        )
    admin = await context_of(app, world, "admin")
    for unknown in (theirs, dw_here, dw_there, world.people["owner"], uuid.uuid4()):
        with pytest.raises(NotFoundError) as refused:
            await guard(app).require_bindable(admin, unknown)
        assert "missing" not in refused.value.details, unknown


async def test_an_inactive_account_or_an_absent_owner_is_not_bound(
    world: World, app: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R6.17 (OP18), in the guard's order: the account first, then its owner."""
    admin = await context_of(app, world, "admin")
    status = "UPDATE platform.tenant_members SET status = :s WHERE tenant_id = :t AND user_id = :u"

    async def run(sql: str, **values: object) -> None:
        async with migrator.begin() as conn:
            await conn.execute(sa.text(sql), values)

    async def refused() -> str:
        with pytest.raises(ConflictError) as caught:
            await guard(app).require_bindable(admin, world.service)
        return str(caught.value.details["reason_code"])

    await run(status, s="suspended", t=world.a.tenant_id, u=world.people["owner"])
    assert await refused() == "owner_missing"
    await run(status, s="suspended", t=world.a.tenant_id, u=world.service)
    assert await refused() == "principal_inactive"
    await run(status, s="active", t=world.a.tenant_id, u=world.service)
    await run(status, s="active", t=world.a.tenant_id, u=world.people["owner"])
    await guard(app).require_bindable(admin, world.service)

    await run(
        "UPDATE platform.service_principals SET owner_user_id = NULL WHERE user_id = :u",
        u=world.service,
    )
    assert await refused() == "owner_missing"


# ---- R6.9, R6.10, R6.11, R6.16 ------------------------------------------------


async def test_purging_service_users_refuses_an_active_tenant_and_another_tenant(
    world: World, app: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R6.9 (OP14), as `dw_app`: an `active` tenant, then an `offboarding` one
    that is not the transaction's own, refused 23514 with nothing deleted; its
    own, offboarding, deletes its one service user."""
    async with migrator.begin() as conn:
        leaving = await plant_tenant(conn)
        person = await _person(conn, leaving)
        theirs, _ = await plant_service(conn, leaving.tenant_id, leaving.main, person)
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": leaving.tenant_id},
        )
    purge = sa.text("SELECT platform.purge_tenant_service_users(:p)")
    bind = sa.text("SELECT set_config('app.tenant_id', :t, true)")
    for bound, purged in (
        (world.a.tenant_id, world.a.tenant_id),
        (world.a.tenant_id, leaving.tenant_id),
    ):
        with pytest.raises(DBAPIError) as refused:
            async with app.begin() as conn:
                await conn.execute(bind, {"t": str(bound)})
                await conn.execute(purge, {"p": purged})
        assert _refusal(refused.value) == ("23514", "ck_users_service_purge")
    service_users = "SELECT count(*) FROM platform.users WHERE id = ANY(:ids)"
    assert await _count(migrator, service_users, ids=[world.service, theirs]) == 2

    async with app.begin() as conn:
        await conn.execute(bind, {"t": str(leaving.tenant_id)})
        assert (await conn.execute(purge, {"p": leaving.tenant_id})).scalar_one() == 1
    assert await _count(migrator, service_users, ids=[world.service, theirs]) == 1


async def test_a_composite_key_cannot_name_another_tenants_service_account(
    world: World, migrator: AsyncEngine
) -> None:
    """R6.10 (OP15): the target `uq_service_principals_tenant_id_user_id` is in
    the catalog, and a key through it refuses (tenant B, A's account)."""
    async with migrator.connect() as conn:
        kind = await conn.scalar(
            sa.text(
                "SELECT contype::text FROM pg_constraint"
                " WHERE conname = 'uq_service_principals_tenant_id_user_id'"
                "   AND conrelid = 'platform.service_principals'::regclass"
            )
        )
        assert kind == "u"
    async with migrator.connect() as conn:
        async with conn.begin() as tx:
            await conn.execute(
                sa.text(
                    "CREATE TABLE platform.zz_sp_reference_probe ("
                    " tenant_id uuid NOT NULL, sp_id uuid NOT NULL,"
                    " FOREIGN KEY (tenant_id, sp_id)"
                    " REFERENCES platform.service_principals (tenant_id, user_id))"
                )
            )
            with pytest.raises(DBAPIError) as refused:
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text("INSERT INTO platform.zz_sp_reference_probe VALUES (:t, :s)"),
                        {"t": world.b.tenant_id, "s": world.service},
                    )
            assert _refusal(refused.value)[0] == "23503"
            rows = await conn.scalar(sa.text("SELECT count(*) FROM platform.zz_sp_reference_probe"))
            assert rows == 0
            await tx.rollback()


@pytest.mark.parametrize("writer", ["app", "provisioner"])
async def test_a_service_account_is_a_member_of_its_own_tenant_only(
    world: World,
    app: AsyncEngine,
    provisioner: AsyncEngine,
    migrator: AsyncEngine,
    writer: str,
) -> None:
    """R6.11 (OP16): a company row in tenant B for A's account, by each writer."""
    engine = app if writer == "app" else provisioner
    with pytest.raises(DBAPIError) as refused:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(world.b.tenant_id)},
            )
            await add_tenant_member(conn, world.b.tenant_id, world.service, "active")
    assert _refusal(refused.value) == ("23514", "ck_tenant_members_service_own_tenant")
    rows = "SELECT count(*) FROM platform.tenant_members WHERE user_id = :u AND tenant_id = :t"
    assert await _count(migrator, rows, u=world.service, t=world.b.tenant_id) == 0


async def test_a_service_accounts_company_row_does_not_move_tenant(
    world: World, migrator: AsyncEngine
) -> None:
    """R6.11 (OP16): the UPDATE side, as the migrator (no application role may)."""
    with pytest.raises(DBAPIError) as refused:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.tenant_members SET tenant_id = :b"
                    " WHERE tenant_id = :a AND user_id = :u"
                ),
                {"a": world.a.tenant_id, "b": world.b.tenant_id, "u": world.service},
            )
    assert _refusal(refused.value)[0] == "23514"


async def test_the_accountable_owner_is_given_and_an_active_human_member(
    world: World, migrator: AsyncEngine
) -> None:
    """R6.16 (OP18): none, a suspended person, an invited one, a person of
    tenant B and a service account are each refused; a name changes under a
    suspended owner; the owner's company row removed empties the column."""
    a = world.a.tenant_id
    insert = (
        "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
        " name, owner_user_id) VALUES (:u, :t, :w, :n, :o)"
    )
    async with migrator.connect() as conn, conn.begin() as tx:
        fresh = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                " VALUES (:u, :s, 'svc', 'service', :t)"
            ),
            {"u": fresh, "s": f"service:{fresh}", "t": a},
        )
        for owner in (
            None,
            world.people["suspended"],
            world.people["invited"],
            world.people["b_person"],
            world.service,
        ):
            with pytest.raises(DBAPIError) as refused:
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text(insert),
                        {"u": fresh, "t": a, "w": world.a.main, "n": "x", "o": owner},
                    )
            assert _refusal(refused.value) == (
                "23514",
                "ck_service_principals_accountable_owner",
            ), owner
        await conn.execute(
            sa.text(insert),
            {"u": fresh, "t": a, "w": world.a.main, "n": "x", "o": world.people["owner"]},
        )
        with pytest.raises(DBAPIError):
            async with conn.begin_nested():
                await conn.execute(
                    sa.text(
                        "UPDATE platform.service_principals SET owner_user_id = :o"
                        " WHERE user_id = :u"
                    ),
                    {"o": world.people["suspended"], "u": fresh},
                )
        await tx.rollback()

    async with migrator.begin() as conn:
        second_owner = await _person(conn, world.a)
        account, _ = await plant_service(conn, a, world.a.main, second_owner)
        await conn.execute(
            sa.text("UPDATE platform.tenant_members SET status = 'suspended' WHERE user_id = :u"),
            {"u": second_owner},
        )
        await conn.execute(
            sa.text("UPDATE platform.service_principals SET name = 'renamed' WHERE user_id = :u"),
            {"u": account},
        )
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": a, "u": second_owner},
        )
    async with migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT name, owner_user_id FROM platform.service_principals WHERE user_id = :u"
                ),
                {"u": account},
            )
        ).one()
    assert tuple(row) == ("renamed", None)


# ---- R7: no service account among login identities ----------------------------


async def test_no_service_account_is_a_directory_candidate(
    world: World, app: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R7.1 (OP11): an admin of B lists candidates for B's main workspace; a
    service account of B (in its other workspace) and one of A, both with an
    email written by SQL, are not among them, while a person of B is."""
    async with migrator.begin() as conn:
        b_admin = await _person(conn, world.b, {"platform.members.write": "tenant"})
        theirs, _ = await plant_service(
            conn,
            world.b.tenant_id,
            world.b.workspaces[1],
            world.people["b_person"],
            email=f"svc-b-{uuid.uuid4().hex[:8]}@dw.test",
        )
        ours, _ = await plant_service(
            conn,
            world.a.tenant_id,
            world.a.main,
            world.people["owner"],
            email=f"svc-a-{uuid.uuid4().hex[:8]}@dw.test",
        )
        person = await plant_person(
            conn, world.b.tenant_id, email=f"p-b-{uuid.uuid4().hex[:8]}@dw.test"
        )
        await plant_membership(conn, world.b.tenant_id, world.b.workspaces[1], person)
    lookup = SqlMembershipLookup(async_sessionmaker(app, expire_on_commit=False))
    access = await lookup.find_access(
        f"rbac-{b_admin}", DEV_ISSUER, world.b.tenant_id, world.b.main
    )
    assert access is not None
    listed = {
        c.user_id
        for c in await SqlWorkspaceDirectory(async_sessionmaker(app)).list_candidates(
            context_from(access)
        )
    }
    assert person in listed
    assert theirs not in listed
    assert ours not in listed


async def test_the_platform_user_list_holds_people_only(
    world: World, provisioner: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R7.2 (OP11): a service account given an email by SQL is not listed."""
    async with migrator.begin() as conn:
        account, _ = await plant_service(
            conn,
            world.a.tenant_id,
            world.a.main,
            world.people["owner"],
            email=f"svc-list-{uuid.uuid4().hex[:8]}@dw.test",
        )
        person = await plant_person(
            conn, world.a.tenant_id, email=f"p-list-{uuid.uuid4().hex[:8]}@dw.test"
        )
    users = await SqlProvisioningRepository(
        async_sessionmaker(provisioner, class_=AsyncSession)
    ).list_users()
    listed = {u.user_id for u in users}
    assert person in listed
    assert account not in listed
