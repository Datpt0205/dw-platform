"""Tenant roles as their administrators change them (tenant-rbac R6-R8; ADR-0104
decisions 6 and 10).

Two rules shape every write here, and the database holds both for every writer
(`platform.rbac_refusals`, `platform.rbac_guard`); this service asks the same
function first so a refusal is a clear answer instead of a constraint name:

- **Hold what you hand out.** A privilege enters a role, an assignment or a
  revocation only from someone holding it at the same or a broader depth over
  the anchor; `platform.roles.bind` assigns roles that are not critical; nobody
  assigns to themselves; system roles keep their shape; a key no tenant may hold
  never enters (`rbac_refusal_error`).
- **One person closes, two open (D11).** A change that only narrows (privileges
  removed or made shallower, a role nobody holds deleted) is applied in the
  sender's transaction with one audit event. Every other change is a proposal
  in `platform.role_change_requests`, applied only when another holder of the
  same permission confirms it, in their own transaction, so the triggers judge
  the confirming person.

A role on an existing row is an R3 resource of app-standards: its `version` is
its ETag, and every write names it in `If-Match` (412 when stale, 428 missing).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from dw_kernel.errors import (
    ConflictError,
    DomainError,
    DWError,
    NotFoundError,
    PermissionDeniedError,
)
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.ports import AuthorizationPort
from dw_platform.domain.audit import AuditEvent

ROLES_READ = "platform.roles.read"
ROLES_WRITE = "platform.roles.write"
ROLES_BIND = "platform.roles.bind"

ProposalKind = Literal["role_create", "role_update", "role_permissions", "assignment_grant"]
ProposalStatus = Literal["proposed", "confirmed", "withdrawn"]
RoleKind = Literal["role", "permission_set"]

DEPTHS: tuple[str, ...] = ("own", "workspace", "tenant")
SYSTEM_ROLES = frozenset({"tenant_owner", "member"})
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

# Audit actions (labels in configs/copy/audit_actions.d/tenant-rbac.yaml).
ACTION_PROPOSED = "platform.role_change.proposed"
ACTION_CONFIRMED = "platform.role_change.confirmed"
ACTION_WITHDRAWN = "platform.role_change.withdrawn"
ACTION_ROLE_CREATE = "platform.role.create"
ACTION_ROLE_UPDATE = "platform.role.update"
ACTION_ROLE_PERMISSIONS = "platform.role.permissions_set"
ACTION_ROLE_DELETE = "platform.role.delete"
ACTION_GRANT = "platform.role_assignment.grant"
ACTION_REVOKE = "platform.role_assignment.revoke"


@dataclass(frozen=True, slots=True, order=True)
class Privilege:
    key: str
    depth: str

    def as_json(self) -> dict[str, str]:
        return {"key": self.key, "depth": self.depth}


@dataclass(frozen=True, slots=True)
class Refusal:
    """One row of `platform.rbac_refusals`."""

    reason_code: str
    permission_key: str | None = None
    depth: str | None = None


def rbac_refusal_error(refusals: Sequence[Refusal]) -> DWError | None:
    """The one answer to a refusal of `platform.rbac_refusals`, for the service's
    early ask and for the trigger's 23514 alike (step 7): 403 `rbac_escalation`
    with the keys missing, 403 `rbac_self_assignment`, 422 `rbac_not_grantable`,
    409 `role_is_system`. None when nothing was refused."""
    if not refusals:
        return None
    codes = {r.reason_code for r in refusals}
    keys = sorted(
        {f"{r.permission_key}:{r.depth}" for r in refusals if r.permission_key is not None}
    )
    if "role_is_system" in codes:
        return ConflictError(
            "a system role keeps its key, its life and, for the owner, its privileges",
            details={"reason_code": "role_is_system"},
        )
    if "rbac_not_grantable" in codes:
        return DomainError(
            "a tenant may not hold this privilege or role",
            details={"reason_code": "rbac_not_grantable", "keys": keys},
        )
    if "rbac_self_assignment" in codes:
        return PermissionDeniedError(
            "nobody assigns a role to themselves",
            details={"reason_code": "rbac_self_assignment"},
        )
    return PermissionDeniedError(
        "you do not hold every privilege this change hands out",
        details={"reason_code": "rbac_escalation", "keys": keys},
    )


def _refuse_if_any(refusals: Sequence[Refusal]) -> None:
    error = rbac_refusal_error(refusals)
    if error is not None:
        raise error


def conflict(message: str, reason_code: str, **details: object) -> ConflictError:
    return ConflictError(message, details={"reason_code": reason_code, **details})


@dataclass(frozen=True, slots=True)
class RoleSummary:
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    kind: str
    is_system: bool
    template_key: str | None
    holder_count: int
    version: int
    assignable_by_me: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RoleDetail:
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    kind: str
    is_system: bool
    template_key: str | None
    holder_count: int
    version: int
    updated_at: datetime
    deleted: bool
    privileges: tuple[Privilege, ...]


@dataclass(frozen=True, slots=True)
class RoleAssignmentRow:
    id: uuid.UUID
    membership_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    assigned_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class RoleTemplate:
    key: str
    name: str
    kind: str
    privileges: tuple[Privilege, ...]


@dataclass(frozen=True, slots=True)
class Proposal:
    id: uuid.UUID
    kind: ProposalKind
    role_id: uuid.UUID | None
    base_version: int | None
    payload: Mapping[str, object]
    required_permission: str
    proposed_by: uuid.UUID
    proposed_at: datetime
    expires_at: datetime
    status: ProposalStatus
    confirmed_by: uuid.UUID | None = None
    decided_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewProposal:
    """A proposal as the service writes it. `base_version` is the role's
    version the proposer read (`If-Match`), or None: read under the role row's
    lock for an assignment, and absent for a role not yet made."""

    id: uuid.UUID
    kind: ProposalKind
    role_id: uuid.UUID | None
    base_version: int | None
    payload: Mapping[str, object]

    @property
    def required_permission(self) -> str:
        return ROLES_BIND if self.kind == "assignment_grant" else ROLES_WRITE


@dataclass(frozen=True, slots=True)
class CreateRole:
    key: str
    name: str
    description: str | None = None
    kind: RoleKind = "role"
    from_template: str | None = None
    clone_of: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class PrivilegeDiff:
    added: tuple[Privilege, ...] = ()
    raised: tuple[Privilege, ...] = ()
    removed: tuple[Privilege, ...] = ()
    lowered: tuple[Privilege, ...] = ()

    @property
    def widens(self) -> bool:
        return bool(self.added or self.raised)

    @property
    def empty(self) -> bool:
        return not (self.added or self.raised or self.removed or self.lowered)


def diff_privileges(current: Sequence[Privilege], target: Sequence[Privilege]) -> PrivilegeDiff:
    """What moving a role from ``current`` to ``target`` adds, deepens, removes
    and makes shallower. Only a diff with nothing added or deepened narrows
    (R7.6); a mixed one widens and takes two people (R7.1, RB32)."""
    now = {p.key: p.depth for p in current}
    then = {p.key: p.depth for p in target}
    added, raised, removed, lowered = [], [], [], []
    for key, depth in sorted(then.items()):
        if key not in now:
            added.append(Privilege(key, depth))
        elif DEPTHS.index(depth) > DEPTHS.index(now[key]):
            raised.append(Privilege(key, depth))
        elif DEPTHS.index(depth) < DEPTHS.index(now[key]):
            lowered.append(Privilege(key, now[key]))
    for key, depth in sorted(now.items()):
        if key not in then:
            removed.append(Privilege(key, depth))
    return PrivilegeDiff(tuple(added), tuple(raised), tuple(removed), tuple(lowered))


def privilege_changes(role_id: uuid.UUID, diff: PrivilegeDiff) -> list[dict[str, object]]:
    """The diff as `platform.rbac_refusals` changes: the depth at stake is the
    new one for what widens and the old one for what narrows."""
    ops = (("add", diff.added), ("raise", diff.raised), ("remove", diff.removed))
    changes: list[dict[str, object]] = [
        {"op": op, "role_id": str(role_id), "permission_key": p.key, "depth": p.depth}
        for op, privileges in ops
        for p in privileges
    ]
    changes += [
        {"op": "lower", "role_id": str(role_id), "permission_key": p.key, "depth": p.depth}
        for p in diff.lowered
    ]
    return changes


@dataclass(frozen=True, slots=True)
class CatalogueKey:
    key: str
    scope_kind: str
    status: str
    tenant_grantable: bool

    @property
    def allowed_depths(self) -> tuple[str, ...]:
        if self.scope_kind == "tenant":
            return ("tenant",)
        if self.scope_kind == "workspace":
            return ("workspace", "tenant")
        return DEPTHS


@dataclass(frozen=True, slots=True)
class ConfirmOutcome:
    proposal: Proposal
    role_id: uuid.UUID | None


class RoleAdminRepositoryPort(Protocol):
    """The role tables and the proposals of the caller's tenant (its RLS)."""

    async def list_roles(self, context: AccessContext) -> list[RoleSummary]:
        """Every live role, `assignable_by_me` from `platform.rbac_refusals`
        for a grantee other than the caller at the caller's workspace."""
        ...

    async def get_role(self, context: AccessContext, role_id: uuid.UUID) -> RoleDetail | None: ...

    async def role_by_key(self, context: AccessContext, key: str) -> RoleDetail | None:
        """A role of this key, soft-deleted ones included (a key is never reused)."""
        ...

    async def list_assignments(
        self, context: AccessContext, role_id: uuid.UUID
    ) -> list[RoleAssignmentRow]: ...

    async def list_templates(self) -> list[RoleTemplate]: ...

    async def catalogue(self, keys: frozenset[str]) -> Mapping[str, CatalogueKey]: ...

    async def refusals(
        self, context: AccessContext, changes: Sequence[Mapping[str, object]]
    ) -> list[Refusal]:
        """`platform.rbac_refusals` for the caller, every change in one ask."""
        ...

    async def has_checker(self, context: AccessContext, permission: str) -> bool:
        """`platform.checker_candidates` names someone but the caller."""
        ...

    async def propose(
        self,
        context: AccessContext,
        proposal: NewProposal,
        *,
        expected: ExpectedVersion | None,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> Proposal:
        """Write the proposal and its audit event in one transaction. With
        ``expected``, the role row is locked and compared first: stale is 412,
        a role gone is 404. An assignment's base version is read under that
        lock when ``proposal.base_version`` is None and it names a role."""
        ...

    async def apply_narrowing(
        self,
        context: AccessContext,
        role_id: uuid.UUID,
        *,
        expected: ExpectedVersion,
        target: Sequence[Privilege] | None,
        delete: bool,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> RoleDetail:
        """Under the role row's lock and ``expected`` (412): set the privileges
        to ``target``, or soft-delete the role (409 `role_in_use` when it is
        held), with ``audit``, in one transaction."""
        ...

    async def get_proposal(
        self, context: AccessContext, request_id: uuid.UUID
    ) -> Proposal | None: ...

    async def list_open_proposals(
        self, context: AccessContext, request: PageRequest
    ) -> Page[Proposal]: ...

    async def confirm(
        self,
        context: AccessContext,
        request_id: uuid.UUID,
        *,
        audits: ConfirmAudits,
        effect: PendingEffect | None = None,
    ) -> ConfirmOutcome:
        """Lock the proposal, refuse in the ticket's order (404, 403, 409
        `second_person_required`, `proposal_closed`, `proposal_expired`,
        `proposal_stale`), confirm it and apply its payload in this caller's
        transaction, with the two audit events. A refusal by the database at
        apply is read back as its domain error and nothing changes."""
        ...

    async def withdraw(
        self,
        context: AccessContext,
        request_id: uuid.UUID,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> Proposal: ...


class ConfirmAudits(Protocol):
    """The two audit events of a confirmation, made once the proposal is read."""

    def confirmed(self, proposal: Proposal) -> AuditEvent: ...

    def applied(self, proposal: Proposal, details: Mapping[str, object]) -> AuditEvent: ...


@dataclass(frozen=True)
class AuditFactory:
    """One shape for every audit event of this service: ids and codes only."""

    clock: UtcClock
    ids: IdGenerator
    context: AccessContext

    def event(
        self,
        action: str,
        resource_type: str,
        resource_id: object,
        details: Mapping[str, object],
        *,
        workspace_id: uuid.UUID | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            id=self.ids.new_uuid(),
            tenant_id=TenantId(self.context.tenant_id),
            workspace_id=WorkspaceId(workspace_id or self.context.workspace_id),
            actor_id=UserId(self.context.principal_id),
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )

    def proposed(self, proposal: NewProposal) -> AuditEvent:
        return self.event(
            ACTION_PROPOSED,
            "role_change_request",
            proposal.id,
            {
                "request_id": str(proposal.id),
                "kind": proposal.kind,
                "role_id": str(proposal.role_id or proposal.payload.get("role_id")),
                **_assignment_ids(proposal.payload),
            },
        )

    def confirmed(self, proposal: Proposal) -> AuditEvent:
        return self.event(
            ACTION_CONFIRMED,
            "role_change_request",
            proposal.id,
            {
                "request_id": str(proposal.id),
                "kind": proposal.kind,
                "role_id": str(proposal.role_id or proposal.payload.get("role_id")),
                "proposed_by": str(proposal.proposed_by),
                **_assignment_ids(proposal.payload),
            },
        )

    def applied(self, proposal: Proposal, details: Mapping[str, object]) -> AuditEvent:
        action, resource = _APPLIED[proposal.kind]
        role_id = proposal.role_id or uuid.UUID(str(proposal.payload["role_id"]))
        return self.event(
            action,
            resource,
            details.get("assignment_id", role_id),
            {"request_id": str(proposal.id), "role_id": str(role_id), **details},
            workspace_id=_workspace_of(proposal.payload),
        )


_APPLIED: Mapping[ProposalKind, tuple[str, str]] = {
    "role_create": (ACTION_ROLE_CREATE, "role"),
    "role_update": (ACTION_ROLE_UPDATE, "role"),
    "role_permissions": (ACTION_ROLE_PERMISSIONS, "role"),
    "assignment_grant": (ACTION_GRANT, "role_assignment"),
}


def _assignment_ids(payload: Mapping[str, object]) -> dict[str, str]:
    return {
        k: str(payload[k]) for k in ("membership_id", "workspace_id", "user_id") if k in payload
    }


def _workspace_of(payload: Mapping[str, object]) -> uuid.UUID | None:
    found = payload.get("workspace_id")
    return uuid.UUID(str(found)) if found else None


@dataclass(frozen=True)
class RoleAdminService:
    repo: RoleAdminRepositoryPort
    authz: AuthorizationPort
    clock: UtcClock
    ids: IdGenerator

    def _audits(self, context: AccessContext) -> AuditFactory:
        return AuditFactory(self.clock, self.ids, context)

    # ---- reads ----
    async def list_roles(self, context: AccessContext) -> list[RoleSummary]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="role")
        return await self.repo.list_roles(context)

    async def get_role(self, context: AccessContext, role_id: uuid.UUID) -> RoleDetail:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="role")
        return await self._live_role(context, role_id)

    async def list_assignments(
        self, context: AccessContext, role_id: uuid.UUID
    ) -> list[RoleAssignmentRow]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="role")
        await self._live_role(context, role_id)
        return await self.repo.list_assignments(context, role_id)

    async def list_templates(self, context: AccessContext) -> list[RoleTemplate]:
        await self.authz.require(context=context, action=ROLES_READ, resource_type="role")
        return await self.repo.list_templates()

    async def list_proposals(self, context: AccessContext, request: PageRequest) -> Page[Proposal]:
        await self.authz.require(
            context=context, action=ROLES_READ, resource_type="role_change_request"
        )
        return await self.repo.list_open_proposals(context, request)

    # ---- changes that widen: proposals ----
    async def create_role(
        self, context: AccessContext, command: CreateRole, *, effect: PendingEffect | None = None
    ) -> Proposal:
        await self.authz.require(context=context, action=ROLES_WRITE, resource_type="role")
        key = command.key.strip()
        name = command.name.strip()
        if not _KEY.fullmatch(key):
            raise DomainError(
                "a role key is lowercase letters, digits and _",
                details={"errors": [{"pointer": "/key", "detail": "invalid key"}]},
            )
        if not name:
            raise DomainError(
                "a role needs a name",
                details={"errors": [{"pointer": "/name", "detail": "required"}]},
            )
        if command.from_template is not None and command.clone_of is not None:
            raise DomainError("from_template or clone_of, not both")
        privileges, template_key = await self._source(context, command)
        role_id = self.ids.new_uuid()
        changes: list[dict[str, object]] = [
            {"op": "role_create", "role_id": str(role_id), "role_key": key}
        ]
        changes += privilege_changes(role_id, PrivilegeDiff(added=privileges))
        _refuse_if_any(await self.repo.refusals(context, changes))
        if await self.repo.role_by_key(context, key) is not None:
            raise conflict("this company already has a role with that key", "role_key_taken")
        proposal = NewProposal(
            id=self.ids.new_uuid(),
            kind="role_create",
            role_id=None,
            base_version=None,
            payload={
                "role_id": str(role_id),
                "key": key,
                "name": name,
                "description": command.description,
                "kind": command.kind,
                "template_key": template_key,
                "permissions": [p.as_json() for p in privileges],
            },
        )
        return await self._propose(context, proposal, expected=None, effect=effect)

    async def update_role(
        self,
        context: AccessContext,
        role_id: uuid.UUID,
        expected: ExpectedVersion,
        patch: Mapping[str, object],
        *,
        effect: PendingEffect | None = None,
    ) -> Proposal | RoleDetail:
        """A proposal (202), or the role unchanged when the patch changes nothing."""
        await self.authz.require(context=context, action=ROLES_WRITE, resource_type="role")
        role = await self._live_role(context, role_id)
        unknown = sorted(set(patch) - {"name", "description"})
        if unknown:
            raise DomainError(
                "only name and description change here",
                details={
                    "errors": [{"pointer": f"/{k}", "detail": "not editable"} for k in unknown]
                },
            )
        name = patch.get("name", role.name)
        description = patch.get("description", role.description)
        if not isinstance(name, str) or not name.strip():
            raise DomainError(
                "a role needs a name",
                details={"errors": [{"pointer": "/name", "detail": "required"}]},
            )
        if description is not None and not isinstance(description, str):
            raise DomainError(
                "a description is text",
                details={"errors": [{"pointer": "/description", "detail": "not text"}]},
            )
        if not expected.matches(role.version):
            raise _stale_if_match()
        if name.strip() == role.name and description == role.description:
            return role
        proposal = NewProposal(
            id=self.ids.new_uuid(),
            kind="role_update",
            role_id=role_id,
            base_version=expected.version,
            payload={"name": name.strip(), "description": description},
        )
        _refuse_if_any(
            await self.repo.refusals(
                context, [{"op": "role_update", "role_id": str(role_id), "role_key": role.key}]
            )
        )
        return await self._propose(context, proposal, expected=expected, effect=effect)

    async def set_permissions(
        self,
        context: AccessContext,
        role_id: uuid.UUID,
        expected: ExpectedVersion,
        permissions: Sequence[Privilege],
        *,
        effect: PendingEffect | None = None,
    ) -> Proposal | RoleDetail:
        """Applied at once (200) when it only narrows, else a proposal (202)."""
        await self.authz.require(context=context, action=ROLES_WRITE, resource_type="role")
        role = await self._live_role(context, role_id)
        if role.key == "tenant_owner":
            raise rbac_refusal_error([Refusal("role_is_system")]) or AssertionError()
        target = await self._checked_privileges(permissions)
        if not expected.matches(role.version):
            raise _stale_if_match()
        diff = diff_privileges(role.privileges, target)
        _refuse_if_any(await self.repo.refusals(context, privilege_changes(role_id, diff)))
        if not diff.widens:
            if diff.empty:
                return role
            return await self.repo.apply_narrowing(
                context,
                role_id,
                expected=expected,
                target=target,
                delete=False,
                audit=self._audits(context).event(
                    ACTION_ROLE_PERMISSIONS,
                    "role",
                    role_id,
                    {"role_id": str(role_id), "role_key": role.key, **_diff_details(diff)},
                ),
                effect=effect,
            )
        proposal = NewProposal(
            id=self.ids.new_uuid(),
            kind="role_permissions",
            role_id=role_id,
            base_version=expected.version,
            payload={"permissions": [p.as_json() for p in target]},
        )
        return await self._propose(context, proposal, expected=expected, effect=effect)

    async def delete_role(
        self,
        context: AccessContext,
        role_id: uuid.UUID,
        expected: ExpectedVersion,
        *,
        effect: PendingEffect | None = None,
    ) -> RoleDetail:
        """A soft delete of a role nobody holds: one person and one audit event
        (R7.6, Quyết định 24/10/2026)."""
        await self.authz.require(context=context, action=ROLES_WRITE, resource_type="role")
        role = await self._live_role(context, role_id)
        if role.key in SYSTEM_ROLES:
            raise rbac_refusal_error([Refusal("role_is_system")]) or AssertionError()
        if not expected.matches(role.version):
            raise _stale_if_match()
        if role.holder_count:
            raise conflict(
                "this role is still assigned", "role_in_use", holder_count=role.holder_count
            )
        _refuse_if_any(
            await self.repo.refusals(
                context, [{"op": "role_delete", "role_id": str(role_id), "role_key": role.key}]
            )
        )
        return await self.repo.apply_narrowing(
            context,
            role_id,
            expected=expected,
            target=None,
            delete=True,
            audit=self._audits(context).event(
                ACTION_ROLE_DELETE, "role", role_id, {"role_id": str(role_id), "role_key": role.key}
            ),
            effect=effect,
        )

    # ---- the second person ----
    async def require_may_confirm(self, context: AccessContext, request_id: uuid.UUID) -> Proposal:
        """404 for a request outside the tenant, then 403 unless the caller
        holds the proposal's permission: the check the confirm route declares
        for its idempotency key too."""
        proposal = await self.repo.get_proposal(context, request_id)
        if proposal is None:
            raise NotFoundError("no such role change request")
        if proposal.kind == "assignment_grant":
            await self.authz.require(
                context=context, action=ROLES_BIND, resource_type="role_change_request"
            )
        else:
            await self.authz.require(
                context=context, action=ROLES_WRITE, resource_type="role_change_request"
            )
        return proposal

    async def confirm(
        self,
        context: AccessContext,
        request_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> ConfirmOutcome:
        proposal = await self.require_may_confirm(context, request_id)
        if proposal.proposed_by == context.principal_id:
            raise conflict("a second person confirms a role change", "second_person_required")
        return await self.repo.confirm(
            context, request_id, audits=self._audits(context), effect=effect
        )

    async def require_may_withdraw(self, context: AccessContext, request_id: uuid.UUID) -> Proposal:
        """The proposer, or a holder of the proposal's permission; 404 first."""
        proposal = await self.repo.get_proposal(context, request_id)
        if proposal is None:
            raise NotFoundError("no such role change request")
        if proposal.proposed_by != context.principal_id:
            await self.require_may_confirm(context, request_id)
        return proposal

    async def withdraw(
        self,
        context: AccessContext,
        request_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> Proposal:
        proposal = await self.require_may_withdraw(context, request_id)
        return await self.repo.withdraw(
            context,
            request_id,
            audit=self._audits(context).event(
                ACTION_WITHDRAWN,
                "role_change_request",
                request_id,
                {"request_id": str(request_id), "kind": proposal.kind},
            ),
            effect=effect,
        )

    # ---- helpers ----
    async def _propose(
        self,
        context: AccessContext,
        proposal: NewProposal,
        *,
        expected: ExpectedVersion | None,
        effect: PendingEffect | None,
    ) -> Proposal:
        if not await self.repo.has_checker(context, proposal.required_permission):
            raise conflict("nobody else here could confirm this change", "no_checker_available")
        return await self.repo.propose(
            context,
            proposal,
            expected=expected,
            audit=self._audits(context).proposed(proposal),
            effect=effect,
        )

    async def _live_role(self, context: AccessContext, role_id: uuid.UUID) -> RoleDetail:
        role = await self.repo.get_role(context, role_id)
        if role is None or role.deleted:
            raise NotFoundError("no such role")
        return role

    async def _source(
        self, context: AccessContext, command: CreateRole
    ) -> tuple[tuple[Privilege, ...], str | None]:
        """The privileges a new role starts with, read now: the confirmation
        never reads the template or the source role again."""
        if command.from_template is not None:
            for template in await self.repo.list_templates():
                if template.key == command.from_template:
                    return template.privileges, template.key
            raise DomainError(
                "no such role template",
                details={"errors": [{"pointer": "/from_template", "detail": "unknown"}]},
            )
        if command.clone_of is not None:
            source = await self.repo.get_role(context, command.clone_of)
            # Another tenant's id answers as one that does not exist (M19).
            if source is None or source.deleted or source.key == "tenant_owner":
                raise DomainError(
                    "no such role to clone",
                    details={"errors": [{"pointer": "/clone_of", "detail": "unknown"}]},
                )
            return source.privileges, None
        return (), None

    async def _checked_privileges(self, permissions: Sequence[Privilege]) -> tuple[Privilege, ...]:
        seen: dict[str, Privilege] = {}
        errors: list[dict[str, str]] = []
        catalogue = await self.repo.catalogue(frozenset(p.key for p in permissions))
        for index, privilege in enumerate(permissions):
            known = catalogue.get(privilege.key)
            pointer = f"/permissions/{index}"
            if privilege.key in seen:
                errors.append({"pointer": pointer, "detail": "listed twice"})
            elif known is None or known.status == "retired":
                errors.append({"pointer": f"{pointer}/key", "detail": "unknown key"})
            elif privilege.depth not in known.allowed_depths:
                errors.append({"pointer": f"{pointer}/depth", "detail": "depth not allowed"})
            seen[privilege.key] = privilege
        if errors:
            raise DomainError("these privileges cannot be set", details={"errors": errors})
        return tuple(sorted(seen.values()))


def _stale_if_match() -> DWError:
    from dw_kernel.errors import PreconditionFailedError

    return PreconditionFailedError(
        "the role changed since you read it", details={"header": "If-Match"}
    )


def _diff_details(diff: PrivilegeDiff) -> dict[str, object]:
    return {
        "added": [p.as_json() for p in diff.added],
        "raised": [p.as_json() for p in diff.raised],
        "removed": [p.as_json() for p in diff.removed],
        "lowered": [p.as_json() for p in diff.lowered],
    }


__all__ = [
    "ROLES_BIND",
    "ROLES_READ",
    "ROLES_WRITE",
    "AuditFactory",
    "CatalogueKey",
    "ConfirmAudits",
    "ConfirmOutcome",
    "CreateRole",
    "NewProposal",
    "Privilege",
    "PrivilegeDiff",
    "Proposal",
    "Refusal",
    "RoleAdminRepositoryPort",
    "RoleAdminService",
    "RoleAssignmentRow",
    "RoleDetail",
    "RoleSummary",
    "RoleTemplate",
    "conflict",
    "diff_privileges",
    "field",
    "privilege_changes",
    "rbac_refusal_error",
]
