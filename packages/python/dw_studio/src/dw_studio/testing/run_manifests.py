"""Builders for the run manifest's tests and its measurement (tenant-config
ticket 04): artifacts with a `live` version, a closure of any size, and run
rows that name a manifest.

A version leaves `draft` by the legal path of `dw_studio.testing.lifecycle`
(agent-lifecycle 03); the seal itself changes no stage. A live version is of
`fixture_gateless` and an `evaluating` one of the gated `fixture`, since only
ticket 06's gate takes a gated kind past `evaluating`.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from dw_studio.core.application.service import ArtifactService, SealResult
from dw_studio.testing.lifecycle import move_for_test
from dw_studio.testing.world import Person


def fixture_document(*uses: uuid.UUID, title: str = "Khách hàng", size: int = 0) -> dict[str, Any]:
    return {"title": title, "uses": [str(u) for u in uses], "size": size}


async def draft_of(
    service: ArtifactService, who: Person, document: dict[str, Any], *, kind: str = "fixture"
) -> tuple[uuid.UUID, uuid.UUID, int]:
    """A new artifact and its draft: (artifact, draft version, row_version)."""
    row, draft = await service.create(
        who.context(),
        kind=kind,
        api_name=f"a_{uuid.uuid4().hex[:12]}",
        labels=[],
        document=document,
    )
    return row.id, draft.id, draft.row_version


async def sealed(
    service: ArtifactService, who: Person, artifact_id: uuid.UUID, row_version: int
) -> SealResult:
    async with service.store.transaction(who.context()) as tx:
        return await service.seal(tx, artifact_id, row_version)


async def published(
    service: ArtifactService,
    migrator: AsyncEngine,
    who: Person,
    document: dict[str, Any],
    *,
    stage: str = "live",
) -> tuple[uuid.UUID, SealResult]:
    """An artifact whose version 1 is sealed and moved to `stage`: of the
    gated `fixture` for `evaluating`, of `fixture_gateless` otherwise."""
    kind = "fixture" if stage == "evaluating" else "fixture_gateless"
    artifact_id, _, row_version = await draft_of(service, who, document, kind=kind)
    result = await sealed(service, who, artifact_id, row_version)
    await move_for_test(migrator, result.version_id, stage)
    return artifact_id, result


async def live_closure(
    service: ArtifactService, migrator: AsyncEngine, who: Person, size: int
) -> list[uuid.UUID]:
    """`size` artifacts with a `live` version each: a root that uses them all
    has a closure of `size` entries (R6.6's 50)."""
    return [
        (await published(service, migrator, who, fixture_document(title=f"đích {n}")))[0]
        for n in range(size)
    ]


async def insert_run(
    app_engine: AsyncEngine,
    who: Person,
    *,
    run_mode: str,
    run_manifest_hash: str | None,
) -> uuid.UUID:
    """A run row as the door of workflow-engine/02 will write it, as `dw_app`."""
    run_id = uuid.uuid4()
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.workspace_id', :w, true)"
            ),
            {"t": str(who.tenant_id), "w": str(who.workspace_id)},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id, worker_version, graph_version, requested_by, run_mode,"
                " run_manifest_hash)"
                " VALUES (:r, :r, :t, :w, 'studio', '1', '1', :u, :m, :h)"
            ),
            {
                "r": run_id,
                "t": who.tenant_id,
                "w": who.workspace_id,
                "u": who.id,
                "m": run_mode,
                "h": run_manifest_hash,
            },
        )
    return run_id
