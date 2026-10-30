"""The `dw_timers` lane: a Digital Worker's run that waited on a timer runs on
(wf-lite R6.5, R6.12, R6.15).

Each pass asks `platform.dw_timer_scopes_due` which tenant and workspace hold a
work item `waiting_timer` whose `wake_at` has passed (ids only), then, scope by
scope under that scope's RLS:

1. claims what is due of an operating DW, `FOR UPDATE SKIP LOCKED`, pushing
   its `wake_at` 15 minutes ahead in the claim's own transaction (a lease): two
   lanes never take one item, and a lane that dies after the claim leaves the
   item due again once the lease runs out. A paused DW's items are not
   claimed; they wait, as they are, until it operates again (R6.15);
2. reads the item's run under the same scope and resumes it with the context
   its own row holds (`resume_context`): the run moves its item back to
   `in_progress`, and on to its next wait or its end.

A run that is no longer waiting (a lane that lost its answer resumed it
already) is refused by the runner with `ConflictError`, and that is a no-op
here: the item is where the run left it. One item's failure is logged and the
next runs; one scope's, the next scope.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from dw_agent_runtime.adapters.run_store import RunRecord, resume_context
from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import ConflictError
from dw_kernel.ports import UtcClock
from dw_platform.application.work_queue import WorkQueue, WorkScope
from dw_platform.domain.work_item import WorkItem

_LOG = logging.getLogger(__name__)

INTERVAL_SECONDS = 10.0
SCOPES_PER_PASS = 50
CLAIMS_PER_SCOPE = 20
CHANNEL = "dw_timer"


class WaitingRunsPort(Protocol):
    async def get_in(self, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID) -> RunRecord: ...


class RunResumerPort(Protocol):
    async def resume(
        self, *, run_context: RunContext, run_id: UUID, resume_payload: dict[str, Any]
    ) -> None: ...


def build_dw_timers_consumer(
    queue: WorkQueue, runs: WaitingRunsPort, runner: RunResumerPort, clock: UtcClock
) -> Callable[[], Awaitable[None]]:
    async def consume() -> None:
        for scope in await queue.due_timer_scopes(limit=SCOPES_PER_PASS):
            try:
                for item in await queue.claim_timers(scope, limit=CLAIMS_PER_SCOPE):
                    await _wake(scope, item, runs, runner, clock)
            except Exception:
                _LOG.exception("dw_timers scope failed", extra={"tenant_id": str(scope.tenant_id)})

    return consume


async def _wake(
    scope: WorkScope,
    item: WorkItem,
    runs: WaitingRunsPort,
    runner: RunResumerPort,
    clock: UtcClock,
) -> None:
    if item.run_id is None:
        _LOG.warning("dw_timers item has no run", extra={"work_item_id": str(item.id)})
        return
    try:
        record = await runs.get_in(
            tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, run_id=item.run_id
        )
        await runner.resume(
            run_context=resume_context(record, tenant_id=scope.tenant_id, channel=CHANNEL),
            run_id=record.id,
            resume_payload={"woke_at": clock.now().isoformat()},
        )
    except ConflictError:
        _LOG.info("dw_timers run no longer waiting", extra={"run_id": str(item.run_id)})
    except Exception:
        # The lease holds the item: it is due again in 15 minutes.
        _LOG.exception("dw_timers resume failed", extra={"run_id": str(item.run_id)})
