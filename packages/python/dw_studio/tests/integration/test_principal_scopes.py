"""The record reach ledger (record-access ticket 02; revision f6ea6e818d0c).

Raw SQL as the role each criterion names, on a migrated Postgres: the door
`studio.ensure_principal_scope()` and the readers `studio.acl_*` as `dw_app`,
worlds planted as the migrator (every writer but `dw_migrator` is judged by
`platform.rbac_guard()`). A change is committed in one transaction and the
door's first call in the next reads it (R5.2); interleavings use two real
connections and a row lock, never a mock (R5.4).
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    role_id,
)
from dw_platform.testing.record_objects import plant_object
from dw_studio.testing.reach import (
    ACTIONS,
    ARMS,
    Organisation,
    Scope,
    access_key,
    expected_scope,
    plant_random_organisation,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

_ORGANISATIONS = 500
_PER_TRANSACTION = 50


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_engine(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this suite's database: plants as the migrator and reads
    as `dw_app` inside one transaction that rolls back."""
    url = studio_db.admin.rsplit("/", 1)[0] + "/" + studio_db.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


# -- reading the ledger -------------------------------------------------------------

_OBJECT_ARMS = ("own", "tenant")
_READ_REACH = sa.text(
    "SELECT studio.acl_user() AS acl_user, studio.acl_create_own_keys() AS create_own_keys, "
    + ", ".join(
        [
            *(
                f"studio.acl_objects('{a}', '{arm}') AS {a}_{arm}"
                for a in ACTIONS
                for arm in _OBJECT_ARMS
            ),
            *(f"studio.acl_keys('{a}') AS {a}_keys" for a in ACTIONS),
        ]
    )
)
_SETTINGS = sa.text(
    "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"
)
_DOOR = sa.text("SELECT studio.ensure_principal_scope()")
_OWN_ROW = sa.text("SELECT workspace_ids, valid_until, state FROM studio.principal_scopes")


@dataclass(frozen=True)
class Reach:
    user: uuid.UUID | None
    arms: dict[tuple[str, str], frozenset[uuid.UUID]]
    create_own_keys: frozenset[uuid.UUID]

    def arm(self, action: str, arm: str) -> frozenset[uuid.UUID]:
        return self.arms[(action, arm)]

    @property
    def no_reach(self) -> bool:
        return not self.create_own_keys and not any(self.arms.values())

    @property
    def empty(self) -> bool:
        """Every reader's '{}': no valid row behind the connection at all."""
        return self.user is None and self.no_reach


async def read_reach(conn: AsyncConnection) -> Reach:
    row = (await conn.execute(_READ_REACH)).mappings().one()
    return Reach(
        row["acl_user"],
        {(a, arm): frozenset(row[f"{a}_{arm}"]) for a in ACTIONS for arm in ARMS},
        frozenset(row["create_own_keys"]),
    )


async def bind(conn: AsyncConnection, tenant: uuid.UUID, user: uuid.UUID | None) -> None:
    await conn.execute(_SETTINGS, {"t": str(tenant), "u": "" if user is None else str(user)})


async def door(app: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID | None) -> Reach:
    """One Studio transaction as `dw_app`: bind, call the door, read, commit."""
    async with app.begin() as conn:
        await bind(conn, tenant, user)
        await conn.execute(_DOOR)
        return await read_reach(conn)


async def ledger_row(migrator: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID) -> Any:
    async with migrator.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT state, version, epoch, valid_until FROM studio.principal_scopes"
                    " WHERE tenant_id = :t AND principal_id = :u"
                ),
                {"t": tenant, "u": user},
            )
        ).one_or_none()


async def execute(engine: AsyncEngine, sql: str, **values: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text(sql), values)


# -- a company --------------------------------------------------------------------


@dataclass(frozen=True)
class Company:
    """`mkt` (main) and `sales`; `lead` and `campaign`; `reader` holds read on
    lead at workspace depth and is assigned in both workspaces; `wide` holds
    read on campaign at tenant depth; `owner` holds `tenant_owner`; `spare` is
    an object no role names, so only its own table's trigger sees it go."""

    tenant: PlantedTenant
    lead: uuid.UUID
    campaign: uuid.UUID
    spare: uuid.UUID
    reader_role: uuid.UUID
    reader: uuid.UUID
    reader_sales_membership: uuid.UUID
    wide_role: uuid.UUID
    wide: uuid.UUID
    owner: uuid.UUID

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id

    @property
    def mkt(self) -> uuid.UUID:
        return self.tenant.workspaces[0]

    @property
    def sales(self) -> uuid.UUID:
        return self.tenant.workspaces[1]


