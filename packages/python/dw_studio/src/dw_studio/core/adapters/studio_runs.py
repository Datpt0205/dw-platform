"""`SqlStudioRunStore`: `StudioRunStorePort` over `platform.worker_runs`, the
run manifest and the version rows it pins (workflow-engine/03 step 2, R4.11,
R6.14; ADR-0109 decision 7).

Every call is one transaction of `dw_app` under the run's tenant (RLS), so
another tenant's run is no run. `take` reads the claimed row `FOR UPDATE`,
then the root artifact `FOR SHARE` (so a `save_draft` of a draft root waits,
as at the door), then the manifest through `PinnedResolver.load`, which
hashes a draft's content again the way it was pinned: a draft changed since
leaves the run `blocked` with `incompatible_resume`, and nothing is compiled.
The plan the run's `RunContext` carries is the tenant's own, read here
(model-connections ticket 02, MEDIUM (a)).

`cancel_past_deadline` ends the run and audits `run.deadline_exceeded` as the
`studio_runs` lane in one transaction (CLAUDE.md, Agent and tool rules: a lane
acting on its own audits as itself).

Every call names the claim the `studio_runs` lane made (workflow-engine/04,
R5.5): a row is read and written only `WHERE lease_owner = :token`, so a
worker whose claim lapsed and was taken over reads `StudioLeaseLostError` and
writes nothing. A run leaves `running` with its claim cleared.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import STUDIO_RUN, worker_runs
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import StudioLeaseLostError, StudioRun, StudioRunBlocked
from dw_agent_runtime.studio_lane import LANE
from dw_kernel.errors import ConfigError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.residency import parse_route_class
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.domain.audit import lane_audit_event
from dw_studio.core.adapters.run_intake import tenant_plan
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.adapters.tables import artifacts

DEADLINE_EXCEEDED: Final = "run.deadline_exceeded"
INCOMPATIBLE_RESUME: Final = "incompatible_resume"


@dataclass(frozen=True)
class SqlStudioRunStore:
    session_factory: async_sessionmaker[AsyncSession]
    ids: IdGenerator
    clock: UtcClock

    async def take(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> StudioRun | StudioRunBlocked:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            row = (
                await session.execute(
                    sa.select(worker_runs)
                    .where(_claimed(run_id, lease_token), STUDIO_RUN)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise StudioLeaseLostError(run_id)
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
                await self._leave(
                    session,
                    run_id,
                    lease_token,
                    RunStatus.BLOCKED,
                    error={"code": INCOMPATIBLE_RESUME},
                )
                return StudioRunBlocked(run_id, INCOMPATIBLE_RESUME)
            plan = await tenant_plan(session)
            root = resolver.root.artifact
            assert root is not None  # `load` refuses a root it cannot read
            return StudioRun(
                run_id=row.id,
                thread_id=row.thread_id,
                tenant_id=tenant_id,
                workspace_id=row.workspace_id,
                artifact_kind=row.artifact_kind,
                artifact_id=row.artifact_id,
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
                # As admitted; NULL is a row admitted before the column.
                data_route_class=parse_route_class(row.data_route_class or "vn_only"),
                trigger_kind=row.trigger_kind or "",
                root_run_id=None if row.root_run_id == row.id else row.root_run_id,
            )

    async def admitted(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str, deadline: timedelta
    ) -> datetime:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            # Set once, at the first take that passed dispatch; a take again
            # (after a wait, a requeue) keeps it (R5.22).
            found: datetime | None = await session.scalar(
                sa.update(worker_runs)
                .where(_claimed(run_id, lease_token))
                .values(
                    deadline_at=sa.func.coalesce(
                        worker_runs.c.deadline_at, sa.func.now() + sa.literal(deadline)
                    ),
                    updated_at=sa.func.now(),
                )
                .returning(worker_runs.c.deadline_at)
            )
        if found is None:
            raise StudioLeaseLostError(run_id)
        return found

    async def hold(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        lease_token: str,
        delay: timedelta,
        until: datetime | None = None,
    ) -> None:
        due: Any = sa.literal(until) if until is not None else sa.func.now() + sa.literal(delay)
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            await session.execute(
                sa.update(worker_runs)
                .where(_claimed(run_id, lease_token))
                .values(
                    status=RunStatus.QUEUED.value,
                    lease_owner=None,
                    lease_until=None,
                    available_at=due,
                    updated_at=sa.func.now(),
                )
            )

    async def finish(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        status: Literal["completed", "failed", "cancelled"],
        *,
        lease_token: str,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
    ) -> None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            await self._leave(
                session,
                run_id,
                lease_token,
                RunStatus(status),
                error=error,
                result=result,
                outcomes=outcomes,
            )

    async def cancel_past_deadline(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, *, lease_token: str
    ) -> bool:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            workspace = await self._leave(
                session,
                run_id,
                lease_token,
                RunStatus.CANCELLED,
                error={"code": "deadline_exceeded"},
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

    @staticmethod
    async def _leave(
        session: AsyncSession,
        run_id: uuid.UUID,
        lease_token: str,
        status: RunStatus,
        *,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
    ) -> uuid.UUID | None:
        """Move the claimed run out of `running`, its claim cleared; the
        workspace of the row moved, None when the claim was no longer held or
        the run had already left `running` (a kill's cancel)."""
        values: dict[str, Any] = {
            "status": status.value,
            "lease_owner": None,
            "lease_until": None,
            "outcomes": list(outcomes),
            "updated_at": sa.func.now(),
        }
        if error is not None:
            values["error"] = dict(error)
        if result is not None:
            values["result"] = dict(result)
        found: uuid.UUID | None = await session.scalar(
            sa.update(worker_runs)
            .where(_claimed(run_id, lease_token))
            .values(**values)
            .returning(worker_runs.c.workspace_id)
        )
        return found


def _claimed(run_id: uuid.UUID, lease_token: str) -> sa.ColumnElement[bool]:
    """The run, while it is `running` under this claim (R5.5)."""
    return sa.and_(
        worker_runs.c.id == run_id,
        worker_runs.c.status == RunStatus.RUNNING.value,
        worker_runs.c.lease_owner == lease_token,
    )
