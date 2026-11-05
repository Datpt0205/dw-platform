"""`SqlStudioRunStore`: `StudioRunStorePort` over `platform.worker_runs`, the
run manifest and the version rows it pins (workflow-engine/03 step 2, R4.11,
R6.14; ADR-0109 decision 7).

Every call is one transaction of `dw_app` under the run's tenant (RLS), so
another tenant's run is no run. `take` reads the `queued` row `FOR UPDATE`,
then the root artifact `FOR SHARE` (so a `save_draft` of a draft root waits,
as at the door), then the manifest through `PinnedResolver.load`, which
hashes a draft's content again the way it was pinned: a draft changed since
leaves the run `blocked` with `incompatible_resume`, and nothing is compiled.
The plan the run's `RunContext` carries is the tenant's own, read here
(model-connections ticket 02, MEDIUM (a)).

`cancel_past_deadline` ends the run and audits `run.deadline_exceeded` as the
`studio_runs` lane in one transaction (CLAUDE.md, Agent and tool rules: a lane
acting on its own audits as itself).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import StudioRun, StudioRunBlocked
from dw_kernel.errors import ConfigError, ConflictError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.domain.audit import lane_audit_event
from dw_studio.core.adapters.run_intake import tenant_plan
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.adapters.tables import artifacts

LANE: Final = "studio_runs"
DEADLINE_EXCEEDED: Final = "run.deadline_exceeded"
INCOMPATIBLE_RESUME: Final = "incompatible_resume"


def _not_queued() -> ConflictError:
    return ConflictError(
        "the run is not a queued Studio run of this tenant",
        details={"reason_code": "run_not_queued"},
    )


@dataclass(frozen=True)
class SqlStudioRunStore:
    session_factory: async_sessionmaker[AsyncSession]
    ids: IdGenerator
    clock: UtcClock

    async def take(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> StudioRun | StudioRunBlocked:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            row = (
                await session.execute(
                    sa.select(worker_runs).where(worker_runs.c.id == run_id).with_for_update()
                )
            ).one_or_none()
            if row is None or row.artifact_kind is None or row.status != RunStatus.QUEUED.value:
                raise _not_queued()
            (
                await session.execute(
                    sa.select(artifacts.c.id)
                    .where(artifacts.c.id == row.artifact_id)
                    .with_for_update(read=True)
                )
            ).all()
            try:
                resolver = await PinnedResolver.load(
                    SqlRunManifestStore(session), str(row.run_manifest_hash)
                )
            except ConfigError as exc:
                if exc.details.get("reason") != "pinned_version_changed":
                    raise
                await self._set(
                    session, run_id, RunStatus.BLOCKED, error={"code": INCOMPATIBLE_RESUME}
                )
                return StudioRunBlocked(run_id, INCOMPATIBLE_RESUME)
            plan = await tenant_plan(session)
            await self._set(session, run_id, RunStatus.RUNNING)
            root = resolver.root.artifact
            assert root is not None  # `load` refuses a root it cannot read
            return StudioRun(
                run_id=row.id,
                thread_id=row.thread_id,
                tenant_id=tenant_id,
                workspace_id=row.workspace_id,
                artifact_kind=row.artifact_kind,
                artifact_version_id=row.artifact_version_id,
                pinned_hash=str(resolver.root.content_hash),
                run_mode=row.run_mode,
                requested_by=row.requested_by,
                run_as_principal_id=row.run_as_principal_id,
                run_manifest_hash=str(row.run_manifest_hash),
                plan_id=plan or "",
                deadline_at=row.deadline_at,
                input=dict(row.input or {}),
                pinned_results=row.pinned_results,
                document=root.document,
                engine=dict(resolver.body.get("engine") or {}),
                version_no=root.version_no,
                trace_id=row.trace_id or str(run_id),
            )

    async def finish(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        status: Literal["completed", "failed", "cancelled"],
        *,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            await self._set(session, run_id, RunStatus(status), error=error, result=result)

    async def cancel_past_deadline(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            workspace = await self._set(
                session, run_id, RunStatus.CANCELLED, error={"code": "deadline_exceeded"}
            )
            if workspace is None:
                return False
            await SqlAuditRepository(session).append(
                lane_audit_event(
                    lane=LANE,
                    event_id=self.ids.new_uuid(),
                    tenant_id=TenantId(tenant_id),
                    workspace_id=WorkspaceId(workspace),
                    action=DEADLINE_EXCEEDED,
                    resource_type="worker_run",
                    resource_id=str(run_id),
                    occurred_at=self.clock.now(),
                    details={"reason_code": "deadline_exceeded"},
                    run_id=run_id,
                )
            )
            return True

    async def _set(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> uuid.UUID | None:
        """Move the run on from where it stands (`queued` to `running` or
        `blocked`, `running` to an end); the workspace of the row moved, None
        when it no longer stood there."""
        values: dict[str, Any] = {"status": status.value, "updated_at": sa.func.now()}
        if error is not None:
            values["error"] = dict(error)
        if result is not None:
            values["result"] = dict(result)
        source = (
            RunStatus.QUEUED
            if status in (RunStatus.RUNNING, RunStatus.BLOCKED)
            else RunStatus.RUNNING
        )
        found: uuid.UUID | None = await session.scalar(
            sa.update(worker_runs)
            .where(worker_runs.c.id == run_id, worker_runs.c.status == source.value)
            .values(**values)
            .returning(worker_runs.c.workspace_id)
        )
        return found
