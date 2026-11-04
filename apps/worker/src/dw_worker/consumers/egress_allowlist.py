"""A decided `egress.allowed_host` approval, carried out
(connections-and-vault R3.11; ADR-0115 decision 6).

The approval flow announces every run-less decision on the outbox; for
`egress.allowed_host` this handler asks `AllowedHostSettler` to insert the row
whose id is the approval's, `ON CONFLICT DO NOTHING`, auditing only a row that
is new. Tenancy comes from the envelope; what was decided, and by whom, from
the approval row, which the settlement reads itself in its own transaction.

At least once, like every handler here: a redelivered decision, a decision
replayed after its row was removed, and a second approval of a pattern already
live all end without error and write nothing, so the outbox does not retry
them. An approval that is not there raises `UndeliverableEventError`: it does
not change on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.application.egress_allowlist import (
    EGRESS_ALLOWED_HOST_DECIDED,
    AllowedHostSettlement,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["EGRESS_ALLOWED_HOST_DECIDED", "AllowedHostSettlerPort", "build_allowed_host_handler"]


class AllowedHostSettlerPort(Protocol):
    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> AllowedHostSettlement: ...


class _DecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_allowed_host_handler(service: AllowedHostSettlerPort) -> EventHandler:
    """The handler to wire under `EGRESS_ALLOWED_HOST_DECIDED`."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _DecidedPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        scope = WorkScope(tenant_id=event.tenant_id.value, workspace_id=event.workspace_id.value)
        try:
            settled = await service.settle(scope, payload.approval_id)
        except NotFoundError as exc:
            raise UndeliverableEventError(f"refused: {exc.message} {exc.details}") from exc
        return f"egress allowed host {settled.outcome}"

    return handle
