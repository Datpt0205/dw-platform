"""Unit: the hand-off copy a wf-lite hand-off recommends from (wf-lite R6.20).

A packet's `recommendation` is never empty: the shipped file loads with its
fallback, and a file without it, or with an empty sentence, refuses to load.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dw_agent_runtime.adapters.wflite_host import FALLBACK_CODE, load_handoff_copy
from dw_kernel.errors import ConfigError

pytestmark = pytest.mark.unit

SHIPPED = Path(__file__).resolve().parents[5] / "configs" / "copy" / "wflite_handoff.yaml"


def test_the_shipped_copy_names_every_code_a_hand_off_carries() -> None:
    copy = load_handoff_copy(SHIPPED)
    expected = {
        FALLBACK_CODE,
        "model_output_invalid",
        "low_confidence",
        "definition_changed",
        "approval_missing",
        "subject_changed",
        "dw_not_operating",
        "tool_not_allowed",
        "scope_lost",
    }
    assert expected <= set(copy)
    assert all(text.strip() and "\n" not in text for text in copy.values())


@pytest.mark.parametrize(
    "body",
    [
        "recommendations:\n  low_confidence: Viết lại thư.\n",
        "recommendations:\n  step_failed: Xem lại.\n  low_confidence: '  '\n",
    ],
)
def test_a_copy_without_its_fallback_or_with_an_empty_sentence_refuses_to_load(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "wflite_handoff.yaml"
    path.write_text(
        'schema_version: "1.0"\ncopy_id: platform.wflite_handoff\nversion: "1.0.0"\n' + body,
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_handoff_copy(path)
