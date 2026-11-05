"""SqlTenantOffboarding against real Postgres: catalog discovery, FK order, isolation.

Seeds through raw SQL rather than importing `dw_memory`/`dw_knowledge` table
objects — `dw_platform` declares no dependency on either (checked before
writing this), and `SqlTenantOffboarding` itself never imports them either.
That is the property under test as much as export/purge behavior is: this
file couldn't cheat by reaching for a table object even if it wanted to.

Each test seeds its own fresh tenant/workspace pair rather than sharing module
constants: `db_urls` is session-scoped (one database for the whole file), and
seeding the same ids twice collides on `uq_workspaces_tenant_slug`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_platform.adapters.persistence.offboarding import (
    _FOREIGN_KEYS,
    STUDIO_EXCLUSIONS,
    ExportedTable,
    OffboardingPurgeStep,
    SqlTenantOffboarding,
    order_purge_steps,
)
from dw_platform.testing.members import add_tenant_member

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 22, tzinfo=UTC)


async def _collect(batches: AsyncIterator[ExportedTable]) -> list[ExportedTable]:
    """Every batch of an export, merged per table in arrival order."""
    merged: dict[tuple[str, str], ExportedTable] = {}
    async for batch in batches:
        key = (batch.schema, batch.table)
        if key in merged:
            merged[key].rows.extend(batch.rows)
        else:
            merged[key] = ExportedTable(batch.schema, batch.table, list(batch.rows))
    return list(merged.values())


@dataclass(frozen=True)
class _Tenant:
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID


def _new_tenant() -> _Tenant:
    return _Tenant(tenant_id=uuid.uuid4(), workspace_id=uuid.uuid4())


@pytest.fixture
async def sessions(db_urls: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _seed_tenant(sessions: async_sessionmaker[AsyncSession], t: _Tenant) -> None:
    """A tenant + workspace, plus a chain that exercises every FK-RESTRICT
    edge purge order depends on:
    worker_runs <- items <- item_evidence -> evidence <- (chunks, documents).
    """
    run_id, memory_id, evidence_id, document_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)}
        )
        await session.execute(
            # As the lane finds it: offboarding has begun (compliance-pdpl R5.6).
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status)"
                " VALUES (:t, :slug, :slug, 'offboarding')"
            ),
            {"t": t.tenant_id, "slug": f"off-{t.tenant_id.hex[-10:]}"},
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'main', 'Main')"
            ),
            {"w": t.workspace_id, "t": t.tenant_id},
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.worker_runs"
                " (run_mode, id, thread_id, tenant_id, workspace_id, worker_id, worker_version,"
                "  graph_version, requested_by)"
                " VALUES ('live', :r, :r, :t, :w, 'demo', '1.0.0', '1.0.0', gen_random_uuid())"
            ),
            {"r": run_id, "t": t.tenant_id, "w": t.workspace_id},
        )
        await session.execute(
            sa.text(
                "INSERT INTO knowledge.documents"
                " (id, tenant_id, workspace_id, title, source_uri, created_by, created_at)"
                " VALUES (:d, :t, :w, 'tài liệu', 's3://dw/x', gen_random_uuid(), :c)"
            ),
            {"d": document_id, "t": t.tenant_id, "w": t.workspace_id, "c": NOW},
        )
        await session.execute(
            sa.text(
                "INSERT INTO knowledge.evidence"
                " (evidence_id, tenant_id, workspace_id, source_document_id, source_version,"
                "  relevance_score, classification, provenance_hash, created_at)"
                " VALUES (:e, :t, :w, :d, '1', 0.9, 'internal', :h, :c)"
            ),
            {
                "e": evidence_id,
                "t": t.tenant_id,
                "w": t.workspace_id,
                "d": document_id,
                "h": "0" * 64,
                "c": NOW,
            },
        )
        await session.execute(
            sa.text(
                "INSERT INTO memory.items"
                " (memory_id, tenant_id, workspace_id, worker_id, memory_type, subject_refs,"
                "  content, structured_facts, provenance_refs, confidence, classification,"
                "  valid_from, retention_policy, memory_schema_version, created_by_run_id,"
                "  created_at)"
                " VALUES (:m, :t, :w, 'demo', 'semantic', '[]', 'x', '{}',"
                "  :refs, 0.9, 'internal', :c, 'default', '1.0.0', :r, :c)"
            ),
            {
                "m": memory_id,
                "t": t.tenant_id,
                "w": t.workspace_id,
                "refs": f'[{{"evidence_id": "{uuid.uuid4()}"}}]',
                "c": NOW,
                "r": run_id,
            },
        )
        await session.execute(
            sa.text(
                "INSERT INTO memory.item_evidence (memory_id, evidence_id, tenant_id)"
                " VALUES (:m, :e, :t)"
            ),
            {"m": memory_id, "e": evidence_id, "t": t.tenant_id},
        )
        # Append-only: dw_app has no DELETE here (0001_platform_grants.sql).
        # purge_rows must skip it entirely, not fail trying.
        await session.execute(
            sa.text(
                "INSERT INTO platform.audit_events"
                " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
                "  resource_id, details, occurred_at)"
                " VALUES (gen_random_uuid(), :t, :w, gen_random_uuid(), 'test.seed',"
                "  'test', 'r-1', '{}', :c)"
            ),
            {"t": t.tenant_id, "w": t.workspace_id, "c": NOW},
        )


async def _count(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, schema: str, table: str
) -> int:
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        return (
            await session.scalar(
                sa.text(f'SELECT count(*) FROM "{schema}"."{table}" WHERE tenant_id = :t'),
                {"t": str(tenant_id)},
            )
        ) or 0


async def test_catalog_discovery_sees_a_table_added_after_this_class_was_written(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """`budget_leases` (usage-and-limits ticket 03) is not named anywhere in
    offboarding.py — proof the discovery is real, not a list that happens to be
    current today."""
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    async with sessions() as session, session.begin():
        exportable = await offboarding._exportable_tables(session)
        purgeable = await offboarding._purgeable_tables(session)
    assert ("platform", "budget_leases") in exportable
    assert ("platform", "budget_leases") in purgeable
    assert ("platform", "tenant_offboarding_requests") not in exportable, (
        "the request row IS the job; it must never purge itself"
    )
    assert ("platform", "tenants") not in exportable, (
        "tenants carries a tenant_isolation_% policy but no tenant_id column"
    )
    assert ("platform", "audit_events") in exportable, "the tenant may still export its own audit"
    assert ("platform", "audit_events") not in purgeable, (
        "audit_events is append-only (dw_app has no DELETE); its own retention"
        " term governs it, not offboarding"
    )


async def test_export_rows_returns_only_this_tenants_data(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    mine, theirs = _new_tenant(), _new_tenant()
    await _seed_tenant(sessions, mine)
    await _seed_tenant(sessions, theirs)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    exported = await _collect(offboarding.export_rows(mine.tenant_id))

    by_table = {(t.schema, t.table): t.rows for t in exported}
    workspace_rows = by_table[("platform", "workspaces")]
    assert [str(r["tenant_id"]) for r in workspace_rows] == [str(mine.tenant_id)]
    item_rows = by_table[("memory", "items")]
    assert [str(r["tenant_id"]) for r in item_rows] == [str(mine.tenant_id)]


async def test_purge_rows_respects_fk_order_and_leaves_the_other_tenant_alone(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    mine, theirs = _new_tenant(), _new_tenant()
    await _seed_tenant(sessions, mine)
    await _seed_tenant(sessions, theirs)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    await offboarding.purge_rows(mine.tenant_id)  # must not raise a FK violation

    for schema, table in (
        ("memory", "items"),
        ("memory", "item_evidence"),
        ("knowledge", "evidence"),
        ("knowledge", "documents"),
        ("platform", "worker_runs"),
        ("platform", "workspaces"),
    ):
        assert await _count(sessions, mine.tenant_id, schema, table) == 0, (
            f"{schema}.{table} not purged"
        )
        assert await _count(sessions, theirs.tenant_id, schema, table) == 1, (
            f"{schema}.{table} lost the other tenant's row too"
        )

    assert await _count(sessions, mine.tenant_id, "platform", "audit_events") == 1, (
        "audit_events is append-only; purge must not touch it even for the tenant being offboarded"
    )


async def _seed_member(sessions: async_sessionmaker[AsyncSession], t: _Tenant) -> uuid.UUID:
    """A person of the tenant: the company row and a membership hanging from it
    (org-and-principals R4.1), written as `dw_app` under the tenant."""
    user = uuid.uuid4()
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)}
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'member')"
            ),
            {"u": user, "s": f"off-{user}"},
        )
        await add_tenant_member(session, t.tenant_id, user)
        await session.execute(
            sa.text(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                " VALUES (gen_random_uuid(), :t, :w, :u)"
            ),
            {"t": t.tenant_id, "w": t.workspace_id, "u": user},
        )
    return user


async def test_offboarding_exports_and_purges_the_company_members(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Ticket 02 step 7: discovered from the catalog like every tenant table,
    exported first, then gone with the memberships hanging from it."""
    mine, theirs = _new_tenant(), _new_tenant()
    for t in (mine, theirs):
        await _seed_tenant(sessions, t)
    member = await _seed_member(sessions, mine)
    await _seed_member(sessions, theirs)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    exported = {
        (t.schema, t.table): t.rows for t in await _collect(offboarding.export_rows(mine.tenant_id))
    }
    assert [str(r["user_id"]) for r in exported[("platform", "tenant_members")]] == [str(member)]

    await offboarding.purge_rows(mine.tenant_id)

    for table in ("tenant_members", "memberships"):
        assert await _count(sessions, mine.tenant_id, "platform", table) == 0, table
        assert await _count(sessions, theirs.tenant_id, "platform", table) == 1, table


