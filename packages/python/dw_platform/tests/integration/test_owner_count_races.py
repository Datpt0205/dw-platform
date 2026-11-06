"""Integration: the last active owner under a removal of the recipient and a
reactivation (tenant-rbac ticket 14; R6.7, RB20).

Every side runs as `dw_migrator` (the last-owner rule holds for every writer),
on real connections through `dw_platform.testing.races`: the first side writes
and holds, later sides run until they wait on a lock or are done, then the
first commits; no fixed sleep. After each case the tenant keeps at least one
active owner; a refusal is 23514 `ck_role_assignments_last_owner` and leaves
the refused side's rows as they were; `40P01` is counted apart and is 0
except in the interleaved cases, where exactly one side is aborted.
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
    interleaved,
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
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    unregister_key,
)

pytestmark = pytest.mark.integration

LAST_OWNER = "ck_role_assignments_last_owner"


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


@pytest.fixture
async def std_key(migrator: AsyncEngine) -> AsyncIterator[str]:
    key = f"test.oc{uuid.uuid4().hex[:10]}.std"
    async with migrator.begin() as conn:
        await register_key(conn, key)
    yield key
    async with migrator.begin() as conn:
        await unregister_key(conn, key)


@dataclass
class Company:
    t: PlantedTenant
    owner_role: uuid.UUID

    @property
    def id(self) -> uuid.UUID:
        return self.t.tenant_id

    @property
    def main(self) -> uuid.UUID:
        return self.t.main

    @property
    def b(self) -> uuid.UUID:
        return self.t.workspaces[1]


async def company(conn: AsyncConnection) -> Company:
    t = await plant_tenant(conn, workspaces=2)
    return Company(t, await role_id(conn, t.tenant_id, "tenant_owner"))


async def set_tenant_status(conn: AsyncConnection, co: Company, status: str) -> None:
    await conn.execute(
        sa.text("UPDATE platform.tenants SET status = :s WHERE id = :t"), {"s": status, "t": co.id}
    )


async def member(
    conn: AsyncConnection,
    co: Company,
    workspace: uuid.UUID | None = None,
    *,
    status: str = "active",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A person and their membership: (person, membership)."""
    person = await plant_person(conn, co.id, status=status)  # type: ignore[arg-type]
    return person, await plant_membership(conn, co.id, workspace or co.main, person)


async def owner(
    conn: AsyncConnection, co: Company, workspace: uuid.UUID | None = None
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An active owner: (person, membership, assignment)."""
    person, membership = await member(conn, co, workspace)
    return (
        person,
        membership,
        await assign(conn, co.id, workspace or co.main, membership, co.owner_role),
    )


async def set_status(conn: AsyncConnection, co: Company, person: uuid.UUID, status: str) -> None:
    await conn.execute(
        sa.text(
            "UPDATE platform.tenant_members SET status = :s WHERE tenant_id = :t AND user_id = :u"
        ),
        {"s": status, "t": co.id, "u": person},
    )


def statuser(co: Company, person: uuid.UUID, status: str) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await set_status(conn, co, person, status)

    return go


def assigner(co: Company, workspace: uuid.UUID, membership: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await assign(conn, co.id, workspace, membership, co.owner_role)

    return go


def revoker(assignment: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
        )

    return go


def remover(co: Company, person: uuid.UUID) -> Write:
    """The person's company row deleted (its memberships and assignments cascade)."""

    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": co.id, "u": person},
        )

    return go


def mover(m: uuid.UUID, to: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("UPDATE platform.memberships SET user_id = :u WHERE id = :m"), {"u": to, "m": m}
        )

    return go


def both(*writes: Write) -> Write:
    async def go(conn: AsyncConnection) -> None:
        for write in writes:
            await write(conn)

    return go


async def active_owners(engine: AsyncEngine, co: Company) -> set[uuid.UUID]:
    async with engine.connect() as conn:
        return set(
            await conn.scalars(sa.text("SELECT platform.active_tenant_owners(:t)"), {"t": co.id})
        )


async def has_row(engine: AsyncEngine, sql: str, **params: object) -> bool:
    async with engine.connect() as conn:
        return bool(await conn.scalar(sa.text(f"SELECT EXISTS ({sql})"), params))


def refused_by_last_owner(error: BaseException | None) -> None:
    assert error is not None, "accepted"
    found = cause(error)
    assert getattr(found, "sqlstate", None) == "23514", found
    assert getattr(found, "constraint_name", None) == LAST_OWNER, found


# ---- K1: the recipient's company row removed beside a handover -----------------------


