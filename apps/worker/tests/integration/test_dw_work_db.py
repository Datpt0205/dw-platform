"""Integration: the `dw_work` lane on real PostgreSQL, as `dw_app`.

digital-worker ticket 02: R3.6 (DWK10, one start per item even with two lanes),
R3.7 (DWK11, a paused DW is left alone), R3.9 (DWK27, the limit defers),
R3.15 (a refused start fails the item, an existing run does not), R3.14
(DWK35/DWK37, a claim with no run returns with its run id and is started
again with it).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConfigError, ConflictError, QuotaExceededError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.work_queue import Claimed, InMemoryWorkKindSchemas, WorkQueue
from dw_worker.consumers.dw_work import build_dw_work_consumer

pytestmark = pytest.mark.integration


@dataclass
class Starter:
    """Counts starts; raises what it is told to, once per item."""

    raises: Exception | None = None
    started: list[Claimed] = field(default_factory=list)

    async def start(self, claimed: Claimed) -> None:
        self.started.append(claimed)
        if self.raises is not None:
            raise self.raises


@dataclass
class Seeded:
    tenant: uuid.UUID
    workspace: uuid.UUID
    dw: uuid.UUID
    items: list[uuid.UUID]


@pytest.fixture
async def engines(worker_db: DatabaseUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(worker_db.migrator, poolclass=NullPool)
    app = create_async_engine(worker_db.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


async def seed(migrator: AsyncEngine, *, state: str = "operating", items: int = 1) -> Seeded:
    t, w, owner, principal, dw = (uuid.uuid4() for _ in range(5))
    work = [uuid.uuid4() for _ in range(items)]
    async with migrator.begin() as conn:
        for sql, values in (
            (
                "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)",
                {"t": t, "s": f"dww-{t.hex[:12]}"},
            ),
            (
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'main', 'main')",
                {"w": w, "t": t},
            ),
            (
                "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'owner')",
                {"u": owner, "s": f"dww-{owner}"},
            ),
            (
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
                " VALUES (:i, :t, :w, :u, '[\"approver\"]'::jsonb)",
                {"i": uuid.uuid4(), "t": t, "w": w, "u": owner},
            ),
            (
                "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                " VALUES (:u, :s, 'dw', 'service', :t)",
                {"u": principal, "s": f"service:{principal}", "t": t},
            ),
            (
                "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
                " name, owner_user_id) VALUES (:u, :t, :w, 'dw', :o)",
                {"u": principal, "t": t, "w": w, "o": owner},
            ),
            (
                "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
                " principal_user_id, key, name, mandate, work_kinds, allowed_tools, workflow_key,"
                " workflow_version, state, technical_owner_id, work_assigner_id, validator_id,"
                " created_by) VALUES (:d, :t, :w, :u, 'lane_dw', 'dw', 'dw', ARRAY['lead.new'],"
                " ARRAY[]::text[], 'leadcare', '1.0.0', :st, :o, :o, :o, :o)",
                {"d": dw, "t": t, "w": w, "u": principal, "o": owner, "st": state},
            ),
        ):
            await conn.execute(sa.text(sql), values)
        for n, item in enumerate(work):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.work_items (id, tenant_id, workspace_id, dw_id, kind,"
                    " source_key, payload, payload_hash, holder_kind, holder_id)"
                    " VALUES (:i, :t, :w, :d, 'lead.new', :k, CAST(:p AS jsonb), repeat('a', 64),"
                    " 'digital_worker', :d)"
                ),
                {"i": item, "t": t, "w": w, "d": dw, "k": f"k-{n}", "p": json.dumps({"n": n})},
            )
    return Seeded(t, w, dw, work)


def queue(app: AsyncEngine) -> WorkQueue:
    sessions = async_sessionmaker(app, expire_on_commit=False)
    return WorkQueue(
        repo=SqlWorkQueueRepository(sessions),
        workers=SqlDigitalWorkerRepository(sessions),
        people=SqlDwMembershipCheck(sessions),
        schemas=InMemoryWorkKindSchemas({}),
        authz=ScopeAuthorizationService(),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


async def statuses(migrator: AsyncEngine, s: Seeded) -> list[tuple[str, uuid.UUID | None]]:
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT status, run_id FROM platform.work_items WHERE dw_id = :d ORDER BY id"
                ),
                {"d": s.dw},
            )
        ).all()
    return [(r.status, r.run_id) for r in rows]


async def test_two_lanes_start_each_item_once(engines: tuple[AsyncEngine, AsyncEngine]) -> None:
    """DWK10."""
    migrator, app = engines
    s = await seed(migrator, items=5)
    first, second = Starter(), Starter()
    await asyncio.gather(
        build_dw_work_consumer(queue(app), first)(), build_dw_work_consumer(queue(app), second)()
    )
    started = [c.item.id for c in (*first.started, *second.started) if c.item.dw_id == s.dw]
    assert sorted(started) == sorted(s.items)
    assert all(status == "in_progress" and run for status, run in await statuses(migrator, s))


async def test_a_paused_dw_is_left_alone(engines: tuple[AsyncEngine, AsyncEngine]) -> None:
    """DWK11."""
    migrator, app = engines
    s = await seed(migrator, state="paused")
    starter = Starter()
    await build_dw_work_consumer(queue(app), starter)()
    assert [c for c in starter.started if c.item.dw_id == s.dw] == []
    assert [status for status, _ in await statuses(migrator, s)] == ["open"]


async def test_the_limit_defers_and_a_refusal_fails(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """DWK27, R3.15."""
    migrator, app = engines
    limited = await seed(migrator)
    await build_dw_work_consumer(queue(app), Starter(QuotaExceededError("runs_per_day")))()
    [(status, run_id)] = await statuses(migrator, limited)
    assert status == "open" and run_id is not None
    async with migrator.connect() as conn:
        due = (
            await conn.execute(
                sa.text(
                    "SELECT available_at - now() > interval '4 minutes'"
                    " FROM platform.work_items WHERE dw_id = :d"
                ),
                {"d": limited.dw},
            )
        ).scalar_one()
    assert due is True

    refused = await seed(migrator)
    await build_dw_work_consumer(queue(app), Starter(ConfigError("workflow not loaded")))()
    [(status, _)] = await statuses(migrator, refused)
    assert status == "failed"

    exists = await seed(migrator)
    await build_dw_work_consumer(queue(app), Starter(ConflictError("run exists")))()
    [(status, _)] = await statuses(migrator, exists)
    assert status == "in_progress"


async def test_a_claim_that_never_became_a_run_is_started_again_with_its_id(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """DWK35, DWK37: the same run id, so an effect keyed `wf:<run_id>:...` is
    not repeated by the second start."""
    migrator, app = engines
    s = await seed(migrator)
    first = Starter()
    await build_dw_work_consumer(queue(app), first)()
    [claimed] = [c for c in first.started if c.item.dw_id == s.dw]
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.work_items SET updated_at = now() - interval '16 minutes'"
                " WHERE dw_id = :d"
            ),
            {"d": s.dw},
        )
    second = Starter()
    await build_dw_work_consumer(queue(app), second)()
    [again] = [c for c in second.started if c.item.dw_id == s.dw]
    assert again.run_id == claimed.run_id
