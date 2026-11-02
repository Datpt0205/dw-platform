"""A tenant whose owners fell below two, told to the people who can fix it
(tenant-rbac R3.12; H-15).

`platform.check_owner_coverage` writes one `platform.tenant.owner_coverage_low`
event the moment fewer than two active people hold `platform.roles.write` or
`studio.publish.approve`, and only when the tenant's
`owner_coverage_low_since` was empty, so a fall announces once however many
writes follow it. This handler sends one in-app notification to each holder of
`platform.members.write` at tenant depth, in the workspace that anchors their
holding (a recipient need not be a member of `main`), through
`platform.deliver_notification`, the inbox's one door.

At least once, like every handler here: the `source_key` carries the tenant
and the fall's timestamp from the event, so a redelivered event adds nothing,
and the next fall (a new timestamp) is a new notification. The tenant comes
from the event's envelope, which the database tagged.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_platform.adapters.persistence.tenant_session import TenantScope
from dw_platform.domain.outbox import OutboxEvent
from dw_worker.consumers.outbox import EventHandler, UndeliverableEventError

OWNER_COVERAGE_LOW = "platform.tenant.owner_coverage_low"
# Who is told: whoever may manage the company's members, at tenant depth.
_RECIPIENT_KEY = "platform.members.write"
_TITLE = "Công ty còn dưới hai người giữ quyền chủ"
_BODY = (
    "Số người giữ quyền quản trị vai trò hoặc duyệt phát hành đã xuống dưới hai. "
    "Hãy giao thêm người để mọi thay đổi vẫn có người thứ hai xác nhận."
)
_LINK = "/admin/members"

__all__ = ["OWNER_COVERAGE_LOW", "build_owner_coverage_handler"]


class TenantDepthHoldersPort(Protocol):
    async def tenant_depth_holders(
        self, tenant_id: uuid.UUID, key: str
    ) -> dict[uuid.UUID, list[uuid.UUID]]: ...


class ScopedDeliveryPort(Protocol):
    async def deliver_in(
        self,
        scope: TenantScope,
        *,
        recipients: Sequence[uuid.UUID],
        source_key: str,
        title: str,
        body: str,
        link: str | None,
    ) -> None: ...


class _CoverageLowPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: uuid.UUID
    keys: list[str]
    owner_coverage_low_since: datetime


def build_owner_coverage_handler(
    holders: TenantDepthHoldersPort, notifications: ScopedDeliveryPort
) -> EventHandler:
    """The handler to wire under `OWNER_COVERAGE_LOW`."""

    async def handle(event: OutboxEvent) -> str:
        try:
            payload = _CoverageLowPayload.model_validate(event.payload)
        except ValidationError as exc:
            raise UndeliverableEventError(f"payload does not parse: {exc}") from exc
        tenant_id = event.tenant_id.value
        if payload.tenant_id != tenant_id:
            raise UndeliverableEventError("the payload names another tenant than its envelope")
        source_key = (
            f"{OWNER_COVERAGE_LOW}:{tenant_id}:{payload.owner_coverage_low_since.isoformat()}"
        )
        by_workspace = await holders.tenant_depth_holders(tenant_id, _RECIPIENT_KEY)
        for workspace_id, recipients in sorted(by_workspace.items(), key=lambda i: str(i[0])):
            await notifications.deliver_in(
                TenantScope(tenant_id=tenant_id, workspace_id=workspace_id),
                recipients=recipients,
                source_key=source_key,
                title=_TITLE,
                body=_BODY,
                link=_LINK,
            )
        told = sum(len(people) for people in by_workspace.values())
        return f"owner coverage low ({', '.join(payload.keys)}): {told} told"

    return handle