@dataclass
class Handover:
    co: Company
    p: uuid.UUID
    m_p: uuid.UUID
    q_assignment: uuid.UUID

    def write(self) -> Write:
        return both(assigner(self.co, self.co.main, self.m_p), revoker(self.q_assignment))


async def handover_world(conn: AsyncConnection, tenant_status: str = "active") -> Handover:
    """Q the only active owner; P active with M_P in main, not an owner."""
    co = await company(conn)
    _, _, q_assignment = await owner(conn, co)
    p, m_p = await member(conn, co)
    await set_tenant_status(conn, co, tenant_status)
    return Handover(co, p, m_p, q_assignment)


@pytest.mark.parametrize("tenant_status", ["active", "locked"])
async def test_k1_removing_the_recipient_after_a_handover_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine, tenant_status: str
) -> None:
    """(i): the handover holds; the removal waits on P's membership, then counts."""
    async with migrator.begin() as conn:
        w = await handover_world(conn, tenant_status)
    raced = await race(migrator, admin, w.write(), remover(w.co, w.p))
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, w.co) == {w.p}


async def test_k1_a_handover_after_the_recipient_is_removed_fails_at_its_first_statement(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(ii), closed before this ticket: the assignment names a membership gone."""
    async with migrator.begin() as conn:
        w = await handover_world(conn)
    raced = await race(migrator, admin, remover(w.co, w.p), w.write())
    assert raced.first is None and raced.deadlocks == 0
    assert sqlstate(raced.second) == "23503", cause(raced.second)
    assert await has_row(
        migrator, "SELECT 1 FROM platform.role_assignments WHERE id = :a", a=w.q_assignment
    )
    assert len(await active_owners(migrator, w.co)) == 1


async def test_k1_removing_an_owner_given_a_second_owner_assignment_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(iii): P owns through M_P1; A gives M_P2 `tenant_owner` and removes Q."""
    async with migrator.begin() as conn:
        co = await company(conn)
        p, _, _ = await owner(conn, co)
        m_p2 = await plant_membership(conn, co.id, co.b, p)
        _, _, q_assignment = await owner(conn, co)
    handover = both(assigner(co, co.b, m_p2), revoker(q_assignment))
    raced = await race(migrator, admin, handover, remover(co, p))
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, co) == {p}


