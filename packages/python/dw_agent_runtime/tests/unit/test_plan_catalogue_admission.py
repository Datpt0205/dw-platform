"""Admission over the plan catalogue (usage-and-limits ticket 01, R1.2).

`DailyAllowance` is the one check both doors run (the runner's start and the
one-call gateway). Over the platform's `PlanEntitlementService`: a plan with
no `platform.plan_limits` row is refused, never unlimited; a catalogue that
cannot be read stops the admission with its own error, before anything is
counted. The real adapter is in `tests/integration/test_plan_limits_admission.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from dw_agent_runtime.allowance import DailyAllowance
from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import QuotaExceededError
from dw_kernel.ports import FixedClock
from dw_platform.application.entitlement import PlanEntitlementService
from dw_platform.application.plan_catalog import PlanLimits
from dw_platform.testing.plan_catalog import InMemoryPlanCatalog

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 2, 15, 30, tzinfo=UTC)


@dataclass
class _Counts:
    started: int = 0
    asked: list[str] = field(default_factory=list)

    async def started_since(self, tenant_id: uuid.UUID, since: datetime) -> int:
        self.asked.append("runs")
        return self.started

    async def spend_today(self, tenant_id: uuid.UUID, day: date) -> Decimal:
        self.asked.append("spend")
        return Decimal(0)


class _DatabaseDownError(Exception):
    pass


def _limits(plan_id: str, runs_per_day: int | None) -> PlanLimits:
    return PlanLimits(
        plan_id=plan_id,
        runs_per_day=runs_per_day,
        cost_usd_per_day=None,
        cost_usd_per_month=None,
        tokens_per_month=None,
        max_cost_usd_per_run=Decimal("1"),
        max_tokens_per_run=1000,
        max_steps_per_run=10,
        max_model_calls_per_run=10,
        max_tool_calls_per_run=10,
    )


def _context(plan_id: str) -> RunContext:
    return RunContext(
        run_id=uuid.UUID(int=1),
        tenant_id=uuid.UUID(int=2),
        workspace_id=uuid.UUID(int=3),
        actor_id=uuid.UUID(int=4),
        worker_id="demo_approval",
        worker_version="1.0.0",
        channel="web",
        plan_id=plan_id,
        roles=frozenset({"member"}),
        scopes=frozenset(),
        trace_id="trace-1",
    )


def _allowance(catalog: InMemoryPlanCatalog, counts: _Counts) -> DailyAllowance:
    return DailyAllowance(
        allowance=PlanEntitlementService(catalog),
        runs=counts,
        spend=counts,
        clock=FixedClock(NOW),
    )


async def test_a_plan_with_a_row_is_admitted_under_its_number() -> None:
    counts = _Counts(started=19)
    await _allowance(InMemoryPlanCatalog({"basic": _limits("basic", 20)}), counts).require(
        _context("basic")
    )


async def test_a_plan_with_no_row_is_refused_not_unlimited() -> None:
    counts = _Counts(started=0)
    catalog = InMemoryPlanCatalog({"basic": _limits("basic", None)})
    with pytest.raises(QuotaExceededError) as raised:
        await _allowance(catalog, counts).require(_context("ghost"))
    assert raised.value.details["quota"] == "runs_per_day"
    assert raised.value.details["limit"] == "0"


async def test_a_catalogue_that_cannot_be_read_stops_the_admission_with_its_error() -> None:
    counts = _Counts(started=0)
    catalog = InMemoryPlanCatalog(
        {"basic": _limits("basic", None)}, failing=_DatabaseDownError("plan_limits unreachable")
    )
    with pytest.raises(_DatabaseDownError):
        await _allowance(catalog, counts).require(_context("basic"))
    assert counts.asked == []
