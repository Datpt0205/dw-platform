"""One cutoff per registered parent, each from its own fragment
(usage-and-limits ticket 02, step 4; H-1, H-27).

`platform.drop_expired_partitions(cutoffs jsonb)` drops a parent's whole months
behind its own cutoff and touches no parent that has none, so a table whose
fragment is not `enforced` (the ledger's ships that way) loses no month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence.partition_maintenance import SqlPartitionMaintenance
from dw_platform.retention_policy import (
    RetentionFragment,
    RetentionPolicy,
    load_retention_policy,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 4, tzinfo=UTC)
_LEDGER, _AUDIT = "platform.usage_events", "platform.audit_events"


@dataclass(frozen=True)
class _Clock:
    def now(self) -> datetime:
        return NOW


async def _month(migrator: AsyncEngine, parent: str, month: date) -> str:
    async with migrator.begin() as conn:
        made = await conn.scalar(
            sa.text("SELECT platform._ensure_one_partition('platform', :p, :m)"),
            {"p": parent, "m": month},
        )
    return made or f"{parent}_{month:%Y_%m}"


async def _exists(migrator: AsyncEngine, name: str) -> bool:
    async with migrator.connect() as conn:
        return bool(
            await conn.scalar(
                sa.text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"platform.{name}"}
            )
        )


def _policy(ledger: RetentionFragment) -> RetentionPolicy:
    shipped = load_retention_policy()
    stores = {**shipped.stores, _LEDGER: ledger}
    stores[_AUDIT] = RetentionFragment(
        days=1, purger="drop_partition", enforced=False, description="giữ"
    )
    return shipped.model_copy(update={"stores": stores})


async def test_each_parent_drops_by_its_own_term_only(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    old_ledger = await _month(migrator, "usage_events", date(2024, 1, 1))
    old_audit = await _month(migrator, "audit_events", date(2024, 1, 1))
    recent_ledger = await _month(migrator, "usage_events", date(2026, 10, 1))
    policy = _policy(
        RetentionFragment(days=395, purger="drop_partition", enforced=True, description="thử")
    )
    lane = SqlPartitionMaintenance(app_sessions, policy, _Clock())
    assert set(lane.cutoffs(NOW)) == {_LEDGER}

    await lane.prune()

    assert not await _exists(migrator, old_ledger)
    assert await _exists(migrator, recent_ledger)
    assert await _exists(migrator, old_audit), "a parent with no enforced term lost a month"


async def test_the_shipped_ledger_term_drops_nothing_until_enforced(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """Q-h11: the ledger's fragment ships with `enforced: false`."""
    shipped = load_retention_policy()
    assert shipped.stores[_LEDGER].enforced is False
    ancient = await _month(migrator, "usage_events", date(2023, 6, 1))
    lane = SqlPartitionMaintenance(app_sessions, shipped, _Clock())
    assert _LEDGER not in lane.cutoffs(NOW)

    await lane.prune()

    assert await _exists(migrator, ancient)


async def test_the_function_refuses_anything_but_an_object(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with app_sessions() as session, session.begin():
        with pytest.raises(sa.exc.DBAPIError, match="json object"):
            await session.execute(
                sa.text("SELECT platform.drop_expired_partitions(CAST('[]' AS jsonb))")
            )
