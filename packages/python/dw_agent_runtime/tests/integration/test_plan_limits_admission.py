"""Admission against the real plan catalogue (usage-and-limits ticket 01).

`DailyAllowance` over `PlanEntitlementService` over the adapter the two roots
wire (`CachingPlanCatalog(SqlPlanCatalog(...))`), reading
`platform.plan_limits` as `dw_app`. Each test owns a probe plan the migrator
writes, the way a migration would, and removes it after (its limits row goes
with it, ON DELETE CASCADE):

- R1.1: a number the migrator changes reaches admission once the 30 seconds
  since the previous read have passed, not before;
- R1.2: a plan with no row is refused, not unlimited;
- R1.2: a read that fails stops admission with its error, even with an
  expired row in the cache.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from runtime_harness import RuntimeUrls, make_run_context
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.allowance import DailyAllowance
from dw_kernel.errors import QuotaExceededError
from dw_kernel.ports import FixedClock
from dw_platform.adapters.persistence.plan_catalog import CachingPlanCatalog, SqlPlanCatalog
from dw_platform.application.entitlement import PlanEntitlementService

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@dataclass
class _Started:
    count: int

    async def started_since(self, tenant_id: uuid.UUID, since: datetime) -> int:
        return self.count

    async def spend_today(self, tenant_id: uuid.UUID, day: date) -> Decimal:
        return Decimal(0)


class _BrokenSession:
    """A session whose database is gone: every statement raises."""

    async def __aenter__(self) -> _BrokenSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def begin(self) -> _BrokenSession:
        return self

    async def execute(self, *args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT", {}, ConnectionError("connection lost"))


@dataclass
class _Sessions:
    real: async_sessionmaker[AsyncSession]
    broken: bool = False

    def __call__(self) -> Any:
        return _BrokenSession() if self.broken else self.real()


@pytest.fixture
async def migrator(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_sessions(urls: RuntimeUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def probe_plan(migrator: AsyncEngine) -> AsyncIterator[str]:
    plan_id = f"ul01_{uuid.uuid4().hex[:12]}"
    async with migrator.begin() as conn:
        await conn.execute(
            text("INSERT INTO platform.plans (plan_id, name) VALUES (:p, 'Probe')"), {"p": plan_id}
        )
    yield plan_id
    async with migrator.begin() as conn:
        await conn.execute(text("DELETE FROM platform.plans WHERE plan_id = :p"), {"p": plan_id})


async def _set_runs(migrator: AsyncEngine, plan_id: str, runs_per_day: int | None) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO platform.plan_limits (plan_id, runs_per_day, max_cost_usd_per_run,"
                " max_tokens_per_run, max_steps_per_run, max_model_calls_per_run,"
                " max_tool_calls_per_run) VALUES (:p, :r, 1, 1000, 10, 10, 10)"
                " ON CONFLICT (plan_id) DO UPDATE SET runs_per_day = EXCLUDED.runs_per_day"
            ),
            {"p": plan_id, "r": runs_per_day},
        )


def _admission(sessions: Any, clock: FixedClock, started: int) -> DailyAllowance:
    catalog = CachingPlanCatalog(SqlPlanCatalog(cast(Any, sessions)), clock)
    counts = _Started(started)
    return DailyAllowance(
        allowance=PlanEntitlementService(catalog), runs=counts, spend=counts, clock=clock
    )


async def test_a_changed_number_reaches_admission_after_thirty_seconds_not_before(
    migrator: AsyncEngine, app_sessions: async_sessionmaker[AsyncSession], probe_plan: str
) -> None:
    await _set_runs(migrator, probe_plan, 1)
    clock = FixedClock(T0)
    admission = _admission(app_sessions, clock, started=1)
    run = make_run_context().model_copy(update={"plan_id": probe_plan})

    with pytest.raises(QuotaExceededError):
        await admission.require(run)
    await _set_runs(migrator, probe_plan, 2)

    clock.advance_to(T0 + timedelta(seconds=29))
    with pytest.raises(QuotaExceededError) as raised:
        await admission.require(run)
    assert raised.value.details["limit"] == "1", "within 30 s the previous read answers"

    clock.advance_to(T0 + timedelta(seconds=30))
    await admission.require(run)


async def test_a_plan_with_no_limits_row_is_refused(
    app_sessions: async_sessionmaker[AsyncSession], probe_plan: str
) -> None:
    admission = _admission(app_sessions, FixedClock(T0), started=0)
    run = make_run_context().model_copy(update={"plan_id": probe_plan})
    with pytest.raises(QuotaExceededError) as raised:
        await admission.require(run)
    assert raised.value.details["limit"] == "0"


async def test_a_failed_read_stops_admission_even_with_an_expired_row_cached(
    migrator: AsyncEngine, app_sessions: async_sessionmaker[AsyncSession], probe_plan: str
) -> None:
    await _set_runs(migrator, probe_plan, None)
    clock = FixedClock(T0)
    sessions = _Sessions(app_sessions)
    admission = _admission(sessions, clock, started=0)
    run = make_run_context().model_copy(update={"plan_id": probe_plan})
    await admission.require(run)  # unlimited, read and cached

    clock.advance_to(T0 + timedelta(seconds=31))
    sessions.broken = True
    with pytest.raises(OperationalError):
        await admission.require(run)


async def test_the_seeded_plans_admit_under_their_numbers(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    clock = FixedClock(T0)
    for plan_id, limit in (("basic", 20), ("professional", 200), ("enterprise", 2000)):
        run = make_run_context().model_copy(update={"plan_id": plan_id})
        await _admission(app_sessions, clock, started=limit - 1).require(run)
        with pytest.raises(QuotaExceededError):
            await _admission(app_sessions, clock, started=limit).require(run)
