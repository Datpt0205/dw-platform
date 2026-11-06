"""Integration: separation of duties under two concurrent writes, and a
membership's change of person (tenant-rbac ticket 11; R5.1, RB14, R3.12).

Two real connections: the first writes and holds its transaction open, the
second starts in a task until it waits on a lock (`pg_stat_activity`, read as
the superuser) or is done, the first commits, then the second finishes. No
fixed sleep. Each case plants a fresh tenant as `dw_migrator`; each rule (a
global table) carries its own key over catalogue keys of its own and is
removed, waivers first, even when the test fails.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.members import add_tenant_member
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

Write = Callable[[AsyncConnection], Coroutine[Any, Any, None]]


# ---- engines and rules ------------------------------------------------------------


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
async def admin(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this database: only to watch `pg_stat_activity`."""
    url = db_urls.admin.rsplit("/", 1)[0] + "/" + db_urls.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@dataclass(frozen=True)
class Rule:
    key: str
    left: str
    right: str
    outside: str


@pytest.fixture
async def new_rule(migrator: AsyncEngine) -> AsyncIterator[Callable[..., Awaitable[Rule]]]:
    """Keys of the case's own and a rule over them; ``add=False`` registers the
    keys only, so a test can add the rule after the assignments are in."""
    made: list[Rule] = []

    async def make(*, waivable: bool = False, add: bool = True) -> Rule:
        suffix = uuid.uuid4().hex[:10]
        rule = Rule(
            f"sod_{suffix}",
            f"test.w{suffix}.left",
            f"test.w{suffix}.right",
            f"test.w{suffix}.outside",
        )
        made.append(rule)
        async with migrator.begin() as conn:
            for key in (rule.left, rule.right, rule.outside):
                await register_key(conn, key)
            if add:
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


# ---- a company -----------------------------------------------------------------


@dataclass
class Company:
    t: PlantedTenant
    owners: tuple[uuid.UUID, uuid.UUID]
    roles: dict[str, uuid.UUID] = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        return self.t.tenant_id

    def ws(self, name: str) -> uuid.UUID:
        return self.t.workspaces["AB".index(name)]


async def company(conn: AsyncConnection, rule: Rule | None = None) -> Company:
    """Two workspaces A and B, two owners (who propose and confirm), and, given
    a rule, roles `left`, `right` and `outside` carrying one key each."""
    t = await plant_tenant(conn, workspaces=2)
    owner_role = await role_id(conn, t.tenant_id, "tenant_owner")
    owners = []
    for _ in range(2):
        owner = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, owner)
        await assign(conn, t.tenant_id, t.main, membership, owner_role)
        owners.append(owner)
    co = Company(t, (owners[0], owners[1]))
    if rule is not None:
        for name, key in (("left", rule.left), ("right", rule.right), ("outside", rule.outside)):
            co.roles[name] = await plant_role(conn, co.id, f"r_{name}", {key: "workspace"})
    return co


async def member(conn: AsyncConnection, co: Company, *workspaces: str) -> tuple[uuid.UUID, ...]:
    """A person with a membership in each of `workspaces`: (person, *memberships)."""
    person = await plant_person(conn, co.id)
    return (person, *[await plant_membership(conn, co.id, co.ws(w), person) for w in workspaces])


async def membership_of(
    conn: AsyncConnection, co: Company, person: uuid.UUID, ws: str
) -> uuid.UUID:
    found = await conn.scalar(
        sa.text(
            "SELECT id FROM platform.memberships WHERE tenant_id = :t AND workspace_id = :w"
            " AND user_id = :u"
        ),
        {"t": co.id, "w": co.ws(ws), "u": person},
    )
    assert found is not None
    return uuid.UUID(str(found))


async def holds(engine: AsyncEngine, co: Company, person: uuid.UUID, key: str) -> bool:
    async with engine.connect() as conn:
        return bool(
            await conn.scalar(
                sa.text("SELECT :k = ANY (platform.sod_held_keys(:t, :u))"),
                {"k": key, "t": co.id, "u": person},
            )
        )


