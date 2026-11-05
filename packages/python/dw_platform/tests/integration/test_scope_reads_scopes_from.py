"""Integration: `_STANDING` and `_HOLDERS` with `platform.scopes_in` in FROM
hold exactly what the select-list form held and what `platform.scopes_in`
answers (tenant-rbac/10, K1-K3).

Ticket 07 moved the AccessContext lookup's call into FROM, where PostgreSQL
inlines the SQL function; ticket 10 measured the two other reads of the
projection at D12 and moved them the same way. These tests pin that the move
changed nothing anyone holds: for the bench's three shapes (a person with roles
and a permission set in three workspaces, an owner, a plain member), every
membership reads the same scopes in both forms and in the function, a whole
workspace lists the same people with the same scopes, nothing a person holds in
another tenant reaches either read, and a suspended member still reads as no
membership.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.adapters.identity.dev_token import DEV_ISSUER
from dw_platform.adapters.persistence.digital_workers_repo import (
    _STANDING,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.scope_holders import _HOLDERS, SqlScopeHolders
from dw_platform.application.access_context import AccessContext
from dw_platform.application.identity import context_from
from dw_platform.application.work_queue import WorkScope
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    scopes_in,
    unregister_key,
)

pytestmark = pytest.mark.integration

# The two reads as they stood before ticket 10, `platform.scopes_in` in the select
# list: the baseline the moved statements must equal, kept here verbatim.
_STANDING_SELECT_LIST = sa.text(
    """
    SELECT u.kind,
           ARRAY(SELECT platform.scopes_in(CAST(:t AS uuid), u.id, CAST(:w AS uuid))) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    JOIN platform.tenant_members tm
      ON tm.tenant_id = m.tenant_id AND tm.user_id = m.user_id AND tm.status = 'active'
    WHERE m.workspace_id = CAST(:w AS uuid) AND m.user_id = CAST(:u AS uuid)
    """
)
_HOLDERS_SELECT_LIST = sa.text(
    """
    SELECT m.user_id,
           ARRAY(SELECT platform.scopes_in(m.tenant_id, m.user_id, m.workspace_id)) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    WHERE m.tenant_id = CAST(:t AS uuid) AND m.workspace_id = CAST(:w AS uuid)
      AND (CAST(:u AS uuid) IS NULL OR m.user_id = CAST(:u AS uuid))
      AND (NOT CAST(:people AS boolean) OR u.kind = 'human')
    ORDER BY m.user_id
    """
)


@dataclass(frozen=True)
class Member:
    user_id: uuid.UUID
    # workspace -> membership
    memberships: dict[uuid.UUID, uuid.UUID]


@dataclass(frozen=True)
class World:
    a: PlantedTenant
    b: PlantedTenant
    keys: dict[str, str]
    heavy: Member
    owner: Member
    plain: Member
    suspended: uuid.UUID


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
async def world(migrator: AsyncEngine) -> AsyncIterator[World]:
    suffix = uuid.uuid4().hex[:10]
    keys = {
        "work": f"test.s{suffix}.work",
        "other": f"test.s{suffix}.other",
        "admin": f"test.s{suffix}.admin",
        "record": f"test.s{suffix}.record",
        "b_only": f"test.s{suffix}.bonly",
    }
    kinds = {"work": "workspace", "other": "workspace", "admin": "tenant", "record": "record"}
    async with migrator.begin() as conn:
        for name, key in keys.items():
            await register_key(conn, key, scope_kind=kinds.get(name, "tenant"))
        a = await plant_tenant(conn, workspaces=3)
        b = await plant_tenant(conn)
        member = await role_id(conn, a.tenant_id, "member")
        ws0, ws1, ws2 = a.workspaces

        # The heavy person: a role in each of two workspaces, a permission set in
        # a third, `member` everywhere (the bench's 30 roles in 10, made small).
        heavy = await plant_person(conn, a.tenant_id)
        heavy_at = {ws: await plant_membership(conn, a.tenant_id, ws, heavy) for ws in a.workspaces}
        role_a = await plant_role(
            conn, a.tenant_id, "r_standing_a", {keys["work"]: "workspace", keys["admin"]: "tenant"}
        )
        role_b = await plant_role(
            conn,
            a.tenant_id,
            "r_standing_b",
            {keys["other"]: "workspace", keys["record"]: "workspace"},
        )
        boost = await plant_role(
            conn, a.tenant_id, "p_standing", {keys["work"]: "workspace"}, kind="permission_set"
        )
        await assign(conn, a.tenant_id, ws0, heavy_at[ws0], role_a)
        await assign(conn, a.tenant_id, ws1, heavy_at[ws1], role_b)
        await assign(conn, a.tenant_id, ws2, heavy_at[ws2], boost)
        for ws, membership in heavy_at.items():
            await assign(conn, a.tenant_id, ws, membership, member)

        owner = await plant_person(conn, a.tenant_id)
        owner_at = await plant_membership(conn, a.tenant_id, ws0, owner)
        await assign(
            conn, a.tenant_id, ws0, owner_at, await role_id(conn, a.tenant_id, "tenant_owner")
        )

        plain = await plant_person(conn, a.tenant_id)
        plain_at = await plant_membership(conn, a.tenant_id, ws0, plain)
        await assign(conn, a.tenant_id, ws0, plain_at, member)

        # A member of ws0 the company has suspended, holding the heavy person's
        # ws0 role: a membership row and assignments, and no standing (K3).
        suspended = await plant_person(conn, a.tenant_id, status="suspended")
        suspended_at = await plant_membership(conn, a.tenant_id, ws0, suspended)
        await assign(conn, a.tenant_id, ws0, suspended_at, role_a)
        await assign(conn, a.tenant_id, ws0, suspended_at, member)

        # The same heavy person in tenant B, holding a key only B grants.
        await add_tenant_member(conn, b.tenant_id, heavy)
        heavy_in_b = await plant_membership(conn, b.tenant_id, b.main, heavy)
        role_in_b = await plant_role(
            conn, b.tenant_id, "r_standing_bonly", {keys["b_only"]: "tenant"}
        )
        await assign(conn, b.tenant_id, b.main, heavy_in_b, role_in_b)
    yield World(
        a=a,
        b=b,
        keys=keys,
        heavy=Member(heavy, heavy_at),
        owner=Member(owner, {ws0: owner_at}),
        plain=Member(plain, {ws0: plain_at}),
        suspended=suspended,
    )
    async with migrator.begin() as conn:
        for key in keys.values():
            await unregister_key(conn, key)


async def _rows(
    app: AsyncEngine,
    statement: sa.TextClause,
    tenant: uuid.UUID,
    workspace: uuid.UUID,
    values: Mapping[str, object],
) -> list[tuple[uuid.UUID | str, frozenset[str]]]:
    """`statement` as `dw_app`, bound to `tenant` and `workspace` the way
    `tenant_session` binds the modules' own transactions."""
    async with app.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.workspace_id', :w, true)"
            ),
            {"t": str(tenant), "w": str(workspace)},
        )
        found = await conn.execute(statement, dict(values))
        return [(row[0], frozenset(row.scopes)) for row in found]


