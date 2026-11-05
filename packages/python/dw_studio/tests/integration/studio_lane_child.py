"""The worker `test_studio_run_lane.py` kills: one tick of the real
`studio_runs` lane over one tenant, with a claim lease of two seconds and a
beat every half second (the lane's own 60 s and 15 s, scaled), whose
`FileDoor` ends the process (`os._exit`) right after the step named on the
command line applied its send.

    python studio_lane_child.py <app url> <tenant id> <door file> <step>
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# The stack is a test support module (`tests/support`), on pytest's path only.
SUPPORT = Path(__file__).resolve().parents[5] / "tests" / "support"


async def main(url: str, tenant: str, door_file: str, step: str) -> None:
    sys.path.insert(0, str(SUPPORT))
    from studio_run_stack import FileDoor, build_runner, scoped_queue

    from dw_agent_runtime.studio_lane import StudioRunsLane

    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    door = FileDoor(Path(door_file), die_after=step)
    runner, _ = build_runner(sessions, {"tool": door})
    lane = StudioRunsLane(
        queue=scoped_queue(sessions, frozenset({uuid.UUID(tenant)})),
        runner=runner,
        worker="child",
        lease=timedelta(seconds=2),
        heartbeat_seconds=0.5,
    )
    await lane()
    while lane.running:
        await asyncio.sleep(0.05)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:5]))
