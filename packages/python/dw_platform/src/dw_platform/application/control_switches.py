"""Freezing a company, and lifting a freeze with a second person
(agent-lifecycle R7.4-R7.6, R7.10, R7.11; ADR-0120 decisions 5, 7, amended
2026-11-04; D11).

- **Freezing** (`POST /admin/freeze`) is one person's, holding
  `studio.lifecycle.freeze` (a tenant-depth key): one open company-set freeze
  at a time (`already_frozen`), the row and `control.freeze.set` in one
  transaction. Every door of the runtime asks `RunControlPort`, which reads it.
- **Asking to lift** (`POST /admin/unfreeze`) opens a strict, run-less
  `studio.lifecycle.unfreeze` approval stamped `studio.lifecycle.freeze`, its
  payload only the open company-set freeze's `switch_id`; nothing is lifted.
  No company-set freeze open: 403 when an operator's freeze holds the company
  (R7.4: the company cannot lift it), 409 `not_frozen` otherwise; a lift
  already waiting: 409 `lift_pending`, held by a partial unique index.
- **Lifting** (`UnfreezeSettler`, on the worker, at the decision's outbox
  event): an approval lifts exactly that row, `lift_approval_id` written, in
  the decider's name with `details.lane`; the database refuses any other lift
  (`platform.guard_control_switch()`). A rejection, a replay, a row already
  lifted end without error and write nothing.
- **Reading** (`GET /control-state`): every member, codes only.
- **The operators' switches** (`PlatformFreezeService`, the provisioning
  context): a platform freeze, and a freeze of one company with origin
  `platform`, which the company never lifts; each change audited in
  `platform.provisioning_audit` in its own transaction.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import permission_denied
from dw_platform.application.effect_keys import EffectClaim, PendingEffect
from dw_platform.application.ports import AuthorizationPort
from dw_platform.application.provisioning import ProvisioningContext
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest, decided_event_type
from dw_platform.domain.audit import AuditEvent

__all__ = [
    "FREEZE_LIFTED",
    "FREEZE_SET",
    "LIFECYCLE_FREEZE",
    "LIFECYCLE_PREFIX",
    "LIFECYCLE_UNFREEZE",
    "LIFECYCLE_UNFREEZE_DECIDED",
    "PLATFORM_FREEZE_LIFTED",
    "PLATFORM_FREEZE_SET",
    "PLATFORM_TENANT_FREEZE_LIFTED",
    "PLATFORM_TENANT_FREEZE_SET",
    "ControlState",
    "ControlSwitchRepositoryPort",
    "ControlSwitchService",
    "ControlSwitchTx",
    "LiftDecision",
    "OpenFreeze",
    "PlatformFreezeRepositoryPort",
    "PlatformFreezeService",
    "ProvisioningAudit",
    "ReasonCode",
    "UnfreezeSettler",
    "already_frozen",
]

# Every approval type of the lifecycle is strict: its requester never decides
# it (ADR-0104 decision 11). Added with `|=` at both composition roots.
LIFECYCLE_PREFIX = "studio.lifecycle."
LIFECYCLE_FREEZE = "studio.lifecycle.freeze"
LIFECYCLE_UNFREEZE = "studio.lifecycle.unfreeze"
LIFECYCLE_UNFREEZE_DECIDED = decided_event_type(LIFECYCLE_UNFREEZE)

FREEZE_SET = "control.freeze.set"
FREEZE_LIFTED = "control.freeze.lifted"
PLATFORM_FREEZE_SET = "platform.freeze.set"
PLATFORM_FREEZE_LIFTED = "platform.freeze.lifted"
PLATFORM_TENANT_FREEZE_SET = "platform.tenant_freeze.set"
PLATFORM_TENANT_FREEZE_LIFTED = "platform.tenant_freeze.lifted"

# The lane that carries out the decision, named in `details.lane` of the audit
# row standing in the decider's name (ADR-0011).
SETTLING_LANE = "outbox"
_RESOURCE = "control_switch"

ReasonCode = Literal["incident", "maintenance", "abuse", "test", "other"]
Origin = Literal["tenant", "platform"]


@dataclass(frozen=True, slots=True)
class OpenFreeze:
    """An open freeze of a company: the company's own or an operator's."""

    id: uuid.UUID
    origin: Origin
    reason_code: str
    set_at: datetime


@dataclass(frozen=True, slots=True)
class ControlState:
    """What a member is told: codes and times, never a reason's text."""

    platform_freeze_set_at: datetime | None
    platform_freeze_reason_code: str | None
    freezes: tuple[OpenFreeze, ...]

    @property
    def state(self) -> Literal["open", "platform_frozen", "tenant_frozen"]:
        if self.platform_freeze_set_at is not None:
            return "platform_frozen"
        return "tenant_frozen" if self.freezes else "open"