async def test_k1_a_second_owner_assignment_cannot_slip_past_a_removal_waiting_on_a_row(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(iv): P the only owner through A_P1, M_P2 without one. C holds A_P1 FOR
    SHARE; the removal of P waits on it; T gives M_P2 `tenant_owner` (waits on
    the removal's lock on M_P2, or is done and commits); C commits; the
    removal is refused and P stays an owner."""
    async with migrator.begin() as conn:
        co = await company(conn)
        p, _, a_p1 = await owner(conn, co)
        m_p2 = await plant_membership(conn, co.id, co.b, p)
    errors: dict[str, BaseException] = {}
    async with (
        migrator.connect() as c,
        migrator.connect() as b,
        migrator.connect() as t,
    ):
        await c.begin()
        await c.execute(
            sa.text("SELECT 1 FROM platform.role_assignments WHERE id = :a FOR SHARE"), {"a": a_p1}
        )

        async def side(name: str, conn: AsyncConnection, write: Write) -> None:
            try:
                await write(conn)
                await conn.commit()
            except DBAPIError as error:
                errors[name] = error
                await conn.rollback()

        await b.begin()
        b_task = asyncio.create_task(side("removal", b, remover(co, p)))
        assert await until_waiting(admin, await backend_pid(b), b_task)
        await t.begin()
        t_task = asyncio.create_task(side("assignment", t, assigner(co, co.b, m_p2)))
        await until_waiting(admin, await backend_pid(t), t_task)
        await c.commit()
        await asyncio.gather(b_task, t_task)
    assert set(errors) == {"removal"}, errors
    refused_by_last_owner(errors["removal"])
    assert await active_owners(migrator, co) == {p}


async def test_k1_a_removal_between_the_handovers_two_statements_waits_and_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        w = await handover_world(conn)
    errors = await interleaved(
        migrator,
        admin,
        assigner(w.co, w.co.main, w.m_p),
        remover(w.co, w.p),
        revoker(w.q_assignment),
    )
    assert len(errors) == 1 and sqlstate(errors[0]) != "40P01", errors
    refused_by_last_owner(errors[0])
    assert await active_owners(migrator, w.co) == {w.p}


async def test_k1_removing_the_recipients_user_after_a_handover_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async def remove_user(conn: AsyncConnection) -> None:
        await conn.execute(sa.text("DELETE FROM platform.users WHERE id = :u"), {"u": w.p})

    async with migrator.begin() as conn:
        w = await handover_world(conn)
    raced = await race(migrator, admin, w.write(), remove_user)
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, w.co) == {w.p}


async def test_k1_removing_someone_else_beside_a_handover_passes(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        w = await handover_world(conn)
        r, _ = await member(conn, w.co)
    raced = await race(migrator, admin, w.write(), remover(w.co, r))
    assert (raced.first, raced.second) == (None, None)
    assert await active_owners(migrator, w.co) == {w.p}


async def test_k1_removing_the_membership_itself_beside_a_handover_by_role_change_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine, std_key: str
) -> None:
    """Closed before this ticket by the row lock of the DELETE itself."""
    async with migrator.begin() as conn:
        w = await handover_world(conn)
        plain = await plant_role(conn, w.co.id, "r_plain", {std_key: "workspace"})
        other = await assign(conn, w.co.id, w.co.main, w.m_p, plain)

    async def to_owner(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("UPDATE platform.role_assignments SET role_id = :r WHERE id = :a"),
            {"r": w.co.owner_role, "a": other},
        )

    async def remove_membership(conn: AsyncConnection) -> None:
        await conn.execute(sa.text("DELETE FROM platform.memberships WHERE id = :m"), {"m": w.m_p})

    raced = await race(migrator, admin, both(to_owner, revoker(w.q_assignment)), remove_membership)
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, w.co) == {w.p}


# ---- K2: a not-yet-active owner's assignment removed beside a reactivation ------------


@dataclass
class Reactivation:
    co: Company
    x: uuid.UUID
    q: uuid.UUID
    m_q: uuid.UUID
    q_assignment: uuid.UUID

    def write(self) -> Write:
        """Reactivate Q, then suspend X, in one transaction."""
        return both(statuser(self.co, self.q, "active"), statuser(self.co, self.x, "suspended"))


async def reactivation_world(conn: AsyncConnection, tenant_status: str = "active") -> Reactivation:
    """X the only active owner; Q holds `tenant_owner` through M_Q, suspended."""
    co = await company(conn)
    x, _, _ = await owner(conn, co)
    q, m_q, q_assignment = await owner(conn, co, co.b)
    await set_status(conn, co, q, "suspended")
    await set_tenant_status(conn, co, tenant_status)
    return Reactivation(co, x, q, m_q, q_assignment)


@pytest.mark.parametrize("tenant_status", ["active", "locked"])
async def test_k2_removing_a_suspended_owner_after_their_reactivation_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine, tenant_status: str
) -> None:
    """(i)."""
    async with migrator.begin() as conn:
        w = await reactivation_world(conn, tenant_status)
    raced = await race(migrator, admin, w.write(), revoker(w.q_assignment))
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await has_row(
        migrator, "SELECT 1 FROM platform.role_assignments WHERE id = :a", a=w.q_assignment
    )
    assert await active_owners(migrator, w.co) == {w.q}


async def test_k2_a_reactivation_after_the_removal_is_refused_at_its_suspension(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(ii), closed before this ticket by the version row."""
    async with migrator.begin() as conn:
        w = await reactivation_world(conn)
    raced = await race(migrator, admin, revoker(w.q_assignment), w.write())
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, w.co) == {w.x}


async def test_k2_a_removal_between_the_reactivations_two_statements_aborts_exactly_one(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        w = await reactivation_world(conn)
    errors = await interleaved(
        migrator,
        admin,
        statuser(w.co, w.q, "active"),
        revoker(w.q_assignment),
        statuser(w.co, w.x, "suspended"),
    )
    assert len(errors) == 1, errors
    assert sqlstate(errors[0]) in {"23514", "40P01"}, errors[0]
    assert len(await active_owners(migrator, w.co)) == 1


async def test_k2_moving_a_suspended_owners_membership_after_their_reactivation_is_refused(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """The `memberships` branch of ticket 12: M_Q moves to R (invited)."""
    async with migrator.begin() as conn:
        w = await reactivation_world(conn)
        r = await plant_person(conn, w.co.id, status="invited")
    raced = await race(migrator, admin, w.write(), mover(w.m_q, r))
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await has_row(
        migrator,
        "SELECT 1 FROM platform.memberships WHERE id = :m AND user_id = :u",
        m=w.m_q,
        u=w.q,
    )


async def test_k2_removing_an_assignment_whose_membership_was_just_moved_to_an_active_person(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """(iii): Q (suspended) owns through M; A moves M to P (active), then
    suspends X; the removal of the assignment on M reads M's person again."""
    async with migrator.begin() as conn:
        w = await reactivation_world(conn)
        p = await plant_person(conn, w.co.id)
    handover = both(mover(w.m_q, p), statuser(w.co, w.x, "suspended"))
    raced = await race(migrator, admin, handover, revoker(w.q_assignment))
    assert raced.first is None and raced.deadlocks == 0
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, w.co) == {p}


async def test_k2_removing_another_suspended_owner_beside_a_reactivation_passes(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        w = await reactivation_world(conn)
        s, _, s_assignment = await owner(conn, w.co)
        await set_status(conn, w.co, s, "suspended")
    raced = await race(migrator, admin, w.write(), revoker(s_assignment))
    assert (raced.first, raced.second) == (None, None)
    assert await active_owners(migrator, w.co) == {w.q}


# ---- K3: the two locks do not deadlock two removals of the last two owners ------------


@pytest.mark.parametrize("how", ["company_rows", "assignments"])
async def test_k3_two_removals_of_the_last_two_owners_queue_behind_a_tenant_lock(
    migrator: AsyncEngine, admin: AsyncEngine, how: str
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn)
        q1, _, a1 = await owner(conn, co)
        q2, _, a2 = await owner(conn, co)

    async def hold_tenant(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("SELECT 1 FROM platform.tenants WHERE id = :t FOR NO KEY UPDATE"), {"t": co.id}
        )

    first, second = (
        (remover(co, q1), remover(co, q2)) if how == "company_rows" else (revoker(a1), revoker(a2))
    )
    found = await waiting_pair(migrator, admin, hold_tenant, first, second)
    errors = [e for e in found if e is not None]
    assert len(errors) == 1 and sqlstate(errors[0]) != "40P01", errors
    refused_by_last_owner(errors[0])
    assert len(await active_owners(migrator, co)) == 1


# ---- K4: no wait for a foreign key, no deadlock beside ticket 08 ----------------------


def new_workspace(co: Company) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, :s, :s)"
            ),
            {"w": uuid.uuid4(), "t": co.id, "s": f"ws-{uuid.uuid4().hex[:8]}"},
        )

    return go


async def k4_world(conn: AsyncConnection) -> tuple[Company, uuid.UUID, uuid.UUID]:
    """An active owner; R, an active member; S, a suspended owner: (co, R, S's assignment)."""
    co = await company(conn)
    await owner(conn, co)
    r, _ = await member(conn, co)
    s, _, s_assignment = await owner(conn, co, co.b)
    await set_status(conn, co, s, "suspended")
    return co, r, s_assignment


@pytest.mark.parametrize("first", ["remove_company_row", "remove_suspended_owner"])
async def test_k4_an_open_removal_does_not_hold_up_a_foreign_key_to_the_tenant(
    migrator: AsyncEngine, admin: AsyncEngine, first: str
) -> None:
    async with migrator.begin() as conn:
        co, r, s_assignment = await k4_world(conn)
    write = remover(co, r) if first == "remove_company_row" else revoker(s_assignment)
    raced = await race(migrator, admin, write, new_workspace(co))
    assert (raced.first, raced.second) == (None, None)
    assert raced.second_done_before_commit and not raced.second_waited


@pytest.mark.parametrize("second", ["remove_company_row", "remove_suspended_owner"])
async def test_k4_a_removal_beside_a_fall_below_two_adds_no_deadlock(
    migrator: AsyncEngine, admin: AsyncEngine, second: str
) -> None:
    async with migrator.begin() as conn:
        co, r, s_assignment = await k4_world(conn)
        keys = await conn.scalar(sa.text("SELECT platform.owner_permission_keys()"))
        admins = await plant_role(conn, co.id, "r_admins", dict.fromkeys(keys, "tenant"))
        _, x_membership = await member(conn, co)
        x_assignment = await assign(conn, co.id, co.main, x_membership, admins)
    async with migrator.connect() as conn:
        assert (
            await conn.scalar(
                sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
                {"t": co.id},
            )
            is None
        )
        counts = {
            k: await conn.scalar(
                sa.text("SELECT count(*) FROM platform.checker_candidates(:t, :k, NULL)"),
                {"t": co.id, "k": k},
            )
            for k in keys
        }
    assert counts["platform.roles.write"] == 2 and all(n >= 2 for n in counts.values()), counts
    write = remover(co, r) if second == "remove_company_row" else revoker(s_assignment)
    raced = await race(migrator, admin, revoker(x_assignment), write)
    assert (raced.first, raced.second) == (None, None), (
        sqlstate(raced.first),
        sqlstate(raced.second),
    )
    assert raced.second_waited
    async with migrator.connect() as conn:
        events = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.outbox_events WHERE tenant_id = :t"
                " AND event_type = 'platform.tenant.owner_coverage_low'"
            ),
            {"t": co.id},
        )
    assert events == 1
