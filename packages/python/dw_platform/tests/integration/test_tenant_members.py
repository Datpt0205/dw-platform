# ruff: noqa: F811  (`provisioner_engine` is a fixture imported from test_provisioning)
"""Integration: everyone in a tenant, roles per workspace, invitations.

`dw_app` under RLS, PostgreSQL compose (tenant-members-and-invitations 01, as
tenant-rbac ticket 03 left it). TM1 (a role left out of the body is a
revocation the caller must be able to make, R6.1; no critical role carrying a
key the caller lacks handed out), TM2 (only the caller's tenant), TM3 (support
staff never members), TM4 (one email, one person), the first sign-in of an
invited person, and the Vietnamese name order. A role added is a proposal that
a second holder of `platform.roles.bind` confirms (R7.1).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from rbac_world import confirm_all, open_proposals
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from support_world import (
    ISSUER,
    SupportWorld,
    add_checker,
    build_world,
    checker_context,
    context_of,
    provisioning,
)
from test_provisioning import provisioner_engine  # noqa: F401  (a fixture, used by name)

from dw_kernel.errors import ConflictError, NotFoundError, PermissionDeniedError
from dw_kernel.ports import FixedClock, SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.directory import SqlWorkspaceDirectory
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.role_assignments_repo import SqlRoleAssignmentRepository
from dw_platform.adapters.persistence.tenant_members import SqlTenantMembersRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.role_assignments import (
    InviteMember,
    RoleAssignmentService,
    SetMemberships,
    WorkspaceRoles,
)
from dw_platform.application.tenant_members import TenantMember, TenantMembersService
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import assign, plant_membership, plant_person, plant_role

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Identity:
    subject: str
    email: str | None
    # An IdP that verified the address, as a corporate SSO does.
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


@pytest.fixture
def members(app_engine: AsyncEngine) -> TenantMembersService:
    return TenantMembersService(
        SqlTenantMembersRepository(async_sessionmaker(app_engine, expire_on_commit=False)),
        ScopeAuthorizationService(),
    )


@pytest.fixture
def roles(app_engine: AsyncEngine) -> RoleAssignmentService:
    return RoleAssignmentService(
        SqlRoleAssignmentRepository(async_sessionmaker(app_engine, expire_on_commit=False)),
        ScopeAuthorizationService(),
        SystemClock(),
        Uuid4Generator(),
    )


@pytest.fixture
async def checker(world: SupportWorld, migrator: AsyncEngine) -> AccessContext:
    """A second holder of `platform.roles.bind` in tenant A: without one a
    request that adds a role is refused 409 `no_checker_available`."""
    return checker_context(world, await add_checker(migrator, world))


async def _admin(app: AsyncEngine, w: SupportWorld) -> AccessContext:
    """`requester` holds `org_admin` in ws1 of tenant A."""
    return await context_of(app, w, "requester", w.tenant_a, w.ws1)


async def _roles(migrator: AsyncEngine, user: uuid.UUID) -> dict[uuid.UUID, set[str]]:
    """Workspace -> the roles assigned there, every tenant, past RLS."""
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT m.workspace_id, r.key FROM platform.memberships m"
                    " LEFT JOIN platform.role_assignments a"
                    "   ON a.tenant_id = m.tenant_id AND a.membership_id = m.id"
                    " LEFT JOIN platform.tenant_roles r"
                    "   ON r.tenant_id = a.tenant_id AND r.id = a.role_id"
                    " WHERE m.user_id = :u"
                ),
                {"u": user},
            )
        ).all()
    found: dict[uuid.UUID, set[str]] = {}
    for row in rows:
        keys = found.setdefault(row.workspace_id, set())
        if row.key is not None:
            keys.add(row.key)
    return found


async def _place(
    migrator: AsyncEngine, w: SupportWorld, user: uuid.UUID, ws: uuid.UUID, roles: list[str]
) -> None:
    async with migrator.begin() as conn:
        await add_tenant_member(conn, w.tenant_a, user)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
                " VALUES (:id, :t, :ws, :u, CAST(:r AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "t": w.tenant_a,
                "ws": ws,
                "u": user,
                "r": "[" + ", ".join(f'"{r}"' for r in roles) + "]",
            },
        )


async def _audit(migrator: AsyncEngine, user: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT action, workspace_id FROM platform.audit_events"
                    " WHERE resource_type = 'membership' AND resource_id = :u"
                    " ORDER BY action, workspace_id"
                ),
                {"u": str(user)},
            )
        ).all()
    return [(row.action, row.workspace_id) for row in rows]


def _plain(w: SupportWorld) -> str:
    return f"probe_plain_{w.tag}"


# ---- TM2: only the caller's tenant ------------------------------------------


async def test_the_list_holds_this_tenant_only(
    world: SupportWorld, app_engine: AsyncEngine, members: TenantMembersService
) -> None:
    listed = {m.user_id: m for m in await members.list_members(await _admin(app_engine, world))}
    for name in ("granter", "granter2", "narrow", "requester", "plain", "granter_ws2"):
        assert world.users[name] in listed, name
    for name in ("b_granter", "c_granter", "staff", "not_staff"):
        assert world.users[name] not in listed, name
    ws2_member = listed[world.users["granter_ws2"]]
    assert [m.workspace_name for m in ws2_member.memberships] == ["Workspace 2"]
    plain = await context_of(app_engine, world, "plain", world.tenant_a, world.ws1)
    with pytest.raises(PermissionDeniedError):
        await members.list_members(plain)


async def test_another_tenants_person_or_workspace_is_not_found(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
    checker: AccessContext,
) -> None:
    admin = await _admin(app_engine, world)
    before_proposals = await open_proposals(migrator, world.tenant_a)
    with pytest.raises(NotFoundError):
        await roles.set_memberships(
            admin,
            SetMemberships(
                user_id=world.users["b_granter"],
                memberships=(WorkspaceRoles(world.ws1, frozenset({_plain(world)})),),
            ),
        )
    before = await _roles(migrator, world.users["plain"])
    with pytest.raises(NotFoundError):
        await roles.set_memberships(
            admin,
            SetMemberships(
                user_id=world.users["plain"],
                memberships=(
                    WorkspaceRoles(world.ws1, frozenset({_plain(world)})),
                    WorkspaceRoles(world.ws_b, frozenset({_plain(world)})),
                ),
            ),
        )
    assert await _roles(migrator, world.users["plain"]) == before
    assert await _roles(migrator, world.users["b_granter"]) == {world.ws_b: {world.granter_role}}
    assert await open_proposals(migrator, world.tenant_a) == before_proposals


# ---- TM1: a role is removed only by one who could hand it out ----------------


async def _binder(migrator: AsyncEngine, w: SupportWorld) -> AccessContext:
    """A member of tenant A who may place people and bind roles that are not
    critical (`platform.members.*`, `platform.roles.bind`), and holds nothing of
    `org_admin`'s other keys."""
    async with migrator.begin() as conn:
        person = await plant_person(conn, w.tenant_a)
        membership = await plant_membership(conn, w.tenant_a, w.ws1, person)
        role = await plant_role(
            conn,
            w.tenant_a,
            f"probe_binder_{w.tag}",
            {
                "platform.members.read": "tenant",
                "platform.members.write": "tenant",
                "platform.roles.bind": "tenant",
            },
        )
        await assign(conn, w.tenant_a, w.ws1, membership, role)
    return AccessContext(
        tenant_id=w.tenant_a,
        workspace_id=w.ws1,
        principal_id=person,
        roles=frozenset({f"probe_binder_{w.tag}"}),
        scopes=frozenset(
            {"platform.members.read", "platform.members.write", "platform.roles.bind"}
        ),
        plan_id="professional",
    )


