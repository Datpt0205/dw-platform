"""SQL implementation of the membership lookup used to build AccessContext.

The requested tenant becomes the RLS context for the lookup transaction itself:
if the caller is not a member, RLS + the membership predicate return no rows and
access is denied. The client-requested tenant is only ever used as a filter that
must be CONFIRMED by data, never trusted directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.identity.dev_token import DEV_ISSUER
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.hierarchy_repo import SUBTREE_QUERY
from dw_platform.application.access_context import Grant
from dw_platform.application.authorization import PLATFORM_ADMIN_ROLE
from dw_platform.application.identity import MembershipAccess

_SET_LOOKUP_CONTEXT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_LINKED_CONTEXT = text(
    "SELECT set_config('app.principal_id', :principal_id, true),"
    "       set_config('app.tenant_id', :tenant_id, true)"
)
# Leadership scope: sees every record in the workspace even in a restricted
# tenant (ADR-003), so the roll-up never narrows a director's record lists.
_RECORDS_ALL_READ = "crm.records.all.read"

_ACCESS_VERSION = text(
    "SELECT version FROM platform.tenant_access_versions WHERE tenant_id = CAST(:t AS uuid)"
)
_SCOPES_IN = text(
    "SELECT platform.scopes_in(CAST(:t AS uuid), CAST(:u AS uuid), CAST(:w AS uuid)) AS key"
)
# What one person holds in the tenant, the roles assigned to this membership,
# and their projection for this workspace, in one round trip. Every answer is
# the database's: `platform.effective_grants` and `platform.scopes_in`
# (tenant-rbac R2, ADR-0104 decision 5); nothing here decides which key counts.
_HELD = text(
    """
    SELECT
        ARRAY(SELECT platform.scopes_in(CAST(:t AS uuid), CAST(:u AS uuid), CAST(:w AS uuid)))
            AS scopes,
        ARRAY(
            SELECT DISTINCT r.key
            FROM platform.role_assignments a
            JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
            WHERE a.tenant_id = CAST(:t AS uuid) AND a.membership_id = CAST(:m AS uuid)
              AND r.deleted_at IS NULL AND (a.expires_at IS NULL OR a.expires_at > now())
        ) AS role_keys,
        (
            SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_array(
                       g.permission_key, g.depth, g.anchor_workspace_id)), '[]'::jsonb)
            FROM platform.effective_grants(CAST(:t AS uuid), CAST(:u AS uuid)) g
        ) AS grants
    """
)


async def access_version(session: AsyncSession, tenant_id: UUID) -> int | None:
    """The tenant's access version (`platform.tenant_access_versions`), or None
    when it has no row: an offboarded tenant, whose contexts are never cached."""
    found = await session.scalar(_ACCESS_VERSION, {"t": str(tenant_id)})
    return None if found is None else int(found)


async def effective_scopes(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, workspace_id: UUID
) -> frozenset[str]:
    """What a person holds acting in one workspace: `platform.scopes_in`, the
    projection of `platform.effective_grants` (tenant-rbac R2.2).

    A thin adapter, deliberately: the access context, "who in this workspace
    holds X" and a Digital Worker's standing and boundary all ask it, and the
    rule is the database's alone, so none of them can drift from the triggers
    and policies that read the same function."""
    rows = await session.execute(
        _SCOPES_IN, {"t": str(tenant_id), "u": str(user_id), "w": str(workspace_id)}
    )
    return frozenset(row.key for row in rows)


def _grants(raw: list[list[str]]) -> tuple[Grant, ...]:
    grants = (
        Grant(key=key, depth=depth, anchor_workspace_id=UUID(anchor)) for key, depth, anchor in raw
    )
    return tuple(sorted(grants, key=lambda g: (g.key, str(g.anchor_workspace_id), g.depth)))


async def _access_in(
    session: AsyncSession,
    user_clause: sa.ColumnElement[bool],
    tenant_id: UUID,
    workspace_id: UUID,
    ceiling: frozenset[str] | None = None,
) -> MembershipAccess | None:
    """The access a membership matching ``user_clause`` holds in one workspace.

    Shared by the sign-in path and the linked-chat path, so tenant status,
    entitlement and the record roll-up are read one way for both. The caller
    has already bound the transaction's settings. With a ``ceiling`` the scopes
    and grants are cut to it and no role is carried: a role can stand in for
    scopes (``platform_admin`` passes every scope check), so a context limited
    to a ceiling must not hold one.
    """
    # Before the data, in the same transaction (R4.1): the data read below is
    # never older than the version the context carries.
    version = await access_version(session, tenant_id)
    # Membership and the tenant's status in one round-trip. A locked
    # tenant is frozen: even a valid member is denied an AccessContext, so
    # the Platform Operator's lock (ADR-002) actually bites instead of
    # only setting a column. Joining `tenants` here reads its status
    # alongside the membership rather than paying a second query for a
    # column keyed on the same tenant.
    membership_row = (
        await session.execute(
            sa.select(
                tables.memberships.c.id,
                tables.memberships.c.user_id,
                tables.memberships.c.role_keys,
                tables.memberships.c.clearance,
                tables.tenants.c.status.label("tenant_status"),
                tables.tenants.c.record_visibility,
                tables.tenants.c.max_autonomy_level,
            )
            .select_from(
                tables.memberships.join(
                    tables.tenants, tables.tenants.c.id == tables.memberships.c.tenant_id
                )
                # R4.3: only an `active` member of the company passes, at every
                # route and in every workspace; no company row denies too.
                .join(
                    tables.tenant_members,
                    sa.and_(
                        tables.tenant_members.c.tenant_id == tables.memberships.c.tenant_id,
                        tables.tenant_members.c.user_id == tables.memberships.c.user_id,
                        tables.tenant_members.c.status == "active",
                    ),
                )
            )
            .where(
                user_clause,
                tables.memberships.c.tenant_id == tenant_id,
                tables.memberships.c.workspace_id == workspace_id,
            )
        )
    ).first()
    # Fail closed: no membership, a person not `active` in the company, or a
    # tenant that is not active (`setup` as `locked`, R3.14), denies — an
    # unreadable/absent status is not "active" and denies too.
    if membership_row is None or membership_row.tenant_status != "active":
        return None

    held = (
        await session.execute(
            _HELD,
            {
                "t": str(tenant_id),
                "u": str(membership_row.user_id),
                "w": str(workspace_id),
                "m": str(membership_row.id),
            },
        )
    ).one()
    # The roles assigned here; `platform_admin` stays in `role_keys` in W1 (G2).
    role_keys = frozenset(held.role_keys) | (
        frozenset({PLATFORM_ADMIN_ROLE}) & frozenset(membership_row.role_keys)
    )
    scopes = set(held.scopes)
    grants = _grants(held.grants)
    if ceiling is not None:
        # Narrowed BEFORE anything below reads them, so the roll-up's
        # "sees everything" cannot be granted by a scope or role the
        # ceiling took away.
        scopes &= ceiling
        grants = tuple(g for g in grants if g.key in ceiling)
        role_keys = frozenset()

    entitlement_row = (
        await session.execute(
            sa.select(
                tables.entitlements.c.plan_id,
                tables.entitlements.c.feature_overrides,
                tables.plans.c.features,
            )
            .select_from(
                tables.entitlements.join(
                    tables.plans,
                    tables.entitlements.c.plan_id == tables.plans.c.plan_id,
                )
            )
            .where(tables.entitlements.c.tenant_id == tenant_id)
        )
    ).first()
    if entitlement_row is None:
        return None  # tenant without a plan: fail closed

    feature_flags = frozenset(entitlement_row.features) | frozenset(
        entitlement_row.feature_overrides
    )

    # Record-visibility roll-up (ADR-003): in a restricted tenant a caller
    # without the sees-everything scope is limited to the records owned by
    # their subtree (self + reports). None means no limit — an open tenant
    # or leadership. Computed once here and carried on the context so read
    # paths filter on it rather than re-walking the tree per query.
    #
    # "Sees everything" mirrors the authorization port, not just the literal
    # scope: a platform admin bypasses every scope check (authorization.py),
    # so it must bypass the roll-up too — otherwise an admin in a restricted
    # tenant is narrowed to its own (usually empty) subtree and sees nothing.
    sees_everything = _RECORDS_ALL_READ in scopes or PLATFORM_ADMIN_ROLE in role_keys
    visible_owners: frozenset[UUID] | None = None
    if membership_row.record_visibility == "restricted" and not sees_everything:
        subtree = await session.execute(
            SUBTREE_QUERY,
            {
                "tenant": str(tenant_id),
                "ws": str(workspace_id),
                "root": str(membership_row.user_id),
            },
        )
        visible_owners = frozenset(row.user_id for row in subtree)

    return MembershipAccess(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_id=membership_row.user_id,
        roles=role_keys,
        scopes=frozenset(scopes),
        groups=frozenset(),
        clearance=membership_row.clearance,
        plan_id=entitlement_row.plan_id,
        feature_flags=feature_flags,
        record_visibility=membership_row.record_visibility,
        visible_owners=visible_owners,
        max_autonomy_level=membership_row.max_autonomy_level,
        grants=grants,
        access_version=version,
    )


@dataclass(frozen=True)
class SqlMembershipLookup:
    """Implements ``MembershipLookupPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def access_version(self, tenant_id: UUID) -> int | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_LOOKUP_CONTEXT, {"tenant_id": str(tenant_id)})
            return await access_version(session, tenant_id)

    async def find_access(
        self,
        subject: str,
        issuer: str,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> MembershipAccess | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_LOOKUP_CONTEXT, {"tenant_id": str(tenant_id)})

            # The verified identity resolves to a platform user through its own
            # `(issuer, subject)` identity, or, for the dev issuer only, through
            # the subject stored on the user: a subject of one issuer must not
            # reach a user known through another (R4.3).
            by_identity = sa.select(tables.external_identities.c.user_id).where(
                tables.external_identities.c.issuer == issuer,
                tables.external_identities.c.subject == subject,
                # A linked chat is where to send, not who is signing in.
                tables.external_identities.c.provider.not_in(tables.CHANNEL_LINK_PROVIDERS),
            )
            candidate_users = (
                by_identity.union(
                    sa.select(tables.users.c.id).where(tables.users.c.subject == subject)
                )
                if issuer == DEV_ISSUER
                else by_identity
            )

            return await _access_in(
                session,
                tables.memberships.c.user_id.in_(candidate_users),
                tenant_id,
                workspace_id,
            )

    async def find_linked_access(
        self,
        user_id: UUID,
        tenant_id: UUID,
        workspace_id: UUID,
        ceiling: frozenset[str],
    ) -> MembershipAccess | None:
        """The access a person who wrote through a linked chat holds, cut to ``ceiling``.

        Keyed by ``user_id`` — resolved from the chat's link row — and never by
        ``issuer``/``subject``: a linked chat is a delivery address, and
        ``find_access`` keeps refusing to resolve one (``CHANNEL_LINK_PROVIDERS``).
        The transaction binds ``app.principal_id`` to that user, the setting the
        baseline's ``memberships_self_select`` answers "my memberships" with, and
        ``app.tenant_id`` to the tenant the person's own membership or choice
        named, so the tenant row and its entitlement are readable. Both with
        ``is_local`` true, so a pooled connection carries neither onward.

        None — refused — when the membership is gone, the tenant is locked or
        has no plan, exactly as for sign-in. Scopes are the membership's
        effective scopes intersected with ``ceiling``, and no role is carried.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(
                _SET_LINKED_CONTEXT, {"principal_id": str(user_id), "tenant_id": str(tenant_id)}
            )
            return await _access_in(
                session,
                tables.memberships.c.user_id == user_id,
                tenant_id,
                workspace_id,
                ceiling,
            )
