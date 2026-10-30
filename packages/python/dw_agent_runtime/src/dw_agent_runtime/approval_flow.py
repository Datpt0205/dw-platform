"""Approve/reject a pending approval and resume its paused run.

Bridges platform approvals and the workflow runner: the human decision is
persisted first (aggregate invariant: decided exactly once), then the durable
run resumes with the decision payload.

An approval with no run has nothing to resume, so its decision is announced
instead: one outbox event, `decided_event_type(approval_type)`, written in the
decision's own transaction. A context that wants a consequence registers a
handler for its type where the worker is composed; this service never learns
which types exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any, Protocol

from dw_agent_runtime.adapters.run_store import RunRecord, RunStatus, SqlWorkerRunStore
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_kernel.autonomy import FAIL_CLOSED_LEVEL
from dw_kernel.errors import ConflictError, DomainError, NotFoundError
from dw_kernel.ids import UserId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_observability.metrics import DW_APPROVAL_WAIT_SECONDS
from dw_observability.telemetry import NullTelemetry, TelemetryPort
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import (
    ApprovalAudience,
    ScopeAuthorizationService,
    holds_stamped_scope,
    permission_denied,
)
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.ports import PlatformUnitOfWork, PlatformUnitOfWorkFactory
from dw_platform.domain.approval import (
    APPROVALS_DECIDE,
    ApprovalDecision,
    ApprovalRequest,
    DecisionOutcome,
    decided_event_type,
)
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent

DecisionGuard = Callable[[ApprovalRequest, AccessContext], None]
"""A condition one approval type puts on who may decide it, beyond the scope.

