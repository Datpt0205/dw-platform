"""A switch's changes, carried out (agent-lifecycle R7.10, R7.11, R8.2, R8.6,
R8.10; ADR-0120 decision 7; D11).

Two kinds of event, each under its own type at the composition root:

- **A decided lift** (`studio.lifecycle.unfreeze.decided`,
  `studio.lifecycle.revive.decided`): the approval flow announces every
  run-less decision on the outbox, and `build_lift_handler` asks the
  `SwitchLiftSettler` of that type to lift the one switch the request names,
  `lift_approval_id` written, auditing the lift in the decider's name. A
  redelivered decision, a rejection and a switch already lifted end without
  error and write nothing, so the outbox does not retry them and a redelivery
  never meets the trigger's refusal.
- **A kill's change** (`control.switch.changed`): `build_switch_changed_handler`
  hands it to the `control_switch` lane, which cancels the component's parked
  runs and their approvals (`dw_agent_runtime.control_switch_lane`). A lift's
  event, or a switch that is gone, ends with nothing changed; a cancel hook
  that raises fails the event, which the outbox delivers again.

Tenancy comes from the envelope; what was decided or set, and by whom, from
the rows, which each reads itself in its own transaction. An event that is
not there or does not parse raises `UndeliverableEventError`: it does not
change on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.application.control_switches import (
    CONTROL_SWITCH_CHANGED,
    LIFECYCLE_REVIVE_DECIDED,
    LIFECYCLE_UNFREEZE_DECIDED,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = [
    "CONTROL_SWITCH_CHANGED",
    "LIFECYCLE_REVIVE_DECIDED",
    "LIFECYCLE_UNFREEZE_DECIDED",
    "ControlSwitchLanePort",
    "LiftSettlerPort",
    "build_lift_handler",
    "build_switch_changed_handler",
]


class LiftSettlerPort(Protocol):
    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> str: ...


class ControlSwitchLanePort(Protocol):
    async def handle(self, tenant_id: uuid.UUID, switch_id: uuid.UUID) -> int: ...


class _DecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


class _ChangedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    switch_id: uuid.UUID


def build_lift_handler(service: LiftSettlerPort, noun: str) -> EventHandler:
    """The handler to wire under a lift's `.decided` type; `noun` names what
    it lifts in the outcome it reports."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _DecidedPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        scope = WorkScope(tenant_id=event.tenant_id.value, workspace_id=event.workspace_id.value)
        try:
            outcome = await service.settle(scope, payload.approval_id)
        except NotFoundError as exc:
            raise UndeliverableEventError(f"refused: {exc.message} {exc.details}") from exc
        return f"{noun} {outcome}"

    return handle


def build_switch_changed_handler(lane: ControlSwitchLanePort) -> EventHandler:
    """The handler to wire under `CONTROL_SWITCH_CHANGED`. The tenant is the
    envelope's, never the payload's."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _ChangedPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        cancelled = await lane.handle(event.tenant_id.value, payload.switch_id)
        return f"{cancelled} runs cancelled"

    return handle
