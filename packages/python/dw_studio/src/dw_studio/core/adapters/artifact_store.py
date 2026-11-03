"""`SqlArtifactStore`: the artifact envelope over schema `studio`, as `dw_app`
under the caller's tenant (RLS).

It decides nothing. The database refuses what a row may not become (the
partial unique indexes, the triggers of revision 67071483caa6), and this module
reads each refusal back by the constraint it names, so a write that went round
the service still answers 409, never 500 (R2.23).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_kernel.pagination import CursorPosition
from dw_kernel.ports import IdGenerator
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.keyset import after_position, newest_first
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.audit import AuditEvent
from dw_studio.core.adapters.tables import (
    artifact_versions,
    artifacts,
    definition_manifests,
    dependencies,
)
from dw_studio.core.application.ports import (
    ArtifactRow,
    DependencyRow,
    Dependent,
    ListScope,
    LiveTarget,
    VersionRow,
)
from dw_studio.core.domain.artifacts import IN_USE_STAGES, Stage

_API_NAME_TAKEN = "uq_artifacts_tenant_id_kind_api_name"
_API_NAME_IMMUTABLE = "ck_artifacts_api_name_immutable"
_UNRELEASED = "uq_artifact_versions_unreleased"
_NOT_IN_USE = "ck_artifacts_not_in_use"
_DEADLOCK = "40P01"

_REACH = sa.text("SELECT platform.workspace_reach(:t, :u, :k) AS w")


def _conflict(message: str, reason: str, **details: object) -> ConflictError:
    return ConflictError(message, details={"reason_code": reason, **details})


def _refused(exc: IntegrityError) -> str | None:
    found = refusal(exc)
    return None if found is None else found[0]


def _artifact(row: Any) -> ArtifactRow:
    return ArtifactRow(
        id=row.id,
        kind=row.kind,
        api_name=row.api_name,
        owning_workspace_id=row.owning_workspace_id,
        labels=tuple(row.labels or ()),
        last_version_no=row.last_version_no,
        row_version=row.row_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _version(row: Any) -> VersionRow:
    return VersionRow(
        id=row.id,
        artifact_id=row.artifact_id,
        stage=Stage(row.stage),
        version_no=row.version_no,
        document_schema=row.document_schema,
        document=row.document,
        content_hash=row.content_hash,
        definition_hash=row.definition_hash,
        row_version=row.row_version,
        based_on_version_id=row.based_on_version_id,
        change_note=row.change_note,
    )


def _in_use_counts(detail: str) -> dict[str, int]:
    """`ck_artifacts_not_in_use`'s DETAIL, `stage=n,...`, as counts by stage."""
    counts: dict[str, int] = {}
    for part in detail.split(","):
        stage, _, n = part.partition("=")
        if stage and n.isdigit():
            counts[stage] = int(n)
    return counts


