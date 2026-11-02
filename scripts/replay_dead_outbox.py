"""Put dead outbox events back on the queue, in an operator's name
(runtime-hardening R10.4, R10.5; DO-56.1).

    DW_DATABASE_URL=postgresql+asyncpg://dw_app:...@host/dw \\
        uv run python scripts/replay_dead_outbox.py --operator ops@fdx.vn <event_id>...

Run by a platform operator with the application's credentials (`dw_app`):
`--operator` must be a user in `platform.platform_operators`, or nothing is
touched and the script exits 1. Each event is replayed in its own
transaction, under its own tenant: `dead_at` cleared, no attempts spent, due
now, and one `platform.outbox.replayed` audit row naming the operator, both
or neither. The payload is never read. An id that is not a dead event (never
was, already replayed, delivered since) is reported and changes nothing, and
the script exits 2. No tenant has a route for this: a tenant sees its failed
runs in its run history.

Exit codes: 0 all replayed; 1 the operator is unknown; 2 some ids were not
dead events.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.outbox_drain import DeadEvent, SqlDeadLetters
from dw_platform.domain.audit import AuditEvent

ACTION = "platform.outbox.replayed"


async def operator_of(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> uuid.UUID | None:
    """The platform operator with this email, or None."""
    u, o = tables.users, tables.platform_operators
    async with session_factory() as session:
        return (
            await session.execute(
                sa.select(u.c.id)
                .select_from(u.join(o, o.c.user_id == u.c.id))
                .where(sa.func.lower(u.c.email) == email.strip().lower())
            )
        ).scalar_one_or_none()


def _audit(event: DeadEvent, operator: uuid.UUID) -> AuditEvent:
    return AuditEvent(
        id=uuid.uuid4(),
        tenant_id=TenantId(event.tenant_id),
        workspace_id=WorkspaceId(event.workspace_id),
        actor_id=UserId(operator),
        action=ACTION,
        resource_type="outbox_event",
        resource_id=str(event.id),
        details={"event_type": event.event_type},
        occurred_at=datetime.now(UTC),
    )


async def replay(
    session_factory: async_sessionmaker[AsyncSession],
    operator_email: str,
    event_ids: Sequence[uuid.UUID],
) -> int:
    operator = await operator_of(session_factory, operator_email)
    if operator is None:
        print(f"{operator_email} is not a platform operator; nothing replayed", file=sys.stderr)
        return 1
    letters = SqlDeadLetters(session_factory)
    missing = 0
    for event_id in event_ids:
        event = await letters.find(event_id)
        if event is None or not await letters.replay(event, _audit(event, operator)):
            print(f"{event_id}: not a dead event; unchanged", file=sys.stderr)
            missing += 1
            continue
        print(f"{event_id}: replayed ({event.event_type})")
    return 2 if missing else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--operator", required=True, help="the platform operator's email")
    parser.add_argument("event_ids", nargs="+", type=uuid.UUID)
    args = parser.parse_args(argv)
    url = os.environ.get("DW_DATABASE_URL")
    if not url:
        print("DW_DATABASE_URL is not set", file=sys.stderr)
        return 1
    engine = create_async_engine(url)

    async def run() -> int:
        try:
            return await replay(
                async_sessionmaker(engine, expire_on_commit=False), args.operator, args.event_ids
            )
        finally:
            await engine.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
