"""The record policies, default access and the tenant-wide scope (record-access
ticket 03; revision 2c2095fbb4c7).

Raw SQL on a migrated Postgres, each statement as the role the criterion names:
records planted as the migrator past the reach policies (`plant_record`), read
and written as `dw_app` bound the way the API door binds a request
(`act_as_user`: tenant, principal, actor kind `user`, the reach door). A change
of default access commits in one transaction and the next one reads it (R5.2).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_platform.adapters.persistence.offboarding import OFFBOARDING_LANE, SqlTenantOffboarding
from dw_platform.adapters.persistence.tenant_session import (
    TenantScope,
    TenantWideScopeRefusedError,
    bind_tenant,
    tenant_session,
    tenant_wide_scope,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_platform.testing.record_objects import plant_object
from dw_studio.records.adapters.record_policy import record_policies
from dw_studio.records.adapters.user_session import user_session
from dw_studio.testing.records import act_as_user, plant_record

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


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
    """The superuser on this suite's database, to act as two roles in one
    transaction that rolls back."""
    url = studio_db.admin.rsplit("/", 1)[0] + "/" + studio_db.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


def sqlstate(error: BaseException) -> str | None:
    return getattr(getattr(error, "orig", None), "sqlstate", None)


def constraint(error: BaseException) -> str | None:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


# -- a company ------------------------------------------------------------------


async def privilege(
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


async def person(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    grants: dict[uuid.UUID, tuple[tuple[uuid.UUID, str, str], ...]],
) -> uuid.UUID:
    """A member of ``tenant`` holding, in each workspace named, a role of its
    own carrying those (object, action, depth) privileges."""
    t = tenant.tenant_id
    who = await plant_person(conn, t)
    memberships: dict[uuid.UUID, uuid.UUID] = {}
    for workspace in (tenant.main, *grants):
        if workspace not in memberships:
            memberships[workspace] = await plant_membership(conn, t, workspace, who)
    for workspace, privileges in grants.items():
        role = await plant_role(conn, t, f"r{uuid.uuid4().hex[:10]}", {})
        for obj, action, depth in privileges:
            await privilege(conn, t, role, obj, action, depth)
        await assign(conn, t, workspace, memberships[workspace], role)
    return who


@dataclass(frozen=True)
class Company:
    """Marketing (main) and Sales; Lead and Campaign, both `private`.

    `me` and `peer` hold read, update and delete on Lead at own depth in
    Marketing; `ws_reader` read at workspace depth in Marketing; `wide` read at
    tenant depth; `both` read at own depth in Sales and at workspace depth in
    Marketing; `creator` create at own depth on Lead in Marketing and on
    Campaign in Sales. Records: `mine` (Lead, Marketing, me), `peers` (Lead,
    Marketing, peer), `sales` (Lead, Sales, peer), `boths` (Lead, Sales, both),
    `campaign` (Campaign, Marketing, peer)."""

    tenant: PlantedTenant
    lead: uuid.UUID
    campaign: uuid.UUID
    me: uuid.UUID
    peer: uuid.UUID
    ws_reader: uuid.UUID
    wide: uuid.UUID
    both: uuid.UUID
    creator: uuid.UUID
    mine: uuid.UUID
    peers: uuid.UUID
    sales: uuid.UUID
    boths: uuid.UUID
    campaign_record: uuid.UUID

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id

    @property
    def mkt(self) -> uuid.UUID:
        return self.tenant.workspaces[0]

    @property
    def sales_ws(self) -> uuid.UUID:
        return self.tenant.workspaces[1]


_OWN_RUD = ("read", "update", "delete")


async def plant_company(migrator: AsyncEngine) -> Company:
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        mkt, sales = tenant.workspaces
        lead = (await plant_object(conn, tenant, "lead", {})).object_id
        campaign = (await plant_object(conn, tenant, "campaign", {})).object_id
        own_rud = tuple((lead, action, "own") for action in _OWN_RUD)
        me = await person(conn, tenant, {mkt: own_rud})
        peer = await person(conn, tenant, {mkt: own_rud})
        ws_reader = await person(conn, tenant, {mkt: ((lead, "read", "workspace"),)})
        wide = await person(conn, tenant, {mkt: ((lead, "read", "tenant"),)})
        both = await person(
            conn,
            tenant,
            {sales: ((lead, "read", "own"),), mkt: ((lead, "read", "workspace"),)},
        )
        creator = await person(
            conn,
            tenant,
            {mkt: ((lead, "create", "own"),), sales: ((campaign, "create", "own"),)},
        )
        t = tenant.tenant_id
        mine = await plant_record(conn, t, lead, mkt, me)
        peers = await plant_record(conn, t, lead, mkt, peer)
        in_sales = await plant_record(conn, t, lead, sales, peer)
        boths = await plant_record(conn, t, lead, sales, both)
        campaign_record = await plant_record(conn, t, campaign, mkt, peer)
    return Company(
        tenant,
        lead,
        campaign,
        me,
        peer,
        ws_reader,
        wide,
        both,
        creator,
        mine,
        peers,
        in_sales,
        boths,
        campaign_record,
    )


async def visible(app: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID) -> set[uuid.UUID]:
    async with app.begin() as conn:
        await act_as_user(conn, tenant, user)
        return set((await conn.execute(sa.text("SELECT id FROM studio.records"))).scalars())


async def changed(
    app: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID, sql: str, **values: Any
) -> int:
    """Rows a write as ``user`` touched; the transaction commits."""
    async with app.begin() as conn:
        await act_as_user(conn, tenant, user)
        return (await conn.execute(sa.text(sql), values)).rowcount


async def refused(
    app: AsyncEngine, tenant: uuid.UUID, user: uuid.UUID, sql: str, **values: Any
) -> DBAPIError:
    with pytest.raises(DBAPIError) as caught:
        async with app.begin() as conn:
            await act_as_user(conn, tenant, user)
            await conn.execute(sa.text(sql), values)
    return caught.value


async def record_row(migrator: AsyncEngine, record: uuid.UUID) -> Any:
    async with migrator.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT owner_id, workspace_id, object_id, deleted_at, name"
                    " FROM studio.records WHERE id = :r"
                ),
                {"r": record},
            )
        ).one_or_none()


async def set_default_access(migrator: AsyncEngine, obj: uuid.UUID, access: str) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE studio.object_defs SET default_access = :a WHERE id = :o"),
            {"a": access, "o": obj},
        )


_INSERT = (
    "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind, owner_id,"
    " name, created_by, updated_by) VALUES (gen_random_uuid(), :t, :o, :w, :kind, :owner,"
    " 'Mới', :owner, :owner)"
)


# -- R1.2 (RA1): the owner is an active member of the row's company ---------------


@pytest.mark.parametrize("case", ["other_company", "suspended", "team"])
async def test_r1_2_an_owner_who_is_not_an_active_member_is_refused(
    migrator: AsyncEngine, case: str
) -> None:
    """INSERT as the migrator (past every policy, so only the trigger can
    refuse), bound to the row's tenant."""
    company = await plant_company(migrator)
    async with migrator.begin() as conn:
        other = await plant_tenant(conn)
        stranger = await plant_person(conn, other.tenant_id)
        suspended = await plant_person(conn, company.t, status="suspended")
    owner, kind = {
        "other_company": (stranger, "user"),
        "suspended": (suspended, "user"),
        "team": (company.me, "team"),
    }[case]
    with pytest.raises(DBAPIError) as caught:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(company.t)}
            )
            await conn.execute(
                sa.text(_INSERT),
                {"t": company.t, "o": company.lead, "w": company.mkt, "kind": kind, "owner": owner},
            )
    assert sqlstate(caught.value) == "23514"
    assert constraint(caught.value) == "ck_records_owner_in_tenant"


