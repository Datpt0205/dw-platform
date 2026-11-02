"""A decided publication of a Digital Worker's workflow draft, carried out
(wf-ai R6.5, R6.6, R6.11, R6.14).

The approval flow announces every run-less decision on the outbox; for
`dw.workflow.publish` this handler asks `PublishSettler.settle_publish` to
publish the approved content as the DW's next `+t<n>` version, or to return
the draft with the reason it no longer applies. Tenancy comes from the
envelope; what was decided, and by whom, from the approval row, which the
settler reads itself in the settlement's transaction.

At least once, like every handler here: a redelivered decision finds its
version already written, or no draft waiting on it, and changes nothing. An
approval that is not there, or names a DW that is gone, raises
`UndeliverableEventError`: neither changes on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_agent_runtime.wflite.publish import DW_WORKFLOW_PUBLISH_DECIDED, PublishSettlement
from dw_kernel.errors import NotFoundError
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["DW_WORKFLOW_PUBLISH_DECIDED", "PublishSettlerPort", "build_publish_handler"]


class PublishSettlerPort(Protocol):
    async def settle_publish(
        self, scope: WorkScope, approval_id: uuid.UUID
    ) -> PublishSettlement: ...


class _PublishDecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_publish_handler(service: PublishSettlerPort) -> EventHandler:
    """The handler to wire under `DW_WORKFLOW_PUBLISH_DECIDED`."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _PublishDecidedPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        scope = WorkScope(tenant_id=event.tenant_id.value, workspace_id=event.workspace_id.value)
        try:
            settled = await service.settle_publish(scope, payload.approval_id)
        except NotFoundError as exc:
            raise UndeliverableEventError(f"refused: {exc.message} {exc.details}") from exc
        return f"dw workflow publish {settled.outcome}"

    return handle