Raises to refuse. Registered by type at the composition root, the way strict
prefixes are, so a context with its own rule adds an entry rather than a branch
in `decide` (memory: the decider must be cleared for what they are deciding on).
"""

ProposalEditor = Callable[[Mapping[str, Any], Mapping[str, Any]], None]
"""How one approval type takes a proposal the decider edited before approving:
given the request's payload and the edit, raises to refuse it. A type with no
editor takes no edit (digital-worker R5.4, D18)."""

DECIDED_EVENT_SCHEMA = "1.0"

# Every decision writes exactly one audit row, in its own transaction, naming
# the decider (approval-audit-and-workspace/01). One admitted by something
# outside the approval (a single-use code, ADR 0007) keeps its own action, which
# also records what admitted it; every other decision writes `approval.decided`.
DECIDED_ACTION = "approval.decided"
CHANNEL_DECIDED_ACTION = "approval.channel_decided"


class DecisionAdmission(Protocol):
    """What one decision must also show, beyond who may decide it.

    Not a `DecisionGuard`, which is per approval TYPE and synchronous: this is
    per DECISION, passed by the caller, and runs inside `decide`'s own unit of
    work after every check `decide` makes and before anything is written, so
    what it consumes (a single-use code) is consumed only by a decision that
    is then written, and restored by the rollback of one that is not. Raises
    to refuse; returns what the decision's audit event records about it.
    """

    async def admit(
        self, uow: PlatformUnitOfWork, request: ApprovalRequest, context: AccessContext
    ) -> Mapping[str, object]: ...


@dataclass
class ApproveAndResumeService:
    uow_factory: PlatformUnitOfWorkFactory
    runner: WorkflowRunnerPort
    run_store: SqlWorkerRunStore
    clock: UtcClock
    id_generator: IdGenerator
    strict_approval_prefixes: frozenset[str] = frozenset()
    # Keyed by the exact approval type. Checked where the decision is made,
    # before anything is written: a rule the inbox merely hides a button for is
    # a rule a direct POST walks past.
    decision_guards: Mapping[str, DecisionGuard] = field(default_factory=dict)
    # Keyed by the exact approval type, like the guards, for a condition that
    # must be read in the decision's own transaction: who may decide a
    # Digital Worker's decision is its Validator or Business Owner as they are
    # when it is decided (digital-worker R5.3). Run after every check above and
    # before anything is written.
    type_admissions: Mapping[str, DecisionAdmission] = field(default_factory=dict)
    proposal_editors: Mapping[str, ProposalEditor] = field(default_factory=dict)
    telemetry: TelemetryPort = field(default_factory=NullTelemetry)

    def is_strict(self, approval_type: str) -> bool:
        """Whether this type demands a second person and a written reason.

        Public because the UI has to know before it offers a decision: a form
        that hardcoded the prefixes would be a second copy of this policy, and
        the one it had let approvers submit decisions the server always refused.
        """
        return approval_type.startswith(tuple(self.strict_approval_prefixes))

    @staticmethod
    def may_decide(
        request: ApprovalRequest,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
    ) -> bool:
        """Whether the caller's scopes let them decide this request: the same two
        checks `decide` runs (`approvals.decide`, then the stamp), for the inbox
        to lock what the server would refuse. Withdrawing your own request,
        separation of duties and per-type guards are not in it."""
        return ApprovalAudience.of(context, authorization).may_decide(request)

    def _enforce_strict_rules(
        self, request: ApprovalRequest, comment: str, context: AccessContext
    ) -> None:
        if request.requested_by.value == context.principal_id:
            raise ConflictError(
                "separation of duties: requester cannot approve their own request",
                details={
                    "approval_id": str(request.id),
                    "approval_type": request.approval_type,
                },
            )
        if not comment.strip():
            raise ConflictError(
                "this approval type requires a review comment",
                details={"approval_type": request.approval_type},
            )

    async def _resumable_run(
        self, context: AccessContext, request: ApprovalRequest
    ) -> RunRecord | None:
        if request.run_id is None:
            return None
        record = await self.run_store.get(
            self._run_context_for(context, request.run_id), request.run_id
        )
        if record.status is not RunStatus.WAITING_APPROVAL:
            raise ConflictError(
                "run is not waiting for approval",
                details={
                    "approval_id": str(request.id),
                    "run_id": str(request.run_id),
                    "status": record.status.value,
                },
            )
        if not self.runner.hosts(
            worker_id=record.worker_id,
            worker_version=record.worker_version,
            graph_version=record.graph_version,
        ):
            raise ConflictError(
                "this service does not run the graph that owns the approval",
                details={
                    "approval_id": str(request.id),
                    "worker_id": record.worker_id,
                    "worker_version": record.worker_version,
                    "graph_version": record.graph_version,
                },
            )
        return record

    async def authorize_decision(
        self,
        *,
        approval_id: uuid.UUID,
        approve: bool,
        comment: str,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
    ) -> None:
        """Whether this caller may decide (or withdraw) this request: the same
        rules `decide` applies, and nothing of the request's state, so a retry
        of a decision already made passes it. What the route's idempotency
        check calls before any key row is read (app-standards R2.30)."""
        async with self.uow_factory(context) as uow:
            request = await self._visible(uow, approval_id, context, authorization)
            await self._authorize(
                request,
                approve=approve,
                comment=comment,
                context=context,
                authorization=authorization,
            )

    async def _visible(
        self,
        uow: PlatformUnitOfWork,
        approval_id: uuid.UUID,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
    ) -> ApprovalRequest:
        # Narrowed to the caller's workspace by the repository: RLS on
        # approval_requests narrows by tenant only. Another workspace's
        # request is not found, before any scope check, write or resume.
        # So is a stamped request the caller may neither decide nor asked
        # for (ADR 0004, amendment 2026-10-07): the inbox does not list it,
        # and a refusal here would tell them it exists and what it needs.
        request = await uow.approvals.get(
            approval_id,
            workspace_id=context.workspace_id,
            audience=ApprovalAudience.of(context, authorization),
        )
        if request is None:
            raise NotFoundError(
                "approval request not found", details={"approval_id": str(approval_id)}
            )
        return request

    async def _authorize(
        self,
        request: ApprovalRequest,
        *,
        approve: bool,
        comment: str,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
    ) -> None:
        """Who may decide this request: the scope, the stamped scope, the strict
        rules and the type's guard. Never its state."""
        # Approving is the decision that needs the right; WITHDRAWING your
        # own request is not. A seller who asks the assistant to do
        # something and then changes their mind must not have to find a
        # manager to take it back — without this the request sits pending
        # forever and its run stays parked (measured 2026-09-08: a sales
        # role got `permission_denied` on Reject as well as Approve).
        # The read moves above the gate so we know whose request it is;
        # it is tenant-scoped by RLS and workspace-scoped by the read above.
        if approve or request.requested_by.value != context.principal_id:
            await authorization.require(
                context=context,
                action=APPROVALS_DECIDE,
                resource_type="approval_request",
                resource_id=str(request.id),
            )
            # Who may decide THIS request, stamped when it was raised
            # (ADR 0004) and read from the row, never from today's policy.
            # NOT through `require`: its admin rule would let a platform
            # operator decide a business approval (2026-10-06). The inbox
            # reads the same `holds_stamped_scope`; and this sits before any
            # write or resume, so a refusal leaves the request pending and
            # the run parked.
            if not holds_stamped_scope(context, request.required_scope):
                raise permission_denied(
                    action=str(request.required_scope),
                    resource_type="approval_request",
                    resource_id=str(request.id),
                )
        if self.is_strict(request.approval_type):
            self._enforce_strict_rules(request, comment, context)
        guard = self.decision_guards.get(request.approval_type)
        if guard is not None:
            guard(request, context)

    async def decide(
        self,
        *,
        approval_id: uuid.UUID,
        approve: bool,
        comment: str,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
        approved_action_ids: list[str] | None = None,
        channel: str = "web",
        admission: DecisionAdmission | None = None,
        effect: PendingEffect | None = None,
        edited_proposal: Mapping[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Decide, then resume the run. `channel` is where the decision came
        from (`web`, or `zalo` through `ChannelApprovalDecisionService`): it is
        written on the decision row and is the resumed run's channel.
        `admission`, when given, must admit this decision inside the same unit
        of work (see `DecisionAdmission`)."""
        async with self.uow_factory(context) as uow:
            # First in the decision's transaction, before the request is read
            # and its state checked: a concurrent attempt of the same key waits
            # here, then meets this decision rather than "already decided"
            # (app-standards R2.33, R2.38).
            if effect is not None:
                await uow.effect_keys.claim(effect.of(approval_id))
            request = await self._visible(uow, approval_id, context, authorization)
            await self._authorize(
                request,
                approve=approve,
                comment=comment,
                context=context,
                authorization=authorization,
            )
            record = await self._resumable_run(context, request)
            if edited_proposal is not None:
                self._check_edit(request, approve, edited_proposal)
            type_admission = self.type_admissions.get(request.approval_type)
            if type_admission is not None:
                await type_admission.admit(uow, request, context)
            admitted = None if admission is None else await admission.admit(uow, request, context)

            decision = request.decide(
                decision_id=self.id_generator.new_uuid(),
                decided_by=UserId(context.principal_id),
                outcome=DecisionOutcome.APPROVED if approve else DecisionOutcome.REJECTED,
                decided_at=self.clock.now().astimezone(UTC),
                comment=comment,
                channel=channel,
                edited_payload=edited_proposal,
            )
            await uow.approvals.save(request)
            await uow.approvals.add_decision(decision)
            if request.run_id is None:
                await uow.outbox.add(self._decided_event(request, decision))
            # Before the commit, in the decision's transaction: a decision with
            # no trail, or a trail for a decision rolled back, is not possible.
            await uow.audit.append(
                self._decided_audit(request, decision)
                if admitted is None
                else self._admitted_audit(request, decision, admitted)
            )
            await uow.commit()
        self._record_wait(request, decision, record)

        if record is not None and request.run_id is not None:
            resume_payload: dict[str, Any] = {
                "approved": approve,
                "comment": comment,
                # Who decided, from the decider's verified context. The run
                # resumes with the requester's authority (below), so a graph
                # that records the decider has no other way to learn it; built
                # here, never copied from the approval's payload, which is the
                # graph's own interrupt value.
                "decided_by": str(context.principal_id),
            }
            if approved_action_ids is not None:
                resume_payload["approved_action_ids"] = approved_action_ids
            if edited_proposal is not None:
                resume_payload["edited_proposal"] = dict(edited_proposal)
            await self.runner.resume(
                run_context=RunContext(
                    run_id=request.run_id,
                    thread_id=record.thread_id,
                    tenant_id=context.tenant_id,
                    # The run's workspace, from its row, never the decider's:
                    # what the resumed graph reads and writes is the run's.
                    workspace_id=record.workspace_id,
                    # A DW's run acts as its principal again, and stays the
                    # lane's request (digital-worker R1.4).
                    actor_id=record.run_as_principal_id or record.requested_by,
                    requested_by=record.requested_by,
                    run_as_principal_id=record.run_as_principal_id,
                    definition_hash=record.definition_hash,
                    worker_id=record.worker_id,
                    worker_version=record.worker_version,
                    # Where the decision came from, so the resumed graph knows.
                    channel=channel,
                    # Authority comes from the run, not from whoever is
                    # approving it. Separation of duties guarantees they are
                    # different people, so reading it from the approver's
                    # context handed their scopes to the requester's agent.
                    plan_id=record.actor_plan_id,
                    roles=record.actor_roles,
                    scopes=record.actor_scopes,
                    clearance=record.actor_clearance,
                    # Same reason as the roles and scopes above: the run
                    # resumes with the reach it started with, not with the
                    # approver's. Omitting these resumed with no owner limit
                    # at all, which widens rather than narrows.
                    record_visibility=record.actor_record_visibility,
                    visible_owners=record.actor_visible_owners,
                    # The autonomy the run started with, from its row — never
                    # re-resolved from the tenant's ceiling today, and never the
                    # approver's. A run started before 0006 has no stamp; it
                    # resumes at None, which the policy reads as ask-everything.
                    autonomy_level=record.autonomy_level,
                    autonomy_ceiling=record.autonomy_level or FAIL_CLOSED_LEVEL,
                    approval_policy_version=record.approval_policy_version,
                    trace_id=f"resume-{request.run_id.hex[:12]}",
                ),
                run_id=request.run_id,
                resume_payload=resume_payload,
            )
        return request

    def _check_edit(
        self, request: ApprovalRequest, approve: bool, edited: Mapping[str, Any]
    ) -> None:
        """An edit is approved, not rejected, and only on a type that takes
        one, by that type's own rule (R5.4)."""
        editor = self.proposal_editors.get(request.approval_type)
        if editor is None or not approve:
            raise DomainError(
                "this decision takes no edited proposal",
                details={"reason_code": "proposal_not_editable"},
            )
        editor(request.payload, edited)

    def _record_wait(
        self, request: ApprovalRequest, decision: ApprovalDecision, record: RunRecord | None
    ) -> None:
        """How long the request waited for a person, once it is decided.

        After the commit: a decision rolled back did not end the wait. A request
        read without its creation time (a fake, a row from before the column)
        has no wait to report, and inventing one would skew the distribution.
        """
        if request.created_at is None:
            return
        waited = (decision.decided_at - request.created_at).total_seconds()
        self.telemetry.record_histogram(
            DW_APPROVAL_WAIT_SECONDS,
            max(waited, 0.0),
            {
                "worker": record.worker_id if record is not None else "none",
                "approval_type": request.approval_type,
            },
        )

    def _decided_event(self, request: ApprovalRequest, decision: ApprovalDecision) -> OutboxEvent:
        """Identifiers and the outcome only. The comment and the request's payload
        stay where their readers are authorized: the outbox is read by a
        dispatcher that serves every tenant, not by a person with a scope."""
        return OutboxEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            event_type=decided_event_type(request.approval_type),
            schema_version=DECIDED_EVENT_SCHEMA,
            aggregate_id=request.id,
            occurred_at=decision.decided_at,
            payload={
                "approval_id": str(request.id),
                "decision_id": str(decision.id),
                "outcome": decision.outcome.value,
                "decided_by": str(decision.decided_by.value),
            },
            actor_id=decision.decided_by.value,
        )

    def _decided_audit(self, request: ApprovalRequest, decision: ApprovalDecision) -> AuditEvent:
        """The decider, never the run's requester (who `run.resumed` names), and
        identifiers and codes only: the comment and the payload can carry
        business data, and their readers are authorized on `approval_decisions`
        and `approval_requests`, not on the audit log."""
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            actor_id=decision.decided_by,
            action=DECIDED_ACTION,
            resource_type="approval_request",
            resource_id=str(request.id),
            occurred_at=decision.decided_at,
            run_id=request.run_id,
            details={
                "approval_type": request.approval_type,
                "outcome": decision.outcome.value,
                "decision_id": str(decision.id),
                # The requester taking their own request back (allowed without
                # `approvals.decide`, and only on a type that is not strict).
                "withdrawn": decision.outcome is DecisionOutcome.REJECTED
                and decision.decided_by == request.requested_by,
            },
        )

    def _admitted_audit(
        self,
        request: ApprovalRequest,
        decision: ApprovalDecision,
        admitted: Mapping[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            actor_id=decision.decided_by,
            action=CHANNEL_DECIDED_ACTION,
            resource_type="approval_request",
            resource_id=str(request.id),
            occurred_at=decision.decided_at,
            run_id=request.run_id,
            details={
                **admitted,
                "channel": decision.channel,
                "decision_id": str(decision.id),
                "outcome": decision.outcome.value,
                "approval_type": request.approval_type,
            },
        )

    def _run_context_for(self, context: AccessContext, run_id: uuid.UUID) -> RunContext:
        return RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id="unknown",
            worker_version="0.0.0",
            channel="web",
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            clearance=context.clearance,
            trace_id=f"lookup-{run_id.hex[:12]}",
        )