_PROBE_DEFINER = """
    CREATE FUNCTION public.probe_insert_record(p_tenant uuid, p_object uuid, p_workspace uuid,
                                               p_owner uuid) RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
        INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind, owner_id,
                                    name, created_by, updated_by)
        VALUES (gen_random_uuid(), p_tenant, p_object, p_workspace, 'user', p_owner, 'Qua hàm',
                p_owner, p_owner)
    $$
"""


async def _through_definer(
    admin: AsyncEngine,
    bound: uuid.UUID,
    row_tenant: uuid.UUID,
    obj: uuid.UUID,
    workspace: uuid.UUID,
    owner: uuid.UUID,
) -> DBAPIError:
    """A SECURITY DEFINER function of the migrator (as ticket 05's will be),
    called by `dw_app` bound to ``bound``; made and rolled back here."""
    async with admin.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_migrator"))
            await conn.execute(sa.text(_PROBE_DEFINER))
            await conn.execute(
                sa.text(
                    "GRANT EXECUTE ON FUNCTION public.probe_insert_record(uuid, uuid, uuid,"
                    " uuid) TO dw_app"
                )
            )
            await conn.execute(sa.text("RESET SESSION AUTHORIZATION"))
            await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_app"))
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(bound)}
            )
            with pytest.raises(DBAPIError) as caught:
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text("SELECT public.probe_insert_record(:t, :o, :w, :u)"),
                        {"t": row_tenant, "o": obj, "w": workspace, "u": owner},
                    )
        finally:
            await tx.rollback()
    return caught.value


