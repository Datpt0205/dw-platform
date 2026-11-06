"""A thread's checkpoints compacted to its latest (workflow-engine R6.11,
DO-41; ADR-0113 decision 4), in the caller's transaction.

Plain SQL over `platform.run_checkpoints` and its pending writes, apart from
`SqlAlchemyCheckpointSaver` so the Studio run store calls it in the park of a
run that waits without importing LangGraph (Studio never does, ADR-0112
Amendments 2026-11-03). With the `checkpoint_retention` lane, the only
deleter of checkpoints short of offboarding.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# R6.11 (DO-41): the latest checkpoint of each namespace of a thread, which a
# waiting run resumes from; every other one, and the writes of every other
# one, go.
_LATEST = (
    "SELECT checkpoint_ns, max(checkpoint_id) AS checkpoint_id"
    " FROM platform.run_checkpoints WHERE thread_id = :t GROUP BY checkpoint_ns"
)
_COMPACT_WRITES = sa.text(
    f"WITH latest AS ({_LATEST})"
    " DELETE FROM platform.run_checkpoint_writes w WHERE w.thread_id = :t"
    " AND NOT EXISTS (SELECT 1 FROM latest l"
    "   WHERE l.checkpoint_ns = w.checkpoint_ns AND l.checkpoint_id = w.checkpoint_id)"
)
_COMPACT_CHECKPOINTS = sa.text(
    f"WITH latest AS ({_LATEST})"
    " DELETE FROM platform.run_checkpoints c WHERE c.thread_id = :t"
    " AND NOT EXISTS (SELECT 1 FROM latest l"
    "   WHERE l.checkpoint_ns = c.checkpoint_ns AND l.checkpoint_id = c.checkpoint_id)"
)


async def compact_thread(session: AsyncSession, thread_id: uuid.UUID) -> int:
    """Delete every checkpoint of the thread but the latest of each namespace,
    and their pending writes; how many checkpoints went."""
    await session.execute(_COMPACT_WRITES, {"t": thread_id})
    gone = await session.execute(_COMPACT_CHECKPOINTS, {"t": thread_id})
    return int(getattr(gone, "rowcount", 0) or 0)