async def _standing_rows(
    app: AsyncEngine, statement: sa.TextClause, t: uuid.UUID, w: uuid.UUID, u: uuid.UUID
) -> list[tuple[uuid.UUID | str, frozenset[str]]]:
    return await _rows(app, statement, t, w, {"t": str(t), "w": str(w), "u": str(u)})


async def _holders_rows(
    app: AsyncEngine,
    statement: sa.TextClause,
    t: uuid.UUID,
    w: uuid.UUID,
    u: uuid.UUID | None,
    *,
    people: bool,
) -> list[tuple[uuid.UUID | str, frozenset[str]]]:
    values = {"t": str(t), "w": str(w), "u": None if u is None else str(u), "people": people}
    return await _rows(app, statement, t, w, values)


async def _function(
    migrator: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID, workspace: uuid.UUID
) -> frozenset[str]:
    """`platform.scopes_in` read on its own, as the select-list form called it."""
    async with migrator.connect() as conn:
        return frozenset(await scopes_in(conn, tenant, user, workspace))


async def _context(app: AsyncEngine, user: uuid.UUID, t: uuid.UUID, w: uuid.UUID) -> AccessContext:
    """The access context sign-in builds: the real lookup."""
    lookup = SqlMembershipLookup(async_sessionmaker(app, expire_on_commit=False))
    access = await lookup.find_access(f"rbac-{user}", DEV_ISSUER, t, w)
    assert access is not None, (user, w)
    return context_from(access)


