"""One usage record's row, written in the caller's transaction (usage-and-
limits R3.1, R3.2): the one INSERT of `platform.usage_events`, which the ledger,
a lease's settlement and the reaper's estimate all use."""

from __future__ import annotations

import json
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from dw_usage.domain.events import UsageEvent

__all__ = ["insert_usage_event"]

_COLUMNS: Final = (
    "id",
    "occurred_at",
    "tenant_id",
    "workspace_id",
    "run_id",
    "root_run_id",
    "lease_id",
    "node_id",
    "artifact_kind",
    "artifact_id",
    "artifact_version",
    "user_id",
    "actor_kind",
    "trigger_kind",
    "operation",
    "purpose",
    "payer",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "units",
    "cost_usd",
    "cost_source",
    "price_book_version",
    "price_entry_ids",
    "data_route_class",
    "data_location",
    "processor",
)


def _value(column: str) -> str:
    if column == "units":
        return "CAST(:units AS jsonb)"
    return f":{column}"


_SETTLE = sa.text(
    f"INSERT INTO platform.usage_events ({', '.join(_COLUMNS)})"  # nosec B608 - fixed names
    f" VALUES ({', '.join(_value(c) for c in _COLUMNS)})"
    " ON CONFLICT (id, occurred_at) DO NOTHING RETURNING id"
).bindparams(sa.bindparam("price_entry_ids", type_=postgresql.ARRAY(sa.Text())))


def _params(event: UsageEvent) -> dict[str, Any]:
    params: dict[str, Any] = {column: getattr(event, column) for column in _COLUMNS}
    params["units"] = json.dumps(dict(event.units), sort_keys=True)
    params["price_entry_ids"] = list(event.price_entry_ids)
    return params


async def insert_usage_event(session: AsyncSession, event: UsageEvent) -> bool:
    """One record in the caller's transaction, under its tenant; `False` when
    its `(id, occurred_at)` is already there (R3.2)."""
    written = await session.scalar(_SETTLE, _params(event))
    return written is not None
