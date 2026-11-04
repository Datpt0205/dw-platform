"""A usage record's own rules, a company's days, and the one reader of price
(usage-and-limits R2.1, R3.5, R2.5)."""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest

from dw_agent_runtime.model.pricing import CostSource
from dw_usage.domain.events import COST_SOURCES, UsageEvent
from dw_usage.domain.windows import window_bounds

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_the_ledger_and_the_runtime_name_the_same_cost_sources() -> None:
    assert set(get_args(CostSource)) == COST_SOURCES


def _event(**overrides: Any) -> UsageEvent:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "occurred_at": datetime(2026, 11, 4, tzinfo=UTC),
        "tenant_id": uuid.uuid4(),
        "operation": "chat",
        "purpose": "run",
        "payer": "platform",
        "actor_kind": "user",
        "provider": "mock",
        "model": "m",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_source": "computed",
        "price_book_version": "1.0.0",
        "cost_usd": Decimal("0.01"),
    }
    return UsageEvent(**{**fields, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"cost_source": "unpriced"},  # a cost on an unpriced call
        {"cost_usd": None},  # no cost on a priced one
        {"cost_usd": Decimal("-1")},
        {"operation": "dance"},
        {"purpose": "fun"},
        {"data_route_class": "vn_maybe"},
        {"data_location": "moon"},
        {"cache_read_tokens": 11},
        {"reasoning_tokens": 6},
        {"occurred_at": datetime(2026, 11, 4)},
        {"price_book_version": " "},
    ],
)
def test_a_record_refuses_what_its_columns_refuse(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _event(**overrides)


def test_an_unpriced_record_has_no_cost() -> None:
    assert _event(cost_source="unpriced", cost_usd=None).cost_usd is None


@pytest.mark.parametrize(
    ("zone", "at", "day"),
    [
        # A company with no zone is in Asia/Ho_Chi_Minh (UTC+7).
        (None, datetime(2026, 11, 3, 17, 30, tzinfo=UTC), date(2026, 11, 4)),
        (None, datetime(2026, 11, 3, 16, 30, tzinfo=UTC), date(2026, 11, 3)),
        # Asia/Tokyo (UTC+9) cuts its day at 15:00Z.
        ("Asia/Tokyo", datetime(2026, 11, 3, 15, 0, tzinfo=UTC), date(2026, 11, 4)),
        ("Asia/Tokyo", datetime(2026, 11, 3, 14, 59, tzinfo=UTC), date(2026, 11, 3)),
    ],
)
def test_a_day_is_cut_in_the_company_s_zone(zone: str | None, at: datetime, day: date) -> None:
    window = window_bounds(zone, "day", at)
    assert window.day == day
    assert window.start <= at < window.end
    assert (window.end - window.start).total_seconds() == 86_400


def test_tokyo_s_day_starts_at_fifteen_utc() -> None:
    window = window_bounds("Asia/Tokyo", "day", datetime(2026, 11, 4, 3, tzinfo=UTC))
    assert window.start == datetime(2026, 11, 3, 15, tzinfo=UTC)
    assert window.timezone == "Asia/Tokyo"


def test_a_month_runs_to_the_first_of_the_next() -> None:
    window = window_bounds(None, "month", datetime(2026, 12, 15, tzinfo=UTC))
    assert window.day == date(2026, 12, 1)
    assert window.end == datetime(2026, 12, 31, 17, tzinfo=UTC)


def test_an_unknown_zone_is_refused_not_guessed() -> None:
    with pytest.raises(Exception, match="No time zone"):
        window_bounds("Mars/Olympus", "day", datetime(2026, 11, 4, tzinfo=UTC))


# ---- R2.1: one reader of a price -------------------------------------------

_PRICE_FIELDS = frozenset({"price_per_million_input", "price_per_million_output"})
_DECLARED_IN = "packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py"


def price_field_reads(roots: list[Path], base: Path = REPO_ROOT) -> list[str]:
    """Every attribute read of a route price field in `src/`, as `file:line`.

    The declaration on `ModelRoute` is an annotated assignment, not an attribute
    read, so it is never one of them: the book is the one owner of a price, and
    a second reader would be a second copy that drifts (failure-modes #2).
    """
    found: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in _PRICE_FIELDS:
                    found.append(f"{path.relative_to(base).as_posix()}:{node.lineno}")
                elif isinstance(node, ast.Constant) and node.value in _PRICE_FIELDS:
                    found.append(f"{path.relative_to(base).as_posix()}:{node.lineno}")
    return found


def _src_roots() -> list[Path]:
    return [*REPO_ROOT.glob("packages/python/*/src"), *REPO_ROOT.glob("apps/*/src")]


def test_no_code_reads_a_price_off_a_route() -> None:
    assert price_field_reads(_src_roots()) == []


def test_the_scan_names_the_file_of_a_planted_read(tmp_path: Path) -> None:
    root = tmp_path / "packages" / "python" / "x" / "src"
    root.mkdir(parents=True)
    (root / "planted.py").write_text(
        "def cost(route):\n    return route.price_per_million_input\n", encoding="utf-8"
    )
    assert price_field_reads([root], tmp_path) == ["packages/python/x/src/planted.py:2"]
    assert (REPO_ROOT / _DECLARED_IN).exists()
