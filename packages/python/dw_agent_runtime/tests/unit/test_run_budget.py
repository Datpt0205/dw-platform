"""The per-run ceiling, which was configured and unenforced until it was not."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from dw_agent_runtime.model.budget import (
    BudgetExceededError,
    RunBudgetLedger,
    route_cost,
)
from dw_agent_runtime.model.profiles import ModelBudgets, ModelRoute
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_kernel.errors import PriceNotFoundError

pytestmark = pytest.mark.unit

_PRICED = ModelRoute(provider="openai_responses", model="gpt-5.6-luna")
_UNPRICED = ModelRoute(provider="mock", model="mock-structured")
_BOOK = FlatPricing(
    prices={"gpt-5.6-luna": (Decimal("0.20"), Decimal("1.20"))},
    refused=frozenset({"mock-structured"}),
)
_TIGHT = ModelBudgets(max_input_tokens_per_run=10_000, max_cost_usd_per_run=0.01)
_AT = datetime(2026, 11, 4, tzinfo=UTC)
_TENANT = uuid.uuid4()


def _cost(route: ModelRoute, input_tokens: int, output_tokens: int) -> Decimal:
    return route_cost(
        _BOOK,
        route,
        tenant_id=_TENANT,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        at=_AT,
    ).cost_usd


class TestRouteCost:
    def test_a_priced_route_costs_what_the_book_says(self) -> None:
        # 1M input at $0.20 and 1M output at $1.20.
        assert _cost(_PRICED, 1_000_000, 1_000_000) == Decimal("1.40")

    def test_a_realistic_extraction_call_is_fractions_of_a_cent(self) -> None:
        assert float(_cost(_PRICED, 6242, 236)) == pytest.approx(0.00153, abs=1e-5)

    def test_a_call_the_book_cannot_price_is_an_error_not_zero(self) -> None:
        """R2.5: an unknown cost never reads as nothing spent."""
        with pytest.raises(PriceNotFoundError):
            _cost(_UNPRICED, 1_000_000, 1_000_000)

    def test_the_book_is_asked_for_the_run_s_tenant_at_the_call_s_moment(self) -> None:
        book = FlatPricing()
        route_cost(book, _PRICED, tenant_id=_TENANT, input_tokens=1, output_tokens=1, at=_AT)
        assert book.calls == [(_TENANT, "openai_responses", "gpt-5.6-luna", _AT)]


class TestLedger:
    def test_a_fresh_run_may_always_make_its_first_call(self) -> None:
        RunBudgetLedger().check(uuid.uuid4(), _TIGHT, task="first")

    def test_spending_accumulates_across_calls(self) -> None:
        ledger, run = RunBudgetLedger(), uuid.uuid4()
        ledger.record(run, input_tokens=100, output_tokens=10, cost_usd=0.001)
        spend = ledger.record(run, input_tokens=100, output_tokens=10, cost_usd=0.001)
        assert (spend.input_tokens, spend.calls) == (200, 2)

    def test_the_token_ceiling_stops_the_next_call(self) -> None:
        ledger, run = RunBudgetLedger(), uuid.uuid4()
        ledger.record(run, input_tokens=10_000, output_tokens=0, cost_usd=0.0)
        with pytest.raises(BudgetExceededError, match="input-token ceiling"):
            ledger.check(run, _TIGHT, task="next")

    def test_the_cost_ceiling_stops_the_next_call(self) -> None:
        ledger, run = RunBudgetLedger(), uuid.uuid4()
        ledger.record(run, input_tokens=1, output_tokens=1, cost_usd=0.01)
        with pytest.raises(BudgetExceededError, match="cost ceiling"):
            ledger.check(run, _TIGHT, task="next")

    def test_the_error_says_which_run_and_how_many_calls(self) -> None:
        # A ceiling that fires without saying what hit it turns a loop into a
        # mystery, which is the thing the ceiling exists to make visible.
        ledger, run = RunBudgetLedger(), uuid.uuid4()
        for _ in range(7):
            ledger.record(run, input_tokens=2_000, output_tokens=0, cost_usd=0.0)
        with pytest.raises(BudgetExceededError) as caught:
            ledger.check(run, _TIGHT, task="section_extract:financials:r2")
        details = caught.value.details
        assert details["run_id"] == str(run)
        assert details["calls"] == "7"
        assert details["task"] == "section_extract:financials:r2"

    def test_one_run_reaching_its_ceiling_does_not_stop_another(self) -> None:
        ledger, spent, fresh = RunBudgetLedger(), uuid.uuid4(), uuid.uuid4()
        ledger.record(spent, input_tokens=10_000, output_tokens=0, cost_usd=0.0)
        ledger.check(fresh, _TIGHT, task="unrelated")

    def test_a_finished_run_is_forgotten_so_a_worker_does_not_accumulate_them(self) -> None:
        ledger, run = RunBudgetLedger(), uuid.uuid4()
        ledger.record(run, input_tokens=5, output_tokens=1, cost_usd=0.0)
        assert ledger.forget(run) is not None
        assert ledger.spend == {}

    def test_an_unpriced_call_stops_the_run_at_its_next_call(self) -> None:
        """R2.5: the answer already given stands; the next call is refused."""
        ledger, run = RunBudgetLedger(), uuid.uuid4()
        ledger.mark_unpriced(run)
        with pytest.raises(BudgetExceededError, match="could not be priced"):
            ledger.check(run, ModelBudgets(), task="next")
