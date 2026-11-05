"""Org Admin console: workspaces, tenant settings, the permission catalogue
and the permission-set templates.

The same two rails as ``membership_admin``: every entry point requires an
``platform.*`` scope an Org Admin holds and a member does not, and every write
runs under the caller's tenant RLS, so an Org Admin of one company can never
touch another's workspaces or settings. Mutations record an audit event in the
same transaction as the change.

The tenant's own roles, and who holds them, are `role_admin` and
`role_assignments` (tenant-rbac ticket 03); the catalogue here says, for the
caller, how deep each key may be set and how deep the caller could hand it out.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from dw_kernel.autonomy import is_autonomy_level
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.residency import tenant_class_change, workspace_class_change
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import AuthorizationPort
from dw_platform.domain.audit import AuditEvent

WORKSPACES_WRITE = "platform.workspaces.write"
ROLES_READ = "platform.roles.read"
TENANT_SETTINGS_WRITE = "platform.tenant.settings.write"
MEMBERS_READ = "platform.members.read"

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_ACTION_WS_CREATE = "platform.workspace.create"
_ACTION_WS_RENAME = "platform.workspace.rename"
_ACTION_WS_ARCHIVE = "platform.workspace.archive"
_ACTION_TENANT_UPDATE = "platform.tenant.settings.update"
# compliance-pdpl R2.8: the one event of a route class change, tenant or workspace.
ACTION_RESIDENCY_CHANGED = "residency.class_changed"
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
    # NULL inherits the tenant's data route class (compliance-pdpl R2.4).
    data_route_class: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionInfo:
    """One row of the permission catalogue (tenant-rbac R1.4)."""

    key: str
    area: str
    label_vi: str
    scope_kind: str
    risk: str
    status: str
    # The depths the key takes by its kind (R3.4), and the broadest of them the
    # caller holds at their own workspace (the hold rule), None when none.
    allowed_depths: tuple[str, ...] = ()
    max_grantable_depth: str | None = None
    # A generated `obj.<object>.<action>` key (tenant-rbac R9.1): the ids a
    # client puts in `object_privileges`; None for a catalogue row.
    object_id: uuid.UUID | None = None
    action: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionSetInfo:
    key: str
    name: str
    scopes: tuple[str, ...]


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
    data_route_class: str = "vn_only"


@dataclass(frozen=True, slots=True)
class CreateWorkspace:
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class RenameWorkspace:
    workspace_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class UpdateWorkspace:
    """`PATCH /admin/workspaces/{id}`: only what is set changes. `data_route_class`
    is read only when `sets_route_class`, because `None` there is a value (back
    to inheriting the tenant's, a loosening) and not "leave as is"."""

    workspace_id: uuid.UUID
    name: str | None = None
    data_route_class: str | None = None
    sets_route_class: bool = False


@dataclass(frozen=True, slots=True)
class RouteClassWrite:
    """A tightening the service decided on, written only while the row still
    holds `expected` (a concurrent change refuses the write), with its
    `residency.class_changed` event in the same transaction (R2.8)."""

    expected: str | None
    new: str | None
    audit: AuditEvent


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
    data_route_class: str | None = None


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

    async def update_workspace(
        self,
        context: AccessContext,
        *,
        workspace_id: uuid.UUID,
        name: str | None,
        route_class: RouteClassWrite | None,
        audit: AuditEvent | None,
    ) -> WorkspaceRef | None:
        """Rename a workspace in the caller's tenant and/or tighten its route
        class, each audit event in the same transaction, or None if there is no
        such workspace. Raises `ConflictError` when `route_class.expected` no
        longer holds."""
        ...

    async def route_classes(
        self, context: AccessContext, workspace_id: uuid.UUID
    ) -> tuple[str, str | None] | None:
        """The tenant's and the workspace's class, or None when the workspace is
        not the caller's tenant's (RLS returns no row)."""
        ...

    async def archive_workspace(
        self, context: AccessContext, *, workspace_id: uuid.UUID, audit: AuditEvent
    ) -> bool: ...

    async def list_permission_sets(self) -> list[PermissionSetInfo]: ...

    async def list_permissions(self, context: AccessContext) -> list[PermissionInfo]:
        """The catalogue, by area then key, with the caller's depths."""
        ...

    async def get_tenant_settings(self, context: AccessContext) -> TenantSettings | None: ...

    async def update_tenant_settings(
        self,
        context: AccessContext,
        *,
        command: UpdateTenantSettings,
        audit: AuditEvent,
        route_class: RouteClassWrite | None = None,
    ) -> TenantSettings | None:
        """`command.data_route_class` is not read: a class is written only
        through `route_class`, the change the service decided on."""
        ...


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
        return await self.update_workspace(
            context, UpdateWorkspace(workspace_id=command.workspace_id, name=command.name)
        )

    async def update_workspace(
        self, context: AccessContext, command: UpdateWorkspace
    ) -> WorkspaceRef:
        """The name under `platform.workspaces.write`; the data route class under
        `platform.tenant.settings.write`, a tenant-depth key, because the route
        is the controller's decision (compliance-pdpl R2.4, R2.7, R2.8). Every
        refusal comes before any write, so a refused request changes nothing."""
        if command.name is None and not command.sets_route_class:
            raise DomainError("nothing to change")
        if command.name is not None:
            await self.authz.require(
                context=context, action=WORKSPACES_WRITE, resource_type=_RES_WORKSPACE
            )
        if command.sets_route_class:
            await self.authz.require(
                context=context, action=TENANT_SETTINGS_WRITE, resource_type=_RES_WORKSPACE
            )
        name = command.name.strip() if command.name is not None else None
        if name is not None and not name:
            raise DomainError("a workspace needs a name")
        route_class: RouteClassWrite | None = None
        if command.sets_route_class:
            classes = await self.repo.route_classes(context, command.workspace_id)
            if classes is None:
                raise _no_workspace(command.workspace_id)
            tenant_class, current = classes
            # 422 when looser than the tenant, 409 when it loosens the
            # workspace's own: both before anything is written. The class it
            # already holds writes and audits nothing.
            change = workspace_class_change(tenant_class, current, command.data_route_class)
            if change == "tightened":
                route_class = RouteClassWrite(
                    expected=current,
                    new=command.data_route_class,
                    audit=self._residency_event(
                        context,
                        command.workspace_id,
                        _RES_WORKSPACE,
                        str(command.workspace_id),
                        before=current,
                        after=command.data_route_class,
                    ),
                )
        result = await self.repo.update_workspace(
            context,
            workspace_id=command.workspace_id,
            name=name,
            route_class=route_class,
            audit=(
                None
                if name is None
                else self._event(
                    context,
                    _ACTION_WS_RENAME,
                    command.workspace_id,
                    _RES_WORKSPACE,
                    str(command.workspace_id),
                    {"name": name},
                )
            ),
        )
        if result is None:
            raise _no_workspace(command.workspace_id)
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

    # ---- the permission catalogue (read-only, tenant-rbac R1.4) ----
    async def list_permissions(self, context: AccessContext) -> list[PermissionInfo]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="permission")
        return await self.repo.list_permissions(context)

    # ---- permission sets ----
    async def list_permission_sets(self, context: AccessContext) -> list[PermissionSetInfo]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="permission_set")
        return await self.repo.list_permission_sets()

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
        route_class: RouteClassWrite | None = None
        if command.data_route_class is not None:
            current = await self.repo.get_tenant_settings(context)
            if current is None:
                raise NotFoundError("tenant not found")
            # One person tightens; loosening is 409 before anything is written
            # (compliance-pdpl R2.7, R2.8). The class it already holds changes
            # nothing and is not audited.
            change = tenant_class_change(current.data_route_class, command.data_route_class)
            if change == "tightened":
                route_class = RouteClassWrite(
                    expected=current.data_route_class,
                    new=command.data_route_class,
                    audit=self._residency_event(
                        context,
                        context.workspace_id,
                        _RES_TENANT,
                        str(context.tenant_id),
                        before=current.data_route_class,
                        after=command.data_route_class,
                    ),
                )
        settings = await self.repo.update_tenant_settings(
            context,
            route_class=route_class,
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

    def _residency_event(
        self,
        context: AccessContext,
        workspace_id: uuid.UUID,
        resource_type: str,
        resource_id: str,
        *,
        before: str | None,
        after: str | None,
    ) -> AuditEvent:
        # Which class, before and after, and of what (R2.8); NULL inherits.
        return self._event(
            context,
            ACTION_RESIDENCY_CHANGED,
            workspace_id,
            resource_type,
            resource_id,
            {"scope": resource_type, "from": before, "to": after},
        )

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


def _no_workspace(workspace_id: uuid.UUID) -> NotFoundError:
    return NotFoundError(
        "no such workspace in this tenant", details={"workspace_id": str(workspace_id)}
    )
