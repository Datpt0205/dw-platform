"""The plan catalogue's cache and the service over it (usage-and-limits ticket 01).

R1.1: the cache answers from memory for 30 seconds after a read, then asks
again; R1.2: a plan with no row is refused (0 runs, no spend), never
unlimited, and a catalogue that cannot be read raises, even with an expired
entry in hand. The database side is in the integration suites.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from dw_kernel.ports import FixedClock
from dw_platform.adapters.persistence.plan_catalog import (
    PLAN_LIMITS_TTL_SECONDS,
    CachingPlanCatalog,
)
from dw_platform.application.entitlement import PlanEntitlementService
from dw_platform.application.plan_catalog import PlanLimits
from dw_platform.testing.plan_catalog import InMemoryPlanCatalog

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _limits(plan_id: str, runs_per_day: int | None, spend: Decimal | None = None) -> PlanLimits:
    return PlanLimits(
        plan_id=plan_id,
        runs_per_day=runs_per_day,
        cost_usd_per_day=spend,
        cost_usd_per_month=None,
        tokens_per_month=None,
        max_cost_usd_per_run=Decimal("1"),
        max_tokens_per_run=1000,
        max_steps_per_run=10,
        max_model_calls_per_run=10,
        max_tool_calls_per_run=10,
    )


class _DatabaseDownError(Exception):
    pass


def test_the_ttl_is_thirty_seconds() -> None:
    assert PLAN_LIMITS_TTL_SECONDS == 30


async def test_a_plan_with_no_row_is_refused_runs_and_spend() -> None:
    service = PlanEntitlementService(InMemoryPlanCatalog({"basic": _limits("basic", 20)}))
    assert await service.runs_per_day("ghost") == 0
    assert await service.spend_usd_per_day("ghost") == Decimal(0)


async def test_the_rows_numbers_are_the_answer_and_null_is_no_limit() -> None:
    service = PlanEntitlementService(
        InMemoryPlanCatalog(
            {"basic": _limits("basic", 20, Decimal("5")), "internal": _limits("internal", None)}
        )
    )
    assert await service.runs_per_day("basic") == 20
    assert await service.spend_usd_per_day("basic") == Decimal("5")
    assert await service.runs_per_day("internal") is None
    assert await service.spend_usd_per_day("internal") is None


async def test_a_catalogue_that_cannot_be_read_raises_through_the_service() -> None:
    service = PlanEntitlementService(InMemoryPlanCatalog(failing=_DatabaseDownError("down")))
    with pytest.raises(_DatabaseDownError):
        await service.runs_per_day("basic")
    with pytest.raises(_DatabaseDownError):
        await service.spend_usd_per_day("basic")


async def test_within_the_ttl_the_cache_answers_and_after_it_the_catalogue_does() -> None:
    rows = {"basic": _limits("basic", 20)}
    inner = InMemoryPlanCatalog(rows)
    clock = FixedClock(_T0)
    cache = CachingPlanCatalog(inner, clock)

    first = await cache.limits("basic")
    assert first is not None and first.runs_per_day == 20
    rows["basic"] = _limits("basic", 25)

    clock.advance_to(_T0 + timedelta(seconds=29))
    cached = await cache.limits("basic")
    assert cached is not None and cached.runs_per_day == 20
    assert inner.reads == 1

    clock.advance_to(_T0 + timedelta(seconds=30))
    fresh = await cache.limits("basic")
    assert fresh is not None and fresh.runs_per_day == 25
    assert inner.reads == 2


async def test_a_missing_plan_is_cached_as_missing() -> None:
    inner = InMemoryPlanCatalog()
    clock = FixedClock(_T0)
    cache = CachingPlanCatalog(inner, clock)
    assert await cache.limits("ghost") is None
    clock.advance_to(_T0 + timedelta(seconds=10))
    assert await cache.limits("ghost") is None
    assert inner.reads == 1


async def test_a_failed_read_raises_and_never_answers_from_the_expired_entry() -> None:
    inner = InMemoryPlanCatalog({"basic": _limits("basic", 20)})
    clock = FixedClock(_T0)
    cache = CachingPlanCatalog(inner, clock)
    assert await cache.limits("basic") is not None

    clock.advance_to(_T0 + timedelta(seconds=31))
    inner.failing = _DatabaseDownError("down")
    with pytest.raises(_DatabaseDownError):
        await cache.limits("basic")
    # Still down a moment later: the failed read kept nothing alive.
    clock.advance_to(_T0 + timedelta(seconds=32))
    with pytest.raises(_DatabaseDownError):
        await cache.limits("basic")
    assert inner.reads == 3
