"""Offboarding reaches the append-only tables through one function, for the
leaving company only, in the order the catalog's foreign keys demand
(usage-and-limits R3.8-R3.11; UL16).

`platform.purge_tenant_append_only` is called as `dw_app`, the role the lane
connects as. The probe tables planted below stand for a Studio append-only table
holding a RESTRICT key to an ordinary one (agent-builder's messages and
conversations): they are registered in `platform.time_partitioned_tables` the
way a migration would, and the step finds them with no line of code changed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_offboarding_coverage import _PLATFORM_PREDATING, offboarding_violations
from test_usage_ledger_db import event, rows_of, seed_tenant

from dw_platform.adapters.persistence.marketing_send_repo import marketing_purge_step
from dw_platform.adapters.persistence.offboarding import (
    APPEND_ONLY_STEP,
    EXPORT_EXCLUSIONS,
    STUDIO_EXCLUSIONS,
    ExportedTable,
    OffboardingPurgeStep,
    OffboardingPurgeSteps,
    OffboardingRefusedError,
    SqlTenantOffboarding,
    access_version_purge_step,
    append_only_purge_step,
    service_users_purge_step,
)
from dw_platform.retention_policy import load_retention_policy
from dw_usage.adapters.sql import SqlUsageLedger

pytestmark = pytest.mark.integration

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")
_PURGE = sa.text(
    "SELECT table_name, deleted FROM platform.purge_tenant_append_only(CAST(:t AS uuid),"
    " CAST(:tables AS text[]))"
)
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_FK = "fk_ul_probe_messages_thread_id_ul_probe_threads"
_THREADS, _MESSAGES = "studio.ul_probe_threads", "studio.ul_probe_messages"

_PROBE_DDL = (
    f"CREATE TABLE {_THREADS} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
    f"ALTER TABLE {_THREADS} ENABLE ROW LEVEL SECURITY",
    f"ALTER TABLE {_THREADS} FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY tenant_isolation_ul_probe_threads ON {_THREADS}"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    f"GRANT SELECT, INSERT, DELETE ON {_THREADS} TO dw_app",
    f"CREATE TABLE {_MESSAGES} (id uuid NOT NULL, at timestamptz NOT NULL,"
    " tenant_id uuid NOT NULL, thread_id uuid NOT NULL,"
    " CONSTRAINT pk_ul_probe_messages PRIMARY KEY (id, at),"
    f" CONSTRAINT {_FK} FOREIGN KEY (thread_id) REFERENCES {_THREADS} (id) ON DELETE RESTRICT)"
    " PARTITION BY RANGE (at)",
    f"CREATE TABLE {_MESSAGES}_default PARTITION OF {_MESSAGES} DEFAULT",
    f"ALTER TABLE {_MESSAGES} ENABLE ROW LEVEL SECURITY",
    f"ALTER TABLE {_MESSAGES} FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY tenant_isolation_ul_probe_messages ON {_MESSAGES}"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    f"ALTER TABLE {_MESSAGES}_default ENABLE ROW LEVEL SECURITY",
    f"ALTER TABLE {_MESSAGES}_default FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY tenant_isolation_ul_probe_messages_default ON {_MESSAGES}_default"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    f"REVOKE ALL ON {_MESSAGES} FROM dw_app",
    f"GRANT SELECT, INSERT ON {_MESSAGES} TO dw_app",
    f"SELECT platform._revoke_all_but_owner('{_MESSAGES}_default'::regclass)",
    "INSERT INTO platform.time_partitioned_tables (schema_name, table_name, append_only,"
    " registered_by) VALUES ('studio', 'ul_probe_messages', true, 'usage-and-limits test')",
)


@pytest.fixture
async def probe(migrator: AsyncEngine) -> AsyncIterator[None]:
    """The planted pair, committed: the lane runs its own transactions."""
    async with migrator.begin() as conn:
        for statement in _PROBE_DDL:
            await conn.execute(sa.text(statement))
    try:
        yield
    finally:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "DELETE FROM platform.time_partitioned_tables"
                    " WHERE schema_name = 'studio' AND table_name = 'ul_probe_messages'"
                )
            )
            await conn.execute(sa.text(f"DROP TABLE {_MESSAGES}"))
            await conn.execute(sa.text(f"DROP TABLE {_THREADS}"))


async def _plant_thread(sessions: async_sessionmaker[AsyncSession], tenant: uuid.UUID) -> None:
    thread = uuid.uuid4()
    async with sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        await session.execute(
            sa.text(f"INSERT INTO {_THREADS} (id, tenant_id) VALUES (:id, :t)"),  # nosec B608
            {"id": thread, "t": tenant},
        )
        await session.execute(
            sa.text(  # nosec B608
                f"INSERT INTO {_MESSAGES} (id, at, tenant_id, thread_id)"
                " VALUES (gen_random_uuid(), now(), :t, :th)"
            ),
            {"t": tenant, "th": thread},
        )


async def _plant_audit(
    sessions: async_sessionmaker[AsyncSession], tenant: uuid.UUID, ws: uuid.UUID
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        await session.execute(
            sa.text(
                "INSERT INTO platform.audit_events (id, tenant_id, workspace_id, actor_id,"
                " action, resource_type, resource_id, details, occurred_at)"
                " VALUES (gen_random_uuid(), :t, :w, gen_random_uuid(), 'probe.kept', 'probe',"
                " 'x', '{}', now())"
            ),
            {"t": tenant, "w": ws},
        )


async def _call(
    sessions: async_sessionmaker[AsyncSession],
    *,
    as_tenant: uuid.UUID,
    for_tenant: uuid.UUID,
    tables: list[str],
) -> dict[str, int]:
    async with sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(as_tenant)})
        rows = await session.execute(_PURGE, {"t": str(for_tenant), "tables": tables})
        return {row.table_name: row.deleted for row in rows}


# ---- R3.9 (UL16) -------------------------------------------------------------


async def test_an_active_company_is_refused_and_keeps_every_row(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    tenant, _ = await seed_tenant(app_sessions, status="active")
    await SqlUsageLedger(app_sessions).settle(event(tenant))
    with pytest.raises(sa.exc.IntegrityError, match="only for a tenant offboarding") as raised:
        await _call(
            app_sessions, as_tenant=tenant, for_tenant=tenant, tables=["platform.usage_events"]
        )
    assert getattr(raised.value.orig, "sqlstate", None) == "23514"
    assert len(await rows_of(app_sessions, tenant, "platform.usage_events")) == 1


async def test_one_company_cannot_purge_another_offboarding_one(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    a, _ = await seed_tenant(app_sessions, status="active")
    b, _ = await seed_tenant(app_sessions, status="offboarding")
    await SqlUsageLedger(app_sessions).settle(event(b))
    with pytest.raises(sa.exc.IntegrityError, match="transaction's own tenant"):
        await _call(app_sessions, as_tenant=a, for_tenant=b, tables=["platform.usage_events"])
    assert len(await rows_of(app_sessions, b, "platform.usage_events")) == 1


@pytest.mark.parametrize("table", ["platform.audit_events", "platform.workspaces", "nope.nothing"])
async def test_a_table_outside_the_append_only_set_is_refused(
    app_sessions: async_sessionmaker[AsyncSession], table: str
) -> None:
    """R3.10: the audit log and an ordinary table are not this function's,
    and naming one refuses the whole call, the ledger included."""
    tenant, [ws] = await seed_tenant(app_sessions, status="offboarding")
    await SqlUsageLedger(app_sessions).settle(event(tenant))
    await _plant_audit(app_sessions, tenant, ws)
    with pytest.raises(sa.exc.IntegrityError, match="registered append-only tables"):
        await _call(
            app_sessions,
            as_tenant=tenant,
            for_tenant=tenant,
            tables=["platform.usage_events", table],
        )
    assert len(await rows_of(app_sessions, tenant, "platform.usage_events")) == 1
    assert len(await rows_of(app_sessions, tenant, "platform.audit_events")) == 1


# ---- R3.10 -------------------------------------------------------------------


async def test_the_function_deletes_the_company_s_rows_in_every_table_named(
    app_sessions: async_sessionmaker[AsyncSession], probe: None
) -> None:
    leaving, [ws] = await seed_tenant(app_sessions, status="offboarding")
    staying, _ = await seed_tenant(app_sessions, status="active")
    ledger = SqlUsageLedger(app_sessions)
    for tenant in (leaving, staying):
        await ledger.settle(event(tenant))
        await _plant_thread(app_sessions, tenant)
    await _plant_audit(app_sessions, leaving, ws)

    deleted = await _call(
        app_sessions,
        as_tenant=leaving,
        for_tenant=leaving,
        tables=["platform.usage_events", _MESSAGES],
    )

    assert deleted == {"platform.usage_events": 1, _MESSAGES: 1}
    assert await rows_of(app_sessions, leaving, "platform.usage_events") == []
    assert await rows_of(app_sessions, leaving, _MESSAGES) == []
    assert len(await rows_of(app_sessions, staying, "platform.usage_events")) == 1
    assert len(await rows_of(app_sessions, staying, _MESSAGES)) == 1
    assert len(await rows_of(app_sessions, leaving, "platform.audit_events")) == 1


async def test_the_step_takes_every_append_only_table_no_other_step_declares(
    app_sessions: async_sessionmaker[AsyncSession], probe: None
) -> None:
    """The worker's registry holds this step and `purge_tenant_marketing`; the
    step's tables, read at the pass, are the registry's minus the marketing
    step's and never the audit log (R3.10, foundations-hardening R11.8)."""
    from dw_worker.main import build_purge_steps

    steps = build_purge_steps().all()
    names = {step.name for step in steps}
    assert {APPEND_ONLY_STEP, "platform.purge_tenant_marketing"} <= names
    fixed = frozenset(t for step in steps if step.resolve is None for t in step.tables)
    [resolving] = [step for step in steps if step.resolve is not None]
    async with app_sessions() as session, session.begin():
        assert resolving.resolve is not None
        resolved = await resolving.resolve(session, fixed)
    assert resolved.tables == {"platform.usage_events", _MESSAGES}
    assert not resolved.tables & {
        "platform.consent_records",
        "platform.marketing_send_log",
        "platform.audit_events",
    }


