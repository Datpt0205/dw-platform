# ruff: noqa: F811  (`provisioner_engine` is a fixture imported from test_provisioning)
"""Integration: a person's standing in the company is one row with a status.

org-and-principals ticket 02 (R4.1-R4.5, R4.7, R4.8, R5.1; OP4-OP7), against
PostgreSQL as `dw_app` under RLS, with the migrator only to plant and to read
back. The world is `support_world`'s: tenant A (ws1, ws2), tenant B (wsB), its
people known to the dev issuer by `sg-<id>`.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import ModuleType

import pytest
import sqlalchemy as sa
from pg_harness import REPO_ROOT, DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from support_world import ISSUER, SupportWorld, build_world, context_of, provisioning
from test_provisioning import provisioner_engine  # noqa: F401  (a fixture, used by name)

from dw_kernel.errors import ConflictError
from dw_kernel.ports import FixedClock, SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.directory import SqlWorkspaceDirectory
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_admin import SqlMembershipAdminRepository
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.provisioning_repo import SqlProvisioningRepository
from dw_platform.adapters.persistence.tenant_members import SqlTenantMembersRepository
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.membership_admin import (
    GrantMembership,
    GrantMembershipHandler,
    RevokeMembership,
    RevokeMembershipHandler,
)
from dw_platform.application.tenant_members import (
    InviteMember,
    TenantMembersService,
    WorkspaceRoles,
)
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.seed_env import seed_test_env

pytestmark = pytest.mark.integration

OTHER_IDP = "https://issuer.test/realms/dw"


def _load(relative: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class _Identity:
    subject: str
    email: str | None
    email_verified: bool = True
    issuer: str = ISSUER
    name: str | None = None
    auth_methods: frozenset[str] = frozenset()
    acr: str | None = None


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def world(migrator: AsyncEngine) -> SupportWorld:
    return await build_world(migrator)


def _bootstrap(app: AsyncEngine, w: SupportWorld, **kw: object) -> SqlIdentityBootstrap:
    return SqlIdentityBootstrap(
        session_factory=async_sessionmaker(app, expire_on_commit=False),
        default_tenant_id=w.tenant_a,
        default_workspace_id=w.ws1,
        **kw,  # type: ignore[arg-type]
    )


def _seeded(w: SupportWorld, name: str) -> _Identity:
    """A world person signing in through the dev issuer, by their seeded subject."""
    return _Identity(subject=f"sg-{w.users[name]}", email=w.email(name))


def _members(app: AsyncEngine) -> TenantMembersService:
    return TenantMembersService(
        SqlTenantMembersRepository(async_sessionmaker(app, expire_on_commit=False)),
        ScopeAuthorizationService(),
        SystemClock(),
        Uuid4Generator(),
    )


async def _status(migrator: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID) -> str | None:
    async with migrator.connect() as conn:
        status = await conn.scalar(
            sa.text(
                "SELECT status FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"
            ),
            {"t": tenant, "u": user},
        )
    return None if status is None else str(status)


async def _set_status(
    migrator: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID, status: str
) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_members SET status = :s"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"s": status, "t": tenant, "u": user},
        )


async def _new_person(migrator: AsyncEngine, tag: str) -> tuple[uuid.UUID, str]:
    user = uuid.uuid4()
    email = f"{tag}-{user.hex[:8]}@status.test"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, email, display_name)"
                " VALUES (:u, :s, :e, :n)"
            ),
            {"u": user, "s": f"sg-{user}", "e": email, "n": tag},
        )
    return user, email


# ---- R4.1 (OP4): every membership hangs from a company member -------------------


async def test_a_membership_without_its_company_member_is_refused(
    world: SupportWorld, migrator: AsyncEngine
) -> None:
    user, _ = await _new_person(migrator, "orphan")
    with pytest.raises(IntegrityError, match="fk_memberships_tenant_members"):
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                    " VALUES (gen_random_uuid(), :t, :w, :u)"
                ),
                {"t": world.tenant_a, "w": world.ws1, "u": user},
            )


async def test_the_backfill_gives_one_row_per_pair_by_kind_and_sign_in(
    world: SupportWorld, migrator: AsyncEngine
) -> None:
    """Step 3, run on planted people with the key lifted, in a transaction that
    rolls back: signed in → active, a linked chat only or nothing → invited, a
    service user → active, one row for two workspaces."""
    backfill = _load("db/migrations/versions/349080a62e41_tenant_members.py", "tm_mig").BACKFILL
    people = {name: uuid.uuid4() for name in ("signed_in", "chat_only", "never", "service")}
    async with migrator.connect() as conn, conn.begin() as tx:
        await conn.execute(
            sa.text(
                "ALTER TABLE platform.memberships DROP CONSTRAINT fk_memberships_tenant_members"
            )
        )
        for name, user in people.items():
            service = name == "service"
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                    " VALUES (:u, :s, :n, :k, :o)"
                ),
                {
                    "u": user,
                    "s": f"bf-{user}",
                    "n": name,
                    "k": "service" if service else "human",
                    "o": world.tenant_a if service else None,
                },
            )
            for ws in (world.ws1, world.ws2):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                        " VALUES (gen_random_uuid(), :t, :w, :u)"
                    ),
                    {"t": world.tenant_a, "w": ws, "u": user},
                )
        for name, provider in (("signed_in", "oidc"), ("chat_only", "zalo")):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.external_identities (id, user_id, issuer, subject,"
                    " provider) VALUES (gen_random_uuid(), :u, :i, :s, :p)"
                ),
                {"u": people[name], "i": provider, "s": f"bf-{uuid.uuid4()}", "p": provider},
            )
        await conn.execute(sa.text(backfill))
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT user_id, tenant_id, status FROM platform.tenant_members"
                    " WHERE user_id = ANY(:us)"
                ),
                {"us": list(people.values())},
            )
        ).all()
        await tx.rollback()
    by_user = {r.user_id: (r.tenant_id, r.status) for r in rows}
    assert len(rows) == 4
    assert by_user == {
        people["signed_in"]: (world.tenant_a, "active"),
        people["chat_only"]: (world.tenant_a, "invited"),
        people["never"]: (world.tenant_a, "invited"),
        people["service"]: (world.tenant_a, "active"),
    }


async def test_a_grant_writes_an_invited_member_who_is_active_at_next_sign_in(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    repo = SqlMembershipAdminRepository(async_sessionmaker(app_engine, expire_on_commit=False))
    grant = GrantMembershipHandler(
        repo, ScopeAuthorizationService(), SystemClock(), Uuid4Generator()
    )
    admin = await context_of(app_engine, world, "requester", world.tenant_a, world.ws1)
    await grant.handle(
        admin,
        GrantMembership(
            email=world.email("not_staff"),
            workspace_id=world.ws1,
            role_keys=frozenset({f"probe_plain_{world.tag}"}),
        ),
    )
    person = world.users["not_staff"]
    assert await _status(migrator, world.tenant_a, person) == "invited"

    view = await _bootstrap(app_engine, world).bootstrap(_seeded(world, "not_staff"))
    assert await _status(migrator, world.tenant_a, person) == "active"
    assert [m.workspace_id for m in view.memberships] == [world.ws1]


async def test_the_provisioners_grant_writes_an_invited_member(
    world: SupportWorld, migrator: AsyncEngine, provisioner_engine: AsyncEngine
) -> None:
    repo = SqlProvisioningRepository(async_sessionmaker(provisioner_engine, expire_on_commit=False))
    person = world.users["not_staff"]
    await repo.assign_tenant_owner(tenant_id=world.tenant_a, workspace_id=world.ws2, user_id=person)
    assert await _status(migrator, world.tenant_a, person) == "invited"
    # A second grant into the other workspace keeps the row as it is.
    await _set_status(migrator, world.tenant_a, person, "suspended")
    await repo.assign_tenant_owner(tenant_id=world.tenant_a, workspace_id=world.ws1, user_id=person)
    assert await _status(migrator, world.tenant_a, person) == "suspended"


async def test_the_default_membership_of_a_first_sign_in_is_active(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    view = await _bootstrap(app_engine, world, auto_provision_default_membership=True).bootstrap(
        _Identity(subject=f"auto-{uuid.uuid4()}", email=None)
    )
    assert await _status(migrator, world.tenant_a, view.principal_id) == "active"
    assert [m.workspace_id for m in view.memberships] == [world.ws1]


async def test_the_operators_admin_script_writes_an_active_member(
    world: SupportWorld, db_urls: DatabaseUrls, migrator: AsyncEngine
) -> None:
    script = _load("scripts/grant_platform_admin.py", "grant_platform_admin")
    async with migrator.connect() as conn:
        slug = await conn.scalar(
            sa.text("SELECT slug FROM platform.tenants WHERE id = :t"), {"t": world.tenant_a}
        )
    assert await script._run(db_urls.migrator, world.email("not_staff"), slug) == 0
    assert await _status(migrator, world.tenant_a, world.users["not_staff"]) == "active"


async def test_the_seed_writes_active_members_and_a_reseed_restores_them(
    db_urls: DatabaseUrls, migrator: AsyncEngine
) -> None:
    await seed_test_env(db_urls.migrator)
    async with migrator.begin() as conn:
        tenant, user = (
            await conn.execute(
                sa.text(
                    "SELECT m.tenant_id, m.user_id FROM platform.memberships m"
                    " JOIN platform.users u ON u.id = m.user_id WHERE u.subject = 'dev|an.nguyen'"
                    " LIMIT 1"
                )
            )
        ).one()
    await _set_status(migrator, tenant, user, "suspended")
    await seed_test_env(db_urls.migrator)
    assert await _status(migrator, tenant, user) == "active"


# ---- R4.1: status_changed_at follows the status ---------------------------------


async def _changed_at(migrator: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID) -> object:
    async with migrator.connect() as conn:
        return await conn.scalar(
            sa.text(
                "SELECT status_changed_at FROM platform.tenant_members"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"t": tenant, "u": user},
        )


async def test_status_changed_at_moves_only_when_the_status_changes(
    world: SupportWorld, migrator: AsyncEngine
) -> None:
    tenant, person = world.tenant_a, world.users["plain"]
    first = await _changed_at(migrator, tenant, person)

    await _set_status(migrator, tenant, person, "active")  # the same value
    assert await _changed_at(migrator, tenant, person) == first

    await _set_status(migrator, tenant, person, "suspended")
    moved = await _changed_at(migrator, tenant, person)
    assert moved > first  # type: ignore[operator]

    stated = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_members SET status = 'active',"
                " status_changed_at = :at"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"at": stated, "t": tenant, "u": person},
        )
        kept = await conn.scalar(
            sa.text(
                "SELECT status_changed_at = :at FROM platform.tenant_members"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"at": stated, "t": tenant, "u": person},
        )
    assert kept is True


# ---- R4.2 (OP4): the company row takes its memberships with it --------------------


async def test_deleting_a_company_member_deletes_every_membership_in_one_statement(
    world: SupportWorld, migrator: AsyncEngine
) -> None:
    person, _ = await _new_person(migrator, "two_ws")
    async with migrator.begin() as conn:
        await add_tenant_member(conn, world.tenant_a, person)
        for ws in (world.ws1, world.ws2):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                    " VALUES (gen_random_uuid(), :t, :w, :u)"
                ),
                {"t": world.tenant_a, "w": ws, "u": person},
            )
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": world.tenant_a, "u": person},
        )
        left = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.memberships WHERE user_id = :u"), {"u": person}
        )
    assert left == 0


# ---- R4.3 (OP5): only an active member passes the AccessContext door ---------------


async def test_a_suspended_or_missing_member_gets_no_access_in_any_workspace(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    person = world.users["not_staff"]
    async with migrator.begin() as conn:
        await add_tenant_member(conn, world.tenant_a, person)
        for ws in (world.ws1, world.ws2):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys) VALUES (gen_random_uuid(), :t, :w, :u, '[\"member\"]')"
                ),
                {"t": world.tenant_a, "w": ws, "u": person},
            )
    lookup = SqlMembershipLookup(async_sessionmaker(app_engine, expire_on_commit=False))
    subject = f"sg-{person}"
    for ws in (world.ws1, world.ws2):
        assert await lookup.find_access(subject, ISSUER, world.tenant_a, ws) is not None

    for status in ("suspended", "invited"):
        await _set_status(migrator, world.tenant_a, person, status)
        for ws in (world.ws1, world.ws2):
            assert await lookup.find_access(subject, ISSUER, world.tenant_a, ws) is None, status
            # The linked-chat door shares the join (`_access_in`).
            linked = await lookup.find_linked_access(
                person, world.tenant_a, ws, frozenset({"x.read"})
            )
            assert linked is None, status

    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": world.tenant_a, "u": person},
        )
    assert await lookup.find_access(subject, ISSUER, world.tenant_a, world.ws1) is None


# ---- R4.4: an invitation writes an invited member, or nothing ------------------------


async def test_an_invitation_writes_an_invited_member_and_a_refused_one_writes_none(
    world: SupportWorld,
    app_engine: AsyncEngine,
    migrator: AsyncEngine,
    provisioner_engine: AsyncEngine,
) -> None:
    admin = await context_of(app_engine, world, "requester", world.tenant_a, world.ws1)
    roles = (WorkspaceRoles(world.ws1, frozenset({f"probe_plain_{world.tag}"})),)
    ref = await _members(app_engine).invite(
        admin,
        InviteMember(
            display_name="Người mới", email=f"fresh-{world.tag}@status.test", memberships=roles
        ),
    )
    assert await _status(migrator, world.tenant_a, ref.user_id) == "invited"

    # Refused inside the transaction, after the company row was written: the
    # membership trigger refuses support staff, and the row goes with it.
    await provisioning(provisioner_engine, FixedClock(datetime.now(UTC))).add_support_staff(
        world.operator, email=world.email("other_staff"), note=None
    )
    with pytest.raises(ConflictError):
        await _members(app_engine).invite(
            admin,
            InviteMember(
                display_name="Support staff", email=world.email("other_staff"), memberships=roles
            ),
        )
    assert await _status(migrator, world.tenant_a, world.users["other_staff"]) is None


async def test_a_person_signed_in_elsewhere_is_invited_then_active_at_next_bootstrap(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    person = world.users["b_granter"]
    await _bootstrap(app_engine, world).bootstrap(_seeded(world, "b_granter"))
    admin = await context_of(app_engine, world, "requester", world.tenant_a, world.ws1)
    await _members(app_engine).invite(
        admin,
        InviteMember(
            display_name="Bê Granter",
            email=world.email("b_granter"),
            memberships=(WorkspaceRoles(world.ws1, frozenset({f"probe_plain_{world.tag}"})),),
        ),
    )
    assert await _status(migrator, world.tenant_a, person) == "invited"

    view = await _bootstrap(app_engine, world).bootstrap(_seeded(world, "b_granter"))
    assert await _status(migrator, world.tenant_a, person) == "active"
    assert {m.workspace_id for m in view.memberships} == {world.ws1, world.ws_b}


# ---- R4.5: the first sign-in activates, never from suspended -------------------------


async def test_the_first_sign_in_activates_in_the_transaction_that_links_the_identity(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    admin = await context_of(app_engine, world, "requester", world.tenant_a, world.ws1)
    email = f"first-{world.tag}@status.test"
    ref = await _members(app_engine).invite(
        admin,
        InviteMember(
            display_name="Lần đầu",
            email=email,
            memberships=(WorkspaceRoles(world.ws1, frozenset({f"probe_plain_{world.tag}"})),),
        ),
    )
    view = await _bootstrap(app_engine, world).bootstrap(
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email, issuer=OTHER_IDP)
    )
    assert view.principal_id == ref.user_id
    async with migrator.connect() as conn:
        member_tx, identity_tx = (
            await conn.execute(
                sa.text(
                    "SELECT (SELECT xmin::text FROM platform.tenant_members"
                    "          WHERE tenant_id = :t AND user_id = :u AND status = 'active'),"
                    "       (SELECT xmin::text FROM platform.external_identities"
                    "          WHERE user_id = :u AND issuer = :i)"
                ),
                {"t": world.tenant_a, "u": ref.user_id, "i": OTHER_IDP},
            )
        ).one()
    assert member_tx is not None and member_tx == identity_tx


async def test_sign_in_activates_an_invitation_and_leaves_a_suspension(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """Invited in A, suspended in B: A becomes active, B stays suspended and
    lists none of its workspaces (R4.5, R4.8)."""
    person = world.users["b_granter"]
    await _set_status(migrator, world.tenant_b, person, "suspended")
    async with migrator.begin() as conn:
        await add_tenant_member(conn, world.tenant_a, person, "invited")
        await conn.execute(
            sa.text(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                " VALUES (gen_random_uuid(), :t, :w, :u)"
            ),
            {"t": world.tenant_a, "w": world.ws2, "u": person},
        )
    view = await _bootstrap(app_engine, world).bootstrap(_seeded(world, "b_granter"))
    assert await _status(migrator, world.tenant_a, person) == "active"
    assert await _status(migrator, world.tenant_b, person) == "suspended"
    assert [m.workspace_id for m in view.memberships] == [world.ws2]


async def test_a_connection_bound_only_to_a_principal_changes_no_status(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    person = world.users["plain"]
    await _set_status(migrator, world.tenant_a, person, "suspended")
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.principal_id', :p, true)"), {"p": str(person)}
        )
        seen = await conn.scalar(sa.text("SELECT count(*) FROM platform.tenant_members"))
        changed = (
            await conn.execute(
                sa.text("UPDATE platform.tenant_members SET status = 'active' WHERE user_id = :u"),
                {"u": person},
            )
        ).rowcount
    assert seen == 1, "the person reads their own row"
    assert changed == 0
    assert await _status(migrator, world.tenant_a, person) == "suspended"


# ---- R4.7 (OP6): a company's members are its own ---------------------------------------


async def test_a_connection_reads_only_its_tenants_members_or_its_own_rows(
    world: SupportWorld, app_engine: AsyncEngine
) -> None:
    async def count(settings: dict[str, str], where: str = "", **params: object) -> int:
        async with app_engine.begin() as conn:
            for key, value in settings.items():
                await conn.execute(
                    sa.text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value}
                )
            return int(
                await conn.scalar(
                    sa.text(f"SELECT count(*) FROM platform.tenant_members {where}"), params
                )
                or 0
            )

    b_where = "WHERE tenant_id = :b"
    a = {"app.tenant_id": str(world.tenant_a)}
    assert await count(a, b_where, b=world.tenant_b) == 0
    assert await count({}, b_where, b=world.tenant_b) == 0
    assert await count({}) == 0
    assert await count(a, "WHERE tenant_id = :a", a=world.tenant_a) == 6
    me = {"app.principal_id": str(world.users["granter"])}
    assert await count(me) == 1
    assert await count(me, "WHERE user_id <> :u", u=world.users["granter"]) == 0


# ---- R4.8 (OP7): bootstrap lists only companies where the person is active -------------


async def test_bootstrap_drops_the_companies_where_the_person_is_suspended(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    person = world.users["b_granter"]
    async with migrator.begin() as conn:
        await add_tenant_member(conn, world.tenant_a, person)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                " VALUES (gen_random_uuid(), :t, :w, :u)"
            ),
            {"t": world.tenant_a, "w": world.ws1, "u": person},
        )
    await _set_status(migrator, world.tenant_a, person, "suspended")
    view = await _bootstrap(app_engine, world).bootstrap(_seeded(world, "b_granter"))
    assert [m.workspace_id for m in view.memberships] == [world.ws_b]


# ---- R5.1: both member lists read the column -------------------------------------------


async def test_both_member_lists_report_the_company_status(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    await _set_status(migrator, world.tenant_a, world.users["plain"], "suspended")
    await _set_status(migrator, world.tenant_a, world.users["narrow"], "invited")
    async with migrator.connect() as conn:
        column = {
            r.user_id: r.status
            for r in await conn.execute(
                sa.text("SELECT user_id, status FROM platform.tenant_members WHERE tenant_id = :t"),
                {"t": world.tenant_a},
            )
        }
    admin = await context_of(app_engine, world, "requester", world.tenant_a, world.ws1)
    listed = {m.user_id: m.status for m in await _members(app_engine).list_members(admin)}
    directory = SqlWorkspaceDirectory(async_sessionmaker(app_engine, expire_on_commit=False))
    in_ws1 = {m.user_id: m.status for m in await directory.list_members(admin)}

    assert listed == column
    assert in_ws1 == {u: s for u, s in column.items() if u != world.users["granter_ws2"]}
    assert {listed[world.users["plain"]], listed[world.users["narrow"]]} == {
        "suspended",
        "invited",
    }


# ---- G2: removing the last membership keeps the company member -------------------------


async def test_revoking_the_last_membership_keeps_the_company_member(
    world: SupportWorld, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    repo = SqlMembershipAdminRepository(async_sessionmaker(app_engine, expire_on_commit=False))
    revoke = RevokeMembershipHandler(
        repo, ScopeAuthorizationService(), SystemClock(), Uuid4Generator()
    )
    admin = await context_of(app_engine, world, "requester", world.tenant_a, world.ws1)
    person = world.users["plain"]
    await revoke.handle(admin, RevokeMembership(user_id=person, workspace_id=world.ws1))
    async with migrator.connect() as conn:
        left = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.memberships WHERE user_id = :u"), {"u": person}
        )
    assert left == 0
    assert await _status(migrator, world.tenant_a, person) == "active"


async def test_a_status_outside_the_three_is_refused(
    world: SupportWorld, migrator: AsyncEngine
) -> None:
    with pytest.raises(IntegrityError, match="ck_tenant_members_status"):
        await _set_status(migrator, world.tenant_a, world.users["plain"], "removed")
