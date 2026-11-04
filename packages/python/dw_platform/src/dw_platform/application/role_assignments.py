"""Who holds which role, as company administrators change it (tenant-rbac
ticket 03, step 6; R6, R7.1, R7.6, R8.2).

The four routes that place a person (`PUT .../memberships`, `POST /admin/members`,
`POST /admin/invitations`, `PUT .../permission-sets`) come here. The membership
and the company row are the route's own business (`platform.members.write`);
every role a request touches also needs `platform.roles.bind` (R8.2), and the
unit is one assignment, one membership and one role:

- a role removed is revoked at once with one audit event (only narrows, R7.6);
- a role added is a proposal `assignment_grant`, applied when another holder of
  `platform.roles.bind` confirms it (R7.1), so an invited person holds nothing
  until then, `member` included;
- a membership with no role grants nothing (R2.5), so the person, their company
  row and their memberships are written at once.

Every check runs before the first write, and one refusal refuses the whole
request with nothing written (ADR-0104 decision 10): unknown roles (404), the
hold rule and its siblings (`platform.rbac_refusals`: 403 `rbac_escalation`,
`rbac_self_assignment`, 422 `rbac_not_grantable`), a critical role for a service
account (422 `role_not_allowed_for_service`, the guard of org-and-principals 03
decides again at the confirmation), a Digital Worker principal (409
`dw_principal_roles_fixed`), and nobody else to confirm (409
`no_checker_available`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.membership_admin import MEMBERS_WRITE
from dw_platform.application.ports import AuthorizationPort
from dw_platform.application.role_admin import (
    ROLES_BIND,
    AuditFactory,
    Refusal,
    conflict,
    rbac_refusal_error,
)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True, slots=True)
class TenantRole:
    id: uuid.UUID
    key: str
    kind: str
    critical: bool


@dataclass(frozen=True, slots=True)
class HeldRole:
    assignment_id: uuid.UUID
    role_id: uuid.UUID
    key: str
    kind: str


@dataclass(frozen=True, slots=True)
class MembershipHolding:
    membership_id: uuid.UUID
    roles: Mapping[str, HeldRole]


@dataclass(frozen=True, slots=True)
class MemberHoldings:
    """A person in this tenant: their kind, whether they are a Digital
    Worker's principal, and the roles assigned on each of their memberships."""

    user_id: uuid.UUID
    kind: Literal["human", "service"]
    dw_principal: bool
    memberships: Mapping[uuid.UUID, MembershipHolding]


@dataclass(frozen=True, slots=True)
class Revoke:
    assignment_id: uuid.UUID
    role_id: uuid.UUID
    role_key: str
    workspace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class GrantRole:
    role_id: uuid.UUID
    role_key: str
    workspace_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AssignmentPlan:
    """What one request does, decided before anything is written."""

    user_id: uuid.UUID | None
    new_memberships: tuple[uuid.UUID, ...] = ()
    revokes: tuple[Revoke, ...] = ()
    dropped_memberships: tuple[uuid.UUID, ...] = ()
    grants: tuple[GrantRole, ...] = ()

    @property
    def touches_roles(self) -> bool:
        return bool(self.revokes or self.grants)


@dataclass(frozen=True, slots=True)
class AssignmentOutcome:
    user_id: uuid.UUID
    applied: tuple[Revoke, ...]
    proposals: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class PersonRef:
    user_id: uuid.UUID
    email: str | None
    display_name: str


@dataclass(frozen=True, slots=True)
class WorkspaceRoles:
    workspace_id: uuid.UUID
    role_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class SetMemberships:
    user_id: uuid.UUID
    memberships: tuple[WorkspaceRoles, ...]


@dataclass(frozen=True, slots=True)
class InviteMember:
    display_name: str
    email: str
    memberships: tuple[WorkspaceRoles, ...]


