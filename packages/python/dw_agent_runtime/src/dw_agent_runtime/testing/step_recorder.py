"""`FakeStepRecorder`: `StepRecorderPort` in memory, honouring its contract
(workflow-engine/03 step 13), so a test of the node wrapper meets the same
refusals the real `platform.run_steps` adapter of telemetry-and-audit/03 does:
an attempt below 1, a missing lane or iteration path; `step_started` keeps the
first `started_at` of an attempt; `attempts` counts the attempts that ended.
`step_recorder_contract` runs against it and against the real adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from dw_agent_runtime.ports import LanePath, StepRun, check_step_run
from dw_kernel.ports import SystemClock, UtcClock


@dataclass
class FakeStepRecorder:
    clock: UtcClock = field(default_factory=SystemClock)
    started: dict[tuple[UUID, UUID, str, str, int], datetime] = field(default_factory=dict)
    finished: list[StepRun] = field(default_factory=list)

    async def attempts(
        self, *, tenant_id: UUID, run_id: UUID, node_id: str, iteration_path: str
    ) -> int:
        return len(
            {
                step.attempt
                for step in self.finished
                if (step.tenant_id, step.run_id, step.node_id, step.iteration_path)
                == (tenant_id, run_id, node_id, iteration_path)
            }
        )

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
        key = (tenant_id, run_id, node_id, iteration_path, attempt)
        return self.started.setdefault(key, self.clock.now())

    async def step_finished(self, step: StepRun) -> None:
        check_step_run(step.attempt, step.lane_path, step.iteration_path)
        self.finished.append(step)

    def of(self, node_id: str) -> list[StepRun]:
        return [step for step in self.finished if step.node_id == node_id]
