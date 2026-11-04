"""SQL implementation of removing a membership.

Runs through ``tenant_session`` so RLS bounds it to the caller's tenant. The
roles on the membership go with it, each revocation judged by the triggers
of the role tables; a refusal is read back by ``role_write_refusal``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.role_refusals import role_write_refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.audit import AuditEvent


@dataclass(frozen=True)
class SqlMembershipAdminRepository:
    """Implements ``MembershipAdminRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def revoke(
        self,
        context: AccessContext,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        scope = TenantScope.from_access_context(context)
        try:
            async with tenant_session(self.session_factory, scope) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(user_id))
                deleted = (
                    await session.execute(
                        sa.delete(tables.memberships)
                        .where(
                            tables.memberships.c.user_id == user_id,
                            tables.memberships.c.workspace_id == workspace_id,
                        )
                        .returning(tables.memberships.c.id)
                    )
                ).first()
                if deleted is None:
                    return False
                await SqlAuditRepository(session).append(audit)
        except IntegrityError as exc:
            known = role_write_refusal(exc)
            if known is None:
                raise
            raise known from exc
        return True
