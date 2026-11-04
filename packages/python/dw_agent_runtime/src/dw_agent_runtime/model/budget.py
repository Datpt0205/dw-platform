"""A ceiling on what one run may spend, enforced rather than declared.

Every model profile has carried `budgets` since the profiles were written, and
until now nothing read it. A limit that is configured and unenforced is worse
than no limit: it reads like a control in review, and the first runaway loop
discovers it was decoration.

The ceiling is a backstop, not a quality lever (ADR-19). A healthy run stops
because its coverage gate is satisfied, far below this. What this catches is the
case the gate cannot: a loop, a retry storm, or a lane whose answer does not
exist being asked for again and again.

Cost is computed from the price book (`PricingPort`) when the provider does not
report one, which is the normal case behind a gateway - the gateway returns
token counts and no money. A call the book cannot price is not free: the run is
marked as having reached its cost ceiling, so its next call is refused
(usage-and-limits R2.5).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from dw_agent_runtime.model.pricing import PriceQuote, PricingPort, chat_quantities
from dw_agent_runtime.model.profiles import ModelBudgets, ModelRoute
from dw_kernel.errors import DomainError

logger = logging.getLogger("dw_agent_runtime.budget")


class BudgetExceededError(DomainError):
    """This run has spent its ceiling and must stop."""


@dataclass
class RunSpend:
    """What one run has spent so far."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    # A call of this run could not be priced (R2.5). Its cost is unknown, not
    # zero, so the run is treated as having reached its cost ceiling.
    unpriced: bool = False


def route_cost(
    pricing: PricingPort,
    route: ModelRoute,
    *,
    tenant_id: uuid.UUID,
    input_tokens: int,
    output_tokens: int,
    at: datetime,
) -> PriceQuote:
    """What one call on `route` cost, from the price book.

    `PriceNotFoundError` propagates: a caller decides what an unpriced call
    means for it, and none of them may read it as zero (R2.5).
    """
    return pricing.price(
        tenant_id,
        chat_quantities(input_tokens=input_tokens, output_tokens=output_tokens),
        route.provider,
        route.model,
        at,
    )


@dataclass
class RunBudgetLedger:
    """Per-run spend, checked before a call and updated after it.

    In-process and per-gateway: it bounds one run inside one worker, which is
    where a loop actually burns money. A cross-process quota is a different
    control with a different home (the plan's per-tenant quota), and conflating
    them would make neither enforceable.
    """

    spend: dict[uuid.UUID, RunSpend] = field(default_factory=dict)

    def check(self, run_id: uuid.UUID, budgets: ModelBudgets, *, task: str) -> None:
        """Refuse the next call when this run has already spent its ceiling."""
        current = self.spend.get(run_id)
        if current is None:
            return
        if current.unpriced:
            raise BudgetExceededError(
                "run reached its cost ceiling: a call could not be priced",
                details={
                    "run_id": str(run_id),
                    "task": task,
                    "calls": str(current.calls),
                },
            )
        if current.input_tokens >= budgets.max_input_tokens_per_run:
            raise BudgetExceededError(
                "run reached its input-token ceiling",
                details={
                    "run_id": str(run_id),
                    "task": task,
                    "input_tokens": str(current.input_tokens),
                    "ceiling": str(budgets.max_input_tokens_per_run),
                    "calls": str(current.calls),
                },
            )
        if current.cost_usd >= budgets.max_cost_usd_per_run:
            raise BudgetExceededError(
                "run reached its cost ceiling",
                details={
                    "run_id": str(run_id),
                    "task": task,
                    "cost_usd": f"{current.cost_usd:.4f}",
                    "ceiling": str(budgets.max_cost_usd_per_run),
                    "calls": str(current.calls),
                },
            )

    def record(
        self, run_id: uuid.UUID, *, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> RunSpend:
        current = self.spend.setdefault(run_id, RunSpend())
        current.input_tokens += input_tokens
        current.output_tokens += output_tokens
        current.cost_usd += cost_usd
        current.calls += 1
        return current

    def mark_unpriced(self, run_id: uuid.UUID) -> RunSpend:
        """A call of this run has happened and the book could not price it:
        the next `check` refuses (R2.5; ticket 03's lease keeps the rule)."""
        current = self.spend.setdefault(run_id, RunSpend())
        current.unpriced = True
        return current

    def forget(self, run_id: uuid.UUID) -> RunSpend | None:
        """Drop a finished run, so a long-lived worker does not accumulate them."""
        return self.spend.pop(run_id, None)
