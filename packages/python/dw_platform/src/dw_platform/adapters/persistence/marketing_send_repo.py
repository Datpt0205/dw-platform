"""The Send floor's tables (compliance-pdpl ticket 08; ADR-0124).

- `SqlSendFloorStore`: one transaction of the floor under the request's tenant
  and workspace, with transaction-scoped advisory locks, the reads it asks and
  the row and audit event it writes, committed together.
- `SqlConsentStore`: an append-only consent record under the caller's tenant;
  RLS's WITH CHECK refuses a row of another.
- `SqlSuppressionStore`: an opt-out under the token's tenant, once.
- `marketing_purge_step`: the offboarding lane's step for the two append-only
  tables, which `dw_app` cannot DELETE from; `platform.purge_tenant_marketing`
  refuses any tenant but the transaction's own, and any tenant not
  `offboarding`. Suppressions go by the lane's default step, which the table's
  trigger lets through only then.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence.offboarding import OffboardingPurgeStep
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.marketing_send import PURPOSE, CurrentConsent, LogRow
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent

_LOCK = sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))")
_DISPATCHING = sa.text(
    "SELECT consent_record_id FROM platform.marketing_send_log"
    " WHERE idempotency_key = :k AND outcome = 'dispatching' LIMIT 1"
)
_SUPPRESSED = sa.text(
    "SELECT EXISTS (SELECT 1 FROM platform.contact_suppressions"
    " WHERE channel = :c AND address_hash = :h)"
)
_CONSENT = sa.text(
    "SELECT id, state FROM platform.consent_records"
    " WHERE subject_ref = :s AND channel = :c AND purpose = :p"
    # Latest first; a withdrawal and a grant at one instant read as withdrawn.
    " ORDER BY captured_at DESC, (state = 'withdrawn') DESC LIMIT 1"
)
_SENDS_SINCE = sa.text("SELECT platform.marketing_sends_since(:c, :h, :since)")
_RECIPIENTS = sa.text("SELECT platform.marketing_recipients_of_run(:r)")
_HAS_RECIPIENT = sa.text(
    "SELECT EXISTS (SELECT 1 FROM platform.marketing_send_log WHERE root_run_id = :r"
    " AND channel = :c AND address_hash = :h AND outcome = 'dispatching')"
)
_WRITE_LOG = sa.text(
    "INSERT INTO platform.marketing_send_log (id, tenant_id, workspace_id, channel,"
    " address_hash, outcome, blocked_reason, idempotency_key, run_id, root_run_id,"
    " consent_record_id, tool_name, tool_version) VALUES (:id, :t, :w, :c, :h, :o, :reason,"
    " :k, :run, :root, :consent, :tool, :version)"
)
_INSERT_CONSENT = sa.text(
    "INSERT INTO platform.consent_records (id, tenant_id, subject_ref, purpose, channel,"
    " state, captured_at, source, evidence_ref, notice_version, withdrawn_at)"
    " VALUES (:id, :tenant_id, :subject_ref, :purpose, :channel, :state, :captured_at,"
    " :source, :evidence_ref, :notice_version, :withdrawn_at)"
)
_SUPPRESS = sa.text(
    "INSERT INTO platform.contact_suppressions (tenant_id, channel, address_hash, source)"
    " VALUES (:t, :c, :h, :s) ON CONFLICT DO NOTHING RETURNING tenant_id"
)
_PURGE = sa.text("SELECT platform.purge_tenant_marketing(:t)")


def _bound(scope: WorkScope) -> TenantScope:
    return TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)


@dataclass(frozen=True)
class _SqlSendFloorTx:
    session: AsyncSession
    scope: WorkScope

    async def lock(self, key: str) -> None:
        await self.session.execute(_LOCK, {"k": key})

    async def dispatching_consent(self, idempotency_key: str) -> uuid.UUID | None:
        found = (await self.session.execute(_DISPATCHING, {"k": idempotency_key})).first()
        return None if found is None else found.consent_record_id

    async def suppressed(self, channel: str, hashed: str) -> bool:
        return bool(await self.session.scalar(_SUPPRESSED, {"c": channel, "h": hashed}))

    async def current_consent(self, subject_ref: str, channel: str) -> CurrentConsent | None:
        row = (
            await self.session.execute(_CONSENT, {"s": subject_ref, "c": channel, "p": PURPOSE})
        ).first()
        return None if row is None else CurrentConsent(id=row.id, state=row.state)

    async def sends_since(self, channel: str, hashed: str, since: datetime) -> int:
        return int(
            await self.session.scalar(_SENDS_SINCE, {"c": channel, "h": hashed, "since": since})
            or 0
        )

    async def run_recipients(self, root_run_id: uuid.UUID) -> int:
        return int(await self.session.scalar(_RECIPIENTS, {"r": root_run_id}) or 0)

    async def run_has_recipient(self, root_run_id: uuid.UUID, channel: str, hashed: str) -> bool:
        return bool(
            await self.session.scalar(_HAS_RECIPIENT, {"r": root_run_id, "c": channel, "h": hashed})
        )

    async def write_log(self, row_id: uuid.UUID, row: LogRow) -> None:
        await self.session.execute(
            _WRITE_LOG,
            {
                "id": row_id,
                "t": self.scope.tenant_id,
                "w": self.scope.workspace_id,
                "c": row.channel,
                "h": row.address_hash,
                "o": row.outcome,
                "reason": row.blocked_reason,
                "k": row.idempotency_key,
                "run": row.run_id,
                "root": row.root_run_id,
                "consent": row.consent_record_id,
                "tool": row.tool_name,
                "version": row.tool_version,
            },
        )

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)


@dataclass(frozen=True)
class SqlSendFloorStore:
    """Implements `SendFloorStorePort`."""

    session_factory: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def transaction(self, scope: WorkScope) -> AsyncIterator[_SqlSendFloorTx]:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            yield _SqlSendFloorTx(session=session, scope=scope)


@dataclass(frozen=True)
class SqlConsentStore:
    """Implements `ConsentStorePort`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def insert(self, scope: WorkScope, row: Mapping[str, Any]) -> None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            await session.execute(_INSERT_CONSENT, dict(row))


@dataclass(frozen=True)
class SqlSuppressionStore:
    """Implements `SuppressionStorePort`: tenant-wide, so the token's tenant
    is the whole scope."""

    session_factory: async_sessionmaker[AsyncSession]

    async def suppress(
        self, tenant_id: uuid.UUID, channel: str, hashed: str, *, source: str
    ) -> bool:
        scope = TenantScope(tenant_id=tenant_id)
        async with tenant_session(self.session_factory, scope) as session:
            added = await session.execute(
                _SUPPRESS, {"t": tenant_id, "c": channel, "h": hashed, "s": source}
            )
            return added.first() is not None


async def _purge(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(_PURGE, {"t": tenant_id})


def marketing_purge_step() -> OffboardingPurgeStep:
    return OffboardingPurgeStep(
        name="platform.purge_tenant_marketing",
        tables=frozenset({"platform.consent_records", "platform.marketing_send_log"}),
        run=_purge,
    )
