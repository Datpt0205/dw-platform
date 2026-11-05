"""Who is told that a trigger's Studio runs are held, and once per change
(workflow-engine R5.20, R5.21; ADR-0113 decision 3; V4.15, V4.16).

Satisfies `dw_agent_runtime.ports.HeldRunAlertPort` without importing it. The
`studio_runs` lane names the run's tenant, workspace and run-as principal;
this adapter reads the rest and builds each notice's `source_key` from the
change itself, so many held runs over many cycles tell each person once, and
the next change tells them again:

- an inactive service account: `studio.run.principal_inactive:<principal>:
  <status_changed_at>`, the member row's own timestamp (org-and-principals/02),
  to every active person holding `platform.members.write` at tenant depth, in
  the workspace their holding is anchored at (`tenant_depth_holders`);
- a binding to approve again: `studio.run.binding_needs_review:<artifact>:
  <principal>:<grants_changed_at>`, to every member of the run's workspace
  holding `studio.bindings.approve` there (`holding`).

Delivered through `platform.deliver_notification`, whose UNIQUE
`(recipient_user_id, source_key)` turns a repeat into nothing and drops a
recipient who is not a member of the workspace it is sent in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.notifications import SqlNotificationRepository
from dw_platform.adapters.persistence.scope_holders import SqlScopeHolders
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

__all__ = ["SqlHeldRunAlerts"]

MEMBERS_WRITE: Final = "platform.members.write"
BINDINGS_APPROVE: Final = "studio.bindings.approve"
# Where each reader lifts the hold: the members screen, the workflows screen.
_MEMBERS_LINK: Final = "/admin/members"
_WORKFLOWS_LINK: Final = "/studio/workflows"
_INACTIVE_TITLE: Final = "Lượt chạy đang chờ vì tài khoản dịch vụ không hoạt động"
_INACTIVE_BODY: Final = (
    "Tài khoản dịch vụ chạy các lượt do trình kích hoạt xin đã ngừng hoạt động. "
    "Các lượt đó được giữ trong hàng chờ và sẽ chạy theo thứ tự khi tài khoản hoạt động lại."
)
_REVIEW_TITLE: Final = "Lượt chạy đang chờ duyệt lại Bộ giá trị gắn"
_REVIEW_BODY: Final = (
    "Quyền của tài khoản dịch vụ đã tăng sau lần duyệt Bộ giá trị gắn mang nó. "
    "Các lượt do trình kích hoạt xin được giữ trong hàng chờ "
    "cho tới khi Bộ giá trị gắn được duyệt lại."
)


@dataclass(frozen=True)
class SqlHeldRunAlerts:
    session_factory: async_sessionmaker[AsyncSession]

    async def principal_inactive(
        self, tenant_id: uuid.UUID, *, workspace_id: uuid.UUID, principal_id: uuid.UUID
    ) -> None:
        members = tables.tenant_members
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            changed: datetime | None = await session.scalar(
                sa.select(members.c.status_changed_at).where(
                    members.c.tenant_id == tenant_id, members.c.user_id == principal_id
                )
            )
        # A principal with no member row has no change to key the notice by:
        # the run stays held, and nobody is told twice.
        if changed is None:
            return
        key = f"studio.run.principal_inactive:{principal_id}:{changed.isoformat()}"
        holders = await SqlScopeHolders(self.session_factory).tenant_depth_holders(
            tenant_id, MEMBERS_WRITE
        )
        notifications = SqlNotificationRepository(self.session_factory)
        for anchor, people in sorted(holders.items(), key=lambda item: str(item[0])):
            await notifications.deliver_in(
                TenantScope(tenant_id=tenant_id, workspace_id=anchor),
                recipients=people,
                source_key=key,
                title=_INACTIVE_TITLE,
                body=_INACTIVE_BODY,
                link=_MEMBERS_LINK,
            )

    async def binding_needs_review(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID,
        artifact_id: uuid.UUID,
        principal_id: uuid.UUID,
        grants_changed_at: datetime,
    ) -> None:
        key = (
            f"studio.run.binding_needs_review:{artifact_id}:{principal_id}:"
            f"{grants_changed_at.isoformat()}"
        )
        people = await SqlScopeHolders(self.session_factory).holding(
            tenant_id, workspace_id, frozenset({BINDINGS_APPROVE})
        )
        await SqlNotificationRepository(self.session_factory).deliver_in(
            TenantScope(tenant_id=tenant_id, workspace_id=workspace_id),
            recipients=people,
            source_key=key,
            title=_REVIEW_TITLE,
            body=_REVIEW_BODY,
            link=_WORKFLOWS_LINK,
        )
