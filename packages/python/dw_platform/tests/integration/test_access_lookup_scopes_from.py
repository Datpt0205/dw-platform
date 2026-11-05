"""Integration: the AccessContext lookup with `platform.scopes_in` in FROM holds
exactly what `platform.scopes_in` answers (tenant-rbac/07, K1, K2).

discovery/08 found the lookup paying 3-10x `platform.effective_grants` because
the set-returning call sat in a SELECT list, where PostgreSQL does not inline
it; ticket 07 moved it into FROM. These tests pin that the move changed nothing
anyone holds: for the bench's three shapes (a person with roles and a
permission set in three workspaces, an owner, a plain member), every membership
reads the same scopes as the function, and nothing a person holds in another
tenant reaches the lookup.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.adapters.identity.dev_token import DEV_ISSUER
from dw_platform.adapters.persistence.membership_lookup import _HELD, SqlMembershipLookup
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    grants_of,
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
    # The heavy person's membership in tenant B.
    heavy_in_b: uuid.UUID


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
        "work": f"test.k{suffix}.work",
        "other": f"test.k{suffix}.other",
        "admin": f"test.k{suffix}.admin",
        "record": f"test.k{suffix}.record",
        "b_only": f"test.k{suffix}.bonly",
    }
    kinds = {"work": "workspace", "other": "workspace", "admin": "tenant", "record": "record"}
    async with migrator.begin() as conn:
        for name, key in keys.items():
            await register_key(conn, key, scope_kind=kinds.get(name, "tenant"))
        a = await plant_tenant(conn, workspaces=3)
        b = await plant_tenant(conn)
        member = await role_id(conn, a.tenant_id, "member")

        # The heavy person: a role in each of two workspaces, a permission set in
        # a third, `member` everywhere (the bench's 30 roles in 10, made small).
        heavy = await plant_person(conn, a.tenant_id)
        heavy_at = {ws: await plant_membership(conn, a.tenant_id, ws, heavy) for ws in a.workspaces}
        role_a = await plant_role(
            conn, a.tenant_id, "r_lookup_a", {keys["work"]: "workspace", keys["admin"]: "tenant"}
        )
        role_b = await plant_role(
            conn,
            a.tenant_id,
            "r_lookup_b",
            {keys["other"]: "workspace", keys["record"]: "workspace"},
        )
        boost = await plant_role(
            conn, a.tenant_id, "p_lookup", {keys["work"]: "workspace"}, kind="permission_set"
        )
        ws0, ws1, ws2 = a.workspaces
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

        # The same heavy person in tenant B, holding a key only B grants.
        await add_tenant_member(conn, b.tenant_id, heavy)
        heavy_in_b = await plant_membership(conn, b.tenant_id, b.main, heavy)
        role_in_b = await plant_role(
            conn, b.tenant_id, "r_lookup_bonly", {keys["b_only"]: "tenant"}
        )
        await assign(conn, b.tenant_id, b.main, heavy_in_b, role_in_b)
    yield World(
        a=a,
        b=b,
        keys=keys,
        heavy=Member(heavy, heavy_at),
        owner=Member(owner, {ws0: owner_at}),
        plain=Member(plain, {ws0: plain_at}),
        heavy_in_b=heavy_in_b,
    )
    async with migrator.begin() as conn:
        for key in keys.values():
            await unregister_key(conn, key)


async def _held(
    app: AsyncEngine,
    tenant: uuid.UUID,
    user: uuid.UUID,
    workspace: uuid.UUID,
    membership: uuid.UUID,
) -> sa.Row[tuple[object, ...]]:
    """The lookup's own statement, as `dw_app` bound to `tenant`, as `_access_in` runs it."""
    async with app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        return (
            await conn.execute(
                _HELD, {"t": str(tenant), "u": str(user), "w": str(workspace), "m": str(membership)}
            )
        ).one()


async def _reference(
    migrator: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID, workspace: uuid.UUID
) -> tuple[set[str], set[tuple[str, str]]]:
    """What the database's functions answer, read on their own: `platform.scopes_in`
    called as head called it, and `platform.effective_grants`."""
    async with migrator.connect() as conn:
        return (
            await scopes_in(conn, tenant, user, workspace),
            await grants_of(conn, tenant, user),
        )