async def object_privilege(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    role: uuid.UUID,
    obj: uuid.UUID,
    action: str,
    depth: str,
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO platform.tenant_role_object_privileges"
            " (tenant_id, role_id, object_id, action, depth) VALUES (:t, :r, :o, :a, :d)"
        ),
        {"t": tenant, "r": role, "o": obj, "a": action, "d": depth},
    )


async def plant_company(migrator: AsyncEngine) -> Company:
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        t, mkt, sales = tenant.tenant_id, tenant.workspaces[0], tenant.workspaces[1]
        lead = (await plant_object(conn, tenant, "lead", {})).object_id
        campaign = (await plant_object(conn, tenant, "campaign", {})).object_id
        spare = (await plant_object(conn, tenant, "spare", {})).object_id
        reader_role = await plant_role(conn, t, "reader", {})
        await object_privilege(conn, t, reader_role, lead, "read", "workspace")
        reader = await plant_person(conn, t)
        await assign(conn, t, mkt, await plant_membership(conn, t, mkt, reader), reader_role)
        in_sales = await plant_membership(conn, t, sales, reader)
        await assign(conn, t, sales, in_sales, reader_role)
        wide_role = await plant_role(conn, t, "wide", {})
        await object_privilege(conn, t, wide_role, campaign, "read", "tenant")
        wide = await plant_person(conn, t)
        await assign(conn, t, mkt, await plant_membership(conn, t, mkt, wide), wide_role)
        owner = await plant_person(conn, t)
        owner_role = await role_id(conn, t, "tenant_owner")
        await assign(conn, t, mkt, await plant_membership(conn, t, mkt, owner), owner_role)
    return Company(
        tenant, lead, campaign, spare, reader_role, reader, in_sales, wide_role, wide, owner
    )


# -- R5.1, RA12: one function, the oracle, two tenants ------------------------------


def _observed(reach: Reach, row: Any) -> Scope:
    return Scope(
        workspace_ids=frozenset(row.workspace_ids) if row is not None else frozenset(),
        arms={k: v for k, v in reach.arms.items() if v},
        create_own_keys=reach.create_own_keys,
        valid_until=row.valid_until if row is not None else None,
    )


def _expected(org: Organisation, person: uuid.UUID, now: datetime) -> Scope:
    scope = expected_scope(org, person, now)
    return Scope(
        workspace_ids=scope.workspace_ids,
        arms={k: v for k, v in scope.arms.items() if v},
        create_own_keys=scope.create_own_keys,
        valid_until=scope.valid_until,
    )


async def _as_app(conn: AsyncConnection, tenant: uuid.UUID, user: uuid.UUID) -> tuple[Reach, Any]:
    await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_app"))
    try:
        await bind(conn, tenant, user)
        await conn.execute(_DOOR)
        reach = await read_reach(conn)
        row = (await conn.execute(_OWN_ROW)).one_or_none()
    finally:
        await conn.execute(sa.text("RESET SESSION AUTHORIZATION"))
    return reach, row


async def _as_migrator(conn: AsyncConnection) -> None:
    await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_migrator"))


async def test_r5_1_ra12_every_reader_matches_the_oracle_over_random_organisations(
    admin: AsyncEngine,
) -> None:
    """R5.1 (RA12): at least 500 random organisations, every principal, every
    action and arm, `workspace_ids` and `valid_until`; the row a principal reads
    is their own and is `valid`."""
    rng = random.Random(20261105)
    checked = people = 0
    while checked < _ORGANISATIONS:
        async with admin.connect() as conn:
            tx = await conn.begin()
            try:
                await _as_migrator(conn)
                now = (await conn.execute(sa.text("SELECT now()"))).scalar_one()
                orgs = [
                    await plant_random_organisation(conn, rng, now) for _ in range(_PER_TRANSACTION)
                ]
                await conn.execute(sa.text("RESET SESSION AUTHORIZATION"))
                for org in orgs:
                    for person in org.people:
                        reach, row = await _as_app(conn, org.tenant_id, person.id)
                        assert _observed(reach, row) == _expected(org, person.id, now), (
                            org,
                            person,
                        )
                        assert reach.user == person.id and row.state == "valid"
                        people += 1
                    checked += 1
            finally:
                await tx.rollback()
    assert checked >= _ORGANISATIONS and people > checked


