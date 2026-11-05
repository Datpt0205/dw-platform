"""The `studio_runs` and `studio_run_reaper` lanes (workflow-engine/04: R5.1-R5.8,
R5.23; ADR-0113 decisions 2, 3).

`StudioRunsLane` is one tick of the worker's `studio_runs` lane: the tenants
with due work, the longest waiting first (`StudioRunQueuePort.scopes_due`),
each given at most `ceil(free / tenants)` claims, so one tenant's backlog
never starves another's (R5.2). A process runs at most `BATCH` runs at once;
each claimed run runs in a task of its own with its heartbeat started at the
claim, so the last run of a batch does not lose its lease waiting on the
first (R5.6). A heartbeat that finds the claim gone stops the run (R5.5).
`close` is the orderly shutdown: the runs still running are stopped and their
claims handed back, `attempt` unchanged, so a deploy is not a crash.

`StudioRunReaper` is one tick of `studio_run_reaper`: first every unfinished
run past its deadline that no live claim holds, and every run never admitted
in `RUN_DEADLINE`, ended `cancelled` `deadline_exceeded` (R5.23); then every
`running` run whose claim lapsed (a dead worker) queued again with `attempt +
1` after `studio_backoff`, or dead-lettered once it was queued again
`MAX_REQUEUES` times (R5.6, R5.7). `attempt` moves here and nowhere else, so a
run that waits on many approvals is never dead-lettered for it.

The run itself is `LangGraphWorkflowRunner.run_studio`'s: dispatch, the
graph, the end. Polled by the worker's `ConsumerRegistry`; no `NOTIFY`
(`dw_run_state` is workflow-engine's W2 row).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final, Protocol
from uuid import UUID

from dw_agent_runtime.ports import StudioClaim, StudioLeaseLostError, StudioRunQueuePort
from dw_agent_runtime.studio_dispatch import RUN_DEADLINE

logger = logging.getLogger(__name__)

__all__ = [
    "BATCH",
    "CLAIM_LEASE",
    "HEARTBEAT_SECONDS",
    "LANE",
    "LANE_INTERVAL_SECONDS",
    "MAX_REQUEUES",
    "REAPER_INTERVAL_SECONDS",
    "REAPER_LANE",
    "StudioRunReaper",
    "StudioRunner",
    "StudioRunsLane",
    "studio_backoff",
]

LANE: Final = "studio_runs"
REAPER_LANE: Final = "studio_run_reaper"
# Runs one process runs at once (the batch of a tick).
BATCH: Final = 8
# The claim's lease and its heartbeat (ADR-0113 decision 3).
CLAIM_LEASE: Final = timedelta(seconds=60)
HEARTBEAT_SECONDS: Final = 15.0
# How often each lane ticks. A dead worker's run is taken again within
# `CLAIM_LEASE` + `REAPER_INTERVAL_SECONDS` + the first backoff (at most 6 s)
# + `LANE_INTERVAL_SECONDS`: 82 s, inside R5.6's 90.
LANE_INTERVAL_SECONDS: Final = 1.0
REAPER_INTERVAL_SECONDS: Final = 15.0
# Queued again four times, a run that dies a fifth time is dead-lettered.
MAX_REQUEUES: Final = 4
# Tenants one reaper pass visits per sweep.
REAPER_TENANTS: Final = 100

_BACKOFF_BASE_SECONDS: Final = 5.0
_BACKOFF_CAP_SECONDS: Final = 600.0
_JITTER: Final = 0.2


def studio_backoff(attempt: int, *, jitter: Callable[[], float] = random.random) -> timedelta:
    """`min(2^attempt * 5 s, 10 min)` plus up to a fifth of it, so the runs
    of a worker that died together do not come back together."""
    base = min(2**attempt * _BACKOFF_BASE_SECONDS, _BACKOFF_CAP_SECONDS)
    return timedelta(seconds=base * (1 + _JITTER * jitter()))


class StudioRunner(Protocol):
    """What the lane runs a claimed run with (`LangGraphWorkflowRunner`)."""

    async def run_studio(self, *, tenant_id: UUID, run_id: UUID, lease_token: str) -> Any: ...


@dataclass
class StudioRunsLane:
    queue: StudioRunQueuePort
    runner: StudioRunner
    # This process's name in each claim's token (`<worker>:<uuid>`).
    worker: str
    batch: int = BATCH
    lease: timedelta = CLAIM_LEASE
    heartbeat_seconds: float = HEARTBEAT_SECONDS
    _running: dict[UUID, tuple[StudioClaim, asyncio.Task[None]]] = field(default_factory=dict)

    @property
    def running(self) -> int:
        return len(self._running)

    async def __call__(self) -> None:
        free = self.batch - len(self._running)
        if free <= 0:
            return
        tenants = await self.queue.scopes_due(free)
        if not tenants:
            return
        share = math.ceil(free / len(tenants))
        for tenant_id in tenants:
            if free <= 0:
                break
            claims = await self.queue.claim(
                tenant_id, limit=min(share, free), worker=self.worker, lease=self.lease
            )
            for claim in claims:
                self._start(claim)
            free -= len(claims)

    def _start(self, claim: StudioClaim) -> None:
        task = asyncio.create_task(self._run(claim), name=f"studio_run:{claim.run_id}")
        self._running[claim.run_id] = (claim, task)

        def forget(_: asyncio.Task[None]) -> None:
            held = self._running.get(claim.run_id)
            if held is not None and held[1] is task:
                del self._running[claim.run_id]

        task.add_done_callback(forget)

    async def _run(self, claim: StudioClaim) -> None:
        current = asyncio.current_task()
        assert current is not None
        beat = asyncio.create_task(self._beat(claim, current))
        try:
            await self.runner.run_studio(
                tenant_id=claim.tenant_id, run_id=claim.run_id, lease_token=claim.lease_token
            )
        except StudioLeaseLostError:
            logger.info("a Studio run's claim was taken over", extra={"run_id": str(claim.run_id)})
        except Exception:
            # The row stays `running` under this claim; with no heartbeat its
            # lease lapses and the reaper queues it again, as for a crash.
            logger.exception("a Studio run stopped", extra={"run_id": str(claim.run_id)})
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def _beat(self, claim: StudioClaim, run: asyncio.Task[None]) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                held = await self.queue.beat(claim, lease=self.lease)
            except Exception:
                # Retried at the next beat; a lease that lapses meanwhile is
                # the reaper's, and the run's next write finds the fence.
                logger.warning("a Studio run's heartbeat failed", exc_info=True)
                continue
            if not held:
                logger.warning("a Studio run's claim is gone; stopping it")
                run.cancel()
                return

    async def close(self) -> None:
        """Stop what runs and hand each claim back (`queued`, due now)."""
        running = list(self._running.values())
        for _, task in running:
            task.cancel()
        await asyncio.gather(*(task for _, task in running), return_exceptions=True)
        for claim, _ in running:
            try:
                await self.queue.release(claim)
            except Exception:
                logger.warning("a Studio run's claim was not handed back", exc_info=True)


@dataclass
class StudioRunReaper:
    queue: StudioRunQueuePort
    tenants: int = REAPER_TENANTS
    max_requeues: int = MAX_REQUEUES
    unclaimed_after: timedelta = RUN_DEADLINE
    backoff: Callable[[int], timedelta] = studio_backoff

    async def __call__(self) -> None:
        for tenant_id in await self.queue.deadlines_due(
            self.tenants, unclaimed_after=self.unclaimed_after
        ):
            try:
                await self.queue.cancel_overdue(tenant_id, unclaimed_after=self.unclaimed_after)
            except Exception:
                logger.exception("a tenant's overdue runs were not ended")
        for tenant_id in await self.queue.orphans_due(self.tenants):
            try:
                await self.queue.requeue_orphans(
                    tenant_id, max_requeues=self.max_requeues, backoff=self.backoff
                )
            except Exception:
                logger.exception("a tenant's orphaned runs were not queued again")
