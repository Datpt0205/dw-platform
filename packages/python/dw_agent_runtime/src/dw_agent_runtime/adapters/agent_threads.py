"""`SqlAgentThreads`: a finished Studio agent run's checkpoints, gone when it
ends (agent-builder ticket 03 step 5; ADR-0117 decision 6).

A Studio agent run is its own thread (`thread_id = run_id`), and what its
checkpoints hold is the conversation's content, which is kept in exactly one
place, the conversation (or a trial's record), and never in the run. So once
the run has ended there is nothing to resume from them, and they go at once
rather than waiting for the retention lane's term (`checkpoint_retention`).

The delete is guarded in its own statement, the way the retention pass is: it
removes a thread's rows only while the run that is the thread is visible and
in a terminal status and no run on the thread is unfinished, so a run still
waiting for a person keeps its checkpoint, and an invisible `worker_runs`
deletes nothing. One transaction of `dw_app` under the run's tenant (RLS).
This, `SqlAlchemyCheckpointSaver.compact` (a waiting run's older checkpoints)
and the retention lane are the three deleters of checkpoints.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.run_store import TERMINAL_STATUSES
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

_TERMINAL = tuple(sorted(status.value for status in TERMINAL_STATUSES))

_SETTLED = (
    " EXISTS (SELECT 1 FROM platform.worker_runs r"
    "   WHERE r.id = :t AND r.status IN :terminal)"
    " AND NOT EXISTS (SELECT 1 FROM platform.worker_runs r"
    "   WHERE r.thread_id = :t AND r.status NOT IN :terminal)"
)
_FORGET_WRITES = sa.text(
    f"DELETE FROM platform.run_checkpoint_writes WHERE thread_id = :t AND {_SETTLED}"
).bindparams(sa.bindparam("terminal", expanding=True))
_FORGET_CHECKPOINTS = sa.text(
    f"DELETE FROM platform.run_checkpoints WHERE thread_id = :t AND {_SETTLED}"
).bindparams(sa.bindparam("terminal", expanding=True))


@dataclass(frozen=True)
class SqlAgentThreads:
    session_factory: async_sessionmaker[AsyncSession]

    async def forget(self, tenant_id: uuid.UUID, thread_id: uuid.UUID) -> None:
        params = {"t": thread_id, "terminal": list(_TERMINAL)}
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            await session.execute(_FORGET_WRITES, params)
            await session.execute(_FORGET_CHECKPOINTS, params)
