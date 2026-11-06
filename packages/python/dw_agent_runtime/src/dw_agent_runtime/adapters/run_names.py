"""`SqlRunNames`: whom a Studio agent's frame says is asking (agent-builder
R2.1; ADR-0117 decision 4's `user_display_name` and `workspace_name`).

One read per model call, in a transaction of `dw_app` under the run's tenant:
the display name of the person the run acts for and the name of its
workspace. A name this transaction cannot read (a person who left, another
tenant's workspace) is an empty string, which the frame shows as nothing
rather than a guess; both values are contained by `assemble_system_prompt`.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.record_session import run_principal
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.studio_agent import RunNames
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

_NAMES = sa.text(
    "SELECT"
    " (SELECT u.display_name FROM platform.users u WHERE u.id = :person) AS person,"
    " (SELECT w.name FROM platform.workspaces w WHERE w.id = :workspace) AS workspace"
)


@dataclass(frozen=True)
class SqlRunNames:
    session_factory: async_sessionmaker[AsyncSession]

    async def names(self, run: RunContext) -> RunNames:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=run.tenant_id)
        ) as session:
            row = (
                await session.execute(
                    _NAMES, {"person": run_principal(run), "workspace": run.workspace_id}
                )
            ).one()
        return RunNames(person=row.person or "", workspace=row.workspace or "")
