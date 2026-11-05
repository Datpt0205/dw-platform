"""What the usage routes answer, and how a read becomes it.

Money is a decimal string (`"0.01234500"`), never a float: the client formats
it, and a float would round a cost the ledger stores to eight places.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from dw_usage.application.limits import LimitLine, PolicyWrite
from dw_usage.application.ports import RunUsageRow, SummaryRow
from dw_usage.application.reads import RunUsage, UsageSummary

__all__ = [
    "LimitLineView",
    "LimitPolicyView",
    "RunUsageRowView",
    "RunUsageView",
    "UsageGroupView",
    "UsageSummaryView",
    "limit_line_view",
    "limit_policy_view",
    "run_usage_view",
    "usage_summary_view",
]


def _money(value: Decimal) -> str:
    return f"{value:.8f}"


class RunUsageRowView(BaseModel):
    operation: str
    provider: str
    model: str
    cost_source: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str


class RunUsageView(BaseModel):
    run_id: UUID
    calls: int
    cost_usd: str
    rows: list[RunUsageRowView]


class UsageGroupView(BaseModel):
    # `None`: the company-level group (no workspace), or calls of no agent or
    # workflow; the screen names it.
    key: str | None
    artifact_kind: str | None
    label: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str
    unpriced_calls: int
    estimated_calls: int


class UsageSummaryView(BaseModel):
    first_day: date
    last_day: date
    timezone: str
    group_by: Literal["workspace", "artifact", "purpose"]
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str
    unpriced_calls: int
    estimated_calls: int
    groups: list[UsageGroupView]


def _row(row: RunUsageRow) -> RunUsageRowView:
    return RunUsageRowView(
        operation=row.operation,
        provider=row.provider,
        model=row.model,
        cost_source=row.cost_source,
        calls=row.calls,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=_money(row.cost_usd),
    )


def run_usage_view(usage: RunUsage) -> RunUsageView:
    return RunUsageView(
        run_id=usage.run_id,
        calls=usage.calls,
        cost_usd=_money(usage.cost_usd),
        rows=[_row(row) for row in usage.rows],
    )


def _group(row: SummaryRow) -> UsageGroupView:
    return UsageGroupView(
        key=row.key,
        artifact_kind=row.artifact_kind,
        label=row.label,
        calls=row.calls,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=_money(row.cost_usd),
        unpriced_calls=row.unpriced_calls,
        estimated_calls=row.estimated_calls,
    )


def usage_summary_view(summary: UsageSummary) -> UsageSummaryView:
    groups = summary.groups
    return UsageSummaryView(
        first_day=summary.first_day,
        last_day=summary.last_day,
        timezone=summary.timezone,
        group_by=summary.group_by,
        calls=sum(g.calls for g in groups),
        input_tokens=sum(g.input_tokens for g in groups),
        output_tokens=sum(g.output_tokens for g in groups),
        cost_usd=_money(sum((g.cost_usd for g in groups), Decimal(0))),
        unpriced_calls=sum(g.unpriced_calls for g in groups),
        estimated_calls=sum(g.estimated_calls for g in groups),
        groups=[_group(row) for row in groups],
    )


class LimitLineView(BaseModel):
    """One limit of the company (usage-and-limits R4; `GET /api/v1/limits`):
    the policy at its scope (`limit_value` `None` for the plan's cap alone),
    the plan's cap at the company, the effective limit along the chain, and the
    current period's counter, money and tokens as decimal strings."""

    scope_type: Literal["tenant", "workspace", "agent", "workflow"]
    scope_id: UUID
    metric: Literal["cost_usd", "tokens", "runs"]
    window_kind: Literal["day", "month"]
    kind: Literal["hard"] = "hard"
    limit_value: str | None
    # The policy's ETag, `If-Match` of its next write; `None` for the plan's
    # cap alone, which a `PUT` without `If-Match` turns into a policy.
    version: int | None
    plan_limit: str | None
    effective_limit: str
    limit_source: Literal["plan", "policy"]
    used: str
    reserved: str
    resets_at: datetime


class LimitPolicyView(BaseModel):
    scope_type: Literal["tenant", "workspace", "agent", "workflow"]
    scope_id: UUID
    metric: Literal["cost_usd", "tokens", "runs"]
    window_kind: Literal["day", "month"]
    kind: Literal["hard"] = "hard"
    limit_value: str
    version: int


def _amount(metric: str, value: Decimal) -> str:
    return _money(value) if metric == "cost_usd" else str(int(value))


def limit_line_view(line: LimitLine) -> LimitLineView:
    return LimitLineView(
        scope_type=line.scope_type,
        scope_id=line.scope_id,
        metric=line.metric,
        window_kind=line.window_kind,
        limit_value=None if line.limit_value is None else _amount(line.metric, line.limit_value),
        version=line.version,
        plan_limit=None if line.plan_limit is None else _amount(line.metric, line.plan_limit),
        effective_limit=_amount(line.metric, line.effective_limit),
        limit_source=line.limit_source,
        used=_amount(line.metric, line.used),
        reserved=_amount(line.metric, line.reserved),
        resets_at=line.resets_at,
    )


def limit_policy_view(written: PolicyWrite) -> LimitPolicyView:
    ref = written.ref
    return LimitPolicyView(
        scope_type=ref.scope_type,
        scope_id=ref.scope_id,
        metric=ref.metric,
        window_kind=ref.window_kind,
        limit_value=_amount(ref.metric, written.limit_value),
        version=written.version,
    )
