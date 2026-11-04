"""`LifecycleService`: the one writer of a version's stage (agent-lifecycle R1,
R2; ADR-0120 decision 1), with `studio.guard_version_stage()` the backstop.

Every move goes through `_move`, which asks the pure table (`may_move`) first,
so a move the machine does not have is refused here before the trigger has to.
A route segment names one kind (`SUBMIT_SEGMENTS`): an artifact of another
kind, another company, soft-deleted, or one the caller cannot read at its
owning workspace is a 404 as if it did not exist; one they read without the
action's key is a 403 (`ArtifactService.open_for`, the envelope's own rule).

This ticket builds the gated kinds' submit (`draft -> evaluating`); a kind
without a quality gate answers its submit 404 until ticket 04 builds its
branch, so no route takes such a kind without one. Ticket 06 queues the gate
run in the submit's transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from dw_kernel.errors import ConflictError, DomainError, DWError, NotFoundError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.approval import ApprovalStatus
from dw_studio.core.application.ports import ArtifactTx, VersionRow
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.core.application.service import (
    ArtifactService,
    DependentGroup,
    SealResult,
    name_or_count,
)
from dw_studio.core.domain.artifacts import (
    CANDIDATE_STAGES,
    RetireReason,
    Stage,
    may_move,
)
from dw_studio.lifecycle.application.ports import (
    ControlStatePort,
    LifecycleStore,
    LifecycleTx,
    SubmitCheck,
)

# The submit key the `agent` and `workflow` kinds declare in their registry
# entries (tenant-config R2.15; agent-builder/02, workflow-engine/01), and the
# retire key (R2.5), both at workspace depth.
VERSIONS_SUBMIT_SCOPE = "studio.versions.submit"
VERSIONS_RETIRE_SCOPE = "studio.versions.retire"

# The route segment of each kind whose submit is built (spec, API). Ticket 04
# adds `objects` -> `object` and `data-sources` -> `endpoint` with the branch
# of a kind without a gate.
SUBMIT_SEGMENTS: Final[Mapping[str, str]] = MappingProxyType(
    {"agents": "agent", "workflows": "workflow"}
)

# An `If-Match` that names no version this platform minted (a weak tag): a
# row_version is at least 1 (`ck_artifact_versions_row_version`), so this is
# a 412, never a match.
_NO_VERSION: Final = 0


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
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.control = control
        self.checks = MappingProxyType({kind: tuple(c) for kind, c in checks.items()})
        self.clock = clock

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
        self, tx: LifecycleTx, kind: str, version: VersionRow, *, actor_id: uuid.UUID
    ) -> VersionRow:
        """R1.4: the live version this one replaces is retired `superseded`
        first, in the same transaction, then this one goes live; the one-live
        index refuses the other order. Ticket 04's publish handler and its
        tighten-only branch call it, with the kind's hook and the audit."""
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
            tx, kind, version, Stage.LIVE, published_by=actor_id, published_at=now
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

    # ---- submit, withdraw, retire -------------------------------------------

    async def submit(
        self,
        context: AccessContext,
        kind: str,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        expected: ExpectedVersion,
        effect: PendingEffect | None = None,
    ) -> VersionRow:
        """R2.1-R2.3, R2.7, R2.10, R2.12, R7.9: in one transaction, the freeze
        asked, the draft sealed under `If-Match`, the kind's checks run, the
        version moved to `evaluating` and the submit audited."""
        async with self.store.transaction(context) as tx:
            envelope = tx.envelope
            if effect is not None:
                await envelope.claim(effect.of(version_id))
            await self.artifacts.open_for(
                envelope, artifact_id, kind=kind, key=_submit_key, lock=False
            )
            if not await tx.has_quality_gate(kind):
                raise _not_found()  # ticket 04 builds this kind's branch
            refused = await self.control.admission_state(context.tenant_id)
            if refused is not None:
                raise _reason(ConflictError, "submitting is stopped", str(refused))
            sealed = await self._seal(envelope, artifact_id, version_id, expected)
            version = _find(await envelope.versions(artifact_id), version_id)
            for check in self.checks.get(kind, ()):
                refusal = await check(envelope, version, sealed.closure)
                if refusal is not None:
                    raise _reason(DomainError, refusal.detail, refusal.reason_code)
            live = await self._live(envelope, artifact_id)
            moved = await self._move(
                tx,
                kind,
                version,
                Stage.EVALUATING,
                submitted_by=context.principal_id,
                submitted_at=self.clock.now(),
                compared_live_hash=None if live is None else live.definition_hash,
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
        return moved

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
