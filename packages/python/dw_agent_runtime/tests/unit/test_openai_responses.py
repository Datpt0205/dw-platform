"""Unit tests for the OpenAI Responses adapter internals."""

from __future__ import annotations

from typing import ClassVar

import httpx
import pytest

from dw_agent_runtime.adapters.openai_responses import (
    OpenAIResponsesAdapter,
    _build_request_body,
    _parse_responses_payload,
    _to_strict_schema,
)
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_agent_runtime.registry import ConfigError

pytestmark = pytest.mark.unit


def _payload(output: list[dict[str, object]]) -> dict[str, object]:
    return {"output": output, "usage": {"input_tokens": 10, "output_tokens": 5}}


def test_parses_json_and_reasoning_summary() -> None:
    data = _payload(
        [
            {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "Người dùng nêu ngân sách 7,5 tỷ."},
                    {"type": "summary_text", "text": "Trên ngưỡng 5 tỷ → đấu thầu."},
                ],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"intent": "provide_info"}'}],
            },
        ]
    )
    parsed, reasoning = _parse_responses_payload(data)
    assert parsed == {"intent": "provide_info"}
    assert reasoning is not None
    assert "7,5 tỷ" in reasoning and "đấu thầu" in reasoning
    assert reasoning.count("\n") == 1  # two summary parts joined line-by-line


def test_reasoning_absent_is_none_not_error() -> None:
    data = _payload(
        [{"type": "message", "content": [{"type": "output_text", "text": '{"ok": true}'}]}]
    )
    parsed, reasoning = _parse_responses_payload(data)
    assert parsed == {"ok": True}
    assert reasoning is None


def test_output_text_split_across_parts_is_joined() -> None:
    data = _payload(
        [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"a": '},
                    {"type": "output_text", "text": "1}"},
                ],
            }
        ]
    )
    parsed, _ = _parse_responses_payload(data)
    assert parsed == {"a": 1}


def test_refusal_raises_value_error() -> None:
    data = _payload(
        [{"type": "message", "content": [{"type": "refusal", "refusal": "cannot comply"}]}]
    )
    with pytest.raises(ValueError, match="refused"):
        _parse_responses_payload(data)


def test_missing_output_text_raises() -> None:
    with pytest.raises(ValueError, match="no output_text"):
        _parse_responses_payload(_payload([{"type": "reasoning", "summary": []}]))


def _prompt() -> RenderedPrompt:
    return RenderedPrompt(
        prompt_id="demo.p", version="1.0.0", system="sys", user="usr", checksum="x"
    )


def test_build_body_includes_effort_and_summary() -> None:
    route = ModelRoute(
        provider="openai_responses", model="gpt-5", timeout_seconds=60, reasoning_effort="low"
    )
    body = _build_request_body(
        _prompt(),
        {"type": "object"},
        route,
        reasoning_summary="auto",
        strict_schema=False,
        max_output_tokens=None,
    )
    assert body["reasoning"] == {"summary": "auto", "effort": "low"}
    assert body["model"] == "gpt-5"
    fmt = body["text"]["format"]  # type: ignore[index]
    assert fmt["type"] == "json_schema" and "strict" not in fmt


def test_build_body_without_effort_omits_it() -> None:
    route = ModelRoute(provider="openai_responses", model="gpt-5", timeout_seconds=60)
    body = _build_request_body(
        _prompt(),
        {"type": "object"},
        route,
        reasoning_summary="auto",
        strict_schema=False,
        max_output_tokens=500,
    )
    assert body["reasoning"] == {"summary": "auto"}
    assert body["max_output_tokens"] == 500
    assert "temperature" not in body


def test_build_body_sends_temperature_only_when_configured() -> None:
    route = ModelRoute(
        provider="openai_responses", model="gpt-5", timeout_seconds=60, temperature=0.3
    )
    body = _build_request_body(
        _prompt(),
        {"type": "object"},
        route,
        reasoning_summary="",
        strict_schema=False,
        max_output_tokens=None,
    )
    assert body["temperature"] == 0.3


def test_strict_schema_transform_closes_objects_and_strips_constraints() -> None:
    schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "pattern": r"^REQ-\d{2}$", "minLength": 1},
            "nested": {
                "type": "object",
                "properties": {"n": {"type": "integer", "minimum": 0, "default": 3}},
            },
            "items": {"type": "array", "items": {"type": "string", "maxLength": 5}},
        },
        "required": ["code"],
    }
    strict = _to_strict_schema(schema)
    assert strict["additionalProperties"] is False
    assert sorted(strict["required"]) == ["code", "items", "nested"]
    assert "pattern" not in strict["properties"]["code"]
    assert "minLength" not in strict["properties"]["code"]
    nested = strict["properties"]["nested"]
    assert nested["additionalProperties"] is False and nested["required"] == ["n"]
    assert "minimum" not in nested["properties"]["n"] and "default" not in nested["properties"]["n"]
    assert "maxLength" not in strict["properties"]["items"]["items"]


