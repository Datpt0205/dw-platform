"""`SqlRunManifestStore`: `RunManifestPort` over `platform.run_manifests` and
the version rows its keys hold (tenant-config R6.3, R6.4; ADR-0109 decision 7).

Bound to one session whose transaction carries the run's tenant; every read is
`dw_app` under RLS, and names no tenant itself, so another tenant's hash reads
as no manifest at all. Each key row is joined to the exact version it pinned,
never to an artifact's current one. A row now in `draft` gets `current_hash`,
its content hashed again the way it was pinned: the root by `definition_body`
over its content and the closure pinned in the body (never `closure_of`, so a
dependency published while the run waits changes nothing), any other row by
the hash of its content. Comparing is `PinnedResolver`'s.

`SqlRunManifestEngines` answers `PinnedEnginePort` for `ModelResolver`: the
`engine` section of one manifest, in a transaction of its own under the run's
tenant (model-connections R1.4, R1.5), so a model door that holds only the
run's context reads what the run pinned and nothing current.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.ports import PinnedEntry, PinnedManifest, PinnedVersion
from dw_kernel.canonical import content_hash
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.tables import artifact_versions, run_manifest_keys, run_manifests
from dw_studio.core.domain.artifacts import (
    ClosureItem,
    Stage,
    TargetKind,
    definition_body,
    definition_hash,
)

# Each key row to the version it pinned.
_PINNED = sa.and_(
    artifact_versions.c.tenant_id == run_manifest_keys.c.tenant_id,
    artifact_versions.c.id == run_manifest_keys.c.artifact_version_id,
)


def _current_hash(row: Any, root: Mapping[str, Any], closure: list[ClosureItem]) -> str | None:
    if row.stage != Stage.DRAFT.value:
        return None
    if row.id == uuid.UUID(str(root["version_id"])):
        body = definition_body(
            str(root["kind"]), row.artifact_id, content_hash(row.document), closure
        )
        return definition_hash(body)
    return content_hash(row.document)


def _closure(body: Mapping[str, Any]) -> list[ClosureItem]:
    return [
        ClosureItem(item["kind"], item["key"], item["version"], item["content_hash"])
        for item in body["closure"]
    ]


@dataclass(frozen=True)
class SqlRunManifestStore:
    session: AsyncSession

    async def load(self, run_manifest_hash: str) -> PinnedManifest | None:
        body = await self.session.scalar(
            sa.select(run_manifests.c.body).where(run_manifests.c.hash == run_manifest_hash)
        )
        if body is None:
            return None
        rows = (
            await self.session.execute(
                sa.select(
                    run_manifest_keys.c.artifact_version_id.label("key_version_id"),
                    artifact_versions.c.id,
                    artifact_versions.c.artifact_id,
                    artifact_versions.c.version_no,
                    artifact_versions.c.stage,
                    artifact_versions.c.content_hash,
                    artifact_versions.c.definition_hash,
                    artifact_versions.c.document_schema,
                    artifact_versions.c.document,
                )
                .select_from(run_manifest_keys.outerjoin(artifact_versions, _PINNED))
                .where(run_manifest_keys.c.manifest_hash == run_manifest_hash)
            )
        ).all()
        root = body["root"]
        closure = _closure(body)
        versions = {
            row.artifact_id: PinnedVersion(
                id=row.id,
                artifact_id=row.artifact_id,
                version_no=row.version_no,
                stage=row.stage,
                content_hash=row.content_hash,
                definition_hash=row.definition_hash,
                document_schema=row.document_schema,
                document=row.document,
                current_hash=_current_hash(row, root, closure),
            )
            for row in rows
            if row.id is not None
        }
        root_id = uuid.UUID(str(root["artifact_id"]))
        return PinnedManifest(
            hash=run_manifest_hash,
            body=body,
            root=PinnedEntry(
                kind=str(root["kind"]),
                key=str(root_id),
                version=root["version_no"],
                content_hash=root["definition_hash"],
                artifact=versions.get(root_id),
            ),
            closure=tuple(
                PinnedEntry(
                    kind=item.kind,
                    key=item.key,
                    version=item.version,
                    content_hash=item.content_hash,
                    artifact=(
                        versions.get(uuid.UUID(item.key))
                        if item.kind == TargetKind.ARTIFACT.value
                        else None
                    ),
                )
                for item in closure
            ),
            unread_keys=tuple(row.key_version_id for row in rows if row.id is None),
        )


@dataclass(frozen=True)
class SqlRunManifestEngines:
    session_factory: async_sessionmaker[AsyncSession]

    async def engine(
        self, tenant_id: uuid.UUID, run_manifest_hash: str
    ) -> Mapping[str, Any] | None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            body = await session.scalar(
                sa.select(run_manifests.c.body).where(run_manifests.c.hash == run_manifest_hash)
            )
        if body is None:
            return None
        engine: Mapping[str, Any] = body["engine"]
        return engine