async def test_r1_2_the_check_holds_under_a_security_definer_function(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    async with migrator.begin() as conn:
        other = await plant_tenant(conn)
        stranger = await plant_person(conn, other.tenant_id)
    error = await _through_definer(admin, company.t, company.t, company.lead, company.mkt, stranger)
    assert sqlstate(error) == "23514"
    assert constraint(error) == "ck_records_owner_in_tenant"


async def test_r1_2_another_company_s_row_is_refused_before_its_members_are_read(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """Gate (m): bound to A, a row of B through the definer is refused 42501
    whether its owner is B's active member or no one's, with one message, so
    the refusal says nothing about B's members."""
    a = await plant_company(migrator)
    b = await plant_company(migrator)
    member = await _through_definer(admin, a.t, b.t, b.lead, b.mkt, b.me)
    nobody = await _through_definer(admin, a.t, b.t, b.lead, b.mkt, uuid.uuid4())
    assert sqlstate(member) == sqlstate(nobody) == "42501"
    assert str(member.orig).split("\n")[0] == str(nobody.orig).split("\n")[0]
    assert "row-level security" in str(member)


# -- R1.3 (RA2): dw_app never moves a record ---------------------------------------


_TYPE = {"owner_id": "uuid", "owner_kind": "text", "workspace_id": "uuid", "object_id": "uuid"}


@pytest.mark.parametrize("column", sorted(_TYPE))
async def test_r1_3_dw_app_updates_no_owner_workspace_or_object(
    migrator: AsyncEngine, app_engine: AsyncEngine, column: str
) -> None:
    company = await plant_company(migrator)
    value = {
        "owner_id": str(company.peer),
        "owner_kind": "user",
        "workspace_id": str(company.sales_ws),
        "object_id": str(company.campaign),
    }[column]
    error = await refused(
        app_engine,
        company.t,
        company.me,
        f"UPDATE studio.records SET {column} = CAST(:v AS {_TYPE[column]}) WHERE id = :r",
        v=value,
        r=company.mine,
    )
    assert "permission denied" in str(error)
    assert (await record_row(migrator, company.mine)).owner_id == company.me


async def test_r1_3_dw_app_updates_no_access_key(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A generated column refuses a value before privileges are asked; set to
    DEFAULT, the statement is a privilege question and `dw_app` holds none."""
    company = await plant_company(migrator)
    error = await refused(
        app_engine,
        company.t,
        company.me,
        "UPDATE studio.records SET access_key = DEFAULT WHERE id = :r",
        r=company.mine,
    )
    assert "permission denied" in str(error)
    value = await refused(
        app_engine,
        company.t,
        company.me,
        "UPDATE studio.records SET access_key = gen_random_uuid() WHERE id = :r",
        r=company.mine,
    )
    assert sqlstate(value) == "428C9"


# -- R2 (RA4): default access -------------------------------------------------------


async def test_r2_2_public_read_opens_reading_and_never_writing(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """`private`: own depth reads only one's own; `public_read`: every Lead,
    and an UPDATE of a peer's still touches nothing."""
    company = await plant_company(migrator)
    assert company.peers not in await visible(app_engine, company.t, company.me)
    await set_default_access(migrator, company.lead, "public_read")
    seen = await visible(app_engine, company.t, company.me)
    assert {company.mine, company.peers, company.sales, company.boths} <= seen
    assert company.campaign_record not in seen
    assert (
        await changed(
            app_engine,
            company.t,
            company.me,
            "UPDATE studio.records SET name = 'Đổi' WHERE id = :r",
            r=company.peers,
        )
        == 0
    )


async def test_r2_3_public_read_write_opens_update_and_includes_read(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Read and update at own depth update a peer's record by id; a holder of
    read alone reads it (gate (c): read-write includes read)."""
    company = await plant_company(migrator)
    async with migrator.begin() as conn:
        reader = await person(conn, company.tenant, {company.mkt: ((company.lead, "read", "own"),)})
    await set_default_access(migrator, company.lead, "public_read_write")
    assert (
        await changed(
            app_engine,
            company.t,
            company.me,
            "UPDATE studio.records SET name = 'Sửa chung' WHERE id = :r",
            r=company.peers,
        )
        == 1
    )
    assert (await record_row(migrator, company.peers)).name == "Sửa chung"
    assert company.peers in await visible(app_engine, company.t, reader)


async def test_r2_4_public_read_write_never_deletes(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    await set_default_access(migrator, company.lead, "public_read_write")
    assert (
        await changed(
            app_engine,
            company.t,
            company.me,
            "DELETE FROM studio.records WHERE id = :r",
            r=company.peers,
        )
        == 0
    )
    assert await record_row(migrator, company.peers) is not None


_SOFT_DELETE = "UPDATE studio.records SET deleted_at = now(), deleted_by = :u WHERE id = :r"


async def test_r2_7_a_soft_delete_needs_delete_reach(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Gate (b): `public_read_write` lets `me` update a peer's record but a
    soft delete of it is refused by WITH CHECK, and the row keeps no
    `deleted_at`; `me` soft-deletes their own (delete at own depth)."""
    company = await plant_company(migrator)
    await set_default_access(migrator, company.lead, "public_read_write")
    error = await refused(
        app_engine, company.t, company.me, _SOFT_DELETE, u=company.me, r=company.peers
    )
    assert sqlstate(error) == "42501" and "row-level security" in str(error)
    assert (await record_row(migrator, company.peers)).deleted_at is None
    assert (
        await changed(
            app_engine,
            company.t,
            company.me,
            "DELETE FROM studio.records WHERE id = :r",
            r=company.peers,
        )
        == 0
    )
    assert (
        await changed(app_engine, company.t, company.me, _SOFT_DELETE, u=company.me, r=company.mine)
        == 1
    )


async def test_r2_7_workspace_update_with_own_delete_soft_deletes_only_ones_own(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Update at workspace depth and delete at own depth in Marketing: a
    colleague's Marketing record is refused 42501; with delete at workspace
    depth too, the same statement succeeds."""
    company = await plant_company(migrator)
    lead, mkt = company.lead, company.mkt
    async with migrator.begin() as conn:
        narrow = await person(
            conn,
            company.tenant,
            {
                mkt: (
                    (lead, "read", "workspace"),
                    (lead, "update", "workspace"),
                    (lead, "delete", "own"),
                )
            },
        )
        broad = await person(
            conn,
            company.tenant,
            {mkt: tuple((lead, action, "workspace") for action in _OWN_RUD)},
        )
    error = await refused(app_engine, company.t, narrow, _SOFT_DELETE, u=narrow, r=company.peers)
    assert sqlstate(error) == "42501"
    assert (await record_row(migrator, company.peers)).deleted_at is None
    assert await changed(app_engine, company.t, broad, _SOFT_DELETE, u=broad, r=company.peers) == 1


# -- R3 (RA5-RA7): depth ------------------------------------------------------------


async def test_r3_1_own_depth_reaches_ones_own_records_for_each_command(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    seen = await visible(app_engine, company.t, company.me)
    assert seen == {company.mine}
    update = "UPDATE studio.records SET name = 'Của tôi' WHERE id = :r"
    assert await changed(app_engine, company.t, company.me, update, r=company.peers) == 0
    assert await changed(app_engine, company.t, company.me, update, r=company.mine) == 1
    assert (
        await changed(
            app_engine, company.t, company.me, _SOFT_DELETE, u=company.me, r=company.peers
        )
        == 0
    )
    assert (
        await changed(app_engine, company.t, company.me, _SOFT_DELETE, u=company.me, r=company.mine)
        == 1
    )
    delete = "DELETE FROM studio.records WHERE id = :r"
    assert await changed(app_engine, company.t, company.me, delete, r=company.peers) == 0
    assert await changed(app_engine, company.t, company.me, delete, r=company.mine) == 1


async def test_r3_2_workspace_depth_reaches_its_workspace_only(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    assert await visible(app_engine, company.t, company.ws_reader) == {company.mine, company.peers}


async def test_r3_3_tenant_depth_reaches_every_workspace(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    assert await visible(app_engine, company.t, company.wide) == {
        company.mine,
        company.peers,
        company.sales,
        company.boths,
    }


async def test_r3_4_two_assignments_add_up_whatever_the_working_workspace(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Own depth in Sales and workspace depth in Marketing: the Marketing
    records and their own Sales record, not a peer's Sales record; the same
    set with Marketing or Sales as the working workspace."""
    company = await plant_company(migrator)
    sets = []
    for working in (company.mkt, company.sales_ws):
        async with app_engine.begin() as conn:
            await act_as_user(conn, company.t, company.both)
            await bind_tenant(
                conn,
                TenantScope(tenant_id=company.t, workspace_id=working, principal_id=company.both),
            )
            sets.append(
                set((await conn.execute(sa.text("SELECT id FROM studio.records"))).scalars())
            )
    assert sets[0] == sets[1] == {company.mine, company.peers, company.boths}


@pytest.mark.parametrize(
    "case", ["workspace_out_of_reach", "someone_elses_record", "object_of_the_other_anchor"]
)
async def test_r3_5_a_create_outside_create_reach_is_refused(
    migrator: AsyncEngine, app_engine: AsyncEngine, case: str
) -> None:
    """Create at own depth on Lead anchored in Marketing and on Campaign in
    Sales: Lead in Sales, a Lead owned by a peer, and (Lead, Sales) are each
    refused 42501 with no row made; Lead in Marketing and Campaign in Sales,
    owned by the creator, are made."""
    company = await plant_company(migrator)
    obj, workspace, owner = {
        "workspace_out_of_reach": (company.campaign, company.mkt, company.creator),
        "someone_elses_record": (company.lead, company.mkt, company.peer),
        "object_of_the_other_anchor": (company.lead, company.sales_ws, company.creator),
    }[case]
    error = await refused(
        app_engine,
        company.t,
        company.creator,
        _INSERT,
        t=company.t,
        o=obj,
        w=workspace,
        kind="user",
        owner=owner,
    )
    assert sqlstate(error) == "42501" and "row-level security" in str(error)
    async with migrator.connect() as conn:
        made = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE tenant_id = :t AND name = 'Mới'"),
            {"t": company.t},
        )
    assert made == 0
    for obj, workspace in ((company.lead, company.mkt), (company.campaign, company.sales_ws)):
        assert (
            await changed(
                app_engine,
                company.t,
                company.creator,
                _INSERT,
                t=company.t,
                o=obj,
                w=workspace,
                kind="user",
                owner=company.creator,
            )
            == 1
        )


# -- R4: one place, every path ------------------------------------------------------


async def test_r4_2_another_company_s_records_are_neither_read_nor_written(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    a = await plant_company(migrator)
    b = await plant_company(migrator)
    async with app_engine.begin() as conn:
        await act_as_user(conn, a.t, a.wide)
        by_id = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE id = :r"), {"r": b.peers}
        )
    assert by_id == 0
    error = await refused(
        app_engine,
        a.t,
        a.creator,
        _INSERT,
        t=b.t,
        o=a.lead,
        w=a.mkt,
        kind="user",
        owner=a.creator,
    )
    assert sqlstate(error) == "42501" and "row-level security" in str(error)


async def test_r4_3_dw_app_reaches_no_partition_by_name(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    async with migrator.connect() as conn:
        partitions = list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                        " WHERE i.inhparent = 'studio.records'::regclass ORDER BY 1"
                    )
                )
            ).scalars()
        )
    assert len(partitions) >= 4
    for partition in partitions:
        for statement in (
            f"SELECT count(*) FROM studio.{partition}",
            f"INSERT INTO studio.{partition} (id, tenant_id, object_id, workspace_id, owner_kind,"
            " owner_id, name, created_by, updated_by) VALUES (gen_random_uuid(), :t, :o, :w,"
            " 'user', :u, 'x', :u, :u)",
        ):
            error = await refused(
                app_engine,
                company.t,
                company.wide,
                statement,
                t=company.t,
                o=company.lead,
                w=company.mkt,
                u=company.wide,
            )
            assert "permission denied" in str(error), (partition, statement)


async def test_r4_4_a_platform_admin_or_support_staff_reaches_no_record(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """`platform_admin` in a membership's legacy keys, with no assignment; a
    support staff member who is no company member: the door does nothing for
    the second, and neither reads a record, without an error."""
    company = await plant_company(migrator)
    async with migrator.begin() as conn:
        admin_user = await plant_person(conn, company.t)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
                " VALUES (gen_random_uuid(), :t, :w, :u, '[\"platform_admin\"]')"
            ),
            {"t": company.t, "w": company.mkt, "u": admin_user},
        )
        staff = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'Hỗ trợ')"
            ),
            {"u": staff, "s": f"support-{staff}"},
        )
        await conn.execute(
            sa.text("INSERT INTO platform.support_staff (user_id) VALUES (:u)"), {"u": staff}
        )
    assert await visible(app_engine, company.t, admin_user) == set()
    assert await visible(app_engine, company.t, staff) == set()


