"""The prototype builds its executor from the unit suite's in-memory doubles
(`tests/unit/fakes.py`) rather than a copy of them, so that directory is put
on the path for a run that collects only this one."""

from __future__ import annotations

import sys
from pathlib import Path

UNIT = str(Path(__file__).resolve().parents[1] / "unit")
if UNIT not in sys.path:
    sys.path.insert(0, UNIT)
