"""Unit: the builder's fixtures F1-F9 are documents of wf-lite's one model
(workflow-builder-ui ticket 02 step 2; ADR-0112 Amendments 2026-11-03).

`apps/web/lib/__fixtures__/workflows/f*.json` are what the web's tree
operations and layout are tested on. Each must load through
`WorkflowDocument.model_validate`, the model every path reads, so a fixture
that drifts from the document's shape (a key the model refuses, a step key
the model does not have) goes red here and not in a browser. Every lane's
steps are validated as `Step` too: the model keeps a lane's items as plain
dicts inside `config` and `error_lane`, and lowering parses them later.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.wflite.document import Step, WorkflowDocument

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).resolve().parents[5] / "apps/web/lib/__fixtures__/workflows"
_FILES = sorted(_FIXTURES.glob("f[0-9]-*.json"))


def _lane_items(value: Any) -> Iterator[dict[str, Any]]:
    """Every step object found in a step's lanes, at any depth: a list of
    step-shaped dicts under a config key, a keyed object of such lists, or the
    error lane. Read structurally, so the test needs no catalogue."""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and "id" in item and "type" in item:
                yield item
                yield from _lane_items(item.get("config"))
                yield from _lane_items(item.get("error_lane"))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _lane_items(item)


def test_there_are_nine_fixtures() -> None:
    assert [path.name[:2] for path in _FILES] == [f"f{n}" for n in range(1, 10)]


@pytest.mark.parametrize("path", _FILES, ids=lambda path: path.name)
def test_fixture_is_a_workflow_document(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    document = WorkflowDocument.model_validate(raw)
    assert document.schema_ == "dw.workflow/v1"
    # Dumped back, nothing is lost: no key of the fixture was outside the model.
    dumped = document.model_dump(by_alias=True, exclude_unset=True)
    assert dumped == raw
    nested = [step for top in document.steps for step in _lane_items([top.model_dump()])]
    assert len(nested) > len(document.steps) or path.name.startswith("f8")
    for item in nested:
        Step.model_validate(item)
