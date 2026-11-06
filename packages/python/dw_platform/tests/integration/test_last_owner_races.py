"""Integration: the last active owner under a suspension beside a write that
makes the suspended person an owner (tenant-rbac ticket 13; R6.7, RB20).

Every side runs as `dw_migrator` (the last-owner rule holds for every writer).
A suspension is `UPDATE platform.tenant_members SET status = 'suspended'`. The
concurrent cases run on real connections: the first writes and holds its
transaction open, the second starts in a task until it waits on a lock
(`pg_stat_activity`, read as the superuser) or is done, then the first commits;
no fixed sleep. After each case the tenant keeps at least one active owner,
and every refusal is 23514 `ck_role_assignments_last_owner`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.races import Write, cause, interleaved, race, sqlstate, waiting_pair
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    role_id,
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


@dataclass
class Company:
    t: PlantedTenant
    owner_role: uuid.UUID

    @property
    def id(self) -> uuid.UUID:
        return self.t.tenant_id

    @property
    def b(self) -> uuid.UUID:
        return self.t.workspaces[1]


async def company(conn: AsyncConnection, status: str = "active") -> Company:
    t = await plant_tenant(conn, workspaces=2, status=status)
    return Company(t, await role_id(conn, t.tenant_id, "tenant_owner"))


async def owner(
    conn: AsyncConnection, co: Company, workspace: uuid.UUID | None = None
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An active owner: (person, membership, assignment)."""
    person = await plant_person(conn, co.id)
    membership = await plant_membership(conn, co.id, workspace or co.t.main, person)
    made = await assign(conn, co.id, workspace or co.t.main, membership, co.owner_role)
    return person, membership, made


def suspender(co: Company, person: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_members SET status = 'suspended'"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"t": co.id, "u": person},
        )

    return go


def mover(m: uuid.UUID, to: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("UPDATE platform.memberships SET user_id = :u WHERE id = :m"), {"u": to, "m": m}
        )

    return go


def revoker(assignment: uuid.UUID) -> Write:
    async def go(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
        )

    return go


def handover(co: Company, p_membership: uuid.UUID, q_assignment: uuid.UUID) -> tuple[Write, Write]:
    """Ownership handed over in one transaction: `tenant_owner` to P, then Q's removed."""

    async def to_p(conn: AsyncConnection) -> None:
        await assign(conn, co.id, co.t.main, p_membership, co.owner_role)

    async def both(conn: AsyncConnection) -> None:
        await to_p(conn)
        await revoker(q_assignment)(conn)

    return to_p, both


async def status_of(engine: AsyncEngine, co: Company, person: uuid.UUID) -> str:
    async with engine.connect() as conn:
        return str(
            await conn.scalar(
                sa.text(
                    "SELECT status FROM platform.tenant_members"
                    " WHERE tenant_id = :t AND user_id = :u"
                ),
                {"t": co.id, "u": person},
            )
        )


async def active_owners(engine: AsyncEngine, co: Company) -> int:
    async with engine.connect() as conn:
        return int(
            await conn.scalar(
                sa.text("SELECT count(*) FROM platform.active_tenant_owners(:t)"), {"t": co.id}
            )
            or 0
        )


def refused_by_last_owner(error: BaseException | None) -> None:
    assert error is not None, "accepted"
    found = cause(error)
    assert getattr(found, "sqlstate", None) == "23514", found
    assert getattr(found, "constraint_name", None) == LAST_OWNER, found


# ---- K1: a membership moved to P beside P's suspension ------------------------------


async def _k1(conn: AsyncConnection, tenant_status: str) -> tuple[Company, uuid.UUID, uuid.UUID]:
    """Q the only active owner through M (workspace B); P active, no membership in B."""
    co = await company(conn)
    _, m, _ = await owner(conn, co, co.b)
    p = await plant_person(conn, co.id)
    await conn.execute(
        sa.text("UPDATE platform.tenants SET status = :s WHERE id = :t"),
        {"s": tenant_status, "t": co.id},
    )
    return co, m, p


@pytest.mark.parametrize("tenant_status", ["active", "locked"])
@pytest.mark.parametrize(
    "move_first", [True, False], ids=["move_then_suspend", "suspend_then_move"]
)
async def test_k1_a_move_to_p_beside_suspending_p_keeps_an_active_owner(
    migrator: AsyncEngine, admin: AsyncEngine, tenant_status: str, move_first: bool
) -> None:
    async with migrator.begin() as conn:
        co, m, p = await _k1(conn, tenant_status)
    move, suspend = mover(m, p), suspender(co, p)
    raced = await race(migrator, admin, *((move, suspend) if move_first else (suspend, move)))
    assert raced.first is None
    refused_by_last_owner(raced.second)
    assert await status_of(migrator, co, p) == ("active" if move_first else "suspended")
    assert await active_owners(migrator, co) == 1


