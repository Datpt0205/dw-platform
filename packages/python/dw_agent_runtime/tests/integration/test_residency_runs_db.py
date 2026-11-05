"""A run's data route class is pinned where it is admitted, on its row and in
its context, and a resume reads it back (compliance-pdpl R2.1; ADR-0123
decisions 3, 6; Amendments 2026-11-04).

Against PostgreSQL: the class is read in the transaction that writes the row,
it is the strictest of the tenant's and the workspace's, a workspace tightened
after admission does not change a run already admitted, and a row admitted
before the column existed resumes `vn_only`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from runtime_harness import RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore, resume_context
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER
from dw_platform.adapters.persistence import tables

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def migrator(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def store(urls: RuntimeUrls) -> AsyncIterator[SqlWorkerRunStore]:
    engine = create_async_engine(urls.app, poolclass=NullPool)
    try:
        yield SqlWorkerRunStore(
            async_sessionmaker(engine, expire_on_commit=False), stale_run_after_seconds=3600
        )
    finally:
        await engine.dispose()


async def _company(
    migrator: AsyncEngine, tenant_class: str, workspace_class: str | None
) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(
                id=tenant_id,
                slug=f"route-{tenant_id.hex[:12]}",
                name="route",
                data_route_class=tenant_class,
            )
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=workspace_id,
                tenant_id=tenant_id,
                slug="main",
                name="Main",
                data_route_class=workspace_class,
            )
        )
    return tenant_id, workspace_id


async def _row_class(migrator: AsyncEngine, run_id: uuid.UUID) -> str | None:
    async with migrator.connect() as conn:
        value: str | None = await conn.scalar(
            sa.text("SELECT data_route_class FROM platform.worker_runs WHERE id = :r"),
            {"r": run_id},
        )
    return value


@pytest.mark.parametrize(
    ("tenant_class", "workspace_class", "pinned"),
    [
        ("cross_border_full", None, "cross_border_full"),
        ("cross_border_full", "cross_border_minimised", "cross_border_minimised"),
        ("cross_border_minimised", "vn_only", "vn_only"),
        ("vn_only", None, "vn_only"),
    ],
)
async def test_admission_pins_the_strictest_class_on_the_row_and_the_context(
    migrator: AsyncEngine,
    store: SqlWorkerRunStore,
    tenant_class: str,
    workspace_class: str | None,
    pinned: str,
) -> None:
    tenant_id, workspace_id = await _company(migrator, tenant_class, workspace_class)
    context = make_run_context(tenant=tenant_id, workspace=workspace_id, thread_id=uuid.uuid4())
    # A caller's context says nothing the admission reads: it is overwritten.
    assert context.route_class == "vn_only"

    admitted = await store.create(context, worker=DEMO_WORKER, input_payload={})

    assert admitted.route_class == pinned
    assert await _row_class(migrator, context.run_id) == pinned


async def test_a_resume_reads_the_row_and_never_recomputes_the_class(
    migrator: AsyncEngine, store: SqlWorkerRunStore
) -> None:
    """R2.1: the workspace is tightened after the run was admitted; the resume
    still carries the class the run was admitted with."""
    tenant_id, workspace_id = await _company(migrator, "cross_border_full", None)
    context = make_run_context(tenant=tenant_id, workspace=workspace_id, thread_id=uuid.uuid4())
    admitted = await store.create(context, worker=DEMO_WORKER, input_payload={})
    async with migrator.begin() as conn:
        await conn.execute(
            sa.update(tables.workspaces)
            .where(tables.workspaces.c.id == workspace_id)
            .values(data_route_class="vn_only")
        )

    record = await store.get(admitted, admitted.run_id)
    resumed = resume_context(record, tenant_id=tenant_id, channel="web")

    assert resumed.route_class == "cross_border_full"


async def test_a_row_admitted_before_the_column_resumes_vn_only(
    migrator: AsyncEngine, store: SqlWorkerRunStore
) -> None:
    tenant_id, workspace_id = await _company(migrator, "cross_border_full", None)
    context = make_run_context(tenant=tenant_id, workspace=workspace_id, thread_id=uuid.uuid4())
    await store.create(context, worker=DEMO_WORKER, input_payload={})
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.worker_runs SET data_route_class = NULL WHERE id = :r"),
            {"r": context.run_id},
        )

    record = await store.get(context, context.run_id)

    assert resume_context(record, tenant_id=tenant_id, channel="web").route_class == "vn_only"
