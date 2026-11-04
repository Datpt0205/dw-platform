"""`platform.control_switches` and `platform.platform_freezes` against the
catalog and the roles that write them (agent-lifecycle ticket 01: R7.1, R7.4,
R7.5, R7.10, R10.1; AL12, AL16, AL18; migration 8efd60e59d32).

Every write here goes in as the role the code uses (`dw_app` under one
company's RLS, `dw_provisioner` for an operator's switch), so a refusal is
the database's, not a repository's: lifting without the second person,
changing anything but the lift, deleting outside offboarding, a company
writing an operator's switch, one company reading another's.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from pg_test_db import provisioner_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.rbac import PlantedTenant, plant_person, plant_tenant

pytestmark = pytest.mark.integration

UNFREEZE = "studio.lifecycle.unfreeze"


@dataclass
class Db:
    migrator: AsyncEngine
    app: AsyncEngine
    provisioner: AsyncEngine
    a: PlantedTenant
    b: PlantedTenant
    asker: uuid.UUID
    decider: uuid.UUID

    @asynccontextmanager
    async def as_app(self, tenant: uuid.UUID | None) -> AsyncIterator[AsyncConnection]:
        async with self.app.begin() as conn:
            if tenant is not None:
                await conn.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
                )
            yield conn

    async def freeze(self, tenant: PlantedTenant | None = None) -> uuid.UUID:
        target = tenant or self.a
        switch = uuid.uuid4()
        async with self.as_app(target.tenant_id) as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                    " origin, reason_code, reason, set_by)"
                    " VALUES (:id, :t, 'tenant', 'freeze', 'tenant', 'incident', 'sự cố', :by)"
                ),
                {"id": switch, "t": target.tenant_id, "by": self.asker},
            )
        return switch

    async def kill(self) -> uuid.UUID:
        switch = uuid.uuid4()
        async with self.as_app(self.a.tenant_id) as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.control_switches (id, tenant_id, scope_type,"
                    " owning_workspace_id, target_id, action, origin, reason_code, reason,"
                    " set_by) VALUES (:id, :t, 'agent', :w, gen_random_uuid(), 'kill', 'tenant',"
                    " 'abuse', 'lạm dụng', :by)"
                ),
                {"id": switch, "t": self.a.tenant_id, "w": self.a.main, "by": self.asker},
            )
        return switch

    async def operator_freeze(self, tenant: PlantedTenant) -> uuid.UUID:
        switch = uuid.uuid4()
        async with self.provisioner.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                    " origin, reason_code, reason, set_by)"
                    " VALUES (:id, :t, 'tenant', 'freeze', 'platform', 'abuse', 'nhà vận hành',"
                    " :by)"
                ),
                {"id": switch, "t": tenant.tenant_id, "by": self.decider},
            )
        return switch

    async def request(
        self,
        switch: uuid.UUID,
        *,
        approval_type: str = UNFREEZE,
        status: str = "approved",
        decided_by: uuid.UUID | None = None,
        tenant: PlantedTenant | None = None,
    ) -> uuid.UUID:
        """A lift request as the approval flow leaves it, written as the
        migrator: the trigger reads it, it does not care who wrote it."""
        target = tenant or self.a
        approval = uuid.uuid4()
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                    " approval_type, requested_by, payload, status)"
                    " VALUES (:a, :t, :w, :k, :r,"
                    " jsonb_build_object('switch_id', CAST(:s AS text)), :st)"
                ),
                {
                    "a": approval,
                    "t": target.tenant_id,
                    "w": target.main,
                    "k": approval_type,
                    "r": self.asker,
                    "s": str(switch),
                    "st": status,
                },
            )
            if status == "approved":
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.approval_decisions (id, request_id, tenant_id,"
                        " workspace_id, decided_by, outcome, decided_at)"
                        " VALUES (gen_random_uuid(), :a, :t, :w, :d, 'approved', now())"
                    ),
                    {
                        "a": approval,
                        "t": target.tenant_id,
                        "w": target.main,
                        "d": decided_by or self.decider,
                    },
                )
        return approval

    async def lift(self, switch: uuid.UUID, approval: uuid.UUID | None) -> None:
        async with self.as_app(self.a.tenant_id) as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.control_switches SET lifted_at = now(), lifted_by = :d,"
                    " lift_approval_id = :a WHERE id = :s"
                ),
                {"d": self.decider, "a": approval, "s": switch},
            )

    async def row(self, switch: uuid.UUID) -> Any:
        async with self.migrator.connect() as conn:
            return (
                await conn.execute(
                    sa.text("SELECT * FROM platform.control_switches WHERE id = :s"), {"s": switch}
                )
            ).first()


@pytest.fixture
async def db(db_urls: DatabaseUrls) -> AsyncIterator[Db]:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    app = create_async_engine(db_urls.app, poolclass=NullPool)
    provisioner = create_async_engine(provisioner_url(db_urls.migrator), poolclass=NullPool)
    async with migrator.begin() as conn:
        a, b = await plant_tenant(conn), await plant_tenant(conn)
        asker = await plant_person(conn, a.tenant_id)
        decider = await plant_person(conn, a.tenant_id)
    try:
        yield Db(migrator, app, provisioner, a, b, asker, decider)
    finally:
        for engine in (provisioner, app, migrator):
            await engine.dispose()


def _check_violation(exc: BaseException) -> str:
    """The constraint a 23514 names."""
    assert isinstance(exc, DBAPIError)
    orig: Any = exc.orig
    assert getattr(orig, "sqlstate", None) == "23514", exc
    return str(getattr(orig.__cause__, "constraint_name", "") or orig)


# ---- what is written ---------------------------------------------------------------


async def test_a_company_cannot_write_an_operators_switch_nor_a_freeze_that_is_a_kill(
    db: Db,
) -> None:
    """R7.10 (AL18): `dw_app` inserting an `origin='platform'` row, or a
    company-scope row whose action is `kill`, is 23514; so is a row inserted
    already lifted."""
    statements = {
        "ck_control_switches_platform_origin": (
            "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action, origin,"
            " reason_code, reason, set_by) VALUES (gen_random_uuid(), :t, 'tenant', 'freeze',"
            " 'platform', 'other', 'x', gen_random_uuid())"
        ),
        "ck_control_switches_scope_action": (
            "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action, origin,"
            " reason_code, reason, set_by) VALUES (gen_random_uuid(), :t, 'tenant', 'kill',"
            " 'tenant', 'other', 'x', gen_random_uuid())"
        ),
        "ck_control_switches_insert_open": (
            "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action, origin,"
            " reason_code, reason, set_by, lifted_at, lifted_by) VALUES (gen_random_uuid(), :t,"
            " 'tenant', 'freeze', 'tenant', 'other', 'x', gen_random_uuid(), now(),"
            " gen_random_uuid())"
        ),
    }
    for constraint, statement in statements.items():
        with pytest.raises(DBAPIError) as refused:
            async with db.as_app(db.a.tenant_id) as conn:
                await conn.execute(sa.text(statement), {"t": db.a.tenant_id})
        assert constraint in _check_violation(refused.value)


async def test_a_company_freeze_and_an_operator_freeze_are_both_open_one_each(db: Db) -> None:
    """R7.10, ADR-0120 decision 5 amended 2026-11-04: one open switch per
    target and origin."""
    await db.freeze()
    await db.operator_freeze(db.a)
    with pytest.raises(IntegrityError, match="uq_control_switches_open"):
        await db.freeze()
    with pytest.raises(IntegrityError, match="uq_control_switches_open"):
        await db.operator_freeze(db.a)


async def test_only_one_platform_freeze_is_open_and_only_the_provisioner_writes_it(
    db: Db,
) -> None:
    first = uuid.uuid4()
    async with db.provisioner.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.platform_freezes (id, reason_code, reason, set_by)"
                " VALUES (:id, 'maintenance', 'bảo trì', gen_random_uuid())"
            ),
            {"id": first},
        )
    try:
        with pytest.raises(IntegrityError, match="uq_platform_freezes_open"):
            async with db.provisioner.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.platform_freezes (id, reason_code, reason, set_by)"
                        " VALUES (gen_random_uuid(), 'other', 'x', gen_random_uuid())"
                    )
                )
        with pytest.raises(DBAPIError, match="permission denied"):
            async with db.as_app(db.a.tenant_id) as conn:
                await conn.execute(
                    sa.text("UPDATE platform.platform_freezes SET lifted_at = now()")
                )
    finally:
        async with db.provisioner.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.platform_freezes SET lifted_at = now(),"
                    " lifted_by = gen_random_uuid() WHERE id = :id"
                ),
                {"id": first},
            )


# ---- R7.5: one lift, by the second person's approval -----------------------------


async def test_a_company_freeze_lifts_only_with_its_approved_second_person_request(
    db: Db,
) -> None:
    """R7.5 (AL12): without an approval, with a pending one, one of another
    type, one naming another switch, one its requester decided, each 23514
    and the freeze still open; the right one lifts it, once."""
    switch = await db.freeze()
    other = await db.kill()
    wrong = {
        "none": None,
        "pending": await db.request(switch, status="pending"),
        "type": await db.request(switch, approval_type="studio.lifecycle.revive"),
        "switch": await db.request(other),
        "self": await db.request(switch, decided_by=db.asker),
    }
    for case, approval in wrong.items():
        with pytest.raises(DBAPIError) as refused:
            await db.lift(switch, approval)
        assert "ck_control_switches_lift_approval" in _check_violation(refused.value), case
        assert (await db.row(switch)).lifted_at is None, case

    right = await db.request(switch)
    await db.lift(switch, right)
    lifted = await db.row(switch)
    assert (lifted.lift_approval_id, lifted.lifted_by) == (right, db.decider)

    with pytest.raises(DBAPIError) as again:
        await db.lift(switch, right)
    assert "ck_control_switches_lift_once" in _check_violation(again.value)


async def test_a_lift_changes_nothing_else(db: Db) -> None:
    """R7.5 (AL12): any other column in the same UPDATE is 23514; `dw_app`
    may not even name one outside its grant."""
    switch = await db.freeze()
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.as_app(db.a.tenant_id) as conn:
            await conn.execute(
                sa.text("UPDATE platform.control_switches SET reason = 'khác' WHERE id = :s"),
                {"s": switch},
            )
    async with db.migrator.begin() as conn:
        with pytest.raises(DBAPIError) as refused:
            await conn.execute(
                sa.text(
                    "UPDATE platform.control_switches SET reason = 'khác', lifted_at = now(),"
                    " lifted_by = gen_random_uuid() WHERE id = :s"
                ),
                {"s": switch},
            )
    assert "ck_control_switches_lift_once" in _check_violation(refused.value)


async def test_an_operators_freeze_is_lifted_by_the_provisioner_alone(db: Db) -> None:
    """R7.4 (AL12): not by the company, not even with an approval; and the
    provisioner never lifts the company's own."""
    operator = await db.operator_freeze(db.a)
    approval = await db.request(operator)
    with pytest.raises(DBAPIError) as refused:
        await db.lift(operator, approval)
    assert "ck_control_switches_platform_lift" in _check_violation(refused.value)

    own = await db.freeze()
    async with db.provisioner.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(
                sa.text(
                    "UPDATE platform.control_switches SET lifted_at = now(),"
                    " lifted_by = gen_random_uuid() WHERE id = :s"
                ),
                {"s": own},
            )
        await conn.rollback()
    async with db.provisioner.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.control_switches SET lifted_at = now(),"
                " lifted_by = gen_random_uuid() WHERE id = :s"
            ),
            {"s": operator},
        )
    assert (await db.row(operator)).lifted_at is not None
    assert (await db.row(own)).lifted_at is None