async def test_r4_6_a_connection_without_a_tenant_reads_no_record(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.user_id', :u, true),"
                " set_config('app.actor_kind', 'user', true)"
            ),
            {"u": str(company.wide)},
        )
        assert await conn.scalar(sa.text("SELECT count(*) FROM studio.records")) == 0
    async with migrator.connect() as conn:
        there = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE tenant_id = :t"), {"t": company.t}
        )
    assert there == 5


# -- R5.2 (RA13): default access changes from the next transaction ------------------


async def test_r5_2_narrowing_default_access_holds_from_the_next_transaction(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """`public_read` back to `private` in transaction A: the first statement of
    B, for someone who reached the peer's record only through it, reads 0."""
    company = await plant_company(migrator)
    await set_default_access(migrator, company.lead, "public_read")
    assert company.peers in await visible(app_engine, company.t, company.me)
    await set_default_access(migrator, company.lead, "private")
    assert company.peers not in await visible(app_engine, company.t, company.me)


async def test_r5_2_a_publish_that_keeps_default_access_bumps_no_epoch(
    migrator: AsyncEngine,
) -> None:
    """Gate (n): the publish hook always sets the column; only a change bumps."""
    company = await plant_company(migrator)

    async def epoch() -> int:
        async with migrator.connect() as conn:
            return int(
                await conn.scalar(
                    sa.text("SELECT epoch FROM studio.access_epochs WHERE tenant_id = :t"),
                    {"t": company.t},
                )
            )

    before = await epoch()
    await set_default_access(migrator, company.lead, "private")
    assert await epoch() == before
    await set_default_access(migrator, company.lead, "public_read")
    assert await epoch() == before + 1


# -- R6 (RA17, RA18): the actor kind ------------------------------------------------


async def test_r6_1_no_actor_kind_or_an_unknown_one_reaches_nothing(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    company = await plant_company(migrator)
    scope = TenantScope(tenant_id=company.t, principal_id=company.wide)
    for kind in (None, "admin"):
        async with app_engine.begin() as conn:
            await bind_tenant(conn, scope)
            if kind is not None:
                await conn.execute(
                    sa.text("SELECT set_config('app.actor_kind', :k, true)"), {"k": kind}
                )
            await conn.execute(sa.text("SELECT studio.ensure_principal_scope()"))
            assert await conn.scalar(sa.text("SELECT studio.acl_user()")) == company.wide
            assert await conn.scalar(sa.text("SELECT count(*) FROM studio.records")) == 0, kind
        with pytest.raises(DBAPIError) as caught:
            async with app_engine.begin() as conn:
                await bind_tenant(
                    conn, TenantScope(tenant_id=company.t, principal_id=company.creator)
                )
                if kind is not None:
                    await conn.execute(
                        sa.text("SELECT set_config('app.actor_kind', :k, true)"), {"k": kind}
                    )
                await conn.execute(sa.text("SELECT studio.ensure_principal_scope()"))
                await conn.execute(
                    sa.text(_INSERT),
                    {
                        "t": company.t,
                        "o": company.lead,
                        "w": company.mkt,
                        "kind": "user",
                        "owner": company.creator,
                    },
                )
        assert "row-level security" in str(caught.value), kind


def _context(company: Company, who: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=company.t,
        workspace_id=company.mkt,
        principal_id=who,
        roles=frozenset(),
        plan_id="professional",
    )


async def test_r6_2_a_studio_request_binds_user_and_the_reach_before_its_first_statement(
    migrator: AsyncEngine, studio_db: DatabaseUrls
) -> None:
    """The helper's transaction carries `user`, the caller and a valid ledger
    row before the caller's first statement, and reads the caller's reach; a
    run's session opened from the same context, not through the helper, reads
    no record."""
    company = await plant_company(migrator)
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with user_session(sessions, _context(company, company.ws_reader)) as session:
            row = (
                await session.execute(
                    sa.text(
                        "SELECT current_setting('app.actor_kind', true) AS kind,"
                        " current_setting('app.user_id', true) AS who,"
                        " (SELECT state FROM studio.principal_scopes) AS state"
                    )
                )
            ).one()
            seen = set((await session.execute(sa.text("SELECT id FROM studio.records"))).scalars())
        async with tenant_session(
            sessions, TenantScope.from_access_context(_context(company, company.ws_reader))
        ) as session:
            await session.execute(sa.text("SELECT studio.ensure_principal_scope()"))
            run = await session.scalar(sa.text("SELECT count(*) FROM studio.records"))
    finally:
        await engine.dispose()
    assert (row.kind, row.who, row.state) == ("user", str(company.ws_reader), "valid")
    assert seen == {company.mine, company.peers}
    assert run == 0


# -- R7 (RA22, RA23): the tenant-wide scope -----------------------------------------


async def test_r7_1_the_tenant_wide_scope_reads_every_record_of_one_tenant_for_one_transaction(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """For A, with no actor kind and no principal: every record of A, none of
    B. The next transaction on the same connection, bound to B through the
    door, has an empty scope and reads only its reach."""
    a = await plant_company(migrator)
    b = await plant_company(migrator)
    async with app_engine.connect() as conn:
        async with conn.begin():
            await tenant_wide_scope(conn, a.t, OFFBOARDING_LANE, OFFBOARDING_SCOPES)
            tenants = (
                await conn.execute(
                    sa.text("SELECT tenant_id, count(*) FROM studio.records GROUP BY 1")
                )
            ).all()
        async with conn.begin():
            await act_as_user(conn, b.t, b.me)
            scope = await conn.scalar(
                sa.text("SELECT current_setting('app.workspace_scope', true)")
            )
            seen = set((await conn.execute(sa.text("SELECT id FROM studio.records"))).scalars())
    assert [tuple(r) for r in tenants] == [(a.t, 5)]
    assert scope in ("", None)
    assert seen == {b.mine}


async def test_r7_2_an_unregistered_lane_is_refused_before_anything_is_set(
    app_engine: AsyncEngine,
) -> None:
    async with app_engine.begin() as conn:
        with pytest.raises(TenantWideScopeRefusedError):
            await tenant_wide_scope(conn, uuid.uuid4(), "record_index", OFFBOARDING_SCOPES)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT current_setting('app.workspace_scope', true) AS scope,"
                    " current_setting('app.tenant_id', true) AS tenant"
                )
            )
        ).one()
    assert row.scope in ("", None) and row.tenant in ("", None)


