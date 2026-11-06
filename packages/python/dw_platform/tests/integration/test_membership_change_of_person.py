"""Integration: a membership's change of person passes the guards an assignment
and a revocation pass (tenant-rbac ticket 12; R3.11, R3.12, R6.7, RB20, RB39,
RB40, RB50).

Every change is `UPDATE platform.memberships SET user_id = :p WHERE id = :m`
as `dw_migrator`, the one writer RB50 leaves it to. Each refusal asserts the
SQLSTATE, the constraint, and that M kept its person and its assignments. The
concurrent cases run both orders on two real connections: the first writes and
holds its transaction open, the second starts in a task until it waits on a
lock (`pg_stat_activity`, read as the superuser) or is done, the first commits,
then the second finishes; no fixed sleep, and no `40P01` in either order.
"""

from __future__ import annotations

import asyncio
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
OPERATOR = "ck_role_assignments_operator_not_owner"
SERVICE = "ck_role_assignments_service_not_critical"
LAST_OWNER = "ck_role_assignments_last_owner"
# The owner key the concurrent cases add to a role: `studio.publish.approve` is of
# risk `standard`, so the service-account guard takes no role lock for it and the
# R3.11 guard's own lock is the one under test (`platform.roles.write` is
# `critical`: that guard would lock the role row first and hide a missing lock).
APPROVE = "studio.publish.approve"


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admin(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this database: only to watch `pg_stat_activity`."""
    url = db_urls.admin.rsplit("/", 1)[0] + "/" + db_urls.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@dataclass
class Keys:
    std: str
    critical: str
    listed: list[tuple[str, uuid.UUID]] = field(default_factory=list)


@pytest.fixture
async def keys(migrator: AsyncEngine) -> AsyncIterator[Keys]:
    """A standard and a critical catalogue key of the test's own; the people it
    lists as operators or support staff (global tables) are unlisted after."""
    tag = uuid.uuid4().hex[:10]
    k = Keys(f"test.mc{tag}.std", f"test.mc{tag}.crit")
    async with migrator.begin() as conn:
        await register_key(conn, k.std)
        await register_key(conn, k.critical, risk="critical")
    yield k
    async with migrator.begin() as conn:
        for table, user in k.listed:
            await conn.execute(
                sa.text(f"DELETE FROM platform.{table} WHERE user_id = :u"), {"u": user}
            )
        for key in (k.std, k.critical):
            await unregister_key(conn, key)


@dataclass
class Company:
    t: PlantedTenant
    owner_role: uuid.UUID
    roles: dict[str, uuid.UUID] = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        return self.t.tenant_id

    @property
    def b(self) -> uuid.UUID:
        return self.t.workspaces[1]


async def company(conn: AsyncConnection, k: Keys, *, owners: int = 2) -> Company:
    """Two workspaces, `owners` owners in main, and three roles: `std` (a
    standard key), `write` (`platform.roles.write` at `tenant`) and `approve`
    (`studio.publish.approve` at `tenant`)."""
    t = await plant_tenant(conn, workspaces=2)
    co = Company(t, await role_id(conn, t.tenant_id, "tenant_owner"))
    for _ in range(owners):
        owner = await plant_person(conn, co.id)
        await assign(
            conn, co.id, t.main, await plant_membership(conn, co.id, t.main, owner), co.owner_role
        )
    co.roles["std"] = await plant_role(conn, co.id, "r_std", {k.std: "workspace"})
    co.roles["write"] = await plant_role(conn, co.id, "r_write", {"platform.roles.write": "tenant"})
    co.roles["approve"] = await plant_role(
        conn, co.id, "r_approve", {"studio.publish.approve": "tenant"}
    )
    return co


async def carrying(
    conn: AsyncConnection, co: Company, *roles: uuid.UUID, status: str = "active"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Q, and Q's membership M in workspace B carrying `roles`: (Q, M)."""
    q = await plant_person(conn, co.id, status=status)  # type: ignore[arg-type]
    m = await plant_membership(conn, co.id, co.b, q)
    for role in roles:
        await assign(conn, co.id, co.b, m, role)
    return q, m


async def listed(conn: AsyncConnection, k: Keys, table: str, user: uuid.UUID) -> None:
    await conn.execute(sa.text(f"INSERT INTO platform.{table} (user_id) VALUES (:u)"), {"u": user})
    k.listed.append((table, user))


async def service_account(conn: AsyncConnection, co: Company) -> uuid.UUID:
    """A service account of the company, as the route makes one, with its
    membership of main (so workspace B is free for M)."""
    user = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
            " VALUES (:u, :s, 'Tài khoản dịch vụ', 'service', :t)"
        ),
        {"u": user, "s": f"service:{user}", "t": co.id},
    )
    await add_tenant_member(conn, co.id, user, "active")
    owner = await conn.scalar(
        sa.text(
            "SELECT m.user_id FROM platform.role_assignments a"
            " JOIN platform.memberships m ON m.id = a.membership_id"
            " WHERE a.tenant_id = :t AND a.role_id = :r LIMIT 1"
        ),
        {"t": co.id, "r": co.owner_role},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.service_principals"
            " (user_id, tenant_id, owning_workspace_id, name, owner_user_id)"
            " VALUES (:u, :t, :w, :n, :o)"
        ),
        {"u": user, "t": co.id, "w": co.t.main, "n": f"svc-{user.hex[:12]}", "o": owner},
    )
    await plant_membership(conn, co.id, co.t.main, user)
    return user


