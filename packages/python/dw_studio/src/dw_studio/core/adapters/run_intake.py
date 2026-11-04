"""The run row `RunRequestService` writes, on the session of the caller's
transaction (workflow-engine R3.3, R3.6, R3.20).

The only module that inserts a Studio run into `platform.worker_runs`; an
architecture test holds that (WE1). It decides nothing: the CHECKs of
revision 703be798341f refuse a row a Studio run may not be, and
`uq_worker_runs_tenant_id_request_key` is the `ON CONFLICT` target, so two
requests with one key leave one row.

The `actor_*` columns get their narrowest values, never their DEFAULT
(`'open'` would read as "sees every owner"): a Studio run's reach is read
live at each start and resume (workflow-engine R6.12), never from this stamp.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_studio.core.application.run_request import ExistingRun, QueuedRun


async def run_by_request_key(session: AsyncSession, request_key: str) -> ExistingRun | None:
    row = (
        await session.execute(
            sa.select(
                worker_runs.c.id,
                worker_runs.c.artifact_version_id,
                worker_runs.c.run_mode,
                worker_runs.c.run_as_principal_id,
                worker_runs.c.input,
            ).where(worker_runs.c.request_key == request_key)
        )
    ).one_or_none()
    if row is None:
        return None
    return ExistingRun(
        id=row.id,
        artifact_version_id=row.artifact_version_id,
        run_mode=row.run_mode,
        run_as_principal_id=row.run_as_principal_id,
        input=row.input,
    )


async def insert_queued_run(session: AsyncSession, tenant_id: uuid.UUID, run: QueuedRun) -> bool:
    inserted = await session.scalar(
        pg_insert(worker_runs)
        .values(
            id=run.id,
            # The run's own thread; a `chat` run names its conversation's when
            # agent-builder connects it.
            thread_id=run.id,
            tenant_id=tenant_id,
            workspace_id=run.workspace_id,
            worker_id=run.worker_id,
            worker_version=run.worker_version,
            graph_version=run.graph_version,
            status=RunStatus.QUEUED.value,
            input=dict(run.input),
            requested_by=run.requested_by,
            run_as_principal_id=run.run_as_principal_id,
            run_mode=run.run_mode,
            run_manifest_hash=run.run_manifest_hash,
            definition_hash=run.definition_hash,
            release_manifest_ref=run.release_manifest_ref,
            artifact_kind=run.artifact_kind,
            artifact_id=run.artifact_id,
            artifact_version_id=run.artifact_version_id,
            trigger_kind=run.trigger_kind,
            inbound_event_id=run.inbound_event_id,
            request_key=run.request_key,
            priority=run.priority,
            actor_roles=[],
            actor_scopes=[],
            actor_plan_id="",
            actor_clearance="internal",
            actor_record_visibility="restricted",
            actor_visible_owners=[],
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
        .on_conflict_do_nothing(
            index_elements=[worker_runs.c.tenant_id, worker_runs.c.request_key],
            index_where=worker_runs.c.request_key.is_not(None),
        )
        .returning(worker_runs.c.id)
    )
    return inserted is not None
