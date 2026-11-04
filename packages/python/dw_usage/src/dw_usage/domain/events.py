"""A usage record: one model call, who it is attributed to, and what it cost
(usage-and-limits R3.1; the `platform.usage_events` row).

Each fixed set below is the CHECK of its column (migration `2354ad4d2e3c`); the
record refuses a value outside it before the database does, and
`test_usage_domain.py` holds the sets to the runtime's `CostSource`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

__all__ = [
    "ACTOR_KINDS",
    "ARTIFACT_KINDS",
    "COST_SOURCES",
    "DATA_LOCATIONS",
    "DATA_ROUTE_CLASSES",
    "OPERATIONS",
    "PAYERS",
    "PURPOSES",
    "UsageEvent",
]

OPERATIONS: Final = frozenset(
    {
        "chat",
        "embeddings",
        "rerank",
        "extraction",
        "transcription",
        "sandbox_exec",
        "server_tool",
        "unsettled_estimate",
    }
)
PURPOSES: Final = frozenset(
    {
        "run",
        "test_run",
        "builder_assist",
        "eval_offline",
        "eval_online",
        "ingestion",
        "retrieval",
        "compaction",
        "memory",
    }
)
PAYERS: Final = frozenset({"platform", "tenant"})
ACTOR_KINDS: Final = frozenset({"user", "service", "system"})
ARTIFACT_KINDS: Final = frozenset({"agent", "workflow"})
COST_SOURCES: Final = frozenset({"computed", "provider_reported", "estimated", "unpriced"})
DATA_ROUTE_CLASSES: Final = frozenset({"vn_only", "cross_border_minimised", "cross_border_full"})
DATA_LOCATIONS: Final = frozenset({"vn", "foreign"})


def _one_of(name: str, value: str | None, allowed: frozenset[str], *, nullable: bool) -> None:
    if value is None and nullable:
        return
    if value not in allowed:
        raise ValueError(f"{name} {value!r} is not one of {sorted(allowed)}")


@dataclass(frozen=True)
class UsageEvent:
    """One row of the ledger. `id` and `occurred_at` are minted once, before the
    first attempt to settle, and travel together on every retry (R3.2, M2).

    The route columns are NULL until compliance-pdpl/03 writes them from
    `ResidencyGate`: NULL means the call did not pass the gate, never
    `vn_only`.
    """

    id: UUID
    occurred_at: datetime
    tenant_id: UUID
    operation: str
    purpose: str
    payer: str
    actor_kind: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_source: str
    price_book_version: str
    cost_usd: Decimal | None
    price_entry_ids: tuple[str, ...] = ()
    units: Mapping[str, int] = field(default_factory=dict)
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    workspace_id: UUID | None = None
    run_id: UUID | None = None
    root_run_id: UUID | None = None
    lease_id: UUID | None = None
    node_id: str | None = None
    artifact_kind: str | None = None
    artifact_id: UUID | None = None
    artifact_version: str | None = None
    user_id: UUID | None = None
    trigger_kind: str | None = None
    data_route_class: str | None = None
    data_location: str | None = None
    processor: str | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at is an aware moment")
        _one_of("operation", self.operation, OPERATIONS, nullable=False)
        _one_of("purpose", self.purpose, PURPOSES, nullable=False)
        _one_of("payer", self.payer, PAYERS, nullable=False)
        _one_of("actor_kind", self.actor_kind, ACTOR_KINDS, nullable=False)
        _one_of("cost_source", self.cost_source, COST_SOURCES, nullable=False)
        _one_of("artifact_kind", self.artifact_kind, ARTIFACT_KINDS, nullable=True)
        _one_of("data_route_class", self.data_route_class, DATA_ROUTE_CLASSES, nullable=True)
        _one_of("data_location", self.data_location, DATA_LOCATIONS, nullable=True)
        # The cost is unknown exactly when the call was not priced (R2.5).
        if (self.cost_usd is None) != (self.cost_source == "unpriced"):
            raise ValueError("cost_usd is NULL exactly when cost_source is 'unpriced'")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd is never negative")
        tokens = (
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
            self.reasoning_tokens,
        )
        if any(count < 0 for count in tokens):
            raise ValueError("a token count is never negative")
        if self.cache_read_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("cache tokens are part of the input tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning tokens are part of the output tokens")
        if not self.price_book_version.strip():
            raise ValueError("a usage record names the price book it was priced by")
