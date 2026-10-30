"""Claims on a tool key and the `dispatched` rows they fence (ADR-0108 decision 5).

Implements `dw_agent_runtime.dispatch.ToolClaimPort`. Every statement runs in a
short transaction of its own under the run's tenant, and every comparison with
the clock is PostgreSQL's `now()`, so two processes with drifting clocks still
agree about which claim has expired.

The `dispatched` row is inserted by `INSERT ... SELECT ... WHERE EXISTS` on the
caller's own live claim and committed before the handler runs. A holder that
stalled past `expires_at` and was taken over inserts nothing, so it cannot send
beside the holder that replaced it (R6.13).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import tool_execution_claims
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.dispatch import DispatchRecord

__all__ = ["SqlToolClaimRetention", "SqlToolClaims"]

logger = logging.getLogger("dw_agent_runtime.tool_claims")

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")

_INSERT_CLAIM = text(
    """
    INSERT INTO platform.tool_execution_claims
        (tenant_id, workspace_id, tool_name, idempotency_key, run_id, expires_at)
    VALUES (:tenant_id, :workspace_id, :tool_name, :idempotency_key, :run_id,
            now() + make_interval(secs => :lease_seconds))
    ON CONFLICT (tenant_id, tool_name, idempotency_key) DO NOTHING
    RETURNING claim_token
    """
)

# Only while the token read is still the holder's and still expired: two takers
# that read the same expired claim cannot both delete it.
_TAKE_OVER = text(
    """
    DELETE FROM platform.tool_execution_claims
    WHERE tenant_id = :tenant_id AND tool_name = :tool_name
      AND idempotency_key = :idempotency_key
      AND claim_token = :old_token AND expires_at < now()
    """
)

_UNRESOLVED = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM platform.tool_executions AS d
        WHERE d.tenant_id = :tenant_id AND d.tool_name = :tool_name
          AND d.idempotency_key = :idempotency_key AND d.status = 'dispatched'
          AND NOT EXISTS (
              SELECT 1 FROM platform.tool_executions AS t
              WHERE t.tenant_id = d.tenant_id AND t.dispatch_id = d.id
                AND t.status IN ('succeeded', 'failed')
          )
    )
    """
)

_DISPATCH = text(
    """
    INSERT INTO platform.tool_executions
        (id, tenant_id, workspace_id, run_id, tool_name, tool_version, status,
         idempotency_key, input_hash, attempts, started_at)
    SELECT :id, :tenant_id, :workspace_id, :run_id, :tool_name, :tool_version,
           'dispatched', :idempotency_key, :input_hash, 1, :started_at
    WHERE EXISTS (
        SELECT 1 FROM platform.tool_execution_claims
        WHERE tenant_id = :tenant_id AND tool_name = :tool_name
          AND idempotency_key = :idempotency_key
          AND claim_token = :token AND expires_at > now()
    )
    """
)


@dataclass(frozen=True)
class SqlToolClaims:
    session_factory: async_sessionmaker[AsyncSession]

    async def claim(
        self,
        run_context: RunContext,
        tool_name: str,
        idempotency_key: str,
        *,
        lease_seconds: float,
    ) -> uuid.UUID | None:
        key = {
            "tenant_id": run_context.tenant_id,
            "tool_name": tool_name,
            "idempotency_key": idempotency_key,
        }
        values = {
            **key,
            "workspace_id": run_context.workspace_id,
            "run_id": run_context.run_id,
            "lease_seconds": lease_seconds,
        }
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            token = (await session.execute(_INSERT_CLAIM, values)).scalar_one_or_none()
            if token is not None:
                return uuid.UUID(str(token))
            held = (
                await session.execute(
                    sa.select(
                        tool_execution_claims.c.claim_token,
                        (tool_execution_claims.c.expires_at < sa.func.now()).label("expired"),
                    ).where(
                        tool_execution_claims.c.tenant_id == run_context.tenant_id,
                        tool_execution_claims.c.tool_name == tool_name,
                        tool_execution_claims.c.idempotency_key == idempotency_key,
                    )
                )
            ).first()
            if held is not None and not held.expired:
                return None
            if held is not None:
                taken = await session.execute(_TAKE_OVER, {**key, "old_token": held.claim_token})
                if getattr(taken, "rowcount", 0) != 1:
                    return None
            token = (await session.execute(_INSERT_CLAIM, values)).scalar_one_or_none()
        return uuid.UUID(str(token)) if token is not None else None

    async def release(
        self, run_context: RunContext, tool_name: str, idempotency_key: str, token: uuid.UUID
    ) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            await session.execute(
                sa.delete(tool_execution_claims).where(
                    tool_execution_claims.c.tenant_id == run_context.tenant_id,
                    tool_execution_claims.c.tool_name == tool_name,
                    tool_execution_claims.c.idempotency_key == idempotency_key,
                    tool_execution_claims.c.claim_token == token,
                )
            )

    async def has_unresolved_dispatch(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> bool:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            found = (
                await session.execute(
                    _UNRESOLVED,
                    {
                        "tenant_id": run_context.tenant_id,
                        "tool_name": tool_name,
                        "idempotency_key": idempotency_key,
                    },
                )
            ).scalar_one()
        return bool(found)

    async def dispatch(
        self,
        run_context: RunContext,
        tool_name: str,
        idempotency_key: str,
        token: uuid.UUID,
        record: DispatchRecord,
    ) -> bool:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            inserted = await session.execute(
                _DISPATCH,
                {
                    "id": record.execution_id,
                    "tenant_id": run_context.tenant_id,
                    "workspace_id": run_context.workspace_id,
                    "run_id": run_context.run_id,
                    "tool_name": tool_name,
                    "tool_version": record.tool_version,
                    "idempotency_key": idempotency_key,
                    "input_hash": record.input_hash,
                    "started_at": record.started_at,
                    "token": token,
                },
            )
        return getattr(inserted, "rowcount", 0) == 1


@dataclass(frozen=True)
class SqlToolClaimRetention:
    """Implements `dw_worker.consumers.retention.RetentionPrunePort` for claims (R6.7).

    A claim past `expires_at` guards nothing: the next call with its key takes it
    over (ADR-0108 decision 5), so the lane deletes it with no further term.
    What it guarded is not lost with it: a dispatch with no known outcome is
    answered from `platform.tool_executions`, which this lane never touches
    (R6.9). Housekeeping of operational rows, so it writes no audit and logs the
    count (ADR-0011 "Not applied").
    """

    session_factory: async_sessionmaker[AsyncSession]

    async def prune(self) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            removed = await session.execute(
                sa.delete(tool_execution_claims).where(
                    tool_execution_claims.c.expires_at < sa.func.now()
                )
            )
        logger.info(
            "retention removed expired tool claims",
            extra={"deleted": getattr(removed, "rowcount", 0)},
        )