async def test_a_role_left_out_is_revoked_only_by_one_who_could_hand_it_out(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
    checker: AccessContext,
) -> None:
    """R6.1: a role in the membership that the body leaves out is a revocation,
    judged by the hold rule. `org_admin` is critical, so `platform.roles.bind`
    alone does not cover it: 403 `rbac_escalation` and nothing changes, the
    role added beside it not proposed either. An org admin, who holds it,
    removes it at once; the role added is a proposal."""
    person = world.users["not_staff"]
    await _place(migrator, world, person, world.ws1, ["org_admin", _plain(world)])
    before_proposals = await open_proposals(migrator, world.tenant_a)
    body = SetMemberships(
        user_id=person,
        memberships=(WorkspaceRoles(world.ws1, frozenset({world.granter_role})),),
    )
    with pytest.raises(PermissionDeniedError) as refused:
        await roles.set_memberships(await _binder(migrator, world), body)
    assert refused.value.details["reason_code"] == "rbac_escalation"
    keys = refused.value.details["keys"]
    assert isinstance(keys, list) and "platform.sod_waivers.write:tenant" in keys
    assert await _roles(migrator, person) == {world.ws1: {"org_admin", _plain(world)}}
    assert await open_proposals(migrator, world.tenant_a) == before_proposals

    outcome = await roles.set_memberships(await _admin(app_engine, world), body)
    assert sorted(r.role_key for r in outcome.applied) == sorted(["org_admin", _plain(world)])
    assert await _roles(migrator, person) == {world.ws1: set()}
    await confirm_all(app_engine, checker, outcome.proposals)
    assert await _roles(migrator, person) == {world.ws1: {world.granter_role}}


