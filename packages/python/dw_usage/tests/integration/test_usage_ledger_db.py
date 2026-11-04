"""The usage ledger and its roll-up against real Postgres (usage-and-limits
R2.4, R3.1, R3.2, R3.4-R3.7; UL7, UL12).

Every write and read is as `dw_app`, the role the application connects as; the
migrator plants only what `dw_app` may not (a partition through the lane's own
function).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dw_kernel.ports import FixedClock
from dw_usage.adapters.sql import (
    SqlTenantTimezones,
    SqlUsageLedger,
    SqlUsageReads,
    SqlUsageRollupStore,
)
from dw_usage.application.calendar import UsageCalendar
from dw_usage.application.ports import SummaryFilter
from dw_usage.application.rollup import UsageRollup
from dw_usage.domain.events import UsageEvent

pytestmark = pytest.mark.integration

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")


async def seed_tenant(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: str = "active",
    timezone: str | None = None,
    workspaces: int = 1,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    tenant, spaces = uuid.uuid4(), [uuid.uuid4() for _ in range(workspaces)]
    async with sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        await session.execute(
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status, timezone)"
                " VALUES (:t, :s, :s, :status, :tz)"
            ),
            {"t": tenant, "s": f"ul-{tenant.hex[:12]}", "status": status, "tz": timezone},
        )
        for n, ws in enumerate(spaces):
            await session.execute(
                sa.text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:w, :t, :s, :s)"
                ),
                {"w": ws, "t": tenant, "s": f"ws{n}"},
            )
    return tenant, spaces


def event(tenant: uuid.UUID, **overrides: Any) -> UsageEvent:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "occurred_at": datetime(2026, 11, 3, 10, tzinfo=UTC),
        "tenant_id": tenant,
        "operation": "chat",
        "purpose": "run",
        "payer": "platform",
        "actor_kind": "user",
        "provider": "openai_compatible",
        "model": "gpt-4.1",
        "input_tokens": 1000,
        "output_tokens": 100,
        "cost_source": "computed",
        "price_book_version": "1.0.0",
        "cost_usd": Decimal("0.00280000"),
        "price_entry_ids": ("openai_compatible/gpt-4.1/input_uncached/0@x",),
        "units": {"input_uncached": 1000, "output": 100},
    }
    return UsageEvent(**{**fields, **overrides})


async def rows_of(
    sessions: async_sessionmaker[AsyncSession], tenant: uuid.UUID, table: str
) -> list[Any]:
    async with sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        return list((await session.execute(sa.text(f"SELECT * FROM {table}"))).all())  # nosec B608


# ---- R3.1, R3.2 ------------------------------------------------------------


async def test_a_record_is_stored_with_its_route_and_settled_once(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    tenant, [ws] = await seed_tenant(app_sessions)
    ledger = SqlUsageLedger(app_sessions)
    one = event(
        tenant,
        workspace_id=ws,
        run_id=uuid.uuid4(),
        data_route_class="cross_border_minimised",
        data_location="foreign",
        processor="openai",
    )

    assert await ledger.settle(one) is True
    assert await ledger.settle(one) is False  # R3.2: the same (id, occurred_at)

    [row] = await rows_of(app_sessions, tenant, "platform.usage_events")
    assert (row.data_route_class, row.data_location, row.processor) == (
        "cross_border_minimised",
        "foreign",
        "openai",
    )
    assert row.workspace_id == ws and row.cost_usd == Decimal("0.00280000")
    assert row.units == {"input_uncached": 1000, "output": 100}
    assert row.price_entry_ids == ["openai_compatible/gpt-4.1/input_uncached/0@x"]


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("data_route_class", "vn_maybe"),
        ("data_location", "moon"),
        ("cost_source", "guessed"),
        ("purpose", "fun"),
    ],
)
async def test_the_database_refuses_a_value_outside_its_set(
    app_sessions: async_sessionmaker[AsyncSession], column: str, value: str
) -> None:
    tenant, _ = await seed_tenant(app_sessions)
    values = {
        "data_route_class": "vn_only",
        "data_location": "vn",
        "cost_source": "computed",
        "purpose": "run",
        column: value,
    }
    async with app_sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        with pytest.raises(sa.exc.IntegrityError, match="ck_usage_events_"):
            await session.execute(
                sa.text(
                    "INSERT INTO platform.usage_events (id, occurred_at, tenant_id, actor_kind,"
                    " operation, purpose, payer, provider, model, input_tokens, output_tokens,"
                    " cache_read_tokens, cache_write_tokens, reasoning_tokens, units, cost_usd,"
                    " cost_source, price_book_version, price_entry_ids, data_route_class,"
                    " data_location) VALUES (gen_random_uuid(), now(), :t, 'user', 'chat',"
                    " :purpose, 'platform', 'p', 'm', 1, 1, 0, 0, 0, '{}', 0, :cost_source, '1',"
                    " '{}', :data_route_class, :data_location)"
                ),
                {"t": tenant, **values},
            )


async def test_an_unpriced_record_has_no_cost_and_a_priced_one_must(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    tenant, _ = await seed_tenant(app_sessions)
    async with app_sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(tenant)})
        with pytest.raises(sa.exc.IntegrityError, match="ck_usage_events_cost_when_priced"):
            await session.execute(
                sa.text(
                    "INSERT INTO platform.usage_events (id, occurred_at, tenant_id, actor_kind,"
                    " operation, purpose, payer, provider, model, input_tokens, output_tokens,"
                    " cache_read_tokens, cache_write_tokens, reasoning_tokens, units, cost_usd,"
                    " cost_source, price_book_version, price_entry_ids) VALUES"
                    " (gen_random_uuid(), now(), :t, 'user', 'chat', 'run', 'platform', 'p',"
                    " 'm', 1, 1, 0, 0, 0, '{}', NULL, 'computed', '1', '{}')"
                ),
                {"t": tenant},
            )


async def test_a_new_book_leaves_old_records_as_they_were(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R2.4 (UL12): a record keeps the version and cost it was settled with."""
    tenant, _ = await seed_tenant(app_sessions)
    ledger = SqlUsageLedger(app_sessions)
    await ledger.settle(event(tenant))
    await ledger.settle(event(tenant, price_book_version="1.1.0", cost_usd=Decimal("0.0056")))
    rows = await rows_of(app_sessions, tenant, "platform.usage_events")
    assert sorted((r.price_book_version, r.cost_usd) for r in rows) == [
        ("1.0.0", Decimal("0.00280000")),
        ("1.1.0", Decimal("0.00560000")),
    ]