def _shape(world: World, shape: str) -> Member:
    found: Member = getattr(world, shape)
    return found


@pytest.mark.parametrize("shape", ["heavy", "owner", "plain"])
async def test_standing_holds_what_the_select_list_form_and_scopes_in_hold(
    app: AsyncEngine, migrator: AsyncEngine, world: World, shape: str
) -> None:
    """K1, `_STANDING`: every membership of each shape, the statement, the
    select-list form, the function and `standing` agree, and none is empty."""
    person = _shape(world, shape)
    t = world.a.tenant_id
    check = SqlDwMembershipCheck(async_sessionmaker(app, expire_on_commit=False))
    for workspace in person.memberships:
        expected = await _function(migrator, t, person.user_id, workspace)
        assert expected, (shape, workspace)
        new = await _standing_rows(app, _STANDING, t, workspace, person.user_id)
        old = await _standing_rows(app, _STANDING_SELECT_LIST, t, workspace, person.user_id)
        assert new == old == [("human", expected)], (shape, workspace)

        # Asked by the heavy person, a member of every workspace of A.
        caller = await _context(app, world.heavy.user_id, t, workspace)
        standing = await check.standing(caller, person.user_id)
        assert standing is not None and standing.scopes == expected, (shape, workspace)
        assert await check.is_person_in(WorkScope(t, workspace), person.user_id)


@pytest.mark.parametrize("shape", ["heavy", "owner", "plain"])
async def test_one_member_holds_what_the_select_list_form_and_scopes_in_hold(
    app: AsyncEngine, migrator: AsyncEngine, world: World, shape: str
) -> None:
    """K1, `_HOLDERS` for one member (`scopes_of`, `holds`): every membership of
    each shape, the same scopes in both forms, the function and the adapter."""
    person = _shape(world, shape)
    t = world.a.tenant_id
    holders = SqlScopeHolders(async_sessionmaker(app, expire_on_commit=False))
    for workspace in person.memberships:
        expected = await _function(migrator, t, person.user_id, workspace)
        new = await _holders_rows(app, _HOLDERS, t, workspace, person.user_id, people=False)
        old = await _holders_rows(
            app, _HOLDERS_SELECT_LIST, t, workspace, person.user_id, people=False
        )
        assert new == old == [(person.user_id, expected)], (shape, workspace)
        assert await holders.scopes_of(t, workspace, person.user_id) == expected
        for key in expected:
            assert await holders.holds(t, workspace, person.user_id, key)


async def test_a_whole_workspace_lists_the_same_people_with_the_same_scopes(
    app: AsyncEngine, world: World
) -> None:
    """K1, `_HOLDERS` for a whole workspace (`holding`): every workspace of A,
    people and not, the same members in the same order with the same scopes,
    and `holding` names exactly the members the select-list form says hold a key."""
    t = world.a.tenant_id
    holders = SqlScopeHolders(async_sessionmaker(app, expire_on_commit=False))
    for workspace in world.a.workspaces:
        for people in (False, True):
            new = await _holders_rows(app, _HOLDERS, t, workspace, None, people=people)
            old = await _holders_rows(app, _HOLDERS_SELECT_LIST, t, workspace, None, people=people)
            assert new == old, (workspace, people)
            assert new, workspace
        old = await _holders_rows(app, _HOLDERS_SELECT_LIST, t, workspace, None, people=True)
        for key in world.keys.values():
            expected = [user for user, scopes in old if key in scopes]
            assert await holders.holding(t, workspace, frozenset({key})) == expected, (
                workspace,
                key,
            )