async def move(conn: AsyncConnection, m: uuid.UUID, to: uuid.UUID) -> None:
    await conn.execute(
        sa.text("UPDATE platform.memberships SET user_id = :u WHERE id = :m"), {"u": to, "m": m}
    )


def mover(m: uuid.UUID, to: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await move(conn, m, to)

    return go


def key_adder(co: Company, role: uuid.UUID, key: str, depth: str = "tenant") -> Write:
    async def go(conn: AsyncConnection) -> None:
        await grant_privilege(conn, co.id, role, key, depth)

    return go


def assigner(co: Company, workspace: uuid.UUID, m: uuid.UUID, role: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await assign(conn, co.id, workspace, m, role)

    return go


def lister(k: Keys, table: str, user: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await listed(conn, k, table, user)

    return go


@dataclass
class State:
    user: uuid.UUID
    assignments: int


async def state(engine: AsyncEngine, m: uuid.UUID) -> State:
    async with engine.connect() as conn:
        user = await conn.scalar(
            sa.text("SELECT user_id FROM platform.memberships WHERE id = :m"), {"m": m}
        )
        count = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.role_assignments WHERE membership_id = :m"),
            {"m": m},
        )
    return State(uuid.UUID(str(user)), int(count or 0))


def _cause(error: BaseException) -> Any:
    return getattr(getattr(error, "orig", None), "__cause__", None)


def refused_by(error: BaseException | None, constraint: str) -> None:
    assert error is not None, "accepted"
    cause = _cause(error)
    assert getattr(cause, "sqlstate", None) == "23514", cause
    assert getattr(cause, "constraint_name", None) == constraint, cause


async def refused_move(migrator: AsyncEngine, m: uuid.UUID, to: uuid.UUID, constraint: str) -> None:
    before = await state(migrator, m)
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await move(conn, m, to)
    refused_by(refused.value, constraint)
    assert await state(migrator, m) == before


async def accepted_move(migrator: AsyncEngine, m: uuid.UUID, to: uuid.UUID) -> None:
    async with migrator.begin() as conn:
        await move(conn, m, to)
    assert (await state(migrator, m)).user == to


async def _blocked(admin: AsyncEngine, pid: int) -> bool:
    async with admin.connect() as conn:
        waiting = await conn.scalar(
            sa.text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        )
    return bool(waiting == "Lock")


async def race(migrator: AsyncEngine, admin: AsyncEngine, first: Write, second: Write) -> list[Any]:
    """[first's error, second's error]: `first` writes and holds; `second`
    starts until it waits or is done; `first` commits; `second` finishes."""
    errors: list[Any] = [None, None]
    async with migrator.connect() as one, migrator.connect() as two:
        await one.begin()
        await first(one)
        await two.begin()
        pid = int(await two.scalar(sa.text("SELECT pg_backend_pid()")))
        later = asyncio.create_task(second(two))
        deadline = asyncio.get_running_loop().time() + 10
        while not later.done() and asyncio.get_running_loop().time() < deadline:
            if await _blocked(admin, pid):
                break
            await asyncio.sleep(0.05)
        try:
            await one.commit()
        except DBAPIError as error:
            errors[0] = error
            await one.rollback()
        try:
            await later
            await two.commit()
        except DBAPIError as error:
            errors[1] = error
            await two.rollback()
    return errors


async def both_orders(
    migrator: AsyncEngine,
    admin: AsyncEngine,
    plant: Callable[[AsyncConnection], Awaitable[tuple[Write, Write]]],
    constraint: str,
) -> None:
    """In each order on a fresh plant, exactly the second write is refused with
    `constraint`; never a deadlock."""
    for flip in (False, True):
        async with migrator.begin() as conn:
            x, y = await plant(conn)
        first, second = (y, x) if flip else (x, y)
        errors = await race(migrator, admin, first, second)
        assert errors[0] is None, (flip, errors[0])
        assert getattr(_cause(errors[1]), "sqlstate", None) != "40P01", flip
        refused_by(errors[1], constraint)


# ---- K1: no owner authority reaches an operator or support staff ------------------


@pytest.mark.parametrize("table", ["platform_operators", "support_staff"])
@pytest.mark.parametrize("carried", ["owner", "write", "approve"])
async def test_k1_a_move_handing_owner_authority_to_a_listed_person_is_refused(
    migrator: AsyncEngine, keys: Keys, table: str, carried: str
) -> None:
    """R3.11 (RB39): `tenant_owner`, a role with `platform.roles.write`, one
    with `studio.publish.approve`, each at `tenant`. A support staff member
    holds no membership of a customer's tenant at all: that older guard
    (`ck_memberships_not_support_staff`, first by name) refuses the move first."""
    async with migrator.begin() as conn:
        co = await company(conn, keys)
        role = co.owner_role if carried == "owner" else co.roles[carried]
        _, m = await carrying(conn, co, role)
        p = await plant_person(conn, co.id)
        await listed(conn, keys, table, p)
    expected = OPERATOR if table == "platform_operators" else "ck_memberships_not_support_staff"
    await refused_move(migrator, m, p, expected)


async def test_k1_a_move_of_a_plain_role_to_an_operator_passes(
    migrator: AsyncEngine, keys: Keys
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.roles["std"])
        p = await plant_person(conn, co.id)
        await listed(conn, keys, "platform_operators", p)
    await accepted_move(migrator, m, p)


async def test_k1_only_the_moved_membership_is_read_not_the_old_persons_others(
    migrator: AsyncEngine, keys: Keys
) -> None:
    """Q owns tenant A through M_A and holds a plain role in B through M_B:
    moving M_B to an operator passes."""
    async with migrator.begin() as conn:
        a, b = await company(conn, keys), await company(conn, keys)
        q = await plant_person(conn, a.id)
        await assign(
            conn, a.id, a.t.main, await plant_membership(conn, a.id, a.t.main, q), a.owner_role
        )
        await add_tenant_member(conn, b.id, q, "active")
        m_b = await plant_membership(conn, b.id, b.b, q)
        await assign(conn, b.id, b.b, m_b, b.roles["std"])
        p = await plant_person(conn, b.id)
        await listed(conn, keys, "platform_operators", p)
    await accepted_move(migrator, m_b, p)


async def test_k1i_a_move_beside_listing_its_new_person(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.owner_role)
        p = await plant_person(conn, co.id)
        return mover(m, p), lister(keys, "platform_operators", p)

    await both_orders(migrator, admin, plant, OPERATOR)


async def test_k1ii_a_move_to_an_operator_beside_an_owner_assignment_on_it(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.roles["std"])
        p = await plant_person(conn, co.id)
        await listed(conn, keys, "platform_operators", p)
        return mover(m, p), assigner(co, co.b, m, co.owner_role)

    await both_orders(migrator, admin, plant, OPERATOR)


async def test_k1iii_a_move_to_an_operator_beside_an_owner_key_into_its_role(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.roles["std"])
        p = await plant_person(conn, co.id)
        await listed(conn, keys, "platform_operators", p)
        return mover(m, p), key_adder(co, co.roles["std"], APPROVE)

    await both_orders(migrator, admin, plant, OPERATOR)


async def test_k1iv_an_assignment_to_an_operator_beside_an_owner_key_into_the_role(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        p = await plant_person(conn, co.id)
        m = await plant_membership(conn, co.id, co.b, p)
        await listed(conn, keys, "platform_operators", p)
        return assigner(co, co.b, m, co.roles["std"]), key_adder(co, co.roles["std"], APPROVE)

    await both_orders(migrator, admin, plant, OPERATOR)


async def test_k1v_listing_a_person_beside_an_owner_key_into_a_role_they_hold(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        p, _ = await carrying(conn, co, co.roles["std"])
        return lister(keys, "platform_operators", p), key_adder(co, co.roles["std"], APPROVE)

    await both_orders(migrator, admin, plant, OPERATOR)


# ---- K2: no critical role reaches a service account, and the move is announced -----


async def announced(engine: AsyncEngine, co: Company, s: uuid.UUID) -> int:
    async with engine.connect() as conn:
        return int(
            await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.outbox_events WHERE tenant_id = :t"
                    " AND event_type = 'platform.service_principal.grants_changed'"
                    " AND aggregate_id = :s"
                ),
                {"t": co.id, "s": s},
            )
            or 0
        )


@pytest.mark.parametrize("carried", ["owner", "critical"])
async def test_k2_a_move_handing_a_critical_role_to_a_service_account_is_refused(
    migrator: AsyncEngine, keys: Keys, carried: str
) -> None:
    """org-and-principals R6.4 through RB50's open door."""
    async with migrator.begin() as conn:
        co = await company(conn, keys)
        if carried == "owner":
            role = co.owner_role
        else:
            role = await plant_role(conn, co.id, "r_crit", {keys.critical: "workspace"})
        _, m = await carrying(conn, co, role)
        s = await service_account(conn, co)
    before = await announced(migrator, co, s)
    await refused_move(migrator, m, s, SERVICE)
    assert await announced(migrator, co, s) == before


async def test_k2_a_move_of_a_plain_role_to_a_service_account_passes_and_is_announced_once(
    migrator: AsyncEngine, keys: Keys
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.roles["std"])
        s = await service_account(conn, co)
    before = await announced(migrator, co, s)
    await accepted_move(migrator, m, s)
    assert await announced(migrator, co, s) == before + 1


async def test_k2_a_move_of_a_membership_with_no_assignment_is_not_announced(
    migrator: AsyncEngine, keys: Keys
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn, keys)
        _, m = await carrying(conn, co)
        s = await service_account(conn, co)
    before = await announced(migrator, co, s)
    await accepted_move(migrator, m, s)
    assert await announced(migrator, co, s) == before


async def test_k2i_a_move_to_a_service_account_beside_a_critical_key_into_its_role(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.roles["std"])
        s = await service_account(conn, co)
        return mover(m, s), key_adder(co, co.roles["std"], keys.critical, "workspace")

    await both_orders(migrator, admin, plant, SERVICE)


async def test_k2ii_a_move_to_a_service_account_beside_an_owner_assignment_on_it(
    migrator: AsyncEngine, admin: AsyncEngine, keys: Keys
) -> None:
    async def plant(conn: AsyncConnection) -> tuple[Write, Write]:
        co = await company(conn, keys)
        _, m = await carrying(conn, co, co.roles["std"])
        s = await service_account(conn, co)
        return mover(m, s), assigner(co, co.b, m, co.owner_role)

    await both_orders(migrator, admin, plant, SERVICE)


# ---- K3: a move never leaves the tenant without an active owner ---------------------


@pytest.mark.parametrize("tenant_status", ["active", "locked"])
async def test_k3_moving_the_last_active_owner_to_an_invited_member_is_refused(
    migrator: AsyncEngine, keys: Keys, tenant_status: str
) -> None:
    """R6.7 (RB20): Q is the only active owner, through M; P is invited."""
    async with migrator.begin() as conn:
        co = await company(conn, keys, owners=0)
        _, m = await carrying(conn, co, co.owner_role)
        p = await plant_person(conn, co.id, status="invited")
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = :s WHERE id = :t"),
            {"s": tenant_status, "t": co.id},
        )
    await refused_move(migrator, m, p, LAST_OWNER)


@pytest.mark.parametrize("case", ["to_an_active_member", "without_tenant_owner"])
async def test_k3_a_move_keeping_an_active_owner_passes(
    migrator: AsyncEngine, keys: Keys, case: str
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn, keys, owners=0 if case == "to_an_active_member" else 1)
        role = co.owner_role if case == "to_an_active_member" else co.roles["std"]
        _, m = await carrying(conn, co, role)
        p = await plant_person(
            conn, co.id, status="active" if case == "to_an_active_member" else "invited"
        )
    await accepted_move(migrator, m, p)


# ---- K4: a move below two owner-key holders is told -----------------------------------


@pytest.mark.parametrize(("status", "told"), [("invited", 1), ("active", 0)])
async def test_k4_a_move_below_two_holders_of_an_owner_key_is_told_once(
    migrator: AsyncEngine, keys: Keys, status: str, told: int
) -> None:
    """R3.12 (RB40): two active owners, Q through M and O; M moves to P."""
    async with migrator.begin() as conn:
        co = await company(conn, keys, owners=1)
        _, m = await carrying(conn, co, co.owner_role)
        p = await plant_person(conn, co.id, status=status)  # type: ignore[arg-type]
    await accepted_move(migrator, m, p)
    async with migrator.connect() as conn:
        events = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.outbox_events WHERE tenant_id = :t"
                " AND event_type = 'platform.tenant.owner_coverage_low'"
            ),
            {"t": co.id},
        )
        since = await conn.scalar(
            sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
            {"t": co.id},
        )
    assert (events, since is not None) == (told, bool(told))
