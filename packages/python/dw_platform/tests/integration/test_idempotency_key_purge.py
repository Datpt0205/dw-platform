"""Integration: the purge of `platform.idempotency_keys`, against real Postgres.

app-standards ticket 04 (R2.8, R2.9, R2.13, R2.15; APS14). The replay cache is
emptied of every tenant's expired rows through one no-argument function that
hands back a count and nothing else, and reads its term from
`platform.retention_terms`, never from a default of its own.

The function is called as `dw_app` with no tenant set, which is how the
retention lane's purger calls it: the point is that it crosses tenants without
any connection being able to read across them. Terms are changed as the
migrator, inside a transaction that is rolled back, because `dw_app` may not
write `platform.retention_terms` (82e168f6d189).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.idempotency_store import SqlIdempotencyKeyRetention
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID(int=0x9A40)
WORKSPACE_A = uuid.UUID(int=0x9A41)
TENANT_B = uuid.UUID(int=0x9B40)
WORKSPACE_B = uuid.UUID(int=0x9B41)
WORKSPACES = {TENANT_A: WORKSPACE_A, TENANT_B: WORKSPACE_B}

PURGE = sa.text("SELECT platform.purge_expired_idempotency_keys()")


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    for tenant_id, slug in ((TENANT_A, "purge-tenant-a"), (TENANT_B, "purge-tenant-b")):
        async with tenant_session(factory, TenantScope(tenant_id=tenant_id)) as session:
            await session.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name) VALUES (:id, :slug, :slug) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(tenant_id), "slug": slug},
            )
            await session.execute(
                sa.text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name) "
                    "VALUES (:id, :tenant, 'main', 'Main') ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(WORKSPACES[tenant_id]), "tenant": str(tenant_id)},
            )
    return factory


async def key_aged(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, hours: int
) -> str:
    """A completed key of `tenant_id` whose reservation began `hours` ago."""
    key = f"purge-{hours}h-{uuid.uuid4()}"
    async with tenant_session(sessions, TenantScope(tenant_id=tenant_id)) as session:
        await session.execute(
            sa.text(
                "INSERT INTO platform.idempotency_keys (tenant_id, idempotency_key,"
                " workspace_id, request_method, request_path, body_hash, response_status,"
                " response_body, created_at, completed_at)"
                " VALUES (:t, :k, :w, 'POST', '/p', 'h', 201, '{\"secret\": 1}',"
                " now() - make_interval(hours => :h), now() - make_interval(hours => :h))"
            ),
            {"t": str(tenant_id), "k": key, "w": str(WORKSPACES[tenant_id]), "h": hours},
        )
    return key


async def present(conn: AsyncConnection | AsyncEngine, key: str) -> bool:
    statement = sa.text("SELECT count(*) FROM platform.idempotency_keys WHERE idempotency_key = :k")
    if isinstance(conn, AsyncEngine):
        async with conn.connect() as fresh:
            return bool(await fresh.scalar(statement, {"k": key}))
    return bool(await conn.scalar(statement, {"k": key}))


async def test_expired_keys_of_every_tenant_go_and_young_ones_stay(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.8, R2.13 (APS14): one call, no tenant set, removes the 25-hour rows of
    two tenants and keeps a 1-hour one, and hands back a count and no column of
    any row."""
    old_a = await key_aged(sessions, TENANT_A, 25)
    old_b = await key_aged(sessions, TENANT_B, 25)
    young = await key_aged(sessions, TENANT_A, 1)

    async with sessions() as session, session.begin():
        result = await session.execute(PURGE)
        rows = result.all()

    assert list(result.keys()) == ["purge_expired_idempotency_keys"]
    assert len(rows) == 1 and len(rows[0]) == 1
    assert isinstance(rows[0][0], int) and rows[0][0] >= 2
    assert not await present(migrator, old_a)
    assert not await present(migrator, old_b)
    assert await present(migrator, young)


async def test_the_term_is_read_from_retention_terms(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """ADR-0122 decision 7: counsel changes the term in the fragment, not in
    code. Under a 2-day term a 25-hour row is not expired, so a function that
    read the term and then used a day of its own would delete it."""
    kept = await key_aged(sessions, TENANT_A, 25)
    async with migrator.connect() as conn, conn.begin() as transaction:
        await conn.execute(
            sa.text(
                "UPDATE platform.retention_terms SET term_days = 2"
                " WHERE store_key = 'platform.idempotency_keys'"
            )
        )
        await conn.execute(PURGE)
        assert await present(conn, kept)
        await transaction.rollback()


async def test_a_missing_term_fails_and_removes_nothing(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R2.15 (APS14): with no term for the store the function raises, and the
    expired row is still there inside the same transaction; there is no
    default term to fall back to."""
    expired = await key_aged(sessions, TENANT_B, 25)
    async with migrator.connect() as conn, conn.begin() as transaction:
        await conn.execute(
            sa.text(
                "DELETE FROM platform.retention_terms WHERE store_key = 'platform.idempotency_keys'"
            )
        )
        savepoint = await conn.begin_nested()
        with pytest.raises(Exception, match="no retention term"):
            await conn.execute(PURGE)
        await savepoint.rollback()
        assert await present(conn, expired)
        await transaction.rollback()


async def test_the_registered_purger_logs_a_count_and_writes_no_audit_row(
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R2.9: housekeeping of operational rows (`CLAUDE.md` "Agent and tool
    rules"; ADR-0011 "Not applied")."""
    expired = await key_aged(sessions, TENANT_A, 25)
    async with migrator.connect() as conn:
        audits = await conn.scalar(sa.text("SELECT count(*) FROM platform.audit_events"))

    with caplog.at_level(logging.INFO):
        await SqlIdempotencyKeyRetention(sessions).purge()

    purged = [r for r in caplog.records if r.getMessage() == "idempotency keys purged"]
    assert purged and vars(purged[0])["deleted"] >= 1
    assert vars(purged[0])["retention_class"] == "platform.idempotency_keys"
    async with migrator.connect() as conn:
        assert await conn.scalar(sa.text("SELECT count(*) FROM platform.audit_events")) == audits
    assert not await present(migrator, expired)
