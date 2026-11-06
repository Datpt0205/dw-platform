"""Integration: a `setup` tenant opens only after an owner loss beside it
commits (tenant-rbac ticket 15; R3.10, R6.7, RB20, RB38).

Every side runs as `dw_migrator`, on real connections through
`dw_platform.testing.races`. Each case plants a fresh `setup` tenant whose
owners are invited and activated as `test_tenant_roles.py` does. After each
case: an `active` tenant has an active owner; a tenant opened through
`complete_tenant_setup` has exactly one `platform.tenant.setup_completed`
audit naming exactly the two owners the case expects; a tenant still `setup`
has none. `40P01` is counted and is 0 except in K1 (d).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.races import (
    Write,
    backend_pid,
    cause,
    race,
    sqlstate,
    until_waiting,
    waiting_pair,
)
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_tenant,
    role_id,
)

pytestmark = pytest.mark.integration


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
class Setup:
    t: PlantedTenant
    owner_role: uuid.UUID

    @property
    def id(self) -> uuid.UUID:
        return self.t.tenant_id


async def setup_tenant(conn: AsyncConnection) -> Setup:
    t = await plant_tenant(conn, status="setup")
    return Setup(t, await role_id(conn, t.tenant_id, "tenant_owner"))


async def invited_owner(
    conn: AsyncConnection, s: Setup, status: str = "invited"
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A member (invited unless said) holding `tenant_owner`: (person, membership, assignment)."""
    person = await plant_person(conn, s.id, status=status)  # type: ignore[arg-type]
    membership = await plant_membership(conn, s.id, s.t.main, person)
    return person, membership, await assign(conn, s.id, s.t.main, membership, s.owner_role)


def statuser(s: Setup, person: uuid.UUID, status: str) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_members SET status = :s"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"s": status, "t": s.id, "u": person},
        )

    return go


def revoker(assignment: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
        )

    return go


def assigner(s: Setup, membership: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await assign(conn, s.id, s.t.main, membership, s.owner_role)

    return go


def mover(m: uuid.UUID, to: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("UPDATE platform.memberships SET user_id = :u WHERE id = :m"), {"u": to, "m": m}
        )

    return go


def opener(s: Setup) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'active' WHERE id = :t"), {"t": s.id}
        )

    return go


def remover(s: Setup, person: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": s.id, "u": person},
        )

    return go


def both(*writes: Write) -> Write:
    async def go(conn: AsyncConnection) -> None:
        for write in writes:
            await write(conn)

    return go


@dataclass
class State:
    status: str
    owners: set[uuid.UUID]
    audits: list[set[str]]


async def state(engine: AsyncEngine, s: Setup) -> State:
    async with engine.connect() as conn:
        status = await conn.scalar(
            sa.text("SELECT status FROM platform.tenants WHERE id = :t"), {"t": s.id}
        )
        owners = set(
            await conn.scalars(sa.text("SELECT platform.active_tenant_owners(:t)"), {"t": s.id})
        )
        rows = await conn.scalars(
            sa.text(
                "SELECT details->'owner_ids' FROM platform.audit_events"
                " WHERE tenant_id = :t AND action = 'platform.tenant.setup_completed'"
            ),
            {"t": s.id},
        )
        audits = [set(map(str, ids)) for ids in rows]
    return State(str(status), owners, audits)


def refused_by(error: BaseException | None, constraint: str) -> None:
    assert error is not None, "accepted"
    found = cause(error)
    assert getattr(found, "sqlstate", None) == "23514", found
    assert getattr(found, "constraint_name", None) == constraint, found


Owner = tuple[uuid.UUID, uuid.UUID, uuid.UUID]  # (person, membership, assignment)


async def o1_active_o2_invited(conn: AsyncConnection) -> tuple[Setup, Owner, Owner]:
    """O1 an active owner (activated alone: the tenant stays `setup`), O2 an invited owner."""
    s = await setup_tenant(conn)
    o1 = await invited_owner(conn, s)
    o2 = await invited_owner(conn, s)
    await statuser(s, o1[0], "active")(conn)
    return s, o1, o2


# ---- K1: an activation beside the loss of an owner already there ----------------------