async def _seed_keys(sessions: async_sessionmaker[AsyncSession], t: _Tenant) -> None:
    """One HTTP idempotency key and one effect key (app-standards ticket 02)."""
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)}
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.idempotency_keys (tenant_id, idempotency_key, workspace_id,"
                " request_method, request_path, body_hash) VALUES (:t, 'k', :w, 'POST', '/p', 'h')"
            ),
            {"t": t.tenant_id, "w": t.workspace_id},
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.effect_keys (tenant_id, operation, idempotency_key,"
                " caller_ref, request_hash, result) VALUES (:t, 'POST /p', 'k', :c, :h,"
                ' CAST(\'{"status": 201, "id": "x"}\' AS jsonb))'
            ),
            {"t": t.tenant_id, "c": f"user:{uuid.uuid4()}", "h": "c" * 64},
        )


async def test_purge_removes_the_tenants_idempotency_and_effect_keys(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """app-standards R2.27 (APS29): both key tables lose this tenant's rows, as
    `dw_app`, without a permission error, and keep the other tenant's."""
    mine, theirs = _new_tenant(), _new_tenant()
    for tenant in (mine, theirs):
        await _seed_tenant(sessions, tenant)
        await _seed_keys(sessions, tenant)

    await SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES).purge_rows(
        mine.tenant_id
    )

    for table in ("idempotency_keys", "effect_keys"):
        assert await _count(sessions, mine.tenant_id, "platform", table) == 0, table
        assert await _count(sessions, theirs.tenant_id, "platform", table) == 1, table


async def _seed_checkpoint(sessions: async_sessionmaker[AsyncSession], t: _Tenant) -> None:
    """One run checkpoint and one pending write: the verbatim conversation a
    thread leaves behind, which must go with the tenant."""
    thread = uuid.uuid4()
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)}
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.run_checkpoints"
                " (thread_id, checkpoint_ns, checkpoint_id, tenant_id, workspace_id,"
                "  type, checkpoint, metadata)"
                " VALUES (:th, '', 'c1', :t, :w, 'msgpack', '\\x00', '\\x00')"
            ),
            {"th": thread, "t": t.tenant_id, "w": t.workspace_id},
        )
        await session.execute(
            sa.text(
                "INSERT INTO platform.run_checkpoint_writes"
                " (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, tenant_id,"
                "  workspace_id, channel, type, value)"
                " VALUES (:th, '', 'c1', 'task', 0, :t, :w, 'messages', 'msgpack', '\\x00')"
            ),
            {"th": thread, "t": t.tenant_id, "w": t.workspace_id},
        )


