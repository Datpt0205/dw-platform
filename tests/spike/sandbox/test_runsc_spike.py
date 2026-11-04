"""R1.2 to R1.4 of code-sandbox 01: the caps of `py-small` hold under runsc on
a rootless engine (CS1), the host keeps serving while bombs run (R1.3), and the
container really runs on gVisor (CS2).

    DW_SANDBOX_SPIKE=1 uv run python -m pytest tests/spike/sandbox

Every threshold lives in `harness.py`, beside the procedure that measures it.
A cap the engine does not honour is not loosened here: its test carries
`pytest.mark.xfail(strict=True)` pointing at its blocking row in ADR-0119
(Proposed) (R1.2).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import harness

Record = Callable[[str, object], None]


def _record(record_property: Record, found: Any) -> None:
    record_property("measured", json.dumps(asdict(found), ensure_ascii=False))


def test_cpu_cap_holds(engine: harness.Engine, record_property: Record) -> None:
    found = harness.measure_cpu(engine)
    _record(record_property, found)
    assert found.ratio <= harness.CPU_RATIO_MAX, (
        f"{found.ratio} vCPU used under --cpus=0.5 (cpu.max {found.cpu_max})"
    )


def test_memory_cap_holds(engine: harness.Engine, record_property: Record) -> None:
    found = harness.measure_memory(engine)
    _record(record_property, found)
    assert found.held, (
        f"OOMKilled {found.oom_killed}, exit {found.exit_code} after {found.seconds} s, "
        f"{found.allocated_mib} MiB allocated, memory.peak {found.peak_bytes} B "
        f"(limit {harness.MEMORY_PEAK_MAX:.0f} B)"
    )


def test_pids_cap_holds(engine: harness.Engine, record_property: Record) -> None:
    found = harness.measure_fork_bomb(engine)
    _record(record_property, found)
    assert found.held, (
        f"{found.max_inside} processes in the guest under --pids-limit={harness.PIDS_CAP}, "
        f"sandbox exit {found.sandbox_exit}: {found.samples}"
    )


def test_host_keeps_serving_during_bombs(engine: harness.Engine, record_property: Record) -> None:
    found = harness.measure_serving_during_bombs(engine)
    _record(record_property, found)
    late = [probe for probe in found.probes if not probe.ok]
    assert not late, f"probes over {harness.PROBE_DEADLINE_SECONDS} s or wrong: {late}"
    assert found.info_seconds <= harness.INFO_DEADLINE_SECONDS, (
        f"docker info took {found.info_seconds} s after the bombs were removed"
    )


def test_engine_reports_runsc_dw(engine: harness.Engine, record_property: Record) -> None:
    found = harness.measure_runtime(engine)
    record_property("measured", json.dumps({"runtime": found.host_config_runtime}))
    assert found.host_config_runtime == harness.RUNTIME


def test_kernel_inside_is_gvisor(engine: harness.Engine, record_property: Record) -> None:
    # HostConfig.Runtime only repeats what the harness asked for
    # (failure-modes.md #0); the guest kernel's own log is the evidence.
    found = harness.measure_runtime(engine)
    record_property("measured", json.dumps({"dmesg_head": found.dmesg[:300]}))
    assert found.is_gvisor, f"dmesg inside the container has no 'gVisor': {found.dmesg[:500]!r}"