async def granted_as_the_service_does(
    conn: AsyncConnection, co: Company, membership: uuid.UUID, ws: str, role: uuid.UUID
) -> None:
    """As `dw_app`: owner 1 proposes the assignment, owner 2 confirms it in this
    transaction and writes it, the way the role service writes."""
    request = uuid.uuid4()
    user = await conn.scalar(
        sa.text("SELECT user_id FROM platform.memberships WHERE id = :m"), {"m": membership}
    )

    async def bound(actor: uuid.UUID, change: uuid.UUID | None = None) -> None:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.user_id', :u, true), set_config('app.role_change_id', :r, true)"
            ),
            {"t": str(co.id), "u": str(actor), "r": str(change or "")},
        )

    await bound(co.owners[0])
    await conn.execute(
        sa.text(
            "INSERT INTO platform.role_change_requests (id, tenant_id, kind, payload, role_id,"
            " base_version, required_permission, proposed_by, expires_at, status)"
            " VALUES (:id, :t, 'assignment_grant', CAST(:p AS jsonb), :r, 1,"
            " 'platform.roles.bind', :by, now() + interval '7 days', 'proposed')"
        ),
        {
            "id": request,
            "t": co.id,
            "p": json.dumps(
                {
                    "membership_id": str(membership),
                    "workspace_id": str(co.ws(ws)),
                    "user_id": str(user),
                }
            ),
            "r": role,
            "by": co.owners[0],
        },
    )
    await bound(co.owners[1], request)
    await conn.execute(
        sa.text(
            "UPDATE platform.role_change_requests"
            " SET status = 'confirmed', confirmed_by = :c, decided_at = now() WHERE id = :id"
        ),
        {"c": co.owners[1], "id": request},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.role_assignments"
            " (id, tenant_id, workspace_id, membership_id, role_id, assigned_by)"
            " VALUES (gen_random_uuid(), :t, :w, :m, :r, :by)"
        ),
        {"t": co.id, "w": co.ws(ws), "m": membership, "r": role, "by": co.owners[1]},
    )


async def waived(conn: AsyncConnection, co: Company, rule: Rule) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO platform.sod_waivers (id, tenant_id, rule_key, reason, granted_by)"
            " VALUES (gen_random_uuid(), :t, :k, 'nhỏ', :g)"
        ),
        {"t": co.id, "k": rule.key, "g": co.owners[0]},
    )
    await conn.execute(
        sa.text(
            "UPDATE platform.sod_waivers SET confirmed_at = now(), confirmed_by = :c,"
            " confirm_reason = 'đồng ý' WHERE tenant_id = :t AND rule_key = :k"
        ),
        {"t": co.id, "k": rule.key, "c": co.owners[1]},
    )


# ---- two connections -------------------------------------------------------------


def _cause(error: BaseException) -> Any:
    return getattr(getattr(error, "orig", None), "__cause__", None)


async def _blocked(admin: AsyncEngine, pid: int) -> bool:
    async with admin.connect() as conn:
        waiting = await conn.scalar(
            sa.text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        )
    return bool(waiting == "Lock")


@dataclass
class Raced:
    first: BaseException | None = None
    second: BaseException | None = None
    second_waited: bool = False


async def race(
    admin: AsyncEngine,
    engines: tuple[AsyncEngine, AsyncEngine],
    first: Write,
    second: Write,
) -> Raced:
    """`first` writes and holds its transaction open; `second` starts, waits on
    it (or does not), then `first` commits, then `second` finishes."""
    out = Raced()
    async with engines[0].connect() as one, engines[1].connect() as two:
        await one.begin()
        await first(one)
        await two.begin()
        pid = int(await two.scalar(sa.text("SELECT pg_backend_pid()")))
        later = asyncio.create_task(second(two))
        deadline = asyncio.get_running_loop().time() + 10
        while not later.done() and asyncio.get_running_loop().time() < deadline:
            if await _blocked(admin, pid):
                out.second_waited = True
                break
            await asyncio.sleep(0.05)
        try:
            await one.commit()
        except DBAPIError as error:
            out.first = error
            await one.rollback()
        try:
            await later
            await two.commit()
        except DBAPIError as error:
            out.second = error
            await two.rollback()
    return out


def refused_by(error: BaseException | None, constraint: str) -> Any:
    assert error is not None, "the second write was accepted"
    cause = _cause(error)
    assert getattr(cause, "sqlstate", None) == "23514", cause
    assert getattr(cause, "constraint_name", None) == constraint, cause
    return cause


