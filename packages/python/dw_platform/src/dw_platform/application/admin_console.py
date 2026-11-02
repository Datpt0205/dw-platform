"""Org Admin console: workspaces, tenant settings, and the role catalog.

The same two rails as ``membership_admin``: every entry point requires an
``platform.*`` scope an Org Admin holds and a member does not, and every write
runs under the caller's tenant RLS, so an Org Admin of one company can never
touch another's workspaces or settings. Mutations record an audit event in the
same transaction as the change.

The role catalog is read-only here on purpose (ADR-001, one-owner-per-fact):
roles and their scopes are versioned configuration edited by deploy, not a
runtime table an admin rewrites. This exposes them so an admin can *see* what
each role grants, nothing more.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from dw_kernel.autonomy import is_autonomy_level
from dw_kernel.errors import DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import PLATFORM_ADMIN_ROLE
from dw_platform.application.ports import AuthorizationPort
from dw_platform.domain.audit import AuditEvent

WORKSPACES_WRITE = "platform.workspaces.write"
ROLES_READ = "platform.roles.read"
TENANT_SETTINGS_WRITE = "platform.tenant.settings.write"
MEMBERS_READ = "platform.members.read"
MEMBERS_WRITE = "platform.members.write"

_ACTION_SET_PERMISSION_SETS = "platform.member.permission_sets"
_RES_MEMBER = "membership"

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_ACTION_WS_CREATE = "platform.workspace.create"
_ACTION_WS_RENAME = "platform.workspace.rename"
_ACTION_WS_ARCHIVE = "platform.workspace.archive"
_ACTION_TENANT_UPDATE = "platform.tenant.settings.update"
_RES_WORKSPACE = "workspace"
_RES_TENANT = "tenant"


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    workspace_id: uuid.UUID
    slug: str
    name: str
    member_count: int
    archived: bool


@dataclass(frozen=True, slots=True)
class WorkspaceRef:
    workspace_id: uuid.UUID
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class RoleInfo:
    key: str
    name: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermissionInfo:
    """One row of the permission catalogue (tenant-rbac R1.4)."""

    key: str
    area: str
    label_vi: str
    scope_kind: str
    risk: str
    status: str


@dataclass(frozen=True, slots=True)
class PermissionSetInfo:
    key: str
    name: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SetPermissionSets:
    """Replace a member's permission sets (in the caller's workspace)."""

    user_id: uuid.UUID
    permission_set_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class TenantSettings:
    tenant_id: uuid.UUID
    slug: str
    name: str
    status: str
    record_visibility: str
    timezone: str | None
    locale: str | None
    max_autonomy_level: str


@dataclass(frozen=True, slots=True)
class CreateWorkspace:
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class RenameWorkspace:
    workspace_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class ArchiveWorkspace:
    workspace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class UpdateTenantSettings:
    """Only the fields present are changed; None means "leave as is"."""

    name: str | None = None
    timezone: str | None = None
    locale: str | None = None
    record_visibility: str | None = None
    max_autonomy_level: str | None = None


class AdminConsoleRepositoryPort(Protocol):
    async def list_workspaces(self, context: AccessContext) -> list[WorkspaceSummary]: ...

    async def create_workspace(
        self,
        context: AccessContext,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        name: str,
        audit: AuditEvent,
    ) -> WorkspaceRef:
        """Insert a workspace in the caller's tenant. Raises ``ConflictError``
        if the slug is already taken there."""
        ...

    async def rename_workspace(
        self, context: AccessContext, *, workspace_id: uuid.UUID, name: str, audit: AuditEvent
    ) -> WorkspaceRef | None:
        """Rename a workspace in the caller's tenant, or None if there is none."""
        ...

    async def archive_workspace(
        self, context: AccessContext, *, workspace_id: uuid.UUID, audit: AuditEvent
    ) -> bool: ...

    async def list_roles(self) -> list[RoleInfo]: ...

    async def list_permission_sets(self) -> list[PermissionSetInfo]: ...

    async def list_permissions(self) -> list[PermissionInfo]:
        """The catalogue, by area then key."""
        ...

    async def known_permission_sets(self, keys: frozenset[str]) -> frozenset[str]:
        """Which of the given permission-set keys exist in the catalog."""
        ...

    async def scopes_for_permission_sets(self, keys: frozenset[str]) -> frozenset[str]:
        """The union of scopes the given permission sets carry."""
        ...

    async def set_permission_sets(
        self,
        context: AccessContext,
        *,
        user_id: uuid.UUID,
        permission_set_keys: frozenset[str],
        audit: AuditEvent,
    ) -> bool:
        """Replace the member's permission sets; False if no such membership."""
        ...

    async def get_tenant_settings(self, context: AccessContext) -> TenantSettings | None: ...

    async def update_tenant_settings(
        self, context: AccessContext, *, command: UpdateTenantSettings, audit: AuditEvent
    ) -> TenantSettings | None: ...


