"""Digital Workers as their owners create and run them (digital-worker R1, R2).

A DW acts under a service principal of its own (ADR-0103 decision 2): a
`platform.users` row of kind `service`, a `platform.service_principals` row
whose owner is the Business Owner, and one membership in the DW's workspace
with the roles its creator gave it. What the principal may do is that
membership's scopes; what the DW may decide alone is each decision class's
effective level (ADR-0128 decision 3).

The rules this service keeps, in the order a request meets them:

- **Reading** takes `dw.read`. A caller without it, a DW of another tenant or
  of another workspace, and an id that does not exist are one answer, 404,
  before any check that would say 403 (R1.5).
- **Creating** takes `dw.manage`. The configuration must be well formed (the
  domain's checks), its tools known to the platform (R1.3), its roles neither
  critical (R1.15) nor wider than the creator's own scopes (R1.10, ADR-0103
  decision 4), and its four people human members of the workspace, the
  Validator one who may decide approvals (R1.2).
- **Changing state or people** takes being the DW's Business Owner or
  Technical Owner, not a scope (R1.6, R1.13; ADR-0128 decision 2). Putting a
  DW into operation the first time takes a second person, who holds every
  scope of the principal's roles (R1.9): the configuration and its earned
  levels are not set to run by one person alone.

The database repeats what it can: the CHECKs on the tables, the accountable
owner (R1.16), no login identity for a service user (R1.11), and roles that
do not grow once the DW exists (R1.17).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from dw_kernel.autonomy import (
    AUTONOMY_LEVELS,
    FAIL_CLOSED_LEVEL,
    AutonomyLevel,
    effect_rung,
    is_autonomy_level,
    lower_autonomy,
    requires_person,
)
from dw_kernel.errors import ConflictError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.membership_admin import forbid_escalation, is_administrative
from dw_platform.application.ports import AuthorizationPort
from dw_platform.domain.approval import APPROVALS_DECIDE
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import (
    DecisionClass,
    DigitalWorker,
    DwConfiguration,
    DwPeople,
    DwState,
    EffectLevel,
    check_transition,
    refused,
)

_log = logging.getLogger(__name__)

DW_READ = "dw.read"
DW_MANAGE = "dw.manage"

_RESOURCE = "digital_worker"
_ACTION_CREATED = "dw.created"
_ACTION_STATE_CHANGED = "dw.state_changed"
_ACTION_PEOPLE_CHANGED = "dw.people_changed"

# R1.15, ADR-0103 decision 2: roles a service principal never holds, besides
# any role carrying an administrative scope. The platform's administrative
# prefix is `platform.` (`is_administrative`); the spec's `admin.*` is checked
# too, so a scope family added under that name later is covered unasked.
CRITICAL_ROLES = frozenset({"tenant_owner", "org_admin", "platform_admin"})
_ADMIN_SCOPE_PREFIX = "admin."


def is_critical_role(key: str, scopes: frozenset[str]) -> bool:
    """Whether a role is out of a service principal's reach (R1.15, R1.18)."""
    return (
        key in CRITICAL_ROLES
        or is_administrative(scopes)
        or any(scope.startswith(_ADMIN_SCOPE_PREFIX) for scope in scopes)
    )


@dataclass(frozen=True, slots=True)
class Standing:
    """A user's membership in the caller's workspace: what kind of user, and
    the scopes the membership holds."""

    kind: Literal["human", "service"]
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class CreateDigitalWorker:
    configuration: DwConfiguration
    people: DwPeople


@dataclass(frozen=True, slots=True)
class ChangeState:
    target: DwState


@dataclass(frozen=True, slots=True)
class DecisionLevels:
    """What a decision class's effective level is read from, at the moment it
    is asked (R2.3): its own ceiling and earned level, and the tenant's."""

    effect_level: EffectLevel
    reversible: bool
    ceiling: str
    earned_level: str
    tenant_ceiling: str