async def test_the_heavy_person_holds_each_key_only_where_its_depth_reaches(
    app: AsyncEngine, world: World
) -> None:
    """K1, by hand and not only against the function: a workspace key at its
    anchor, a tenant key everywhere, a record key at every depth (R2.3, R2.4),
    through both moved statements."""
    k = world.keys
    t = world.a.tenant_id
    ws0, ws1, ws2 = world.a.workspaces
    planted = {k["work"], k["other"], k["admin"], k["record"]}
    expected = {
        ws0: {k["work"], k["admin"], k["record"]},
        ws1: {k["admin"], k["other"], k["record"]},
        ws2: {k["work"], k["admin"], k["record"]},
    }
    user = world.heavy.user_id
    holders = SqlScopeHolders(async_sessionmaker(app, expire_on_commit=False))
    for workspace in world.heavy.memberships:
        [(_kind, standing)] = await _standing_rows(app, _STANDING, t, workspace, user)
        assert standing & planted == expected[workspace], workspace
        assert await holders.scopes_of(t, workspace, user) & planted == expected[workspace]
    [(_kind, plain)] = await _standing_rows(app, _STANDING, t, ws0, world.plain.user_id)
    assert plain & planted == set()
    [(_kind, owner)] = await _standing_rows(app, _STANDING, t, ws0, world.owner.user_id)
    assert planted <= owner, "the owner holds every grantable key (R2.7)"


async def test_nothing_held_in_another_tenant_reaches_either_read(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    """K2: the same person in A and B. Read under each tenant, each read holds
    exactly that tenant's `platform.scopes_in`, not empty, its own key and none
    of the other's. Absence alone could not fail under RLS; equality can."""
    k = world.keys
    in_a = {k["work"], k["other"], k["admin"], k["record"]}
    user = world.heavy.user_id
    check = SqlDwMembershipCheck(async_sessionmaker(app, expire_on_commit=False))
    holders = SqlScopeHolders(async_sessionmaker(app, expire_on_commit=False))

    for workspace in world.heavy.memberships:
        expected_a = await _function(migrator, world.a.tenant_id, user, workspace)
        assert expected_a & in_a and k["b_only"] not in expected_a
        caller = await _context(app, user, world.a.tenant_id, workspace)
        standing = await check.standing(caller, user)
        assert standing is not None and standing.scopes == expected_a, workspace
        assert await holders.scopes_of(world.a.tenant_id, workspace, user) == expected_a
        assert not await holders.holds(world.a.tenant_id, workspace, user, k["b_only"])
        assert user not in await holders.holding(
            world.a.tenant_id, workspace, frozenset({k["b_only"]})
        )

    expected_b = await _function(migrator, world.b.tenant_id, user, world.b.main)
    assert k["b_only"] in expected_b and not expected_b & in_a
    caller_b = await _context(app, user, world.b.tenant_id, world.b.main)
    standing_b = await check.standing(caller_b, user)
    assert standing_b is not None and standing_b.scopes == expected_b
    assert await holders.scopes_of(world.b.tenant_id, world.b.main, user) == expected_b
    assert await holders.holding(world.b.tenant_id, world.b.main, frozenset({k["b_only"]})) == [
        user
    ]
    assert await holders.holding(world.b.tenant_id, world.b.main, frozenset(in_a)) == []


async def test_a_suspended_member_still_has_no_standing(app: AsyncEngine, world: World) -> None:
    """K3: a suspended member of ws0 holding a role there reads as no membership,
    in the moved statement as in the select-list form."""
    t = world.a.tenant_id
    ws0 = world.a.main
    user = world.suspended
    assert await _standing_rows(app, _STANDING, t, ws0, user) == []
    assert await _standing_rows(app, _STANDING_SELECT_LIST, t, ws0, user) == []
    check = SqlDwMembershipCheck(async_sessionmaker(app, expire_on_commit=False))
    caller = await _context(app, world.owner.user_id, t, ws0)
    assert await check.standing(caller, user) is None
    assert not await check.is_person_in(WorkScope(t, ws0), user)
