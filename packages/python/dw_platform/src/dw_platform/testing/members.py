"""The company member row a test fixture writes before a membership.

Every ``platform.memberships`` row hangs from a ``platform.tenant_members`` row
of the same ``(tenant_id, user_id)`` (``fk_memberships_tenant_members``,
org-and-principals R4.1), so a fixture that writes a membership in raw SQL
writes this first, in the same transaction or before it. ``active`` by
default, since a fixture's person is meant to pass the AccessContext door; a
row already there keeps its status. Application code writes the row through
``dw_platform.adapters.persistence.tenant_member_rows`` instead.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

TENANT_MEMBER_SQL = (
    "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
    " VALUES (:tenant_id, :user_id, :status)"
    " ON CONFLICT (tenant_id, user_id) DO NOTHING"
)

MemberStatus = Literal["invited", "active", "suspended"]


def tenant_member_params(
    tenant_id: UUID | str, user_id: UUID | str, status: MemberStatus = "active"
) -> dict[str, object]:
    """The parameters of ``TENANT_MEMBER_SQL``, for a fixture's statement list."""
    return {"tenant_id": tenant_id, "user_id": user_id, "status": status}


async def add_tenant_member(
    conn: AsyncConnection | AsyncSession,
    tenant_id: UUID | str,
    user_id: UUID | str,
    status: MemberStatus = "active",
) -> None:
    await conn.execute(sa.text(TENANT_MEMBER_SQL), tenant_member_params(tenant_id, user_id, status))
