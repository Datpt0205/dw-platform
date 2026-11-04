from typing import Any

import pytest

from dw_agent_runtime.adapters.openai_compatible import _build_request_body, _extract_json_object
from dw_agent_runtime.model.profiles import ModelRoute
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_agent_runtime.testing.models import route as test_route

pytestmark = pytest.mark.unit

SCHEMA: dict[str, object] = {"type": "object", "properties": {"answer": {"type": "string"}}}


def _prompt() -> RenderedPrompt:
    return RenderedPrompt(
        prompt_id="demo", version="1.0.0", system="Bạn là trợ lý.", user="Xin chào", checksum="abc"
    )


def _route(**overrides: Any) -> ModelRoute:
    defaults: dict[str, Any] = {"provider": "openai_compatible", "model": "gpt-4o-mini"}
    defaults.update(overrides)
    return test_route(**defaults)


def test_json_schema_mode_sends_native_response_format() -> None:
    body = _build_request_body(
        _prompt(), SCHEMA, _route(), structured_mode="json_schema", max_output_tokens=None
    )
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "structured_output", "schema": SCHEMA},
    }
    assert "temperature" not in body


def test_reasoner_puts_schema_in_prompt_and_drops_response_format() -> None:
    body = _build_request_body(
        _prompt(),
        SCHEMA,
        _route(model="deepseek-reasoner"),
        structured_mode="json_schema",
        max_output_tokens=None,
    )
    assert "response_format" not in body
    messages = body["messages"]
    assert isinstance(messages, list)
    assert "answer" in messages[0]["content"]


def test_temperature_is_sent_only_when_configured() -> None:
    body = _build_request_body(
        _prompt(),
        SCHEMA,
        _route(temperature=0.4),
        structured_mode="json_schema",
        max_output_tokens=None,
    )
    assert body["temperature"] == 0.4


@pytest.mark.parametrize(
    ("model", "expected_key"),
    [("gpt-4o-mini", "max_tokens"), ("gpt-5", "max_completion_tokens")],
)
def test_output_token_key_depends_on_model_family(model: str, expected_key: str) -> None:
    body = _build_request_body(
        _prompt(), SCHEMA, _route(model=model), structured_mode="json_schema", max_output_tokens=800
    )
    assert body[expected_key] == 800


def test_json_object_is_extracted_from_fenced_text() -> None:
    assert _extract_json_object('```json\n{"answer": "ok"}\n```') == {"answer": "ok"}


def test_non_object_json_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-object"):
        _extract_json_object("[1, 2]")
