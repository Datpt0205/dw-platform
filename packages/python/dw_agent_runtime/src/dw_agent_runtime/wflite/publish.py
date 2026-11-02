"""Publishing a Digital Worker's workflow draft (wf-ai R6.3-R6.6, R6.8,
R6.10, R6.11, R6.14; ADR-0120 decision 2).

- **Submitting** opens a `dw.workflow.publish` approval with no run, carrying
  identifiers and hashes only: the DW, the draft's content hash, the hash of
  the base it was made from and everyone who saved it. Only a draft whose last
  simulation passed on that very content is submitted (R6.3), and a submitted
  draft is locked until it is withdrawn or decided (R6.8).
- **Deciding** is the approval door's ordinary `decide`. The type is strict (a
  second person, a written reason), and `PUBLISH_ADMISSION` admits only the
  DW's Validator or Technical Owner as they are then, never one who saved the
  draft or submitted it (R6.4): 409 `second_person_required`.
- **Settling** happens on the worker when the decision's outbox event arrives
  (`PublishSettler`), in one transaction under the DW's row lock: an approval
  publishes the draft's content as `<pack semver>+t<n>` and moves the DW's pin
  to it (R6.5), only while the DW still pins the base the approval names and
  the draft still hashes to the approved content; otherwise the draft goes
  back to `draft` with `base_changed` or `content_changed` and nothing is
  published (R6.6). A rejection returns the draft too (R6.11). The approval's
  id is unique on the version, and a settlement acts only on the draft that
  waits on that approval, so a redelivered event changes nothing (R6.14).
- **Withdrawing** cancels the pending approval and returns the draft in one
  transaction (R6.10).

Submitting and withdrawing are the DW's Business or Technical Owner's
(`require_owner`), each one transaction with its audit row and effect key
(R6.12, R6.15).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from dw_agent_runtime.wflite.assistant import DwOwnerPort
from dw_agent_runtime.wflite.catalog import workflow_sha256
from dw_agent_runtime.wflite.drafts import Draft, Simulation
from dw_agent_runtime.wflite.versions import PinnedWorkflowsPort, base_sha256
from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.decision_gate import DwDecisionAdmission
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.ports import PlatformUnitOfWork
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest, decided_event_type
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import (
    TENANT_PIN_MARK,
    DwPeople,
    is_tenant_pin,
    pack_version_of,
)

DW_WORKFLOW_PREFIX = "dw.workflow."
DW_WORKFLOW_PUBLISH = "dw.workflow.publish"
DW_WORKFLOW_PUBLISH_DECIDED = decided_event_type(DW_WORKFLOW_PUBLISH)

SUBMITTED = "dw.workflow.submitted"
WITHDRAWN = "dw.workflow.withdrawn"
PUBLISHED = "dw.workflow.published"
RETURNED = "dw.workflow.returned"

# The lane that carries out a decided publication; named in `details.lane` of
# the audit row, which stands in the decider's name (CLAUDE.md, lane audit).
SETTLING_LANE = "outbox"

_RESOURCE = "digital_worker"


def _validator_or_technical_owner(people: DwPeople) -> tuple[uuid.UUID | None, ...]:
    return (people.validator_id, people.technical_owner_id)


def second_person_required() -> ConflictError:
    return ConflictError(
        "nobody who saved or submitted this draft decides its publication",
        details={"reason_code": "second_person_required"},
    )


_PEOPLE = DwDecisionAdmission(
    deciders=_validator_or_technical_owner,
    refusal="only the digital worker's validator or technical owner decides a publication",
)


@dataclass(frozen=True)
class PublishAdmission:
    """R6.4: the DW's Validator or Technical Owner as they are in the
    decision's transaction, and none of the draft's authors or its submitter.
    A payload without its authors refuses: it was not written here."""

    people: DwDecisionAdmission = _PEOPLE

    async def admit(
        self, uow: PlatformUnitOfWork, request: ApprovalRequest, context: AccessContext
    ) -> Mapping[str, object]:
        authors = request.payload.get("author_ids")
        if not isinstance(authors, list) or not authors:
            raise second_person_required()
        if str(context.principal_id) in {str(a) for a in authors} | {
            str(request.requested_by.value)
        }:
            raise second_person_required()
        return await self.people.admit(uow, request, context)


PUBLISH_ADMISSION = PublishAdmission()
"""Registered under `DW_WORKFLOW_PUBLISH` in `type_admissions`, beside the
strict prefix `DW_WORKFLOW_PREFIX`, in both composition roots."""


class PublicationStorePort(Protocol):
    async def submit(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        open_approval: Callable[[Draft, Simulation | None], tuple[ApprovalRequest, AuditEvent]],
        *,
        effect: PendingEffect | None,
    ) -> Draft:
        """One transaction: the effect key; the draft and its simulation read
        under the draft's row lock; the approval `open_approval` builds from
        them (or its refusal), the draft `submitted` on it, the audit row.
        NotFoundError `draft_not_found` without a draft."""
        ...

    async def withdraw(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        close: Callable[[Draft], AuditEvent],
        *,
        effect: PendingEffect | None,
    ) -> Draft:
        """One transaction: the draft read under its row lock, `close`'s audit
        row (or its refusal), its pending approval cancelled and the draft back
        to `draft`. 409 `approval_decided` when the approval was decided first:
        its settlement returns the draft."""
        ...


def _not_submitted() -> ConflictError:
    return ConflictError(
        "the draft is not waiting for a decision", details={"reason_code": "draft_not_submitted"}
    )


def _simulation_required() -> ConflictError:
    return ConflictError(
        "simulate this draft, and see it pass, before submitting it",
        details={"reason_code": "simulation_required"},
    )


@dataclass(frozen=True)
class WorkflowPublishing:
    workers: DwOwnerPort
    store: PublicationStorePort
    clock: UtcClock
    id_generator: IdGenerator

    async def submit(
        self, context: AccessContext, dw_id: uuid.UUID, *, effect: PendingEffect | None = None
    ) -> Draft:
        worker = await self.workers.require_owner(context, dw_id)
        name = worker.configuration.name

        def open_approval(
            draft: Draft, simulation: Simulation | None
        ) -> tuple[ApprovalRequest, AuditEvent]:
            if draft.state == "submitted":
                raise ConflictError(
                    "the draft already waits for its decision",
                    details={"reason_code": "draft_submitted"},
                )
            if (
                simulation is None
                or simulation.outcome != "passed"
                or simulation.content_sha256 != draft.content_sha256
            ):
                raise _simulation_required()
            approval_id = self.id_generator.new_uuid()
            payload: dict[str, object] = {
                "dw_id": str(dw_id),
                "content_sha256": draft.content_sha256,
                "base_sha256": draft.base_sha256,
                "author_ids": [str(a) for a in draft.author_ids],
            }
            request = ApprovalRequest(
                id=approval_id,
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(context.workspace_id),
                approval_type=DW_WORKFLOW_PUBLISH,
                requested_by=UserId(context.principal_id),
                reason=f"{name}: {draft.content_sha256[:12]}",
                # Identifiers and hashes only: the inbox shows the payload to
                # every holder of `approvals.read`.
                payload=payload,
            )
            return request, self._event(
                context,
                dw_id,
                SUBMITTED,
                {"approval_id": str(approval_id), "content_sha256": draft.content_sha256},
            )

        return await self.store.submit(WorkScope.of(context), dw_id, open_approval, effect=effect)

    async def withdraw(
        self, context: AccessContext, dw_id: uuid.UUID, *, effect: PendingEffect | None = None
    ) -> Draft:
        await self.workers.require_owner(context, dw_id)

        def close(draft: Draft) -> AuditEvent:
            if draft.state != "submitted" or draft.approval_id is None:
                raise _not_submitted()
            return self._event(
                context,
                dw_id,
                WITHDRAWN,
                {"approval_id": str(draft.approval_id), "content_sha256": draft.content_sha256},
            )

        return await self.store.withdraw(WorkScope.of(context), dw_id, close, effect=effect)

    def _event(
        self, context: AccessContext, dw_id: uuid.UUID, action: str, details: dict[str, object]
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


@dataclass(frozen=True, slots=True)
class PublishFacts:
    """A decided publication as its settlement reads it, under its locks."""

    approval_id: uuid.UUID
    dw_id: uuid.UUID
    approved: bool
    decided_by: uuid.UUID
    content_sha256: str
    base_sha256: str
    # The DW's pin now, and the content hash of its tenant version when the
    # pin is one (None when the row is not there).
    workflow_key: str
    workflow_version: str
    pinned_version_sha256: str | None
    draft: Draft | None
    already_published: bool
    next_seq: int


@dataclass(frozen=True, slots=True)
class NewVersion:
    id: uuid.UUID
    seq: int
    version: str


@dataclass(frozen=True, slots=True)
class PublishSettlement:
    """What to write in the transaction that read the facts: the version to
    publish, or the draft back to `draft` with its reason, and the audit row."""

    outcome: Literal["published", "base_changed", "content_changed", "rejected", "settled"]
    publish: NewVersion | None = None
    return_draft: bool = False
    reason: Literal["base_changed", "content_changed"] | None = None
    audit: AuditEvent | None = None


class PublishSettlementPort(Protocol):
    async def settle_publish(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[PublishFacts], PublishSettlement],
    ) -> PublishSettlement:
        """Read the facts under the DW's and the draft's row locks, apply what
        `settle` decides, in one transaction. NotFoundError when no decided
        publication of that id is there."""
        ...


@dataclass(frozen=True)
class PublishSettler:
    """R6.5, R6.6, R6.11, R6.14, on the worker, where the decision's outbox
    event arrives."""

    repo: PublishSettlementPort
    workflows: PinnedWorkflowsPort
    clock: UtcClock
    id_generator: IdGenerator

    async def settle_publish(self, scope: WorkScope, approval_id: uuid.UUID) -> PublishSettlement:
        return await self.repo.settle_publish(
            scope, approval_id, lambda facts: self._settlement(scope, facts)
        )

    def _base_now(self, facts: PublishFacts) -> str | None:
        if is_tenant_pin(facts.workflow_version):
            return facts.pinned_version_sha256
        pack = self.workflows.pack(facts.workflow_key, facts.workflow_version)
        return None if pack is None else base_sha256(pack)

    def _settlement(self, scope: WorkScope, facts: PublishFacts) -> PublishSettlement:
        draft = facts.draft
        waiting = (
            draft is not None
            and draft.state == "submitted"
            and draft.approval_id == facts.approval_id
        )
        if facts.already_published or not waiting or draft is None:
            # Delivered before, or withdrawn since: nothing is this one's.
            return PublishSettlement("settled")
        details: dict[str, object] = {
            "approval_id": str(facts.approval_id),
            "content_sha256": facts.content_sha256,
            "lane": SETTLING_LANE,
        }
        if not facts.approved:
            return PublishSettlement(
                "rejected",
                return_draft=True,
                audit=self._event(scope, facts, RETURNED, {**details, "reason": "rejected"}),
            )
        reason: Literal["base_changed", "content_changed"] | None = None
        if self._base_now(facts) != facts.base_sha256:
            reason = "base_changed"
        elif workflow_sha256(draft.content) != facts.content_sha256:
            reason = "content_changed"
        if reason is not None:
            return PublishSettlement(
                reason,
                return_draft=True,
                reason=reason,
                audit=self._event(scope, facts, RETURNED, {**details, "reason": reason}),
            )
        version = f"{pack_version_of(facts.workflow_version)}{TENANT_PIN_MARK}{facts.next_seq}"
        return PublishSettlement(
            "published",
            publish=NewVersion(
                id=self.id_generator.new_uuid(), seq=facts.next_seq, version=version
            ),
            audit=self._event(
                scope,
                facts,
                PUBLISHED,
                {**details, "version": version, "from_version": facts.workflow_version},
            ),
        )

    def _event(
        self, scope: WorkScope, facts: PublishFacts, action: str, details: dict[str, object]
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


__all__ = [
    "DW_WORKFLOW_PREFIX",
    "DW_WORKFLOW_PUBLISH",
    "DW_WORKFLOW_PUBLISH_DECIDED",
    "PUBLISH_ADMISSION",
    "NewVersion",
    "PublicationStorePort",
    "PublishAdmission",
    "PublishFacts",
    "PublishSettlement",
    "PublishSettlementPort",
    "PublishSettler",
    "WorkflowPublishing",
    "second_person_required",
]