# ---- R3.8, R3.11 -------------------------------------------------------------


async def _collect(offboarding: SqlTenantOffboarding, tenant: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    batch: ExportedTable
    async for batch in offboarding.export_rows(tenant):
        key = f"{batch.schema}.{batch.table}"
        counts[key] = counts.get(key, 0) + len(batch.rows)
    return counts


async def _plant_daily(sessions: async_sessionmaker[AsyncSession], tenant: uuid.UUID) -> None:
    async with sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        await session.execute(
            sa.text(
                "INSERT INTO platform.usage_daily (tenant_id, workspace_id, day, provider,"
                " model, operation, purpose, payer, calls, input_tokens, output_tokens,"
                " cache_read_tokens, cache_write_tokens, reasoning_tokens, cost_usd,"
                " unpriced_calls, estimated_calls, rolled_up_at) VALUES (:t, NULL,"
                " '2026-11-03', 'p', 'm', 'chat', 'run', 'platform', 2, 1, 1, 0, 0, 0, 1, 0,"
                " 0, now())"
            ),
            {"t": tenant},
        )


async def test_offboarding_exports_each_row_once_then_purges_both_tables(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R3.8: the lane's export carries every ledger and roll-up row once; its
    purge empties both for the leaving company and no other."""
    leaving, _ = await seed_tenant(app_sessions, status="offboarding")
    staying, _ = await seed_tenant(app_sessions)
    ledger = SqlUsageLedger(app_sessions)
    for tenant in (leaving, staying):
        for _ in range(3):
            await ledger.settle(event(tenant, occurred_at=datetime.now(UTC)))
        await _plant_daily(app_sessions, tenant)
    lane = SqlTenantOffboarding(session_factory=app_sessions)

    exported = await _collect(lane, leaving)
    assert exported["platform.usage_events"] == 3
    assert exported["platform.usage_daily"] == 1

    await lane.purge_rows(leaving)

    for table in ("platform.usage_events", "platform.usage_daily"):
        assert await rows_of(app_sessions, leaving, table) == []
        assert len(await rows_of(app_sessions, staying, table)) == (
            3 if table == "platform.usage_events" else 1
        )


async def test_without_the_step_the_ledger_outlives_the_company(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R3.8, the step's negative: a registry without it leaves the rows."""
    leaving, _ = await seed_tenant(app_sessions, status="offboarding")
    await SqlUsageLedger(app_sessions).settle(event(leaving))
    without = OffboardingPurgeSteps()
    for step in (marketing_purge_step(), access_version_purge_step(), service_users_purge_step()):
        without.register(step)

    await SqlTenantOffboarding(session_factory=app_sessions, steps=without).purge_rows(leaving)

    assert len(await rows_of(app_sessions, leaving, "platform.usage_events")) == 1


async def test_an_append_only_child_is_purged_before_its_ordinary_parent(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine, probe: None
) -> None:
    """R3.11: the step's tables come from the registry, so the RESTRICT key of
    the planted child orders the step before the parent's own, and one pass
    empties both; the coverage check of studio-skeleton R4.2 finds nothing."""
    leaving, _ = await seed_tenant(app_sessions, status="offboarding")
    await _plant_thread(app_sessions, leaving)
    lane = SqlTenantOffboarding(session_factory=app_sessions)
    async with app_sessions() as session, session.begin():
        order = await lane.purge_order(session)
    assert order.index(APPEND_ONLY_STEP) < order.index(_THREADS)

    await lane.purge_rows(leaving)

    assert await rows_of(app_sessions, leaving, _MESSAGES) == []
    assert await rows_of(app_sessions, leaving, _THREADS) == []
    async with migrator.connect() as conn:
        found = await offboarding_violations(
            conn,
            STUDIO_EXCLUSIONS,
            EXPORT_EXCLUSIONS,
            _PLATFORM_PREDATING,
            load_retention_policy().term,
        )
    assert [line for line in found if "ul_probe" in line] == []


async def test_a_hand_written_table_list_leaves_the_child_and_deletes_nothing(
    app_sessions: async_sessionmaker[AsyncSession], probe: None
) -> None:
    """R3.11's negative: the step with a hand-written list that omits the
    planted child no longer orders before the parent, and the pass refuses
    before its first delete, naming the key, so nothing is lost half-way."""
    leaving, _ = await seed_tenant(app_sessions, status="offboarding")
    await _plant_thread(app_sessions, leaving)
    await SqlUsageLedger(app_sessions).settle(event(leaving))

    async def run(session: AsyncSession, tenant_id: uuid.UUID) -> None:
        await session.execute(_PURGE, {"t": str(tenant_id), "tables": ["platform.usage_events"]})

    hand_written = OffboardingPurgeSteps()
    for step in (marketing_purge_step(), access_version_purge_step(), service_users_purge_step()):
        hand_written.register(step)
    hand_written.register(
        OffboardingPurgeStep(
            name=APPEND_ONLY_STEP, tables=frozenset({"platform.usage_events"}), run=run
        )
    )
    lane = SqlTenantOffboarding(session_factory=app_sessions, steps=hand_written)
    async with app_sessions() as session, session.begin():
        order = await lane.purge_order(session)
    assert _MESSAGES not in order

    with pytest.raises(OffboardingRefusedError, match=_FK):
        await lane.purge_rows(leaving)

    assert len(await rows_of(app_sessions, leaving, _MESSAGES)) == 1
    assert len(await rows_of(app_sessions, leaving, _THREADS)) == 1
    assert len(await rows_of(app_sessions, leaving, "platform.usage_events")) == 1


async def test_the_resolving_step_refuses_to_run_unresolved() -> None:
    step = append_only_purge_step()
    with pytest.raises(OffboardingRefusedError, match="resolved"):
        await step.run(None, uuid.uuid4())  # type: ignore[arg-type]