async def test_k1_suspending_someone_else_beside_the_move_passes(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        co, m, p = await _k1(conn, "active")
        r = await plant_person(conn, co.id)
    raced = await race(migrator, admin, mover(m, p), suspender(co, r))
    assert (raced.first, raced.second) == (None, None)
    async with migrator.connect() as conn:
        owners = list(
            await conn.scalars(sa.text("SELECT platform.active_tenant_owners(:t)"), {"t": co.id})
        )
    assert owners == [p]


# ---- K2: ownership handed over in one transaction beside the recipient's suspension --


async def _k2(conn: AsyncConnection) -> tuple[Company, uuid.UUID, uuid.UUID, uuid.UUID]:
    co = await company(conn)
    _, _, q_assignment = await owner(conn, co)
    p = await plant_person(conn, co.id)
    p_membership = await plant_membership(conn, co.id, co.t.main, p)
    return co, p, p_membership, q_assignment


@pytest.mark.parametrize(
    "handover_first", [True, False], ids=["handover_then_suspend", "suspend_then_handover"]
)
async def test_k2_a_handover_beside_suspending_the_recipient_keeps_an_active_owner(
    migrator: AsyncEngine, admin: AsyncEngine, handover_first: bool
) -> None:
    async with migrator.begin() as conn:
        co, p, p_membership, q_assignment = await _k2(conn)
    _, both = handover(co, p_membership, q_assignment)
    suspend = suspender(co, p)
    raced = await race(migrator, admin, *((both, suspend) if handover_first else (suspend, both)))
    assert raced.first is None
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, co) == 1


async def test_k2_a_suspension_between_the_handovers_two_statements_aborts_exactly_one(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """A's first statement; P's suspension in a task until it waits; A's second
    statement and commit. Whichever side Postgres picks is aborted, 23514 or
    40P01; the other passes; one active owner remains."""
    async with migrator.begin() as conn:
        co, p, p_membership, q_assignment = await _k2(conn)
    to_p, _ = handover(co, p_membership, q_assignment)
    errors = await interleaved(migrator, admin, to_p, suspender(co, p), revoker(q_assignment))
    assert len(errors) == 1, errors
    assert sqlstate(errors[0]) in {"23514", "40P01"}, errors[0]
    assert await active_owners(migrator, co) == 1


# ---- K3: two owners' suspensions still queue ------------------------------------------


@pytest.mark.parametrize("first_q", [0, 1])
async def test_k3_suspending_the_last_two_owners_at_once_refuses_the_second(
    migrator: AsyncEngine, admin: AsyncEngine, first_q: int
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn)
        qs = [(await owner(conn, co))[0] for _ in range(2)]
    raced = await race(migrator, admin, suspender(co, qs[first_q]), suspender(co, qs[1 - first_q]))
    assert raced.first is None and raced.second_waited
    assert sqlstate(raced.second) != "40P01"
    refused_by_last_owner(raced.second)
    assert await active_owners(migrator, co) == 1


async def test_k3_two_owner_suspensions_waiting_on_a_third_removal_queue_without_deadlock(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn)
        q1, q2 = (await owner(conn, co))[0], (await owner(conn, co))[0]
        _, _, q3_assignment = await owner(conn, co)
    found = await waiting_pair(
        migrator, admin, revoker(q3_assignment), suspender(co, q1), suspender(co, q2)
    )
    errors = [e for e in found if e is not None]
    assert len(errors) == 1, errors
    refused_by_last_owner(errors[0])
    assert await active_owners(migrator, co) == 1


# ---- K4: no wait for a foreign key, no deadlock beside ticket 08 ----------------------


async def test_k4_a_suspension_does_not_hold_up_a_foreign_key_to_the_tenant(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    async with migrator.begin() as conn:
        co = await company(conn)
        await owner(conn, co)
        r = await plant_person(conn, co.id)

    async def new_workspace(conn: AsyncConnection) -> None:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, :s, :s)"
            ),
            {"w": uuid.uuid4(), "t": co.id, "s": f"ws-{uuid.uuid4().hex[:8]}"},
        )

    raced = await race(migrator, admin, suspender(co, r), new_workspace)
    assert (raced.first, raced.second) == (None, None)
    assert raced.second_done_before_commit and not raced.second_waited


async def test_k4_a_suspension_beside_a_fall_below_two_adds_no_deadlock(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """One owner O and X, who holds both owner keys through a role: exactly two
    holders of `platform.roles.write`. X's assignment goes (held open), R's
    suspension waits on the version row; both pass, one warning."""
    async with migrator.begin() as conn:
        co = await company(conn)
        await owner(conn, co)
        keys = await conn.scalar(sa.text("SELECT platform.owner_permission_keys()"))
        admins = await plant_role(conn, co.id, "r_admins", dict.fromkeys(keys, "tenant"))
        x = await plant_person(conn, co.id)
        x_assignment = await assign(
            conn, co.id, co.t.main, await plant_membership(conn, co.id, co.t.main, x), admins
        )
        r = await plant_person(conn, co.id)
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
    raced = await race(migrator, admin, revoker(x_assignment), suspender(co, r))
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
        since = await conn.scalar(
            sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
            {"t": co.id},
        )
    assert (events, since is not None) == (1, True)
