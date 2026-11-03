"""Service accounts a company's runs act as (org-and-principals R6; ADR-0103
decisions 2-4).

A service account is a `platform.users` row of kind `service` owned by one
tenant: an `active` company member with one membership in its owning
workspace and no role of its own until the role-assignment API gives it one
(two people, D11). It never signs in, never holds a critical privilege, and
has an accountable owner who is an `active` human member. The database keeps
every one of those rules (migrations be93e0c26a4c and 557e6907195e); this
module authorizes the caller and reads the refusals back.

A Digital Worker's principal is a service account too, but not one this
surface manages or binds: it is absent here, the same 404 as an account of
another tenant or an id that does not exist (R6.13, R6.15).

Who may bind an account as a run's principal is `ServicePrincipalBindingGuard`
(R6.5, R6.15, R6.17), in this order: the account is visible, the caller holds
`platform.service_principals.use` reaching its workspace, the account is
`active`, its owner is present, and the caller holds every privilege it holds
(`platform.uncovered_grants`, the database's one cover rule). A context that
binds declares its own Protocol; the composition root hands it this object.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from dw_kernel.errors import (
    ConflictError,
    DomainError,
    DWError,
    NotFoundError,
    PermissionDeniedError,
)
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import permission_denied
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.audit import AuditEvent

# Checked against the workspace a row is owned by, through
# `platform.workspace_reach` (step 5): never as a scope of the acting workspace.
SERVICE_PRINCIPALS_MANAGE_SCOPE = "platform.service_principals.manage"
SERVICE_PRINCIPALS_USE_SCOPE = "platform.service_principals.use"

# R6.12: a page of the list holds at most this many accounts.
MAX_PAGE_ROWS = 50

_RESOURCE = "service_principal"
_ACTION_CREATED = "platform.service_principal.created"
_ACTION_UPDATED = "platform.service_principal.updated"

MemberStatus = Literal["invited", "active", "suspended"]


@dataclass(frozen=True, slots=True)
class ServicePrincipal:
    """One account as the admin surface shows it. ``status`` is its company
    row's (None once that row is gone, which reads as not `active`)."""

    id: uuid.UUID
    name: str
    description: str | None
    owning_workspace_id: uuid.UUID
    owner_user_id: uuid.UUID | None
    owner_missing: bool
    status: MemberStatus | None


@dataclass(frozen=True, slots=True)
class ListedServicePrincipal:
    principal: ServicePrincipal
    bindable_by_me: bool


@dataclass(frozen=True, slots=True)
class NewServicePrincipal:
    name: str
    description: str | None
    owning_workspace_id: uuid.UUID
    owner_user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ServicePrincipalChanges:
    """What a PATCH names; None leaves a field as it is, except `description`,
    which ``clear_description`` empties."""

    name: str | None = None
    description: str | None = None
    clear_description: bool = False
    owner_user_id: uuid.UUID | None = None

    def fields(self) -> tuple[str, ...]:
        named = []
        if self.name is not None:
            named.append("name")
        if self.description is not None or self.clear_description:
            named.append("description")
        if self.owner_user_id is not None:
            named.append("owner_user_id")
        return tuple(named)


@dataclass(frozen=True, slots=True)
class MissingGrant:
    """A privilege the caller lacks, at the depth and anchor the account holds it."""

    permission_key: str
    depth: str
    anchor_workspace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class BindingFacts:
    """What the guard decides on, read in one statement under the caller's RLS."""

    found: bool
    is_digital_worker: bool
    owning_workspace_id: uuid.UUID | None
    can_use: bool
    active: bool
    owner_present: bool
    uncovered: tuple[MissingGrant, ...]


class WorkspaceNotInTenantError(DomainError):
    """The owning workspace is not one of the caller's tenant (or does not
    exist): 422 `validation_failed` located at ``pointer``, one answer for both."""

    def __init__(self) -> None:
        super().__init__(
            "the owning workspace is not a workspace of this company",
            details={"reason_code": "workspace_unknown"},
        )
        self.pointer = "/owning_workspace_id"


