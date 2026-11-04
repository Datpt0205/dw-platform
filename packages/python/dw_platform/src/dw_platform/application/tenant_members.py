"""Everyone in a tenant, with their roles per workspace.

An Org Admin sees every person of their tenant with the roles assigned to them
in each workspace (`platform.members.read`, under the caller's tenant RLS).
Placing people in roles, inviting them and replacing their roles is
`role_assignments.RoleAssignmentService`'s (tenant-rbac ticket 03), where
every role change is held to the hold rule and two people.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import AuthorizationPort

MEMBERS_READ = "platform.members.read"

MemberStatus = Literal["invited", "active", "suspended"]

_RESOURCE = "membership"


@dataclass(frozen=True, slots=True)
class MemberWorkspace:
    workspace_id: uuid.UUID
    workspace_name: str
    role_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TenantMember:
    user_id: uuid.UUID
    display_name: str
    email: str | None
    status: MemberStatus
    memberships: tuple[MemberWorkspace, ...]


class TenantMembersRepositoryPort(Protocol):
    """Membership of the caller's tenant (its RLS), and the identity plane."""

    async def list_members(self, context: AccessContext) -> list[TenantMember]:
        """Everyone with a membership in the caller's tenant, by name."""
        ...


@dataclass(frozen=True)
class TenantMembersService:
    repo: TenantMembersRepositoryPort
    authz: AuthorizationPort

    async def list_members(self, context: AccessContext) -> list[TenantMember]:
        await self.authz.require(context=context, action=MEMBERS_READ, resource_type=_RESOURCE)
        return await self.repo.list_members(context)
