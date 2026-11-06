"""`UsageMeterPort` on the lease in force: an embedding or a rerank held to the
same lease, counters and ledger as a chat call (usage-and-limits R6.1, R6.2;
ADR-0121 decisions 1, 5, 7).

Knowledge declares the port and knows nothing of leases; this answers it with
`SqlRunLease.permit`, the run's `before_call` for a door that holds no run
context, and writes the call's usage record keyed by the permit, which is its
settlement into the lease (`SqlUsageLedger.settle`, R5.11).

A call is priced by the book for its `units` (`embedding_input` tokens, one
`rerank_search_unit`) at the moment it is asked about. An embedding's tokens
are the door's estimate, so its record is `estimated`; a rerank is one search
unit, `computed`. A route the book cannot price is asked about with no money
and recorded `unpriced`, which marks the lease so its next call is refused
(R2.5): an unknown cost is never zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from dw_agent_runtime.model.pricing import PricingPort
from dw_agent_runtime.ports import CallEstimate, CallPermit
from dw_kernel.errors import PriceNotFoundError
from dw_kernel.limits import LeaseInForce, MeteredCall, MeterPermit
from dw_kernel.ports import UtcClock
from dw_usage.adapters.limits_sql import SqlLimits, SqlRunLease
from dw_usage.application.ports import UsageLedgerPort
from dw_usage.domain.events import UsageEvent

__all__ = ["SqlUsageMeter"]

# Who pays a platform route in W1 (BYOM is W2), as the recorder writes it.
_PAYER: Final = "platform"


@dataclass(frozen=True)
class SqlUsageMeter:
    """Implements `dw_knowledge.ports.UsageMeterPort`."""

    limits: SqlLimits
    ledger: UsageLedgerPort
    pricing: PricingPort
    clock: UtcClock

    async def before_call(self, holder: LeaseInForce, call: MeteredCall) -> MeterPermit:
        cost, version, _entries = self._price(holder, call, self.clock.now())
        permit = await SqlRunLease(self.limits, holder.tenant_id, holder.lease_root).permit(
            run_id=holder.run_id,
            cost_ceiling_usd=holder.cost_ceiling_usd,
            estimate=CallEstimate(
                provider=call.provider,
                model=call.model,
                input_tokens=call.input_tokens,
                input_cost_usd=cost,
                # Neither door has an output to bound.
                output_usd_per_token=Decimal(0),
                price_book_version=version,
                max_output_tokens=0,
            ),
        )
        return MeterPermit(
            lease_id=permit.lease_id, call_id=permit.call_id, occurred_at=permit.occurred_at
        )

    async def settle(self, holder: LeaseInForce, permit: MeterPermit, call: MeteredCall) -> None:
        # Priced at the moment it was permitted, as the lease was asked for it.
        cost, version, entries = self._price(holder, call, permit.occurred_at)
        if cost is None:
            source = "unpriced"
        else:
            source = "estimated" if call.operation == "embeddings" else "computed"
        await self.ledger.settle(
            UsageEvent(
                id=permit.call_id,
                occurred_at=permit.occurred_at,
                tenant_id=holder.tenant_id,
                workspace_id=holder.workspace_id,
                run_id=holder.run_id,
                root_run_id=holder.lease_root,
                lease_id=permit.lease_id,
                operation=call.operation,
                purpose=holder.purpose,
                payer=_PAYER,
                actor_kind=holder.actor_kind,
                user_id=holder.actor_id,
                provider=call.provider,
                model=call.model,
                input_tokens=call.input_tokens,
                output_tokens=0,
                units={kind: count for kind, count in call.units.items() if count},
                cost_source=source,
                cost_usd=cost,
                price_book_version=version,
                price_entry_ids=entries,
                data_location=call.data_location,
                processor=call.processor,
            )
        )

    async def abandon(self, holder: LeaseInForce, permit: MeterPermit) -> None:
        await SqlRunLease(self.limits, holder.tenant_id, holder.lease_root).abandon(
            CallPermit(
                lease_id=permit.lease_id,
                call_id=permit.call_id,
                occurred_at=permit.occurred_at,
                max_output_tokens=0,
            )
        )

    def _price(
        self, holder: LeaseInForce, call: MeteredCall, at: datetime
    ) -> tuple[Decimal | None, str, tuple[str, ...]]:
        try:
            quote = self.pricing.price(holder.tenant_id, call.units, call.provider, call.model, at)
        except PriceNotFoundError as exc:
            return None, exc.price_book_version, ()
        return Decimal(quote.cost_usd), quote.price_book_version, tuple(quote.entry_ids)
