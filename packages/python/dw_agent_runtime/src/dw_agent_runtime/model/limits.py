"""What a model call is asked to fit in before it is sent (usage-and-limits
R5.2, R5.10; ADR-0121 decision 5).

One estimate for every door that reaches a model through a lease (the
structured gateway, the agent loop's `LimitsMiddleware`, context compaction):
the input counted as characters over four, the measure LangChain's own
approximate counter uses, priced by the book the call settles by; and the
book's price of one output token, read as the difference the output makes to
the same call's price, so a tier picked by the input's size prices both alike.

A route the book cannot price estimates `None` money: the lease bounds it by
tokens, and its settlement records it `unpriced`, which stops the run at its
next call (R2.5). Never zero.

Also here, because every door of the run reads them:

- `clamp_run_limits`: a run's behavioural limits, the version's value where it
  declares one and the plan's ceiling otherwise, never above the ceiling
  (usage-and-limits R6.4);
- `permitted` and `permit_in_force`: the permit a lease gave the chat model
  call about to be made, set around exactly that call by the door that asked
  for it (`LimitsMiddleware`, context compaction), so a chat model built by
  `LimitedChatModelFactory` refuses any call made without one, however it was
  reached (R6.1, R6.2).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from typing import Final

from dw_agent_runtime.contracts import DeclaredLimits
from dw_agent_runtime.model.pricing import PriceKey, PricingPort, chat_quantities
from dw_agent_runtime.ports import CallEstimate, CallPermit, RunLimits
from dw_kernel.errors import PriceNotFoundError

__all__ = [
    "approximate_tokens",
    "clamp_run_limits",
    "estimate_call",
    "permit_in_force",
    "permitted",
]

# What one token is taken to be, in characters (LangChain's
# `count_tokens_approximately` default).
CHARS_PER_TOKEN: Final = 4
# The output a price is read over: large enough that the per-token difference
# is exact in the book's eight decimal places.
_PRICE_PROBE_TOKENS: Final = 1_000_000


def approximate_tokens(texts: Iterable[str]) -> int:
    """Tokens of everything a call sends, at four characters each, at least one."""
    return max(1, math.ceil(sum(len(text) for text in texts) / CHARS_PER_TOKEN))


def estimate_call(
    pricing: PricingPort,
    route: PriceKey,
    *,
    tenant_id: uuid.UUID,
    input_tokens: int,
    max_output_tokens: int | None,
    at: datetime,
) -> CallEstimate:
    try:
        quote = pricing.price(
            tenant_id,
            chat_quantities(input_tokens=input_tokens, output_tokens=0),
            route.provider,
            route.model,
            at,
        )
        input_cost = quote.cost_usd
        probed = pricing.price(
            tenant_id,
            chat_quantities(input_tokens=input_tokens, output_tokens=_PRICE_PROBE_TOKENS),
            route.provider,
            route.model,
            at,
        ).cost_usd
    except PriceNotFoundError as exc:
        return CallEstimate(
            provider=str(route.provider),
            model=route.model,
            input_tokens=input_tokens,
            input_cost_usd=None,
            output_usd_per_token=None,
            price_book_version=exc.price_book_version,
            max_output_tokens=max_output_tokens,
        )
    return CallEstimate(
        provider=str(route.provider),
        model=route.model,
        input_tokens=input_tokens,
        input_cost_usd=Decimal(input_cost),
        output_usd_per_token=(Decimal(probed) - Decimal(input_cost)) / _PRICE_PROBE_TOKENS,
        price_book_version=quote.price_book_version,
        max_output_tokens=max_output_tokens,
    )


def clamp_run_limits(declared: DeclaredLimits, ceiling: RunLimits) -> RunLimits:
    """The run's limits: each field the version declares, at most the plan's
    ceiling for it; each one it does not, the ceiling (R6.4)."""

    def lower(value: int | None, cap: int) -> int:
        return cap if value is None else min(value, cap)

    return RunLimits(
        max_steps=lower(declared.max_steps, ceiling.max_steps),
        max_model_calls=lower(declared.max_model_calls, ceiling.max_model_calls),
        max_tool_calls=lower(declared.max_tool_calls, ceiling.max_tool_calls),
        max_cost_usd=(
            ceiling.max_cost_usd
            if declared.max_cost_usd is None
            else min(declared.max_cost_usd, ceiling.max_cost_usd)
        ),
        max_tokens=lower(declared.max_tokens, ceiling.max_tokens),
    )


# One permit, for the one chat call it was asked for. A ContextVar for the
# reason the usage meter's tally is one: it belongs to this call, not to the
# shared, compiled-once model.
_PERMIT: ContextVar[CallPermit | None] = ContextVar("dw_chat_permit", default=None)


def permit_in_force() -> CallPermit | None:
    """The permit of the chat call being made now, or `None`."""
    return _PERMIT.get()


@contextmanager
def permitted(permit: CallPermit) -> Iterator[None]:
    """Make `permit` the one in force for the block: the call it was asked for
    is made inside it, and nothing after it is permitted by it."""
    token = _PERMIT.set(permit)
    try:
        yield
    finally:
        _PERMIT.reset(token)