async def test_purge_deletes_the_tenants_run_checkpoints(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Pinned, not built: the lane finds both checkpoint tables from the catalog
    (a `tenant_isolation_%` policy and `dw_app` holding DELETE), so nothing here
    names them. This is what goes red if either stops being true."""
    mine, theirs = _new_tenant(), _new_tenant()
    for t in (mine, theirs):
        await _seed_tenant(sessions, t)
        await _seed_checkpoint(sessions, t)

    await SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES).purge_rows(
        mine.tenant_id
    )

    for table in ("run_checkpoints", "run_checkpoint_writes"):
        assert await _count(sessions, mine.tenant_id, "platform", table) == 0, (
            f"platform.{table} kept the offboarded tenant's conversation"
        )
        assert await _count(sessions, theirs.tenant_id, "platform", table) == 1, (
            f"platform.{table} lost the other tenant's row too"
        )


async def test_purge_records_an_audit_event_before_deleting_anything(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """The one delete-adjacent thing in this pass that cannot be undone gets
    its own permanent record — in `audit_events`, which the purge it belongs
    to can never itself remove."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)  # seeds one audit_events row of its own
    request_id = await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    await offboarding.purge_rows(mine.tenant_id)

    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mine.tenant_id)}
        )
        row = (
            await session.execute(
                sa.text(
                    "SELECT actor_id, resource_id FROM platform.audit_events"
                    " WHERE action = 'tenant.offboarding.purged' AND tenant_id = :t"
                ),
                {"t": str(mine.tenant_id)},
            )
        ).one()
        requested_by = await session.scalar(
            sa.text("SELECT requested_by FROM platform.tenant_offboarding_requests WHERE id = :r"),
            {"r": request_id},
        )
    assert row.resource_id == str(mine.tenant_id)
    assert row.actor_id == requested_by, "the audit row credits the operator who requested this"


async def _file_request(db_urls: DatabaseUrls, tenant_id: uuid.UUID) -> uuid.UUID:
    """dw_app has no INSERT on this table (migration 5d9d89ffc716) - insert as
    the migrator, the same way the real row already exists by the time a
    worker lane sees it (the operator's INSERT happens through
    dw_provisioner, which bypasses RLS)."""
    request_id = uuid.uuid4()
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenant_offboarding_requests"
                    " (id, tenant_id, requested_by) VALUES (:r, :t, gen_random_uuid())"
                ),
                {"r": request_id, "t": tenant_id},
            )
    finally:
        await migrator.dispose()
    return request_id


async def test_purge_never_touches_the_offboarding_request_itself(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    request_id = await _file_request(db_urls, mine.tenant_id)

    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    await offboarding.purge_rows(mine.tenant_id)

    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mine.tenant_id)}
        )
        found = await session.scalar(
            sa.text("SELECT 1 FROM platform.tenant_offboarding_requests WHERE id = :r"),
            {"r": request_id},
        )
    assert found == 1, "the request row must survive its own purge pass"


async def test_another_tenant_cannot_read_the_request_through_ordinary_rls(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """Through `dw_app` directly, RLS on, no drain — the path an application
    request actually takes. `claim_requested`'s `app.worker_drain` escape
    hatch is for the worker's own poll, never reachable from a request, and
    this proves the ordinary policy still holds without it."""
    mine, theirs = _new_tenant(), _new_tenant()
    await _seed_tenant(sessions, mine)
    await _seed_tenant(sessions, theirs)
    await _file_request(db_urls, mine.tenant_id)

    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(theirs.tenant_id)}
        )
        rows = (
            await session.execute(
                sa.text("SELECT tenant_id FROM platform.tenant_offboarding_requests")
            )
        ).all()

    assert rows == [], "tenant B must see nothing of tenant A's offboarding request"


async def test_claim_requested_moves_status_and_returns_the_tenant(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    claimed = {c.tenant_id for c in await offboarding.claim_requested()}

    assert mine.tenant_id in claimed
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mine.tenant_id)}
        )
        status = await session.scalar(
            sa.text("SELECT status FROM platform.tenant_offboarding_requests WHERE tenant_id = :t"),
            {"t": str(mine.tenant_id)},
        )
    assert status == "exporting"


async def test_claim_requested_never_claims_the_same_request_twice(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    first = {c.tenant_id for c in await offboarding.claim_requested()}
    second = {c.tenant_id for c in await offboarding.claim_requested()}

    assert mine.tenant_id in first
    assert mine.tenant_id not in second, "a claimed request must not be claimed again"


async def _age_the_request(db_urls: DatabaseUrls, tenant_id: uuid.UUID, minutes_ago: int) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.tenant_offboarding_requests"
                    " SET updated_at = now() - make_interval(mins => :m)"
                    " WHERE tenant_id = :t"
                ),
                {"m": minutes_ago, "t": tenant_id},
            )
    finally:
        await migrator.dispose()


async def test_a_request_stuck_in_progress_past_the_stale_window_is_reclaimed(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """A worker that claimed a request and then died leaves it at
    'exporting'/'purging' forever otherwise — nothing else ever moves a
    request off 'requested', so a dead worker's claim has to expire."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    await offboarding.claim_requested()  # -> 'exporting', updated_at = now()
    await _age_the_request(db_urls, mine.tenant_id, minutes_ago=31)

    reclaimed = {c.tenant_id for c in await offboarding.claim_requested()}

    assert mine.tenant_id in reclaimed


async def test_a_request_still_in_progress_within_the_window_is_left_alone(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """The other side of the same window: a live worker still inside it must
    not have its claim stolen by another poll tick."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    await offboarding.claim_requested()
    await _age_the_request(db_urls, mine.tenant_id, minutes_ago=5)

    reclaimed = {c.tenant_id for c in await offboarding.claim_requested()}

    assert mine.tenant_id not in reclaimed


async def test_mark_status_reports_progress_on_the_tenants_own_row(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    await offboarding.claim_requested()

    await offboarding.mark_status(mine.tenant_id, "completed", export_key="x/exports/y.zip")

    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mine.tenant_id)}
        )
        row = (
            await session.execute(
                sa.text(
                    "SELECT status, export_key FROM platform.tenant_offboarding_requests"
                    " WHERE tenant_id = :t"
                ),
                {"t": str(mine.tenant_id)},
            )
        ).one()
    assert row.status == "completed"
    assert row.export_key == "x/exports/y.zip"


