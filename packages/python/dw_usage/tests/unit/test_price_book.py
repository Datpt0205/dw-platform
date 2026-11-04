"""The dated price book (usage-and-limits R2.1, R2.2, R2.4, R2.5; UL12)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.model.budget import route_cost
from dw_agent_runtime.model.pricing import chat_quantities
from dw_agent_runtime.model.profiles import ModelRoute
from dw_kernel.errors import ConfigError, PriceNotFoundError
from dw_usage.adapters.price_book_file import load_price_book
from dw_usage.domain.pricing import PriceBook, price_book_from_document

pytestmark = pytest.mark.unit

TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()


def _book(models: list[dict[str, Any]], version: str = "1.0.0") -> PriceBook:
    return price_book_from_document(
        {
            "schema_version": "1.0",
            "price_book_id": "test",
            "version": version,
            "currency": "USD",
            "models": models,
        }
    )


def _model(
    prices: Mapping[str, str],
    *,
    since: str = "2026-07-01T00:00:00+00:00",
    model: str = "m-1",
    tiers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "provider": "openai_compatible",
        "model": model,
        "effective_from": since,
        "source": "test",
        "prices": dict(prices),
    }
    if tiers is not None:
        entry["tiers"] = tiers
    return entry


_BASE = {"input_uncached": "1.00", "cache_read": "0.10", "output": "4.00"}
_BOOK = _book(
    [
        _model(_BASE),
        # From 2027-01-01 the model costs twice as much (R2.1, R2.4).
        _model(
            {"input_uncached": "2.00", "cache_read": "0.20", "output": "8.00"},
            since="2027-01-01T00:00:00+00:00",
        ),
        _model(
            {"input_uncached": "3.00", "output": "6.00"},
            model="tiered",
            tiers=[
                {
                    "min_input_tokens": 200_000,
                    "prices": {"input_uncached": "6.00", "output": "9.00"},
                }
            ],
        ),
    ]
)
_JULY = datetime(2026, 8, 1, tzinfo=UTC)


def _price(
    quantities: Mapping[str, int],
    *,
    model: str = "m-1",
    at: datetime = _JULY,
    tenant: uuid.UUID = TENANT_A,
    book: PriceBook = _BOOK,
) -> Decimal:
    return book.price(tenant, quantities, "openai_compatible", model, at).cost_usd


def test_a_price_changed_from_a_date_gives_two_costs() -> None:
    call = {"input_uncached": 1_000_000, "output": 1_000_000}
    before = _price(call, at=datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    after = _price(call, at=datetime(2027, 1, 1, tzinfo=UTC))
    assert (before, after) == (Decimal("5.00"), Decimal("10.00"))


def test_cache_reads_are_taken_out_of_the_uncached_input() -> None:
    quantities = chat_quantities(input_tokens=1000, output_tokens=0, cache_read_tokens=800)
    assert quantities["input_uncached"] == 200
    assert quantities["cache_read"] == 800
    # 200 at $1/M and 800 at $0.10/M.
    assert _price(quantities) == Decimal("0.00028")


def test_the_tier_of_the_whole_input_prices_the_whole_call() -> None:
    small = _price({"input_uncached": 199_999, "output": 1000}, model="tiered")
    large = _price({"input_uncached": 200_000, "output": 1000}, model="tiered")
    assert small == Decimal(199_999 * 3 + 1000 * 6) / Decimal(1_000_000)
    assert large == Decimal(200_000 * 6 + 1000 * 9) / Decimal(1_000_000)


def test_cache_reads_count_toward_the_tier() -> None:
    quantities = chat_quantities(input_tokens=250_000, output_tokens=0, cache_read_tokens=60_000)
    book = _book(
        [
            _model(
                {"input_uncached": "3.00", "cache_read": "0.30"},
                tiers=[
                    {
                        "min_input_tokens": 200_000,
                        "prices": {"input_uncached": "6.00", "cache_read": "0.60"},
                    }
                ],
            )
        ]
    )
    entries = book.price(TENANT_A, quantities, "openai_compatible", "m-1", _JULY).entry_ids
    assert all("/200000@" in entry for entry in entries)


def test_two_tenants_get_the_platform_layer_in_w1() -> None:
    call = {"input_uncached": 10_000, "output": 2_000}
    assert _price(call, tenant=TENANT_A) == _price(call, tenant=TENANT_B)


def test_route_cost_is_the_book_s_price_for_the_same_call() -> None:
    route = ModelRoute(provider="openai_compatible", model="m-1")
    quote = route_cost(
        _BOOK, route, tenant_id=TENANT_A, input_tokens=6242, output_tokens=236, at=_JULY
    )
    assert quote.cost_usd == _price({"input_uncached": 6242, "output": 236})
    assert quote.price_book_version == "1.0.0"
    assert quote.entry_ids == (
        "openai_compatible/m-1/input_uncached/0@2026-07-01T00:00:00+00:00",
        "openai_compatible/m-1/output/0@2026-07-01T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("quantities", "at"),
    [
        # A call before the earliest entry (R2.5).
        ({"input_uncached": 10, "output": 10}, datetime(2026, 6, 1, tzinfo=UTC)),
        # A kind with no entry at all (R2.5).
        ({"image_input": 10}, _JULY),
    ],
)
def test_a_call_nothing_covers_is_refused_not_free(
    quantities: Mapping[str, int], at: datetime
) -> None:
    with pytest.raises(PriceNotFoundError) as raised:
        _price(quantities, at=at)
    assert raised.value.price_book_version == "1.0.0"


def test_a_kind_the_call_did_not_use_needs_no_entry() -> None:
    assert _price({"input_uncached": 0, "image_input": 0, "output": 1_000_000}) == Decimal("4")


def test_a_new_book_does_not_reprice_what_an_old_one_quoted() -> None:
    """R2.4 (UL12): the quote carries its own book version and cost; a second
    book with another price answers a new quote, and the first stays as it was."""
    old = _BOOK.price(TENANT_A, {"output": 1_000_000}, "openai_compatible", "m-1", _JULY)
    newer = _book([_model({"input_uncached": "9.00", "output": "9.00"})], version="1.1.0")
    new = newer.price(TENANT_A, {"output": 1_000_000}, "openai_compatible", "m-1", _JULY)
    assert (old.price_book_version, old.cost_usd) == ("1.0.0", Decimal("4.00"))
    assert (new.price_book_version, new.cost_usd) == ("1.1.0", Decimal("9.00"))


@pytest.mark.parametrize(
    ("models", "says"),
    [
        ([_model(_BASE), _model({"output": "1.00"})], "same moment"),
        ([_model({"tokens_of_joy": "1.00"})], "unknown usage kind"),
        ([_model({"output": "-0.01"})], "negative"),
        ([_model(_BASE, since="2026-07-01T00:00:00")], "time zone"),
    ],
)
def test_the_loader_refuses_a_bad_book(models: list[dict[str, Any]], says: str) -> None:
    """R2.2: overlapping entries of one key, an unknown kind, a negative price
    (and a moment without a zone, M14) refuse the whole book."""
    with pytest.raises(ConfigError, match=says):
        _book(models)


def test_a_tier_is_part_of_the_overlap_key() -> None:
    _book([_model(_BASE, tiers=[{"min_input_tokens": 200_000, "prices": dict(_BASE)}])])


def test_the_shipped_book_loads_and_names_its_version(tmp_path: Path) -> None:
    book = load_price_book()
    assert book.version == "1.0.0"
    copied = tmp_path / "price_book@2.0.0.yaml"
    copied.write_text(
        (
            Path(__file__).resolve().parents[5] / "configs" / "pricing" / "price_book@1.0.0.yaml"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"says version 1.0.0"):
        load_price_book(copied)


def test_the_mock_routes_are_in_the_book_at_zero() -> None:
    book = load_price_book()
    for model in ("extraction-mock-1", "reasoning-mock-1", "fallback-mock-1"):
        quote = book.price(TENANT_A, {"input_uncached": 10, "output": 10}, "mock", model, _JULY)
        assert quote.cost_usd == 0
