"""A decided Studio publish request, carried out (agent-lifecycle R5.5, R5.9,
R5.10, R7.12; ADR-0120 decisions 1-2; ADR-0011).

The approval flow announces every run-less decision on the outbox; for
`studio.publish.<kind>` this handler asks `PublishSettler` to take the version
live or back to its draft, in the decider's name with `details.lane`
`outbox`. One handler, registered under the `.decided` type of every kind of
the worker's `ArtifactKindRegistry` (`register_studio_publish` in
`dw_worker.main`), never a list written by hand. Tenancy comes from the
envelope; what was decided, and by whom, from the rows the settler reads in
its own transaction.

At least once: a redelivered decision, and a version withdrawn or settled
before the outbox reached it, end without error and write nothing. A read
that fails raises and the outbox delivers again. A request that is not there
raises `UndeliverableEventError`: it does not change on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["PublishSettlerPort", "build_publish_decided_handler"]


class PublishSettlerPort(Protocol):
    async def settle(self, tenant_id: uuid.UUID, approval_id: uuid.UUID) -> str: ...


class _DecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_publish_decided_handler(settler: PublishSettlerPort) -> EventHandler:
    """The handler to wire under each `studio.publish.<kind>.decided`. The
    tenant is the envelope's, never the payload's."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _DecidedPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        try:
            outcome = await settler.settle(event.tenant_id.value, payload.approval_id)
        except NotFoundError as exc:
            raise UndeliverableEventError(f"refused: {exc.message} {exc.details}") from exc
        return f"studio publish {outcome}"

    return handle
