"""The `control_switch` lane: a kill carried out on the runs it holds
(agent-lifecycle R8.2, R8.3, R8.10; ADR-0120 decisions 5, 7; ADR-0113
decision 4; DO-28 C).

The worker's outbox hands it every `control.switch.changed` (`{tenant_id,
switch_id}`). It reads the switch by id under the company's RLS: a row lifted,
gone or not a kill ends the event with nothing changed, which is also what a
lift's event finds. A kill still open cancels every run of the component that
is parked, `waiting_approval`, `waiting_timer`, `waiting` or `queued`, and
not `simulate` (R8.1: a kill never stops a simulation, so a fix can be
evaluated), each in a transaction of its own:

1. the run is read again `FOR UPDATE` and must still be parked, and the kill
   still open (read `FOR SHARE`, so a revive waits for this cancel or this
   cancel sees the revive);
2. each `pending` approval of the run is cancelled (`ApprovalRequest.cancel()`)
   and audited `approval.cancelled`; a request already decided is left as it
   is, since `decide` commits the decision before it resumes, and that resume
   meets a run no longer waiting (409, R8.3);
3. every registered `RunCancelHook` is called, in this transaction;
4. the run is set `cancelled` with `error.code` `artifact_killed`, audited
   `run.cancelled`.

Each audit row names the person who set the kill and `details.lane`
`control_switch`: the lane carries out that person's decision (CLAUDE.md,
Agent and tool rules; ADR-0011). A hook that raises rolls its run back and
the event fails, so the outbox delivers it again; runs already cancelled are
no longer parked and are not touched twice.

A run that is running is not this lane's: its next door refuses it
(`RunControlPort`, `artifact_killed`). Nor is a parent run paused on a linked
agent that was killed: its `resume` door refuses it when it goes on. The
triggers of the component are not touched either: they ask `admission_state`
and record `refused_killed` while the kill holds (workflow-triggers R1.4), so
a revive reopens them with nothing to undo.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from dw_agent_runtime.ports import RunCancelHook, RunCancelUnit
from dw_agent_runtime.run_control import HaltReason
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent

__all__ = [
    "APPROVAL_CANCELLED",
    "LANE",
    "PARKED_STATUSES",
    "RUN_CANCELLED",
    "ControlSwitchLane",
    "KillCancelTx",
    "KilledRunsPort",
    "OpenKillOfRuns",
    "ParkedRun",
    "RunCancelHooks",
]

LANE: Final = "control_switch"
APPROVAL_CANCELLED: Final = "approval.cancelled"
RUN_CANCELLED: Final = "run.cancelled"

# Where a run waits without running (`RunStatus`): for a person, a timer, a
# Studio wait (`outcome_review` and an incident are `waiting`, workflow-engine)
# or its turn in the queue. A kill keeps none of them (DO-28 C).
PARKED_STATUSES: Final = frozenset({"waiting_approval", "waiting_timer", "waiting", "queued"})


@dataclass(frozen=True, slots=True)
class OpenKillOfRuns:
    """The open kill an event names, as the lane needs it."""

    switch_id: uuid.UUID
    target_id: uuid.UUID
    set_by: uuid.UUID


@dataclass(frozen=True, slots=True)
class ParkedRun:
    """A run of the killed component, still parked when read again."""

    run_id: uuid.UUID
    workspace_id: uuid.UUID


class KillCancelTx(RunCancelUnit, Protocol):
    """One run's cancel, in one transaction under the run's tenant; the unit
    every hook is handed."""

    async def kill_open(self, switch_id: uuid.UUID) -> bool:
        """Whether the kill is still open, read `FOR SHARE`."""
        ...

    async def parked(self, run_id: uuid.UUID) -> ParkedRun | None:
        """The run `FOR UPDATE`, when still parked and not `simulate`."""
        ...

    async def pending_approvals(self, run_id: uuid.UUID) -> list[ApprovalRequest]:
        """The run's `pending` requests, `FOR UPDATE`."""
        ...

    async def save_approval(self, request: ApprovalRequest) -> None:
        """The request's new status, by its version."""
        ...

    async def cancel(self, run_id: uuid.UUID, *, switch_id: uuid.UUID) -> None:
        """The run `cancelled`, `error` `{code: artifact_killed, switch_id}`."""
        ...


