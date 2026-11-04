"""Spike S-RT checks (discovery 14). Outside pytest's `testpaths`, so no CI
suite collects them; run them by path:

    DW_TEST_DB_SUFFIX=_lane2 uv run python tests/spike/srt/run_srt.py setup
    DW_TEST_DB_SUFFIX=_lane2 uv run pytest tests/spike/srt -m unit
    DW_TEST_DB_SUFFIX=_lane2 uv run pytest tests/spike/srt -m integration

The integration checks start real worker processes on the spike database and
take minutes (the crash matrix waits out a 60 s lease).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from srtlib import measure
from srtlib.compiler import Lowering
from srtlib.control import Harness
from srtlib.db import reset, urls
from srtlib.doc import lanes, walk
from srtlib.workflows import WORKFLOWS


@pytest.mark.unit
@pytest.mark.parametrize("key", sorted(WORKFLOWS))
def test_every_reference_workflow_compiles(key: str) -> None:
    Lowering(WORKFLOWS[key]).build().compile()


@pytest.mark.unit
def test_parallel_lanes_export_disjoint_channels() -> None:
    lowering = Lowering(WORKFLOWS["rw2_q7"])
    for step in walk(WORKFLOWS["rw2_q7"].steps):
        if step.type != "logic.parallel@1":
            continue
        owned = [set(lowering._owned(lane)) for lane in lanes(step).values()]
        for i, a in enumerate(owned):
            for b in owned[i + 1 :]:
                assert not a & b


def _experiment(name: str, **kwargs: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        h = Harness(urls(), Path(tempfile.mkdtemp(prefix=f"srt-{name}-")))
        await reset(h.migrator)
        try:
            if kwargs:
                return await measure.t3(h, **kwargs)
            return await measure.EXPERIMENTS[name](h)
        finally:
            h.stop_all()
            await h.dispose()

    return asyncio.run(go())


@pytest.mark.integration
def test_golden_traces_of_the_reference_workflows() -> None:
    result = _experiment("t1")
    assert result["pass"], [c for c in result["cases"] if not c["pass"]]


@pytest.mark.integration
def test_the_step_counter_stops_a_waiting_loop_and_recursion_limit_does_not() -> None:
    result = _experiment("t1r")
    assert result["pass"], result


@pytest.mark.integration
def test_keyed_effects_are_applied_once_at_every_crash_point() -> None:
    result = _experiment("t3", only="keyed-K")
    assert result["pass"], [c for c in result["cells"] if not c["verdict"]["pass"]]
