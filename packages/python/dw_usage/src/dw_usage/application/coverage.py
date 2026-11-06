"""The startup check: a deployed service refuses to start while a paid platform
route has no price in force (usage-and-limits R2.3).

A paid route is every route of `configs/models/*.yaml` whose provider is not
`mock` (W1 has no BYOM). A `mock` route is not paid; it is in the book at zero,
so pricing has no branch for it. Each paid route must be priced, at the moment the
service starts, for every usage kind its route type's adapter reports; with
that held, `PriceNotFoundError` in a deployed profile is left only for a kind
no W1 adapter reports.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Final

from dw_agent_runtime.model.profiles import ModelProfile, ModelRoute, Provider
from dw_kernel.errors import ConfigError
from dw_usage.domain.pricing import PriceBook

__all__ = [
    "CHAT_KINDS",
    "EMBEDDING_KINDS",
    "RERANK_KINDS",
    "require_paid_routes_priced",
    "require_rerank_priced",
    "unpriced_paid_routes",
]

# What each route type's adapter reports: chat (every generating route),
# embedding, and rerank. No profile carries a rerank route in W1: the API
# configures its reranker beside the profiles, checked by
# `require_rerank_priced`.
CHAT_KINDS: Final = ("input_uncached", "cache_read", "cache_write_5m", "cache_write_1h", "output")
EMBEDDING_KINDS: Final = ("embedding_input",)
RERANK_KINDS: Final = ("rerank_search_unit",)


def _routes(profile: ModelProfile) -> Iterable[tuple[str, ModelRoute, tuple[str, ...]]]:
    for name in ("structured_extraction", "reasoning", "chat", "deep_reasoning", "fallback"):
        route = getattr(profile, name)
        if route is not None:
            yield name, route, CHAT_KINDS
    if profile.embedding is not None:
        yield "embedding", profile.embedding, EMBEDDING_KINDS


def unpriced_paid_routes(
    profiles: Iterable[ModelProfile], book: PriceBook, at: datetime
) -> list[str]:
    """One line per paid route and usage kind with no entry in force at `at`."""
    missing: list[str] = []
    for profile in profiles:
        for name, route, kinds in _routes(profile):
            if route.provider == Provider.MOCK:
                continue
            missing += [
                f"{profile.profile_id}.{name} ({route.provider} {route.model}): {kind}"
                for kind in kinds
                if not book.covers(route.provider, route.model, kind, at)
            ]
    return missing


def require_paid_routes_priced(
    profiles: Iterable[ModelProfile], book: PriceBook, at: datetime, *, is_deployed: bool
) -> None:
    """Refuse to start a deployed profile with an unpriced paid route. Local and
    test start regardless: a missing price there stops the run that meets it."""
    if not is_deployed:
        return
    missing = unpriced_paid_routes(profiles, book, at)
    if missing:
        raise ConfigError(
            f"price book {book.version} does not price every paid route: {'; '.join(missing)}",
            details={"routes": missing},
        )


def require_rerank_priced(
    provider: str, model: str, book: PriceBook, at: datetime, *, is_deployed: bool
) -> None:
    """R2.3 for the reranker a deployment configures beside its profiles. It is
    metered like every model door (usage-and-limits R6.1), so an unpriced one
    records `unpriced`, which stops the run at its next call (R2.5): a deployed
    API with one does not start, rather than stop every run that reranks."""
    if not is_deployed:
        return
    missing = [kind for kind in RERANK_KINDS if not book.covers(provider, model, kind, at)]
    if missing:
        routes = [f"rerank ({provider} {model}): {kind}" for kind in missing]
        raise ConfigError(
            f"price book {book.version} does not price the reranker: {'; '.join(routes)}",
            details={"routes": routes},
        )
