"""A publish request decided and a candidate read by its reviewer
(agent-lifecycle R5.5, R5.9-R5.12, R7.12; ADR-0120 decisions 1-2; ticket 04).

- **The decision**, announced on the outbox as `studio.publish.<kind>.decided`
  with ids only, is carried out by `PublishSettler` on the worker, in the
  decider's name: a version that left `awaiting_approval` is left alone; a
  rejection, a freeze, a required binding without an approved value and a
  live version that moved since the submit each take the version back to its
  draft with the reason; otherwise `LifecycleService.publish` takes it live.
- **The candidate**, read by someone who may decide the pending request
  (`CandidateReader`): its sealed document and what changed against the
  version it was compared with, one audit row per read.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from dw_kernel.errors import InfrastructureError, NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ApprovalAudience, ScopeAuthorizationService
from dw_platform.domain.approval import ApprovalRequest, ApprovalStatus
from dw_studio.core.application.ports import VersionRow
from dw_studio.core.domain.artifacts import Stage
from dw_studio.lifecycle.application.ports import LifecycleTx
from dw_studio.lifecycle.application.publish import (
    CANDIDATE_READ,
    PUBLISH_PREFIX,
    RETURNED_TO_DRAFT,
    SETTLING_LANE,
    Change,
    document_changes,
    payload_authors,
)
from dw_studio.lifecycle.application.service import LifecycleService

# What the run controls answer that takes an approved version back to its
# draft (R7.12); any other answer is a read that failed, and is retried.
_FROZEN: Final = frozenset({"tenant_frozen", "platform_frozen"})

Settled = Literal[
    "published",
    "rejected",
    "ignored",
    "tenant_frozen",
    "platform_frozen",
    "binding_unset",
    "base_changed",
]


def _no_request(approval_id: uuid.UUID) -> NotFoundError:
    return NotFoundError(
        "no decided publish request of that id", details={"approval_id": str(approval_id)}
    )


@dataclass(frozen=True)
class PublishSettler:
    """R5.5, R5.9, R5.10, R7.12, on the worker. One transaction under the
    tenant alone, the component locked first (the lock withdraw and retire
    take), the version read by its request: idempotent, since a version no
    longer `awaiting_approval` (withdrawn, settled, sent back) is left as it
    is and nothing is audited.

    A read that fails (the run controls unavailable, the bindings check
    raising) raises: the transaction rolls back and the outbox delivers again,
    with nothing published and nothing sent back."""

    lifecycle: LifecycleService

    async def settle(self, tenant_id: uuid.UUID, approval_id: uuid.UUID) -> Settled:
        lifecycle = self.lifecycle
        async with lifecycle.store.for_tenant(tenant_id) as tx:
            decision = await tx.publish_decision(approval_id)
            if decision is None or not decision.approval_type.startswith(PUBLISH_PREFIX):
                raise _no_request(approval_id)
            artifact_id = await tx.candidate_artifact(approval_id)
            artifact = (
                None if artifact_id is None else await tx.envelope.artifact(artifact_id, lock=True)
            )
            if artifact is None:
                return "ignored"
            versions = await tx.envelope.versions(artifact.id)
            version = next((v for v in versions if v.publish_approval_id == approval_id), None)
            if version is None or version.stage is not Stage.AWAITING_APPROVAL:
                return "ignored"
            reason: Settled | None = (
                "rejected"
                if not decision.approved
                else await self._refusal(tx, tenant_id, version, versions)
            )
            details = {"approval_id": str(approval_id), "lane": SETTLING_LANE}
            if reason is not None:
                await lifecycle.return_to_draft(tx, artifact.kind, version)
                await tx.envelope.audit(
                    lifecycle.event_by(
                        tenant_id=tenant_id,
                        workspace_id=decision.workspace_id,
                        actor_id=decision.decided_by,
                        action=RETURNED_TO_DRAFT,
                        artifact_id=artifact.id,
                        details={"version_id": str(version.id), "reason_code": reason, **details},
                    )
                )
                return reason
            # The kind's hook writes in the decider's name (custom-objects/06).
            tx.carry_out(decision, SETTLING_LANE)
            await lifecycle.publish(
                tx,
                artifact.kind,
                version,
                tenant_id=tenant_id,
                workspace_id=decision.workspace_id,
                actor_id=decision.decided_by,
                path="approved",
                details=details,
            )
        return "published"

    async def _refusal(
        self,
        tx: LifecycleTx,
        tenant_id: uuid.UUID,
        version: VersionRow,
        versions: Sequence[VersionRow],
    ) -> Settled | None:
        """In order: the freeze, the bindings, the base (R7.12, R5.10, R5.9)."""
        state = await self.lifecycle.control.admission_state(tenant_id)
        if state is not None and str(state) in _FROZEN:
            return "tenant_frozen" if str(state) == "tenant_frozen" else "platform_frozen"
        if state is not None:
            raise InfrastructureError(
                "the run controls did not answer; the decision is carried out later",
                details={"reason_code": str(state)},
            )
        verdict = await self.lifecycle.bindings.satisfied_in(tx.envelope, tenant_id, version.id)
        if not verdict.satisfied:
            return "binding_unset"
        live = next((v for v in versions if v.stage is Stage.LIVE), None)
        if version.compared_live_hash != (None if live is None else live.definition_hash):
            return "base_changed"
        return None


# ---- the candidate, for the person deciding ------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    approval_id: uuid.UUID
    version_id: uuid.UUID
    artifact_id: uuid.UUID
    kind: str
    version_no: int | None
    definition_hash: str | None
    document: Any
    live_version_id: uuid.UUID | None
    changes: tuple[Change, ...]


def _hidden(approval_id: uuid.UUID) -> NotFoundError:
    return NotFoundError("approval request not found", details={"approval_id": str(approval_id)})


def _decidable_by(
    request: ApprovalRequest | None, audience: ApprovalAudience, context: AccessContext
) -> ApprovalRequest | None:
    """R5.11, R5.12: a pending publish request the caller may decide, neither
    asked for nor written by them; anything else is as if it did not exist."""
    if (
        request is None
        or not request.approval_type.startswith(PUBLISH_PREFIX)
        or request.status is not ApprovalStatus.PENDING
        or not audience.may_decide(request)
        or request.requested_by.value == context.principal_id
    ):
        return None
    authors = payload_authors(request)
    if authors is None or str(context.principal_id) in authors:
        return None
    return request


def _compared(versions: Sequence[VersionRow], candidate: VersionRow) -> VersionRow | None:
    """The version the candidate was compared with at its submit: the one
    whose definition hash is its `compared_live_hash` (it may since have been
    retired), the live one first, then the newest, when two share it."""
    if candidate.compared_live_hash is None:
        return None
    matching = [
        v
        for v in versions
        if v.id != candidate.id and v.definition_hash == candidate.compared_live_hash
    ]
    matching.sort(key=lambda v: (v.stage is not Stage.LIVE, -(v.version_no or 0)))
    return matching[0] if matching else None


@dataclass(frozen=True)
class CandidateReader:
    """`GET /studio/publish-approvals/{approval_id}/candidate` (R5.11, R5.12;
    ADR-0120 decision 2): not through the kind's read key, which a reviewer
    need not hold, but through the request, read as the approval inbox reads
    it (`ApprovalAudience`, the caller's workspace), and only while it waits
    on the caller's decision. Every refusal is the same 404 with nothing
    written; a read writes exactly one audit row, in its own transaction."""

    lifecycle: LifecycleService

    async def read(
        self,
        context: AccessContext,
        authorization: ScopeAuthorizationService,
        approval_id: uuid.UUID,
    ) -> Candidate:
        audience = ApprovalAudience.of(context, authorization)
        lifecycle = self.lifecycle
        async with lifecycle.store.transaction(context) as tx:
            request = _decidable_by(
                await tx.visible_approval(
                    approval_id, workspace_id=context.workspace_id, audience=audience
                ),
                audience,
                context,
            )
            artifact_id = None if request is None else await tx.candidate_artifact(approval_id)
            artifact = None if artifact_id is None else await tx.envelope.artifact(artifact_id)
            if request is None or artifact is None:
                raise _hidden(approval_id)
            versions = await tx.envelope.versions(artifact.id)
            version = next((v for v in versions if v.publish_approval_id == approval_id), None)
            if (
                version is None
                or version.stage is not Stage.AWAITING_APPROVAL
                or request.payload.get("version_id") != str(version.id)
            ):
                raise _hidden(approval_id)
            live = _compared(versions, version)
            changes = document_changes(None if live is None else live.document, version.document)
            await tx.envelope.audit(
                lifecycle.artifacts.event(
                    context,
                    CANDIDATE_READ,
                    artifact.id,
                    {"approval_id": str(approval_id), "version_id": str(version.id)},
                )
            )
        return Candidate(
            approval_id=approval_id,
            version_id=version.id,
            artifact_id=artifact.id,
            kind=artifact.kind,
            version_no=version.version_no,
            definition_hash=version.definition_hash,
            document=version.document,
            live_version_id=None if live is None else live.id,
            changes=tuple(changes),
        )