async def test_an_org_admin_cannot_hand_out_a_critical_role_beyond_their_own(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
    checker: AccessContext,
) -> None:
    """A critical role carrying `platform.roles.write`, which `org_admin` lacks:
    403 `rbac_escalation` naming the key, and the whole request refused, the
    harmless role in the other workspace not proposed either (ADR-0104 decision
    10)."""
    writer = f"probe_writer_{world.tag}"
    async with migrator.begin() as conn:
        await plant_role(conn, world.tenant_a, writer, {"platform.roles.write": "tenant"})
    person = world.users["plain"]
    before = await _roles(migrator, person)
    before_proposals = await open_proposals(migrator, world.tenant_a)
    with pytest.raises(PermissionDeniedError) as refused:
        await roles.set_memberships(
            await _admin(app_engine, world),
            SetMemberships(
                user_id=person,
                memberships=(
                    WorkspaceRoles(world.ws2, frozenset({_plain(world)})),
                    WorkspaceRoles(world.ws1, frozenset({_plain(world), writer})),
                ),
            ),
        )
    assert refused.value.details["reason_code"] == "rbac_escalation"
    assert refused.value.details["keys"] == ["platform.roles.write:tenant"]
    assert await _roles(migrator, person) == before
    assert await open_proposals(migrator, world.tenant_a) == before_proposals


async def test_an_unknown_role_is_named(
    world: SupportWorld, app_engine: AsyncEngine, roles: RoleAssignmentService
) -> None:
    with pytest.raises(NotFoundError) as refused:
        await roles.set_memberships(
            await _admin(app_engine, world),
            SetMemberships(
                user_id=world.users["plain"],
                memberships=(WorkspaceRoles(world.ws1, frozenset({"no_such_role"})),),
            ),
        )
    assert refused.value.details["roles"] == ["no_such_role"]


async def test_a_workspace_left_out_is_removed_and_audited(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
) -> None:
    """Only narrows: applied at once by one person, nothing proposed."""
    person = world.users["not_staff"]
    await _place(migrator, world, person, world.ws1, [_plain(world)])
    await _place(migrator, world, person, world.ws2, [_plain(world)])
    outcome = await roles.set_memberships(
        await _admin(app_engine, world),
        SetMemberships(
            user_id=person,
            memberships=(WorkspaceRoles(world.ws1, frozenset({_plain(world)})),),
        ),
    )
    assert [(r.workspace_id, r.role_key) for r in outcome.applied] == [(world.ws2, _plain(world))]
    assert outcome.proposals == ()
    assert await _roles(migrator, person) == {world.ws1: {_plain(world)}}
    assert await _audit(migrator, person) == [("platform.membership.revoke", world.ws2)]


# ---- invitations --------------------------------------------------------------


async def test_an_invited_person_signs_in_and_finds_their_workspace(
    world: SupportWorld,
    app_engine: AsyncEngine,
    members: TenantMembersService,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
    checker: AccessContext,
) -> None:
    admin = await _admin(app_engine, world)
    email = f"newcomer-{world.tag}@support.test"
    ref, outcome = await roles.invite(
        admin,
        InviteMember(
            display_name="Người Mới",
            email=email.upper(),
            memberships=(WorkspaceRoles(world.ws1, frozenset({_plain(world)})),),
        ),
    )
    assert ref.email == email  # lower-cased
    listed = {m.user_id: m for m in await members.list_members(admin)}
    assert listed[ref.user_id].status == "invited"
    # Every role of an invitation is a proposal (R7.1): placed, holding nothing.
    assert len(outcome.proposals) == 1
    assert await _roles(migrator, ref.user_id) == {world.ws1: set()}
    await confirm_all(app_engine, checker, outcome.proposals)
    assert await _roles(migrator, ref.user_id) == {world.ws1: {_plain(world)}}
    assert await _audit(migrator, ref.user_id) == [("platform.member.invited", world.ws1)]
    directory = SqlWorkspaceDirectory(async_sessionmaker(app_engine, expire_on_commit=False))
    in_ws1 = {m.user_id: m.status for m in await directory.list_members(admin)}
    assert in_ws1[ref.user_id] == "invited"
    # The column, not a sign-in (R5.1): seeded as an active member of the company.
    assert in_ws1[world.users["requester"]] == "active"

    # The first sign-in, from an IdP that verified the same email.
    view = await SqlIdentityBootstrap(
        session_factory=async_sessionmaker(app_engine, expire_on_commit=False),
        default_tenant_id=world.tenant_a,
        default_workspace_id=world.ws1,
    ).bootstrap(_Identity(subject=f"kc-{uuid.uuid4()}", email=email))
    assert view.principal_id == ref.user_id
    assert [m.workspace_id for m in view.memberships] == [world.ws1]
    listed = {m.user_id: m for m in await members.list_members(admin)}
    assert listed[ref.user_id].status == "active"
    assert {m.user_id: m.status for m in await directory.list_members(admin)}[
        ref.user_id
    ] == "active"


