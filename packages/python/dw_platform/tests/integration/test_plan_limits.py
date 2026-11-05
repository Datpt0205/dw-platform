"""`platform.plan_limits` as migration 764b0e239f95 leaves it (usage-and-limits
ticket 01: R1.1, R1.4).

The seed keeps the numbers the runtime enforced, the `quotas` column is gone,
the per-run maxima refuse what the CHECKs refuse, and the adapter reads a row
as `dw_app`. Who may write the table is `test_privileges.py` (R1.3); admission
over it is `dw_agent_runtime`'s `test_plan_limits_admission.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

_INSERT = (
    "INSERT INTO platform.plan_limits (plan_id, max_cost_usd_per_run, max_tokens_per_run,"
    " max_steps_per_run, max_model_calls_per_run, max_tool_calls_per_run)"
    " VALUES (:p, 1, :tokens, :steps, 10, 10)"
)


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_sessions(db_urls: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_the_seed_keeps_the_numbers_the_runtime_enforced(migrator: AsyncEngine) -> None:
    async with migrator.connect() as conn:
        rows = {
            row.plan_id: row
            for row in await conn.execute(sa.text("SELECT * FROM platform.plan_limits"))
        }
        quotas = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform'"
                " AND table_name = 'plans' AND column_name = 'quotas'"
            )
        )
        features = {
            row.plan_id: row.features
            for row in await conn.execute(sa.text("SELECT plan_id, features FROM platform.plans"))
        }
    assert {plan: row.runs_per_day for plan, row in rows.items()} == {
        "basic": 20,
        "professional": 200,
        "enterprise": 2000,
    }
    for row in rows.values():
        assert row.cost_usd_per_day is None and row.cost_usd_per_month is None
        assert row.tokens_per_month is None
        assert row.max_cost_usd_per_run == Decimal("2.0")
        # Tokens in and out of one run, 200000 since usage-and-limits/03 (ticket 01 M2).
        assert row.max_tokens_per_run == 200000
        assert row.max_steps_per_run == 50
        assert row.max_model_calls_per_run == 50
        assert row.max_tool_calls_per_run == 200
    assert quotas == 0, "`platform.plans.quotas` is dropped; the columns own the numbers"
    assert features["enterprise"] == ["knowledge_search", "audit_export"]


@pytest.mark.parametrize(
    ("steps", "tokens", "refused_by"),
    [
        (501, 1000, "ck_plan_limits_max_steps_per_run"),
        (0, 1000, "ck_plan_limits_max_steps_per_run"),
        (1, None, "max_tokens_per_run"),
        (500, 1000, None),
        (1, 1000, None),
    ],
)
async def test_the_per_run_maxima_are_bounded_and_never_null(
    migrator: AsyncEngine, steps: int, tokens: int | None, refused_by: str | None
) -> None:
    """R1.4: as a migration writes the table; each case rolled back."""
    plan_id = f"ul01_{uuid.uuid4().hex[:12]}"
    async with migrator.connect() as conn:
        await conn.execute(
            sa.text("INSERT INTO platform.plans (plan_id, name) VALUES (:p, 'Probe')"),
            {"p": plan_id},
        )
        statement = conn.execute(sa.text(_INSERT), {"p": plan_id, "tokens": tokens, "steps": steps})
        if refused_by is None:
            await statement
        else:
            with pytest.raises(IntegrityError, match=refused_by):
                await statement
        await conn.rollback()


async def test_removing_a_plan_removes_its_limits(migrator: AsyncEngine) -> None:
    plan_id = f"ul01_{uuid.uuid4().hex[:12]}"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO platform.plans (plan_id, name) VALUES (:p, 'Probe')"),
            {"p": plan_id},
        )
        await conn.execute(sa.text(_INSERT), {"p": plan_id, "tokens": 1000, "steps": 10})
        await conn.execute(sa.text("DELETE FROM platform.plans WHERE plan_id = :p"), {"p": plan_id})
        left = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.plan_limits WHERE plan_id = :p"), {"p": plan_id}
        )
    assert left == 0