class KilledRunsPort(Protocol):
    async def open_kill(self, tenant_id: uuid.UUID, switch_id: uuid.UUID) -> OpenKillOfRuns | None:
        """The switch when it is an open kill; None when lifted, gone or a
        freeze."""
        ...

    async def parked_runs(self, tenant_id: uuid.UUID, target_id: uuid.UUID) -> list[uuid.UUID]:
        """The component's parked runs that are not `simulate`, oldest first."""
        ...

    def transaction(self, tenant_id: uuid.UUID) -> AbstractAsyncContextManager[KillCancelTx]:
        """Commits on a clean exit, rolls back on an exception."""
        ...


class RunCancelHooks:
    """The hooks the lane calls for each run it cancels, by name, built at
    the worker's composition root as `ConsumerRegistry` is, and frozen there:
    a hook joins with one `register` line, none by default (R8.10)."""

    def __init__(self) -> None:
        self._hooks: dict[str, RunCancelHook] = {}
        self._frozen = False

    def register(self, name: str, hook: RunCancelHook) -> None:
        if self._frozen:
            raise RuntimeError("run cancel hooks are frozen")
        if name in self._hooks:
            raise ValueError(f"run cancel hook {name!r} is registered twice")
        self._hooks[name] = hook

    def freeze(self) -> RunCancelHooks:
        self._frozen = True
        return self

    def names(self) -> list[str]:
        return list(self._hooks)

    def hooks(self) -> Sequence[RunCancelHook]:
        return tuple(self._hooks.values())


@dataclass(frozen=True)
class ControlSwitchLane:
    store: KilledRunsPort
    hooks: RunCancelHooks
    clock: UtcClock
    ids: IdGenerator

    async def handle(self, tenant_id: uuid.UUID, switch_id: uuid.UUID) -> int:
        """Carry out the switch an event names; the runs cancelled."""
        kill = await self.store.open_kill(tenant_id, switch_id)
        if kill is None:
            return 0
        cancelled = 0
        for run_id in await self.store.parked_runs(tenant_id, kill.target_id):
            if await self._cancel(tenant_id, kill, run_id):
                cancelled += 1
        return cancelled

    async def _cancel(self, tenant_id: uuid.UUID, kill: OpenKillOfRuns, run_id: uuid.UUID) -> bool:
        async with self.store.transaction(tenant_id) as tx:
            run = await tx.parked(run_id)
            if run is None or not await tx.kill_open(kill.switch_id):
                # Moved on since it was listed, or revived meanwhile.
                return False
            now = self.clock.now()
            for request in await tx.pending_approvals(run_id):
                request.cancel()
                await tx.save_approval(request)
                await tx.audit(
                    self._event(
                        tenant_id,
                        request.workspace_id.value,
                        kill,
                        APPROVAL_CANCELLED,
                        "approval_request",
                        request.id,
                        now,
                        {"run_id": str(run_id), "approval_type": request.approval_type},
                        run_id,
                    )
                )
            for hook in self.hooks.hooks():
                await hook.on_cancel(tx, run_id, actor=kill.set_by, lane=LANE)
            await tx.cancel(run_id, switch_id=kill.switch_id)
            await tx.audit(
                self._event(
                    tenant_id,
                    run.workspace_id,
                    kill,
                    RUN_CANCELLED,
                    "worker_run",
                    run_id,
                    now,
                    {"reason_code": HaltReason.ARTIFACT_KILLED.value},
                    run_id,
                )
            )
        return True

    def _event(
        self,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        kill: OpenKillOfRuns,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID,
        at: datetime,
        details: dict[str, object],
        run_id: uuid.UUID,
    ) -> AuditEvent:
        return AuditEvent(
            id=self.ids.new_uuid(),
            tenant_id=TenantId(tenant_id),
            workspace_id=WorkspaceId(workspace_id),
            # The person whose kill this lane carries out (ADR-0011).
            actor_id=UserId(kill.set_by),
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            occurred_at=at,
            details={**details, "switch_id": str(kill.switch_id), "lane": LANE},
            run_id=run_id,
        )
