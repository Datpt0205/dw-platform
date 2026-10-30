"""The gate a Digital Worker's decision passes (digital-worker R5; ADR-0128
decision 8).

`DecisionGate.check` asks `DecisionAutonomy` whether a decision class needs a
person at this moment. When it does not, the DW decides alone and the audit
trail says so, under its own principal (R5.2). When it does, the gate answers
with the approval to open, `dw.decision`, through the approval door every
other approval uses (R5.1).

What the approval door needs to know about `dw.decision`, each registered at
the composition root by type, so `ApproveAndResumeService.decide` holds no
branch for it:

- `DwDecisionAdmission`: who may decide it is the DW's Validator or Business
  Owner as they are when the decision is made, read in the decision's own
  transaction (R5.3);
- `check_edited_proposal`: an edited proposal must still satisfy the
  proposal's schema and leave its locked fields alone (R5.4, D18);
- `DwProposalMask`: the proposal is read by the DW's Validator, Business Owner
  and Technical Owner only (R5.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from dw_kernel.errors import ConflictError, DomainError, NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.digital_workers import DecisionAutonomy
from dw_platform.application.json_schema import problems
from dw_platform.application.ports import PlatformUnitOfWork
from dw_platform.application.work_queue import DwLookupPort, WorkScope
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import DwPeople

DW_DECISION = "dw.decision"


@dataclass(frozen=True, slots=True)
class Auto:
    """The DW decides alone; the audit row is written."""

    effective_level: str
    kind: Literal["auto"] = "auto"


@dataclass(frozen=True, slots=True)
class AskPerson:
    """Open this approval and wait for it (the run's interrupt value)."""

    payload: Mapping[str, Any]
    kind: Literal["ask"] = "ask"


@dataclass(frozen=True, slots=True)
class ApprovedDecision:
    """An approved `dw.decision`: the run and gate step it belongs to, and the
    content approved, edited or as proposed (wf-lite R6.17, D18)."""

    run_id: uuid.UUID | None
    step_id: str | None
    content: Mapping[str, Any]


class ScopedAuditPort(Protocol):
    async def append(self, scope: WorkScope, event: AuditEvent) -> None:
        """One audit row under `scope`'s RLS, in its own transaction."""
        ...


@dataclass(frozen=True)
class DecisionGate:
    autonomy: DecisionAutonomy
    workers: DwLookupPort
    audit: ScopedAuditPort
    clock: UtcClock
    id_generator: IdGenerator

    async def check(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        *,
        decision_class: str,
        proposal: Mapping[str, Any],
        proposal_schema: Mapping[str, Any],
        locked_fields: Sequence[str],
        reason: str,
        run_id: uuid.UUID | None = None,
        step_id: str | None = None,
    ) -> Auto | AskPerson:
        worker = await self.workers.digital_worker(scope, dw_id)
        if worker is None:
            raise NotFoundError("no such digital worker")
        level = await self.autonomy.effective_level(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            dw_id=dw_id,
            key=decision_class,
        )
        if await self.autonomy.requires_person(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            dw_id=dw_id,
            key=decision_class,
        ):
            return AskPerson(
                payload={
                    "approval_type": DW_DECISION,
                    "reason": reason,
                    "dw_id": str(dw_id),
                    "decision_class": decision_class,
                    "effective_level": level,
                    "proposal": dict(proposal),
                    "proposal_schema": dict(proposal_schema),
                    "locked_fields": list(locked_fields),
                    # The gate step: the tool executor takes the approval only
                    # for this run and this gate (wf-lite R6.17).
                    "step_id": step_id,
                }
            )
        await self.audit.append(
            scope,
            AuditEvent(
                id=self.id_generator.new_uuid(),
                tenant_id=TenantId(scope.tenant_id),
                workspace_id=WorkspaceId(scope.workspace_id),
                actor_id=UserId(worker.principal_user_id),
                action="dw.decision.auto",
                resource_type="digital_worker",
                resource_id=str(dw_id),
                occurred_at=self.clock.now(),
                run_id=run_id,
                details={"decision_class": decision_class, "effective_level": level},
            ),
        )
        return Auto(effective_level=level)


def _dw_of(request: ApprovalRequest) -> uuid.UUID:
    try:
        return uuid.UUID(str(request.payload.get("dw_id")))
    except ValueError as exc:
        raise ConflictError(
            "this approval names no digital worker", details={"reason_code": "not_eligible_decider"}
        ) from exc


def _validator_or_business_owner(people: DwPeople) -> Iterable[uuid.UUID | None]:
    return (people.validator_id, people.business_owner_id)


@dataclass(frozen=True)
class DwDecisionAdmission:
    """Who decides an approval about one DW is some of its people as they are
    now, read in the decision's transaction `FOR SHARE`, so a change of people
    either commits before (and counts) or waits (and does not). By default the
    Validator or Business Owner, for `dw.decision` (R5.3); a raise of autonomy
    passes its own `deciders` (R8.3)."""

    deciders: Callable[[DwPeople], Iterable[uuid.UUID | None]] = _validator_or_business_owner
    refusal: str = "only the digital worker's validator or business owner decides this"

    async def admit(
        self, uow: PlatformUnitOfWork, request: ApprovalRequest, context: AccessContext
    ) -> Mapping[str, object]:
        people = await uow.dw_people.people_of(_dw_of(request))
        eligible = set() if people is None else set(self.deciders(people)) - {None}
        if context.principal_id not in eligible:
            raise ConflictError(self.refusal, details={"reason_code": "not_eligible_decider"})
        return {}


def check_edited_proposal(payload: Mapping[str, Any], edited: Mapping[str, Any]) -> None:
    """R5.4: an edit is the proposal still, in its schema, its locked fields
    untouched. Raises 422 `proposal_invalid` or `locked_field_changed`."""
    schema = payload.get("proposal_schema")
    original = payload.get("proposal")
    if not isinstance(schema, Mapping) or not isinstance(original, Mapping):
        raise DomainError(
            "this approval carries no proposal to edit",
            details={"reason_code": "proposal_invalid"},
        )
    found = problems(schema, dict(edited))
    if found:
        raise DomainError(
            "the edited proposal does not match its schema",
            details={"reason_code": "proposal_invalid", "problems": found},
        )
    locked = payload.get("locked_fields") or []
    changed = sorted(
        str(name) for name in locked if edited.get(str(name)) != original.get(str(name))
    )
    if changed:
        raise DomainError(
            "a locked field of the proposal was changed",
            details={"reason_code": "locked_field_changed", "fields": changed},
        )


class DwPeopleBatchPort(Protocol):
    async def people_of_many(
        self, scope: WorkScope, dw_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, DwPeople]:
        """The four people of each DW of `dw_ids` under `scope`, in one read;
        a DW the scope cannot see is absent."""
        ...


@dataclass(frozen=True)
class DwProposalMask:
    """R5.6: who may read a `dw.decision`'s proposal: the DW's Validator,
    Business Owner or Technical Owner, as they are now. One read per page:
    measured, a read per row put the inbox's P95 from 43 ms to 480 ms."""

    people: DwPeopleBatchPort
    masked_fields: tuple[str, ...] = ("proposal",)

    async def readable(
        self, context: AccessContext, requests: Sequence[ApprovalRequest]
    ) -> frozenset[uuid.UUID]:
        named: dict[uuid.UUID, uuid.UUID] = {}
        for request in requests:
            try:
                named[request.id] = _dw_of(request)
            except ConflictError:
                continue
        if not named:
            return frozenset()
        people = await self.people.people_of_many(
            WorkScope(tenant_id=context.tenant_id, workspace_id=context.workspace_id),
            sorted(set(named.values())),
        )
        return frozenset(
            request_id
            for request_id, dw_id in named.items()
            if dw_id in people and context.principal_id in _readers(people[dw_id])
        )


def _readers(people: DwPeople) -> set[uuid.UUID]:
    named = {people.validator_id, people.technical_owner_id}
    if people.business_owner_id is not None:
        named.add(people.business_owner_id)
    return named