class ServicePrincipalRepositoryPort(Protocol):
    """Service accounts of the caller's tenant, under its RLS; a Digital
    Worker's principal is never one of them."""

    async def workspace_usable(self, context: AccessContext, workspace_id: uuid.UUID) -> bool:
        """Whether the workspace is a live one of the caller's tenant."""
        ...

    async def reaches(
        self, context: AccessContext, permission_key: str, workspace_id: uuid.UUID
    ) -> bool:
        """Whether the caller holds ``permission_key`` reaching ``workspace_id``."""
        ...

    async def create(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        command: NewServicePrincipal,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        """Write the service user, its `active` company row, its membership of
        the owning workspace, its detail row and ``audit`` in one transaction."""
        ...

    async def get(
        self, context: AccessContext, principal_id: uuid.UUID
    ) -> ServicePrincipal | None: ...

    async def update(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        changes: ServicePrincipalChanges,
        *,
        audit: AuditEvent,
    ) -> bool:
        """Apply ``changes`` with ``audit``; False when the row is gone."""
        ...

    async def page(self, context: AccessContext, request: PageRequest) -> Page[ServicePrincipal]:
        """By name, those whose owning workspace the caller reaches with
        `.manage` or `.use` (R6.12)."""
        ...


class BindingFactsPort(Protocol):
    async def binding_facts(
        self, context: AccessContext, principal_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, BindingFacts]:
        """The facts of each id, every id answered."""
        ...


def _not_found() -> NotFoundError:
    return NotFoundError("no such service account")


def _escalation(message: str, missing: Sequence[MissingGrant]) -> PermissionDeniedError:
    return PermissionDeniedError(
        message,
        details={
            "reason_code": "rbac_escalation",
            "missing": [
                {
                    "permission_key": grant.permission_key,
                    "depth": grant.depth,
                    "anchor_workspace_id": str(grant.anchor_workspace_id),
                }
                for grant in missing
            ],
        },
    )


def binding_refusal(facts: BindingFacts | None) -> DWError | None:
    """Why the caller may not bind this account, or None: R6.15, R6.5, R6.17,
    R6.5 again, in that order. (a) names no privilege."""
    if facts is None or not facts.found or facts.is_digital_worker:
        return _not_found()
    if not facts.can_use or facts.owning_workspace_id is None:
        anchor = facts.owning_workspace_id or uuid.UUID(int=0)
        return _escalation(
            "binding a service account takes platform.service_principals.use on its workspace",
            [MissingGrant(SERVICE_PRINCIPALS_USE_SCOPE, "workspace", anchor)],
        )
    if not facts.active:
        return ConflictError(
            "the service account is not active", details={"reason_code": "principal_inactive"}
        )
    if not facts.owner_present:
        return ConflictError(
            "the service account has no active accountable owner",
            details={"reason_code": "owner_missing"},
        )
    if facts.uncovered:
        return _escalation(
            "the caller does not hold every privilege of the service account", facts.uncovered
        )
    return None


@dataclass(frozen=True)
class ServicePrincipalBindingGuard:
    """Whether the caller may bind a service account as a run's principal."""

    facts: BindingFactsPort

    async def require_bindable(
        self, context: AccessContext, service_principal_id: uuid.UUID
    ) -> None:
        found = await self.facts.binding_facts(context, [service_principal_id])
        refusal = binding_refusal(found.get(service_principal_id))
        if refusal is not None:
            raise refusal

    async def bindable(
        self, context: AccessContext, service_principal_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, bool]:
        """`bindable_by_me` of a page: the same decision, one read for all."""
        if not service_principal_ids:
            return {}
        found = await self.facts.binding_facts(context, service_principal_ids)
        return {
            principal_id: binding_refusal(found.get(principal_id)) is None
            for principal_id in service_principal_ids
        }


@dataclass(frozen=True)
class ServicePrincipalService:
    repo: ServicePrincipalRepositoryPort
    binding: ServicePrincipalBindingGuard
    clock: UtcClock
    id_generator: IdGenerator

    async def require_manage(self, context: AccessContext, workspace_id: uuid.UUID) -> None:
        """The workspace is the caller's tenant's (422 otherwise), then reached
        with `.manage` (403): the check `POST` declares for its key too."""
        if not await self.repo.workspace_usable(context, workspace_id):
            raise WorkspaceNotInTenantError()
        if not await self.repo.reaches(context, SERVICE_PRINCIPALS_MANAGE_SCOPE, workspace_id):
            raise permission_denied(action=SERVICE_PRINCIPALS_MANAGE_SCOPE, resource_type=_RESOURCE)

    async def create(
        self,
        context: AccessContext,
        command: NewServicePrincipal,
        *,
        effect: PendingEffect | None = None,
    ) -> ListedServicePrincipal:
        await self.require_manage(context, command.owning_workspace_id)
        principal_id = self.id_generator.new_uuid()
        await self.repo.create(
            context,
            principal_id,
            command,
            audit=self._event(
                context,
                _ACTION_CREATED,
                principal_id,
                command.owning_workspace_id,
                {
                    "owning_workspace_id": str(command.owning_workspace_id),
                    "owner_user_id": str(command.owner_user_id),
                },
            ),
            effect=effect,
        )
        return await self.read(context, principal_id)

    async def update(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        changes: ServicePrincipalChanges,
    ) -> ListedServicePrincipal:
        found = await self.repo.get(context, principal_id)
        if found is None:
            raise _not_found()
        if not await self.repo.reaches(
            context, SERVICE_PRINCIPALS_MANAGE_SCOPE, found.owning_workspace_id
        ):
            raise permission_denied(
                action=SERVICE_PRINCIPALS_MANAGE_SCOPE,
                resource_type=_RESOURCE,
                resource_id=str(principal_id),
            )
        details: dict[str, object] = {"fields": list(changes.fields())}
        if changes.owner_user_id is not None and changes.owner_user_id != found.owner_user_id:
            details["owner_user_id"] = {
                "from": str(found.owner_user_id) if found.owner_user_id else None,
                "to": str(changes.owner_user_id),
            }
        updated = await self.repo.update(
            context,
            principal_id,
            changes,
            audit=self._event(
                context, _ACTION_UPDATED, principal_id, found.owning_workspace_id, details
            ),
        )
        if not updated:
            raise _not_found()
        return await self.read(context, principal_id)

    async def read(self, context: AccessContext, principal_id: uuid.UUID) -> ListedServicePrincipal:
        """One account as the list shows it; 404 when the caller cannot see it."""
        found = await self.repo.get(context, principal_id)
        if found is None:
            raise _not_found()
        bindable = await self.binding.bindable(context, [principal_id])
        return ListedServicePrincipal(found, bindable_by_me=bindable[principal_id])

    async def list(
        self, context: AccessContext, request: PageRequest
    ) -> Page[ListedServicePrincipal]:
        capped = replace(request, limit=min(request.limit, MAX_PAGE_ROWS))
        page = await self.repo.page(context, capped)
        bindable = await self.binding.bindable(context, [p.id for p in page.items])
        return page.map_items(lambda p: ListedServicePrincipal(p, bindable_by_me=bindable[p.id]))

    def _event(
        self,
        context: AccessContext,
        action: str,
        principal_id: uuid.UUID,
        workspace_id: uuid.UUID,
        details: Mapping[str, object],
    ) -> AuditEvent:
        # Ids only: a name or a description is not repeated into the audit log.
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(principal_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )


__all__ = [
    "MAX_PAGE_ROWS",
    "SERVICE_PRINCIPALS_MANAGE_SCOPE",
    "SERVICE_PRINCIPALS_USE_SCOPE",
    "BindingFacts",
    "BindingFactsPort",
    "ListedServicePrincipal",
    "MissingGrant",
    "NewServicePrincipal",
    "ServicePrincipal",
    "ServicePrincipalBindingGuard",
    "ServicePrincipalChanges",
    "ServicePrincipalRepositoryPort",
    "ServicePrincipalService",
    "WorkspaceNotInTenantError",
    "binding_refusal",
]