def test_strict_flag_transforms_body_schema() -> None:
    route = ModelRoute(provider="openai_responses", model="gpt-5", timeout_seconds=60)
    body = _build_request_body(
        _prompt(),
        {"type": "object", "properties": {"a": {"type": "string", "pattern": "x"}}},
        route,
        reasoning_summary="",
        strict_schema=True,
        max_output_tokens=None,
    )
    fmt = body["text"]["format"]  # type: ignore[index]
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert "pattern" not in fmt["schema"]["properties"]["a"]
    assert "reasoning" not in body  # summary "" disables the block entirely


class TestStrictSchemaLimits:
    """What strict structured output can and cannot express.

    Measured against the gateway on 2026-08-17: an object with `properties`
    closes and is accepted; an object with only `additionalProperties` - which
    is what Pydantic emits for `dict[str, str]` - is refused, and the endpoint
    blames the *parent's* required key at `context=()`. That misdirection is
    why the field is named here instead.
    """

    def test_a_free_form_map_is_refused_with_the_field_named(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "headers": {"type": "object", "additionalProperties": {"type": "string"}}
            },
        }
        with pytest.raises(ConfigError) as caught:
            _to_strict_schema(schema)
        assert "free-form map" in str(caught.value)
        assert "headers" in str(caught.value.details["path"])

    def test_an_object_with_properties_is_closed_and_fully_required(self) -> None:
        strict = _to_strict_schema(
            {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
        )
        assert strict["additionalProperties"] is False
        assert strict["required"] == ["a", "b"]

    def test_a_property_named_like_a_keyword_is_kept(self) -> None:
        """wf-ai/05: `default` and `format` are stripped as keywords, never as the
        names of a caller's fields (a switch lost its `default` lane that way)."""
        strict = _to_strict_schema(
            {
                "type": "object",
                "properties": {
                    "on": {"type": "string", "default": "x"},
                    "default": {"type": "array", "items": {"type": "string"}, "default": []},
                    "format": {"type": "string", "format": "date"},
                },
                "$defs": {"pattern": {"type": "object", "properties": {"x": {"type": "string"}}}},
            }
        )
        assert list(strict["properties"]) == ["on", "default", "format"]
        assert strict["required"] == ["on", "default", "format"]
        assert "default" not in strict["properties"]["on"]
        assert "default" not in strict["properties"]["default"]
        assert "format" not in strict["properties"]["format"]
        assert strict["$defs"]["pattern"]["required"] == ["x"]

    def test_a_nested_definition_is_closed_too(self) -> None:
        strict = _to_strict_schema(
            {
                "type": "object",
                "properties": {"item": {"$ref": "#/$defs/Item"}},
                "$defs": {"Item": {"type": "object", "properties": {"x": {"type": "string"}}}},
            }
        )
        assert strict["$defs"]["Item"]["required"] == ["x"]
        assert strict["$defs"]["Item"]["additionalProperties"] is False


class _StubResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _StubClient:
    """Captures the body ``complete_json`` posts, without reaching the network."""

    sent: ClassVar[dict[str, object]] = {}

    def __init__(self, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(self, _path: str, *, json: dict[str, object]) -> _StubResponse:
        _StubClient.sent = json
        return _StubResponse(
            _payload(
                [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"a": "x"}'}],
                    }
                ]
            )
        )


async def _post_body(route: ModelRoute, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    adapter = OpenAIResponsesAdapter(base_url="https://gw.invalid/v1", api_key="k")
    schema: dict[str, object] = {"type": "object", "properties": {"a": {"type": "string"}}}
    await adapter.complete_json(_prompt(), schema, route, max_output_tokens=None)
    return _StubClient.sent


@pytest.mark.asyncio
async def test_a_route_that_asks_for_no_summary_is_not_billed_for_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The batch routes declare no summary, and `generate_structured` discards
    the one the adapter used to request regardless."""
    route = ModelRoute(
        provider="openai_responses",
        model="gpt-5.6-luna",
        timeout_seconds=60,
        reasoning_effort="low",
    )
    body = await _post_body(route, monkeypatch)
    assert body["reasoning"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_a_route_that_declares_a_summary_gets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    route = ModelRoute(
        provider="openai_responses",
        model="gpt-5.6-luna",
        timeout_seconds=60,
        reasoning_effort="medium",
        reasoning_summary="auto",
    )
    body = await _post_body(route, monkeypatch)
    assert body["reasoning"] == {"summary": "auto", "effort": "medium"}