def _lookup(app: AsyncEngine) -> SqlMembershipLookup:
    return SqlMembershipLookup(async_sessionmaker(app, expire_on_commit=False))


@pytest.mark.parametrize("shape", ["heavy", "owner", "plain"])
async def test_every_membership_holds_exactly_what_scopes_in_answers(
    app: AsyncEngine, migrator: AsyncEngine, world: World, shape: str
) -> None:
    """K1: scopes, grants and the AccessContext of every membership of each shape."""
    person: Member = getattr(world, shape)
    t = world.a.tenant_id
    for workspace, membership in person.memberships.items():
        expected_scopes, expected_grants = await _reference(migrator, t, person.user_id, workspace)
        held = await _held(app, t, person.user_id, workspace, membership)
        assert set(held.scopes) == expected_scopes, (shape, workspace)
        assert len(held.scopes) == len(expected_scopes), "the projection is DISTINCT"
        assert {(key, depth) for key, depth, _anchor in held.grants} == expected_grants

        access = await _lookup(app).find_access(f"rbac-{person.user_id}", DEV_ISSUER, t, workspace)
        assert access is not None, (shape, workspace)
        assert access.scopes == frozenset(expected_scopes)
        assert {(g.key, g.depth) for g in access.grants} == expected_grants


async def test_the_heavy_person_holds_each_key_only_where_its_depth_reaches(
    app: AsyncEngine, world: World
) -> None:
    """K1, by hand and not only against the function: a workspace key at its anchor,
    a tenant key everywhere, a record key at every depth (R2.3, R2.4)."""
    k = world.keys
    ws0, ws1, ws2 = world.a.workspaces
    planted = {k["work"], k["other"], k["admin"], k["record"]}
    expected = {
        ws0: {k["work"], k["admin"], k["record"]},
        ws1: {k["admin"], k["other"], k["record"]},
        ws2: {k["work"], k["admin"], k["record"]},
    }
    for workspace, membership in world.heavy.memberships.items():
        held = await _held(app, world.a.tenant_id, world.heavy.user_id, workspace, membership)
        assert set(held.scopes) & planted == expected[workspace], workspace

    owner_ws, owner_m = next(iter(world.owner.memberships.items()))
    owner = await _held(app, world.a.tenant_id, world.owner.user_id, owner_ws, owner_m)
    assert planted <= set(owner.scopes), "the owner holds every grantable key (R2.7)"
    plain_ws, plain_m = next(iter(world.plain.memberships.items()))
    plain = await _held(app, world.a.tenant_id, world.plain.user_id, plain_ws, plain_m)
    assert set(plain.scopes) & planted == set()


async def test_nothing_held_in_another_tenant_reaches_the_lookup(
    app: AsyncEngine, migrator: AsyncEngine, world: World
) -> None:
    """K2: the same person in A and B; each tenant's lookup holds only its own keys."""
    k = world.keys
    in_a = {k["work"], k["other"], k["admin"], k["record"]}
    lookup = _lookup(app)
    subject = f"rbac-{world.heavy.user_id}"
    for workspace, membership in world.heavy.memberships.items():
        held = await _held(app, world.a.tenant_id, world.heavy.user_id, workspace, membership)
        assert k["b_only"] not in set(held.scopes)
        assert k["b_only"] not in {key for key, _depth, _anchor in held.grants}
        access = await lookup.find_access(subject, DEV_ISSUER, world.a.tenant_id, workspace)
        assert access is not None
        assert k["b_only"] not in access.scopes

    expected_b, _ = await _reference(migrator, world.b.tenant_id, world.heavy.user_id, world.b.main)
    held_b = await _held(
        app, world.b.tenant_id, world.heavy.user_id, world.b.main, world.heavy_in_b
    )
    assert set(held_b.scopes) == expected_b
    assert k["b_only"] in set(held_b.scopes)
    assert set(held_b.scopes) & in_a == set(), "A's roles grant nothing in B"
    assert {key for key, _depth, _anchor in held_b.grants} & in_a == set()

    # A workspace of B named under tenant A is no membership at all.
    assert await lookup.find_access(subject, DEV_ISSUER, world.a.tenant_id, world.b.main) is None
