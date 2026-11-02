"""SQL store of a Digital Worker's workflow draft and its last simulation
(wf-ai R6.1, R6.2, R6.8, R6.12, R6.13; migration 100d1de08d37).

Every statement runs under the caller's tenant and workspace RLS. A write is
one transaction: the effect key first (app-standards R2.38), then the row,
then its audit row. The draft is read `FOR UPDATE`, so a save, a simulation
and (ticket 03) a submission of one DW take turns.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.wflite.drafts import Draft, Simulation
from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent

_D = tables.dw_workflow_drafts
_S = tables.dw_workflow_simulations


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


__all__ = ["SqlWorkflowDrafts"]