async def _request_rows(db_urls: DatabaseUrls, tenant_id: uuid.UUID) -> list[Any]:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            return list(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT id, status, export_key, error, updated_at"
                            " FROM platform.tenant_offboarding_requests WHERE tenant_id = :t"
                            " ORDER BY requested_at"
                        ),
                        {"t": tenant_id},
                    )
                ).all()
            )
    finally:
        await migrator.dispose()


async def _set_request(db_urls: DatabaseUrls, request_id: uuid.UUID, **values: Any) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            assignments = ", ".join(f"{column} = :{column}" for column in values)
            await conn.execute(
                sa.text(
                    f"UPDATE platform.tenant_offboarding_requests SET {assignments} WHERE id = :r"
                ),
                {"r": request_id, **values},
            )
    finally:
        await migrator.dispose()


async def test_a_stale_purging_request_is_claimed_back_with_its_bundle(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """foundations-hardening R11.10 (FH38): the bundle was uploaded before the
    request reached `purging`, so the claim keeps it there and hands back the key
    rather than restarting an export of a company that may already be gone."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    request_id = await _file_request(db_urls, mine.tenant_id)
    key = f"{mine.tenant_id}/offboarding-{request_id}.zip"
    await _set_request(db_urls, request_id, status="purging", export_key=key)
    await _age_the_request(db_urls, mine.tenant_id, minutes_ago=31)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    claims = [c for c in await offboarding.claim_requested() if c.tenant_id == mine.tenant_id]

    assert [(c.request_id, c.resume_export_key) for c in claims] == [(request_id, key)]
    (row,) = await _request_rows(db_urls, mine.tenant_id)
    assert (row.status, row.export_key) == ("purging", key)


async def test_a_stale_exporting_request_restarts_from_the_top(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """R11.10: before `purging` nothing was deleted, so the export runs again,
    under the same request (and so the same bundle key, R11.18)."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    request_id = await _file_request(db_urls, mine.tenant_id)
    await _set_request(db_urls, request_id, status="exporting", export_key="half/done.zip")
    await _age_the_request(db_urls, mine.tenant_id, minutes_ago=31)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    claims = [c for c in await offboarding.claim_requested() if c.tenant_id == mine.tenant_id]

    assert [(c.request_id, c.resume_export_key) for c in claims] == [(request_id, None)]
    (row,) = await _request_rows(db_urls, mine.tenant_id)
    assert row.status == "exporting"


async def test_keep_claim_refreshes_only_the_tenants_request_in_flight(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """R11.17 (FH44): the live pass's request, and nothing else: not the same
    company's finished request, not another company's request in flight."""
    mine, theirs = _new_tenant(), _new_tenant()
    await _seed_tenant(sessions, mine)
    await _seed_tenant(sessions, theirs)
    finished = await _file_request(db_urls, mine.tenant_id)
    await _set_request(db_urls, finished, status="completed")
    live = await _file_request(db_urls, mine.tenant_id)
    their_live = await _file_request(db_urls, theirs.tenant_id)
    for request_id in (live, their_live):
        await _set_request(db_urls, request_id, status="exporting")
    for tenant_id in (mine.tenant_id, theirs.tenant_id):
        await _age_the_request(db_urls, tenant_id, minutes_ago=20)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    before = {r.id: r.updated_at for r in await _request_rows(db_urls, mine.tenant_id)}
    before |= {r.id: r.updated_at for r in await _request_rows(db_urls, theirs.tenant_id)}

    await offboarding.keep_claim(mine.tenant_id)

    after = {r.id: r for r in await _request_rows(db_urls, mine.tenant_id)}
    after |= {r.id: r for r in await _request_rows(db_urls, theirs.tenant_id)}
    assert after[live].updated_at > before[live]
    assert after[live].status == "exporting"
    assert after[finished].updated_at == before[finished]
    assert after[their_live].updated_at == before[their_live]


async def test_mark_status_leaves_the_tenants_older_requests_alone(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """A company re-filed after a failure keeps its failed request as it was: that
    row may hold the key of a bundle exported before a purge."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    old = await _file_request(db_urls, mine.tenant_id)
    await _set_request(
        db_urls, old, status="failed", export_key="old/bundle.zip", error="InfrastructureError"
    )
    new = await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    await offboarding.claim_requested()

    await offboarding.mark_status(mine.tenant_id, "completed", export_key="new/bundle.zip")

    rows = {r.id: r for r in await _request_rows(db_urls, mine.tenant_id)}
    assert (rows[old].status, rows[old].export_key, rows[old].error) == (
        "failed",
        "old/bundle.zip",
        "InfrastructureError",
    )
    assert (rows[new].status, rows[new].export_key) == ("completed", "new/bundle.zip")


async def test_a_purge_run_again_writes_no_second_audit_row(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """R11.10 (FH38): a resumed pass runs the purge again after it committed; the
    company has no workspace left to write against, so the one record of the
    purge stays one (G8 holds for the first)."""
    mine = _new_tenant()
    await _seed_tenant(sessions, mine)
    await _file_request(db_urls, mine.tenant_id)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    await offboarding.purge_rows(mine.tenant_id)
    await offboarding.purge_rows(mine.tenant_id)

    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mine.tenant_id)}
        )
        purged = await session.scalar(
            sa.text(
                "SELECT count(*) FROM platform.audit_events"
                " WHERE action = 'tenant.offboarding.purged' AND tenant_id = :t"
            ),
            {"t": str(mine.tenant_id)},
        )
    assert purged == 1


# --- A table narrowed by workspace as well as tenant -------------------------
#
# No platform table is narrowed by workspace; a context's may be, with the policy
# shape `test_rls_coverage.py` holds them to. The probe below is that shape, made
# by the migrator for one test and dropped after it. While it exists it passes
# every guard of `test_rls_coverage.py` and `test_privileges.py` (RLS enabled and
# FORCEd, a `tenant_isolation_` policy on both sides, USAGE for dw_app), because
# `db_urls` is one database for the whole session.

_PROBE_SCHEMA = "offboarding_ws_probe"
_PROBE = f"{_PROBE_SCHEMA}.rows"
_PROBE_POLICY = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    " AND (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
    "      OR current_setting('app.workspace_scope', true) = 'tenant')"
)


@dataclass(frozen=True)
class _Probe:
    a: uuid.UUID  # two workspaces, one row in each
    b: uuid.UUID  # one workspace, one row


@pytest.fixture
async def ws_probe(db_urls: DatabaseUrls) -> AsyncIterator[_Probe]:
    a, b = uuid.uuid4(), uuid.uuid4()
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            for statement in (
                f"CREATE SCHEMA {_PROBE_SCHEMA}",
                f"CREATE TABLE {_PROBE} (tenant_id uuid NOT NULL, workspace_id uuid NOT NULL,"
                " label text NOT NULL, PRIMARY KEY (tenant_id, workspace_id, label))",
                f"ALTER TABLE {_PROBE} ENABLE ROW LEVEL SECURITY",
                f"ALTER TABLE {_PROBE} FORCE ROW LEVEL SECURITY",
                f"CREATE POLICY tenant_isolation_rows ON {_PROBE}"
                f" USING ({_PROBE_POLICY}) WITH CHECK ({_PROBE_POLICY})",
                f"GRANT USAGE ON SCHEMA {_PROBE_SCHEMA} TO dw_app",
                f"GRANT SELECT, DELETE ON {_PROBE} TO dw_app",
            ):
                await conn.execute(sa.text(statement))
            # Real tenants, A offboarding as the lane finds it: the platform's
            # own steps check it (compliance-pdpl R5.6).
            for tenant, status in ((a, "offboarding"), (b, "active")):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.tenants (id, slug, name, status)"
                        " VALUES (:t, :s, :s, :st)"
                    ),
                    {"t": tenant, "s": f"wsp-{tenant.hex[:10]}", "st": status},
                )
            await conn.execute(
                sa.text(
                    f"INSERT INTO {_PROBE} VALUES"
                    " (:a, gen_random_uuid(), 'a1'), (:a, gen_random_uuid(), 'a2'),"
                    " (:b, gen_random_uuid(), 'b1')"
                ),
                {"a": a, "b": b},
            )
        yield _Probe(a=a, b=b)
    finally:
        async with migrator.begin() as conn:
            await conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {_PROBE_SCHEMA} CASCADE"))
        await migrator.dispose()


async def _probe_labels(db_urls: DatabaseUrls, tenant_id: uuid.UUID) -> set[str]:
    """Through the migrator, which bypasses RLS: what is really in the table."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            rows = await conn.execute(
                sa.text(f"SELECT label FROM {_PROBE} WHERE tenant_id = :t"), {"t": tenant_id}
            )
            return {row.label for row in rows}
    finally:
        await migrator.dispose()


async def test_export_reads_every_workspace_of_the_tenant(
    sessions: async_sessionmaker[AsyncSession], ws_probe: _Probe
) -> None:
    exported = await _collect(
        SqlTenantOffboarding(sessions, scopes=OFFBOARDING_SCOPES).export_rows(ws_probe.a)
    )

    (probe,) = [t for t in exported if (t.schema, t.table) == (_PROBE_SCHEMA, "rows")]
    assert {row["label"] for row in probe.rows} == {"a1", "a2"}


async def test_purge_deletes_in_every_workspace_and_leaves_the_other_tenant(
    db_urls: DatabaseUrls, sessions: async_sessionmaker[AsyncSession], ws_probe: _Probe
) -> None:
    await SqlTenantOffboarding(sessions, scopes=OFFBOARDING_SCOPES).purge_rows(ws_probe.a)

    assert await _probe_labels(db_urls, ws_probe.a) == set()
    assert await _probe_labels(db_urls, ws_probe.b) == {"b1"}


async def test_the_workspace_scope_never_crosses_tenants(
    sessions: async_sessionmaker[AsyncSession], ws_probe: _Probe
) -> None:
    """Tenant B with the scope set sees all of its own rows and none of A's."""
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                "       set_config('app.workspace_scope', 'tenant', true)"
            ),
            {"t": str(ws_probe.b)},
        )
        labels = {
            row.label for row in await session.execute(sa.text(f"SELECT label FROM {_PROBE}"))
        }
    assert labels == {"b1"}


