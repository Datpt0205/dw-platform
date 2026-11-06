"""The scope chain's arithmetic (usage-and-limits R4.1, R4.14, R5.8; gate
4/11/2026 (p)): the four pairs and their plan columns, the merge of the plan's
caps with the company's policies, the lock order, what a lease holds."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from dw_usage.domain.limits import (
    LIMIT_PAIRS,
    PLAN_COLUMNS,
    PlanCaps,
    PolicyLimit,
    chain_limits,
    held,
    remaining,
)

pytestmark = pytest.mark.unit

TENANT = uuid.UUID(int=1)
WORKSPACE = uuid.UUID(int=2)


def _plan(**periods: str | None) -> PlanCaps:
    return PlanCaps(
        plan_id="p",
        periods={
            pair: None if periods.get(column) is None else Decimal(str(periods[column]))
            for pair, column in PLAN_COLUMNS.items()
        },
        max_cost_usd_per_run=Decimal(2),
        max_tokens_per_run=200_000,
        max_steps_per_run=50,
        max_model_calls_per_run=50,
        max_tool_calls_per_run=200,
    )


def test_w1_has_four_pairs_each_with_its_plan_column() -> None:
    assert set(LIMIT_PAIRS) == {
        ("cost_usd", "day"),
        ("cost_usd", "month"),
        ("tokens", "month"),
        ("runs", "day"),
    }
    assert set(PLAN_COLUMNS.values()) == {
        "cost_usd_per_day",
        "cost_usd_per_month",
        "tokens_per_month",
        "runs_per_day",
    }


def test_the_company_counter_takes_the_smaller_of_the_plan_and_the_policy() -> None:
    lower = PolicyLimit("tenant", TENANT, "cost_usd", "month", Decimal(50))
    higher = PolicyLimit("tenant", TENANT, "runs", "day", Decimal(500))
    (cost, runs) = sorted(
        chain_limits(TENANT, _plan(cost_usd_per_month="100", runs_per_day="200"), [lower, higher]),
        key=lambda limit: limit.metric,
    )
    assert (cost.limit, cost.source) == (Decimal(50), "policy")
    assert (runs.limit, runs.source) == (Decimal(200), "plan")


def test_a_null_plan_column_is_no_limit_and_no_counter() -> None:
    assert chain_limits(TENANT, _plan(), []) == []


def test_the_chain_is_in_lock_order_company_first() -> None:
    limits = chain_limits(
        TENANT,
        _plan(cost_usd_per_month="100"),
        [PolicyLimit("workspace", WORKSPACE, "cost_usd", "month", Decimal(10))],
    )
    assert [limit.scope_type for limit in limits] == ["tenant", "workspace"]


def test_a_platform_paid_lease_reaches_no_company_counter() -> None:
    assert chain_limits(TENANT, None, []) == []


def test_what_a_lease_holds_never_goes_below_zero() -> None:
    assert held(Decimal(2), Decimal("0.5")) == Decimal("1.5")
    assert held(Decimal(1), Decimal(3)) == Decimal(0)
    assert remaining(Decimal(10), Decimal(4), Decimal(3)) == Decimal(3)