async def test_a_lift_cannot_name_another_companys_approval(db: Db) -> None:
    """R7.5: the composite key to `uq_approval_requests_tenant_id_id`."""
    switch = await db.freeze()
    theirs = await db.request(switch, tenant=db.b)
    with pytest.raises(DBAPIError):
        await db.lift(switch, theirs)
    assert (await db.row(switch)).lifted_at is None


# ---- R7.5, R10.1: deleted only by offboarding --------------------------------------


async def test_a_kill_of_an_active_company_is_not_deleted(db: Db) -> None:
    """R7.5 (AL12): 23514, the switch still there."""
    kill = await db.kill()
    with pytest.raises(DBAPIError) as refused:
        async with db.as_app(db.a.tenant_id) as conn:
            await conn.execute(
                sa.text("DELETE FROM platform.control_switches WHERE id = :s"), {"s": kill}
            )
    assert "ck_control_switches_delete" in _check_violation(refused.value)
    assert await db.row(kill) is not None


async def test_a_company_offboarding_has_its_switches_deleted(db: Db) -> None:
    """R10.1: the offboarding lane's delete passes once the company is
    `offboarding`."""
    kill = await db.kill()
    async with db.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": db.a.tenant_id},
        )
    async with db.as_app(db.a.tenant_id) as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.control_switches WHERE id = :s"), {"s": kill}
        )
    assert await db.row(kill) is None