async def _tenant_in(migrator: AsyncEngine, remainder: int) -> Company:
    for _ in range(64):
        company = await plant_company(migrator)
        async with migrator.connect() as conn:
            lands = await conn.scalar(
                sa.text(
                    "SELECT satisfies_hash_partition('studio.records'::regclass, 4, :r,"
                    " CAST(:t AS uuid))"
                ),
                {"r": remainder, "t": company.t},
            )
        if lands:
            return company
    raise AssertionError("no tenant hashed to the partition")


async def test_r7_3_g1_offboarding_exports_each_record_once_and_purges_them(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """R7.3 (RA23), G1: records of three owners, one of whom has left the
    company, in one hash partition; another company in another. The bundle
    holds each of the leaving company's records once and none of the other's;
    after the purge none is left, and the other's are untouched."""
    leaving = await _tenant_in(migrator, 1)
    staying = await _tenant_in(migrator, 2)
    async with migrator.begin() as conn:
        third = await person(conn, leaving.tenant, {})
        await plant_record(conn, leaving.t, leaving.lead, leaving.mkt, third)
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u"),
            {"t": leaving.t, "u": third},
        )
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": leaving.t},
        )
        owners = set(
            (
                await conn.execute(
                    sa.text("SELECT DISTINCT owner_id FROM studio.records WHERE tenant_id = :t"),
                    {"t": leaving.t},
                )
            ).scalars()
        )
        kept = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE tenant_id = :t"), {"t": staying.t}
        )
    assert len(owners) >= 3 and third in owners
    sessions = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    lane = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    exported: list[dict[str, Any]] = []
    async for batch in lane.export_rows(leaving.t):
        if (batch.schema, batch.table) == ("studio", "records"):
            exported.extend(batch.rows)
        assert not batch.table.startswith("records_p"), batch.table
    ids = [row["id"] for row in exported]
    assert len(ids) == len(set(ids)) == 6
    assert {row["tenant_id"] for row in exported} == {leaving.t}
    await lane.purge_rows(leaving.t)
    async with migrator.connect() as conn:
        left = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE tenant_id = :t"), {"t": leaving.t}
        )
        still = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.records WHERE tenant_id = :t"), {"t": staying.t}
        )
    assert left == 0
    assert still == kept == 5


