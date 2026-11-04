"""A decided `studio.lifecycle.unfreeze` approval, carried out
(agent-lifecycle R7.10, R7.11; ADR-0120 decision 7; D11).

The approval flow announces every run-less decision on the outbox; for
`studio.lifecycle.unfreeze` this handler asks `UnfreezeSettler` to lift the
one freeze the request names, `lift_approval_id` written, auditing
`control.freeze.lifted` in the decider's name. Tenancy comes from the
envelope; what was decided, and by whom, from the approval row, which the
settlement reads itself in its own transaction.

At least once, like every handler here: a redelivered decision, a rejection
and a freeze already lifted end without error and write nothing, so the outbox
does not retry them and a redelivery never meets the trigger's refusal. An
approval that is not there raises `UndeliverableEventError`: it does not
change on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.application.control_switches import LIFECYCLE_UNFREEZE_DECIDED
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["LIFECYCLE_UNFREEZE_DECIDED", "UnfreezeSettlerPort", "build_unfreeze_handler"]


class UnfreezeSettlerPort(Protocol):
    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> str: ...


class _DecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_unfreeze_handler(service: UnfreezeSettlerPort) -> EventHandler:
    """The handler to wire under `LIFECYCLE_UNFREEZE_DECIDED`."""

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
        return f"freeze {outcome}"

    return handle
