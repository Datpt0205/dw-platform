"""`SqlLifecycleStore`: the stage machine's reads and writes beyond the
envelope (the publish request, its decision, the `studio.version.live` event),
on the envelope's own session (as `dw_app`, under the caller's tenant, or the
tenant alone for a recorded decision); `SqlKillStore`:
a kill's switch statements on that same session (agent-lifecycle ticket 05).

It decides nothing: `studio.guard_version_stage()` refuses a move, and the
envelope's `update_version` reads that refusal back by its constraint name.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dw_kernel.errors import NotFoundError
from dw_platform.adapters.persistence import tables as platform
from dw_platform.adapters.persistence.control_switches_repo import control_switch_tx
from dw_platform.adapters.persistence.repositories import (
    SqlApprovalRepository,
    SqlOutboxRepository,
    _approval_from_row,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ApprovalAudience
from dw_platform.application.control_switches import ControlSwitchTx
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.outbox import OutboxEvent
from dw_studio.core.adapters.artifact_store import SqlArtifactStore, SqlArtifactTx
from dw_studio.core.adapters.tables import (
    artifact_kinds,
    artifact_versions,
    artifacts,
    dependencies,
)
from dw_studio.core.application.ports import Dependent
from dw_studio.core.domain.artifacts import Stage
from dw_studio.lifecycle.application.ports import PublishDecision

# The plan of a context rebuilt from a recorded decision: no entitlement is
# read from it (`carry_out`).
RECORDED_DECISION = "recorded_decision"

_requests = platform.approval_requests
_decisions = platform.approval_decisions


@dataclass
class SqlLifecycleTx:
    envelope: SqlArtifactTx

    @property
    def session(self) -> AsyncSession:
        return self.envelope.session

    def carry_out(self, decision: PublishDecision, lane: str) -> None:
        # The recorded decision's person, not a verified request: no roles and
        # no plan, only who they are and where they decided.
        self.envelope.context = AccessContext(
            tenant_id=self.envelope.tenant_id,
            workspace_id=decision.workspace_id,
            principal_id=decision.decided_by,
            roles=frozenset(),
            plan_id=RECORDED_DECISION,
        )
        self.envelope.lane = lane

    async def has_quality_gate(self, kind: str) -> bool:
        gated = await self.session.scalar(
            sa.select(artifact_kinds.c.has_quality_gate).where(artifact_kinds.c.kind == kind)
        )
        if gated is None:
            raise NotFoundError("no such kind")
        return bool(gated)

    async def publish_approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        # Tenant RLS alone, not the platform repository's workspace filter: the
        # right to withdraw is the submit key's at the artifact's workspace.
        row = (
            await self.session.execute(
                sa.select(platform.approval_requests)
                .where(platform.approval_requests.c.id == approval_id)
                .with_for_update()
            )
        ).first()
        return None if row is None else _approval_from_row(row)

    async def save_approval(self, request: ApprovalRequest) -> None:
        await SqlApprovalRepository(self.session).save(request)

    async def live_dependents(self, version_id: uuid.UUID) -> list[Dependent]:
        rows = await self.session.execute(
            sa.select(
                artifacts.c.id,
                artifacts.c.kind,
                artifacts.c.api_name,
                artifacts.c.owning_workspace_id,
                artifact_versions.c.stage,
            )
            .distinct()
            .select_from(
                dependencies.join(
                    artifact_versions,
                    sa.and_(
                        artifact_versions.c.tenant_id == dependencies.c.tenant_id,
                        artifact_versions.c.id == dependencies.c.from_version_id,
                    ),
                ).join(
                    artifacts,
                    sa.and_(
                        artifacts.c.tenant_id == dependencies.c.tenant_id,
                        artifacts.c.id == dependencies.c.from_artifact_id,
                    ),
                )
            )
            .where(
                dependencies.c.to_version_id == version_id,
                dependencies.c.from_artifact_id != dependencies.c.to_artifact_id,
                artifact_versions.c.stage == Stage.LIVE.value,
                artifacts.c.deleted_at.is_(None),
            )
            .order_by(artifacts.c.api_name, artifacts.c.id)
        )
        return [
            Dependent(row.id, row.kind, row.api_name, row.owning_workspace_id, Stage(row.stage))
            for row in rows
        ]

    async def open_approval(self, request: ApprovalRequest) -> None:
        await SqlApprovalRepository(self.session).add(request)

    async def announce(self, event: OutboxEvent) -> None:
        await SqlOutboxRepository(self.session).add(event)

    async def publish_decision(self, approval_id: uuid.UUID) -> PublishDecision | None:
        row = (
            await self.session.execute(
                sa.select(
                    _requests.c.approval_type,
                    _requests.c.status,
                    _requests.c.workspace_id,
                    _decisions.c.decided_by,
                )
                .join(
                    _decisions,
                    sa.and_(
                        _decisions.c.tenant_id == _requests.c.tenant_id,
                        _decisions.c.request_id == _requests.c.id,
                    ),
                )
                .where(_requests.c.id == approval_id)
                .order_by(_decisions.c.decided_at.desc())
                .limit(1)
            )
        ).first()
        if row is None or row.status not in ("approved", "rejected"):
            return None
        return PublishDecision(
            approval_type=row.approval_type,
            approved=row.status == "approved",
            workspace_id=row.workspace_id,
            decided_by=row.decided_by,
        )

    async def candidate_artifact(self, approval_id: uuid.UUID) -> uuid.UUID | None:
        found = await self.session.scalar(
            sa.select(artifact_versions.c.artifact_id).where(
                artifact_versions.c.publish_approval_id == approval_id
            )
        )
        return None if found is None else uuid.UUID(str(found))

    async def visible_approval(
        self, approval_id: uuid.UUID, *, workspace_id: uuid.UUID, audience: ApprovalAudience
    ) -> ApprovalRequest | None:
        return await SqlApprovalRepository(self.session).get(
            approval_id, workspace_id=workspace_id, audience=audience
        )


@dataclass(frozen=True)
class SqlLifecycleStore:
    artifacts: SqlArtifactStore

    @asynccontextmanager
    async def transaction(self, context: AccessContext) -> AsyncIterator[SqlLifecycleTx]:
        async with self.artifacts.transaction(context) as envelope:
            yield SqlLifecycleTx(envelope)

    @asynccontextmanager
    async def for_tenant(self, tenant_id: uuid.UUID) -> AsyncIterator[SqlLifecycleTx]:
        async with self.artifacts.for_tenant(tenant_id) as envelope:
            yield SqlLifecycleTx(envelope)


@dataclass
class SqlKillTx:
    """`KillTx`: the envelope's session, and the switch statements bound to it."""

    envelope: SqlArtifactTx
    switches: ControlSwitchTx


@dataclass(frozen=True)
class SqlKillStore:
    artifacts: SqlArtifactStore

    @asynccontextmanager
    async def transaction(self, context: AccessContext) -> AsyncIterator[SqlKillTx]:
        async with self.artifacts.transaction(context) as envelope:
            yield SqlKillTx(envelope, control_switch_tx(envelope.session, context.tenant_id))