@dataclass
class SqlArtifactTx:
    """One transaction of `SqlArtifactStore`; see `ArtifactTx`."""

    session: AsyncSession
    context: AccessContext
    ids: IdGenerator

    async def reach(self, permission_key: str) -> frozenset[uuid.UUID]:
        rows = await self.session.execute(
            _REACH,
            {"t": self.context.tenant_id, "u": self.context.principal_id, "k": permission_key},
        )
        return frozenset(row.w for row in rows)

    async def artifact(self, artifact_id: uuid.UUID, *, lock: bool = False) -> ArtifactRow | None:
        statement = sa.select(artifacts).where(
            artifacts.c.id == artifact_id, artifacts.c.deleted_at.is_(None)
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).one_or_none()
        return None if row is None else _artifact(row)

    async def versions(self, artifact_id: uuid.UUID) -> list[VersionRow]:
        rows = await self.session.execute(
            sa.select(artifact_versions).where(artifact_versions.c.artifact_id == artifact_id)
        )
        return [_version(row) for row in rows]

    async def insert_artifact(
        self,
        *,
        artifact_id: uuid.UUID,
        kind: str,
        api_name: str,
        owning_workspace_id: uuid.UUID,
        labels: Sequence[str],
    ) -> ArtifactRow:
        try:
            row = (
                await self.session.execute(
                    sa.insert(artifacts)
                    .values(
                        id=artifact_id,
                        tenant_id=self.context.tenant_id,
                        kind=kind,
                        api_name=api_name,
                        owning_workspace_id=owning_workspace_id,
                        labels=list(labels),
                        row_version=1,
                    )
                    .returning(artifacts)
                )
            ).one()
        except IntegrityError as exc:
            if _refused(exc) == _API_NAME_TAKEN:
                raise _conflict("this API name is taken", "api_name_taken") from exc
            raise
        return _artifact(row)

    async def insert_draft(
        self,
        *,
        version_id: uuid.UUID,
        artifact_id: uuid.UUID,
        document_schema: str,
        document: Any,
        based_on_version_id: uuid.UUID | None,
    ) -> VersionRow:
        try:
            row = (
                await self.session.execute(
                    sa.insert(artifact_versions)
                    .values(
                        id=version_id,
                        tenant_id=self.context.tenant_id,
                        artifact_id=artifact_id,
                        stage=Stage.DRAFT.value,
                        version_no=None,
                        document_schema=document_schema,
                        document=document,
                        row_version=1,
                        based_on_version_id=based_on_version_id,
                    )
                    .returning(artifact_versions)
                )
            ).one()
        except IntegrityError as exc:
            if _refused(exc) == _UNRELEASED:
                raise _conflict("this artifact already has a draft", "draft_exists") from exc
            raise
        return _version(row)

    async def update_artifact(self, artifact_id: uuid.UUID, **values: Any) -> ArtifactRow:
        try:
            row = (
                await self.session.execute(
                    sa.update(artifacts)
                    .where(artifacts.c.id == artifact_id)
                    .values(**values)
                    .returning(artifacts)
                )
            ).one()
        except IntegrityError as exc:
            refused = _refused(exc)
            if refused == _API_NAME_TAKEN:
                raise _conflict("this API name is taken", "api_name_taken") from exc
            if refused == _API_NAME_IMMUTABLE:
                raise _conflict(
                    "the API name is fixed once a version has been live", "api_name_immutable"
                ) from exc
            raise
        return _artifact(row)

    async def update_version(self, version_id: uuid.UUID, **values: Any) -> VersionRow:
        row = (
            await self.session.execute(
                sa.update(artifact_versions)
                .where(artifact_versions.c.id == version_id)
                .values(**values)
                .returning(artifact_versions)
            )
        ).one()
        return _version(row)

    async def soft_delete(self, artifact_id: uuid.UUID) -> None:
        try:
            await self.session.execute(
                sa.update(artifacts)
                .where(artifacts.c.id == artifact_id)
                .values(deleted_at=sa.func.now())
            )
        except IntegrityError as exc:
            found = refusal(exc)
            if found is not None and found[0] == _NOT_IN_USE:
                raise _conflict(
                    "another version uses this artifact",
                    "artifact_in_use",
                    in_use=_in_use_counts(found[1]),
                ) from exc
            raise

    async def live_target(self, artifact_id: uuid.UUID) -> LiveTarget | None:
        # The target row FOR SHARE: a soft delete of it waits for this
        # transaction, then its trigger sees the dependency written here.
        kind = await self.session.scalar(
            sa.select(artifacts.c.kind)
            .where(artifacts.c.id == artifact_id, artifacts.c.deleted_at.is_(None))
            .with_for_update(read=True)
        )
        if kind is None:
            return None
        live = (
            await self.session.execute(
                sa.select(
                    artifact_versions.c.id,
                    artifact_versions.c.version_no,
                    artifact_versions.c.content_hash,
                ).where(
                    artifact_versions.c.artifact_id == artifact_id,
                    artifact_versions.c.stage == Stage.LIVE.value,
                )
            )
        ).first()
        if live is None or live.version_no is None or live.content_hash is None:
            return None
        return LiveTarget(artifact_id, kind, live.id, live.version_no, live.content_hash)

    async def put_manifest(self, definition_hash: str, body: dict[str, Any]) -> None:
        await self.session.execute(
            pg_insert(definition_manifests)
            .values(tenant_id=self.context.tenant_id, hash=definition_hash, body=body)
            .on_conflict_do_nothing(index_elements=["tenant_id", "hash"])
        )

    async def replace_dependencies(
        self, *, artifact_id: uuid.UUID, version_id: uuid.UUID, rows: Sequence[DependencyRow]
    ) -> None:
        await self.session.execute(
            sa.delete(dependencies).where(dependencies.c.from_version_id == version_id)
        )
        if not rows:
            return
        await self.session.execute(
            sa.insert(dependencies),
            [
                {
                    "id": self.ids.new_uuid(),
                    "tenant_id": self.context.tenant_id,
                    "from_artifact_id": artifact_id,
                    "from_version_id": version_id,
                    "to_kind": row.to_kind.value,
                    "to_key": row.to_key,
                    "to_version": row.to_version,
                    "to_hash": row.to_hash,
                    "to_artifact_id": row.to_artifact_id,
                    "to_version_id": row.to_version_id,
                    "usage": row.usage.value,
                    "path": row.path,
                }
                for row in rows
            ],
        )

    async def dependents(self, artifact_id: uuid.UUID) -> list[Dependent]:
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
                dependencies.c.to_artifact_id == artifact_id,
                dependencies.c.from_artifact_id != artifact_id,
                artifact_versions.c.stage.in_([stage.value for stage in IN_USE_STAGES]),
                artifacts.c.deleted_at.is_(None),
            )
            .order_by(artifacts.c.api_name, artifacts.c.id)
        )
        return [
            Dependent(row.id, row.kind, row.api_name, row.owning_workspace_id, Stage(row.stage))
            for row in rows
        ]

    async def list_page(
        self,
        scopes: Sequence[ListScope],
        *,
        label: str | None,
        after: CursorPosition | None,
        fetch_limit: int,
    ) -> list[ArtifactRow]:
        # Each kind only where its read key reaches: a filter in the statement,
        # on the list index, never a page trimmed after the read (R2.11).
        reach = sa.or_(
            *(
                sa.and_(
                    artifacts.c.kind == scope.kind,
                    artifacts.c.owning_workspace_id
                    == sa.any_(sa.cast(sorted(scope.workspaces), ARRAY(PG_UUID(as_uuid=True)))),
                )
                for scope in scopes
            )
        )
        statement = sa.select(artifacts).where(
            artifacts.c.deleted_at.is_(None),
            reach,
            after_position(artifacts.c.updated_at, artifacts.c.id, after),
        )
        if label is not None:
            statement = statement.where(sa.literal(label, sa.Text) == sa.any_(artifacts.c.labels))
        rows = await self.session.execute(
            statement.order_by(*newest_first(artifacts.c.updated_at, artifacts.c.id)).limit(
                fetch_limit
            )
        )
        return [_artifact(row) for row in rows]

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)


@dataclass(frozen=True)
class SqlArtifactStore:
    session_factory: async_sessionmaker[AsyncSession]
    ids: IdGenerator

    @asynccontextmanager
    async def transaction(self, context: AccessContext) -> AsyncIterator[SqlArtifactTx]:
        try:
            async with tenant_session(
                self.session_factory, TenantScope.from_access_context(context)
            ) as session:
                yield SqlArtifactTx(session, context, self.ids)
        except DBAPIError as exc:
            # Two seals of artifacts that use each other can each hold the row
            # the other shares (gate MEDIUM (i)): a retry succeeds, so a 409.
            cause = getattr(exc.orig, "__cause__", None)
            if getattr(cause, "sqlstate", None) == _DEADLOCK:
                raise _conflict("a concurrent write won; try again", "concurrent_write") from exc
            raise