@pytest.mark.parametrize("loss", ["suspend_o1", "remove_o1_assignment"])
async def test_k1_an_activation_waiting_on_an_owner_loss_leaves_the_tenant_in_setup(
    migrator: AsyncEngine, admin: AsyncEngine, loss: str
) -> None:
    """(a), (b)."""
    async with migrator.begin() as conn:
        s, o1, o2 = await o1_active_o2_invited(conn)
    first = statuser(s, o1[0], "suspended") if loss == "suspend_o1" else revoker(o1[2])
    raced = await race(migrator, admin, first, statuser(s, o2[0], "active"))
    assert (raced.first, raced.second, raced.deadlocks) == (None, None, 0)
    assert raced.second_waited
    after = await state(migrator, s)
    assert (after.status, after.audits) == ("setup", [])


async def test_k1_the_update_way_to_open_waits_on_an_owner_loss_and_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(c): two active owners, not opened (O2's membership moved to Y)."""
    async with migrator.begin() as conn:
        s, o1, o2 = await o1_active_o2_invited(conn)
        y = await plant_person(conn, s.id)
        await mover(o2[1], y)(conn)
    assert (await state(migrator, s)).owners == {o1[0], y}
    raced = await race(migrator, admin, statuser(s, o1[0], "suspended"), opener(s))
    assert raced.first is None and raced.deadlocks == 0
    refused_by(raced.second, "ck_tenants_status_transition")
    assert (await state(migrator, s)).status == "setup"


async def test_k1_moves_then_an_update_beside_suspending_the_new_owners_aborts_a_side(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(d): no active owner; A moves M2 to P1 and M3 to P2, then opens by
    UPDATE; B and C suspend P1 and P2, each waiting; at least one side is
    aborted with 40P01, and the tenant is `active` only with both as owners."""
    async with migrator.begin() as conn:
        s = await setup_tenant(conn)
        _, m2, _ = await invited_owner(conn, s)
        _, m3, _ = await invited_owner(conn, s)
        p1, p2 = await plant_person(conn, s.id), await plant_person(conn, s.id)
    errors: list[BaseException] = []
    async with migrator.connect() as a, migrator.connect() as b, migrator.connect() as c:
        await a.begin()
        await both(mover(m2, p1), mover(m3, p2))(a)

        async def side(conn: AsyncConnection, write: Write) -> None:
            try:
                await write(conn)
                await conn.commit()
            except DBAPIError as error:
                errors.append(error)
                await conn.rollback()

        tasks = []
        for conn, person in ((b, p1), (c, p2)):
            await conn.begin()
            task = asyncio.create_task(side(conn, statuser(s, person, "suspended")))
            assert await until_waiting(admin, await backend_pid(conn), task)
            tasks.append(task)
        a_alive = True
        try:
            await opener(s)(a)
        except DBAPIError as error:
            errors.append(error)
            a_alive = False
            await a.rollback()
        if a_alive:
            try:
                await a.commit()
            except DBAPIError as error:
                errors.append(error)
                await a.rollback()
        await asyncio.gather(*tasks)
    assert any(sqlstate(e) == "40P01" for e in errors), errors
    after = await state(migrator, s)
    if after.status == "active":
        assert after.owners == {p1, p2}
    else:
        assert after.status == "setup"


async def test_k1_an_owner_loss_waiting_on_an_activation_is_judged_in_the_open_tenant(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """The reverse of (a): O2 activated first (the tenant opens), O1's suspension
    waits and is judged under R6.7: both pass, O2 the one active owner."""
    async with migrator.begin() as conn:
        s, o1, o2 = await o1_active_o2_invited(conn)
    raced = await race(
        migrator, admin, statuser(s, o2[0], "active"), statuser(s, o1[0], "suspended")
    )
    assert (raced.first, raced.second, raced.deadlocks) == (None, None, 0)
    after = await state(migrator, s)
    assert (after.status, after.owners) == ("active", {o2[0]})
    assert after.audits == [{str(o1[0]), str(o2[0])}]


# ---- K2: an activation beside the loss of someone it makes an owner -------------------


async def test_k2_suspending_p_before_an_owner_assignment_to_p_keeps_the_tenant_in_setup(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(a), V1: P active and not an owner."""
    async with migrator.begin() as conn:
        s, _, _ = await o1_active_o2_invited(conn)
        p = await plant_person(conn, s.id)
        m_p = await plant_membership(conn, s.id, s.t.main, p)
    raced = await race(migrator, admin, statuser(s, p, "suspended"), assigner(s, m_p))
    assert (raced.first, raced.second, raced.deadlocks) == (None, None, 0)
    after = await state(migrator, s)
    assert (after.status, after.audits) == ("setup", [])


async def test_k2_removing_a_suspended_owner_before_their_reactivation_keeps_the_tenant_in_setup(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(b), V2: Q suspended from the start, holding `tenant_owner`."""
    async with migrator.begin() as conn:
        s, _, _ = await o1_active_o2_invited(conn)
        q, _, q_assignment = await invited_owner(conn, s, status="suspended")
    raced = await race(migrator, admin, revoker(q_assignment), statuser(s, q, "active"))
    assert (raced.first, raced.second, raced.deadlocks) == (None, None, 0)
    after = await state(migrator, s)
    assert (after.status, after.audits) == ("setup", [])


async def test_k2_removing_the_recipient_after_an_opening_handover_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(c), ticket 14's membership lock in a `setup` tenant: A gives P
    `tenant_owner` (the tenant opens) and suspends O1; P's removal waits and is
    refused."""
    async with migrator.begin() as conn:
        s, o1, _ = await o1_active_o2_invited(conn)
        p = await plant_person(conn, s.id)
        m_p = await plant_membership(conn, s.id, s.t.main, p)
    a = both(assigner(s, m_p), statuser(s, o1[0], "suspended"))
    raced = await race(migrator, admin, a, remover(s, p))
    assert raced.first is None and raced.deadlocks == 0
    refused_by(raced.second, "ck_role_assignments_last_owner")
    after = await state(migrator, s)
    assert (after.status, after.owners) == ("active", {p})
    assert after.audits == [{str(o1[0]), str(p)}]


# ---- K3: a loss waiting on an activation is counted under R6.7 -------------------------


async def test_k3_suspending_o1_behind_an_activation_that_suspended_o2_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(i): A activates O2 (the tenant opens) and suspends O2; O1's suspension
    waits at the tenant row and, the tenant now `active`, is refused."""
    async with migrator.begin() as conn:
        s, o1, o2 = await o1_active_o2_invited(conn)
    a = both(statuser(s, o2[0], "active"), statuser(s, o2[0], "suspended"))
    raced = await race(migrator, admin, a, statuser(s, o1[0], "suspended"))
    assert raced.first is None and raced.deadlocks == 0 and raced.second_waited
    refused_by(raced.second, "ck_role_assignments_last_owner")
    after = await state(migrator, s)
    assert (after.status, after.owners) == ("active", {o1[0]})
    assert after.audits == [{str(o1[0]), str(o2[0])}]


async def test_k3_two_suspensions_behind_an_open_activation_refuse_exactly_one(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(ii): A activates O2 and holds; O1's and O2's suspensions wait; A commits."""
    async with migrator.begin() as conn:
        s, o1, o2 = await o1_active_o2_invited(conn)
    found = await waiting_pair(
        migrator,
        admin,
        statuser(s, o2[0], "active"),
        statuser(s, o1[0], "suspended"),
        statuser(s, o2[0], "suspended"),
    )
    errors = [e for e in found if e is not None]
    assert len(errors) == 1 and sqlstate(errors[0]) != "40P01", errors
    refused_by(errors[0], "ck_role_assignments_last_owner")
    after = await state(migrator, s)
    assert after.status == "active" and len(after.owners) == 1
    assert after.audits == [{str(o1[0]), str(o2[0])}]


# ---- K4: the ordinary `setup` flow is unchanged ----------------------------------------


@pytest.mark.parametrize("loss", ["suspend_the_only_active_owner", "remove_the_invited_owner"])
async def test_k4_a_setup_tenant_may_lose_owners_with_no_activation_open(
    migrator: AsyncEngine, loss: str
) -> None:
    """(ii): O1 the only active owner, O2 invited; nothing opens the tenant."""
    async with migrator.begin() as conn:
        s, o1, o2 = await o1_active_o2_invited(conn)
    async with migrator.begin() as conn:
        if loss == "suspend_the_only_active_owner":
            await statuser(s, o1[0], "suspended")(conn)
        else:
            await revoker(o2[2])(conn)
    after = await state(migrator, s)
    assert (after.status, after.audits) == ("setup", [])