@dataclass(frozen=True, slots=True)
class LiftDecision:
    """A decided `studio.lifecycle.unfreeze` request, as its row says."""

    approved: bool
    switch_id: uuid.UUID | None
    decided_by: uuid.UUID
    requested_by: uuid.UUID
    workspace_id: uuid.UUID


class ControlSwitchTx(Protocol):
    """One transaction under one company's RLS."""

    async def open_freezes(self) -> list[OpenFreeze]: ...

    async def platform_freeze(self) -> tuple[datetime, str] | None: ...

    async def claim(self, claim: EffectClaim) -> None: ...

    async def insert_freeze(
        self,
        *,
        switch_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        set_by: uuid.UUID,
    ) -> None:
        """Raises `ConflictError` `already_frozen` when the company-set freeze
        is already open (the open index, under a race)."""
        ...

    async def open_lift_request(self, request: ApprovalRequest) -> None:
        """Raises `ConflictError` `lift_pending` when a lift of the same switch
        is waiting (the pending index, under a race)."""
        ...

    async def lift_decision(self, approval_id: uuid.UUID) -> LiftDecision | None: ...

    async def lift(self, switch_id: uuid.UUID, *, by: uuid.UUID, approval_id: uuid.UUID) -> bool:
        """Lift the open row; False when it is gone or already lifted."""
        ...

    async def audit(self, event: AuditEvent) -> None: ...


class ControlSwitchRepositoryPort(Protocol):
    def transaction(
        self, tenant_id: uuid.UUID, *, workspace_id: uuid.UUID | None = None
    ) -> AbstractAsyncContextManager[ControlSwitchTx]: ...


