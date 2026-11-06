"""`LifecycleService`: the one writer of a version's stage (agent-lifecycle R1,
R2; ADR-0120 decision 1), with `studio.guard_version_stage()` the backstop.

Every move goes through `_move`, which asks the pure table (`may_move`) first,
so a move the machine does not have is refused here before the trigger has to.
A route segment names one kind (`SUBMIT_SEGMENTS`): an artifact of another
kind, another company, soft-deleted, or one the caller cannot read at its
owning workspace is a 404 as if it did not exist; one they read without the
action's key is a 403 (`ArtifactService.open_for`, the envelope's own rule).

A gated kind's submit moves its version to `evaluating` (ticket 03; ticket 06
queues the gate run in the same transaction). A kind without a quality gate
(ticket 04, R2.8-R2.12) asks its comparator after the seal: tighten-only, the
version goes `live` in the submitter's transaction (`publish`); otherwise, or
with no live version yet, it moves to `awaiting_approval` with its publish
request opened in that same transaction (R5.1). Either way the 202 names the
required bindings with no approved value (R2.11); on the tighten-only branch
they refuse the submit instead, since nothing would ask again.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from dw_kernel.errors import ConflictError, DomainError, DWError, NotFoundError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.approval import ApprovalRequest, ApprovalStatus
from dw_platform.domain.audit import AuditEvent
from dw_studio.core.application.ports import ArtifactRow, ArtifactTx, VersionRow
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.core.application.service import (
    RESOURCE,
    ArtifactService,
    DependentGroup,
    SealResult,
    name_or_count,
)
from dw_studio.core.domain.artifacts import (
    CANDIDATE_STAGES,
    DocumentInvalidError,
    RetireReason,
    Stage,
    may_move,
)
from dw_studio.lifecycle.application.ports import (
    ControlStatePort,
    LifecycleStore,
    LifecycleTx,
    PublishBindingsCheck,
    SubmitCheck,
    SubmitRefusal,
)
from dw_studio.lifecycle.application.publish import (
    PUBLISH_APPROVE_SCOPE,
    PUBLISHED,
    Path,
    author_ids,
    publish_approval_type,
    version_live,
)

# The submit key the `agent` and `workflow` kinds declare in their registry
# entries (tenant-config R2.15; agent-builder/02, workflow-engine/01), and the
# retire key (R2.5), both at workspace depth.
VERSIONS_SUBMIT_SCOPE = "studio.versions.submit"
VERSIONS_RETIRE_SCOPE = "studio.versions.retire"

# The route segment of each kind that is submitted and withdrawn (spec, API):
# `objects` and `data-sources` take the branch of a kind without a gate
# (ticket 04). `endpoint` is registered by workflow-triggers/02; until then
# `data-sources` answers 404 for every id, as an unknown kind does.
SUBMIT_SEGMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {"agents": "agent", "workflows": "workflow", "objects": "object", "data-sources": "endpoint"}
)
# The segments a live version is retired under (R2.5; the spec's API): the
# retire route is not mounted for `objects` or `data-sources`.
RETIRE_SEGMENTS: Final = frozenset({"agents", "workflows"})

# An `If-Match` that names no version this platform minted (a weak tag): a
# row_version is at least 1 (`ck_artifact_versions_row_version`), so this is
# a 412, never a match.
_NO_VERSION: Final = 0


class SubmitRefusedError(DocumentInvalidError):
    """A kind's check that named problems in the document (custom-objects/06,
    `live_incompatible`): 422 `validation_failed` with `details.reason_code`
    and one `errors[]` entry per problem, the shape the publish hook's own
    refusal has."""

    def __init__(self, refusal: SubmitRefusal) -> None:
        super().__init__(refusal.detail, refusal.errors)
        self.details["reason_code"] = refusal.reason_code


def _refused(refusal: SubmitRefusal) -> DWError:
    if refusal.errors:
        return SubmitRefusedError(refusal)
    return _reason(DomainError, refusal.detail, refusal.reason_code)


def _reason(error: type[DWError], message: str, reason: str, **details: Any) -> DWError:
    return error(message, details={"reason_code": reason, **details})


def _not_found() -> NotFoundError:
    return NotFoundError("version not found")


def _find(versions: Sequence[VersionRow], version_id: uuid.UUID) -> VersionRow:
    for version in versions:
        if version.id == version_id:
            return version
    raise _not_found()


def _submit_key(entry: ArtifactKindEntry) -> str:
    return entry.submit_key


def _retire_key(_entry: ArtifactKindEntry) -> str:
    return VERSIONS_RETIRE_SCOPE


def _tightens(entry: ArtifactKindEntry, live: VersionRow | None, version: VersionRow) -> bool:
    """R2.8: only with a live version to tighten and a comparator that says
    so; a kind without one never tightens only."""
    if live is None or entry.compare is None:
        return False
    return bool(entry.compare(live.document, version.document))


def _binding_unset(names: Sequence[str]) -> ConflictError:
    return ConflictError(
        "a required binding has no approved value",
        details={"reason_code": "binding_unset", "bindings": list(names)},
    )


@dataclass(frozen=True, slots=True)
class Submitted:
    """A submit's answer (R2.11): the version as it now stands, and the
    required bindings that still have no approved value, empty when none."""

    version: VersionRow
    binding_unset: tuple[str, ...] = ()


# What a return to the draft clears, in the same statement (ticket 03 step 4):
# a withdrawal here, a failed gate, a rejection, an expiry in tickets 04, 06.
_CLEARED: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "gate_run_id": None,
        "publish_approval_id": None,
        "submitted_by": None,
        "submitted_at": None,
        "compared_live_hash": None,
        "tighten_only": False,
    }
)


class LifecycleService:
    def __init__(
        self,
        store: LifecycleStore,
        artifacts: ArtifactService,
        control: ControlStatePort,
        checks: Mapping[str, Sequence[SubmitCheck]],
        clock: UtcClock,
        *,
        bindings: PublishBindingsCheck,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.control = control
        self.checks = MappingProxyType({kind: tuple(c) for kind, c in checks.items()})
        self.clock = clock
        # tenant-config ticket 05's `BindingStatus` at the composition root
        # (R2.11, R5.10).
        self.bindings = bindings

    # ---- the moves --------------------------------------------------------

    async def _move(
        self, tx: LifecycleTx, kind: str, version: VersionRow, target: Stage, **values: Any
    ) -> VersionRow:
        gated = await tx.has_quality_gate(kind)
        tighten_only = bool(values.get("tighten_only", version.tighten_only))
        if not may_move(version.stage, target, gated=gated, tighten_only=tighten_only):
            raise _reason(
                ConflictError,
                f"a version does not move from {version.stage} to {target}",
                "stage_refused",
            )
        return await tx.envelope.update_version(version.id, stage=target.value, **values)

    async def return_to_draft(self, tx: LifecycleTx, kind: str, version: VersionRow) -> VersionRow:
        """Back to the draft, every submit column cleared in the same write;
        `version_no` and the hashes stay until the next save clears them."""
        return await self._move(tx, kind, version, Stage.DRAFT, **_CLEARED)

    async def go_live(
        self,
        tx: LifecycleTx,
        kind: str,
        version: VersionRow,
        *,
        actor_id: uuid.UUID,
        **values: Any,
    ) -> VersionRow:
        """R1.4: the live version this one replaces is retired `superseded`
        first, in the same transaction, then this one goes live; the one-live
        index refuses the other order. `values` ride on the move's own UPDATE
        (the tighten-only branch's submit columns, ticket 03 step 6)."""
        now = self.clock.now()
        for other in await tx.envelope.versions(version.artifact_id):
            if other.stage is Stage.LIVE and other.id != version.id:
                await self._move(
                    tx,
                    kind,
                    other,
                    Stage.RETIRED,
                    retired_by=actor_id,
                    retired_at=now,
                    retire_reason_code=RetireReason.SUPERSEDED.value,
                )
        return await self._move(
            tx, kind, version, Stage.LIVE, published_by=actor_id, published_at=now, **values
        )

    async def publish(
        self,
        tx: LifecycleTx,
        kind: str,
        version: VersionRow,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID,
        path: Path,
        details: Mapping[str, object],
        **values: Any,
    ) -> VersionRow:
        """R2.9, R5.5: live by `go_live`, the kind's publish hook in the same
        transaction, exactly one `studio.version.published` in `actor_id`'s
        name with `details.path`, and the outbox's `studio.version.live`."""
        entry = self.artifacts.registry.get(kind)
        if entry is None:
            raise _not_found()
        moved = await self.go_live(tx, kind, version, actor_id=actor_id, **values)
        await entry.publish_hook(tx.envelope, moved.id)
        await tx.envelope.audit(
            self.event_by(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                action=PUBLISHED,
                artifact_id=moved.artifact_id,
                details={
                    "version_id": str(moved.id),
                    "version_no": moved.version_no,
                    "definition_hash": moved.definition_hash,
                    "path": path,
                    **details,
                },
            )
        )
        await tx.announce(
            version_live(
                self.artifacts.ids.new_uuid(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kind=kind,
                version=moved,
                actor_id=actor_id,
                at=self.clock.now(),
            )
        )
        return moved

    def event_by(
        self,
        *,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID,
        action: str,
        artifact_id: uuid.UUID,
        details: Mapping[str, object],
    ) -> AuditEvent:
        """An audit row in a named person's name: the submitter's on the
        tighten-only branch, the decider's when a lane carries out their
        recorded decision (ADR-0011), with `details.lane`."""
        return AuditEvent(
            id=self.artifacts.ids.new_uuid(),
            tenant_id=TenantId(tenant_id),
            workspace_id=WorkspaceId(workspace_id),
            actor_id=UserId(actor_id),
            action=action,
            resource_type=RESOURCE,
            resource_id=str(artifact_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )

    # ---- who may ----------------------------------------------------------

    async def check(
        self, context: AccessContext, kind: str, artifact_id: uuid.UUID, *, retire: bool = False
    ) -> None:
        """The route's own question for an idempotent retry (app-standards R2.30)."""
        async with self.store.transaction(context) as tx:
            await self.artifacts.open_for(
                tx.envelope,
                artifact_id,
                kind=kind,
                key=_retire_key if retire else _submit_key,
                lock=False,
            )

    async def version(
        self, context: AccessContext, kind: str, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> VersionRow:
        """One version by id, under the kind's read key: an idempotent retry's reread."""
        async with self.store.transaction(context) as tx:
            await self.artifacts.open_for(
                tx.envelope, artifact_id, kind=kind, key=lambda e: e.read_key, lock=False
            )
            return _find(await tx.envelope.versions(artifact_id), version_id)

    async def submitted(
        self, context: AccessContext, kind: str, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> Submitted:
        """A submit's answer read again, under the kind's read key: an
        idempotent retry's reread (R2.11)."""
        async with self.store.transaction(context) as tx:
            await self.artifacts.open_for(
                tx.envelope, artifact_id, kind=kind, key=lambda e: e.read_key, lock=False
            )
            version = _find(await tx.envelope.versions(artifact_id), version_id)
            if version.stage not in CANDIDATE_STAGES:
                return Submitted(version)
            return Submitted(version, await self._unset(tx, context, version_id))

    # ---- submit, withdraw, retire -------------------------------------------

    async def submit(
        self,
        context: AccessContext,
        kind: str,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        expected: ExpectedVersion,
        effect: PendingEffect | None = None,
    ) -> Submitted:
        """R2.1-R2.3, R2.7-R2.12, R5.1, R7.9, R7.13, in one transaction.

        A gated kind: the freeze asked, the draft sealed under `If-Match`, the
        kind's checks, `evaluating`. A kind without a gate: the seal, the
        comparator, the freeze (a company's freeze lets a tighten-only submit
        through, a platform's does not), the kind's checks, then `live` on the
        tighten-only branch, its bindings checked first, or
        `awaiting_approval` with its publish request. The submit columns ride
        on the move's own UPDATE; audited `studio.version.submitted`."""
        async with self.store.transaction(context) as tx:
            envelope = tx.envelope
            if effect is not None:
                await envelope.claim(effect.of(version_id))
            row, entry = await self.artifacts.open_for(
                envelope, artifact_id, kind=kind, key=_submit_key, lock=False
            )
            gated = await tx.has_quality_gate(kind)
            if gated:
                await self._admit(context, tighten_only=False)
            sealed = await self._seal(envelope, artifact_id, version_id, expected)
            version = _find(await envelope.versions(artifact_id), version_id)
            live = await self._live(envelope, artifact_id)
            tighten_only = not gated and _tightens(entry, live, version)
            if not gated:
                await self._admit(context, tighten_only=tighten_only)
            for check in self.checks.get(kind, ()):
                refusal = await check(envelope, version, sealed.closure)
                if refusal is not None:
                    raise _refused(refusal)
            submitted: dict[str, Any] = {
                "submitted_by": context.principal_id,
                "submitted_at": self.clock.now(),
                "compared_live_hash": None if live is None else live.definition_hash,
                "tighten_only": tighten_only,
            }
            if tighten_only:
                unset = await self._unset(tx, context, version_id)
                if unset:
                    raise _binding_unset(unset)
                moved = await self.publish(
                    tx,
                    kind,
                    version,
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    actor_id=context.principal_id,
                    path="tighten_only",
                    details={},
                    **submitted,
                )
            elif gated:
                moved = await self._move(tx, kind, version, Stage.EVALUATING, **submitted)
            else:
                approval_id = await self._open_request(tx, context, row, version)
                moved = await self._move(
                    tx,
                    kind,
                    version,
                    Stage.AWAITING_APPROVAL,
                    publish_approval_id=approval_id,
                    **submitted,
                )
            await envelope.audit(
                self.artifacts.event(
                    context,
                    "studio.version.submitted",
                    artifact_id,
                    {
                        "version_id": str(version_id),
                        "version_no": sealed.version_no,
                        "definition_hash": sealed.definition_hash,
                        "stage": moved.stage.value,
                    },
                )
            )
            # R2.11: on the approval branch the names go back with the 202;
            # the handler asks again before anything goes live (R5.10).
            unset = () if tighten_only else await self._unset(tx, context, version_id)
        return Submitted(moved, unset)

    async def _admit(self, context: AccessContext, *, tighten_only: bool) -> None:
        """R7.9, R7.13: a freeze stops a submit, fail closed; a company's
        freeze lets a tighten-only submit through, since it only takes rights
        away. A gated kind asks before its seal, one without a gate after its
        comparator."""
        refused = await self.control.admission_state(context.tenant_id)
        if refused is None or (tighten_only and str(refused) == "tenant_frozen"):
            return
        raise _reason(ConflictError, "submitting is stopped", str(refused))

    async def _unset(
        self, tx: LifecycleTx, context: AccessContext, version_id: uuid.UUID
    ) -> tuple[str, ...]:
        verdict = await self.bindings.satisfied_in(tx.envelope, context.tenant_id, version_id)
        return verdict.unset

    async def _open_request(
        self, tx: LifecycleTx, context: AccessContext, row: ArtifactRow, version: VersionRow
    ) -> uuid.UUID:
        """R5.1: the run-less `studio.publish.<kind>` request, before the
        version names it: the submitter asks, a holder of the stamp decides in
        the component's own workspace, and the payload is ids only, the
        authors as the version row has them plus its submitter."""
        approval_id = self.artifacts.ids.new_uuid()
        approval_type = publish_approval_type(row.kind)
        await tx.open_approval(
            ApprovalRequest(
                id=approval_id,
                tenant_id=TenantId(context.tenant_id),
                workspace_id=WorkspaceId(row.owning_workspace_id),
                approval_type=approval_type,
                requested_by=UserId(context.principal_id),
                reason=approval_type,
                payload={
                    "artifact_id": str(row.id),
                    "version_id": str(version.id),
                    "author_ids": author_ids(version.contributor_ids, context.principal_id),
                },
                required_scope=PUBLISH_APPROVE_SCOPE,
            )
        )
        return approval_id

    async def _seal(
        self,
        envelope: ArtifactTx,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        expected: ExpectedVersion,
    ) -> SealResult:
        expected_version = _NO_VERSION if expected.version is None else expected.version
        try:
            sealed = await self.artifacts.seal(envelope, artifact_id, expected_version)
        except NotFoundError as exc:
            if exc.details.get("reason_code") != "no_draft":
                raise
            # The seal took the artifact's lock: read the version again under
            # it. A concurrent submit of the same draft won (R1.3).
            for version in await envelope.versions(artifact_id):
                if version.id == version_id and version.stage in CANDIDATE_STAGES:
                    raise _reason(
                        ConflictError, "this version is already submitted", "candidate_exists"
                    ) from exc
            raise _not_found() from exc
        if sealed.version_id != version_id:
            raise _not_found()
        return sealed

    @staticmethod
    async def _live(envelope: ArtifactTx, artifact_id: uuid.UUID) -> VersionRow | None:
        return next(
            (v for v in await envelope.versions(artifact_id) if v.stage is Stage.LIVE), None
        )

    async def withdraw(
        self,
        context: AccessContext,
        kind: str,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        effect: PendingEffect | None = None,
    ) -> VersionRow:
        """R2.4: any holder of the submit key withdraws a candidate with no
        decision yet, its pending publish request cancelled, under the
        artifact's lock."""
        async with self.store.transaction(context) as tx:
            envelope = tx.envelope
            if effect is not None:
                await envelope.claim(effect.of(version_id))
            await self.artifacts.open_for(
                envelope, artifact_id, kind=kind, key=_submit_key, lock=True
            )
            version = _find(await envelope.versions(artifact_id), version_id)
            if version.stage not in CANDIDATE_STAGES:
                raise _reason(ConflictError, "this version is not a candidate", "not_a_candidate")
            if version.publish_approval_id is not None:
                request = await tx.publish_approval(version.publish_approval_id)
                if request is None or request.status is not ApprovalStatus.PENDING:
                    raise _reason(
                        ConflictError, "this candidate is already decided", "not_a_candidate"
                    )
                request.cancel()
                await tx.save_approval(request)
            moved = await self.return_to_draft(tx, kind, version)
            await envelope.audit(
                self.artifacts.event(
                    context,
                    "studio.version.returned_to_draft",
                    artifact_id,
                    {"version_id": str(version_id), "reason_code": "withdrawn"},
                )
            )
        return moved

    async def retire(
        self,
        context: AccessContext,
        kind: str,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        effect: PendingEffect | None = None,
    ) -> VersionRow:
        """R2.5, R2.6: a live version retired `explicit`, refused while the
        live version of another artifact pins this one."""
        async with self.store.transaction(context) as tx:
            envelope = tx.envelope
            if effect is not None:
                await envelope.claim(effect.of(version_id))
            await self.artifacts.open_for(
                envelope, artifact_id, kind=kind, key=_retire_key, lock=True
            )
            version = _find(await envelope.versions(artifact_id), version_id)
            if version.stage is not Stage.LIVE:
                raise _reason(ConflictError, "this version is not live", "not_live")
            dependents = await tx.live_dependents(version_id)
            if dependents:
                group = await name_or_count(envelope, self.artifacts.registry, dependents)
                raise _in_use(group)
            moved = await self._move(
                tx,
                kind,
                version,
                Stage.RETIRED,
                retired_by=context.principal_id,
                retired_at=self.clock.now(),
                retire_reason_code=RetireReason.EXPLICIT.value,
            )
            await envelope.audit(
                self.artifacts.event(
                    context,
                    "studio.version.retired",
                    artifact_id,
                    {"version_id": str(version_id), "reason_code": RetireReason.EXPLICIT.value},
                )
            )
        return moved


def _in_use(group: DependentGroup) -> ConflictError:
    return ConflictError(
        "a live version of another artifact uses this version",
        details={
            "reason_code": "artifact_in_use",
            "dependents": [
                {"artifact_id": str(d.artifact_id), "kind": d.kind, "api_name": d.api_name}
                for d in group.items
            ],
            "hidden": group.hidden,
        },
    )
