"""The `dw_work` lane: Digital Workers take their work (digital-worker R3.6-R3.9,
R3.14, R3.15; ADR-0113 decision 2).

Each pass asks `platform.dw_work_scopes_due` which tenant and workspace hold
work due or stuck (ids only), then, scope by scope under that scope's RLS:

1. returns to `open` what was claimed 15 minutes ago and never became a run,
   keeping its run id (R3.14);
2. claims what is due, `FOR UPDATE SKIP LOCKED`, moving it to `in_progress`
   with its run id in the claim's own transaction (R3.6);
3. asks `DigitalWorkerRunStarter` to start each run with that id. A refusal
   for the tenant's limit puts the work back for five minutes (R3.9); a run
   that already exists is not an error (R3.15); any other refusal the start
   names fails the item with its code (R3.15). A failure that is not a
   refusal (the database, the network) leaves the item claimed, and step 1
   returns it in 15 minutes: nothing is dropped and nothing is started twice.

One scope's failure is logged and the next scope runs.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from dw_kernel.errors import ConflictError, DWError, InfrastructureError, QuotaExceededError
from dw_platform.application.work_queue import Claimed, WorkQueue, WorkScope

_LOG = logging.getLogger(__name__)

INTERVAL_SECONDS = 10.0
SCOPES_PER_PASS = 50
CLAIMS_PER_SCOPE = 20


class DigitalWorkerRunStarter(Protocol):
    """Starts the run of a claimed item with the claim's run id.

    Raises `QuotaExceededError` when the runner refuses for the tenant's
    limit, `ConflictError` when a run with that id already exists, and
    another `DWError` (never `InfrastructureError`) for a start it refuses
    for good: a workflow that does not load, parameters that are wrong.
    wf-lite/02 wires the one that runs the pinned workflow."""

    async def start(self, claimed: Claimed) -> None: ...


class RecordingRunStarter:
    """Records that a run was asked for and starts nothing: the starter until
    wf-lite/02 wires the workflow engine. A deployment cannot reach it with
    work yet (no pack declares a work kind's schema, so every payload is
    refused at the door); should one, the item is returned by step 1 and
    asked for again, never lost."""

    def __init__(self) -> None:
        self.asked: list[Claimed] = []

    async def start(self, claimed: Claimed) -> None:
        self.asked.append(claimed)
        _LOG.info(
            "dw_work run requested; no workflow engine is wired",
            extra={"work_item_id": str(claimed.item.id), "run_id": str(claimed.run_id)},
        )


def build_dw_work_consumer(
    queue: WorkQueue, starter: DigitalWorkerRunStarter
) -> Callable[[], Awaitable[None]]:
    async def consume() -> None:
        for scope in await queue.due_scopes(limit=SCOPES_PER_PASS):
            try:
                released = await queue.release_stuck(scope)
                if released:
                    _LOG.info("dw_work returned stuck claims", extra={"count": released})
                for claimed in await queue.claim_for_lane(scope, limit=CLAIMS_PER_SCOPE):
                    await _start(queue, starter, claimed)
            except Exception:
                _LOG.exception("dw_work scope failed", extra={"tenant_id": str(scope.tenant_id)})

    return consume


async def _start(queue: WorkQueue, starter: DigitalWorkerRunStarter, claimed: Claimed) -> None:
    item = claimed.item
    scope_of = _scope_of(claimed)
    try:
        await starter.start(claimed)
    except QuotaExceededError:
        await queue.release_for_limit(scope_of, item.id)
    except ConflictError:
        # The run with this id exists: started before, by a pass that lost
        # its answer. The item stays with it.
        _LOG.info("dw_work run already exists", extra={"run_id": str(claimed.run_id)})
    except InfrastructureError:
        _LOG.exception("dw_work start failed; the claim returns in 15 minutes")
    except DWError as refused:
        code = refused.details.get("reason_code", refused.code)
        await queue.fail_start(scope_of, item.id, str(code))


def _scope_of(claimed: Claimed) -> WorkScope:
    return WorkScope(tenant_id=claimed.item.tenant_id, workspace_id=claimed.item.workspace_id)
