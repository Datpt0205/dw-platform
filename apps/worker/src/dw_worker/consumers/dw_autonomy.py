"""A decided raise of a Digital Worker's earned level, carried out
(digital-worker R8.6).

The approval flow announces every run-less decision on the outbox; for
`dw.autonomy.raise` this handler asks `DwAutonomyService.settle_raise` to write
the raised level, or to record why it no longer applies. Tenancy comes from
the envelope; what was decided, and by whom, from the approval row, which the
service reads itself in the settlement's transaction.

At least once, like every handler here: a redelivered approval finds the class
already at its new level and changes nothing. An approval that is not there,
or names a class that is gone, raises `UndeliverableEventError`: neither
changes on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.application.dw_autonomy import DW_AUTONOMY_RAISE_DECIDED, RaiseSettlement
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["DW_AUTONOMY_RAISE_DECIDED", "RaiseSettlerPort", "build_raise_handler"]


class RaiseSettlerPort(Protocol):
    async def settle_raise(self, scope: WorkScope, approval_id: uuid.UUID) -> RaiseSettlement: ...


class _RaiseDecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_raise_handler(service: RaiseSettlerPort) -> EventHandler:
    """The handler to wire under `DW_AUTONOMY_RAISE_DECIDED`."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _RaiseDecidedPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        scope = WorkScope(tenant_id=event.tenant_id.value, workspace_id=event.workspace_id.value)
        try:
            settled = await service.settle_raise(scope, payload.approval_id)
        except NotFoundError as exc:
            raise UndeliverableEventError(f"refused: {exc.message} {exc.details}") from exc
        return f"dw autonomy raise {settled.outcome}"

    return handle
