"""A run's model spend on its own row (digital-worker R7.3).

Implements `UsageRecorderPort`: each call's `cost_usd` is added to the
`model_cost_usd` of the run it was made for, in one statement that adds rather
than reads and writes, so two calls of one run at once both count. A call made
outside any run row (a single call with no run, a run not yet written) touches
nothing. Fail-open like every recorder behind `CompositeUsageRecorder`: the
answer has been paid for already, and a lost addition is logged there.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import ModelUsage
from dw_agent_runtime.ports import ModelRequest
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

_ADD = sa.text("UPDATE platform.worker_runs SET model_cost_usd = model_cost_usd + :c WHERE id = :r")


@dataclass(frozen=True)
class RunCostRecorder:
    session_factory: async_sessionmaker[AsyncSession]

    async def record(
        self, run_context: RunContext, request: ModelRequest, usage: ModelUsage
    ) -> None:
        if usage.cost_usd <= 0:
            return
        scope = TenantScope(tenant_id=run_context.tenant_id, workspace_id=run_context.workspace_id)
        async with tenant_session(self.session_factory, scope) as session:
            # str() first: Decimal(0.1) carries float's binary error.
            await session.execute(
                _ADD, {"c": Decimal(str(usage.cost_usd)), "r": run_context.run_id}
            )