async def test_ra12_two_tenants_of_one_structure_share_no_id(admin: AsyncEngine) -> None:
    """RA12: two organisations drawn from one seed have the same api names, roles
    and assignments; each principal's arrays hold only their own tenant's
    objects and keys. Mapping a grant's key to an object without the tenant (the
    view's filter gone) puts the twin's object in, and this goes red."""
    async with admin.connect() as conn:
        tx = await conn.begin()
        try:
            await _as_migrator(conn)
            now = (await conn.execute(sa.text("SELECT now()"))).scalar_one()
            seed = 7
            while True:
                first = await plant_random_organisation(conn, random.Random(seed), now)
                if any(_expected(first, p.id, now).arms for p in first.people):
                    break
                seed += 1
            twin = await plant_random_organisation(conn, random.Random(seed), now)
            await conn.execute(sa.text("RESET SESSION AUTHORIZATION"))
            assert len(first.people) == len(twin.people) and len(first.objects) == len(twin.objects)
            for org, other in ((first, twin), (twin, first)):
                foreign = set(other.objects) | {
                    access_key(o, w) for o in other.objects for w in other.workspaces
                }
                for person in org.people:
                    reach, row = await _as_app(conn, org.tenant_id, person.id)
                    held = set().union(*reach.arms.values(), reach.create_own_keys)
                    assert not held & foreign, person
                    assert _observed(reach, row) == _expected(org, person.id, now)
        finally:
            await tx.rollback()


