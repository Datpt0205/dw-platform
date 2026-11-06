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
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError, PayloadTooLargeError, PermissionDeniedError
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
from dw_studio.core.adapters import run_intake
from dw_studio.core.adapters.tables import (
    artifact_display_stage,
    artifact_versions,
    artifacts,
    config_versions,
    definition_manifests,
    dependencies,
    run_manifest_keys,
    run_manifests,
)
from dw_studio.core.application.bindings import BINDING_SET
from dw_studio.core.application.ports import (
    ArtifactRow,
    BindingSetRow,
    ConnectionFacts,
    DependencyRow,
    Dependent,
    ListScope,
    LiveTarget,
    RootVersion,
    VersionRow,
)
from dw_studio.core.application.run_request import ExistingRun, LaneRequester, QueuedRun
from dw_studio.core.domain.artifacts import IN_USE_STAGES, Stage, TargetKind

_API_NAME_TAKEN = "uq_artifacts_tenant_id_kind_api_name"
_API_NAME_IMMUTABLE = "ck_artifacts_api_name_immutable"
_UNRELEASED = "uq_artifact_versions_unreleased"
_NOT_IN_USE = "ck_artifacts_not_in_use"
_STAGE_REFUSED = "ck_artifact_versions_stage_transition"
_LIVE = "uq_artifact_versions_live"
_RUN_MANIFEST_SIZE = "ck_run_manifests_body_size"
_DEADLOCK = "40P01"

_REACH = sa.text("SELECT platform.workspace_reach(:t, :u, :k) AS w")
_CONNECTION_FACTS = sa.text(
    "SELECT id, connector_key, connector_major, scopes, owning_workspace_id, name"
    " FROM platform.connections WHERE id = ANY(:ids)"
).bindparams(sa.bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))))
_PRINCIPAL_STATUS = sa.text(
    "SELECT user_id, status = 'active' AS active FROM platform.tenant_members"
    " WHERE user_id = ANY(:ids)"
).bindparams(sa.bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))))
# R3.7: the artifacts, not soft-deleted, whose approved Binding set has this
# connection as a value; one source, never `studio.dependencies` (R7.1).
_USING = sa.text(
    "SELECT a.id FROM platform.config_versions v"
    " JOIN studio.artifacts a ON a.tenant_id = v.tenant_id AND a.id::text = v.key"
    " WHERE v.kind = 'binding_set' AND v.status = 'approved' AND a.deleted_at IS NULL"
    " AND EXISTS (SELECT 1 FROM jsonb_each_text(v.document -> 'values') e"
    "             WHERE e.value = :c)"
    " ORDER BY a.id"
)
_CONNECTION_IDS = sa.text("SELECT id FROM platform.connections WHERE id = ANY(:ids)").bindparams(
    sa.bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True)))
)

