"""The stage machine's pure table (agent-lifecycle ticket 03, step 4; ADR-0120
decision 1), which `LifecycleService` asks before every move; the trigger
holds the same pairs as the backstop (`test_version_stage_contract.py`)."""

from __future__ import annotations

import pytest

from dw_studio.core.domain.artifacts import Stage, may_move
from dw_studio.lifecycle.application.service import SUBMIT_SEGMENTS

pytestmark = pytest.mark.unit

D, E, A, L, R = (
    Stage.DRAFT,
    Stage.EVALUATING,
    Stage.AWAITING_APPROVAL,
    Stage.LIVE,
    Stage.RETIRED,
)
GATED = {(D, E), (E, D), (E, A), (A, D), (A, L), (L, R)}
GATELESS = {(D, A), (A, D), (A, L), (L, R)}


@pytest.mark.parametrize("gated", [True, False])
def test_each_kind_has_exactly_its_moves(gated: bool) -> None:
    allowed = {(s, t) for s in Stage for t in Stage if may_move(s, t, gated=gated)}
    assert allowed == (GATED if gated else GATELESS)


def test_draft_to_live_is_the_tighten_only_branch_of_a_kind_without_a_gate() -> None:
    assert may_move(D, L, gated=False, tighten_only=True)
    assert not may_move(D, L, gated=False)
    assert not may_move(D, L, gated=True, tighten_only=True)


def test_only_the_gated_kinds_segments_are_mounted_in_this_ticket() -> None:
    """Ticket 04 adds `objects` and `data-sources` with the gateless branch."""
    assert dict(SUBMIT_SEGMENTS) == {"agents": "agent", "workflows": "workflow"}