# ---- AL16: one company's switches are its own -------------------------------------


async def test_a_company_reads_none_of_another_companys_switches(db: Db) -> None:
    """R7.1 (AL16): under A's tenant, 0 rows of B; with no tenant, 0 rows."""
    await db.freeze(db.b)
    for tenant in (db.a.tenant_id, None):
        async with db.as_app(tenant) as conn:
            seen = await conn.scalar(
                sa.text("SELECT count(*) FROM platform.control_switches WHERE tenant_id = :b"),
                {"b": db.b.tenant_id},
            )
        assert seen == 0, tenant
    async with db.as_app(db.b.tenant_id) as conn:
        assert await conn.scalar(sa.text("SELECT count(*) FROM platform.control_switches")) == 1


async def test_a_company_cannot_write_a_switch_for_another(db: Db) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.as_app(db.a.tenant_id) as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                    " origin, reason_code, reason, set_by) VALUES (gen_random_uuid(), :b,"
                    " 'tenant', 'freeze', 'tenant', 'other', 'x', gen_random_uuid())"
                ),
                {"b": db.b.tenant_id},
            )


# ---- R7.10: one pending lift per switch -------------------------------------------


async def test_a_second_pending_lift_of_the_same_switch_is_refused(db: Db) -> None:
    switch = await db.freeze()
    await db.request(switch, status="pending")
    with pytest.raises(IntegrityError, match="uq_approval_requests_control_lift_pending"):
        await db.request(switch, status="pending")
    await db.request(await db.kill(), status="pending", approval_type="studio.lifecycle.revive")