# -- R4.1 (RA8): the catalog holds what the module renders --------------------------

_POLICY_ROWS = sa.text(
    """
    SELECT p.polname || ' ' || p.polpermissive::text || ' ' || p.polcmd::text
           || ' ' || p.polroles::text
           || ' ' || coalesce(pg_get_expr(p.polqual, p.polrelid), '')
           || ' ' || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') AS policy
    FROM pg_policy p WHERE p.polrelid = CAST(:t AS regclass) ORDER BY p.polname
    """
)


async def policy_drift(conn: AsyncConnection) -> list[str]:
    """Each record table whose policies differ from the module's rendering,
    built on a probe table of the same columns in the caller's transaction."""
    await conn.execute(
        sa.text("CREATE TABLE public.record_policy_probe (LIKE studio.records INCLUDING GENERATED)")
    )
    for policy in record_policies("records"):
        await conn.execute(sa.text(policy.create_sql("public.record_policy_probe")))
    want = list((await conn.execute(_POLICY_ROWS, {"t": "public.record_policy_probe"})).scalars())
    tables = [
        "studio.records",
        *(
            f"studio.{name}"
            for name in (
                await conn.execute(
                    sa.text(
                        "SELECT c.relname FROM pg_inherits i JOIN pg_class c"
                        " ON c.oid = i.inhrelid WHERE i.inhparent = 'studio.records'::regclass"
                    )
                )
            ).scalars()
        ),
    ]
    found = []
    for table in tables:
        held = list((await conn.execute(_POLICY_ROWS, {"t": table})).scalars())
        if held != want:
            found.append(table)
    return found