async def test_the_workspace_scope_ends_with_the_transaction(
    db_urls: DatabaseUrls, ws_probe: _Probe
) -> None:
    """One pooled connection: the next borrower must not inherit the scope."""
    engine = create_async_engine(db_urls.app, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            before = (await session.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
        await _collect(
            SqlTenantOffboarding(factory, scopes=OFFBOARDING_SCOPES).export_rows(ws_probe.a)
        )
        async with factory() as session:
            after = (await session.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
            scope = (
                await session.execute(
                    sa.text("SELECT current_setting('app.workspace_scope', true)")
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    assert after == before, "a second connection was used, so this proves nothing"
    assert scope in (None, ""), f"the next transaction inherited app.workspace_scope={scope!r}"


async def test_offboarding_exports_and_purges_the_role_tables_and_the_version_row_stays_gone(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """tenant-rbac R4.2: roles, their privileges, assignments and the access
    version row are exported, then purged; the version row's step may run
    before the assignments go, and their deletes bring no row back. The role
    and its assignment are planted as the migrator: as `dw_app` each is a
    widening write only a confirmed proposal opens (tenant-rbac ticket 03)."""
    mine, theirs = _new_tenant(), _new_tenant()
    for t in (mine, theirs):
        await _seed_tenant(sessions, t)
        member = await _seed_member(sessions, t)
        async with migrator.begin() as session:
            role = await session.scalar(
                sa.text("SELECT platform.install_role_template(:t, 'approver')"),
                {"t": t.tenant_id},
            )
            await session.execute(
                sa.text(
                    "INSERT INTO platform.role_assignments"
                    " (id, tenant_id, workspace_id, membership_id, role_id)"
                    " SELECT gen_random_uuid(), m.tenant_id, m.workspace_id, m.id, :r"
                    " FROM platform.memberships m WHERE m.user_id = :u"
                ),
                {"r": role, "u": member},
            )
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    tables = (
        "tenant_roles",
        "tenant_role_permissions",
        "role_assignments",
        "tenant_access_versions",
    )

    exported = {
        (t.schema, t.table): t.rows for t in await _collect(offboarding.export_rows(mine.tenant_id))
    }
    for table in tables:
        assert exported.get(("platform", table)), f"{table} is not in the export"

    await offboarding.purge_rows(mine.tenant_id)

    for table in tables:
        assert await _count(sessions, mine.tenant_id, "platform", table) == 0, table
        assert await _count(sessions, theirs.tenant_id, "platform", table) >= 1, table


# ---------------------------------------------------------------------------
# Studio's artifact envelope (tenant-config ticket 02, R3.6, TC21): two
# artifacts of one company, one using the other across its two workspaces,
# purged by the default steps in the order the catalog's keys give.
# ---------------------------------------------------------------------------

_PROBE_KIND = "offboarding_probe"
_HASH = "sha256:" + "d" * 64


async def _seed_studio(
    sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, status: str
) -> None:
    ws1, ws2 = uuid.uuid4(), uuid.uuid4()
    used, user = uuid.uuid4(), uuid.uuid4()
    used_v1, user_v1 = uuid.uuid4(), uuid.uuid4()
    parent_run = uuid.uuid4()
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        statements: list[tuple[str, dict[str, object]]] = [
            (
                "INSERT INTO platform.tenants (id, slug, name, status) VALUES (:t, :s, :s, :st)",
                {"t": tenant_id, "s": f"st-{tenant_id.hex[-10:]}", "st": status},
            ),
            *(
                (
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:w, :t, :s, :s)",
                    {"w": w, "t": tenant_id, "s": slug},
                )
                for w, slug in ((ws1, "main"), (ws2, "ws2"))
            ),
            *(
                (
                    "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name,"
                    " owning_workspace_id, row_version, last_version_no)"
                    " VALUES (:a, :t, :k, :n, :w, 1, 1)",
                    {"a": a, "t": tenant_id, "k": _PROBE_KIND, "n": n, "w": w},
                )
                for a, n, w in ((used, "used_one", ws1), (user, "user_one", ws2))
            ),
            *(
                (
                    # Inserted as a sealed draft, the one stage a row starts in
                    # (agent-lifecycle R1.1); the purge order does not read it.
                    "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
                    " version_no, document_schema, document, content_hash, definition_hash,"
                    " row_version, contributor_ids) VALUES (:v, :t, :a, 'draft', 1,"
                    " 'dw.probe/v1', '{}', :h, :h, 1, ARRAY[gen_random_uuid()])",
                    {"v": v, "t": tenant_id, "a": a, "h": _HASH},
                )
                for v, a in ((used_v1, used), (user_v1, user))
            ),
            (
                "INSERT INTO studio.dependencies (id, tenant_id, from_artifact_id,"
                " from_version_id, to_kind, to_key, to_version, to_hash, to_artifact_id,"
                " to_version_id, usage, path) VALUES (:id, :t, :fa, :fv, 'artifact', :key, 1,"
                " :h, :ta, :tv, 'read', '/uses/0')",
                {
                    "id": uuid.uuid4(),
                    "t": tenant_id,
                    "fa": user,
                    "fv": user_v1,
                    "key": str(used),
                    "h": _HASH,
                    "ta": used,
                    "tv": used_v1,
                },
            ),
            (
                "INSERT INTO studio.definition_manifests (tenant_id, hash, body)"
                " VALUES (:t, :h, '{}')",
                {"t": tenant_id, "h": _HASH},
            ),
            # A run pinning both versions through its manifest (ticket 04).
            (
                "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
                ' VALUES (:t, :h, \'{"run_mode": "live"}\')',
                {"t": tenant_id, "h": _HASH},
            ),
            *(
                (
                    "INSERT INTO platform.run_manifest_keys"
                    " (id, tenant_id, manifest_hash, artifact_version_id) VALUES (:id, :t, :h, :v)",
                    {"id": uuid.uuid4(), "t": tenant_id, "h": _HASH, "v": v},
                )
                for v in (user_v1, used_v1)
            ),
            (
                "INSERT INTO platform.worker_runs (run_mode, id, thread_id, tenant_id,"
                " workspace_id, worker_id, worker_version, graph_version, requested_by,"
                " run_manifest_hash) VALUES ('live', :r, :r, :t, :w, 'studio', '1', '1',"
                " gen_random_uuid(), :h)",
                {"r": uuid.uuid4(), "t": tenant_id, "w": ws2, "h": _HASH},
            ),
            # A Studio run naming its version, and its child (workflow-engine
            # 02): both RESTRICT keys, purged by the one delete of the step.
            *(
                (
                    "INSERT INTO platform.worker_runs (run_mode, id, thread_id, tenant_id,"
                    " workspace_id, worker_id, worker_version, graph_version, requested_by,"
                    " run_manifest_hash, artifact_kind, artifact_id, artifact_version_id,"
                    " trigger_kind, run_as_principal_id, request_key, definition_hash,"
                    " parent_run_id, root_run_id, chain_depth)"
                    " VALUES ('live', :r, :r, :t, :w, 'studio', '1', :h, gen_random_uuid(),"
                    " :h, :k, :a, :v, 'manual', gen_random_uuid(), :key, :h,"
                    " CAST(:p AS uuid), COALESCE(CAST(:p AS uuid), CAST(:r AS uuid)), :d)",
                    {
                        "r": run,
                        "t": tenant_id,
                        "w": ws2,
                        "h": _HASH,
                        "k": _PROBE_KIND,
                        "a": user,
                        "v": user_v1,
                        "key": f"manual:{run}",
                        "p": parent,
                        "d": depth,
                    },
                )
                for run, parent, depth in (
                    (parent_run, None, 0),
                    (uuid.uuid4(), parent_run, 1),
                )
            ),
        ]
        for statement, values in statements:
            await session.execute(sa.text(statement), values)


_STUDIO_TABLES = ("dependencies", "definition_manifests", "artifact_versions", "artifacts")
_RUN_TABLES = ("worker_runs", "run_manifests", "run_manifest_keys")


async def test_offboarding_purges_studio_artifacts_that_use_each_other(
    sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    try:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.artifact_kinds (kind, has_quality_gate)"
                    " VALUES (:k, false) ON CONFLICT DO NOTHING"
                ),
                {"k": _PROBE_KIND},
            )
        await _seed_studio(sessions, mine, "offboarding")
        await _seed_studio(sessions, theirs, "active")
        offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
        async with sessions() as session, session.begin():
            order = await offboarding.purge_order(session)
        position = {name: order.index(f"studio.{name}") for name in _STUDIO_TABLES}
        assert position["dependencies"] < position["artifact_versions"] < position["artifacts"]
        assert order.index("studio.artifacts") < order.index("platform.workspaces")
        # Ticket 04 (R3.6): from the catalog's RESTRICT keys, not by CASCADE.
        assert order.index("platform.run_manifest_keys") < position["artifact_versions"]
        assert order.index("platform.worker_runs") < order.index("platform.run_manifests")
        # workflow-engine 02: a run names its version by a RESTRICT key.
        assert order.index("platform.worker_runs") < position["artifact_versions"]

        await offboarding.purge_rows(mine)

        for table in _STUDIO_TABLES:
            assert await _count(sessions, mine, "studio", table) == 0, table
            assert await _count(sessions, theirs, "studio", table) >= 1, table
        for table in _RUN_TABLES:
            assert await _count(sessions, mine, "platform", table) == 0, table
            assert await _count(sessions, theirs, "platform", table) >= 1, table
    finally:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
                {"t": theirs},
            )
        await SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES).purge_rows(
            theirs
        )
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM studio.artifact_kinds WHERE kind = :k"), {"k": _PROBE_KIND}
            )
        await migrator.dispose()


async def test_a_runs_pinned_versions_are_purged_by_the_catalogs_key_not_by_name(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Ticket 04 (R3.6, TC21): `platform.run_manifest_keys` sorts before
    `studio.artifact_versions` by name alone, so the purge test above cannot
    tell the key from the alphabet. Named the other way round here, only the
    catalog's `fk_run_manifest_keys_artifact_version_id_artifact_versions`, read
    by the lane's own query, puts the keys first."""

    async def nothing(_session: AsyncSession, _tenant: uuid.UUID) -> None:
        return None

    keys = OffboardingPurgeStep("z_keys", frozenset({"platform.run_manifest_keys"}), nothing)
    versions = OffboardingPurgeStep("a_versions", frozenset({"studio.artifact_versions"}), nothing)
    async with sessions() as session, session.begin():
        foreign_keys = (await session.execute(_FOREIGN_KEYS)).all()

    assert [step.name for step in order_purge_steps([versions, keys], foreign_keys)] == [
        "z_keys",
        "a_versions",
    ]


async def test_a_studio_run_is_purged_before_its_version_by_the_catalogs_key(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """workflow-engine 02 (R3.1): named so that name order puts the versions
    first, only `fk_worker_runs_artifact_version_id_artifact_versions`, read
    from the catalog, puts the runs before them; without that edge the order
    turns round, so the step list holds no copy of it."""

    async def nothing(_session: AsyncSession, _tenant: uuid.UUID) -> None:
        return None

    runs = OffboardingPurgeStep("z_runs", frozenset({"platform.worker_runs"}), nothing)
    versions = OffboardingPurgeStep("a_versions", frozenset({"studio.artifact_versions"}), nothing)
    async with sessions() as session, session.begin():
        foreign_keys = (await session.execute(_FOREIGN_KEYS)).all()
    edge = "fk_worker_runs_artifact_version_id_artifact_versions"
    assert edge in {fk.conname for fk in foreign_keys}

    def order(keys: list[object]) -> list[str]:
        return [step.name for step in order_purge_steps([versions, runs], keys)]

    assert order(list(foreign_keys)) == ["z_runs", "a_versions"]
    assert order([fk for fk in foreign_keys if fk.conname != edge]) == ["a_versions", "z_runs"]


# ---- org-and-principals 03: the tenant's service users (R6.8) ------------------

# A table holding a service user by RESTRICT, as a later context's might. Named
# to sort AFTER the step `platform.purge_tenant_service_users`: only the
# catalog's edge can put the step behind it.
_HOLDER = "platform.zz_service_user_holder"


async def _seed_service_tenant(migrator: AsyncEngine) -> dict[str, uuid.UUID]:
    """An `active` tenant, then `offboarding`, holding a person, a service
    account, a Digital Worker (whose principal is a service user too) and a
    support grant."""
    ids = {name: uuid.uuid4() for name in ("tenant", "ws", "person", "account", "dw", "principal")}
    statements: tuple[tuple[str, dict[str, object]], ...] = (
        (
            "INSERT INTO platform.tenants (id, slug, name, status) VALUES (:tenant, :slug, :slug,"
            " 'active')",
            {"slug": f"sp-off-{ids['tenant'].hex[:10]}"},
        ),
        (
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
            " VALUES (:ws, :tenant, 'main', 'Main')",
            {},
        ),
        (
            "INSERT INTO platform.users (id, subject, display_name)"
            " VALUES (:person, 'sp-off-' || CAST(:person AS uuid)::text, 'người')",
            {},
        ),
        (
            "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
            " VALUES (:tenant, :person, 'active')",
            {},
        ),
        (
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
            " VALUES (gen_random_uuid(), :tenant, :ws, :person)",
            {},
        ),
    )
    async with migrator.begin() as conn:
        for sql, extra in statements:
            await conn.execute(sa.text(sql), {**ids, **extra})
        for user in ("account", "principal"):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, display_name, kind,"
                    " owner_tenant_id)"
                    " VALUES (:u, 'service:' || CAST(:u AS uuid)::text, 'svc', 'service', :tenant)"
                ),
                {"u": ids[user], "tenant": ids["tenant"]},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
                    " VALUES (:tenant, :u, 'active')"
                ),
                {"u": ids[user], "tenant": ids["tenant"]},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.service_principals"
                    " (user_id, tenant_id, owning_workspace_id, name, owner_user_id)"
                    " VALUES (:u, :tenant, :ws, :n, :person)"
                ),
                {**ids, "u": ids[user], "n": f"svc {user}"},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
                    " VALUES (gen_random_uuid(), :tenant, :ws, :u)"
                ),
                {**ids, "u": ids[user]},
            )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
                " principal_user_id, key, name, mandate, work_kinds, allowed_tools,"
                " workflow_key, workflow_version, technical_owner_id, work_assigner_id,"
                " validator_id, created_by) VALUES (:dw, :tenant, :ws, :principal, 'off_dw',"
                " 'dw', 'dw', ARRAY['lead'], ARRAY[]::text[], 'wf', '1.0.0', :person, :person,"
                " :person, :person)"
            ),
            ids,
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.support_grants (id, tenant_id, workspace_id,"
                " resource_type, resource_label, scope_set_key, scope_set_label, scopes, reason,"
                " duration_hours, status, requested_by)"
                " VALUES (gen_random_uuid(), :tenant, :ws, 'workspace', 'W', 'k', 'K',"
                " ARRAY['x.read'], 'r', 72, 'pending_approval', :person)"
            ),
            ids,
        )
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :tenant"), ids
        )
    return ids


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def service_user_holder(migrator: AsyncEngine) -> AsyncIterator[str]:
    """Committed, so the purge's own transaction sees it; dropped after."""
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"CREATE TABLE {_HOLDER} ("
                " id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
                " user_id uuid NOT NULL REFERENCES platform.users (id) ON DELETE RESTRICT)"
            )
        )
        await conn.execute(sa.text(f"ALTER TABLE {_HOLDER} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(sa.text(f"ALTER TABLE {_HOLDER} FORCE ROW LEVEL SECURITY"))
        await conn.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation_zz_service_user_holder ON {_HOLDER}"
                " USING (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true),"
                " '')::uuid))"
            )
        )
        await conn.execute(sa.text(f"GRANT SELECT, DELETE ON {_HOLDER} TO dw_app"))
    try:
        yield _HOLDER
    finally:
        async with migrator.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {_HOLDER}"))