@dataclass(frozen=True, slots=True)
class GrantMembership:
    email: str
    workspace_id: uuid.UUID
    role_keys: frozenset[str]
    department: str = "general"


@dataclass(frozen=True, slots=True)
class SetPermissionSets:
    user_id: uuid.UUID
    permission_set_keys: frozenset[str]


class RoleAssignmentRepositoryPort(Protocol):
    """Memberships, assignments and proposals of the caller's tenant (its RLS)."""

    async def holdings(self, context: AccessContext, user_id: uuid.UUID) -> MemberHoldings | None:
        """None when the person has no membership in this tenant."""
        ...

    async def tenant_roles(
        self, context: AccessContext, keys: frozenset[str]
    ) -> Mapping[str, TenantRole]:
        """The live roles of these keys, with `platform.role_is_critical`."""
        ...

    async def refusals(
        self, context: AccessContext, changes: Sequence[Mapping[str, object]]
    ) -> list[Refusal]: ...

    async def has_checker(self, context: AccessContext, permission: str) -> bool: ...

    async def find_person(self, email: str) -> PersonRef | None:
        """A human who has signed in, by lower-cased email."""
        ...

    async def open_grants(self, context: AccessContext, user_id: uuid.UUID) -> list[uuid.UUID]:
        """The person's assignment proposals still waiting for a second person."""
        ...

    async def apply(
        self,
        context: AccessContext,
        plan: AssignmentPlan,
        *,
        audits: AuditFactory,
        member_status: Literal["invited", "active"] | None = None,
        department: str = "general",
        effect: PendingEffect | None = None,
    ) -> AssignmentOutcome:
        """In one transaction, role rows locked first: the company row when
        ``member_status`` asks for one, new memberships, revocations and dropped
        memberships (an audit each), and a proposal per grant (an audit each).
        NotFoundError for a workspace outside the tenant."""
        ...

    async def invite(
        self,
        context: AccessContext,
        *,
        display_name: str,
        email: str,
        plan: AssignmentPlan,
        audits: AuditFactory,
        effect: PendingEffect | None = None,
    ) -> tuple[PersonRef, AssignmentOutcome]:
        """Find or create the person (409 `member_email_exists_in_tenant` when
        already here), their company row `invited`, then `apply` for them."""
        ...