async def test_r4_1_every_record_table_holds_the_module_s_policies(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        tx = await conn.begin()
        try:
            assert await policy_drift(conn) == []
        finally:
            await tx.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER POLICY record_access_records_select ON studio.records_p1 USING (true)",
        "CREATE POLICY wide ON studio.records USING (true)",
        "ALTER POLICY record_access_records_update ON studio.records"
        " WITH CHECK (tenant_id"
        " = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ],
)
async def test_r4_1_a_policy_bent_away_from_the_module_is_named(
    migrator: AsyncEngine, statement: str
) -> None:
    async with migrator.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(sa.text(statement))
            found = await policy_drift(conn)
        finally:
            await tx.rollback()
    assert found


async def test_r4_1_a_module_changed_without_a_revision_is_named(
    migrator: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module's reach changed (the own arm dropped from `delete`) and no
    revision applied it: the comparison names every record table."""
    from dw_studio.records.adapters import record_policy

    original = record_policy.reach_sql

    def bent(command: Any) -> str:
        text = original(command)
        return text.replace(" OR (owner_id", " AND (owner_id") if command == "delete" else text

    monkeypatch.setattr(record_policy, "reach_sql", bent)
    async with migrator.connect() as conn:
        tx = await conn.begin()
        try:
            found = await policy_drift(conn)
        finally:
            await tx.rollback()
    assert "studio.records" in found and len(found) >= 5


# -- R9.10: the standard page plans no sequential scan at 10^5 records ---------------

_PAGE = (
    "SELECT id FROM studio.records WHERE tenant_id = '{t}' AND object_id = '{o}'"
    " AND deleted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 50"
)


def _seq_scans(plan: Any) -> list[str]:
    found = []
    if isinstance(plan, dict):
        if plan.get("Node Type") == "Seq Scan" and str(plan.get("Relation Name", "")).startswith(
            "records"
        ):
            found.append(plan["Relation Name"])
        for value in plan.values():
            found += _seq_scans(value)
    elif isinstance(plan, list):
        for value in plan:
            found += _seq_scans(value)
    return found


async def test_r9_10_the_standard_page_plans_no_sequential_scan_for_any_profile(
    migrator: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """10^5 records of one company over two objects, forty owners and both
    workspaces, analysed; the page custom-objects/04 will compile, planned
    freely, for own, workspace and tenant depth and through `public_read`."""
    company = await plant_company(migrator)
    lead, mkt, sales = company.lead, company.mkt, company.sales_ws
    async with migrator.begin() as conn:
        owners = [company.me, company.peer]
        for _ in range(38):
            owners.append(await person(conn, company.tenant, {}))
        public = (await plant_object(conn, company.tenant, "public_lead", {})).object_id
        await conn.execute(
            sa.text("UPDATE studio.object_defs SET default_access = 'public_read' WHERE id = :o"),
            {"o": public},
        )
        reader = await person(conn, company.tenant, {mkt: ((public, "read", "own"),)})
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(company.t)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
                " owner_id, name, created_at, created_by, updated_by)"
                " SELECT gen_random_uuid(), :t,"
                "  (ARRAY[CAST(:lead AS uuid), CAST(:campaign AS uuid), CAST(:public AS uuid)])"
                "   [1 + n % 3],"
                "  (ARRAY[CAST(:mkt AS uuid), CAST(:sales AS uuid)])[1 + (n / 3) % 2],"
                "  'user', (CAST(:owners AS uuid[]))[1 + n % 40], 'Bản ghi ' || n,"
                "  now() - n * interval '1 minute', :me, :me"
                " FROM generate_series(1, 100000) n"
            ),
            {
                "t": company.t,
                "lead": lead,
                "campaign": company.campaign,
                "public": public,
                "mkt": mkt,
                "sales": sales,
                "owners": [str(o) for o in owners],
                "me": company.me,
            },
        )
    async with migrator.begin() as conn:
        await conn.execute(sa.text("ANALYZE studio.records"))
    profiles = {
        "own": (company.me, lead),
        "workspace": (company.ws_reader, lead),
        "tenant": (company.wide, lead),
        "public_read": (reader, public),
    }
    for profile, (who, obj) in profiles.items():
        async with app_engine.begin() as conn:
            await act_as_user(conn, company.t, who)
            plan = (
                await conn.execute(
                    sa.text("EXPLAIN (FORMAT JSON) " + _PAGE.format(t=company.t, o=obj))
                )
            ).scalar_one()
            page = (await conn.execute(sa.text(_PAGE.format(t=company.t, o=obj)))).all()
        plan = json.loads(plan) if isinstance(plan, str) else plan
        assert _seq_scans(plan) == [], (profile, json.dumps(plan)[:2000])
        assert len(page) == 50, profile