async def test_offboarding_deletes_the_tenants_service_users_after_what_holds_them(
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    service_user_holder: str,
) -> None:
    """org-and-principals R6.8 (OP14): after the purge no service user of the
    tenant is left and no `platform.service_principals` row; its person and
    another tenant's service account stay. The step runs after the delete of a
    table holding a service user by RESTRICT (ordered by the catalog alone), and
    a support grant of the tenant blocks nothing."""
    mine = await _seed_service_tenant(migrator)
    theirs = await _seed_service_tenant(migrator)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(f"INSERT INTO {service_user_holder} VALUES (gen_random_uuid(), :t, :u)"),
            {"t": mine["tenant"], "u": mine["account"]},
        )

    statements: list[str] = []

    def seen(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    engine = sessions.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", seen)
    try:
        await SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES).purge_rows(
            mine["tenant"]
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", seen)

    holder_delete = next(
        i for i, s in enumerate(statements) if "DELETE FROM" in s and "zz_service_user_holder" in s
    )
    purge = next(i for i, s in enumerate(statements) if "purge_tenant_service_users" in s)
    assert holder_delete < purge

    async with migrator.connect() as conn:

        async def count(sql: str, **values: object) -> int:
            return int((await conn.execute(sa.text(sql), values)).scalar_one())

        services = (
            "SELECT count(*) FROM platform.users WHERE kind = 'service' AND owner_tenant_id = :t"
        )
        principals = "SELECT count(*) FROM platform.service_principals WHERE tenant_id = :t"
        assert await count(services, t=mine["tenant"]) == 0
        assert await count(principals, t=mine["tenant"]) == 0
        assert (
            await count("SELECT count(*) FROM platform.users WHERE id = :u", u=mine["person"]) == 1
        )
        assert await count(services, t=theirs["tenant"]) == 2
        assert await count(principals, t=theirs["tenant"]) == 2


# ---------------------------------------------------------------------------
# agent-lifecycle ticket 01 (R10.1): a company leaving the platform takes its
# switches with it, an open kill and a lifted freeze alike, exported once and
# deleted by the default step, which the switch trigger allows only while
# the company is `offboarding`; the other company's stay.
# ---------------------------------------------------------------------------


async def _seed_switches(sessions: async_sessionmaker[AsyncSession], t: _Tenant) -> None:
    asker, decider = await _seed_member(sessions, t), await _seed_member(sessions, t)
    freeze, approval = uuid.uuid4(), uuid.uuid4()
    async with sessions() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)}
        )
        for statement, values in (
            (
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type,"
                " owning_workspace_id, target_id, action, origin, reason_code, reason, set_by)"
                " VALUES (gen_random_uuid(), :t, 'agent', :w, gen_random_uuid(), 'kill',"
                " 'tenant', 'abuse', 'x', :u)",
                {"t": t.tenant_id, "w": t.workspace_id, "u": asker},
            ),
            (
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                " origin, reason_code, reason, set_by)"
                " VALUES (:f, :t, 'tenant', 'freeze', 'tenant', 'incident', 'x', :u)",
                {"f": freeze, "t": t.tenant_id, "u": asker},
            ),
            (
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, payload, status)"
                " VALUES (:a, :t, :w, 'studio.lifecycle.unfreeze', :u,"
                " jsonb_build_object('switch_id', CAST(:f AS text)), 'approved')",
                {
                    "a": approval,
                    "t": t.tenant_id,
                    "w": t.workspace_id,
                    "u": asker,
                    "f": str(freeze),
                },
            ),
            (
                "INSERT INTO platform.approval_decisions (id, request_id, tenant_id,"
                " workspace_id, decided_by, outcome, decided_at)"
                " VALUES (gen_random_uuid(), :a, :t, :w, :d, 'approved', now())",
                {"a": approval, "t": t.tenant_id, "w": t.workspace_id, "d": decider},
            ),
            (
                "UPDATE platform.control_switches SET lifted_at = now(), lifted_by = :d,"
                " lift_approval_id = :a WHERE id = :f",
                {"d": decider, "a": approval, "f": freeze},
            ),
        ):
            await session.execute(sa.text(statement), values)


async def test_offboarding_exports_and_deletes_the_companys_switches(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R10.1: both rows exported once, then deleted before the approval the
    lifted one names (the RESTRICT key orders the steps); the other company's
    are untouched."""
    mine, theirs = _new_tenant(), _new_tenant()
    for t in (mine, theirs):
        await _seed_tenant(sessions, t)
        await _seed_switches(sessions, t)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    exported = [
        t
        for t in await _collect(offboarding.export_rows(mine.tenant_id))
        if (t.schema, t.table) == ("platform", "control_switches")
    ]
    assert len(exported) == 1
    assert sorted(r["action"] for r in exported[0].rows) == ["freeze", "kill"]

    await offboarding.purge_rows(mine.tenant_id)

    assert await _count(sessions, mine.tenant_id, "platform", "control_switches") == 0
    assert await _count(sessions, theirs.tenant_id, "platform", "control_switches") == 2
    assert "platform.control_switches" not in STUDIO_EXCLUSIONS
