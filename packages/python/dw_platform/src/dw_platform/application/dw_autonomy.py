"""Raising and lowering what a Digital Worker has earned (digital-worker R8;
ADR-0128 decision 5).

Lowering takes effect at once and raising waits for a second person, because
the two errors are not the same size: a level set too low asks a person more
often, and one set too high lets the DW act alone where nobody agreed it may.

- **Lowering** (R8.1) is the Business Owner's or the Technical Owner's: the
  new level and `dw.autonomy.lowered` are written in one transaction, only
  while the level is still the one the caller saw, and the gate reads it at
  its next question.
- **Raising** (R8.2, R8.4) is the Business Owner's alone, never above the
  class's ceiling, and changes nothing: it opens a `dw.autonomy.raise`
  approval with no run. One may be pending per class; the database holds that
  with a partial unique index, read back as 409 `raise_pending`.
- **Deciding** the raise (R8.3) is the approval door's ordinary `decide`:
  the type is strict (a second person, a written reason) and admitted only to
  the DW's Validator or Technical Owner as they are then. Both are registered
  at the composition root, beside `dw.decision`'s.
- **Settling** it (R8.6) happens on the worker, when the decision's outbox
  event arrives: an approval writes `to_level` only while the class still sits
  at `from_level` and the DW is not retired, so an emergency lowering made
  while the raise waited is never overwritten; otherwise the trail says
  `dw.autonomy.raise_stale` and nothing changes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from dw_kernel.autonomy import AUTONOMY_LEVELS, AutonomyLevel, is_autonomy_level
from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.decision_gate import DwDecisionAdmission
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.scorecard import DwReaderPort
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest, decided_event_type
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import DwPeople

DW_AUTONOMY_PREFIX = "dw.autonomy."
DW_AUTONOMY_RAISE = "dw.autonomy.raise"
DW_AUTONOMY_RAISE_DECIDED = decided_event_type(DW_AUTONOMY_RAISE)

LOWERED = "dw.autonomy.lowered"
RAISE_REQUESTED = "dw.autonomy.raise_requested"
RAISED = "dw.autonomy.raised"
RAISE_STALE = "dw.autonomy.raise_stale"

# The lane that carries out a decided raise; named in `details.lane` of the
# audit row, which stands in the decider's name (CLAUDE.md, lane audit).
SETTLING_LANE = "outbox"

_RESOURCE = "digital_worker"


def _validator_or_technical_owner(people: DwPeople) -> Iterable[uuid.UUID | None]:
    return (people.validator_id, people.technical_owner_id)


RAISE_ADMISSION = DwDecisionAdmission(
    deciders=_validator_or_technical_owner,
    refusal="only the digital worker's validator or technical owner decides a raise",
)
"""R8.3, registered under `DW_AUTONOMY_RAISE` in `type_admissions`."""


def _rank(level: AutonomyLevel) -> int:
    return AUTONOMY_LEVELS.index(level)


@dataclass(frozen=True, slots=True)
class AutonomyChange:
    """What a request did: lowered now, or a raise waiting on `approval_id`."""

    kind: Literal["lowered", "raise_requested"]
    dw_id: uuid.UUID
    decision_class: str
    earned_level: AutonomyLevel
    requested_level: AutonomyLevel
    approval_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RaiseFacts:
    """A decided raise as its settlement reads it, under its locks."""

    approval_id: uuid.UUID
    dw_id: uuid.UUID
    decision_class: str
    approved: bool
    decided_by: uuid.UUID
    decided_at: datetime
    from_level: str
    to_level: str
    earned_level: str
    dw_state: str


@dataclass(frozen=True, slots=True)
class RaiseSettlement:
    """What to write: the level (None for none) and the audit row (None for
    none), in the transaction that read the facts."""

    outcome: Literal["raised", "stale", "rejected", "already_raised"]
    level: str | None = None
    audit: AuditEvent | None = None


class AutonomyRepositoryPort(Protocol):
    async def lower(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        key: str,
        *,
        from_level: AutonomyLevel,
        to_level: AutonomyLevel,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        """Write `to_level` and `audit` while the class is at `from_level`;
        False when it is not (someone changed it first)."""
        ...

    async def open_raise(
        self,
        context: AccessContext,
        request: ApprovalRequest,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        """Open the approval with `audit`; 409 `raise_pending` when one is
        already pending for its class."""
        ...


class RaiseSettlementPort(Protocol):
    async def settle_raise(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[RaiseFacts], RaiseSettlement],
    ) -> RaiseSettlement:
        """Read the facts under locks, apply what `settle` decides, in one
        transaction. NotFoundError when no decided raise of that id is there."""
        ...


def _denied() -> PermissionDeniedError:
    return PermissionDeniedError(
        "only the DW's business owner raises, and its business or technical owner lowers",
        details={"reason_code": "not_dw_owner"},
    )


@dataclass(frozen=True)
class DwAutonomyService:
    workers: DwReaderPort
    repo: AutonomyRepositoryPort
    clock: UtcClock
    id_generator: IdGenerator

    async def change(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        key: str,
        level: str,
        *,
        effect: PendingEffect | None = None,
    ) -> AutonomyChange:
        worker = await self.workers.get(context, dw_id)
        found = next((c for c in worker.configuration.decision_classes if c.key == key), None)
        if found is None:
            raise NotFoundError(
                "no such decision class", details={"reason_code": "decision_class_not_found"}
            )
        if not is_autonomy_level(level):
            raise DomainError(
                "not an autonomy level", details={"reason_code": "level_invalid", "level": level}
            )
        target = AUTONOMY_LEVELS[AUTONOMY_LEVELS.index(level)]
        current = found.earned_level
        people = worker.people
        if _rank(target) < _rank(current):
            if context.principal_id not in people.owners():
                raise _denied()
            lowered = await self.repo.lower(
                context,
                dw_id,
                key,
                from_level=current,
                to_level=target,
                audit=self._event(
                    context, LOWERED, dw_id, {"decision_class": key, "from": current, "to": target}
                ),
                effect=effect,
            )
            if not lowered:
                raise ConflictError(
                    "the level changed meanwhile; read it again",
                    details={"reason_code": "level_changed"},
                )
            return AutonomyChange("lowered", dw_id, key, target, target)
        if _rank(target) == _rank(current):
            raise DomainError(
                "the decision class is already at that level",
                details={"reason_code": "level_unchanged"},
            )
        if context.principal_id != people.business_owner_id:
            raise _denied()
        if _rank(target) > _rank(found.ceiling):
            raise DomainError(
                "above the decision class's ceiling",
                details={"reason_code": "above_ceiling", "ceiling": found.ceiling},
            )
        approval_id = self.id_generator.new_uuid()
        details = {"decision_class": key, "from_level": current, "to_level": target}
        await self.repo.open_raise(
            context,
            ApprovalRequest(
                id=approval_id,
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(context.workspace_id),
                approval_type=DW_AUTONOMY_RAISE,
                requested_by=UserId(context.principal_id),
                reason=f"{worker.configuration.name}: {key} {current} → {target}",
                # Identifiers and levels only: the inbox shows the payload to
                # every holder of `approvals.read`.
                payload={"dw_id": str(dw_id), **details},
            ),
            audit=self._event(
                context, RAISE_REQUESTED, dw_id, {**details, "approval_id": str(approval_id)}
            ),
            effect=effect,
        )
        return AutonomyChange("raise_requested", dw_id, key, current, target, approval_id)

    def _event(
        self, context: AccessContext, action: str, dw_id: uuid.UUID, details: dict[str, object]
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
            details=details,
        )


@dataclass(frozen=True)
class RaiseSettler:
    """R8.6, on the worker, where the decision's outbox event arrives."""

    repo: RaiseSettlementPort
    clock: UtcClock
    id_generator: IdGenerator

    async def settle_raise(self, scope: WorkScope, approval_id: uuid.UUID) -> RaiseSettlement:
        """R8.6, on the worker: idempotent, so a redelivered event changes
        nothing a second time (a class already at `to_level` is settled)."""
        return await self.repo.settle_raise(
            scope, approval_id, lambda facts: self._settlement(scope, facts)
        )

    def _settlement(self, scope: WorkScope, facts: RaiseFacts) -> RaiseSettlement:
        if not facts.approved:
            # The decision's own `approval.decided` row is the trail.
            return RaiseSettlement("rejected")
        if facts.earned_level == facts.to_level:
            return RaiseSettlement("already_raised")
        details: dict[str, object] = {
            "decision_class": facts.decision_class,
            "from_level": facts.from_level,
            "to_level": facts.to_level,
            "approval_id": str(facts.approval_id),
            "lane": SETTLING_LANE,
        }
        if facts.earned_level == facts.from_level and facts.dw_state != "retired":
            return RaiseSettlement(
                "raised", level=facts.to_level, audit=self._settled(scope, RAISED, facts, details)
            )
        return RaiseSettlement(
            "stale",
            audit=self._settled(
                scope,
                RAISE_STALE,
                facts,
                {**details, "earned_level": facts.earned_level, "dw_state": facts.dw_state},
            ),
        )

    def _settled(
        self, scope: WorkScope, action: str, facts: RaiseFacts, details: dict[str, object]
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(scope.tenant_id),
            workspace_id=WorkspaceId(scope.workspace_id),
            # A lane carrying out one person's decision audits that person.
            actor_id=UserId(facts.decided_by),
            action=action,
            resource_type=_RESOURCE,
            resource_id=str(facts.dw_id),
            occurred_at=self.clock.now(),
            details=details,
        )
