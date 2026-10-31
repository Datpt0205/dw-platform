"""Unit: a pinned workflow as the DW page reads it (digital-worker R9.2).

The shipped lead-care document is the fixture: its classes call several tools
each, in nested lanes, which is where a walk that misses a lane goes wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dw_agent_runtime.wflite.catalog import load_shipped_packs
from dw_agent_runtime.wflite.outline import (
    OutlineStep,
    blocked_classes,
    decision_mode,
    outline,
)
from dw_agent_runtime.wflite.registry import build_node_registry

pytestmark = pytest.mark.unit

CONFIGS = Path(__file__).resolve().parents[5] / "configs"
REGISTRY = build_node_registry()
PINNED = load_shipped_packs(CONFIGS).workflow("lead_care", "1.0.0")
assert PINNED is not None
DOCUMENT = PINNED.document


def _ids(steps: tuple[OutlineStep, ...]) -> list[str]:
    found: list[str] = []
    for step in steps:
        found.append(step.id)
        for _, lane in step.lanes:
            found.extend(_ids(lane))
    return found


def test_the_outline_holds_every_step_of_every_lane_once() -> None:
    ids = _ids(outline(DOCUMENT, REGISTRY))
    assert len(ids) == len(set(ids)) == 15
    assert {"handoff_reply", "handoff_reminder_rejected", "handoff_rejected"} <= set(ids)


def test_a_class_is_blocked_only_when_every_tool_it_calls_is_outside_allowed_tools() -> None:
    every = frozenset({"email.send", "mailbox.fetch_reply", "work.handoff"})
    assert blocked_classes(DOCUMENT, REGISTRY, every) == frozenset()
    assert blocked_classes(DOCUMENT, REGISTRY, frozenset()) == {"email.send", "work.handoff"}
    # work.handoff calls two tools; one of them allowed is enough to act.
    assert blocked_classes(DOCUMENT, REGISTRY, frozenset({"mailbox.fetch_reply"})) == {"email.send"}
    # Versions are not part of the name `allowed_tools` holds.
    assert "email.send" not in blocked_classes(DOCUMENT, REGISTRY, frozenset({"email.send"}))


@pytest.mark.parametrize(
    ("blocked", "requires_person", "mode"),
    [
        (True, False, "blocked"),
        (True, True, "blocked"),
        (False, True, "ask"),
        (False, False, "auto"),
    ],
)
def test_the_mode_says_blocked_before_it_says_ask(
    blocked: bool, requires_person: bool, mode: str
) -> None:
    assert decision_mode(blocked=blocked, requires_person=requires_person) == mode