@dataclass(frozen=True, slots=True)
class DwBoundary:
    """What a Digital Worker's run may reach, read when a tool is called
    (digital-worker R6): whether the DW is operating, the tools it is allowed,
    and the scopes its principal's membership holds now (ADR-0103 decision 5:
    reach is read live, so a run narrows when the principal loses a role)."""

    operating: bool
    allowed_tools: frozenset[str]
    scopes: frozenset[str]
    dw_id: uuid.UUID | None = None


class DigitalWorkerRepositoryPort(Protocol):
    """DWs of the caller's tenant and workspace, under their RLS."""

    async def create(
        self,
        context: AccessContext,
        worker: DigitalWorker,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        """Write, in one transaction, the service user, its principal row, its
        membership with the configuration's roles, the DW and its decision
        classes, and `audit`. ``effect`` is claimed first in that transaction."""
        ...

    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker | None: ...

    async def list(self, context: AccessContext, request: PageRequest) -> Page[DigitalWorker]:
        """The workspace's DWs, newest first."""
        ...

    async def change_state(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        *,
        current: DwState,
        target: DwState,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        """Move the DW from ``current`` to ``target`` with ``audit`` in one
        transaction; False when it is no longer at ``current``."""
        ...

    async def replace_people(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        people: DwPeople,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        """Write the four people (the Business Owner on the principal) with
        ``audit`` in one transaction; False when the DW is gone."""
        ...


class ToolCatalogPort(Protocol):
    """The platform's tool register: whether a tool of that name exists."""

    def has_tool(self, name: str) -> bool: ...


class MembershipCheckPort(Protocol):
    async def standing(self, context: AccessContext, user_id: uuid.UUID) -> Standing | None:
        """The user's membership in the caller's workspace, or None."""
        ...


class RoleCatalogPort(Protocol):
    async def role_catalog(self) -> dict[str, frozenset[str]]:
        """Every role key with its scopes."""
        ...


class DecisionLevelsPort(Protocol):
    async def levels(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> DecisionLevels | None:
        """The class's levels and the tenant's ceiling, or None when the class
        does not exist."""
        ...


def _not_found() -> NotFoundError:
    return NotFoundError("no such digital worker")


def _denied(message: str, reason_code: str) -> PermissionDeniedError:
    return PermissionDeniedError(message, details={"reason_code": reason_code})


def _conflict(message: str, reason_code: str) -> ConflictError:
    return ConflictError(message, details={"reason_code": reason_code})


@dataclass(frozen=True)
class DigitalWorkerService:
    repo: DigitalWorkerRepositoryPort
    authz: AuthorizationPort
    tools: ToolCatalogPort
    members: MembershipCheckPort
    roles: RoleCatalogPort
    clock: UtcClock
    id_generator: IdGenerator

    async def create(
        self,
        context: AccessContext,
        command: CreateDigitalWorker,
        *,
        effect: PendingEffect | None = None,
    ) -> DigitalWorker:
        await self.authz.require(context=context, action=DW_MANAGE, resource_type=_RESOURCE)
        configuration = command.configuration
        unknown = sorted(t for t in set(configuration.allowed_tools) if not self.tools.has_tool(t))
        if unknown:
            raise refused("these tools are not on the platform", "tool_unknown", tools=unknown)
        await self._check_roles(context, configuration.role_keys)
        await self._check_people(context, command.people)

        now = self.clock.now()
        worker = DigitalWorker(
            id=self.id_generator.new_uuid(),
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            principal_user_id=self.id_generator.new_uuid(),
            configuration=configuration,
            people=command.people,
            state="draft",
            created_by=context.principal_id,
            created_at=now,
            updated_at=now,
        )
        await self.repo.create(
            context,
            worker,
            audit=self._event(
                context,
                _ACTION_CREATED,
                worker.id,
                {
                    "key": configuration.key,
                    "principal_user_id": str(worker.principal_user_id),
                    "role_keys": sorted(configuration.role_keys),
                    "decision_classes": {
                        c.key: {"ceiling": c.ceiling, "earned_level": c.earned_level}
                        for c in configuration.decision_classes
                    },
                },
            ),
            effect=effect,
        )
        return worker

    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        try:
            await self.authz.require(context=context, action=DW_READ, resource_type=_RESOURCE)
        except PermissionDeniedError:
            raise _not_found() from None
        worker = await self.repo.get(context, dw_id)
        if worker is None:
            raise _not_found()
        return worker

    async def list(self, context: AccessContext, request: PageRequest) -> Page[DigitalWorker]:
        await self.authz.require(context=context, action=DW_READ, resource_type=_RESOURCE)
        return await self.repo.list(context, request)

    async def require_owner(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        """The DW, when the caller is its Business Owner or Technical Owner:
        404 before 403 (R1.5), then 403 `not_dw_owner` (R1.6). The check a
        write route declares for its idempotency key, too."""
        worker = await self.get(context, dw_id)
        if context.principal_id not in worker.people.owners():
            raise _denied("only the DW's business or technical owner may", "not_dw_owner")
        return worker

    async def change_state(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        command: ChangeState,
        *,
        effect: PendingEffect | None = None,
    ) -> DigitalWorker:
        worker = await self.require_owner(context, dw_id)
        check_transition(worker.state, command.target)
        if worker.state == "draft" and command.target == "operating":
            await self._second_person(context, worker)
        changed = await self.repo.change_state(
            context,
            dw_id,
            current=worker.state,
            target=command.target,
            audit=self._event(
                context,
                _ACTION_STATE_CHANGED,
                dw_id,
                {"from": worker.state, "to": command.target},
            ),
            effect=effect,
        )
        if not changed:
            # Someone moved it first; what it is now decides, not what it was.
            current = await self.get(context, dw_id)
            check_transition(current.state, command.target)
            raise _conflict("the digital worker changed meanwhile; try again", "state_changed")
        return await self.get(context, dw_id)

    async def replace_people(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        people: DwPeople,
        *,
        effect: PendingEffect | None = None,
    ) -> DigitalWorker:
        worker = await self.require_owner(context, dw_id)
        await self._check_people(context, people)
        replaced = await self.repo.replace_people(
            context,
            dw_id,
            people,
            audit=self._event(
                context,
                _ACTION_PEOPLE_CHANGED,
                dw_id,
                {"before": _people_details(worker.people), "after": _people_details(people)},
            ),
            effect=effect,
        )
        if not replaced:
            raise _not_found()
        return await self.get(context, dw_id)

    async def _check_roles(self, context: AccessContext, role_keys: frozenset[str]) -> None:
        if not role_keys:
            raise refused("the principal needs at least one role", "roles_empty")
        catalog = await self.roles.role_catalog()
        unknown = role_keys - catalog.keys()
        if unknown:
            raise refused("unknown role", "role_unknown", roles=sorted(unknown))
        critical = sorted(key for key in role_keys if is_critical_role(key, catalog[key]))
        if critical:
            raise refused(
                "a service principal holds no critical role",
                "role_not_allowed_for_service",
                roles=critical,
            )
        granted = frozenset(scope for key in role_keys for scope in catalog[key])
        # ADR-0103 decision 4: no role stands in for a scope here, the platform
        # admin's included; the creator holds every scope they hand out.
        if not granted <= context.scopes:
            raise _denied(
                "the creator does not hold every scope of the principal's roles",
                "grants_not_covered",
            )
        forbid_escalation(context, granted)

    async def _check_people(self, context: AccessContext, people: DwPeople) -> None:
        if people.business_owner_id is None:
            raise refused("a digital worker has a business owner", "owner_not_member")
        named = {
            people.business_owner_id,
            people.technical_owner_id,
            people.work_assigner_id,
            people.validator_id,
        }
        standings = {user_id: await self.members.standing(context, user_id) for user_id in named}
        outside = sorted(
            str(user_id)
            for user_id, standing in standings.items()
            if standing is None or standing.kind != "human"
        )
        if outside:
            raise refused(
                "every person of a DW is a member of its workspace",
                "owner_not_member",
                users=outside,
            )
        validator = standings[people.validator_id]
        if validator is None or APPROVALS_DECIDE not in validator.scopes:
            raise refused("the validator cannot decide approvals", "validator_cannot_decide")

    async def _second_person(self, context: AccessContext, worker: DigitalWorker) -> None:
        """R1.9: who first puts a DW into operation is not who made it, and
        holds every scope its principal holds."""
        if context.principal_id == worker.created_by:
            raise _conflict(
                "a second person puts a new digital worker into operation",
                "second_person_required",
            )
        principal = await self.members.standing(context, worker.principal_user_id)
        held = principal.scopes if principal is not None else frozenset()
        if not held <= context.scopes:
            raise _denied(
                "the caller does not hold every scope of the principal's roles",
                "grants_not_covered",
            )

    def _event(
        self,
        context: AccessContext,
        action: str,
        dw_id: uuid.UUID,
        details: Mapping[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(dw_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )


def _people_details(people: DwPeople) -> dict[str, str | None]:
    return {
        "business_owner_id": str(people.business_owner_id) if people.business_owner_id else None,
        "technical_owner_id": str(people.technical_owner_id),
        "work_assigner_id": str(people.work_assigner_id),
        "validator_id": str(people.validator_id),
    }


@dataclass(frozen=True)
class DecisionAutonomy:
    """How far a DW goes alone on one kind of decision (R2.3, R2.4).

    Read at the moment of asking, not stamped on a run (spec, Quyết định), so
    lowering a level holds at the next gate of a run already under way. The
    effective level is the lowest of three; anything unreadable is `A0`.
    """

    levels: DecisionLevelsPort

    async def effective_level(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> AutonomyLevel:
        found = await self._levels(
            tenant_id=tenant_id, workspace_id=workspace_id, dw_id=dw_id, key=key
        )
        return _effective(found)

    async def requires_person(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> bool:
        found = await self._levels(
            tenant_id=tenant_id, workspace_id=workspace_id, dw_id=dw_id, key=key
        )
        if found is None:
            return True
        rung = effect_rung(found.effect_level, repeatable=found.reversible)
        return requires_person(rung, _effective(found))

    async def _levels(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> DecisionLevels | None:
        try:
            return await self.levels.levels(
                tenant_id=tenant_id, workspace_id=workspace_id, dw_id=dw_id, key=key
            )
        except Exception:
            # R2.3: a level that cannot be read is A0. The gate asks a person,
            # which is recoverable; the failure is logged, not swallowed.
            _log.exception("decision class levels unreadable", extra={"dw_id": str(dw_id)})
            return None


def _effective(found: DecisionLevels | None) -> AutonomyLevel:
    if found is None:
        return FAIL_CLOSED_LEVEL
    three = (found.ceiling, found.earned_level, found.tenant_ceiling)
    if not all(is_autonomy_level(level) for level in three):
        return FAIL_CLOSED_LEVEL
    ceiling, earned, tenant = (AUTONOMY_LEVELS[AUTONOMY_LEVELS.index(level)] for level in three)
    return lower_autonomy(lower_autonomy(ceiling, earned), tenant)


__all__ = [
    "CRITICAL_ROLES",
    "DW_MANAGE",
    "DW_READ",
    "ChangeState",
    "CreateDigitalWorker",
    "DecisionAutonomy",
    "DecisionClass",
    "DecisionLevels",
    "DecisionLevelsPort",
    "DigitalWorkerRepositoryPort",
    "DigitalWorkerService",
    "DwBoundary",
    "MembershipCheckPort",
    "RoleCatalogPort",
    "Standing",
    "ToolCatalogPort",
    "is_critical_role",
]