@dataclass(frozen=True)
class ControlSwitchService:
    """The company's freeze: set by one person, lifted by two."""

    repo: ControlSwitchRepositoryPort
    authz: AuthorizationPort
    clock: UtcClock
    id_generator: IdGenerator

    async def check_freeze(self, context: AccessContext) -> None:
        """Who may freeze or ask to lift: what the routes' idempotency check
        calls before any key row is read (app-standards R2.30)."""
        await self.authz.require(context=context, action=LIFECYCLE_FREEZE, resource_type=_RESOURCE)

    async def freeze(
        self,
        context: AccessContext,
        *,
        reason_code: ReasonCode,
        reason: str,
        effect: PendingEffect | None = None,
    ) -> uuid.UUID:
        """R7.6: the row and `control.freeze.set` in one transaction."""
        await self.check_freeze(context)
        switch_id = self.id_generator.new_uuid()
        async with self.repo.transaction(
            context.tenant_id, workspace_id=context.workspace_id
        ) as tx:
            if effect is not None:
                await tx.claim(effect.of(switch_id))
            if any(f.origin == "tenant" for f in await tx.open_freezes()):
                raise already_frozen()
            await tx.insert_freeze(
                switch_id=switch_id,
                reason_code=reason_code,
                reason=reason,
                set_by=context.principal_id,
            )
            await tx.audit(
                self._event(
                    context.tenant_id,
                    context.workspace_id,
                    context.principal_id,
                    FREEZE_SET,
                    switch_id,
                    {"reason_code": reason_code},
                )
            )
        return switch_id

    async def request_unfreeze(
        self, context: AccessContext, *, effect: PendingEffect | None = None
    ) -> uuid.UUID:
        """R7.10: a strict run-less approval naming the company-set freeze."""
        await self.check_freeze(context)
        approval_id = self.id_generator.new_uuid()
        async with self.repo.transaction(
            context.tenant_id, workspace_id=context.workspace_id
        ) as tx:
            if effect is not None:
                await tx.claim(effect.of(approval_id))
            freezes = await tx.open_freezes()
            own = next((f for f in freezes if f.origin == "tenant"), None)
            if own is None:
                if freezes:
                    # R7.4: an operator's freeze is not the company's to lift.
                    raise permission_denied(
                        action=LIFECYCLE_FREEZE,
                        resource_type=_RESOURCE,
                        resource_id=str(freezes[0].id),
                    )
                raise ConflictError(
                    "the company is not frozen", details={"reason_code": "not_frozen"}
                )
            await tx.open_lift_request(
                ApprovalRequest(
                    id=approval_id,
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(context.workspace_id),
                    approval_type=LIFECYCLE_UNFREEZE,
                    requested_by=UserId(context.principal_id),
                    reason="studio.lifecycle.unfreeze",
                    payload={"switch_id": str(own.id)},
                    required_scope=LIFECYCLE_FREEZE,
                )
            )
        return approval_id

    async def state(self, context: AccessContext) -> ControlState:
        """Every member of the company: what holds it now, codes only."""
        async with self.repo.transaction(
            context.tenant_id, workspace_id=context.workspace_id
        ) as tx:
            freezes = await tx.open_freezes()
            platform = await tx.platform_freeze()
        return ControlState(
            platform_freeze_set_at=None if platform is None else platform[0],
            platform_freeze_reason_code=None if platform is None else platform[1],
            freezes=tuple(freezes),
        )

    def _event(
        self,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID,
        action: str,
        switch_id: uuid.UUID,
        details: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(tenant_id),
            workspace_id=WorkspaceId(workspace_id),
            actor_id=UserId(actor_id),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(switch_id),
            occurred_at=self.clock.now(),
            details=details,
        )


SettlementOutcome = Literal["lifted", "rejected", "already_lifted"]


@dataclass(frozen=True)
class UnfreezeSettler:
    """R7.10, on the worker, where the decision's outbox event arrives.

    Idempotent by the switch: a replay meets a row already lifted and writes
    nothing, so a redelivery never meets the trigger's refusal."""

    repo: ControlSwitchRepositoryPort
    clock: UtcClock
    id_generator: IdGenerator

    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> SettlementOutcome:
        async with self.repo.transaction(scope.tenant_id) as tx:
            decision = await tx.lift_decision(approval_id)
            if decision is None or decision.switch_id is None:
                raise NotFoundError(
                    "no decided studio.lifecycle.unfreeze approval of that id",
                    details={"approval_id": str(approval_id)},
                )
            if not decision.approved:
                return "rejected"
            if not await tx.lift(
                decision.switch_id, by=decision.decided_by, approval_id=approval_id
            ):
                return "already_lifted"
            await tx.audit(
                AuditEvent(
                    id=self.id_generator.new_uuid(),
                    tenant_id=TenantId(scope.tenant_id),
                    workspace_id=WorkspaceId(decision.workspace_id),
                    # A lane carrying out one person's decision audits that person.
                    actor_id=UserId(decision.decided_by),
                    action=FREEZE_LIFTED,
                    resource_type=_RESOURCE,
                    resource_id=str(decision.switch_id),
                    occurred_at=self.clock.now(),
                    details={
                        "approval_id": str(approval_id),
                        "requested_by": str(decision.requested_by),
                        "lane": SETTLING_LANE,
                    },
                )
            )
        return "lifted"


# ---- the operators' switches --------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvisioningAudit:
    """One `platform.provisioning_audit` row, written in the change's own
    transaction; its target is the row the change touched."""

    id: uuid.UUID
    actor_id: uuid.UUID
    action: str
    target_type: str
    details: dict[str, object]
    occurred_at: datetime