# ---- R7.1: the notification carries the company -----------------------------------


async def test_a_change_is_announced_with_its_company_and_a_platform_freeze_to_all(
    db: Db, db_urls: DatabaseUrls
) -> None:
    """R7.1: `{"tenant_id", "id"}` for a switch, `{"platform": true}` for a
    platform freeze; a write rolled back announces nothing."""
    heard: asyncio.Queue[str] = asyncio.Queue()
    dsn = db_urls.app.replace("postgresql+asyncpg://", "postgresql://", 1)
    listener = await asyncpg.connect(dsn)
    await listener.add_listener("dw_control_switch", lambda *a: heard.put_nowait(a[3]))
    try:
        async with db.app.connect() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(db.a.tenant_id)},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                    " origin, reason_code, reason, set_by) VALUES (gen_random_uuid(), :t,"
                    " 'tenant', 'freeze', 'tenant', 'other', 'x', gen_random_uuid())"
                ),
                {"t": db.a.tenant_id},
            )
            await conn.rollback()
        switch = await db.freeze()
        assert json.loads(await asyncio.wait_for(heard.get(), 5)) == {
            "tenant_id": str(db.a.tenant_id),
            "id": str(switch),
        }
        freeze = uuid.uuid4()
        async with db.provisioner.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.platform_freezes (id, reason_code, reason, set_by)"
                    " VALUES (:id, 'test', 'thử', gen_random_uuid())"
                ),
                {"id": freeze},
            )
        try:
            assert json.loads(await asyncio.wait_for(heard.get(), 5)) == {"platform": True}
        finally:
            async with db.provisioner.begin() as conn:
                await conn.execute(
                    sa.text(
                        "UPDATE platform.platform_freezes SET lifted_at = now(),"
                        " lifted_by = gen_random_uuid() WHERE id = :id"
                    ),
                    {"id": freeze},
                )
        assert heard.qsize() <= 1  # only the lift, never the rolled-back insert
    finally:
        await listener.close()
