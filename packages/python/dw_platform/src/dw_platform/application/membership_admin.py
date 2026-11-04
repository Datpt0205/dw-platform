"""Org Admin removes a person's access to one workspace of their tenant.

- Scope: `platform.members.write`.
- Tenant: the repository runs under the caller's tenant RLS, so a revoke lands
  in the admin's tenant and nowhere else.
- Roles: removing the membership revokes every role on it, and each revocation
  is held by the database to the hold rule (`platform.rbac_refusals`, ADR-0104
  decision 6): a person may remove only what they could hand out; the last
  owner stays (`ck_role_assignments_last_owner`).

Placing people in roles is `role_assignments.RoleAssignmentService`'s
(tenant-rbac ticket 03). The revoke and its audit record land in one
transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.ports import AuthorizationPort
from dw_platform.domain.audit import AuditEvent

MEMBERS_READ = "platform.members.read"
MEMBERS_WRITE = "platform.members.write"

_ACTION_REVOKE = "platform.membership.revoke"
_RESOURCE = "membership"


@dataclass(frozen=True, slots=True)
class UserRef:
    """A platform identity an admin can act on."""

    user_id: uuid.UUID
    email: str | None
    display_name: str


@dataclass(frozen=True, slots=True)
class RevokeMembership:
    """Remove an identity's access to one workspace of the caller's tenant."""

    user_id: uuid.UUID
    workspace_id: uuid.UUID


class MembershipAdminRepositoryPort(Protocol):
    """Writes membership on the admin's tenant (under its RLS)."""

    async def revoke(
        self,
        context: AccessContext,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        """Remove the membership and, if there was one, record ``audit`` in the
        same transaction. Returns False if there was none to remove. A refused
        revocation of a role on it is read back as its domain error.
        ``effect``, when the request holds an idempotency key, is claimed first in
        the same transaction (app-standards R2.16, R2.38)."""
        ...


@dataclass(frozen=True)
class RevokeMembershipHandler:
    repo: MembershipAdminRepositoryPort
    authz: AuthorizationPort
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(
        self,
        context: AccessContext,
        command: RevokeMembership,
        *,
        effect: PendingEffect | None = None,
    ) -> None:
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type=_RESOURCE)
        removed = await self.repo.revoke(
            context,
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            audit=AuditEvent(
                id=self.id_generator.new_uuid(),
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(command.workspace_id),
                actor_id=UserId(context.principal_id),
                action=_ACTION_REVOKE,
                resource_type=_RESOURCE,
                resource_id=str(command.user_id),
                occurred_at=self.clock.now(),
            ),
            effect=effect,
        )
        if not removed:
            raise NotFoundError(
                "no such membership in this tenant",
                details={"user_id": str(command.user_id)},
            )