class PlatformFreezeRepositoryPort(Protocol):
    """Writes as `dw_provisioner`, each with its provisioning-audit row in the
    same transaction. `ConflictError` `already_frozen` when one is open;
    `NotFoundError` for an unknown company."""

    async def set_platform_freeze(
        self,
        *,
        freeze_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        audit: ProvisioningAudit,
    ) -> None: ...

    async def lift_platform_freeze(
        self, *, by: uuid.UUID, audit: ProvisioningAudit
    ) -> uuid.UUID | None:
        """The lifted freeze's id; None when none was open."""
        ...

    async def set_tenant_freeze(
        self,
        *,
        tenant_id: uuid.UUID,
        switch_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        audit: ProvisioningAudit,
    ) -> None: ...

    async def lift_tenant_freeze(
        self, *, tenant_id: uuid.UUID, by: uuid.UUID, reason: str | None, audit: ProvisioningAudit
    ) -> uuid.UUID | None:
        """The lifted operator freeze's id; None when none was open. Never
        the company's own freeze (D11)."""
        ...


@dataclass(frozen=True)
class PlatformFreezeService:
    """The operator's switches. The provisioning context is built only for a
    verified operator, so the gate is at the door."""

    repo: PlatformFreezeRepositoryPort
    clock: UtcClock
    ids: IdGenerator

    async def freeze_platform(
        self, context: ProvisioningContext, *, reason_code: ReasonCode, reason: str
    ) -> uuid.UUID:
        freeze_id = self.ids.new_uuid()
        await self.repo.set_platform_freeze(
            freeze_id=freeze_id,
            reason_code=reason_code,
            reason=reason,
            audit=self._audit(context, PLATFORM_FREEZE_SET, {"reason_code": reason_code}),
        )
        return freeze_id

    async def unfreeze_platform(self, context: ProvisioningContext) -> uuid.UUID:
        lifted = await self.repo.lift_platform_freeze(
            by=context.principal_id, audit=self._audit(context, PLATFORM_FREEZE_LIFTED, {})
        )
        if lifted is None:
            raise _not_frozen()
        return lifted

    async def freeze_tenant(
        self,
        context: ProvisioningContext,
        *,
        tenant_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
    ) -> uuid.UUID:
        switch_id = self.ids.new_uuid()
        await self.repo.set_tenant_freeze(
            tenant_id=tenant_id,
            switch_id=switch_id,
            reason_code=reason_code,
            reason=reason,
            audit=self._audit(
                context,
                PLATFORM_TENANT_FREEZE_SET,
                {"tenant_id": str(tenant_id), "reason_code": reason_code},
            ),
        )
        return switch_id

    async def unfreeze_tenant(
        self, context: ProvisioningContext, *, tenant_id: uuid.UUID, reason: str | None = None
    ) -> uuid.UUID:
        lifted = await self.repo.lift_tenant_freeze(
            tenant_id=tenant_id,
            by=context.principal_id,
            reason=reason,
            audit=self._audit(
                context, PLATFORM_TENANT_FREEZE_LIFTED, {"tenant_id": str(tenant_id)}
            ),
        )
        if lifted is None:
            raise _not_frozen()
        return lifted

    def _audit(
        self, context: ProvisioningContext, action: str, details: dict[str, object]
    ) -> ProvisioningAudit:
        return ProvisioningAudit(
            id=self.ids.new_uuid(),
            actor_id=context.principal_id,
            action=action,
            # The platform freeze, or the operator's switch of one company.
            target_type="platform_freeze" if action.startswith("platform.freeze") else _RESOURCE,
            details=details,
            occurred_at=self.clock.now(),
        )


def already_frozen() -> ConflictError:
    """A second open freeze of the same origin: refused here, and by the
    adapters that meet the open index under a race."""
    return ConflictError("a freeze is already open", details={"reason_code": "already_frozen"})


def _not_frozen() -> ConflictError:
    return ConflictError("no freeze is open", details={"reason_code": "not_frozen"})
