"""A resume in another process, as far as ticket 04 reaches (tenant-config
R6.4, TC15): a fresh interpreter and a fresh connection read a run's
`run_manifest_hash` from its row, load the manifest with `PinnedResolver`
through `SqlRunManifestStore`, and print what one pinned key resolves to.

    python -m dw_studio.testing.pinned_probe <dw_app url> <tenant> <run id> <kind> <key>

Prints one JSON object: `{"refused": <reason>}` for a `ConfigError`, otherwise
the entry's pinned version and its row's id and document. The real resume
through the runner is workflow-engine/05's.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.pinned import PinnedResolver
from dw_kernel.errors import ConfigError
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore


async def probe(url: str, tenant: uuid.UUID, run_id: uuid.UUID, kind: str, key: str) -> Any:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with tenant_session(sessions, TenantScope(tenant_id=tenant)) as session:
            pinned = await session.scalar(
                sa.text("SELECT run_manifest_hash FROM platform.worker_runs WHERE id = :r"),
                {"r": run_id},
            )
            try:
                resolver = await PinnedResolver.load(SqlRunManifestStore(session), str(pinned))
                entry = resolver.resolve(kind, key)
            except ConfigError as exc:
                return {"refused": exc.details.get("reason")}
    finally:
        await engine.dispose()
    row = entry.artifact
    return {
        "version": entry.version,
        "version_id": None if row is None else str(row.id),
        "document": None if row is None else row.document,
    }


def main(argv: list[str]) -> int:
    url, tenant, run_id, kind, key = argv
    answer = asyncio.run(probe(url, uuid.UUID(tenant), uuid.UUID(run_id), kind, key))
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
