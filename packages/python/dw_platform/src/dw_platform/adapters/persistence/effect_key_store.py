"""SQL for `platform.effect_keys` (app-standards R2.16, R2.23-R2.25, R2.37-R2.40).

Three doors, one table: the look-up before an operation reads any state, the
insert inside the effect's own transaction, and the purge. Each meets an
existing row through the same rule (`existing_effect`), and "has it expired"
has one owner too, `platform.effect_key_cutoff()`, which the purge function
reads as well.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import (
    EffectClaim,
    EffectKey,
    EffectResult,
    existing_effect,
)

logger = logging.getLogger(__name__)

# The store key of this table's retention fragment and purger (R2.25).
EFFECT_KEYS = "platform.effect_keys"

_EFFECTS = tables.effect_keys
_LOCK_NOT_AVAILABLE = "55P03"
_PURGE_EFFECT_KEYS = sa.text("SELECT platform.purge_expired_effect_keys()")
_BOUND_TENANT: sa.ColumnClause[Any] = sa.literal_column(
    "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def _row_of(key: EffectKey) -> sa.ColumnElement[bool]:
    return sa.and_(
        _EFFECTS.c.operation == key.operation,
        _EFFECTS.c.idempotency_key == key.idempotency_key,
    )


async def _expired_row_gone(session: AsyncSession, key: EffectKey) -> None:
    """Under a fresh reservation, an expired row is a forgotten key: delete it so
    this request's effect can take its place (R2.37). The cutoff is read only
    when a row is there, so a key's first use never needs the term (R2.40).
    A take-over keeps the row: its own earlier attempt may be that effect."""
    if not key.fresh:
        return
    there = await session.scalar(sa.select(sa.literal(True)).where(_row_of(key)))
    if there:
        await session.execute(
            sa.delete(_EFFECTS).where(
                _row_of(key), _EFFECTS.c.created_at < sa.func.platform.effect_key_cutoff()
            )
        )


async def claim_effect_key(session: AsyncSession, claim: EffectClaim) -> None:
    """Write ``claim`` as the first statements of the effect's transaction (R2.38).

    A second attempt of the same key waits at the primary key, then meets the
    first one's row: :class:`ExistingEffect` for the same caller's same request,
    a conflict otherwise (R2.33). The wait is bounded at five seconds and reset
    before the effect's own statements (R2.39).
    """
    key = claim.key
    await session.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    try:
        await _expired_row_gone(session, key)
        inserted = await session.scalar(
            pg_insert(_EFFECTS)
            .values(
                # The tenant the transaction is bound to: RLS checks it again.
                tenant_id=_BOUND_TENANT,
                operation=key.operation,
                idempotency_key=key.idempotency_key,
                caller_ref=key.caller_ref,
                request_hash=key.request_hash,
                result={"status": claim.result.status, "id": claim.result.id},
            )
            .on_conflict_do_nothing(constraint="pk_effect_keys")
            .returning(sa.literal(True))
        )
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE:
            raise ConflictError(
                "a request with this idempotency key is still in progress",
                details={"hint": "retry in a few seconds"},
            ) from None
        raise
    await session.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))
    if inserted:
        return
    row = (
        await session.execute(
            sa.select(_EFFECTS.c.caller_ref, _EFFECTS.c.request_hash, _EFFECTS.c.result).where(
                _row_of(key)
            )
        )
    ).one()
    raise existing_effect(
        key,
        caller_ref=row.caller_ref,
        request_hash=row.request_hash,
        result=EffectResult(status=int(row.result["status"]), id=str(row.result["id"])),
    )


@dataclass(frozen=True)
class SqlEffectKeyLookup:
    """Implements `EffectKeyPort`: the look-up before the operation reads state."""

    session_factory: async_sessionmaker[AsyncSession]

    async def existing(self, context: AccessContext, key: EffectKey) -> EffectResult | None:
        async with tenant_session(
            self.session_factory, TenantScope.from_access_context(context)
        ) as session:
            row = (
                await session.execute(
                    sa.select(
                        _EFFECTS.c.caller_ref, _EFFECTS.c.request_hash, _EFFECTS.c.result
                    ).where(_row_of(key))
                )
            ).one_or_none()
            if row is None:
                return None
            if key.fresh and await session.scalar(
                sa.select(_EFFECTS.c.created_at < sa.func.platform.effect_key_cutoff()).where(
                    _row_of(key)
                )
            ):
                # Expired, and no earlier attempt of this reservation: the
                # effect's own transaction replaces it (R2.37).
                return None
        return existing_effect(
            key,
            caller_ref=row.caller_ref,
            request_hash=row.request_hash,
            result=EffectResult(status=int(row.result["status"]), id=str(row.result["id"])),
        ).result


@dataclass(frozen=True)
class SqlEffectKeyWriter:
    """Implements `EffectKeyWriterPort` on a unit of work's open transaction."""

    session: AsyncSession

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)


@dataclass(frozen=True)
class SqlEffectKeyRetention:
    """The purger registered for `platform.effect_keys` (R2.25). Housekeeping
    of operational rows: it logs the count and writes no audit row (R2.9;
    `CLAUDE.md` "Agent and tool rules")."""

    session_factory: async_sessionmaker[AsyncSession]

    async def purge(self) -> None:
        async with self.session_factory() as session, session.begin():
            removed = await session.scalar(_PURGE_EFFECT_KEYS)
        logger.info(
            "effect keys purged",
            extra={"deleted": removed, "retention_class": EFFECT_KEYS},
        )