# ---- K1: two concurrent writes leave nobody holding both sides -------------------


async def test_k1a_two_assignments_of_the_two_sides_the_second_is_refused(
    app: AsyncEngine,
    migrator: AsyncEngine,
    admin: AsyncEngine,
    new_rule: Callable[..., Awaitable[Rule]],
) -> None:
    """R5.1 (RB14): L at A held open, R at B waits on it, refused once L commits."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        person, at_a, at_b = await member(conn, co, "A", "B")

    async def left(conn: AsyncConnection) -> None:
        await granted_as_the_service_does(conn, co, at_a, "A", co.roles["left"])

    async def right(conn: AsyncConnection) -> None:
        await granted_as_the_service_does(conn, co, at_b, "B", co.roles["right"])

    raced = await race(admin, (app, app), left, right)
    assert raced.first is None and raced.second_waited
    cause = refused_by(raced.second, "ck_roles_sod_memberships")
    assert getattr(cause, "detail", None) == str(person)
    assert await holds(migrator, co, person, rule.left)
    assert not await holds(migrator, co, person, rule.right)


async def test_k1b_a_right_key_into_a_held_role_then_a_left_assignment_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """P holds X; the right key goes into X, held open; L assigned to P waits, refused."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        person, at_a = await member(conn, co, "A")
        x = await plant_role(conn, co.id, "r_x", {rule.outside: "workspace"})
        await assign(conn, co.id, co.ws("A"), at_a, x)

    async def right_key(conn: AsyncConnection) -> None:
        await grant_privilege(conn, co.id, x, rule.right, "workspace")

    async def left(conn: AsyncConnection) -> None:
        await assign(conn, co.id, co.ws("A"), at_a, co.roles["left"])

    raced = await race(admin, (migrator, migrator), right_key, left)
    assert raced.first is None
    cause = refused_by(raced.second, "ck_roles_sod_memberships")
    assert getattr(cause, "detail", None) == str(person)
    assert not await holds(migrator, co, person, rule.left)


async def test_k1c_a_restore_of_the_right_side_then_a_left_assignment_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """R soft-deleted with P's assignment; its restore held open; L to P refused."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        person, at_a = await member(conn, co, "A")
        await assign(conn, co.id, co.ws("A"), at_a, co.roles["right"])
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET deleted_at = now() WHERE id = :r"),
            {"r": co.roles["right"]},
        )

    async def restore(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET deleted_at = NULL WHERE id = :r"),
            {"r": co.roles["right"]},
        )

    async def left(conn: AsyncConnection) -> None:
        await assign(conn, co.id, co.ws("A"), at_a, co.roles["left"])

    raced = await race(admin, (migrator, migrator), restore, left)
    assert raced.first is None
    cause = refused_by(raced.second, "ck_roles_sod_memberships")
    assert getattr(cause, "detail", None) == str(person)
    assert not await holds(migrator, co, person, rule.left)


async def test_k1_under_a_confirmed_waiver_both_concurrent_assignments_pass(
    app: AsyncEngine,
    migrator: AsyncEngine,
    admin: AsyncEngine,
    new_rule: Callable[..., Awaitable[Rule]],
) -> None:
    rule = await new_rule(waivable=True)
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        await waived(conn, co, rule)
        person, at_a, at_b = await member(conn, co, "A", "B")

    async def left(conn: AsyncConnection) -> None:
        await granted_as_the_service_does(conn, co, at_a, "A", co.roles["left"])

    async def right(conn: AsyncConnection) -> None:
        await granted_as_the_service_does(conn, co, at_b, "B", co.roles["right"])

    raced = await race(admin, (app, app), left, right)
    assert (raced.first, raced.second) == (None, None)
    assert await holds(migrator, co, person, rule.right)


async def test_k1_two_people_each_given_one_side_at_once_both_pass(
    app: AsyncEngine,
    migrator: AsyncEngine,
    admin: AsyncEngine,
    new_rule: Callable[..., Awaitable[Rule]],
) -> None:
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        _, p_at_a = await member(conn, co, "A")
        _, q_at_b = await member(conn, co, "B")

    async def left(conn: AsyncConnection) -> None:
        await granted_as_the_service_does(conn, co, p_at_a, "A", co.roles["left"])

    async def right(conn: AsyncConnection) -> None:
        await granted_as_the_service_does(conn, co, q_at_b, "B", co.roles["right"])

    raced = await race(admin, (app, app), left, right)
    assert (raced.first, raced.second) == (None, None)


async def test_k1_an_assignment_in_another_tenant_does_not_wait(
    migrator: AsyncEngine, admin: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """The lock is the writing tenant's own row: tenant B never waits on A."""
    rule = await new_rule()
    async with migrator.begin() as conn:
        a, b = await company(conn, rule), await company(conn, rule)
        _, in_a = await member(conn, a, "A")
        _, in_b = await member(conn, b, "A")

    async def in_tenant_a(conn: AsyncConnection) -> None:
        await assign(conn, a.id, a.ws("A"), in_a, a.roles["left"])

    async def in_tenant_b(conn: AsyncConnection) -> None:
        await assign(conn, b.id, b.ws("A"), in_b, b.roles["right"])

    raced = await race(admin, (migrator, migrator), in_tenant_a, in_tenant_b)
    assert (raced.first, raced.second, raced.second_waited) == (None, None, False)


