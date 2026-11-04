"""What a model call costs, asked of the price book through a port.

The runtime declares the question and the price book answers it
(usage-and-limits R2.1; ADR-0121 decision 2): `dw_usage.domain.pricing.PriceBook`
satisfies `PricingPort` and the composition roots inject it, so this package
never imports `dw_usage`. A route used to carry its own price, read by
`route_cost` alone; the book is now the one owner of "what does this cost", and
`ModelRoute` carries no price since model-connections/02 (H-4): its price
reference is its (`provider`, `model`), the key the book prices by.

`PriceNotFoundError` (`dw_kernel.errors`) is never turned into zero here: a
caller that catches it after a call keeps the answer, records the call as
`unpriced` and stops the run at its next call (R2.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from dw_kernel.errors import PriceNotFoundError

__all__ = [
    "CostSource",
    "PriceNotFoundError",
    "PriceQuote",
    "PricingPort",
    "chat_quantities",
]

# How a call's cost was arrived at, as the usage ledger stores it.
CostSource = Literal["computed", "provider_reported", "estimated", "unpriced"]


class PriceQuote(Protocol):
    """A call's price: the cost, the book version and the entries it used."""

    @property
    def cost_usd(self) -> Decimal: ...

    @property
    def price_book_version(self) -> str: ...

    @property
    def entry_ids(self) -> tuple[str, ...]: ...


class PricingPort(Protocol):
    """Prices one call. `tenant_id` is the run's, never a request's: a tenant's
    own entries (BYOM, W2) resolve like `TenantOverlay`, and W1 answers every
    tenant from the platform layer."""

    def price(
        self,
        tenant_id: UUID,
        quantities: Mapping[str, int],
        provider: str,
        model: str,
        at: datetime,
    ) -> PriceQuote: ...


def chat_quantities(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
) -> dict[str, int]:
    """A chat call's quantities by usage kind.

    `input_tokens` is everything the provider counted as input, cached or not,
    so `input_uncached` is what remains once the cache reads and writes are
    taken out; the tier of the call is read from the whole input (M15).
    """
    cached = cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens
    if cached > input_tokens:
        raise ValueError("cache tokens exceed the call's input tokens")
    return {
        "input_uncached": input_tokens - cached,
        "cache_read": cache_read_tokens,
        "cache_write_5m": cache_write_5m_tokens,
        "cache_write_1h": cache_write_1h_tokens,
        "output": output_tokens,
    }
