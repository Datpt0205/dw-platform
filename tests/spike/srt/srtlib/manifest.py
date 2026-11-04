"""Question 6 (FOG-59): what the run manifest costs at receipt and at resume,
measured on tenant-config 04's own code (`RunManifestBuilder`,
`SqlRunManifestStore`, `PinnedResolver`) with `dw_studio.testing`'s builders,
as R6.6 of that ticket describes the bench: a closure of 50 `live` artifacts,
one root per build so every build really inserts, a sealed root and a draft.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - this interpreter on a probe of this spike
import sys
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.pinned import PinnedResolver
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.service import ArtifactService
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.run_manifests import (
    draft_of,
    fixture_document,
    insert_run,
    live_closure,
    published,
)
from dw_studio.testing.world import plant_world

from .control import Harness

REF = "sha256:" + "e" * 64

PROBE = """
import asyncio, json, sys, time, uuid
t0 = time.perf_counter()
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from dw_agent_runtime.pinned import PinnedResolver
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
t1 = time.perf_counter()
async def main():
    engine = create_async_engine(sys.argv[1], poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    t2 = time.perf_counter()
    async with tenant_session(sessions, TenantScope(tenant_id=uuid.UUID(sys.argv[2]))) as session:
        pinned = await session.scalar(
            sa.text("SELECT run_manifest_hash FROM platform.worker_runs WHERE id = :r"),
            {"r": uuid.UUID(sys.argv[3])})
        resolver = await PinnedResolver.load(SqlRunManifestStore(session), str(pinned))
    t3 = time.perf_counter()
    await engine.dispose()
    print(json.dumps({"imports_ms": (t1 - t0) * 1000, "load_ms": (t3 - t2) * 1000}))
asyncio.run(main())
"""


def _ms(values: list[float]) -> dict[str, Any]:
    from .measure import summary

    return summary(values)


async def measure(h: Harness, roots: int) -> dict[str, Any]:
    migrator = create_async_engine(h.urls.migrator, poolclass=NullPool)
    app = create_async_engine(h.urls.app, pool_size=4)
    ids = Uuid7Generator()
    sessions = async_sessionmaker(app, class_=AsyncSession, expire_on_commit=False)
    store = SqlArtifactStore(sessions, ids)
    registry = ArtifactKindRegistry(FIXTURE_KINDS)
    service = ArtifactService(store, registry, SystemClock(), ids)
    builder = RunManifestBuilder(registry, REF)
    out: dict[str, Any] = {"closure": 50, "roots": roots}
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            world = await plant_world(conn)
        who = world["writer"]
        setup = time.perf_counter()
        targets = await live_closure(service, migrator, who, 50)
        sealed_roots = []
        for n in range(roots):
            _, result = await published(
                service, migrator, who, fixture_document(*targets, title=f"gốc {n}")
            )
            sealed_roots.append(result.version_id)
        draft_roots = []
        for n in range(roots):
            _, version_id, _ = await draft_of(
                service, who, fixture_document(*targets, title=f"nháp {n}")
            )
            draft_roots.append(version_id)
        out["setup_seconds"] = round(time.perf_counter() - setup, 1)

        async def build(version_id: uuid.UUID, mode: Any) -> tuple[float, str]:
            t0 = time.perf_counter()
            async with store.transaction(who.context()) as tx:
                found = await builder.build(tx, version_id, mode)
            return (time.perf_counter() - t0) * 1000, found

        warm = 20
        sealed_ms, hashes = [], []
        for i, version_id in enumerate(sealed_roots):
            ms, found = await build(version_id, "live")
            if i >= warm:
                sealed_ms.append(ms)
            hashes.append(found)
        draft_ms = []
        for i, version_id in enumerate(draft_roots):
            ms, _ = await build(version_id, "simulate")
            if i >= warm:
                draft_ms.append(ms)
        out["build_sealed_live_ms"] = _ms(sealed_ms)
        out["build_draft_simulate_ms"] = _ms(draft_ms)
        # A resume in this process, warm, then in fresh interpreters.
        runs = [
            await insert_run(app, who, run_mode="live", run_manifest_hash=found)
            for found in hashes[:300]
        ]
        load_ms = []
        for i in range(len(runs)):
            t0 = time.perf_counter()
            async with tenant_session(sessions, TenantScope(tenant_id=who.tenant_id)) as session:
                await PinnedResolver.load(SqlRunManifestStore(session), hashes[i])
            if i >= warm:
                load_ms.append((time.perf_counter() - t0) * 1000)
        out["resume_load_warm_ms"] = _ms(load_ms)
        cold: list[dict[str, Any]] = []
        for run_id in runs[:20]:
            done = subprocess.run(
                [sys.executable, "-c", PROBE, h.urls.app, str(who.tenant_id), str(run_id)],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if done.returncode == 0:
                cold.append(json.loads(done.stdout.strip().splitlines()[-1]))
            else:
                cold.append({"error": done.stderr[-400:]})
        out["resume_fresh_process"] = {
            "load_ms_with_new_connection": _ms([c["load_ms"] for c in cold if "load_ms" in c]),
            "imports_ms": _ms([c["imports_ms"] for c in cold if "imports_ms" in c]),
            "errors": [c for c in cold if "error" in c][:2],
        }
    await app.dispose()
    await migrator.dispose()
    return out