# ---- R3.4, R3.7: append-only, and partitions only through the parent --------


async def test_dw_app_neither_updates_nor_deletes_through_the_parent(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    tenant, _ = await seed_tenant(app_sessions)
    await SqlUsageLedger(app_sessions).settle(event(tenant))
    for statement in (
        "UPDATE platform.usage_events SET cost_usd = 0",
        "DELETE FROM platform.usage_events",
        "TRUNCATE platform.usage_events",
    ):
        async with app_sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant)})
            with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
                await session.execute(sa.text(statement))
    assert len(await rows_of(app_sessions, tenant, "platform.usage_events")) == 1


async def test_dw_app_reaches_no_partition_by_its_name(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R3.7 (UL7): the DEFAULT and a partition the lane's function made answer
    `permission denied` to every verb."""
    async with migrator.begin() as conn:
        made = await conn.scalar(
            sa.text("SELECT platform._ensure_one_partition('platform', 'usage_events', :m)"),
            {"m": date(2031, 1, 1)},
        )
    lane_made = f"platform.{made or 'usage_events_2031_01'}"
    tenant, _ = await seed_tenant(app_sessions)
    for partition in ("platform.usage_events_default", lane_made):
        for statement in (
            f"SELECT count(*) FROM {partition}",
            f"DELETE FROM {partition}",
            f"UPDATE {partition} SET cost_usd = 0",
        ):
            async with app_sessions() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": str(tenant)})
                with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
                    await session.execute(sa.text(statement))


# ---- R3.6 (UL7): another company reads nothing -------------------------------


async def test_another_company_reads_none_of_the_ledger_or_the_roll_up(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    a, _ = await seed_tenant(app_sessions)
    b, [b_ws] = await seed_tenant(app_sessions)
    await SqlUsageLedger(app_sessions).settle(event(b, workspace_id=b_ws))
    async with app_sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(b)})
        await session.execute(
            sa.text(
                "INSERT INTO platform.usage_daily (tenant_id, workspace_id, day, provider,"
                " model, operation, purpose, payer, calls, input_tokens, output_tokens,"
                " cache_read_tokens, cache_write_tokens, reasoning_tokens, cost_usd,"
                " unpriced_calls, estimated_calls, rolled_up_at) VALUES (:t, NULL,"
                " '2026-11-03', 'p', 'm', 'chat', 'run', 'platform', 1, 1, 1, 0, 0, 0, 1, 0,"
                " 0, now())"
            ),
            {"t": b},
        )

    for table in ("platform.usage_events", "platform.usage_daily"):
        assert await rows_of(app_sessions, a, table) == []
        assert len(await rows_of(app_sessions, b, table)) == 1
    reads = SqlUsageReads(app_sessions)
    summary = await reads.summary(
        a,
        SummaryFilter(
            first_day=date(2026, 11, 1), last_day=date(2026, 11, 30), group_by="workspace"
        ),
    )
    assert summary == []


async def test_a_connection_that_sets_nothing_reads_nothing(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    b, _ = await seed_tenant(app_sessions)
    await SqlUsageLedger(app_sessions).settle(event(b))
    async with app_sessions() as session, session.begin():
        assert (await session.scalar(sa.text("SELECT count(*) FROM platform.usage_events"))) == 0


async def test_the_drain_policy_reads_across_companies_and_writes_nothing(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Without `app.worker_drain` a tenant's connection sees only its rows;
    with it, the roll-up lane sees every company's and may still write none."""
    a, _ = await seed_tenant(app_sessions)
    b, _ = await seed_tenant(app_sessions)
    at = datetime(2026, 11, 3, 23, tzinfo=UTC)
    await SqlUsageLedger(app_sessions).settle(event(b, occurred_at=at))

    store = SqlUsageRollupStore(app_sessions)
    assert b in await store.tenants_with_usage_since(at)
    async with app_sessions() as session, session.begin():
        await session.execute(sa.text("SELECT set_config('app.worker_drain', 'on', true)"))
        with pytest.raises(sa.exc.ProgrammingError, match="row-level security"):
            await session.execute(
                sa.text(
                    "INSERT INTO platform.usage_events (id, occurred_at, tenant_id, actor_kind,"
                    " operation, purpose, payer, provider, model, input_tokens, output_tokens,"
                    " cache_read_tokens, cache_write_tokens, reasoning_tokens, units, cost_usd,"
                    " cost_source, price_book_version, price_entry_ids) VALUES"
                    " (gen_random_uuid(), now(), :t, 'user', 'chat', 'run', 'platform', 'p',"
                    " 'm', 1, 1, 0, 0, 0, '{}', 0, 'computed', '1', '{}')"
                ),
                {"t": a},
            )
    async with app_sessions() as session, session.begin():
        await session.execute(_SET_TENANT, {"t": str(a)})
        rows = await session.scalars(
            sa.text("SELECT tenant_id FROM platform.usage_events WHERE occurred_at >= :at"),
            {"at": at},
        )
        assert b not in set(rows.all())


# ---- R3.5: the roll-up equals the ledger, day by company day -----------------


async def _daily(
    sessions: async_sessionmaker[AsyncSession], tenant: uuid.UUID
) -> dict[tuple[date, uuid.UUID | None], tuple[int, Decimal]]:
    found: dict[tuple[date, uuid.UUID | None], tuple[int, Decimal]] = {}
    for row in await rows_of(sessions, tenant, "platform.usage_daily"):
        key = (row.day, row.workspace_id)
        calls, cost = found.get(key, (0, Decimal(0)))
        found[key] = (calls + row.calls, cost + row.cost_usd)
    return found


async def test_the_roll_up_sums_each_company_day_in_its_zone(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    hcm, [ws] = await seed_tenant(app_sessions)  # no zone: Asia/Ho_Chi_Minh
    tokyo, _ = await seed_tenant(app_sessions, timezone="Asia/Tokyo")
    ledger = SqlUsageLedger(app_sessions)
    one = Decimal("0.01")
    # 17:30Z is 4/11 in Hồ Chí Minh, 16:30Z still 3/11; the second has no
    # workspace (company-level work).
    await ledger.settle(
        event(
            hcm,
            workspace_id=ws,
            occurred_at=datetime(2026, 11, 3, 17, 30, tzinfo=UTC),
            cost_usd=one,
        )
    )
    await ledger.settle(
        event(hcm, occurred_at=datetime(2026, 11, 3, 16, 30, tzinfo=UTC), cost_usd=one)
    )
    # Tokyo cuts at 15:00Z: 15:00Z is its 4/11, 14:59Z its 3/11.
    await ledger.settle(
        event(tokyo, occurred_at=datetime(2026, 11, 3, 15, 0, tzinfo=UTC), cost_usd=one)
    )
    await ledger.settle(
        event(tokyo, occurred_at=datetime(2026, 11, 3, 14, 59, tzinfo=UTC), cost_usd=one)
    )
    await ledger.settle(
        event(
            tokyo,
            occurred_at=datetime(2026, 11, 3, 14, 0, tzinfo=UTC),
            cost_source="unpriced",
            cost_usd=None,
        )
    )

    rollup = UsageRollup(
        store=SqlUsageRollupStore(app_sessions),
        calendar=UsageCalendar(SqlTenantTimezones(app_sessions)),
        clock=FixedClock(datetime(2026, 11, 3, 18, tzinfo=UTC)),
    )
    await rollup.run_once()
    first = await _daily(app_sessions, hcm)
    assert first == {
        (date(2026, 11, 4), ws): (1, one),
        (date(2026, 11, 3), None): (1, one),
    }
    assert await _daily(app_sessions, tokyo) == {
        (date(2026, 11, 4), None): (1, one),
        (date(2026, 11, 3), None): (2, one),
    }

    await rollup.run_once()  # twice: the same rows
    assert await _daily(app_sessions, hcm) == first

    # A record settled late shows after the next pass.
    await ledger.settle(
        event(
            hcm,
            workspace_id=ws,
            occurred_at=datetime(2026, 11, 3, 17, 45, tzinfo=UTC),
            cost_usd=one,
        )
    )
    await rollup.run_once()
    assert (await _daily(app_sessions, hcm))[(date(2026, 11, 4), ws)] == (2, one * 2)

    # The summary names the company-level group, and the unpriced call shows.
    summary = await SqlUsageReads(app_sessions).summary(
        hcm,
        SummaryFilter(
            first_day=date(2026, 11, 1), last_day=date(2026, 11, 30), group_by="workspace"
        ),
    )
    assert {(g.key, g.label) for g in summary} == {(str(ws), "ws0"), (None, None)}
    [tokyo_group] = await SqlUsageReads(app_sessions).summary(
        tokyo,
        SummaryFilter(first_day=date(2026, 11, 1), last_day=date(2026, 11, 30), group_by="purpose"),
    )
    assert (tokyo_group.calls, tokyo_group.unpriced_calls) == (3, 1)


async def test_a_run_s_usage_is_its_own_records_only(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    tenant, _ = await seed_tenant(app_sessions)
    run, other_run = uuid.uuid4(), uuid.uuid4()
    ledger = SqlUsageLedger(app_sessions)
    await ledger.settle(event(tenant, run_id=run))
    await ledger.settle(event(tenant, run_id=run, cost_source="unpriced", cost_usd=None))
    await ledger.settle(event(tenant, run_id=other_run))
    rows = await SqlUsageReads(app_sessions).run_usage(tenant, run)
    assert sorted((r.cost_source, r.calls, r.cost_usd) for r in rows) == [
        ("computed", 1, Decimal("0.00280000")),
        ("unpriced", 1, Decimal(0)),
    ]
    assert await SqlUsageReads(app_sessions).run_usage(tenant, uuid.uuid4()) == []
