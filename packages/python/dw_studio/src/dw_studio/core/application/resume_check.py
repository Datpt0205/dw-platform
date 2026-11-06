"""`POST /api/v1/runs/{run_id}/resume-check` (workflow-engine R6.39, R6.22,
R6.23, R6.25, R6.16; WE53).

A Studio run left `blocked` `incompatible_resume` by the checks of a resume
(R6.8, R6.14) is checked again on a person's request, and queued when every
check passes; nothing is pinned again: what "fixes" a run is a build that
reads its `type@major` or format again, or a draft back to its pinned content.

In order, and nothing written before the first refusal:

1. the run, read under the caller's tenant (RLS) and only in a workspace
   `platform.workspace_reach` gives the caller with `runs.read`: another
   company's run, or one out of reach, is a 404 (R6.22);
2. the key `studio.workflows.resume_check`, at the run's workspace by depth:
   403 without it (R6.23);
3. a run that is not a Studio run `blocked` `incompatible_resume` (an
   `empty_resume`, a run of no manifest) is 409 `run_not_resumable`: such a
   run would only block again;
4. past `deadline_at`: the run is `cancelled` `deadline_exceeded`, never
   queued (R6.16), and the answer says so;
5. `RunControlPort`: a freeze, a kill, an unreadable switch state, an
   inactive principal or company is 409 with its reason (R6.25);
6. the draft check (R6.14) and the five checks of R6.7: one still failing is
   409 `incompatible_resume`;
7. `queued` by a write `WHERE status = 'blocked'` (0 rows: 409), with exactly
   one audit `run.unblocked` in the caller's name, one transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

from dw_agent_runtime.ports import StudioRun
from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import permission_denied
from dw_platform.application.effect_keys import PendingEffect

RESUME_CHECK: Final = "studio.workflows.resume_check"
RUNS_READ: Final = "runs.read"
INCOMPATIBLE_RESUME: Final = "incompatible_resume"
UNBLOCKED: Final = "run.unblocked"


@dataclass(frozen=True, slots=True)
class BlockedRun:
    """A run as the resume check reads it: its row, whether the caller holds
    the key at its workspace, and the run as the runner would take it (None
    when its draft changed since it was pinned, R6.14)."""

    run_id: uuid.UUID
    workspace_id: uuid.UUID
    status: str
    error_code: str | None
    deadline_at: datetime | None
    may_check: bool
    run: StudioRun | None


class ResumeCheckStorePort(Protocol):
    async def read(self, context: AccessContext, run_id: uuid.UUID) -> BlockedRun | None:
        """The Studio run under the caller's tenant, in a workspace the
        caller reaches with `runs.read`; None otherwise."""
        ...

    async def unblock(
        self, context: AccessContext, run_id: uuid.UUID, *, effect: PendingEffect | None
    ) -> bool:
        """`blocked` -> `queued`, due now, with audit `run.unblocked` in the
        caller's name, in one transaction; False when it was not blocked."""
        ...

    async def cancel_overdue(
        self, context: AccessContext, run_id: uuid.UUID, *, effect: PendingEffect | None
    ) -> bool:
        """`blocked` -> `cancelled` `deadline_exceeded`, with audit
        `run.deadline_exceeded` in the caller's name, in one transaction."""
        ...


class ResumeRuntimePort(Protocol):
    """What only the runtime can say of a run: its switches (raises
    `RunHaltedError`) and the five checks on its checkpoint."""

    async def require_open(self, run: StudioRun) -> None: ...

    async def failed_checks(self, run: StudioRun) -> tuple[str, ...]:
        """The checks of R6.7 the run fails now (`a`-`e`), and `empty_resume`
        when it has nothing to resume with; empty when it may go on."""
        ...


@dataclass(frozen=True, slots=True)
class ResumeCheckResult:
    run_id: uuid.UUID
    status: Literal["queued", "cancelled"]


def _not_resumable(run_id: uuid.UUID, status: str) -> ConflictError:
    return ConflictError(
        "only a run blocked by its resume checks is checked again",
        details={"reason_code": "run_not_resumable", "run_id": str(run_id), "status": status},
    )


def _incompatible(run_id: uuid.UUID, checks: tuple[str, ...]) -> ConflictError:
    return ConflictError(
        "the run still fails its resume checks",
        details={"reason_code": INCOMPATIBLE_RESUME, "run_id": str(run_id), "checks": list(checks)},
    )


@dataclass(frozen=True)
class ResumeCheckService:
    store: ResumeCheckStorePort
    runtime: ResumeRuntimePort
    clock: UtcClock

    async def authorize(self, context: AccessContext, run_id: uuid.UUID) -> BlockedRun:
        """404 for a run the caller cannot see, 403 without the key at its
        workspace: what the route's idempotency asks before any key row."""
        found = await self.store.read(context, run_id)
        if found is None:
            raise NotFoundError("run not found", details={"run_id": str(run_id)})
        if not found.may_check:
            raise permission_denied(
                action=RESUME_CHECK, resource_type="worker_run", resource_id=str(run_id)
            )
        return found

    async def check(
        self, context: AccessContext, run_id: uuid.UUID, *, effect: PendingEffect | None = None
    ) -> ResumeCheckResult:
        found = await self.authorize(context, run_id)
        if found.status != "blocked" or found.error_code != INCOMPATIBLE_RESUME:
            raise _not_resumable(run_id, found.status)
        if found.deadline_at is not None and self.clock.now() >= found.deadline_at:
            if not await self.store.cancel_overdue(context, run_id, effect=effect):
                raise _not_resumable(run_id, found.status)
            return ResumeCheckResult(run_id, "cancelled")
        if found.run is None:
            raise _incompatible(run_id, ("draft_changed",))
        await self.runtime.require_open(found.run)
        failed = await self.runtime.failed_checks(found.run)
        if failed:
            # An empty resume would only block again (R6.5): refused here too.
            raise _incompatible(run_id, failed)
        if not await self.store.unblock(context, run_id, effect=effect):
            raise _not_resumable(run_id, found.status)
        return ResumeCheckResult(run_id, "queued")
