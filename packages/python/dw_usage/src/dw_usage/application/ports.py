"""The ports the usage use cases take, and the rows they read.

Declared here, satisfied by `dw_usage.adapters.sql`, named only by the
composition roots (`CLAUDE.md`, "Layer rules").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from dw_usage.domain.events import UsageEvent

__all__ = [
    "GroupBy",
    "RunUsageRow",
    "SummaryFilter",
    "SummaryRow",
    "TenantTimezonePort",
    "UsageLedgerPort",
    "UsageReadPort",
    "UsageRollupStorePort",
]

GroupBy = Literal["workspace", "artifact", "purpose"]


class UsageLedgerPort(Protocol):
    async def settle(self, event: UsageEvent) -> bool:
        """Write one record; `False` when a record of the same `(id,
        occurred_at)` is already there (R3.2), which is not an error."""
        ...


class TenantTimezonePort(Protocol):
    async def timezone_of(self, tenant_id: UUID) -> str | None:
        """`platform.tenants.timezone` of the company, `None` when unset."""
        ...


@dataclass(frozen=True)
class RunUsageRow:
    """The calls of one run of one (operation, provider, model, cost source)."""

    operation: str
    provider: str
    model: str
    cost_source: str
    calls: int
    input_tokens: int
    output_tokens: int
    # NULL-skipping sum: an `unpriced` call adds nothing here, and is counted in
    # `calls` under its own `cost_source` so the gap is visible (M13).
    cost_usd: Decimal


@dataclass(frozen=True)
class SummaryFilter:
    first_day: date
    last_day: date
    group_by: GroupBy
    workspace_id: UUID | None = None
    artifact_kind: str | None = None
    artifact_id: UUID | None = None


@dataclass(frozen=True)
class SummaryRow:
    """One group of the roll-up. `key` is `None` for the company-level group
    (no workspace) or for calls of no agent or workflow."""

    key: str | None
    artifact_kind: str | None
    label: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    unpriced_calls: int
    estimated_calls: int


class UsageReadPort(Protocol):
    async def run_usage(self, tenant_id: UUID, run_id: UUID) -> list[RunUsageRow]: ...

    async def summary(self, tenant_id: UUID, query: SummaryFilter) -> list[SummaryRow]: ...


class UsageRollupStorePort(Protocol):
    async def tenants_with_usage_since(self, since: datetime) -> list[UUID]:
        """Every company with a record at or after `since`, read across
        companies under the drain policy (the lane's one cross-tenant read)."""
        ...

    async def recompute_day(
        self, tenant_id: UUID, day: date, start: datetime, end: datetime, at: datetime
    ) -> int:
        """Replace the company's roll-up of `day` with the sum of its records in
        `[start, end)`, under its own tenant; returns the groups written."""
        ...
