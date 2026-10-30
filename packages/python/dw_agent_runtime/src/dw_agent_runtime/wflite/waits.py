"""A Digital Worker's work item, following its run (wf-lite R6.3, R6.5, R6.7).

`RunWaitsPort` for the runner, over the work queue: the item of a run goes to
`waiting_approval` or `waiting_timer` when the run waits, back to
`in_progress` when it resumes, to `done` or `failed` when it ends. An item that
is no longer where that move starts is left as it is: a run that handed its
work to a person still completes, and the person's item stays theirs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from dw_agent_runtime.contracts import RunContext
from dw_platform.application.work_queue import WorkQueue, WorkScope


def _scope(run_context: RunContext) -> WorkScope:
    return WorkScope(tenant_id=run_context.tenant_id, workspace_id=run_context.workspace_id)


@dataclass(frozen=True)
class WorkQueueRunWaits:
    queue: WorkQueue

    async def waiting(
        self,
        run_context: RunContext,
        run_id: UUID,
        *,
        kind: Literal["approval", "timer"],
        wake_at: datetime | None = None,
    ) -> None:
        scope = _scope(run_context)
        item = await self.queue.by_run(scope, run_id)
        if item is None or item.status != "in_progress":
            return
        await self.queue.record_wait(
            scope,
            item.id,
            target="waiting_timer" if kind == "timer" else "waiting_approval",
            wake_at=wake_at if kind == "timer" else None,
        )

    async def resumed(self, run_context: RunContext, run_id: UUID) -> None:
        scope = _scope(run_context)
        item = await self.queue.by_run(scope, run_id)
        if item is None or item.status not in ("waiting_approval", "waiting_timer"):
            return
        await self.queue.resume_claimed(scope, item.id)

    async def finished(self, run_context: RunContext, run_id: UUID, *, failed: bool) -> None:
        scope = _scope(run_context)
        item = await self.queue.by_run(scope, run_id)
        if item is None or item.status != "in_progress":
            return
        await self.queue.finish(
            scope,
            item.id,
            outcome="failed" if failed else "done",
            error="run_failed" if failed else None,
        )
