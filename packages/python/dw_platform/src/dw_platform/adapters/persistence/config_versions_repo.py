"""SQL for a tenant's configuration versions (tenant-config ticket 05;
`platform.config_versions`).

One transaction under one company's RLS (`tenant_session`), the principal kept
for `platform.workspace_reach` and `platform.checker_candidates`. It decides
nothing: the partial unique indexes, `ck_config_versions_checker_not_maker`
and `platform.config_version_transition()` hold what a row may become, and
this module reads the one refusal a caller can provoke by racing another (two
proposals of one key) back by its constraint's name.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import (
    SqlApprovalRepository,
    SqlAuditRepository,
    _approval_from_row,
)
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.config_versions import (
    ConfigVersionRow,
    NewConfigVersion,
    RecordedDecision,
    Status,
)
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.approval import ApprovalRequest, DecisionOutcome
from dw_platform.domain.audit import AuditEvent

__all__ = ["SqlConfigVersionStore", "SqlConfigVersionTx", "config_versions"]

config_versions = sa.table(
    "config_versions",
    sa.column("id", sa.Uuid),
    sa.column("tenant_id", sa.Uuid),
    sa.column("workspace_id", sa.Uuid),
    sa.column("kind"),
    sa.column("key"),
    sa.column("action"),
    sa.column("version_no", sa.Integer),
    sa.column("base_version", sa.Integer),
    sa.column("base_bindings_hash"),
    sa.column("base_approved_id", sa.Uuid),
    sa.column("document", JSONB),
    sa.column("document_hash"),
    sa.column("status"),
    sa.column("approval_id", sa.Uuid),
    sa.column("proposed_by", sa.Uuid),
    sa.column("proposed_at", sa.DateTime(timezone=True)),
    sa.column("decided_by", sa.Uuid),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("decision_comment"),
    sa.column("superseded_at", sa.DateTime(timezone=True)),
    schema="platform",
)
_COLUMNS = (
    config_versions.c.id,
    config_versions.c.tenant_id,
    config_versions.c.workspace_id,
    config_versions.c.kind,
    config_versions.c.key,
    config_versions.c.version_no,
    config_versions.c.base_version,
    config_versions.c.base_bindings_hash,
    config_versions.c.base_approved_id,
    config_versions.c.document,
    config_versions.c.document_hash,
    config_versions.c.status,
    config_versions.c.approval_id,
    config_versions.c.proposed_by,
    config_versions.c.proposed_at,
    config_versions.c.decided_by,
    config_versions.c.decided_at,
)

# Two proposals of one key at once: the loser meets one of these two.
_OPEN = frozenset(
    {
        "uq_config_versions_tenant_id_kind_key_proposed",
        "uq_config_versions_tenant_id_kind_key_version_no",
    }
)

_REACH = sa.text("SELECT platform.workspace_reach(:t, :u, :k) AS w")
# A checker who can also read what they decide (gate 4/11/2026 (r)).
_CHECKER = sa.text(
    "SELECT 1 FROM platform.checker_candidates(:t, :approve, :p, :w) AS c(user_id)"
    " WHERE CAST(:w AS uuid) IN (SELECT platform.workspace_reach(:t, c.user_id, :read)) LIMIT 1"
)


def row_of(row: Any) -> ConfigVersionRow:
    return ConfigVersionRow(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        key=row.key,
        version_no=row.version_no,
        base_version=row.base_version,
        base_bindings_hash=row.base_bindings_hash,
        base_approved_id=row.base_approved_id,
        document=row.document,
        document_hash=row.document_hash,
        status=row.status,
        approval_id=row.approval_id,
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )


@dataclass
class SqlConfigVersionTx:
    """Implements `ConfigVersionTx` on one open transaction."""

    session: AsyncSession
    tenant_id: uuid.UUID
    principal_id: uuid.UUID | None

    async def reach(self, key: str) -> frozenset[uuid.UUID]:
        if self.principal_id is None:
            return frozenset()
        rows = await self.session.execute(
            _REACH, {"t": self.tenant_id, "u": self.principal_id, "k": key}
        )
        return frozenset(rows.scalars())

    async def has_checker(
        self, approve_key: str, read_key: str, proposer: uuid.UUID, workspace_id: uuid.UUID
    ) -> bool:
        found = (
            await self.session.execute(
                _CHECKER,
                {
                    "t": self.tenant_id,
                    "approve": approve_key,
                    "read": read_key,
                    "p": proposer,
                    "w": workspace_id,
                },
            )
        ).first()
        return found is not None

    async def current(
        self, kind: str, key: str, status: Status, *, lock: bool = False
    ) -> ConfigVersionRow | None:
        query = sa.select(*_COLUMNS).where(
            config_versions.c.kind == kind,
            config_versions.c.key == key,
            config_versions.c.status == status,
        )
        found = (await self.session.execute(query.with_for_update() if lock else query)).first()
        return None if found is None else row_of(found)

    async def next_version_no(self, kind: str, key: str) -> int:
        top = await self.session.scalar(
            sa.select(sa.func.max(config_versions.c.version_no)).where(
                config_versions.c.kind == kind, config_versions.c.key == key
            )
        )
        return int(top or 0) + 1

    async def insert(self, row: NewConfigVersion) -> None:
        try:
            async with self.session.begin_nested():
                await self.session.execute(
                    sa.insert(config_versions).values(
                        id=row.id,
                        tenant_id=self.tenant_id,
                        workspace_id=row.workspace_id,
                        kind=row.kind,
                        key=row.key,
                        action="set",
                        version_no=row.version_no,
                        base_version=row.base_version,
                        base_bindings_hash=row.base_bindings_hash,
                        base_approved_id=row.base_approved_id,
                        document=row.document,
                        document_hash=row.document_hash,
                        status="proposed",
                        approval_id=row.approval_id,
                        proposed_by=row.proposed_by,
                    )
                )
        except IntegrityError as exc:
            found = refusal(exc)
            if found is not None and found[0] in _OPEN:
                raise ConflictError(
                    "this configuration already has an open proposal",
                    details={"reason_code": "proposal_open"},
                ) from exc
            raise

    async def _one(self, where: Any, *, lock: bool) -> ConfigVersionRow | None:
        query = sa.select(*_COLUMNS).where(where)
        found = (await self.session.execute(query.with_for_update() if lock else query)).first()
        return None if found is None else row_of(found)

    async def by_id(self, config_version_id: uuid.UUID, *, lock: bool) -> ConfigVersionRow | None:
        return await self._one(config_versions.c.id == config_version_id, lock=lock)

    async def by_approval(self, approval_id: uuid.UUID, *, lock: bool) -> ConfigVersionRow | None:
        return await self._one(config_versions.c.approval_id == approval_id, lock=lock)

    async def open_approval(self, request: ApprovalRequest) -> None:
        await SqlApprovalRepository(self.session).add(request)

    async def approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        found = (
            await self.session.execute(
                sa.select(tables.approval_requests)
                .where(tables.approval_requests.c.id == approval_id)
                .with_for_update()
            )
        ).first()
        return None if found is None else _approval_from_row(found)

    async def save_approval(self, request: ApprovalRequest) -> None:
        await SqlApprovalRepository(self.session).save(request)

    async def decision(self, approval_id: uuid.UUID) -> RecordedDecision | None:
        d = tables.approval_decisions
        found = (
            await self.session.execute(
                sa.select(d.c.outcome, d.c.decided_by, d.c.decided_at, d.c.comment).where(
                    d.c.request_id == approval_id
                )
            )
        ).first()
        if found is None:
            return None
        return RecordedDecision(
            outcome=DecisionOutcome(found.outcome),
            decided_by=found.decided_by,
            decided_at=found.decided_at,
            comment=found.comment or "",
        )

    async def set_status(
        self,
        config_version_id: uuid.UUID,
        status: Status,
        *,
        decided_by: uuid.UUID | None = None,
        decision_comment: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if status == "superseded":
            values["superseded_at"] = sa.func.now()
        else:
            values["decided_at"] = sa.func.now()
            if decided_by is not None:
                values["decided_by"] = decided_by
                values["decision_comment"] = decision_comment or ""
        await self.session.execute(
            sa.update(config_versions)
            .where(config_versions.c.id == config_version_id)
            .values(**values)
        )

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)


@dataclass(frozen=True)
class SqlConfigVersionStore:
    """Implements `ConfigVersionStore`."""

    session_factory: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def transaction(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None,
        principal_id: uuid.UUID | None,
    ) -> AsyncIterator[SqlConfigVersionTx]:
        scope = TenantScope(
            tenant_id=tenant_id, workspace_id=workspace_id, principal_id=principal_id
        )
        async with tenant_session(self.session_factory, scope) as session:
            yield SqlConfigVersionTx(session, tenant_id, principal_id)
