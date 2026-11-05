"""R5.9: the term of `studio.record_write_keys` against a run's deadline
(custom-objects ticket 03; workflow-engine R5.22)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from dw_kernel.run_mode import STUDIO_RUN_DEADLINE
from dw_platform.retention_policy import load_retention_policy

pytestmark = pytest.mark.unit


def test_r5_9_the_keys_outlive_a_run_s_deadline() -> None:
    """A step's last replay comes at most at the run's deadline; its key must
    still be there, so the fragment keeps it longer (31 days against 30)."""
    term = load_retention_policy().term("studio.record_write_keys")
    assert term is not None and term.enforced
    assert timedelta(days=term.days) > STUDIO_RUN_DEADLINE