# ---- K2: no version row refuses, but in offboarding ------------------------------


async def test_k2_an_active_tenant_without_its_version_row_is_refused(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        _, at_a = await member(conn, co, "A")
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_access_versions WHERE tenant_id = :t"),
            {"t": co.id},
        )
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await assign(conn, co.id, co.ws("A"), at_a, co.roles["left"])
    refused_by(refused.value, "ck_roles_sod_access_version")


async def test_k2_deleting_a_user_who_assigned_a_role_passes_in_an_offboarding_tenant(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """The purge took the version row; deleting U nulls `assigned_by` (an
    UPDATE the trigger judges), which must still pass."""
    rule = await new_rule()
    u = uuid.uuid4()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        _, at_a = await member(conn, co, "A")
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name, kind)"
                " VALUES (:u, :s, 'Người gán', 'human')"
            ),
            {"u": u, "s": f"rbac-{u}"},
        )
        made = await assign(conn, co.id, co.ws("A"), at_a, co.roles["left"])
        await conn.execute(
            sa.text("UPDATE platform.role_assignments SET assigned_by = :u WHERE id = :a"),
            {"u": u, "a": made},
        )
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": co.id},
        )
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_access_versions WHERE tenant_id = :t"),
            {"t": co.id},
        )
    async with migrator.begin() as conn:
        await conn.execute(sa.text("DELETE FROM platform.users WHERE id = :u"), {"u": u})
    async with migrator.connect() as conn:
        assert (
            await conn.scalar(
                sa.text("SELECT assigned_by FROM platform.role_assignments WHERE id = :a"),
                {"a": made},
            )
            is None
        )


# ---- K3: a membership's change of person ------------------------------------------


async def moved(migrator: AsyncEngine, membership: uuid.UUID, to: uuid.UUID) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.memberships SET user_id = :u WHERE id = :m"),
            {"u": to, "m": membership},
        )


async def owner_of(migrator: AsyncEngine, membership: uuid.UUID) -> uuid.UUID:
    async with migrator.connect() as conn:
        return uuid.UUID(
            str(
                await conn.scalar(
                    sa.text("SELECT user_id FROM platform.memberships WHERE id = :m"),
                    {"m": membership},
                )
            )
        )


async def in_breach(conn: AsyncConnection, co: Company, rule: Rule) -> tuple[uuid.UUID, uuid.UUID]:
    """P holds L and R at A before `rule` is added: (P, P's membership at A).
    The caller adds the rule afterwards."""
    person, at_a = await member(conn, co, "A")
    for side in ("left", "right"):
        await assign(conn, co.id, co.ws("A"), at_a, co.roles[side])
    return person, at_a


