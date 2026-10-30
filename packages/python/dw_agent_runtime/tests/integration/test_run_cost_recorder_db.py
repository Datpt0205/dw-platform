"""Integration: a run's model spend on its own row, on real PostgreSQL.

digital-worker ticket 03, R7.3: each model call of a run adds its cost to
that run's `model_cost_usd` in one adding statement; a call of another run,
or one made under another tenant naming this run, changes nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import sqlalchemy as sa
from runtime_harness import (
    TENANT_A,
    TENANT_B,
    WORKSPACE_A,
    WORKSPACE_B,
    RuntimeUrls,
    make_run_context,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.run_cost_recorder import RunCostRecorder
from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.ports import ModelRequest

pytestmark = pytest.mark.integration

REQUEST = ModelRequest(task="extract", prompt_id="p", prompt_version="1.0.0")


def usage(cost: float) -> ModelUsage:
    return ModelUsage(provider="mock", model="m", input_tokens=1, output_tokens=1, cost_usd=cost)


@pytest.fixture
async def engines(urls: RuntimeUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(urls.migrator, poolclass=NullPool)
    app = create_async_engine(urls.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


async def new_run(migrator: AsyncEngine) -> uuid.UUID:
    run = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id, worker_version, graph_version, requested_by, created_at)"
                " VALUES (:r, :r, :t, :w, 'dw', '1.0.0', '1', :r, now())"
            ),
            {"r": run, "t": TENANT_A, "w": WORKSPACE_A},
        )
    return run


async def cost_of(migrator: AsyncEngine, run: uuid.UUID) -> Decimal:
    async with migrator.connect() as conn:
        found = await conn.scalar(
            sa.text("SELECT model_cost_usd FROM platform.worker_runs WHERE id = :r"), {"r": run}
        )
    return Decimal(found)


async def test_two_calls_of_a_run_add_up_and_another_run_is_untouched(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    migrator, app = engines
    recorder = RunCostRecorder(async_sessionmaker(app, expire_on_commit=False))
    run, other = await new_run(migrator), await new_run(migrator)
    context = make_run_context(run_id=run)

    # At once, as two calls of one run can be: the statement adds, it does
    # not read and write, so neither is lost.
    await asyncio.gather(
        recorder.record(context, REQUEST, usage(0.012)),
        recorder.record(context, REQUEST, usage(0.003)),
    )
    await recorder.record(context, REQUEST, usage(0.0))

    assert await cost_of(migrator, run) == Decimal("0.015000")
    assert await cost_of(migrator, other) == Decimal("0")


async def test_another_tenant_naming_the_run_adds_nothing(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    migrator, app = engines
    recorder = RunCostRecorder(async_sessionmaker(app, expire_on_commit=False))
    run = await new_run(migrator)

    await recorder.record(
        make_run_context(tenant=TENANT_B, workspace=WORKSPACE_B, run_id=run),
        REQUEST,
        usage(5.0),
    )

    assert await cost_of(migrator, run) == Decimal("0")
