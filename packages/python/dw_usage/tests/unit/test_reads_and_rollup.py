"""The summary is refused before any read without `platform.usage.read`, and
the roll-up recomputes each company's today and yesterday in its own zone
(usage-and-limits R3.5, R3.12; UL18)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from dw_kernel.errors import DomainError, PermissionDeniedError
from dw_kernel.ports import FixedClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_usage.application.calendar import UsageCalendar
from dw_usage.application.ports import RunUsageRow, SummaryFilter, SummaryRow
from dw_usage.application.reads import USAGE_READ, UsageReads
from dw_usage.application.rollup import LOOKBACK, UsageRollup

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
NOW = datetime(2026, 11, 3, 17, 30, tzinfo=UTC)  # 4/11 00:30 in Hồ Chí Minh


@dataclass
class FakeTimezones:
    zones: dict[uuid.UUID, str | None] = field(default_factory=dict)

    async def timezone_of(self, tenant_id: uuid.UUID) -> str | None:
        return self.zones.get(tenant_id)


@dataclass
class FakeReads:
    asked: list[SummaryFilter] = field(default_factory=list)

    async def run_usage(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[RunUsageRow]:
        return []

    async def summary(self, tenant_id: uuid.UUID, query: SummaryFilter) -> list[SummaryRow]:
        self.asked.append(query)
        return [
            SummaryRow(
                key=None,
                artifact_kind=None,
                label=None,
                calls=2,
                input_tokens=10,
                output_tokens=5,
                cost_usd=Decimal("0.5"),
                unpriced_calls=1,
                estimated_calls=0,
            )
        ]


def _reads(store: FakeReads, zone: str | None = None) -> UsageReads:
    return UsageReads(
        store=store,
        calendar=UsageCalendar(FakeTimezones({TENANT: zone})),
        authz=ScopeAuthorizationService(),
        clock=FixedClock(NOW),
    )


def _context(*scopes: str) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        plan_id="professional",
        scopes=frozenset(scopes),
    )


async def test_without_the_key_nothing_is_read() -> None:
    store = FakeReads()
    with pytest.raises(PermissionDeniedError):
        await _reads(store).summary(_context("runs.read"), group_by="workspace")
    assert store.asked == []


async def test_the_holder_reads_the_company_s_month_in_its_zone() -> None:
    store = FakeReads()
    summary = await _reads(store).summary(_context(USAGE_READ), group_by="purpose")
    assert (summary.first_day, summary.last_day) == (date(2026, 11, 1), date(2026, 11, 30))
    assert summary.timezone == "Asia/Ho_Chi_Minh"
    assert [q.group_by for q in store.asked] == ["purpose"]


async def test_a_range_too_long_or_backwards_is_refused_before_a_read() -> None:
    store = FakeReads()
    reads = _reads(store)
    with pytest.raises(DomainError, match="too long"):
        await reads.summary(
            _context(USAGE_READ),
            group_by="workspace",
            first_day=date(2025, 1, 1),
            last_day=date(2026, 2, 5),
        )
    with pytest.raises(DomainError, match="ends before"):
        await reads.summary(
            _context(USAGE_READ),
            group_by="workspace",
            first_day=date(2026, 2, 5),
            last_day=date(2026, 2, 4),
        )
    assert store.asked == []


@dataclass
class FakeRollupStore:
    tenants: list[uuid.UUID]
    failing: set[uuid.UUID] = field(default_factory=set)
    since: list[datetime] = field(default_factory=list)
    days: list[tuple[uuid.UUID, date, datetime, datetime]] = field(default_factory=list)

    async def tenants_with_usage_since(self, since: datetime) -> list[uuid.UUID]:
        self.since.append(since)
        return self.tenants

    async def recompute_day(
        self, tenant_id: uuid.UUID, day: date, start: datetime, end: datetime, at: datetime
    ) -> int:
        if tenant_id in self.failing:
            raise RuntimeError("boom")
        self.days.append((tenant_id, day, start, end))
        return 1


async def test_the_roll_up_recomputes_today_and_yesterday_in_each_zone() -> None:
    hcm, tokyo, broken = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store = FakeRollupStore(tenants=[broken, hcm, tokyo], failing={broken})
    rollup = UsageRollup(
        store=store,
        calendar=UsageCalendar(FakeTimezones({hcm: None, tokyo: "Asia/Tokyo"})),
        clock=FixedClock(NOW),
    )

    assert await rollup.run_once() == 4

    assert store.since == [NOW - LOOKBACK]
    assert [(t, d) for t, d, _, _ in store.days] == [
        (hcm, date(2026, 11, 3)),
        (hcm, date(2026, 11, 4)),
        (tokyo, date(2026, 11, 3)),
        (tokyo, date(2026, 11, 4)),
    ]
    # Tokyo's 4/11 starts at 15:00Z on 3/11; Hồ Chí Minh's at 17:00Z.
    starts = {(t, d): s for t, d, s, _ in store.days}
    assert starts[(tokyo, date(2026, 11, 4))] == datetime(2026, 11, 3, 15, tzinfo=UTC)
    assert starts[(hcm, date(2026, 11, 4))] == datetime(2026, 11, 3, 17, tzinfo=UTC)
