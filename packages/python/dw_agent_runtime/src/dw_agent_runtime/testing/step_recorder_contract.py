"""The contract of `StepRecorderPort`, as functions a test runs against any
implementation (workflow-engine/03 step 13): the fake here, and the
`platform.run_steps` adapter of telemetry-and-audit/03, so the fake cannot
drift from the real one (as `records_port_contract` does for `RecordsPort`).

Each check takes a factory of a fresh recorder and the tenant and run it may
write under (a real adapter needs a planted run); each raises
`AssertionError` naming what broke.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from dw_agent_runtime.ports import LanePath, StepRecorderPort, StepRun

RecorderFactory = Callable[[], Awaitable[StepRecorderPort]]


def _run(
    tenant_id: UUID, run_id: UUID, *, attempt: int, lane_path: Any = (), iteration_path: Any = ""
) -> StepRun:
    return StepRun(
        tenant_id=tenant_id,
        run_id=run_id,
        node_id="gui_email",
        lane_path=lane_path,
        iteration_path=iteration_path,
        attempt=attempt,
        started_at=datetime(2026, 11, 5, tzinfo=UTC),
        status="failed",
        port=None,
        error_type="not_dispatched",
        simulated=False,
        source="door",
        inputs={},
        output={},
        field_ids={},
    )


async def _refused(call: Awaitable[Any]) -> bool:
    try:
        await call
    except ValueError:
        return True
    return False


async def check_refuses_a_bad_attempt(make: RecorderFactory, tenant: UUID, run: UUID) -> None:
    recorder = await make()
    lane: LanePath = ()
    for attempt in (0, -1):
        assert await _refused(
            recorder.step_started(
                tenant_id=tenant,
                run_id=run,
                node_id="gui_email",
                lane_path=lane,
                iteration_path="",
                attempt=attempt,
            )
        ), f"step_started took attempt {attempt}"
        assert await _refused(recorder.step_finished(_run(tenant, run, attempt=attempt))), (
            f"step_finished took attempt {attempt}"
        )


async def check_refuses_missing_paths(make: RecorderFactory, tenant: UUID, run: UUID) -> None:
    recorder = await make()
    assert await _refused(recorder.step_finished(_run(tenant, run, attempt=1, lane_path=None)))
    assert await _refused(recorder.step_finished(_run(tenant, run, attempt=1, iteration_path=None)))


async def check_started_at_is_the_first(make: RecorderFactory, tenant: UUID, run: UUID) -> None:
    """Run again after a crash, the same attempt gets the same `started_at`."""
    recorder = await make()
    lane: LanePath = (("duyet", "rejected"),)
    first = await recorder.step_started(
        tenant_id=tenant,
        run_id=run,
        node_id="gui_email",
        lane_path=lane,
        iteration_path="",
        attempt=1,
    )
    again = await recorder.step_started(
        tenant_id=tenant,
        run_id=run,
        node_id="gui_email",
        lane_path=lane,
        iteration_path="",
        attempt=1,
    )
    assert again == first, "the same attempt started twice got a second time"


async def check_attempts_count_what_ended(make: RecorderFactory, tenant: UUID, run: UUID) -> None:
    recorder = await make()
    assert (
        await recorder.attempts(
            tenant_id=tenant, run_id=run, node_id="gui_email", iteration_path=""
        )
        == 0
    )
    await recorder.step_finished(_run(tenant, run, attempt=1))
    await recorder.step_finished(_run(tenant, run, attempt=2))
    assert (
        await recorder.attempts(
            tenant_id=tenant, run_id=run, node_id="gui_email", iteration_path=""
        )
        == 2
    )


CHECKS = (
    check_refuses_a_bad_attempt,
    check_refuses_missing_paths,
    check_started_at_is_the_first,
    check_attempts_count_what_ended,
)
