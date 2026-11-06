"""A Studio run's row and its version's published boundary, planted for an
integration test (custom-objects ticket 03; tools-and-skills ticket 03).

Here and not in `dw_studio.testing`: only the run door inserts a Studio run in
source (`test_run_request_door.py` scans every `src/`), so the row a test needs
is written by the test, as the migrator, the way the door writes it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from dw_platform.adapters.persistence.tenant_session import TenantScope, bind_tenant
from dw_platform.testing.rbac import PlantedTenant
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.testing.record_world import RunKind


def _digest() -> str:
    return "sha256:" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()


async def plant_run(
    migrator: AsyncEngine,
    app: AsyncEngine,
    tenant: PlantedTenant,
    principal: uuid.UUID,
    objects: Sequence[ObjectBoundary],
    fields: Sequence[FieldBoundary],
    *,
    kind: RunKind = "workflow",
    mode: str = "live",
) -> uuid.UUID:
    """A run of a sealed `workflow` (or `agent`) version acting as
    ``principal``, its row as the run door writes it, and the version's
    published boundary allowing ``objects`` and ``fields``."""
    t, run = tenant.tenant_id, uuid.uuid4()
    artifact, version, digest, manifest = uuid.uuid4(), uuid.uuid4(), _digest(), _digest()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
                " row_version) VALUES (:a, :t, :k, :n, :w, 1)"
            ),
            # A `workflow` artifact for both kinds, as the boundary tests plant
            # an agent's run (no `agent` kind is registered in W1).
            {
                "a": artifact,
                "t": t,
                "k": "workflow",
                "n": f"r_{artifact.hex[:12]}",
                "w": tenant.main,
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
                " version_no, document_schema, document, row_version, contributor_ids,"
                " content_hash, definition_hash) VALUES (:v, :t, :a, 'draft', 1, :s, '{}', 1,"
                " ARRAY[:u]::uuid[], :c, :h)"
            ),
            {
                "v": version,
                "t": t,
                "a": artifact,
                "s": "dw.workflow/v1",
                "u": principal,
                "c": _digest(),
                "h": digest,
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
                " VALUES (:t, :h, CAST(:b AS jsonb))"
            ),
            {"t": t, "h": manifest, "b": json.dumps({"run_mode": mode})},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id, worker_version, graph_version, requested_by, run_as_principal_id,"
                " run_mode, run_manifest_hash, artifact_kind, artifact_id, artifact_version_id,"
                " definition_hash, trigger_kind, request_key, root_run_id, chain_depth)"
                " VALUES (:r, :r, :t, :w, 'studio', '1', '1', :p, :p, :m, :h, :k, :a, :v, :d,"
                " :tk, :rk, :r, 0)"
            ),
            {
                "r": run,
                "t": t,
                "w": tenant.main,
                "p": principal,
                "m": mode,
                "h": manifest,
                "k": kind,
                "a": artifact,
                "v": version,
                "d": digest,
                "tk": "test" if mode == "simulate" else "manual",
                "rk": f"k:{run}",
            },
        )
    async with app.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=t))
        await SqlActorBoundaries().record(conn, kind, version, digest, objects, fields)
    return run
