"""Unit: the work item's transition table, hand-off packet and payload hash
(digital-worker R3.1, R3.12, R4.2)."""

from __future__ import annotations

import pytest

from dw_kernel.errors import ConflictError, DomainError
from dw_platform.domain.work_item import (
    MAX_HANDOFF_FIELD,
    TERMINAL,
    TRANSITIONS,
    HandoffPacket,
    check_transition,
    payload_hash,
    sources_of,
)

pytestmark = pytest.mark.unit

PACKET = {"problem": "p", "context": "c", "tried": "t", "recommendation": "r"}


def test_nothing_leaves_an_end_state() -> None:
    assert not [pair for pair in TRANSITIONS if pair[0] in TERMINAL]


def test_a_move_is_asked_by_the_path_that_owns_it() -> None:
    check_transition("handed_off", "done", "holder")
    for current, target, mover in (
        ("done", "in_progress", "runner"),  # DWK31
        ("in_progress", "done", "holder"),  # DWK12: a person closes only handed-off work
        ("open", "done", "runner"),
        ("handed_off", "done", "runner"),
    ):
        with pytest.raises(ConflictError) as refused:
            check_transition(current, target, mover)  # type: ignore[arg-type]
        assert refused.value.details["reason_code"] == "invalid_transition"


def test_the_sources_a_hand_off_comes_from() -> None:
    assert sources_of("handed_off", "hand_off") == {
        "in_progress",
        "waiting_approval",
        "waiting_timer",
    }


def test_a_packet_has_four_fields_of_bounded_length() -> None:
    assert HandoffPacket.of(PACKET).as_dict() == PACKET
    assert HandoffPacket.of({**PACKET, "tried": "x" * MAX_HANDOFF_FIELD}).tried
    for bad in (
        {k: v for k, v in PACKET.items() if k != "recommendation"},
        {**PACKET, "tried": "x" * (MAX_HANDOFF_FIELD + 1)},
        {**PACKET, "context": "  "},
        {**PACKET, "extra": "x"},
        {**PACKET, "problem": 3},
    ):
        with pytest.raises(DomainError) as refused:
            HandoffPacket.of(bad)
        assert refused.value.details["reason_code"] == "handoff_packet_invalid"


def test_a_payload_hash_ignores_key_order() -> None:
    assert payload_hash({"a": 1, "b": [1, 2]}) == payload_hash({"b": [1, 2], "a": 1})
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})
    assert len(payload_hash({})) == 64
