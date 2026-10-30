"""Append-only persistence of tool executions with idempotency lookup.

`dw_app` holds no UPDATE on the table (migration 3f1cb1d4cece): a call's outcome
is a further row, never a rewrite of the one before it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import tool_executions
from dw_agent_runtime.contracts import RunContext

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

# The backstop behind the claim (ADR-0108 decision 5): a second `succeeded` row
# for one key is refused here, and the refusal is answered by the first row.
_SUCCEEDED_ONCE = "uq_tool_executions_idempotency"


@dataclass(frozen=True)
class StoredExecution:
    id: uuid.UUID
    status: str
    input_hash: str
    output_hash: str | None
    output: dict[str, Any] | None


@dataclass(frozen=True)
class SqlToolExecutionStore:
    session_factory: async_sessionmaker[AsyncSession]

    async def find_succeeded(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> StoredExecution | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            row = (
                await session.execute(
                    sa.select(tool_executions).where(
                        tool_executions.c.tool_name == tool_name,
                        tool_executions.c.idempotency_key == idempotency_key,
                        tool_executions.c.status == "succeeded",
                    )
                )
            ).first()
        if row is None:
            return None
        return StoredExecution(
            id=row.id,
            status=row.status,
            input_hash=row.input_hash,
            output_hash=row.output_hash,
            output=dict(row.output) if row.output is not None else None,
        )

    async def list_outputs_for_run(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, tool_name: str
    ) -> tuple[dict[str, Any], ...]:
        """Everything one tool returned during one run, oldest first.

        The audit trail read back as data. A surface wanting to show what an
        agent did with a tool has this or nothing: the run's messages are the
        model's account of itself, while these rows are the executor's.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            rows = (
                await session.execute(
                    sa.select(tool_executions.c.output)
                    .where(
                        tool_executions.c.run_id == run_id,
                        tool_executions.c.tool_name == tool_name,
                        tool_executions.c.status == "succeeded",
                    )
                    .order_by(tool_executions.c.started_at)
                )
            ).all()
        return tuple(dict(row.output) for row in rows if row.output is not None)

    async def record(
        self,
        run_context: RunContext,
        *,
        execution_id: uuid.UUID,
        tool_name: str,
        tool_version: str,
        status: str,
        input_hash: str,
        output_hash: str | None,
        output: dict[str, Any] | None,
        idempotency_key: str | None,
        error: str | None,
        attempts: int,
        started_at: datetime,
        finished_at: datetime,
        dispatch_id: uuid.UUID | None = None,
    ) -> StoredExecution | None:
        """None once the row is written; the earlier success if the key already had one."""
        try:
            await self._insert(
                run_context,
                id=execution_id,
                tool_name=tool_name,
                tool_version=tool_version,
                status=status,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                output_hash=output_hash,
                output=output,
                error=error,
                attempts=attempts,
                started_at=started_at,
                finished_at=finished_at,
                dispatch_id=dispatch_id,
            )
        except IntegrityError as exc:
            if idempotency_key is None or _SUCCEEDED_ONCE not in str(exc.orig):
                raise
            return await self.find_succeeded(run_context, tool_name, idempotency_key)
        return None

    async def _insert(self, run_context: RunContext, **values: Any) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(run_context.tenant_id)})
            await session.execute(
                sa.insert(tool_executions).values(
                    tenant_id=run_context.tenant_id,
                    workspace_id=run_context.workspace_id,
                    run_id=run_context.run_id,
                    **values,
                )
            )
