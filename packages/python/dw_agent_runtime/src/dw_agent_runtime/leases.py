"""Holding a lease while work spends against it (usage-and-limits R5.9, R6.1,
R6.2; ADR-0121 decision 5).

Two holders, one shape: a run, held by the runner for as long as this process
runs one of its tree, and an operation outside any run (an ingestion, a
retrieval, a builder's assistance), held by whoever does it through
`held_operation`. Both beat the lease every 60 seconds with `beating`, so a
long one is not taken for a dead process, and both make it the lease in force
(`dw_kernel.limits.spending_under`) for the model doors that take no run
context, an embedding and a rerank, which refuse without one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Final, Literal
from uuid import UUID

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import LimitsPort, OperationPurpose, RunLease
from dw_kernel.limits import LeaseInForce, spending_under

__all__ = ["LEASE_BEAT_SECONDS", "beating", "held_operation", "run_holder"]

logger = logging.getLogger("dw_agent_runtime.leases")

# How often a held lease is beaten (R5.9): well inside its 300 s TTL.
LEASE_BEAT_SECONDS: Final = 60.0


def run_holder(run_context: RunContext) -> LeaseInForce:
    """The lease in force while a run runs: its tree's, named for its usage
    records the way the ledger names a run's chat calls."""
    service = run_context.run_as_principal_id is not None
    return LeaseInForce(
        tenant_id=run_context.tenant_id,
        workspace_id=run_context.workspace_id,
        lease_root=run_context.lease_root,
        run_id=run_context.run_id,
        purpose="run",
        actor_id=None if service else run_context.actor_id,
        actor_kind="service" if service else "user",
        cost_ceiling_usd=run_context.cost_ceiling_usd,
    )


@contextlib.asynccontextmanager
async def beating(
    lease: RunLease, every_seconds: float = LEASE_BEAT_SECONDS
) -> AsyncIterator[None]:
    """The lease's heartbeat for as long as the block runs (R5.9): stopped on
    every way out, so finished work beats nothing."""
    task = asyncio.create_task(_beat(lease, every_seconds))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _beat(lease: RunLease, every_seconds: float) -> None:
    while True:
        await asyncio.sleep(every_seconds)
        try:
            if not await lease.beat():
                return
        except Exception:
            # A missed beat is retried on the next; five missed in a row and
            # the reaper settles the lease as if the process had died.
            logger.warning("a lease heartbeat failed", exc_info=True)


@contextlib.asynccontextmanager
async def held_operation(
    limits: LimitsPort,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    purpose: OperationPurpose,
    operation_id: UUID,
    actor_id: UUID | None,
    actor_kind: Literal["user", "service", "system"] = "user",
    every_seconds: float = LEASE_BEAT_SECONDS,
) -> AsyncIterator[RunLease]:
    """An operation's lease for the block (R6.2): admitted first, so a refusal
    (`LimitExceededError`, with `resets_at`) leaves before any model is
    called; in force and beaten while the block runs; released after it,
    `completed` or `failed` as the block ended. A release that fails is logged:
    the lease expires and the reaper settles it (R5.4)."""
    lease = await limits.admit_operation(
        tenant_id=tenant_id, workspace_id=workspace_id, purpose=purpose, operation_id=operation_id
    )
    holder = LeaseInForce(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        lease_root=operation_id,
        run_id=None,
        purpose=purpose,
        actor_id=actor_id,
        actor_kind=actor_kind,
    )
    reason = "failed"
    try:
        with spending_under(holder):
            async with beating(lease, every_seconds):
                yield lease
        reason = "completed"
    finally:
        try:
            await lease.release(reason)
        except Exception:
            logger.exception(
                "could not release an operation's lease", extra={"operation_id": str(operation_id)}
            )
