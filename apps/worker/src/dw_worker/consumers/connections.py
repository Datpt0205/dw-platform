"""A decided `connections.enable` approval, carried out
(connections-and-vault R5.12, R5.19; ADR-0115 decision 2; D11).

The approval flow announces every run-less decision on the outbox; for
`connections.enable` this handler asks `ConnectionEnableSettler` to move the
connection from `disabled` to `active` under the approval's id, auditing
`connection.enabled` in the decider's name. Tenancy comes from the envelope;
what was decided, and by whom, from the approval row, which the settlement
reads itself in its own transaction.

At least once, like every handler here: a redelivered decision, a rejection, a
connection deleted or no longer disabled, and a request opened before the
connection's latest disable all end without error and write nothing, so the
outbox does not retry them. An approval that is not there raises
`UndeliverableEventError`: it does not change on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.application.connection_admin import CONNECTIONS_ENABLE_DECIDED
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["CONNECTIONS_ENABLE_DECIDED", "ConnectionEnableSettlerPort", "build_enable_handler"]


class ConnectionEnableSettlerPort(Protocol):
    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> str: ...


class _DecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_enable_handler(service: ConnectionEnableSettlerPort) -> EventHandler:
    """The handler to wire under `CONNECTIONS_ENABLE_DECIDED`."""

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
        return f"connection enable {outcome}"

    return handle
