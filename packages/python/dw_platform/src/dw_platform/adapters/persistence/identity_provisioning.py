"""SQL implementation of identity bootstrap + first-login provisioning.

Runs as the RLS-constrained runtime role (``dw_app``). The identity plane
(``users``, ``external_identities``) has no RLS; membership reads/writes set the
default tenant as the RLS context first, so a brand-new user can only ever be
provisioned into that one tenant.

Default-deny: a brand-new verified identity gets a platform user but **no
membership** — it lands on the "no workspace, contact an admin" state until an
admin grants access. The legacy auto-provision-into-the-default-tenant path is
kept behind ``auto_provision_default_membership`` (off by default) for the demo
seed and tests; production never turns it on.

Linking follows the interim rule of ADR-0103 decision 8 (foundations-hardening
R4): a sign-in resolves to an existing user through its own ``(issuer,
subject)``; through ``users.subject`` only for the dev issuer; or through its
email only when the token says ``email_verified`` and that user has never
signed in and is neither a platform operator nor support staff — the person an
importer or an invitation created. Any other email match is refused 403
``identity_email_in_use``, and a subject some user already holds without this
issuer's identity is refused 403 ``identity_subject_in_use``: neither creates a
user nor links one. A new user takes the token's email only when it is
verified, so an unverified address cannot be squatted ahead of an invitation.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import PermissionDeniedError
from dw_platform.adapters.identity.dev_token import DEV_ISSUER
from dw_platform.adapters.persistence import tables
from dw_platform.application.identity_bootstrap import (
    BootstrapView,
    WorkspaceMembershipView,
)
from dw_platform.application.ports import VerifiedIdentity

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_PRINCIPAL = text("SELECT set_config('app.principal_id', :principal_id, true)")


_LOCK_LINK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
# A linked chat is where to send, not who is signing in.
_LOGIN = tables.external_identities.c.provider.not_in(tables.CHANNEL_LINK_PROVIDERS)


async def _login_identity_owner(session: AsyncSession, identity: VerifiedIdentity) -> UUID | None:
    return await session.scalar(
        sa.select(tables.external_identities.c.user_id).where(
            tables.external_identities.c.issuer == identity.issuer,
            tables.external_identities.c.subject == identity.subject,
            _LOGIN,
        )
    )


async def _has_login_identity(session: AsyncSession, user_id: UUID) -> bool:
    found = await session.scalar(
        sa.select(sa.literal(True)).where(tables.external_identities.c.user_id == user_id, _LOGIN)
    )
    return found is not None


async def _is_privileged(session: AsyncSession, user_id: UUID) -> bool:
    """A platform operator or support staff member, read as ``bootstrap`` reads them."""
    found = await session.scalar(
        sa.select(sa.literal(True)).where(
            sa.or_(
                sa.exists().where(tables.platform_operators.c.user_id == user_id),
                sa.exists().where(tables.support_staff.c.user_id == user_id),
            )
        )
    )
    return found is not None


def _display_name_for(identity: VerifiedIdentity) -> str:
    name = getattr(identity, "name", None)
    if name:
        return str(name)
    if identity.email:
        return identity.email.split("@", 1)[0]
    return identity.subject[:64]


@dataclass(frozen=True)
class SqlIdentityBootstrap:
    """Implements ``IdentityBootstrapPort``.

    ``default_tenant_id`` / ``default_workspace_id`` must match the seeded demo
    tenant (see ``dw_platform.testing.seed_env``). With
    ``auto_provision_default_membership`` on, brand-new identities land there as
    ``default_role``; off (the default), they get no membership at all.
    """

    session_factory: async_sessionmaker[AsyncSession]
    default_tenant_id: UUID
    default_workspace_id: UUID
    default_role: str = "member"
    provider: str = "oidc"
    auto_provision_default_membership: bool = False

    async def bootstrap(self, identity: VerifiedIdentity) -> BootstrapView:
        async with self.session_factory() as session, session.begin():
            user_id, is_new = await self._resolve_user(session, identity)

            # Membership plane is RLS-scoped: pin the default tenant first (the
            # optional auto-provision writes into it), and set the principal so
            # the read below returns this user's memberships in *every* tenant,
            # not only the pinned one (migration 0065).
            await session.execute(_SET_TENANT, {"tenant_id": str(self.default_tenant_id)})
            await session.execute(_SET_PRINCIPAL, {"principal_id": str(user_id)})
            if is_new and self.auto_provision_default_membership:
                await self._provision_default_membership(session, user_id)

            user_row = (
                await session.execute(
                    sa.select(
                        tables.users.c.subject,
                        tables.users.c.email,
                        tables.users.c.display_name,
                    ).where(tables.users.c.id == user_id)
                )
            ).one()

            memberships = await self._read_memberships(session, user_id)
            # ADR-002: is this identity a Platform Operator? dw_app holds SELECT
            # on the global allowlist (migration 0067); absent table (older DB)
            # is handled by the column not existing, so guard is unnecessary.
            is_operator = (
                await session.execute(
                    sa.select(tables.platform_operators.c.user_id).where(
                        tables.platform_operators.c.user_id == user_id
                    )
                )
            ).first() is not None
            is_support_staff = (
                await session.execute(
                    sa.select(tables.support_staff.c.user_id).where(
                        tables.support_staff.c.user_id == user_id
                    )
                )
            ).first() is not None

        return BootstrapView(
            principal_id=user_id,
            subject=user_row.subject,
            email=user_row.email,
            display_name=user_row.display_name,
            memberships=memberships,
            is_platform_operator=is_operator,
            is_support_staff=is_support_staff,
        )

    async def _resolve_user(
        self, session: AsyncSession, identity: VerifiedIdentity
    ) -> tuple[UUID, bool]:
        """Return (user_id, is_new), linking ``(issuer, subject)`` where the rule allows."""
        mapped = await _login_identity_owner(session, identity)
        if mapped is not None:
            return mapped, False

        # The dev issuer's tokens name the seeded user's own subject; the
        # `local` profile is the only one that verifies them.
        if identity.issuer == DEV_ISSUER:
            seeded = await session.scalar(
                sa.select(tables.users.c.id).where(tables.users.c.subject == identity.subject)
            )
            if seeded is not None:
                return seeded, False

        if identity.email:
            holder = await session.scalar(
                sa.select(tables.users.c.id).where(
                    sa.func.lower(tables.users.c.email) == identity.email.lower()
                )
            )
            if holder is not None:
                # Two first sign-ins to one invited person must not both pass
                # "never signed in". An advisory lock, not FOR UPDATE: `dw_app`
                # holds no UPDATE on `platform.users` (ticket 03).
                await session.execute(_LOCK_LINK, {"key": f"identity_link:{holder}"})
                if not (
                    identity.email_verified
                    and not await _has_login_identity(session, holder)
                    and not await _is_privileged(session, holder)
                ):
                    raise PermissionDeniedError(
                        "this email belongs to an account this sign-in cannot claim",
                        details={"reason_code": "identity_email_in_use"},
                    )
                await self._link(session, holder, identity)
                return holder, False

        created = await session.scalar(
            pg_insert(tables.users)
            .values(
                id=uuid4(),
                subject=identity.subject,
                email=identity.email if identity.email_verified else None,
                display_name=_display_name_for(identity),
            )
            .on_conflict_do_nothing(index_elements=["subject"])
            .returning(tables.users.c.id)
        )
        if created is None:
            # A concurrent first sign-in of this same identity won the insert
            # and linked it; anything else holding the subject is not ours.
            mapped = await _login_identity_owner(session, identity)
            if mapped is not None:
                return mapped, False
            raise PermissionDeniedError(
                "this subject belongs to another account",
                details={"reason_code": "identity_subject_in_use"},
            )
        await self._link(session, created, identity)
        return created, True

    async def _link(self, session: AsyncSession, user_id: UUID, identity: VerifiedIdentity) -> None:
        await session.execute(
            pg_insert(tables.external_identities)
            .values(
                id=uuid4(),
                user_id=user_id,
                issuer=identity.issuer,
                subject=identity.subject,
                provider=self.provider,
            )
            .on_conflict_do_nothing(constraint="uq_external_identities_issuer_subject")
        )

    async def _provision_default_membership(self, session: AsyncSession, user_id: UUID) -> None:
        tenant_exists = (
            await session.execute(
                sa.select(tables.tenants.c.id).where(tables.tenants.c.id == self.default_tenant_id)
            )
        ).first()
        if tenant_exists is None:
            # Unseeded database: user is created but has no workspace yet.
            return
        await session.execute(
            pg_insert(tables.memberships)
            .values(
                id=uuid4(),
                tenant_id=self.default_tenant_id,
                workspace_id=self.default_workspace_id,
                user_id=user_id,
                role_keys=[self.default_role],
                department="general",
            )
            .on_conflict_do_nothing(constraint="uq_memberships_scope_user")
        )

    async def _read_memberships(
        self, session: AsyncSession, user_id: UUID
    ) -> tuple[WorkspaceMembershipView, ...]:
        rows = (
            await session.execute(
                sa.select(
                    tables.memberships.c.workspace_id,
                    tables.memberships.c.role_keys,
                    tables.workspaces.c.slug.label("workspace_slug"),
                    tables.workspaces.c.name.label("workspace_name"),
                    tables.tenants.c.id.label("tenant_id"),
                    tables.tenants.c.slug.label("tenant_slug"),
                    tables.tenants.c.name.label("tenant_name"),
                )
                .select_from(
                    tables.memberships.join(
                        tables.workspaces,
                        tables.memberships.c.workspace_id == tables.workspaces.c.id,
                    ).join(
                        tables.tenants,
                        tables.memberships.c.tenant_id == tables.tenants.c.id,
                    )
                )
                .where(tables.memberships.c.user_id == user_id)
            )
        ).all()
        if not rows:
            return ()

        role_keys: set[str] = set()
        for row in rows:
            role_keys.update(row.role_keys)
        scope_by_role: dict[str, list[str]] = {}
        if role_keys:
            role_rows = await session.execute(
                sa.select(tables.roles.c.key, tables.roles.c.scopes).where(
                    tables.roles.c.key.in_(role_keys)
                )
            )
            for key, role_scopes in role_rows:
                scope_by_role[key] = list(role_scopes)

        views: list[WorkspaceMembershipView] = []
        for row in rows:
            scopes: set[str] = set()
            for key in row.role_keys:
                scopes.update(scope_by_role.get(key, []))
            views.append(
                WorkspaceMembershipView(
                    tenant_id=row.tenant_id,
                    tenant_slug=row.tenant_slug,
                    tenant_name=row.tenant_name,
                    workspace_id=row.workspace_id,
                    workspace_slug=row.workspace_slug,
                    workspace_name=row.workspace_name,
                    roles=tuple(sorted(row.role_keys)),
                    scopes=tuple(sorted(scopes)),
                )
            )
        return tuple(views)
