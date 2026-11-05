"""One admission in a process of its own (usage-and-limits R4.8): a fresh
interpreter, a fresh connection, nothing cached from the test that started it.

    python limits_admit_probe.py <dw_app url> <tenant id> <workspace id>

Prints the new lease's `reserved_usd` as JSON, or `{"refused": ...}`.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.contracts import RunContext
from dw_kernel.limits import LimitExceededError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_usage.adapters.limits_sql import SqlLimits


async def main(url: str, tenant: uuid.UUID, workspace: uuid.UUID) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    context = RunContext(
        run_id=uuid.uuid4(),
        tenant_id=tenant,
        workspace_id=workspace,
        actor_id=uuid.uuid4(),
        worker_id="dw:probe",
        worker_version="1.0.0",
        channel="test",
        plan_id="probe",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="probe",
        run_mode="live",
    )
    try:
        await SqlLimits(sessions, clock=SystemClock(), ids=Uuid4Generator()).admit(context)
        async with sessions() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            held = await session.scalar(
                sa.text("SELECT reserved_usd FROM platform.budget_leases WHERE root_run_id = :r"),
                {"r": context.run_id},
            )
        print(json.dumps({"reserved_usd": str(held)}))
    except LimitExceededError as refused:
        print(json.dumps({"refused": refused.details}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], uuid.UUID(sys.argv[2]), uuid.UUID(sys.argv[3])))
