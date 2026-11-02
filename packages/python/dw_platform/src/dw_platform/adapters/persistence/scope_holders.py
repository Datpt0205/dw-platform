"""Who in a workspace holds a scope: the members a sender should address.

What a member holds there is `platform.scopes_in`, the projection of
`platform.effective_grants` that builds the access context too, so "who may
act" and "who is told to act" cannot disagree (tenant-rbac R2.2). This module
adds no filter of its own: a person who is not an `active` member, a tenant
that is not `active`, a deleted role or an expired assignment grant nothing
there, so nobody holding only those is returned (R2.5; ADR-0104 decision 5).

Both questions here — "who holds one of these scopes" (`holding`) and "does this
person hold this scope" (`holds`) — read one query, so the two answers cannot
drift apart either. Neither takes an `AccessContext`: a workflow node resuming
after someone else's decision, or a worker lane, has a tenant and a workspace
from a verified source but no signed-in caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

# The members of one workspace and each one's scopes there. With `people_only`
# no Digital Worker's principal: it is never someone to tell.
_HOLDERS = text(
    """
    SELECT m.user_id,
           ARRAY(SELECT platform.scopes_in(m.tenant_id, m.user_id, m.workspace_id)) AS scopes
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    WHERE m.tenant_id = CAST(:t AS uuid) AND m.workspace_id = CAST(:w AS uuid)
      AND (CAST(:u AS uuid) IS NULL OR m.user_id = CAST(:u AS uuid))
      AND (NOT CAST(:people AS boolean) OR u.kind = 'human')
    ORDER BY m.user_id
    """
)

# The active people holding a key at tenant depth, each at the workspace that
# anchors it (the smallest id when several do): where a message to them lands.
_TENANT_DEPTH_HOLDERS = text(
    """
    SELECT anchor, array_agg(user_id ORDER BY user_id) AS users
    FROM (
        SELECT tm.user_id,
               (array_agg(g.anchor_workspace_id ORDER BY g.anchor_workspace_id))[1] AS anchor
        FROM platform.tenant_members tm
        JOIN platform.users u ON u.id = tm.user_id AND u.kind = 'human'
        CROSS JOIN LATERAL platform.effective_grants(tm.tenant_id, tm.user_id) g
        WHERE tm.tenant_id = CAST(:t AS uuid)
          AND g.permission_key = :key AND g.depth = 'tenant'
        GROUP BY tm.user_id
    ) held
    GROUP BY anchor
    ORDER BY anchor
    """
)


async def _scopes_by_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    people_only: bool = False,
) -> dict[uuid.UUID, frozenset[str]]:
    rows = await session.execute(
        _HOLDERS,
        {
            "t": str(tenant_id),
            "w": str(workspace_id),
            "u": None if user_id is None else str(user_id),
            "people": people_only,
        },
    )
    return {row.user_id: frozenset(row.scopes) for row in rows}


@dataclass(frozen=True)
class SqlScopeHolders:
    session_factory: async_sessionmaker[AsyncSession]

    async def holding(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID, scopes: frozenset[str]
    ) -> list[uuid.UUID]:
        """The members of `workspace_id` holding any of `scopes`, by user id.

        `tenant_id` and `workspace_id` must come from a source the caller has
        already verified — a row the database tagged with its tenant, a state
        stamped when the run started, an `AccessContext` — never from a request
        body. This function does not check where they came from.
        """
        if not scopes:
            return []
        scope = TenantScope(tenant_id=tenant_id, workspace_id=workspace_id)
        async with tenant_session(self.session_factory, scope) as session:
            held = await _scopes_by_member(session, tenant_id, workspace_id, people_only=True)
        return [user for user, has in held.items() if has & scopes]

    async def tenant_depth_holders(
        self, tenant_id: uuid.UUID, key: str
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """The people holding `key` at tenant depth, grouped by the workspace
        their holding is anchored at, where each is a member. `tenant_id` from a
        verified source, as everywhere here."""
        scope = TenantScope(tenant_id=tenant_id)
        async with tenant_session(self.session_factory, scope) as session:
            rows = await session.execute(_TENANT_DEPTH_HOLDERS, {"t": str(tenant_id), "key": key})
            return {row.anchor: list(row.users) for row in rows}

    async def holds(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, scope: str
    ) -> bool:
        """Whether `user_id` holds `scope` acting in `workspace_id`.

        False for no membership there, no grant in force, or an empty `scope`
        (fail closed). No role stands in for a scope here, `platform_admin`
        included: the question is what this person holds, the same question
        `holding` answers.

        `tenant_id` and `workspace_id` must come from a source the caller has
        already verified (a stamped state, a tenant-tagged row), never from a
        request body; this function does not check where they came from.
        """
        if not scope:
            return False
        return scope in await self.scopes_of(tenant_id, workspace_id, user_id)

    async def scopes_of(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str]:
        """Every scope `user_id` holds acting in `workspace_id`; empty for no
        membership there or nothing in force. Implements `MemberScopesPort` (a
        support grant is in force only while its granter still holds what it
        stamped). Same provenance rule as `holds`."""
        bound = TenantScope(tenant_id=tenant_id, workspace_id=workspace_id)
        async with tenant_session(self.session_factory, bound) as session:
            held = await _scopes_by_member(session, tenant_id, workspace_id, user_id)
        return held.get(user_id, frozenset())
