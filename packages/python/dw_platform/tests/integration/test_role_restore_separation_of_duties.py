"""Integration: a role's restore passes separation of duties, and no rule names a
generated key (tenant-rbac ticket 09; R5.1, RB14; ADR-0104 decision 9).

On a migrated Postgres, as `dw_migrator`, the one writer `rbac_guard` lets
restore a role: the separation-of-duties trigger does not exempt it. Each case
plants a fresh tenant; each rule (a global table) carries its own key over
catalogue keys of its own, and is removed, waivers first, even when the test
fails.

The breach is built in the order the gap allowed: P is assigned R (the right
side), R is soft-deleted, P is assigned L (the left side, accepted: a deleted
role's keys count for nobody), then R is restored.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

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
    unregister_key,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Rule:
    key: str
    left: str
    right: str
    outside: str


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def new_rule(migrator: AsyncEngine) -> AsyncIterator[Callable[..., Awaitable[Rule]]]:
    """Keys of the case's own and a rule over them; ``add=False`` registers the
    keys only, so a test can add the rule after the assignments are in."""
    made: list[Rule] = []

    async def make(*, waivable: bool = False, add: bool = True) -> Rule:
        suffix = uuid.uuid4().hex[:10]
        rule = Rule(
            f"sod_{suffix}",
            f"test.r{suffix}.left",
            f"test.r{suffix}.right",
            f"test.r{suffix}.outside",
        )
        made.append(rule)
        async with migrator.begin() as conn:
            for key in (rule.left, rule.right, rule.outside):
                await register_key(conn, key)
        if add:
            async with migrator.begin() as conn:
                await add_rule(conn, rule, waivable=waivable)
        return rule

    yield make
    async with migrator.begin() as conn:
        for rule in made:
            await conn.execute(
                sa.text("DELETE FROM platform.sod_waivers WHERE rule_key = :k"), {"k": rule.key}
            )
            await conn.execute(
                sa.text("DELETE FROM platform.sod_rules WHERE key = :k"), {"k": rule.key}
            )
            for key in (rule.left, rule.right, rule.outside):
                await unregister_key(conn, key)


async def add_rule(conn: AsyncConnection, rule: Rule, *, waivable: bool = False) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO platform.sod_rules (key, description, left_scopes, right_scopes,"
            " waivable) VALUES (:k, 'người đặt không duyệt', CAST(:l AS jsonb),"
            " CAST(:r AS jsonb), :w)"
        ),
        {"k": rule.key, "l": json.dumps([rule.left]), "r": json.dumps([rule.right]), "w": waivable},
    )


@dataclass
class World:
    t: PlantedTenant
    owners: tuple[uuid.UUID, uuid.UUID]


async def world(conn: AsyncConnection) -> World:
    """A fresh tenant with two owners, who grant and confirm waivers."""
    t = await plant_tenant(conn)
    owner_role = await role_id(conn, t.tenant_id, "tenant_owner")
    owners = []
    for _ in range(2):
        owner = await plant_person(conn, t.tenant_id)
        await assign(
            conn,
            t.tenant_id,
            t.main,
            await plant_membership(conn, t.tenant_id, t.main, owner),
            owner_role,
        )
        owners.append(owner)
    return World(t, (owners[0], owners[1]))


async def soft_delete(conn: AsyncConnection, role: uuid.UUID) -> None:
    await conn.execute(
        sa.text("UPDATE platform.tenant_roles SET deleted_at = now() WHERE id = :r"), {"r": role}
    )


async def restore(engine: AsyncEngine, role: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET deleted_at = NULL WHERE id = :r"),
            {"r": role},
        )


async def deleted(engine: AsyncEngine, role: uuid.UUID) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                sa.text("SELECT deleted_at IS NOT NULL FROM platform.tenant_roles WHERE id = :r"),
                {"r": role},
            )
        )


async def gap_breach(
    conn: AsyncConnection, w: World, rule: Rule, *, expired: bool = False
) -> tuple[uuid.UUID, uuid.UUID]:
    """P assigned R, R soft-deleted, P assigned L: (P, R), R still deleted.
    ``expired``: P's assignment of R ended yesterday."""
    t = w.t.tenant_id
    person = await plant_person(conn, t)
    membership = await plant_membership(conn, t, w.t.main, person)
    right = await plant_role(conn, t, "r_right", {rule.right: "workspace"})
    left = await plant_role(conn, t, "r_left", {rule.left: "workspace"})
    now = datetime.now(UTC)
    await assign(
        conn,
        t,
        w.t.main,
        membership,
        right,
        assigned_at=now - timedelta(days=2) if expired else None,
        expires_at=now - timedelta(days=1) if expired else None,
    )
    await soft_delete(conn, right)
    await assign(conn, t, w.t.main, membership, left)
    return person, right