@dataclass(frozen=True)
class AdminConsoleService:
    repo: AdminConsoleRepositoryPort
    authz: AuthorizationPort
    clock: UtcClock
    id_generator: IdGenerator

    # ---- workspaces ----
    async def list_workspaces(self, context: AccessContext) -> list[WorkspaceSummary]:
        await self.authz.require(context=context, action=MEMBERS_READ, resource_type=_RES_WORKSPACE)
        return await self.repo.list_workspaces(context)

    async def create_workspace(
        self, context: AccessContext, command: CreateWorkspace
    ) -> WorkspaceRef:
        await self.authz.require(
            context=context, action=WORKSPACES_WRITE, resource_type=_RES_WORKSPACE
        )
        name = command.name.strip()
        slug = command.slug.strip().lower()
        if not name:
            raise DomainError("a workspace needs a name")
        if not _SLUG.match(slug):
            raise DomainError(
                "slug must be lowercase letters, digits and single hyphens",
                details={"slug": slug},
            )
        workspace_id = self.id_generator.new_uuid()
        return await self.repo.create_workspace(
            context,
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            audit=self._event(
                context,
                _ACTION_WS_CREATE,
                workspace_id,
                _RES_WORKSPACE,
                str(workspace_id),
                {"slug": slug, "name": name},
            ),
        )

    async def rename_workspace(
        self, context: AccessContext, command: RenameWorkspace
    ) -> WorkspaceRef:
        await self.authz.require(
            context=context, action=WORKSPACES_WRITE, resource_type=_RES_WORKSPACE
        )
        name = command.name.strip()
        if not name:
            raise DomainError("a workspace needs a name")
        result = await self.repo.rename_workspace(
            context,
            workspace_id=command.workspace_id,
            name=name,
            audit=self._event(
                context,
                _ACTION_WS_RENAME,
                command.workspace_id,
                _RES_WORKSPACE,
                str(command.workspace_id),
                {"name": name},
            ),
        )
        if result is None:
            raise NotFoundError(
                "no such workspace in this tenant",
                details={"workspace_id": str(command.workspace_id)},
            )
        return result

    async def archive_workspace(self, context: AccessContext, command: ArchiveWorkspace) -> None:
        await self.authz.require(
            context=context, action=WORKSPACES_WRITE, resource_type=_RES_WORKSPACE
        )
        archived = await self.repo.archive_workspace(
            context,
            workspace_id=command.workspace_id,
            audit=self._event(
                context,
                _ACTION_WS_ARCHIVE,
                command.workspace_id,
                _RES_WORKSPACE,
                str(command.workspace_id),
                {},
            ),
        )
        if not archived:
            raise NotFoundError(
                "no such workspace in this tenant",
                details={"workspace_id": str(command.workspace_id)},
            )

    # ---- roles (read-only) ----
    async def list_roles(self, context: AccessContext) -> list[RoleInfo]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="role")
        return await self.repo.list_roles()

    # ---- the permission catalogue (read-only, tenant-rbac R1.4) ----
    async def list_permissions(self, context: AccessContext) -> list[PermissionInfo]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="permission")
        return await self.repo.list_permissions()

    # ---- permission sets ----
    async def list_permission_sets(self, context: AccessContext) -> list[PermissionSetInfo]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="permission_set")
        return await self.repo.list_permission_sets()

    async def set_permission_sets(self, context: AccessContext, command: SetPermissionSets) -> None:
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type=_RES_MEMBER)
        keys = command.permission_set_keys
        unknown = keys - await self.repo.known_permission_sets(keys)
        if unknown:
            raise NotFoundError("unknown permission set", details={"keys": sorted(unknown)})

        # No escalation: only a platform admin may hand out a set carrying any
        # platform.* scope (same rule that guards administrative roles).
        if PLATFORM_ADMIN_ROLE not in context.roles:
            granted = await self.repo.scopes_for_permission_sets(keys)
            administrative = {scope for scope in granted if scope.startswith("platform.")}
            if administrative:
                raise PermissionDeniedError(
                    "only a platform admin may grant an administrative permission set",
                    details={"scopes": sorted(administrative)},
                )

        changed = await self.repo.set_permission_sets(
            context,
            user_id=command.user_id,
            permission_set_keys=keys,
            audit=self._event(
                context,
                _ACTION_SET_PERMISSION_SETS,
                context.workspace_id,
                _RES_MEMBER,
                str(command.user_id),
                {"permission_set_keys": sorted(keys)},
            ),
        )
        if not changed:
            raise NotFoundError(
                "no such member in this workspace",
                details={"user_id": str(command.user_id)},
            )

    # ---- tenant settings ----
    async def get_tenant_settings(self, context: AccessContext) -> TenantSettings:
        await self.authz.require(context=context, action=MEMBERS_READ, resource_type=_RES_TENANT)
        settings = await self.repo.get_tenant_settings(context)
        if settings is None:
            raise NotFoundError("tenant not found")
        return settings

    async def update_tenant_settings(
        self, context: AccessContext, command: UpdateTenantSettings
    ) -> TenantSettings:
        await self.authz.require(
            context=context, action=TENANT_SETTINGS_WRITE, resource_type=_RES_TENANT
        )
        name = command.name.strip() if command.name is not None else None
        if name is not None and not name:
            raise DomainError("tenant name cannot be empty")
        if command.record_visibility is not None and command.record_visibility not in (
            "open",
            "restricted",
        ):
            raise DomainError(
                "record_visibility must be 'open' or 'restricted'",
                details={"record_visibility": command.record_visibility},
            )
        # The HTTP boundary already refuses anything else, and the database has a
        # CHECK constraint behind this. Checked here too because this service has
        # callers that are not that route.
        if command.max_autonomy_level is not None and not is_autonomy_level(
            command.max_autonomy_level
        ):
            raise DomainError(
                "max_autonomy_level must be one of A0, A1, A2, A3, A4",
                details={"max_autonomy_level": command.max_autonomy_level},
            )
        normalised = UpdateTenantSettings(
            name=name,
            timezone=command.timezone,
            locale=command.locale,
            record_visibility=command.record_visibility,
            max_autonomy_level=command.max_autonomy_level,
        )
        settings = await self.repo.update_tenant_settings(
            context,
            command=normalised,
            audit=self._event(
                context,
                _ACTION_TENANT_UPDATE,
                context.workspace_id,
                _RES_TENANT,
                str(context.tenant_id),
                {
                    k: v
                    for k, v in {
                        "name": name,
                        "timezone": command.timezone,
                        "locale": command.locale,
                        # Who may see which records, for the whole tenant. Going
                        # from `restricted` to `open` widens every list screen at
                        # once, and the event was being written without saying so
                        # — an audit row that records that something changed but
                        # not what is not an answer to the question it is kept for.
                        "record_visibility": command.record_visibility,
                        # How much a tenant lets its workers do unasked is exactly
                        # the kind of change an audit trail exists to answer for.
                        "max_autonomy_level": command.max_autonomy_level,
                    }.items()
                    if v is not None
                },
            ),
        )
        if settings is None:
            raise NotFoundError("tenant not found")
        return settings

    def _event(
        self,
        context: AccessContext,
        action: str,
        workspace_id: uuid.UUID,
        resource_type: str,
        resource_id: str,
        details: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            occurred_at=self.clock.now(),
            details=details,
        )