async def test_k3_moving_a_right_side_membership_to_a_left_holder_is_refused(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        p, p_at_a = await member(conn, co, "A")
        await assign(conn, co.id, co.ws("A"), p_at_a, co.roles["left"])
        q, q_at_b = await member(conn, co, "B")
        await assign(conn, co.id, co.ws("B"), q_at_b, co.roles["right"])
    with pytest.raises(IntegrityError) as refused:
        await moved(migrator, q_at_b, p)
    cause = refused_by(refused.value, "ck_roles_sod_memberships")
    assert getattr(cause, "detail", None) == str(p)
    assert await owner_of(migrator, q_at_b) == q


@pytest.mark.parametrize("carrying", ["nothing", "outside"])
async def test_k3_moving_any_membership_to_someone_already_in_breach_is_refused(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]], carrying: str
) -> None:
    rule = await new_rule(add=False)
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        p, _ = await in_breach(conn, co, rule)
        q, q_at_b = await member(conn, co, "B")
        if carrying == "outside":
            await assign(conn, co.id, co.ws("B"), q_at_b, co.roles["outside"])
        await add_rule(conn, rule)
    with pytest.raises(IntegrityError) as refused:
        await moved(migrator, q_at_b, p)
    refused_by(refused.value, "ck_roles_sod_memberships")
    assert await owner_of(migrator, q_at_b) == q


async def test_k3_moving_an_outside_role_membership_to_someone_clean_passes(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    rule = await new_rule()
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        p, p_at_a = await member(conn, co, "A")
        await assign(conn, co.id, co.ws("A"), p_at_a, co.roles["left"])
        _, q_at_b = await member(conn, co, "B")
        await assign(conn, co.id, co.ws("B"), q_at_b, co.roles["outside"])
    await moved(migrator, q_at_b, p)
    assert await owner_of(migrator, q_at_b) == p


async def test_k3_a_breach_in_another_tenant_does_not_refuse_a_move_here(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """P breaks the rule in B; Q's membership in A (an outside role) moves to P."""
    rule = await new_rule(add=False)
    async with migrator.begin() as conn:
        a, b = await company(conn, rule), await company(conn, rule)
        p, _ = await in_breach(conn, b, rule)
        await add_tenant_member(conn, a.id, p, "active")
        _, q_at_a = await member(conn, a, "A")
        await assign(conn, a.id, a.ws("A"), q_at_a, a.roles["outside"])
        await add_rule(conn, rule)
    await moved(migrator, q_at_a, p)
    assert await owner_of(migrator, q_at_a) == p


async def test_k3_setting_a_membership_to_its_own_person_is_not_judged(
    migrator: AsyncEngine, new_rule: Callable[..., Awaitable[Rule]]
) -> None:
    """`SET user_id = user_id` fires `UPDATE OF user_id`; the WHEN lets it be."""
    rule = await new_rule(add=False)
    async with migrator.begin() as conn:
        co = await company(conn, rule)
        p, p_at_a = await in_breach(conn, co, rule)
        await add_rule(conn, rule)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.memberships SET user_id = user_id WHERE id = :m"),
            {"m": p_at_a},
        )
    assert await owner_of(migrator, p_at_a) == p


# ---- K4: the below-two warning under two concurrent revocations -------------------


async def test_k4_two_concurrent_revocations_below_two_tell_once(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """R3.12 (RB40): one owner and two holders of both owner keys; each
    transaction revokes one holder; after both commit, exactly one event."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        owner = await plant_person(conn, t.tenant_id)
        await assign(
            conn,
            t.tenant_id,
            t.main,
            await plant_membership(conn, t.tenant_id, t.main, owner),
            await role_id(conn, t.tenant_id, "tenant_owner"),
        )
        keys = await conn.scalar(sa.text("SELECT platform.owner_permission_keys()"))
        admins = await plant_role(conn, t.tenant_id, "r_admins", dict.fromkeys(keys, "tenant"))
        held = []
        for _ in range(2):
            person = await plant_person(conn, t.tenant_id)
            membership = await plant_membership(conn, t.tenant_id, t.main, person)
            held.append(await assign(conn, t.tenant_id, t.main, membership, admins))

    def revoke(assignment: uuid.UUID) -> Write:
        async def run(conn: AsyncConnection) -> None:
            await conn.execute(
                sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
            )

        return run

    raced = await race(admin, (migrator, migrator), revoke(held[0]), revoke(held[1]))
    assert (raced.first, raced.second) == (None, None) and raced.second_waited
    async with migrator.connect() as conn:
        events = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.outbox_events WHERE tenant_id = :t"
                " AND event_type = 'platform.tenant.owner_coverage_low'"
            ),
            {"t": t.tenant_id},
        )
        since = await conn.scalar(
            sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
            {"t": t.tenant_id},
        )
    assert (events, since is not None) == (1, True)