async def test_an_email_already_in_the_tenant_is_refused(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    checker: AccessContext,
) -> None:
    with pytest.raises(ConflictError) as refused:
        await roles.invite(
            await _admin(app_engine, world),
            InviteMember(
                display_name="Someone",
                email=world.email("plain"),
                memberships=(WorkspaceRoles(world.ws2, frozenset({_plain(world)})),),
            ),
        )
    assert refused.value.details["reason_code"] == "member_email_exists_in_tenant"


async def test_two_invitations_of_one_new_email_make_one_person(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
    checker: AccessContext,
) -> None:
    admin = await _admin(app_engine, world)
    email = f"twice-{world.tag}@support.test"
    command = InviteMember(
        display_name="Twice Invited",
        email=email,
        memberships=(WorkspaceRoles(world.ws1, frozenset({_plain(world)})),),
    )
    outcomes = await asyncio.gather(
        roles.invite(admin, command), roles.invite(admin, command), return_exceptions=True
    )
    conflicts = [o for o in outcomes if isinstance(o, ConflictError)]
    made = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(made) == 1 and len(conflicts) == 1, outcomes
    async with migrator.connect() as conn:
        assert (
            await conn.scalar(
                sa.text("SELECT count(*) FROM platform.users WHERE lower(email) = :e"), {"e": email}
            )
            == 1
        )


# ---- TM3: support staff never members ------------------------------------------


async def test_support_staff_are_refused_on_every_member_path(
    world: SupportWorld,
    app_engine: AsyncEngine,
    roles: RoleAssignmentService,
    migrator: AsyncEngine,
    provisioner_engine: AsyncEngine,
    checker: AccessContext,
) -> None:
    # A membership held before the person was listed: kept, but frozen.
    await _place(migrator, world, world.users["staff"], world.ws1, [_plain(world)])
    await provisioning(provisioner_engine, FixedClock(NOW)).add_support_staff(
        world.operator, email=world.email("staff"), note=None
    )
    admin = await _admin(app_engine, world)
    with pytest.raises(ConflictError) as refused:
        await roles.invite(
            admin,
            InviteMember(
                display_name="Support person",
                email=world.email("staff"),
                memberships=(WorkspaceRoles(world.ws2, frozenset({_plain(world)})),),
            ),
        )
    # Already a member here: that answer comes first.
    assert refused.value.details["reason_code"] == "member_email_exists_in_tenant"
    with pytest.raises(ConflictError) as refused:
        await roles.set_memberships(
            admin,
            SetMemberships(
                user_id=world.users["staff"],
                memberships=(
                    WorkspaceRoles(world.ws1, frozenset({_plain(world)})),
                    WorkspaceRoles(world.ws2, frozenset({_plain(world)})),
                ),
            ),
        )
    assert refused.value.details["reason_code"] == "support_staff_not_member"
    assert await _roles(migrator, world.users["staff"]) == {world.ws1: {_plain(world)}}

    # Listed staff who is a member nowhere here.
    await provisioning(provisioner_engine, FixedClock(NOW)).add_support_staff(
        world.operator, email=world.email("other_staff"), note=None
    )
    with pytest.raises(ConflictError) as refused:
        await roles.invite(
            admin,
            InviteMember(
                display_name="Other support",
                email=world.email("other_staff"),
                memberships=(WorkspaceRoles(world.ws1, frozenset({_plain(world)})),),
            ),
        )
    assert refused.value.details["reason_code"] == "support_staff_not_member"
    assert await _roles(migrator, world.users["other_staff"]) == {}


# ---- the order of names ------------------------------------------------------------


async def test_names_sort_the_vietnamese_way(
    world: SupportWorld,
    app_engine: AsyncEngine,
    members: TenantMembersService,
    migrator: AsyncEngine,
) -> None:
    names = ["Đạt Phùng", "Dũng Lê", "Zoe Ng", "Ánh Vũ", "An Trần", "Ê Bê"]
    for name in names:
        user = uuid.uuid4()
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, display_name) VALUES (:id, :s, :n)"
                ),
                {"id": user, "s": f"vi-{user}", "n": name},
            )
        await _place(migrator, world, user, world.ws2, [_plain(world)])
    listed: list[TenantMember] = await members.list_members(await _admin(app_engine, world))
    order = [m.display_name for m in listed if m.display_name in names]
    assert order == ["An Trần", "Ánh Vũ", "Dũng Lê", "Đạt Phùng", "Ê Bê", "Zoe Ng"]