def _cause(error: BaseException) -> object:
    return getattr(getattr(error, "orig", None), "__cause__", None)


async def refused_restore(engine: AsyncEngine, role: uuid.UUID) -> object:
    with pytest.raises(IntegrityError) as refused:
        await restore(engine, role)
    cause = _cause(refused.value)
    assert getattr(cause, "sqlstate", None) == "23514"
    assert getattr(cause, "constraint_name", None) == "ck_roles_sod_memberships"
    assert await deleted(engine, role), "a refused restore leaves the role deleted"
    return cause


# ---- K1: a restore leaves nobody in breach ------------------------------------


async def test_k1_a_restore_handing_back_the_other_side_is_refused_with_rule_and_holder(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """RB14: refused with the rule as HINT and P in DETAIL; the role stays deleted."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        w = await world(conn)
        person, right = await gap_breach(conn, w, rule)
    cause = await refused_restore(migrator, right)
    assert getattr(cause, "hint", None) == rule.key
    assert str(person) in (getattr(cause, "detail", None) or "")


async def waiver(
    conn: AsyncConnection, w: World, rule: Rule, *, confirmed: bool, revoked: bool = False
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO platform.sod_waivers (id, tenant_id, rule_key, reason, granted_by)"
            " VALUES (gen_random_uuid(), :t, :k, 'nhỏ', :g)"
        ),
        {"t": w.t.tenant_id, "k": rule.key, "g": w.owners[0]},
    )
    if confirmed:
        await conn.execute(
            sa.text(
                "UPDATE platform.sod_waivers SET confirmed_at = now(), confirmed_by = :c,"
                " confirm_reason = 'đồng ý' WHERE tenant_id = :t AND rule_key = :k"
            ),
            {"t": w.t.tenant_id, "k": rule.key, "c": w.owners[1]},
        )
    if revoked:
        await conn.execute(
            sa.text(
                "UPDATE platform.sod_waivers SET revoked_at = now(), revoked_by = :b,"
                " revoke_reason = 'hết' WHERE tenant_id = :t AND rule_key = :k"
            ),
            {"t": w.t.tenant_id, "k": rule.key, "b": w.owners[0]},
        )


@pytest.mark.parametrize(
    ("confirmed", "revoked", "accepted"),
    [(False, False, False), (True, True, False), (True, False, True)],
    ids=["proposed_unconfirmed", "confirmed_then_revoked", "confirmed_open"],
)
async def test_k1_a_waivable_rule_lets_a_restore_through_only_under_an_open_confirmed_waiver(
    migrator: AsyncEngine,
    new_rule: Callable[..., Awaitable[Rule]],
    confirmed: bool,
    revoked: bool,
    accepted: bool,
) -> None:
    """R5.1: the waiver is the only way past, and only while confirmed and open."""
    rule = await new_rule(waivable=True)
    async with migrator.begin() as conn:
        w = await world(conn)
        _, right = await gap_breach(conn, w, rule)
        await waiver(conn, w, rule, confirmed=confirmed, revoked=revoked)
    if accepted:
        await restore(migrator, right)
        assert not await deleted(migrator, right)
    else:
        cause = await refused_restore(migrator, right)
        assert getattr(cause, "hint", None) == rule.key


async def test_k1_a_restore_that_breaches_nothing_is_accepted(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """P holds only R: its restore hands back one side."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        w = await world(conn)
        t = w.t.tenant_id
        person = await plant_person(conn, t)
        membership = await plant_membership(conn, t, w.t.main, person)
        right = await plant_role(conn, t, "r_right", {rule.right: "workspace"})
        await assign(conn, t, w.t.main, membership, right)
        await soft_delete(conn, right)
    await restore(migrator, right)
    assert not await deleted(migrator, right)


async def test_k1_a_restore_through_an_expired_assignment_is_accepted(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """P's assignment of R ended: the restore hands P nothing."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        w = await world(conn)
        _, right = await gap_breach(conn, w, rule, expired=True)
    await restore(migrator, right)
    assert not await deleted(migrator, right)


async def already_in_breach(
    conn: AsyncConnection, w: World, rule: Rule
) -> tuple[uuid.UUID, uuid.UUID]:
    """P holds L and R live before `rule` exists: (P, P's membership). The
    caller adds the rule afterwards, the one write no trigger judges."""
    t = w.t.tenant_id
    person = await plant_person(conn, t)
    membership = await plant_membership(conn, t, w.t.main, person)
    for name, key in (("r_left", rule.left), ("r_right", rule.right)):
        await assign(
            conn, t, w.t.main, membership, await plant_role(conn, t, name, {key: "workspace"})
        )
    return person, membership


async def test_k1_restoring_a_role_of_keys_in_no_rule_is_refused_while_its_holder_is_in_breach(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """ADR-0104 decision 9: no early return for a restore; V carries only a key
    in no rule, and P, who holds it, already breaks the rule."""
    rule = await new_rule(add=False)
    async with migrator.begin() as conn:
        w = await world(conn)
        t = w.t.tenant_id
        person, membership = await already_in_breach(conn, w, rule)
        outside = await plant_role(conn, t, "r_outside", {rule.outside: "workspace"})
        await assign(conn, t, w.t.main, membership, outside)
        await soft_delete(conn, outside)
        await add_rule(conn, rule)
    cause = await refused_restore(migrator, outside)
    assert getattr(cause, "hint", None) == rule.key
    assert str(person) in (getattr(cause, "detail", None) or "")


async def test_k1_a_soft_delete_is_not_judged_even_while_its_holder_is_in_breach(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """A soft delete only narrows: P in breach, P's role X deleted, accepted."""
    rule = await new_rule(add=False)
    async with migrator.begin() as conn:
        w = await world(conn)
        t = w.t.tenant_id
        _, membership = await already_in_breach(conn, w, rule)
        other = await plant_role(conn, t, "r_other", {rule.outside: "workspace"})
        await assign(conn, t, w.t.main, membership, other)
        await add_rule(conn, rule)
    async with migrator.begin() as conn:
        await soft_delete(conn, other)
    assert await deleted(migrator, other)


# ---- K2: only the holders in that very tenant are judged ----------------------


async def test_k2_a_breach_in_another_tenant_does_not_refuse_a_restore_here(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """R5.1: P breaks the rule in B; in A P holds only R, restored: accepted.
    Q in A, built as K1's breach, is still refused."""
    rule = await new_rule(add=False)
    async with migrator.begin() as conn:
        a, b = await world(conn), await world(conn)
        p, _ = await already_in_breach(conn, b, rule)
        await add_tenant_member(conn, a.t.tenant_id, p, "active")
        right = await plant_role(conn, a.t.tenant_id, "r_right_p", {rule.right: "workspace"})
        await assign(
            conn,
            a.t.tenant_id,
            a.t.main,
            await plant_membership(conn, a.t.tenant_id, a.t.main, p),
            right,
        )
        await soft_delete(conn, right)
        await add_rule(conn, rule)
        q, right_2 = await gap_breach(conn, a, rule)
    await restore(migrator, right)
    assert not await deleted(migrator, right)
    cause = await refused_restore(migrator, right_2)
    assert (getattr(cause, "detail", None) or "") == str(q)


# ---- K3: no rule names a generated key ----------------------------------------


@pytest.mark.parametrize(
    "side",
    [("left_scopes", "obj.lead.read"), ("right_scopes", "fld.lead.phone.edit")],
    ids=["obj_on_the_left", "fld_on_the_right"],
)
async def test_k3_a_rule_naming_a_generated_key_is_refused(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]], side: tuple[str, str]
) -> None:
    """R5.1: a generated key comes from tables no separation-of-duties trigger
    watches, so the rule naming one is refused where it is written."""
    rule = await new_rule(add=False)
    column, generated = side
    scopes = {"left_scopes": [rule.left], "right_scopes": [rule.right]}
    scopes[column] = [generated]
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.sod_rules (key, description, left_scopes,"
                    " right_scopes) VALUES (:k, 'khóa sinh', CAST(:l AS jsonb), CAST(:r AS jsonb))"
                ),
                {
                    "k": rule.key,
                    "l": json.dumps(scopes["left_scopes"]),
                    "r": json.dumps(scopes["right_scopes"]),
                },
            )
    cause = _cause(refused.value)
    assert getattr(cause, "sqlstate", None) == "23514"
    assert getattr(cause, "constraint_name", None) == "ck_sod_rules_no_generated_keys"


async def test_k3_a_rule_over_catalogue_keys_is_accepted(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    rule = await new_rule()
    async with migrator.connect() as conn:
        assert (
            await conn.scalar(
                sa.text("SELECT count(*) FROM platform.sod_rules WHERE key = :k"), {"k": rule.key}
            )
            == 1
        )
