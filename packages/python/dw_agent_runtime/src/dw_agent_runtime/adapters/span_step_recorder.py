"""`TelemetryStepRecorder`: the `StepRecorderPort` a composition root wires
until telemetry-and-audit/03's `platform.run_steps` adapter exists
(workflow-engine/03 step 13).

It keeps nothing in memory (failure-modes #6): each ended attempt becomes one
`dw.node` span of safe identifiers, never a value the step read or wrote. Having no store,
it cannot answer `attempts` with what a crashed process recorded, so it says
0, and a run taken again counts its attempts from 1; `step_started` answers
the time of the call. Both are what the real adapter fixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from dw_agent_runtime.ports import LanePath, StepRun, check_step_run
from dw_kernel.ports import UtcClock
from dw_observability.semconv import DW_NODE
from dw_observability.telemetry import TelemetryPort


@dataclass(frozen=True)
class TelemetryStepRecorder:
    telemetry: TelemetryPort
    clock: UtcClock

    async def attempts(
        self, *, tenant_id: UUID, run_id: UUID, node_id: str, iteration_path: str
    ) -> int:
        return 0

    async def step_started(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        node_id: str,
        lane_path: LanePath,
        iteration_path: str,
        attempt: int,
    ) -> datetime:
        check_step_run(attempt, lane_path, iteration_path)
        return self.clock.now()

    async def step_finished(self, step: StepRun) -> None:
        check_step_run(step.attempt, step.lane_path, step.iteration_path)
        with self.telemetry.span(
            DW_NODE,
            {
                "dw.tenant_id": str(step.tenant_id),
                "dw.run_id": str(step.run_id),
                "dw.step_id": step.node_id,
            },
        ):
            pass
