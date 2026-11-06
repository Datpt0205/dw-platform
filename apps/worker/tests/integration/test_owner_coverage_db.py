"""A tenant whose owners fell below two, told once per fall (tenant-rbac R3.12; RB40).

On a migrated Postgres: the coverage check of migration b5677d345bc1, run at
commit since tenant-rbac/08 (a7ca12c36ec7), sets
`platform.tenants.owner_coverage_low_since` and writes one
`platform.tenant.owner_coverage_low` event per fall; the handler wired in
`dw_worker.main` delivers one notification to each tenant-depth holder of
`platform.members.write`, in the workspace that anchors their holding.

`platform.roles.write` is in the catalogue since tenant-rbac ticket 03 and
`studio.publish.approve` since agent-lifecycle 04 (0353c313569f); an owner key
the catalogue lacks is registered for the test and removed after it, one it
holds is left alone.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.ids import TenantId, WorkspaceId
from dw_platform.adapters.persistence.notifications import SqlNotificationRepository
from dw_platform.adapters.persistence.scope_holders import SqlScopeHolders
from dw_platform.domain.outbox import OutboxEvent
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    unregister_key,
)
from dw_worker.consumers.owner_coverage import OWNER_COVERAGE_LOW, build_owner_coverage_handler

pytestmark = pytest.mark.integration

_OWNER_KEYS = ("platform.roles.write", "studio.publish.approve")


@pytest.fixture
async def migrator(worker_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(worker_db.migrator, poolclass=NullPool)
    async with engine.begin() as conn:
        held = set(
            await conn.scalars(
                sa.text("SELECT key FROM platform.permissions WHERE key = ANY(:k)"),
                {"k": list(_OWNER_KEYS)},
            )
        )
        uncatalogued = [key for key in _OWNER_KEYS if key not in held]
        for key in uncatalogued:
            await register_key(conn, key, scope_kind="tenant")
    yield engine
    async with engine.begin() as conn:
        for key in uncatalogued:
            await unregister_key(conn, key)
    await engine.dispose()


@pytest.fixture
async def app(worker_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(worker_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@dataclass(frozen=True)
class World:
    tenant: PlantedTenant
    admin_role: uuid.UUID
    admins: tuple[tuple[uuid.UUID, uuid.UUID], ...]  # (membership, assignment)
    told: dict[uuid.UUID, uuid.UUID]  # recipient -> the workspace anchoring them


async def _plant(conn: AsyncConnection) -> World:
    t = await plant_tenant(conn, workspaces=2)
    admin_role = await plant_role(
        conn, t.tenant_id, "r_owner_keys", dict.fromkeys(_OWNER_KEYS, "tenant")
    )
    admins = []
    for _ in range(2):
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        admins.append((membership, await assign(conn, t.tenant_id, t.main, membership, admin_role)))
    members_role = await plant_role(
        conn, t.tenant_id, "r_members", {"platform.members.write": "tenant"}
    )
    told = {}
    # One recipient anchored at `main`; one with no membership in `main` at all.
    for ws in t.workspaces:
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, ws, person)
        await assign(conn, t.tenant_id, ws, membership, members_role)
        told[person] = ws
    # Planting passed below two on its way up; the world starts covered.
    await conn.execute(
        sa.text("DELETE FROM platform.outbox_events WHERE tenant_id = :t AND event_type = :e"),
        {"t": t.tenant_id, "e": OWNER_COVERAGE_LOW},
    )
    return World(t, admin_role, tuple(admins), told)


async def _since(conn: AsyncConnection, w: World) -> object:
    return await conn.scalar(
        sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
        {"t": w.tenant.tenant_id},
    )


async def _events(conn: AsyncConnection, w: World) -> list[OutboxEvent]:
    rows = await conn.execute(
        sa.text(
            "SELECT * FROM platform.outbox_events WHERE tenant_id = :t AND event_type = :e"
            " ORDER BY occurred_at, id"
        ),
        {"t": w.tenant.tenant_id, "e": OWNER_COVERAGE_LOW},
    )
    return [
        OutboxEvent(
            id=r.id,
            tenant_id=TenantId(r.tenant_id),
            workspace_id=WorkspaceId(r.workspace_id),
            event_type=r.event_type,
            schema_version=r.schema_version,
            aggregate_id=r.aggregate_id,
            occurred_at=r.occurred_at,
            payload=r.payload,
        )
        for r in rows
    ]


async def _notified(conn: AsyncConnection, w: World) -> list[tuple[uuid.UUID, uuid.UUID]]:
    rows = await conn.execute(
        sa.text(
            "SELECT recipient_user_id, workspace_id FROM platform.notifications"
            " WHERE tenant_id = :t ORDER BY recipient_user_id, created_at"
        ),
        {"t": w.tenant.tenant_id},
    )
    return [(r.recipient_user_id, r.workspace_id) for r in rows]


async def _revoke(conn: AsyncConnection, assignment: uuid.UUID) -> None:
    await conn.execute(
        sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
    )


async def test_a_fall_below_two_tells_each_member_admin_once_where_they_are_anchored(
    migrator: AsyncEngine, app: AsyncEngine
) -> None:
    sessions = async_sessionmaker(app, expire_on_commit=False)
    handle = build_owner_coverage_handler(
        SqlScopeHolders(sessions), SqlNotificationRepository(sessions)
    )
    async with migrator.begin() as conn:
        w = await _plant(conn)
        assert await _since(conn, w) is None
    expected = sorted(w.told.items())

    # Every read follows its write's commit: the check runs there.
    async with migrator.begin() as conn:
        await _revoke(conn, w.admins[0][1])
    async with migrator.connect() as conn:
        assert await _since(conn, w) is not None
        [event] = await _events(conn, w)
    await handle(event)
    await handle(event)  # redelivered: the source key is the fall's
    async with migrator.connect() as conn:
        assert sorted(await _notified(conn, w)) == expected

    # Still below two: another revocation announces nothing.
    async with migrator.begin() as conn:
        await _revoke(conn, w.admins[1][1])
    async with migrator.connect() as conn:
        assert len(await _events(conn, w)) == 1

    # Back to two: the column clears; the next fall is a new notification.
    async with migrator.begin() as conn:
        again = [
            await assign(conn, w.tenant.tenant_id, w.tenant.main, membership, w.admin_role)
            for membership, _ in w.admins
        ]
    async with migrator.connect() as conn:
        assert await _since(conn, w) is None
    async with migrator.begin() as conn:
        await _revoke(conn, again[0])
    async with migrator.connect() as conn:
        events = await _events(conn, w)
        assert len(events) == 2
    await handle(events[1])
    async with migrator.connect() as conn:
        notified = await _notified(conn, w)
    assert sorted(set(notified)) == expected
    assert len(notified) == 2 * len(expected), "one notification per recipient per fall"
