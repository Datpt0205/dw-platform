"""`LedgerUsageRecorder`: every model call the runtime records becomes one
usage record (usage-and-limits R3.1; ADR-0121 decision 1).

It answers the runtime's `UsageRecorderPort`, and the composition roots of the
API and the worker put it in the `CompositeUsageRecorder` the gateway and the
LangChain meter record into, so every call through either writes a record from
the first day.

A call a lease permitted carries its permit (usage-and-limits R5.2): the record
takes the permit's key and lease, and writing it is the call's settlement into
the lease (`after_call` of the spec, R5.11). A settlement whose key the reaper
already wrote as an estimate is not counted twice: it is logged and counted in
`dw_limit_late_settlements_total`.

The call was priced where its route was known (the gateway, the meter); this
class reads that price off the usage and never prices a second time. A call that
reached it unpriced is stored `unpriced` with no cost, logged as an error and
counted in `dw_usage_unpriced_total` (R2.5): the gap shows, it is never zero.
A call is the `purpose` of the lease that permitted it (`run` when none did),
`payer = 'platform'`, `root_run_id` its tree's
root, with NULL artifact and node columns, and NULL lease when no permit came
with it; the route columns are the usage's, which the sending door sets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.model.pricing import chat_quantities
from dw_agent_runtime.ports import ModelRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_observability.metrics import DW_LIMIT_LATE_SETTLEMENTS_TOTAL, DW_USAGE_UNPRICED_TOTAL
from dw_observability.telemetry import TelemetryPort
from dw_usage.application.ports import UsageLedgerPort
from dw_usage.domain.events import UsageEvent

__all__ = ["LedgerUsageRecorder"]

_LOG = logging.getLogger("dw_usage.recorder")


@dataclass(frozen=True)
class LedgerUsageRecorder:
    """Implements `dw_agent_runtime.model.gateway.UsageRecorderPort`."""

    ledger: UsageLedgerPort
    ids: IdGenerator
    clock: UtcClock
    telemetry: TelemetryPort
    # The loaded book's version: what an unpriced record names when the usage
    # carries none (a recorder fed a usage nobody priced).
    price_book_version: str

    async def record(
        self, run_context: RunContext, request: ModelRequest, usage: ModelUsage
    ) -> None:
        del request  # W1 attributes a call to its run; the task is telemetry's.
        source = usage.cost_source
        if source is None:
            _LOG.error(
                "usage of run %s reached the ledger unpriced (%s %s)",
                run_context.run_id,
                usage.provider,
                usage.model,
            )
            source = "unpriced"
        if source == "unpriced":
            _LOG.error(
                "model call recorded unpriced for run %s (%s %s)",
                run_context.run_id,
                usage.provider,
                usage.model,
            )
            self.telemetry.add_metric(
                DW_USAGE_UNPRICED_TOTAL, 1, {"provider": usage.provider, "model": usage.model}
            )
        service = run_context.run_as_principal_id is not None
        quantities = chat_quantities(
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
        )
        permit = usage.permit
        event = UsageEvent(
            id=self.ids.new_uuid() if permit is None else permit.call_id,
            occurred_at=self.clock.now() if permit is None else permit.occurred_at,
            tenant_id=run_context.tenant_id,
            workspace_id=run_context.workspace_id,
            run_id=run_context.run_id,
            root_run_id=run_context.root_run_id or run_context.run_id,
            lease_id=None if permit is None else permit.lease_id,
            operation="chat",
            # The lease's: a builder's assistance is not a run (R6.2).
            purpose="run" if permit is None else permit.purpose,
            payer="platform",
            actor_kind="service" if service else "user",
            user_id=None if service else run_context.actor_id,
            provider=usage.provider,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            units={kind: count for kind, count in quantities.items() if count},
            cost_source=source,
            cost_usd=None if source == "unpriced" else Decimal(str(usage.cost_usd)),
            price_book_version=usage.price_book_version or self.price_book_version,
            price_entry_ids=usage.price_entry_ids if source != "unpriced" else (),
            # Set by the door that sent the call, after the gate admitted it
            # (compliance-pdpl R2.1); NULL when no door set them.
            data_route_class=usage.data_route_class,
            data_location=usage.data_location,
            processor=usage.processor,
        )
        if not await self.ledger.settle(event):
            # Same key, already settled: a retry that minted nothing new, a
            # second writer of the same key with other content (M2), or the
            # reaper's estimate of a call whose process was presumed dead
            # (R5.11). Kept as the first one wrote it.
            _LOG.warning("usage record %s was already settled", event.id)
            if permit is not None:
                self.telemetry.add_metric(DW_LIMIT_LATE_SETTLEMENTS_TOTAL, 1, {})
