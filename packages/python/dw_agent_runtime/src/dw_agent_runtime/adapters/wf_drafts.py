"""SQL store of a Digital Worker's workflow draft, its last simulation, its
publication and the tenant's published versions (wf-ai R6.1-R6.16;
migrations 100d1de08d37, 1fb796131647).

Every statement runs under the caller's tenant and workspace RLS. A write is
one transaction: the effect key first (app-standards R2.38), then the rows,
then the audit row. The draft is read `FOR UPDATE`, so a save, a simulation,
a submission and a withdrawal of one DW take turns; a settlement takes the
DW's row `FOR UPDATE` first, so it and any change of the DW's pin take turns
too, and the next `+t<n>` is counted under that lock.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.wflite.drafts import Draft, Simulation, draft_not_found
from dw_agent_runtime.wflite.publish import (
    DW_WORKFLOW_PUBLISH,
    PublishFacts,
    PublishSettlement,
)
from dw_agent_runtime.wflite.versions import TenantVersion
from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlApprovalRepository, SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import is_tenant_pin

_D = tables.dw_workflow_drafts
_S = tables.dw_workflow_simulations
_V = tables.dw_workflow_versions
_DW = tables.digital_workers


def _bound(scope: WorkScope) -> TenantScope:
    return TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)


def _draft(row: sa.Row[Any]) -> Draft:
    return Draft(
        dw_id=row.dw_id,
        content=dict(row.content),
        content_sha256=row.content_sha256,
        base_sha256=row.base_sha256,
        saved_by=row.saved_by,
        author_ids=tuple(row.author_ids),
        state=cast(Literal["draft", "submitted"], row.state),
        reason=row.reason,
        updated_at=row.updated_at,
        approval_id=row.approval_id,
    )


def _simulation(row: sa.Row[Any]) -> Simulation:
    return Simulation(
        content_sha256=row.content_sha256,
        outcome=cast(Literal["passed", "failed"], row.outcome),
        trail=tuple(row.trail),
        tool_calls=tuple(row.tool_calls),
        failed_step=row.failed_step,
        error=row.error,
        created_at=row.created_at,
    )


def _version(row: sa.Row[Any]) -> TenantVersion:
    return TenantVersion(
        dw_id=row.dw_id,
        key=row.key,
        version=row.version,
        content=dict(row.content),
        content_sha256=row.content_sha256,
        base_sha256=row.base_sha256,
        author_ids=tuple(row.author_ids),
        approved_by=row.approved_by,
        approval_id=row.approval_id,
        created_at=row.created_at,
    )


def _submitted() -> ConflictError:
    return ConflictError(
        "the draft waits for its decision; withdraw it to change it",
        details={"reason_code": "draft_submitted"},
    )


@dataclass(frozen=True)
class SqlWorkflowDrafts:
    """Implements ``DraftStorePort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get(self, scope: WorkScope, dw_id: uuid.UUID) -> Draft | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            row = (await session.execute(sa.select(_D).where(_D.c.dw_id == dw_id))).first()
        return None if row is None else _draft(row)

    async def save(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        *,
        content: Mapping[str, Any],
        content_sha256: str,
        base_sha256: str,
        saved_by: uuid.UUID,
        audit: AuditEvent,
        effect: PendingEffect | None,
    ) -> Draft:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(dw_id))
            current = (
                await session.execute(sa.select(_D).where(_D.c.dw_id == dw_id).with_for_update())
            ).first()
            if current is not None and current.state == "submitted":
                raise _submitted()
            authors = list(current.author_ids) if current is not None else []
            if saved_by not in authors:
                authors.append(saved_by)
            values = {
                "content": dict(content),
                "content_sha256": content_sha256,
                "base_sha256": base_sha256,
                "saved_by": saved_by,
                "author_ids": authors,
                "state": "draft",
                "reason": None,
                "approval_id": None,
            }
            row = (
                await session.execute(
                    pg_insert(_D)
                    .values(
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        dw_id=dw_id,
                        **values,
                    )
                    .on_conflict_do_update(constraint="pk_dw_workflow_drafts", set_=values)
                    .returning(*_D.c)
                )
            ).one()
            await SqlAuditRepository(session).append(audit)
        return _draft(row)

    async def simulation(self, scope: WorkScope, dw_id: uuid.UUID) -> Simulation | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            row = (await session.execute(sa.select(_S).where(_S.c.dw_id == dw_id))).first()
        return None if row is None else _simulation(row)

    async def record_simulation(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        result: Simulation,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None,
    ) -> Simulation:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(dw_id))
            draft = (
                await session.execute(
                    sa.select(_D.c.state, _D.c.content_sha256)
                    .where(_D.c.dw_id == dw_id)
                    .with_for_update()
                )
            ).first()
            if draft is not None and draft.state == "submitted":
                raise _submitted()
            if draft is None or draft.content_sha256 != result.content_sha256:
                raise ConflictError(
                    "the draft changed while it was simulated; simulate it again",
                    details={"reason_code": "draft_changed"},
                )
            values = {
                "content_sha256": result.content_sha256,
                "outcome": result.outcome,
                "trail": [dict(e) for e in result.trail],
                "tool_calls": [dict(c) for c in result.tool_calls],
                "failed_step": result.failed_step,
                "error": result.error,
                "created_at": result.created_at,
            }
            row = (
                await session.execute(
                    pg_insert(_S)
                    .values(
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        dw_id=dw_id,
                        **values,
                    )
                    .on_conflict_do_update(constraint="pk_dw_workflow_simulations", set_=values)
                    .returning(*_S.c)
                )
            ).one()
            await SqlAuditRepository(session).append(audit)
        return _simulation(row)

    async def _locked_draft(self, session: AsyncSession, dw_id: uuid.UUID) -> Draft | None:
        row = (
            await session.execute(sa.select(_D).where(_D.c.dw_id == dw_id).with_for_update())
        ).first()
        return None if row is None else _draft(row)

    async def submit(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        open_approval: Callable[[Draft, Simulation | None], tuple[ApprovalRequest, AuditEvent]],
        *,
        effect: PendingEffect | None,
    ) -> Draft:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(dw_id))
            draft = await self._locked_draft(session, dw_id)
            if draft is None:
                raise draft_not_found()
            found = (await session.execute(sa.select(_S).where(_S.c.dw_id == dw_id))).first()
            request, audit = open_approval(draft, None if found is None else _simulation(found))
            await SqlApprovalRepository(session).add(request)
            row = (
                await session.execute(
                    sa.update(_D)
                    .where(_D.c.dw_id == dw_id, _D.c.state == "draft")
                    .values(state="submitted", reason=None, approval_id=request.id)
                    .returning(*_D.c)
                )
            ).one()
            await SqlAuditRepository(session).append(audit)
        return _draft(row)

    async def withdraw(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        close: Callable[[Draft], AuditEvent],
        *,
        effect: PendingEffect | None,
    ) -> Draft:
        r = tables.approval_requests
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(dw_id))
            draft = await self._locked_draft(session, dw_id)
            if draft is None:
                raise draft_not_found()
            audit = close(draft)
            cancelled = (
                await session.execute(
                    sa.update(r)
                    .where(
                        r.c.id == draft.approval_id,
                        r.c.workspace_id == scope.workspace_id,
                        r.c.approval_type == DW_WORKFLOW_PUBLISH,
                        r.c.status == "pending",
                    )
                    .values(status="cancelled", version=r.c.version + 1)
                    .returning(r.c.id)
                )
            ).first()
            if cancelled is None:
                raise ConflictError(
                    "the publication was decided first; its settlement returns the draft",
                    details={"reason_code": "approval_decided"},
                )
            row = (
                await session.execute(
                    sa.update(_D)
                    .where(_D.c.dw_id == dw_id)
                    .values(state="draft", reason=None, approval_id=None)
                    .returning(*_D.c)
                )
            ).one()
            await SqlAuditRepository(session).append(audit)
        return _draft(row)

    async def settle_publish(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[PublishFacts], PublishSettlement],
    ) -> PublishSettlement:
        r, d = tables.approval_requests, tables.approval_decisions
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            decided = (
                await session.execute(
                    sa.select(r.c.payload, d.c.outcome, d.c.decided_by)
                    .select_from(r.join(d, d.c.request_id == r.c.id))
                    .where(
                        r.c.id == approval_id,
                        r.c.workspace_id == scope.workspace_id,
                        r.c.approval_type == DW_WORKFLOW_PUBLISH,
                    )
                )
            ).first()
            if decided is None:
                raise NotFoundError(
                    "no decided publication of that id", details={"approval_id": str(approval_id)}
                )
            payload = dict(decided.payload)
            try:
                dw_id = uuid.UUID(str(payload["dw_id"]))
                content_sha256, base_sha256 = (
                    str(payload[name]) for name in ("content_sha256", "base_sha256")
                )
            except (KeyError, ValueError) as exc:
                raise NotFoundError(
                    "the publication names no draft", details={"approval_id": str(approval_id)}
                ) from exc
            # The DW first: its pin and the next number are read under it.
            worker = (
                await session.execute(
                    sa.select(_DW.c.workflow_key, _DW.c.workflow_version)
                    .where(_DW.c.id == dw_id)
                    .with_for_update()
                )
            ).first()
            if worker is None:
                raise NotFoundError(
                    "the publication's digital worker is gone",
                    details={"approval_id": str(approval_id)},
                )
            draft = await self._locked_draft(session, dw_id)
            published = (
                await session.execute(sa.select(_V.c.id).where(_V.c.approval_id == approval_id))
            ).first()
            pinned_sha = None
            if is_tenant_pin(worker.workflow_version):
                pinned_sha = (
                    await session.execute(
                        sa.select(_V.c.content_sha256).where(
                            _V.c.dw_id == dw_id, _V.c.version == worker.workflow_version
                        )
                    )
                ).scalar_one_or_none()
            last = (
                await session.execute(
                    sa.select(sa.func.coalesce(sa.func.max(_V.c.seq), 0)).where(_V.c.dw_id == dw_id)
                )
            ).scalar_one()
            settlement = settle(
                PublishFacts(
                    approval_id=approval_id,
                    dw_id=dw_id,
                    approved=decided.outcome == "approved",
                    decided_by=decided.decided_by,
                    content_sha256=content_sha256,
                    base_sha256=base_sha256,
                    workflow_key=worker.workflow_key,
                    workflow_version=worker.workflow_version,
                    pinned_version_sha256=pinned_sha,
                    draft=draft,
                    already_published=published is not None,
                    next_seq=int(last) + 1,
                )
            )
            if settlement.publish is not None and draft is not None:
                new = settlement.publish
                await session.execute(
                    sa.insert(_V).values(
                        id=new.id,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        dw_id=dw_id,
                        key=worker.workflow_key,
                        seq=new.seq,
                        version=new.version,
                        content=dict(draft.content),
                        content_sha256=content_sha256,
                        base_sha256=base_sha256,
                        author_ids=list(draft.author_ids),
                        approved_by=decided.decided_by,
                        approval_id=approval_id,
                        created_at=sa.func.now(),
                    )
                )
                await session.execute(
                    sa.update(_DW).where(_DW.c.id == dw_id).values(workflow_version=new.version)
                )
                await session.execute(sa.delete(_D).where(_D.c.dw_id == dw_id))
            elif settlement.return_draft:
                await session.execute(
                    sa.update(_D)
                    .where(_D.c.dw_id == dw_id)
                    .values(state="draft", reason=settlement.reason, approval_id=None)
                )
            if settlement.audit is not None:
                await SqlAuditRepository(session).append(settlement.audit)
        return settlement


@dataclass(frozen=True)
class SqlTenantWorkflowVersions:
    """Implements ``TenantVersionsPort``: reads only, under the scope given."""

    session_factory: async_sessionmaker[AsyncSession]

    async def of_dw(self, scope: WorkScope, dw_id: uuid.UUID, version: str) -> TenantVersion | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            row = (
                await session.execute(
                    sa.select(_V).where(_V.c.dw_id == dw_id, _V.c.version == version)
                )
            ).first()
        return None if row is None else _version(row)

    async def by_content(
        self, scope: WorkScope, *, key: str, version: str, content_sha256: str
    ) -> TenantVersion | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            row = (
                await session.execute(
                    sa.select(_V)
                    .where(
                        _V.c.key == key,
                        _V.c.version == version,
                        _V.c.content_sha256 == content_sha256,
                    )
                    .limit(1)
                )
            ).first()
        return None if row is None else _version(row)


__all__ = ["SqlTenantWorkflowVersions", "SqlWorkflowDrafts"]
