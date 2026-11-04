"""A price book for tests that do not load the platform's (`PricingPort`).

`dw_usage.domain.pricing.PriceBook` is the real one, and the composition roots
inject it. A runtime test cannot import `dw_usage` without inverting the
layering, so it prices with this: a flat price per million tokens by model, and
a set of models it refuses, which raise `PriceNotFoundError` the way the book
does for a call nothing covers (usage-and-limits R2.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from dw_kernel.errors import PriceNotFoundError

__all__ = ["FlatPricing", "FlatQuote"]

_MILLION = Decimal(1_000_000)
_INPUT = ("input_uncached", "cache_read", "cache_write_5m", "cache_write_1h")


@dataclass(frozen=True)
class FlatQuote:
    cost_usd: Decimal
    price_book_version: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlatPricing:
    """`prices[model] = (input, output)` USD per million; a model not listed is
    free, a model in `refused` is not priced at all. `calls` keeps every
    `(tenant_id, provider, model, at)` asked, for a test that checks the tenant
    and the moment reached the book."""

    prices: Mapping[str, tuple[Decimal, Decimal]] = field(default_factory=dict)
    refused: frozenset[str] = frozenset()
    version: str = "test-book"
    calls: list[tuple[UUID, str, str, datetime]] = field(default_factory=list)

    def price(
        self,
        tenant_id: UUID,
        quantities: Mapping[str, int],
        provider: str,
        model: str,
        at: datetime,
    ) -> FlatQuote:
        self.calls.append((tenant_id, provider, model, at))
        if model in self.refused:
            raise PriceNotFoundError(
                "no price for this model", price_book_version=self.version, details={"model": model}
            )
        per_input, per_output = self.prices.get(model, (Decimal(0), Decimal(0)))
        inbound = sum(quantities.get(kind, 0) for kind in _INPUT)
        cost = (per_input * inbound + per_output * quantities.get("output", 0)) / _MILLION
        return FlatQuote(cost, self.version, (f"{provider}/{model}",))
