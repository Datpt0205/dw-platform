"""Load the pinned retention terms into `platform.retention_terms` (spec R5.9, R5.10).

The fragments under `configs/policies/retention.d/` are the terms; the table is
their runtime copy, read by the narrow purge functions through
`platform.retention_term_days`, which take no argument and so cannot be handed
a term. A copy is a second owner of one fact, so it is made exact on every
deploy and checked by a test that names the key that drifted
(`failure-modes.md` #2).

`python -m dw_platform.adapters.persistence.retention_terms` runs in the compose
`migrate` job right after `alembic upgrade head`, as `dw_provisioner`, the one
role allowed to write the table. A fragment that does not parse, or a database
it cannot reach, exits non-zero with nothing changed, so the deploy stops
instead of starting `api` and `worker` against an empty or stale table.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.retention_policy import RetentionPolicy, load_retention_policy

__all__ = ["loaded_terms", "pinned_terms", "retention_term_drift", "sync_retention_terms"]

logger = logging.getLogger("dw_platform.retention_terms")

_READ = sa.text("SELECT store_key, term_days FROM platform.retention_terms")
_UPSERT = sa.text(
    "INSERT INTO platform.retention_terms (store_key, term_days) VALUES (:key, :days)"
    " ON CONFLICT (store_key) DO UPDATE SET term_days = EXCLUDED.term_days"
    " WHERE platform.retention_terms.term_days IS DISTINCT FROM EXCLUDED.term_days"
)
_DELETE_OTHERS = sa.text(
    "DELETE FROM platform.retention_terms WHERE NOT (store_key = ANY(CAST(:keys AS text[])))"
)


def pinned_terms(policy: RetentionPolicy) -> dict[str, int]:
    """What the table must hold: each fragment with a term in days that is enforced.

    `indefinite` and `null` have no number to purge by, and a term decided but
    not `enforced` may not run yet; none of them has a row, so a purge function
    asking for one stops (R5.12).
    """
    return {
        key: fragment.days
        for key, fragment in policy.stores.items()
        if isinstance(fragment.days, int) and fragment.enforced
    }


async def loaded_terms(conn: AsyncConnection) -> dict[str, int]:
    return {row.store_key: row.term_days for row in (await conn.execute(_READ)).all()}


async def sync_retention_terms(conn: AsyncConnection, policy: RetentionPolicy) -> dict[str, int]:
    """Add, change and remove rows until the table is exactly `pinned_terms`.

    One transaction, the caller's: a failure part-way leaves the table as it was.
    """
    wanted = pinned_terms(policy)
    await conn.execute(_DELETE_OTHERS, {"keys": sorted(wanted)})
    for key, days in sorted(wanted.items()):
        await conn.execute(_UPSERT, {"key": key, "days": days})
    return wanted


def retention_term_drift(loaded: Mapping[str, int], pinned: Mapping[str, int]) -> list[str]:
    """Each key the table is missing, holds extra, or holds with another term."""
    found = [f"{key} missing" for key in sorted(set(pinned) - set(loaded))]
    found += [f"{key} not in the pinned fragment set" for key in sorted(set(loaded) - set(pinned))]
    found += [
        f"{key} holds {loaded[key]} days, the fragment says {pinned[key]}"
        for key in sorted(set(loaded) & set(pinned))
        if loaded[key] != pinned[key]
    ]
    return found


async def _load(database_url: str) -> dict[str, int]:
    policy = load_retention_policy()
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            return await sync_retention_terms(conn, policy)
    finally:
        await engine.dispose()


def main() -> int:
    database_url = os.environ.get("DW_PROVISIONER_DATABASE_URL")
    if not database_url:
        logger.error("DW_PROVISIONER_DATABASE_URL is not set; no retention terms loaded")
        return 2
    try:
        loaded = asyncio.run(_load(database_url))
    except Exception:
        logger.exception("retention terms not loaded; the table is unchanged")
        return 1
    print(f"retention terms loaded: {', '.join(sorted(loaded)) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
