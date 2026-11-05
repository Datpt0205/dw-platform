"""R5.4 (custom-objects ticket 03 step 6): the mode a write runs in is the
stricter of what the run's row holds (`app.run_mode`, which `bind_actor`
binds; empty for a person) and what the door passes, and a mode the service
cannot read writes nothing."""

from __future__ import annotations

import pytest

from dw_kernel.run_mode import RunMode
from dw_studio.records.application.record_service import _mode

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("bound", "asked", "runs"),
    [
        ("", "live", "live"),
        ("", "simulate", "simulate"),
        ("live", "live", "live"),
        ("simulate", "live", "simulate"),
        ("test", "live", "test"),
        ("live", "test", "test"),
        ("unreadable", "live", "simulate"),
    ],
)
def test_r5_4_the_stricter_of_the_row_s_mode_and_the_door_s(
    bound: str, asked: RunMode, runs: str
) -> None:
    assert _mode(bound, asked) == runs
