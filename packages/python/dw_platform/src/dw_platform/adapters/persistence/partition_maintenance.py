"""Keeping the audit log in monthly partitions, on the worker's schedule.

`platform.audit_events` is partitioned by month. The baseline said an
operational job would create those partitions ahead of time; it never existed,
every row landed in the DEFAULT partition, and a default partition cannot be
dropped — so the retention answer for audit ("DROP PARTITION, instant, nothing
to vacuum") could not run at all.

Every registered parent gets its own cutoff (usage-and-limits/02, migration
`2354ad4d2e3c`): `platform.drop_expired_partitions(cutoffs jsonb)` takes one per
`schema.table`, built here from the table's own retention fragment. Only a
fragment with `days`, `purger: drop_partition` and `enforced: true` gives a
cutoff; every other parent is left out of the object and loses no month.

This is that job, and it runs in the worker rather than in a cron entry someone
has to remember to install. Falling behind is not self-correcting: a month with
no partition sends its rows to the default, and a default holding that month's
rows then blocks the month's partition from ever being created.

**Why it calls functions instead of running DDL.** Creating a partition is DDL
on a table `dw_app` does not own, and `dw_app` deliberately has no BYPASSRLS.
Migration `06d9e1a67d40` installs two SECURITY DEFINER functions owned by the
migrator, with a fixed `search_path`, EXECUTE revoked from PUBLIC, and no
argument that names a table. The parents come from
`platform.time_partitioned_tables`, which only migrations write (`a77c5408a1f4`,
ADR 0100 point 7). All this module supplies is a bounded integer and a cutoff.

**Creating and dropping are separate transactions.** Creating is safe and
always worth doing; dropping destroys a month. A drop that fails must not take
the creation with it, because the creation is what keeps next month's rows out
of the default.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_platform.retention_policy import RetentionPolicy

logger = logging.getLogger("dw_platform.partitions")

__all__ = ["AUDIT_EVENTS", "SqlPartitionMaintenance"]

_ENSURE = sa.text("SELECT platform.ensure_time_partitions(:months_ahead)")
_DROP = sa.text("SELECT platform.drop_expired_partitions(CAST(:cutoffs AS jsonb))")

# The audit log's store key: the key of its retention fragment and of its
# `platform.time_partitioned_tables` row.
AUDIT_EVENTS = "platform.audit_events"


@dataclass(frozen=True)
class SqlPartitionMaintenance:
    """Implements `dw_worker.consumers.retention.RetentionPrunePort` for partitions."""

    session_factory: async_sessionmaker[AsyncSession]
    policy: RetentionPolicy
    clock: UtcClock

    async def prune(self) -> None:
        created = await self._create_ahead()
        if created:
            logger.info(
                "created time partitions",
                extra={"partitions": created, "policy_version": self.policy.policy_version},
            )
        dropped = await self._drop_expired()
        if dropped:
            logger.info(
                "dropped expired time partitions",
                extra={"partitions": dropped, "policy_version": self.policy.policy_version},
            )

    async def _create_ahead(self) -> list[str]:
        async with self.session_factory() as session, session.begin():
            made = await session.scalars(_ENSURE, {"months_ahead": self.policy.audit.months_ahead})
            return list(made.all())

    def cutoffs(self, now: datetime) -> dict[str, str]:
        """`schema.table` -> the instant before which its whole months go, for
        every fragment that may drop a partition now (H-1, H-27).

        A store whose term is undecided, not `enforced`, or carried out by
        another purger is left out, which the function reads as "nothing to
        drop": a NULL, never a very old timestamp nobody wrote.
        """
        found: dict[str, str] = {}
        for key, fragment in self.policy.stores.items():
            if fragment.purger != "drop_partition":
                continue
            cutoff = self.policy.store_cutoff(key, now=now)
            if cutoff is not None:
                found[key] = cutoff.isoformat()
        return found

    async def _drop_expired(self) -> list[str]:
        """Every registered parent's cutoff in one call.

        No early return on an empty object: the call is what makes the function
        the one place that decides, and short-circuiting here would put half the
        decision on this side of the connection where nothing tests it.
        """
        cutoffs = self.cutoffs(self.clock.now())
        async with self.session_factory() as session, session.begin():
            gone = await session.scalars(_DROP, {"cutoffs": json.dumps(cutoffs, sort_keys=True)})
            return list(gone.all())