async def test_r5_1_depth_adds_up_and_create_keys_its_own_anchor(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.1: read at workspace depth anchored in Marketing still lists Lead in
    the own arm (a Sales lead the person owns stays in reach); create at own
    depth on Lead in Marketing and on Campaign in Sales keys exactly those two
    pairs, never (Lead, Sales)."""
    company = await plant_company(migrator)
    async with migrator.begin() as conn:
        creator_role = await plant_role(conn, company.t, "creator", {})
        campaign_role = await plant_role(conn, company.t, "campaign_creator", {})
        await object_privilege(conn, company.t, creator_role, company.lead, "create", "own")
        await object_privilege(conn, company.t, campaign_role, company.campaign, "create", "own")
        marketer = await plant_person(conn, company.t)
        m_mkt = await plant_membership(conn, company.t, company.mkt, marketer)
        m_sales = await plant_membership(conn, company.t, company.sales, marketer)
        await assign(conn, company.t, company.mkt, m_mkt, company.reader_role)
        await assign(conn, company.t, company.mkt, m_mkt, creator_role)
        await assign(conn, company.t, company.sales, m_sales, campaign_role)

    reach = await door(app_engine, company.t, marketer)
    assert company.lead in reach.arm("read", "own")
    assert reach.arm("read", "keys") == {access_key(company.lead, company.mkt)}
    assert reach.create_own_keys == {
        access_key(company.lead, company.mkt),
        access_key(company.campaign, company.sales),
    }
    assert access_key(company.lead, company.sales) not in reach.create_own_keys


# -- RA12: the row is its principal's alone ---------------------------------------


async def test_ra12_a_principal_reads_their_own_row_and_no_one_elses(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """RA12: two principals of one tenant, both computed; A reads only A's row,
    B's by id gives 0 rows; only the tenant-wide scope of a registered lane
    reads both. Dropping the RESTRICTIVE policy, or making it PERMISSIVE, lets A
    read B's row."""
    company = await plant_company(migrator)
    await door(app_engine, company.t, company.reader)
    await door(app_engine, company.t, company.wide)
    async with app_engine.begin() as conn:
        await bind(conn, company.t, company.reader)
        mine = (
            await conn.execute(sa.text("SELECT principal_id FROM studio.principal_scopes"))
        ).all()
        theirs = (
            await conn.execute(
                sa.text("SELECT count(*) FROM studio.principal_scopes WHERE principal_id = :u"),
                {"u": company.wide},
            )
        ).scalar_one()
        await conn.execute(sa.text("SELECT set_config('app.workspace_scope', 'tenant', true)"))
        lane = set(
            (await conn.execute(sa.text("SELECT principal_id FROM studio.principal_scopes")))
            .scalars()
            .all()
        )
    assert [r.principal_id for r in mine] == [company.reader]
    assert theirs == 0
    # The owner's row is the `stale` one planting left: the scope reads every row.
    assert lane == {company.reader, company.wide, company.owner}


# -- R5.2, RA13: a change holds from the next transaction ---------------------------


async def _change(kind: str, company: Company, migrator: AsyncEngine) -> uuid.UUID:
    """Commit one kind of change; return the principal whose reach it narrows."""
    t = company.t
    if kind == "member_removed":
        await execute(
            migrator,
            "DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u",
            t=t,
            u=company.reader,
        )
        return company.reader
    if kind == "member_suspended":
        await execute(
            migrator,
            "UPDATE platform.tenant_members SET status = 'suspended'"
            " WHERE tenant_id = :t AND user_id = :u",
            t=t,
            u=company.reader,
        )
        return company.reader
    if kind == "workspace_member_removed":
        await execute(
            migrator,
            "DELETE FROM platform.memberships WHERE id = :m",
            m=company.reader_sales_membership,
        )
        return company.reader
    if kind == "assignment_removed":
        await execute(
            migrator,
            "DELETE FROM platform.role_assignments WHERE membership_id = :m",
            m=company.reader_sales_membership,
        )
        return company.reader
    if kind == "privilege_lowered":
        await execute(
            migrator,
            "UPDATE platform.tenant_role_object_privileges SET depth = 'own'"
            " WHERE tenant_id = :t AND role_id = :r",
            t=t,
            r=company.wide_role,
        )
        return company.wide
    if kind == "company_locked":
        await execute(migrator, "UPDATE platform.tenants SET status = 'locked' WHERE id = :t", t=t)
        return company.wide
    if kind == "workspace_archived":
        await execute(
            migrator,
            "UPDATE platform.workspaces SET archived_at = now() WHERE id = :w",
            w=company.sales,
        )
        return company.reader
    if kind == "object_deleted":
        await execute(migrator, "DELETE FROM studio.object_defs WHERE id = :o", o=company.spare)
        return company.owner
    raise AssertionError(kind)


_NARROWED = {
    "member_removed": lambda c, r: r.empty,
    "member_suspended": lambda c, r: r.no_reach,
    "workspace_member_removed": lambda c, r: r.arm("read", "keys") == {access_key(c.lead, c.mkt)},
    "assignment_removed": lambda c, r: r.arm("read", "keys") == {access_key(c.lead, c.mkt)},
    "privilege_lowered": lambda c, r: (
        r.arm("read", "tenant") == frozenset() and r.arm("read", "own") == {c.campaign}
    ),
    "company_locked": lambda c, r: r.no_reach,
    "workspace_archived": lambda c, r: r.arm("read", "keys") == {access_key(c.lead, c.mkt)},
    "object_deleted": lambda c, r: r.arm("read", "tenant") == {c.lead, c.campaign},
}


@pytest.mark.parametrize("kind", sorted(_NARROWED))
async def test_r5_2_a_committed_change_narrows_the_next_transaction(
    kind: str, migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.2 (RA13): each kind of change commits in transaction A; the door's
    first call in transaction B answers with the new reach. Dropping the
    trigger of the table the change writes turns that kind red."""
    company = await plant_company(migrator)
    before = {p: await door(app_engine, company.t, p) for p in (company.reader, company.wide)}
    before[company.owner] = await door(app_engine, company.t, company.owner)
    principal = await _change(kind, company, migrator)
    after = await door(app_engine, company.t, principal)
    assert not _NARROWED[kind](company, before[principal]), "the change narrowed nothing"
    assert _NARROWED[kind](company, after), after


async def test_r5_2_a_new_object_reaches_the_owner_at_the_next_transaction(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.2: an object created in transaction A is in the owner's tenant arm at
    the first door call of transaction B (`studio.object_defs` INSERT bumps)."""
    company = await plant_company(migrator)
    assert (await door(app_engine, company.t, company.owner)).arm("read", "tenant") == {
        company.lead,
        company.campaign,
        company.spare,
    }
    async with migrator.begin() as conn:
        deal = (await plant_object(conn, company.tenant, "deal", {})).object_id
    assert deal in (await door(app_engine, company.t, company.owner)).arm("read", "tenant")


# -- R5.3, RA14: missing, stale, old or expired reads as nothing --------------------


_SPOILED = {
    "missing": "DELETE FROM studio.principal_scopes WHERE tenant_id = :t AND principal_id = :u",
    "stale": "UPDATE studio.principal_scopes SET state = 'stale'"
    " WHERE tenant_id = :t AND principal_id = :u",
    "old_epoch": "UPDATE studio.access_epochs SET epoch = epoch + 1 WHERE tenant_id = :t",
    "expired": "UPDATE studio.principal_scopes SET valid_until = now() - interval '1 second'"
    " WHERE tenant_id = :t AND principal_id = :u",
}


@pytest.mark.parametrize("case", sorted(_SPOILED))
async def test_r5_3_ra14_a_row_not_valid_now_reads_as_empty(
    case: str, migrator: AsyncEngine, admin: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.3 (RA14): without calling the door, every reader answers '{}' for a
    missing row, a stale one, one of an older epoch and one past `valid_until`;
    the same read before the change answered the reach."""
    company = await plant_company(migrator)
    assert not (await door(app_engine, company.t, company.wide)).empty
    async with admin.connect() as conn:
        tx = await conn.begin()
        try:
            await _as_migrator(conn)
            await conn.execute(sa.text(_SPOILED[case]), {"t": company.t, "u": company.wide})
            await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_app"))
            await bind(conn, company.t, company.wide)
            reach = await read_reach(conn)
        finally:
            await tx.rollback()
    assert reach.empty, reach


async def test_r5_3_an_assignment_that_expires_with_no_write_leaves_at_the_next_statement(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.3: an assignment expiring at T, no write after it: before T the reach
    is there and the row carries T; after T the principal's first door call
    recomputes and keeps only the grant that does not expire."""
    company = await plant_company(migrator)
    async with migrator.begin() as conn:
        at = (await conn.execute(sa.text("SELECT clock_timestamp()"))).scalar_one()
        expires = at + timedelta(seconds=2)
        membership = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM platform.memberships WHERE tenant_id = :t AND user_id = :u"
                ),
                {"t": company.t, "u": company.wide},
            )
        ).scalar_one()
        await assign(
            conn,
            company.t,
            company.mkt,
            membership,
            company.reader_role,
            expires_at=expires,
            assigned_at=at - timedelta(hours=1),
        )
    before = await door(app_engine, company.t, company.wide)
    row = await ledger_row(migrator, company.t, company.wide)
    assert before.arm("read", "own") == {company.lead, company.campaign}
    assert row.valid_until == expires

    async with migrator.connect() as conn:
        while (await conn.execute(sa.text("SELECT clock_timestamp()"))).scalar_one() <= expires:
            await asyncio.sleep(0.2)
    after = await door(app_engine, company.t, company.wide)
    row = await ledger_row(migrator, company.t, company.wide)
    assert after.arm("read", "own") == {company.campaign}
    assert row.state == "valid" and row.valid_until is None


