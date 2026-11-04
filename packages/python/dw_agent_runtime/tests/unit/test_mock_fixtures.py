"""Recorded provider responses, read from disk.

`MockModelAdapter` has been able to load a fixture per prompt since it was
written, `bootstrap/models.py` points it at `evals/fixtures/mock_model`, and
nothing had ever put a file there or read one back. Code that is configured and
never exercised is the shape this repository keeps producing — it reads as a
capability in review and is discovered to be untested by whoever first needs it.

What the fixtures are FOR: running the platform, its evals and its demos without
a provider. A recorded answer is deterministic, costs nothing, and does not go
stale when a model is retired — which is the difference between a suite that can
run on a laptop with no keys and one that cannot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.model.prompts import RenderedPrompt
from dw_agent_runtime.testing.models import route as test_route
from dw_kernel.errors import NotFoundError

pytestmark = pytest.mark.unit

ROUTE = test_route(provider="mock", model="mock-1")


def _prompt(prompt_id: str = "platform.demo", version: str = "1.0.0") -> RenderedPrompt:
    return RenderedPrompt(
        prompt_id=prompt_id,
        version=version,
        system="Bạn là trợ lý.",
        user="Xin chào",
        checksum="0" * 64,
    )


def _write(directory: Path, name: str, body: object) -> None:
    (directory / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


async def _complete(adapter: MockModelAdapter, prompt: RenderedPrompt) -> dict[str, object]:
    response, _usage, _reasoning = await adapter.complete_json(
        prompt, {}, ROUTE, max_output_tokens=None
    )
    return response


async def test_a_recorded_answer_is_replayed(tmp_path: Path) -> None:
    _write(tmp_path, "platform.demo@1.0.0.json", {"lead_id": "L-1", "score": 82})
    adapter = MockModelAdapter(fixtures_dir=tmp_path)

    assert await _complete(adapter, _prompt()) == {"lead_id": "L-1", "score": 82}


async def test_the_fixture_is_found_by_prompt_id_and_by_version(tmp_path: Path) -> None:
    """Versions are the point. A prompt is a versioned artifact, so a recording
    made against 1.0.0 must not answer for 2.0.0 — the wording it was recorded
    against is exactly what changed."""
    _write(tmp_path, "platform.demo@1.0.0.json", {"from": "v1"})
    adapter = MockModelAdapter(fixtures_dir=tmp_path)

    assert await _complete(adapter, _prompt(version="1.0.0")) == {"from": "v1"}
    with pytest.raises(NotFoundError):
        await _complete(adapter, _prompt(version="2.0.0"))


async def test_a_prompt_with_no_recording_is_refused_not_invented(tmp_path: Path) -> None:
    """The failure has to be loud. A mock that answered something plausible for
    a prompt nobody recorded would make a green suite that proves nothing."""
    adapter = MockModelAdapter(fixtures_dir=tmp_path)

    with pytest.raises(NotFoundError) as raised:
        await _complete(adapter, _prompt())

    assert raised.value.details["prompt_id"] == "platform.demo"


async def test_a_fixture_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    """A JSON list parses fine and is not a model response. Caught here rather
    than as a confusing error three layers up."""
    _write(tmp_path, "platform.demo@1.0.0.json", ["không phải object"])
    adapter = MockModelAdapter(fixtures_dir=tmp_path)

    with pytest.raises(NotFoundError, match="JSON object"):
        await _complete(adapter, _prompt())


async def test_a_registered_builder_wins_over_a_recording(tmp_path: Path) -> None:
    """A test that wants to script an answer should not have to delete a file to
    do it."""
    _write(tmp_path, "platform.demo@1.0.0.json", {"from": "fixture"})
    adapter = MockModelAdapter(fixtures_dir=tmp_path)
    adapter.register_builder("platform.demo", "1.0.0", lambda prompt: {"from": "builder"})

    assert await _complete(adapter, _prompt()) == {"from": "builder"}


async def test_usage_is_reported_even_though_nothing_was_paid_for(tmp_path: Path) -> None:
    """Token counts keep the budget and the usage ledger exercised on the mock
    path; the COST is zero because no money moved, which is a different claim
    from "nobody priced it"."""
    _write(tmp_path, "platform.demo@1.0.0.json", {"ok": True})
    adapter = MockModelAdapter(fixtures_dir=tmp_path)

    _response, usage, _reasoning = await adapter.complete_json(
        _prompt(), {}, ROUTE, max_output_tokens=None
    )

    assert usage.input_tokens >= 1
    assert usage.output_tokens >= 1
    assert usage.cost_usd == 0.0


async def test_without_a_fixtures_directory_only_builders_answer() -> None:
    """The unchanged behaviour, pinned: a unit test that scripts its own answers
    must not start needing a directory on disk."""
    adapter = MockModelAdapter()
    adapter.register_builder("platform.demo", "1.0.0", lambda prompt: {"from": "builder"})

    assert await _complete(adapter, _prompt()) == {"from": "builder"}
    with pytest.raises(NotFoundError):
        await _complete(adapter, _prompt(prompt_id="platform.other"))