@dataclass(frozen=True)
class RoleAssignmentService:
    repo: RoleAssignmentRepositoryPort
    authz: AuthorizationPort
    clock: UtcClock
    ids: IdGenerator

    async def set_memberships(
        self,
        context: AccessContext,
        command: SetMemberships,
        *,
        effect: PendingEffect | None = None,
    ) -> AssignmentOutcome:
        """Replace a person's roles workspace by workspace: a workspace in the
        body without a membership gets one, a workspace left out (or with no
        role) loses its membership and every role on it."""
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type="membership")
        held = await self.repo.holdings(context, command.user_id)
        if held is None:
            raise NotFoundError(
                "no such member in this tenant", details={"user_id": str(command.user_id)}
            )
        desired = _by_workspace(command.memberships)
        roles = await self._roles(context, desired)
        revokes: list[Revoke] = []
        grants: list[GrantRole] = []
        new: list[uuid.UUID] = []
        dropped: list[uuid.UUID] = []
        for ws in sorted(set(held.memberships) | set(desired), key=str):
            now = held.memberships.get(ws)
            want = desired.get(ws, frozenset())
            # Permission sets stay: they are `PUT .../permission-sets`'s; a
            # membership that goes takes them with it, each one a revocation.
            held_here = dict(now.roles) if now else {}
            dropping = now is not None and not want
            current = {k: r for k, r in held_here.items() if dropping or r.kind == "role"}
            revokes += [
                Revoke(r.assignment_id, r.role_id, r.key, ws)
                for key, r in sorted(current.items())
                if key not in want
            ]
            grants += [
                GrantRole(roles[key].id, key, ws) for key in sorted(want) if key not in current
            ]
            if now is None and want:
                new.append(ws)
            elif now is not None and not want:
                dropped.append(ws)
        plan = AssignmentPlan(
            user_id=command.user_id,
            new_memberships=tuple(new),
            revokes=tuple(revokes),
            dropped_memberships=tuple(dropped),
            grants=tuple(grants),
        )
        await self._check(context, plan, held=held, roles=roles)
        return await self.repo.apply(
            context, plan, audits=AuditFactory(self.clock, self.ids, context), effect=effect
        )

    async def grant_member(
        self,
        context: AccessContext,
        command: GrantMembership,
        *,
        effect: PendingEffect | None = None,
    ) -> tuple[PersonRef, AssignmentOutcome]:
        """Place someone who has signed in in one workspace, their roles proposed."""
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type="membership")
        if not command.role_keys:
            raise DomainError("a membership needs at least one role")
        roles = await self._roles(context, {command.workspace_id: command.role_keys})
        person = await self.repo.find_person(command.email)
        if person is None:
            raise NotFoundError(
                "no user with that email has signed in yet", details={"email": command.email}
            )
        held = await self.repo.holdings(context, person.user_id)
        now = held.memberships.get(command.workspace_id) if held else None
        current = {k: r for k, r in (now.roles if now else {}).items() if r.kind == "role"}
        plan = AssignmentPlan(
            user_id=person.user_id,
            new_memberships=() if now else (command.workspace_id,),
            grants=tuple(
                GrantRole(roles[key].id, key, command.workspace_id)
                for key in sorted(command.role_keys)
                if key not in current
            ),
        )
        await self._check(context, plan, held=held, roles=roles)
        outcome = await self.repo.apply(
            context,
            plan,
            audits=AuditFactory(self.clock, self.ids, context),
            member_status="invited",
            department=command.department,
            effect=effect,
        )
        return person, outcome

    async def invite(
        self, context: AccessContext, command: InviteMember, *, effect: PendingEffect | None = None
    ) -> tuple[PersonRef, AssignmentOutcome]:
        """Create the person (no sign-in yet) and their memberships; every role
        of the invitation, `member` included, is a proposal (R7.1)."""
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type="membership")
        display_name = command.display_name.strip()
        if not 4 <= len(display_name) <= 120:
            raise DomainError("a display name of 4 to 120 characters is required")
        email = command.email.strip().lower()
        if not _EMAIL.fullmatch(email):
            raise DomainError("a valid email is required")
        desired = {ws: keys for ws, keys in _by_workspace(command.memberships).items() if keys}
        if not desired:
            raise DomainError("an invitation needs at least one workspace with a role")
        roles = await self._roles(context, desired)
        plan = AssignmentPlan(
            user_id=None,
            new_memberships=tuple(sorted(desired, key=str)),
            grants=tuple(
                GrantRole(roles[key].id, key, ws)
                for ws, keys in sorted(desired.items(), key=lambda item: str(item[0]))
                for key in sorted(keys)
            ),
        )
        await self._check(context, plan, held=None, roles=roles)
        return await self.repo.invite(
            context,
            display_name=display_name,
            email=email,
            plan=plan,
            audits=AuditFactory(self.clock, self.ids, context),
            effect=effect,
        )

    async def set_permission_sets(
        self,
        context: AccessContext,
        command: SetPermissionSets,
        *,
        effect: PendingEffect | None = None,
    ) -> AssignmentOutcome:
        """Replace a member's permission sets in the caller's workspace (roles
        of kind `permission_set`); their other roles there stay."""
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type="membership")
        held = await self.repo.holdings(context, command.user_id)
        now = held.memberships.get(context.workspace_id) if held else None
        if held is None or now is None:
            raise NotFoundError(
                "no such member in this workspace", details={"user_id": str(command.user_id)}
            )
        roles = await self._roles(
            context, {context.workspace_id: command.permission_set_keys}, kind="permission_set"
        )
        current = {k: r for k, r in now.roles.items() if r.kind == "permission_set"}
        plan = AssignmentPlan(
            user_id=command.user_id,
            revokes=tuple(
                Revoke(r.assignment_id, r.role_id, k, context.workspace_id)
                for k, r in sorted(current.items())
                if k not in command.permission_set_keys
            ),
            grants=tuple(
                GrantRole(roles[k].id, k, context.workspace_id)
                for k in sorted(command.permission_set_keys)
                if k not in current
            ),
        )
        await self._check(context, plan, held=held, roles=roles)
        return await self.repo.apply(
            context, plan, audits=AuditFactory(self.clock, self.ids, context), effect=effect
        )

    async def open_grants(self, context: AccessContext, user_id: uuid.UUID) -> list[uuid.UUID]:
        """What a retried request is answered with (app-standards R2.29): the
        person's role proposals still waiting, read under the caller's own
        authority now."""
        await self.authz.require(context=context, action=MEMBERS_WRITE, resource_type="membership")
        return await self.repo.open_grants(context, user_id)

    async def _roles(
        self,
        context: AccessContext,
        desired: Mapping[uuid.UUID, frozenset[str]],
        kind: str = "role",
    ) -> Mapping[str, TenantRole]:
        """The live tenant roles of ``kind`` the request names; 404 for any
        other key (a role of the other kind included: memberships carry roles,
        `PUT .../permission-sets` carries permission sets)."""
        asked = frozenset(key for keys in desired.values() for key in keys)
        roles = await self.repo.tenant_roles(context, asked)
        unknown = sorted(k for k in asked if k not in roles or roles[k].kind != kind)
        if unknown:
            if kind == "permission_set":
                raise NotFoundError("unknown permission set", details={"keys": unknown})
            raise NotFoundError("unknown role", details={"roles": unknown})
        return roles

    async def _check(
        self,
        context: AccessContext,
        plan: AssignmentPlan,
        *,
        held: MemberHoldings | None,
        roles: Mapping[str, TenantRole],
    ) -> None:
        """Every refusal before the first write (ADR-0104 decision 10)."""
        if not plan.touches_roles:
            return
        await self.authz.require(
            context=context, action=ROLES_BIND, resource_type="role_assignment"
        )
        if plan.grants and held is not None and held.dw_principal:
            raise conflict(
                "the roles of a digital worker's principal are fixed when it is made",
                "dw_principal_roles_fixed",
            )
        if plan.grants and held is not None and held.kind == "service":
            critical = sorted(g.role_key for g in plan.grants if roles[g.role_key].critical)
            if critical:
                raise DomainError(
                    "a service account holds no critical role",
                    details={"reason_code": "role_not_allowed_for_service", "roles": critical},
                )
        changes: list[dict[str, object]] = [
            {"op": "revoke", "role_id": str(r.role_id), "workspace_id": str(r.workspace_id)}
            for r in plan.revokes
        ]
        changes += [
            {
                "op": "grant",
                "role_id": str(g.role_id),
                "workspace_id": str(g.workspace_id),
                "user_id": str(plan.user_id) if plan.user_id else "",
            }
            for g in plan.grants
        ]
        error = rbac_refusal_error(await self.repo.refusals(context, changes))
        if error is not None:
            raise error
        if plan.grants and not await self.repo.has_checker(context, ROLES_BIND):
            raise conflict("nobody else here could confirm this change", "no_checker_available")


def _by_workspace(rows: Sequence[WorkspaceRoles]) -> dict[uuid.UUID, frozenset[str]]:
    merged: dict[uuid.UUID, frozenset[str]] = {}
    for row in rows:
        if row.workspace_id in merged:
            raise DomainError(
                "a workspace appears twice", details={"workspace_id": str(row.workspace_id)}
            )
        merged[row.workspace_id] = row.role_keys
    return merged
