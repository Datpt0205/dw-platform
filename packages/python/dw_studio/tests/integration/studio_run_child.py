"""The process `test_studio_runs.py` kills: it takes one queued Studio run and
runs it until its `FileDoor` ends the process (`os._exit`) right after the
step named on the command line applied its send, before anything after it.

    python studio_run_child.py <app url> <tenant id> <run id> <door file> <step>
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# The stack is a test support module (`tests/support`), on pytest's path only.
SUPPORT = Path(__file__).resolve().parents[5] / "tests" / "support"


async def main(url: str, tenant: str, run: str, door_file: str, step: str) -> None:
    sys.path.insert(0, str(SUPPORT))
    from studio_run_stack import FileDoor, build_runner

    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    door = FileDoor(Path(door_file), die_after=step)
    runner, _ = build_runner(sessions, {"tool": door, "records": door})
    await runner.run_studio(tenant_id=uuid.UUID(tenant), run_id=uuid.UUID(run))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:6]))
