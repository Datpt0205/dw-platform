"""The Send floor's tables (compliance-pdpl ticket 08; ADR-0124).

`marketing_purge_step` is the offboarding lane's step for the two append-only
tables, which `dw_app` cannot DELETE from: it calls
`platform.purge_tenant_marketing`, which refuses any tenant but the
transaction's own, and any tenant not `offboarding`. Suppressions go by the
lane's default step, which the table's trigger lets through only then.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from dw_platform.adapters.persistence.offboarding import OffboardingPurgeStep

_PURGE = sa.text("SELECT platform.purge_tenant_marketing(:t)")


async def _purge(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(_PURGE, {"t": tenant_id})


def marketing_purge_step() -> OffboardingPurgeStep:
    return OffboardingPurgeStep(
        name="platform.purge_tenant_marketing",
        tables=frozenset({"platform.consent_records", "platform.marketing_send_log"}),
        run=_purge,
    )
