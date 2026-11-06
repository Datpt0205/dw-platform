"""A deployed service refuses to start while a paid route is unpriced (R2.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dw_agent_runtime.model.profiles import ModelProfile
from dw_agent_runtime.testing.models import route as test_route
from dw_kernel.errors import ConfigError
from dw_usage.adapters.price_book_file import (
    enforce_price_coverage,
    load_price_book,
    platform_profiles,
)
from dw_usage.application.coverage import require_paid_routes_priced, require_rerank_priced
from dw_usage.domain.pricing import price_book_from_document

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 4, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[5]

_BOOK = price_book_from_document(
    {
        "schema_version": "1.0",
        "price_book_id": "test",
        "version": "9.9.9",
        "currency": "USD",
        "models": [
            {
                "provider": "openai_compatible",
                "model": "paid-1",
                "effective_from": "2026-01-01T00:00:00+00:00",
                "source": "test",
                # No `output`: the paid route cannot be priced in full.
                "prices": {
                    "input_uncached": "1",
                    "cache_read": "1",
                    "cache_write_5m": "1",
                    "cache_write_1h": "1",
                },
            },
            {
                "provider": "mock",
                "model": "mock-1",
                "effective_from": "2026-01-01T00:00:00+00:00",
                "source": "test",
                "prices": {"input_uncached": "0", "output": "0"},
            },
            {
                "provider": "cohere_compatible",
                "model": "priced-reranker",
                "effective_from": "2026-01-01T00:00:00+00:00",
                "source": "test",
                "prices": {"rerank_search_unit": "2"},
            },
        ],
    }
)


def _profile(provider: str, model: str) -> ModelProfile:
    route = test_route(provider=provider, model=model)
    return ModelProfile(
        schema_version="2.0",
        profile_id="p",
        routing_policy_version="1.0.0",
        structured_extraction=route,
        reasoning=route,
    )


def test_a_paid_route_without_an_output_price_stops_a_deployed_start() -> None:
    with pytest.raises(ConfigError) as raised:
        require_paid_routes_priced(
            [_profile("openai_compatible", "paid-1")], _BOOK, NOW, is_deployed=True
        )
    assert "p.structured_extraction (openai_compatible paid-1): output" in raised.value.message


def test_a_mock_route_starts_with_its_zero_price() -> None:
    require_paid_routes_priced([_profile("mock", "mock-1")], _BOOK, NOW, is_deployed=True)


def test_local_and_test_start_regardless() -> None:
    require_paid_routes_priced(
        [_profile("openai_compatible", "paid-1")], _BOOK, NOW, is_deployed=False
    )


def test_the_shipped_book_prices_every_shipped_paid_route() -> None:
    enforce_price_coverage(
        load_price_book(), REPO_ROOT / "configs" / "models", at=NOW, is_deployed=True
    )
    assert any(
        route.provider != "mock"
        for profile in platform_profiles(REPO_ROOT / "configs" / "models")
        for route in (profile.structured_extraction, profile.reasoning)
    ), "no paid route is shipped, so the check above checked nothing"


def test_a_deployed_api_with_an_unpriced_reranker_does_not_start() -> None:
    """usage-and-limits R6.1 with R2.3: a metered reranker the book cannot price
    would record `unpriced` and stop every run at its next call (R2.5)."""
    with pytest.raises(ConfigError) as raised:
        require_rerank_priced(
            "cohere_compatible", "bge-reranker-v2-m3", _BOOK, NOW, is_deployed=True
        )
    assert (
        "rerank (cohere_compatible bge-reranker-v2-m3): rerank_search_unit" in raised.value.message
    )


def test_a_priced_reranker_starts_and_local_starts_regardless() -> None:
    require_rerank_priced("cohere_compatible", "priced-reranker", _BOOK, NOW, is_deployed=True)
    require_rerank_priced("cohere_compatible", "bge-reranker-v2-m3", _BOOK, NOW, is_deployed=False)
