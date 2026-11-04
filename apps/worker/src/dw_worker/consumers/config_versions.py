"""A decided `config.version` request, carried out (tenant-config R8.10, R8.11,
R8.15, R8.19; ADR-0110 decision 1; ADR-0011).

The approval flow announces every run-less decision on the outbox; for
`config.version` this handler asks `ConfigSettlement` to move the proposal to
`approved` (the key's previous version to `superseded`) or `rejected`, auditing
in the decider's name with `details.lane` `outbox`. Tenancy comes from the
envelope; what was decided, and by whom, from the approval's decision row,
which the settlement reads itself in its own transaction.

At least once: a redelivered decision, and a proposal its proposer withdrew
before the outbox reached it, end without error and write nothing, so the
outbox does not retry them. A request that is not there raises
`UndeliverableEventError`: it does not change on a retry.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_kernel.errors import NotFoundError
from dw_platform.application.config_versions import CONFIG_VERSION_DECIDED
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

__all__ = ["CONFIG_VERSION_DECIDED", "ConfigSettlementPort", "build_config_version_handler"]


class ConfigSettlementPort(Protocol):
    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> str: ...


class _DecidedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: uuid.UUID


def build_config_version_handler(service: ConfigSettlementPort) -> EventHandler:
    """The handler to wire under `CONFIG_VERSION_DECIDED`."""

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
        return f"config version {outcome}"

    return handle
