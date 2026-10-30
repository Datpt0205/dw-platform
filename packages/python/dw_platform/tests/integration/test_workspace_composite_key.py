"""A composite foreign key cannot name another tenant's workspace (org-and-principals R1.1, OP1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _tenant_with_workspace(
    conn: AsyncConnection,
) -> tuple[uuid.UUID, uuid.UUID]:
    tenant, workspace = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        sa.text("INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)"),
        {"t": tenant, "s": f"ck-{tenant.hex[:10]}"},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
            " VALUES (:w, :t, 'main', 'Main')"
        ),
        {"w": workspace, "t": tenant},
    )
    return tenant, workspace


async def test_the_composite_key_exists_by_its_convention_name(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        definition = await conn.scalar(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'uq_workspaces_tenant_id_id'"
                "   AND conrelid = 'platform.workspaces'::regclass"
            )
        )
    assert definition == "UNIQUE (tenant_id, id)"


async def test_a_row_cannot_point_at_another_tenants_workspace(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        transaction = await conn.begin()
        try:
            tenant_a, workspace_a = await _tenant_with_workspace(conn)
            tenant_b, _ = await _tenant_with_workspace(conn)
            await conn.execute(
                sa.text(
                    "CREATE TABLE public.composite_fk_probe (tenant_id uuid NOT NULL,"
                    " workspace_id uuid NOT NULL, FOREIGN KEY (tenant_id, workspace_id)"
                    " REFERENCES platform.workspaces (tenant_id, id) ON DELETE CASCADE)"
                )
            )
            await conn.execute(
                sa.text("INSERT INTO public.composite_fk_probe VALUES (:t, :w)"),
                {"t": tenant_a, "w": workspace_a},
            )
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.IntegrityError, match="foreign key"):
                await conn.execute(
                    sa.text("INSERT INTO public.composite_fk_probe VALUES (:t, :w)"),
                    {"t": tenant_b, "w": workspace_a},
                )
            await savepoint.rollback()
            count = await conn.scalar(
                sa.text("SELECT count(*) FROM public.composite_fk_probe WHERE tenant_id = :t"),
                {"t": tenant_b},
            )
            assert count == 0
        finally:
            await transaction.rollback()
