"""The plan model catalogue's cache (model-connections ticket 02: R2.2, R2.6).

It answers from memory for the plan catalogue's 30 seconds, then asks again;
a read that fails raises, even with an expired entry in hand, and is never
"every profile". The table itself is `test_plan_model_profiles.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dw_kernel.ports import FixedClock
from dw_platform.adapters.persistence.plan_model_profiles import CachingPlanModelProfiles

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class _Catalogue:
    def __init__(self, plans: dict[str, frozenset[str]]) -> None:
        self.plans = plans
        self.asked: list[str] = []
        self.down = False

    async def allowed(self, plan_id: str) -> frozenset[str]:
        self.asked.append(plan_id)
        if self.down:
            raise ConnectionError("the database is down")
        return self.plans.get(plan_id, frozenset())


async def test_a_plan_is_read_once_per_thirty_seconds() -> None:
    inner, clock = _Catalogue({"basic": frozenset({"balanced"})}), FixedClock(_T0)
    cache = CachingPlanModelProfiles(inner, clock)
    assert await cache.allowed("basic") == frozenset({"balanced"})
    clock.advance_to(_T0 + timedelta(seconds=29))
    inner.plans["basic"] = frozenset({"balanced", "luna"})
    assert await cache.allowed("basic") == frozenset({"balanced"})
    clock.advance_to(_T0 + timedelta(seconds=30))
    assert await cache.allowed("basic") == frozenset({"balanced", "luna"})
    assert inner.asked == ["basic", "basic"]


async def test_a_plan_with_no_rows_lists_nothing() -> None:
    assert await CachingPlanModelProfiles(_Catalogue({}), FixedClock(_T0)).allowed("x") == set()


async def test_a_failed_read_raises_and_the_stale_entry_is_not_used() -> None:
    inner, clock = _Catalogue({"basic": frozenset({"balanced"})}), FixedClock(_T0)
    cache = CachingPlanModelProfiles(inner, clock)
    await cache.allowed("basic")
    clock.advance_to(_T0 + timedelta(seconds=31))
    inner.down = True
    with pytest.raises(ConnectionError):
        await cache.allowed("basic")
    with pytest.raises(ConnectionError):
        await cache.allowed("basic")