# The displayed stage of the artifact row a statement reads, from the view in
# that same statement (agent-lifecycle R1.5): never recomputed here.
_DISPLAY_STAGE = (
    sa.select(artifact_display_stage.c.display_stage)
    .where(
        artifact_display_stage.c.tenant_id == artifacts.c.tenant_id,
        artifact_display_stage.c.artifact_id == artifacts.c.id,
    )
    .scalar_subquery()
    .label("display_stage")
)


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
        display_stage=row.display_stage,
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
        contributor_ids=tuple(row.contributor_ids),
        gate_run_id=row.gate_run_id,
        publish_approval_id=row.publish_approval_id,
        tighten_only=row.tighten_only,
        compared_live_hash=row.compared_live_hash,
        submitted_by=row.submitted_by,
        submitted_at=row.submitted_at,
        published_by=row.published_by,
        published_at=row.published_at,
        retired_by=row.retired_by,
        retired_at=row.retired_at,
        retire_reason_code=row.retire_reason_code,
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
    """One transaction of `SqlArtifactStore`; see `ArtifactTx`. A person's
    carries their verified context; a lane's (`for_lane`, workflow-engine/02)
    carries only the tenant its registry issued it for, and asks no reach.

    ``lane`` names the lane carrying out a person's recorded decision in this
    transaction (`outbox` for a publish request's `.decided` handler), which
    then also carries that person's context, so what a kind's publish hook
    audits stands in their name with `details.lane` (ADR-0011; custom-objects
    ticket 06). None for a person's own request."""

    session: AsyncSession
    tenant_id: uuid.UUID
    ids: IdGenerator
    context: AccessContext | None
    lane: str | None = None

    async def reach(self, permission_key: str) -> frozenset[uuid.UUID]:
        if self.context is None:
            raise PermissionDeniedError("a lane holds no person's keys")
        rows = await self.session.execute(
            _REACH,
            {"t": self.context.tenant_id, "u": self.context.principal_id, "k": permission_key},
        )
        return frozenset(row.w for row in rows)

    async def artifact(self, artifact_id: uuid.UUID, *, lock: bool = False) -> ArtifactRow | None:
        statement = sa.select(artifacts, _DISPLAY_STAGE).where(
            artifacts.c.id == artifact_id, artifacts.c.deleted_at.is_(None)
        )
        if lock:
            statement = statement.with_for_update(of=artifacts)
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
                        tenant_id=self.tenant_id,
                        kind=kind,
                        api_name=api_name,
                        owning_workspace_id=owning_workspace_id,
                        labels=list(labels),
                        row_version=1,
                    )
                    # No version exists yet: the caller reads the row back.
                    .returning(artifacts, sa.null().label("display_stage"))
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
        contributor_ids: Sequence[uuid.UUID],
    ) -> VersionRow:
        try:
            row = (
                await self.session.execute(
                    sa.insert(artifact_versions)
                    .values(
                        id=version_id,
                        tenant_id=self.tenant_id,
                        artifact_id=artifact_id,
                        stage=Stage.DRAFT.value,
                        version_no=None,
                        document_schema=document_schema,
                        document=document,
                        row_version=1,
                        based_on_version_id=based_on_version_id,
                        contributor_ids=list(contributor_ids),
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
                    .returning(artifacts, _DISPLAY_STAGE)
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
        try:
            row = (
                await self.session.execute(
                    sa.update(artifact_versions)
                    .where(artifact_versions.c.id == version_id)
                    .values(**values)
                    .returning(artifact_versions)
                )
            ).one()
        except IntegrityError as exc:
            refused = _refused(exc)
            if refused == _STAGE_REFUSED:
                raise _conflict("the stage machine refused this move", "stage_refused") from exc
            if refused == _LIVE:
                raise _conflict("this artifact already has a live version", "live_exists") from exc
            raise
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

    async def connection_ids(self, candidates: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
        # Under the tenant's RLS: another company's connection is no id here.
        found = await self.session.scalars(_CONNECTION_IDS, {"ids": list(candidates)})
        return frozenset(found)

    async def version_documents(self, version_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Any]:
        rows = await self.session.execute(
            sa.select(artifact_versions.c.id, artifact_versions.c.document).where(
                artifact_versions.c.id.in_(list(version_ids))
            )
        )
        return {row.id: row.document for row in rows}

    async def put_manifest(self, definition_hash: str, body: dict[str, Any]) -> None:
        await self.session.execute(
            pg_insert(definition_manifests)
            .values(tenant_id=self.tenant_id, hash=definition_hash, body=body)
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
                    "tenant_id": self.tenant_id,
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
        statement = sa.select(artifacts, _DISPLAY_STAGE).where(
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

    # ---- the run manifest (tenant-config ticket 04) ----------------------

    async def root_version(self, version_id: uuid.UUID) -> RootVersion | None:
        artifact_id = await self.session.scalar(
            sa.select(artifact_versions.c.artifact_id).where(artifact_versions.c.id == version_id)
        )
        if artifact_id is None:
            return None
        # The artifact FOR SHARE first, the version in a statement after it:
        # one statement would read the version from a snapshot taken before
        # a `save_draft` it waited for had committed.
        owner = (
            await self.session.execute(
                sa.select(artifacts.c.kind, artifacts.c.owning_workspace_id)
                .where(artifacts.c.id == artifact_id, artifacts.c.deleted_at.is_(None))
                .with_for_update(read=True)
            )
        ).one_or_none()
        if owner is None:
            return None
        row = (
            await self.session.execute(
                sa.select(artifact_versions).where(artifact_versions.c.id == version_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return RootVersion(owner.kind, _version(row), owner.owning_workspace_id)

    async def definition_manifest(self, definition_hash: str) -> dict[str, Any] | None:
        body = await self.session.scalar(
            sa.select(definition_manifests.c.body).where(
                definition_manifests.c.hash == definition_hash
            )
        )
        return None if body is None else dict(body)

    async def pinned_versions(self, version_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.session.execute(
            sa.select(dependencies.c.to_version_id)
            .distinct()
            .where(
                dependencies.c.from_version_id == version_id,
                dependencies.c.to_kind == TargetKind.ARTIFACT.value,
                dependencies.c.to_version_id.is_not(None),
            )
        )
        return [row.to_version_id for row in rows]

    async def put_run_manifest(self, manifest_hash: str, body: dict[str, Any]) -> None:
        try:
            await self.session.execute(
                pg_insert(run_manifests)
                .values(tenant_id=self.tenant_id, hash=manifest_hash, body=body)
                .on_conflict_do_nothing(index_elements=["tenant_id", "hash"])
            )
        except IntegrityError as exc:
            if _refused(exc) == _RUN_MANIFEST_SIZE:
                raise PayloadTooLargeError(
                    "the run manifest is larger than 1 MiB",
                    details={"reason_code": "run_manifest_too_large"},
                ) from exc
            raise

    async def put_run_manifest_keys(
        self,
        manifest_hash: str,
        version_ids: Sequence[uuid.UUID],
        config_version_id: uuid.UUID | None = None,
    ) -> None:
        rows: list[dict[str, Any]] = [
            {
                "id": self.ids.new_uuid(),
                "tenant_id": self.tenant_id,
                "manifest_hash": manifest_hash,
                "artifact_version_id": version_id,
                "config_version_id": None,
            }
            for version_id in version_ids
        ]
        if config_version_id is not None:
            rows.append(
                {
                    "id": self.ids.new_uuid(),
                    "tenant_id": self.tenant_id,
                    "manifest_hash": manifest_hash,
                    "artifact_version_id": None,
                    "config_version_id": config_version_id,
                }
            )
        if not rows:
            return
        await self.session.execute(
            pg_insert(run_manifest_keys).values(rows).on_conflict_do_nothing()
        )

    # ---- bindings (tenant-config ticket 05) --------------------------------

    async def connections(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ConnectionFacts]:
        rows = await self.session.execute(_CONNECTION_FACTS, {"ids": list(ids)})
        return {
            row.id: ConnectionFacts(
                id=row.id,
                connector_key=row.connector_key,
                connector_major=row.connector_major,
                scopes=tuple(row.scopes or ()),
                owning_workspace_id=row.owning_workspace_id,
                name=row.name,
            )
            for row in rows
        }

    async def principal_status(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, bool]:
        rows = await self.session.execute(_PRINCIPAL_STATUS, {"ids": list(ids)})
        return {row.user_id: row.active for row in rows}

    async def binding_set(self, artifact_id: uuid.UUID, status: str) -> BindingSetRow | None:
        row = (
            await self.session.execute(
                sa.select(
                    config_versions.c.id,
                    config_versions.c.status,
                    config_versions.c.version_no,
                    config_versions.c.document,
                    config_versions.c.workspace_id,
                    config_versions.c.proposed_by,
                    config_versions.c.decided_at,
                ).where(
                    config_versions.c.kind == BINDING_SET,
                    config_versions.c.key == str(artifact_id),
                    config_versions.c.status == status,
                )
            )
        ).first()
        if row is None:
            return None
        return BindingSetRow(
            id=row.id,
            status=row.status,
            version_no=row.version_no,
            document=row.document,
            workspace_id=row.workspace_id,
            proposed_by=row.proposed_by,
            decided_at=row.decided_at,
        )

    async def binding_sets_using(self, connection_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.session.execute(_USING, {"c": str(connection_id)})
        return [row.id for row in rows]

    # ---- the run row (workflow-engine ticket 02) --------------------------

    async def run_by_request_key(self, request_key: str) -> ExistingRun | None:
        return await run_intake.run_by_request_key(self.session, request_key)

    async def insert_queued_run(self, run: QueuedRun) -> bool:
        return await run_intake.insert_queued_run(self.session, self.tenant_id, run)

    async def tenant_plan(self) -> str | None:
        return await run_intake.tenant_plan(self.session)

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)


@dataclass(frozen=True)
class SqlArtifactStore:
    session_factory: async_sessionmaker[AsyncSession]
    ids: IdGenerator

    def transaction(self, context: AccessContext) -> AbstractAsyncContextManager[SqlArtifactTx]:
        return self._open(TenantScope.from_access_context(context), context)

    # `RunIntakeStore` (workflow-engine ticket 02): a person's transaction is
    # the envelope's; a lane's is bound to the tenant its registry issued it for.
    def for_person(self, context: AccessContext) -> AbstractAsyncContextManager[SqlArtifactTx]:
        return self._open(TenantScope.from_access_context(context), context)

    def for_lane(self, lane: LaneRequester) -> AbstractAsyncContextManager[SqlArtifactTx]:
        return self._open(TenantScope(tenant_id=lane.tenant_id), None)

    # `BindingStore` (tenant-config ticket 05): a question asked for a run or a
    # recorded decision, under the tenant alone.
    def for_tenant(self, tenant_id: uuid.UUID) -> AbstractAsyncContextManager[SqlArtifactTx]:
        return self._open(TenantScope(tenant_id=tenant_id), None)

    @asynccontextmanager
    async def _open(
        self, scope: TenantScope, context: AccessContext | None
    ) -> AsyncIterator[SqlArtifactTx]:
        try:
            async with tenant_session(self.session_factory, scope) as session:
                yield SqlArtifactTx(session, scope.tenant_id, self.ids, context)
        except DBAPIError as exc:
            # Two seals of artifacts that use each other can each hold the row
            # the other shares (gate MEDIUM (i)): a retry succeeds, so a 409.
            cause = getattr(exc.orig, "__cause__", None)
            if getattr(cause, "sqlstate", None) == _DEADLOCK:
                raise _conflict("a concurrent write won; try again", "concurrent_write") from exc
            raise
