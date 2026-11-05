"""`ModelProfile` v2 and the profiles `configs/models` ships (model-connections
ticket 02: R2.3, R3.1, R3.2; MR5; ADR-0118 decision 2, ADR-0123 decision 5).

The loader is what CI runs on every shipped file (the API and the worker load
the directory at startup, and so does `test_shipped_profiles_load`), so a file
that drops `data_location` or keeps a price fails here, by name.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from dw_agent_runtime.model.profiles import (
    ModelCapabilities,
    ModelProfile,
    ModelProfileRegistry,
    ModelRoute,
    load_profile,
)
from dw_agent_runtime.registry import ConfigError

pytestmark = pytest.mark.unit

MODELS = Path(__file__).resolve().parents[5] / "configs" / "models"
SHIPPED = ("balanced", "deepseek", "gateway", "low_cost", "luna", "openai")
# ADR-0118 decision 2, Amendments 2026-11-04: the closed set, by name.
TWELVE = frozenset(
    {
        "tool_calling",
        "parallel_tool_calls",
        "strict_tools",
        "max_strict_tools",
        "numeric_bounds",
        "structured_output",
        "reasoning_effort",
        "usage_reporting",
        "stream_usage",
        "provider_tool_search",
        "max_input_tokens",
        "vision",
    }
)
ROUTES = ("structured_extraction", "reasoning", "chat", "deep_reasoning", "fallback", "embedding")


def _shipped(name: str) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load((MODELS / f"{name}.yaml").read_text("utf-8"))
    return document


def _routes(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(name, document[name]) for name in ROUTES if name in document]


def _refused(document: dict[str, Any], tmp_path: Path) -> str:
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ConfigError) as refused:
        load_profile(path)
    return str(refused.value)


def test_shipped_profiles_load() -> None:
    registry = ModelProfileRegistry()
    registry.load_directory(MODELS)
    assert registry.platform_ids() == frozenset(SHIPPED)


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_route_declares_where_it_processes(name: str) -> None:
    """R3.2: a mock route sends nothing anywhere (`vn`, processed by `mock`);
    every other route is `foreign` until FOG-18 locates its alias, and none
    says `vn` without that answer cited in the file."""
    document = _shipped(name)
    text = (MODELS / f"{name}.yaml").read_text("utf-8")
    for route_name, route in _routes(document):
        declared = (route["data_location"], route["processor"])
        if route["provider"] == "mock":
            assert declared == ("vn", "mock"), (name, route_name)
            assert (route["retention_days"], route["no_training"]) == (0, True)
        else:
            assert route["data_location"] == "foreign" or "FOG-18:" in text, (name, route_name)
            assert route["processor"] in {"fpt_ai_gateway", "deepseek", "openai"}
            assert (route["retention_days"], route["no_training"]) == (None, False)


@pytest.mark.parametrize("name", SHIPPED)
def test_no_shipped_profile_carries_a_price(name: str) -> None:
    """R2.3: the price book is the one owner of a price (DO-21.5)."""
    assert "price_per_million" not in (MODELS / f"{name}.yaml").read_text("utf-8")


def test_the_capabilities_are_the_closed_twelve() -> None:
    assert frozenset(ModelCapabilities.model_fields) == TWELVE


def test_an_undeclared_capability_reads_as_unsupported() -> None:
    route = load_profile(MODELS / "balanced.yaml").structured_extraction
    assert route.capabilities.strict_tools is False
    assert route.capabilities.numeric_bounds is False
    assert route.capabilities.max_strict_tools is None


def test_the_summary_route_keeps_its_input_budget_under_capabilities() -> None:
    chat = load_profile(MODELS / "gateway.yaml").chat
    assert chat is not None and chat.capabilities.max_input_tokens == 32000


def test_numbers_that_reach_a_hash_are_decimals_from_their_text() -> None:
    hot = ModelRoute.model_validate({**_shipped("balanced")["reasoning"], "temperature": 0.3})
    assert hot.temperature == Decimal("0.3")


def test_the_version_is_the_routing_policy_version() -> None:
    profile = load_profile(MODELS / "gateway.yaml")
    assert profile.schema_version == "2.0"
    assert profile.routing_policy_version == "2.1.0"


def test_pinned_routes_are_every_route_but_embedding() -> None:
    gateway = load_profile(MODELS / "gateway.yaml")
    assert set(gateway.pinned_routes()) == {
        "structured_extraction",
        "reasoning",
        "chat",
        "fallback",
    }


# ---- what the loader refuses (R2.3, R3.1; MR5) --------------------------------


def test_a_schema_one_file_is_refused(tmp_path: Path) -> None:
    document = _shipped("balanced") | {"schema_version": "1.0"}
    assert "schema_version" in _refused(document, tmp_path)


def test_a_route_still_carrying_a_price_is_refused(tmp_path: Path) -> None:
    document = copy.deepcopy(_shipped("balanced"))
    document["reasoning"]["price_per_million_input"] = 0.2
    assert "price_per_million_input" in _refused(document, tmp_path)


def test_a_capability_outside_the_twelve_is_refused(tmp_path: Path) -> None:
    document = copy.deepcopy(_shipped("balanced"))
    document["reasoning"]["capabilities"] = {"strict_tools": True, "telepathy": True}
    assert "telepathy" in _refused(document, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("data_location", None, id="no-data-location"),
        pytest.param("processor", None, id="no-processor"),
        pytest.param("data_location", "VN", id="data-location-VN"),
        pytest.param("processor", "  ", id="a-blank-processor"),
        pytest.param("retention_days", None, id="no-retention-days"),
        pytest.param("no_training", None, id="no-no-training"),
    ],
)
def test_a_route_without_its_data_route_is_refused(
    field: str, value: str | None, tmp_path: Path
) -> None:
    """R3.1: `None` here means the key is left out of the file."""
    document = copy.deepcopy(_shipped("luna"))
    route = document["fallback"]
    if value is None:
        del route[field]
    else:
        route[field] = value
    assert field in _refused(document, tmp_path)


def test_a_route_built_in_code_has_no_default_data_location() -> None:
    """R3.2: undeclared never becomes `vn`; there is no default to become."""
    with pytest.raises(ValidationError) as refused:
        ModelRoute(provider="openai_compatible", model="m")  # type: ignore[call-arg]
    missing = {error["loc"][0] for error in refused.value.errors()}
    assert {"data_location", "processor", "retention_days", "no_training"} <= missing
    assert ModelRoute.model_fields["data_location"].is_required()


def test_a_known_retention_of_unknown_length_is_written_out() -> None:
    """`retention_days: null` is a declaration ("not known"), not a default."""
    assert ModelRoute.model_fields["retention_days"].is_required()


def test_an_embedding_route_still_declares_its_width() -> None:
    document = copy.deepcopy(_shipped("gateway"))
    del document["embedding"]["dimensions"]
    with pytest.raises(ValidationError, match="dimensions"):
        ModelProfile.model_validate(document)