# -- R5.4, RA15: a computation begun before a revocation never publishes after it ---


async def _waiting(watcher: AsyncConnection, pid: int, task: asyncio.Task[Any]) -> None:
    """Until `pid` waits on a lock, or its statement already finished."""
    for _ in range(100):
        if task.done():
            return
        waits = (
            await watcher.execute(
                sa.text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
            )
        ).scalar_one_or_none()
        if waits == "Lock":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the door neither waited nor finished")


async def _interleave(
    company: Company, migrator: AsyncEngine, app_engine: AsyncEngine, admin: AsyncEngine
) -> None:
    """The door starts computing for `reader`; meanwhile the removal of their
    Sales assignment, begun first, commits; then the door writes. The watcher
    is the superuser: another role's `wait_event_type` is hidden from the
    migrator (it needs `pg_read_all_stats`)."""
    async with (
        migrator.connect() as revoker,
        app_engine.connect() as computer,
        admin.connect() as watcher,
    ):
        await revoker.begin()
        await revoker.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE membership_id = :m"),
            {"m": company.reader_sales_membership},
        )
        await computer.begin()
        await bind(computer, company.t, company.reader)
        pid = (await computer.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
        task = asyncio.ensure_future(computer.execute(_DOOR))
        try:
            await _waiting(watcher, pid, task)
        finally:
            # Released whatever happened, so the door's statement ends and its
            # connection can close.
            await revoker.commit()
            await asyncio.wait_for(task, timeout=30)
        await computer.commit()


async def test_r5_4_ra15_an_existing_row_stays_not_valid_after_a_late_write(
    migrator: AsyncEngine, app_engine: AsyncEngine, admin: AsyncEngine
) -> None:
    """R5.4 (RA15): the row exists and needs computing; the computation's write
    comes after the revocation's commit and finds the version moved, so the
    row stays `stale` and the next call reads the narrower reach."""
    company = await plant_company(migrator)
    await door(app_engine, company.t, company.reader)
    await execute(
        migrator,
        "UPDATE studio.principal_scopes SET state = 'stale' WHERE principal_id = :u",
        u=company.reader,
    )
    await _interleave(company, migrator, app_engine, admin)
    assert (await ledger_row(migrator, company.t, company.reader)).state != "valid"
    assert (await door(app_engine, company.t, company.reader)).arm("read", "keys") == {
        access_key(company.lead, company.mkt)
    }


async def test_r5_4_ra15_a_first_computation_loses_to_the_revocation_s_row(
    migrator: AsyncEngine, app_engine: AsyncEngine, admin: AsyncEngine
) -> None:
    """R5.4 (RA15): the principal has no row; the revocation's trigger upserts a
    `stale` one, so the door's insert of its older computation does nothing."""
    company = await plant_company(migrator)
    await execute(
        migrator, "DELETE FROM studio.principal_scopes WHERE principal_id = :u", u=company.reader
    )
    await _interleave(company, migrator, app_engine, admin)
    assert (await ledger_row(migrator, company.t, company.reader)).state == "stale"


async def test_r5_4_a_first_bump_makes_the_epoch_row_at_one(migrator: AsyncEngine) -> None:
    company = await plant_company(migrator)
    await execute(migrator, "DELETE FROM studio.access_epochs WHERE tenant_id = :t", t=company.t)
    await execute(
        migrator,
        "UPDATE platform.workspaces SET archived_at = now() WHERE id = :w",
        w=company.sales,
    )
    async with migrator.connect() as conn:
        epoch = (
            await conn.execute(
                sa.text("SELECT epoch FROM studio.access_epochs WHERE tenant_id = :t"),
                {"t": company.t},
            )
        ).scalar_one()
    assert epoch == 1


# -- R5.3: a connection with no member behind it --------------------------------------


@pytest.mark.parametrize("who", ["stranger", "nobody"])
async def test_r5_3_the_door_does_nothing_for_someone_who_is_not_a_member(
    who: str, migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.3, RA12: a user who is a member of another company, or no
    `app.user_id` at all: the door returns without error, writes no row, and
    every reader answers '{}'."""
    company = await plant_company(migrator)
    other = await plant_company(migrator)
    user = other.owner if who == "stranger" else None
    reach = await door(app_engine, company.t, user)
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM studio.principal_scopes"
                    " WHERE tenant_id = :t AND principal_id = :u"
                ),
                {"t": company.t, "u": other.owner},
            )
        ).scalar_one()
    assert reach.empty and rows == 0


# -- R5.5, RA16: only the definer functions write ------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO studio.principal_scopes (tenant_id, principal_id, epoch, version, state,"
        " computed_at, workspace_ids) VALUES (:t, :u, 0, 1, 'valid', now(), '{}')",
        "UPDATE studio.principal_scopes SET state = 'valid'",
        "DELETE FROM studio.principal_scopes",
        "INSERT INTO studio.access_epochs (tenant_id) VALUES (:t)",
        "UPDATE studio.access_epochs SET epoch = 0",
        "DELETE FROM studio.access_epochs",
    ],
)
async def test_r5_5_ra16_dw_app_writes_neither_table(
    statement: str, migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    async with app_engine.connect() as conn:
        await bind(conn, company.t, company.reader)
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(sa.text(statement), {"t": company.t, "u": company.reader})


# -- R5.6: removal and offboarding ---------------------------------------------------


async def test_r5_6_removing_a_member_with_no_ledger_row_succeeds_and_leaves_none(
    migrator: AsyncEngine,
) -> None:
    """R5.6: a member who never had a row, with memberships in two workspaces
    and two assignments: the removal succeeds (no trigger inserts a row for
    someone the cascade is removing, so no foreign key error), and no row is
    left."""
    company = await plant_company(migrator)
    await execute(
        migrator, "DELETE FROM studio.principal_scopes WHERE principal_id = :u", u=company.reader
    )
    await execute(
        migrator,
        "DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u",
        t=company.t,
        u=company.reader,
    )
    assert await ledger_row(migrator, company.t, company.reader) is None


async def test_r5_6_the_row_leaves_with_the_member_in_the_same_transaction(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    await door(app_engine, company.t, company.reader)
    async with migrator.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(
                sa.text(
                    "DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"
                ),
                {"t": company.t, "u": company.reader},
            )
            left = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM studio.principal_scopes WHERE principal_id = :u"),
                    {"u": company.reader},
                )
            ).scalar_one()
        finally:
            await tx.rollback()
    assert left == 0


async def test_r5_6_offboarding_leaves_no_ledger_row_and_no_epoch(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R5.6: the lane exports, then purges; the ledger rows go with the company
    members, the epoch row through `studio.purge_access_epoch`, and no delete of
    the lane after that step makes the epoch row again. Another company keeps
    both."""
    company = await plant_company(migrator)
    kept = await plant_company(migrator)
    for c in (company, kept):
        for p in (c.reader, c.wide, c.owner):
            await door(app_engine, c.t, p)
    await execute(
        migrator, "UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t", t=company.t
    )
    lane = SqlTenantOffboarding(session_factory=async_sessionmaker(app_engine, class_=AsyncSession))
    async for _ in lane.export_rows(company.t):
        pass
    await lane.purge_rows(company.t)

    count = (
        "SELECT (SELECT count(*) FROM studio.principal_scopes WHERE tenant_id = :t),"
        " (SELECT count(*) FROM studio.access_epochs WHERE tenant_id = :t)"
    )
    async with migrator.connect() as conn:
        gone = tuple((await conn.execute(sa.text(count), {"t": company.t})).one())
        still = tuple((await conn.execute(sa.text(count), {"t": kept.t})).one())
    assert gone == (0, 0)
    assert still == (3, 1)


async def test_the_epoch_purge_refuses_a_company_that_is_not_leaving(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    other = await plant_company(migrator)
    async with app_engine.connect() as conn:
        await bind(conn, company.t, company.owner)
        for tenant in (company.t, other.t):
            with pytest.raises(DBAPIError, match="purge_access_epoch runs"):
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text("SELECT studio.purge_access_epoch(:t)"), {"t": tenant}
                    )


# -- R5.7: no row for someone who is not a member of that company ---------------------


async def test_r5_7_a_row_naming_another_company_s_member_is_refused(
    migrator: AsyncEngine,
) -> None:
    """R5.7 (RA12): even the function owner inserting A's tenant with a person
    who is a member of B only gets 23503 on the composite key, and no row."""
    a = await plant_company(migrator)
    b = await plant_company(migrator)
    with pytest.raises(IntegrityError) as refused:
        await execute(
            migrator,
            "INSERT INTO studio.principal_scopes (tenant_id, principal_id, epoch, version, state,"
            " computed_at, workspace_ids) VALUES (:t, :u, 0, 1, 'valid', now(), '{}')",
            t=a.t,
            u=b.owner,
        )
    assert getattr(refused.value.orig, "sqlstate", None) == "23503"
    assert "fk_principal_scopes_tenant_id_tenant_members" in str(refused.value)
    assert await ledger_row(migrator, a.t, b.owner) is None


# -- step 7: the declared inputs carry exactly their triggers ------------------------

_DECLARED = sa.text("SELECT table_name, trigger_function, events FROM studio.access_input_tables")
_RELEVANT_TRIGGERS = sa.text(
    """
    SELECT cn.nspname || '.' || c.relname AS table_name, t.tgname,
           pn.nspname || '.' || p.proname AS function, pg_get_triggerdef(t.oid) AS definition
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace cn ON cn.oid = c.relnamespace
    JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace pn ON pn.oid = p.pronamespace
    WHERE NOT t.tgisinternal
      AND pn.nspname || '.' || p.proname IN (
          'studio.mark_principal_stale', 'studio.bump_access_epoch', 'platform.bump_access_version')
    """
)
_TABLES = sa.text(
    "SELECT n.nspname || '.' || c.relname FROM pg_class c"
    " JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r', 'p')"
)


async def access_input_violations(conn: AsyncConnection) -> list[str]:
    """R5.2 (RA13): one line per defect."""
    declared = {r.table_name: r for r in (await conn.execute(_DECLARED)).all()}
    triggers = (await conn.execute(_RELEVANT_TRIGGERS)).all()
    tables = set((await conn.execute(_TABLES)).scalars().all())
    found: list[str] = []
    bumped = {t.table_name for t in triggers if t.function == "platform.bump_access_version"}
    found += [
        f"{table} carries platform.bump_access_version() and is not declared"
        for table in sorted(bumped - declared.keys())
    ]
    ours: dict[str, list[Any]] = {}
    for t in triggers:
        if t.function.startswith("studio."):
            ours.setdefault(t.table_name, []).append(t)
    found += [
        f"{table} carries {', '.join(sorted(t.function for t in ours[table]))} and is not declared"
        for table in sorted(ours.keys() - declared.keys())
    ]
    for table, row in sorted(declared.items()):
        if table not in tables:
            found.append(f"declared {table} does not exist")
            continue
        held = sorted(t.definition for t in ours.get(table, []))
        want = (
            []
            if row.trigger_function == "none"
            else [
                f"CREATE TRIGGER trg_studio_access_input AFTER {row.events} ON {table}"
                f" FOR EACH ROW EXECUTE FUNCTION studio.{row.trigger_function}()"
            ]
        )
        if held != want:
            found.append(f"{table} should carry {want} and carries {held}")
    return found


async def test_step_7_every_declared_input_carries_its_trigger(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        assert await access_input_violations(conn) == []
        declared = set((await conn.execute(_DECLARED)).scalars().all())
    assert {
        "platform.role_assignments",
        "platform.memberships",
        "platform.tenant_members",
        "platform.tenant_role_object_privileges",
        "platform.workspaces",
        "studio.object_defs",
    } <= declared


async def test_step_7_each_planted_defect_is_named(migrator: AsyncEngine) -> None:
    """A table given `platform.bump_access_version()` with no row; a declared
    table whose trigger is gone; a declared table calling the wrong function."""
    async with migrator.connect() as conn:
        tx = await conn.begin()
        try:
            for statement in (
                "CREATE TABLE platform.access_input_probe (tenant_id uuid)",
                "CREATE TRIGGER trg_z_bump_access_version AFTER INSERT"
                " ON platform.access_input_probe"
                " FOR EACH ROW EXECUTE FUNCTION platform.bump_access_version()",
                "DROP TRIGGER trg_studio_access_input ON platform.role_assignments",
                "DROP TRIGGER trg_studio_access_input ON platform.memberships",
                "CREATE TRIGGER trg_studio_access_input AFTER INSERT OR DELETE OR UPDATE"
                " ON platform.memberships"
                " FOR EACH ROW EXECUTE FUNCTION studio.bump_access_epoch()",
            ):
                await conn.execute(sa.text(statement))
            found = await access_input_violations(conn)
        finally:
            await tx.rollback()
    assert (
        "platform.access_input_probe carries platform.bump_access_version() and is not declared"
        in found
    )
    assert any(line.startswith("platform.role_assignments should carry") for line in found)
    assert any(
        line.startswith("platform.memberships should carry") and "bump_access_epoch" in line
        for line in found
    )
    assert len(found) == 3, found
