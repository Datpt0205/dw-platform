"""The code-sandbox 01 spike runs only when asked, and is red, not skipped,
when asked on an engine without `runsc-dw`.

Without DW_SANDBOX_SPIKE=1 every test here is skipped. With it, an engine that
does not list the runtime fails every test at setup, so the Done command cannot
pass on a machine where nothing was measured (failure-modes.md #3). On GitHub
Actions each test's outcome and measurements become one `::notice`, and each
failure one `::error`: the check run's annotations are public, its logs are not.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness  # noqa: E402

ENABLED = os.environ.get("DW_SANDBOX_SPIKE") == "1"
# Which engine this session measures, for the annotation titles: one job runs
# the tests on the rootless engine and again on the rootful fallback.
ENGINE_KIND = {"name": "unknown"}

# Caps the engine does not hold (R1.2), each test kept as written and expected
# to fail strictly, citing its blocking row in ADR-0119 (Proposed)'s
# Measurements. Rootless: runsc runs with --ignore-cgroups (setup_rootless.sh
# step 6 says why), so no container cgroup holds any cap. Rootful (the
# fallback of decision 2): cpu and memory hold, but --pids-limit becomes the
# sandbox's host pids.max, which gVisor's own threads nearly fill, and the
# first forks panic the sentry. A cap that starts holding turns its test red
# (XPASS): the signal to delete its entry here and its row in the ADR.
BLOCKED = {
    True: {
        "test_cpu_cap_holds": "ADR-0119 (Proposed) Measurements, blocking row B1: --cpus",
        "test_memory_cap_holds": "ADR-0119 (Proposed) Measurements, blocking row B2: --memory",
        "test_pids_cap_holds": "ADR-0119 (Proposed) Measurements, blocking row B3: --pids-limit",
    },
    False: {
        "test_pids_cap_holds": "ADR-0119 (Proposed) Measurements, blocking row B3: --pids-limit",
    },
}


def _ours(item_path: object) -> bool:
    return Path(str(item_path)).resolve().is_relative_to(HERE)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    ours = [item for item in items if _ours(item.path)]
    if not ENABLED:
        skip = pytest.mark.skip(
            reason="set DW_SANDBOX_SPIKE=1 on a host prepared by setup_rootless.sh beside this file"
        )
        for item in ours:
            item.add_marker(skip)
        return
    engine = harness.Engine.under_test()
    ENGINE_KIND["name"] = (
        "rootful" if (engine.host or "").endswith(harness.ROOTFUL_SOCKET) else "rootless"
    )
    blocked = BLOCKED[engine.is_rootless()]
    for item in ours:
        reason = blocked.get(item.name)
        if reason:
            item.add_marker(pytest.mark.xfail(strict=True, reason=reason))


@pytest.fixture(scope="session", autouse=True)
def engine() -> Iterator[harness.Engine]:
    found = harness.Engine.under_test()
    problem = found.missing_runtime()
    if problem:
        pytest.fail(problem, pytrace=False)
    found.reap()
    yield found
    found.reap()


def _decoded(value: object) -> object:
    """A property the tests recorded as JSON text, as the value it encodes."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for outcome in ("passed", "failed", "error", "xfailed", "xpassed", "skipped"):
        for report in terminalreporter.stats.get(outcome, []):
            nodeid = str(getattr(report, "nodeid", ""))
            if not nodeid or not _ours(Path(nodeid.split("::")[0])):
                continue
            name = f"{ENGINE_KIND['name']} {nodeid.split('::')[-1]}"
            measured = {
                key: _decoded(value) for key, value in getattr(report, "user_properties", [])
            }
            message = json.dumps({"outcome": outcome, **measured}, ensure_ascii=False)
            terminalreporter.write_line(
                harness.workflow_command("notice", f"sandbox-spike test {name}", message)
            )
            if outcome in ("failed", "error"):
                terminalreporter.write_line(
                    harness.workflow_command(
                        "error",
                        f"sandbox-spike test {name} {outcome}",
                        str(getattr(report, "longreprtext", ""))[-1500:],
                    )
                )
