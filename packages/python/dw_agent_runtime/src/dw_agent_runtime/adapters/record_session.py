"""The transaction of a Studio object tool's call (record-access ticket 04,
step 5; ADR-0103 decisions 4 and 5, ADR-0105 decision 6).

The one module of the runtime that binds the actor kind `agent`. Each call of
a tool that reads or writes Studio records opens its own transaction here, the
first one after a resume from an approval included: the run's tenant and
principal (`bind_tenant`), the actor `agent` with the run's boundary chain and
mode read from its run row (`bind_actor`), then the reach door
`studio.ensure_principal_scope()`, all before the tool's first statement. So
the record policies decide with the principal's reach as it is now, never as it
was stamped when the run began (R6.6), within the boundaries the run's chain
fixed (R6.4), in the mode the row says, whatever `RunContext.run_mode` holds
(R6.3).

The principal named to `bind_tenant` is the one the context says the run acts
as; `bind_actor` refuses unless the run row agrees, so a context that drifted
from its row binds nothing. The real object tools join this in agent-builder/03
and tools-and-skills/03; a pack's code tools do not use it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.contracts import RunContext
from dw_platform.adapters.persistence.tenant_session import TenantScope, bind_actor, bind_tenant

_REACH_DOOR = text("SELECT studio.ensure_principal_scope()")


def run_principal(run: RunContext) -> uuid.UUID:
    """Whom the run acts as: its run-as principal, else whoever asked, else
    its actor (the row's `coalesce(run_as_principal_id, requested_by)`)."""
    return run.run_as_principal_id or run.requested_by or run.actor_id


@asynccontextmanager
async def agent_record_session(
    session_factory: async_sessionmaker[AsyncSession], run: RunContext
) -> AsyncIterator[AsyncSession]:
    """A session inside one transaction of ``run``'s tool call, bound to its
    tenant, principal and the actor `agent` within its boundaries, the
    principal's reach row made valid. Commits on a clean exit, rolls back on an
    exception."""
    async with session_factory() as session, session.begin():
        await bind_tenant(
            session,
            TenantScope(
                tenant_id=run.tenant_id,
                workspace_id=run.workspace_id,
                principal_id=run_principal(run),
            ),
        )
        await bind_actor(session, "agent", run_id=run.run_id)
        (await session.execute(_REACH_DOOR)).first()
        yield session
