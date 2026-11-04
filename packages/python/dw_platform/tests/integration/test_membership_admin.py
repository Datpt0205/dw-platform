"""Integration: an Org Admin places a person and removes them, under RLS.

The vertical slice of ADR-001's "admin adds membership", as tenant-rbac ticket
03 left it: a person signs in (default-deny, no access), an Org Admin places
them in a workspace of their tenant with a business role, and the role takes
once a second holder of `platform.roles.bind` confirms it (R7.1). The rails are
exercised — scope, tenant, the hold rule (no role carrying what the admin does
not hold, none a tenant may not hold) and the second person — plus the audit
trail every change leaves.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from rbac_world import (
    Admins,
    assigned_roles,
    assignment_service,
    confirm_all,
    open_proposals,
    plant_admins,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import NotFoundError, PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_admin import SqlMembershipAdminRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.membership_admin import RevokeMembership, RevokeMembershipHandler
from dw_platform.application.role_assignments import GrantMembership
from dw_platform.testing.seed_env import seed_test_env

pytestmark = pytest.mark.integration

# Seeded tenant-alpha / its workspace (uuid5, matches dw_platform.testing.seed_env).
ALPHA = uuid.UUID("d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d")
ALPHA_WS = uuid.UUID("64764894-718d-5558-ba17-9a2949214063")


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    await seed_test_env(db_urls.migrator)
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admins(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> Admins:
    """Two org admins of alpha: one proposes, the other confirms."""
    return await plant_admins(migrator_engine, ALPHA, ALPHA_WS)


@dataclass(frozen=True)
class _Identity:
    subject: str
    email: str | None
    # An IdP that verified the address, as a corporate SSO does.
    email_verified: bool = True
    issuer: str = "https://issuer.test/realms/dw"
    name: str | None = None
    auth_methods: frozenset[str] = frozenset()
    acr: str | None = None


async def _sign_in(engine: AsyncEngine, email: str) -> uuid.UUID:
    """A first login: identity created, default-deny (no membership)."""
    bootstrap = SqlIdentityBootstrap(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        default_tenant_id=ALPHA,
        default_workspace_id=ALPHA_WS,
    )
    view = await bootstrap.bootstrap(_Identity(subject=f"sub-{uuid.uuid4()}", email=email))
    assert view.memberships == ()
    return view.principal_id


def _revoke_handler(engine: AsyncEngine) -> RevokeMembershipHandler:
    repo = SqlMembershipAdminRepository(async_sessionmaker(engine, expire_on_commit=False))
    return RevokeMembershipHandler(
        repo, ScopeAuthorizationService(), SystemClock(), Uuid4Generator()
    )


async def _audit_actions(engine: AsyncEngine, user_id: uuid.UUID) -> list[str]:
    """Every audit row of alpha about one target user (its resource, or named in
    its details), sorted: two events of one transaction may share a time."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(ALPHA)}
        )
        a = tables.audit_events
        rows = (
            await session.execute(
                sa.select(a.c.action).where(
                    sa.or_(
                        a.c.resource_id == str(user_id),
                        a.c.details["user_id"].astext == str(user_id),
                    )
                )
            )
        ).all()
    return sorted(r.action for r in rows)


async def _grant(
    engine: AsyncEngine, admins: Admins, email: str, workspace: uuid.UUID, *keys: str
) -> tuple[uuid.UUID, tuple[uuid.UUID, ...]]:
    person, outcome = await assignment_service(engine).grant_member(
        admins.maker_context,
        GrantMembership(email=email, workspace_id=workspace, role_keys=frozenset(keys)),
    )
    return person.user_id, outcome.proposals


async def test_org_admin_grants_a_business_role_and_it_is_audited(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, admins: Admins
) -> None:
    user_id = await _sign_in(app_engine, "newhire@fpt.com")

    granted, proposals = await _grant(app_engine, admins, "newhire@fpt.com", ALPHA_WS, "member")

    assert granted == user_id
    assert len(proposals) == 1
    # Placed, holding nothing until a second person confirms (R7.1).
    assert await assigned_roles(migrator_engine, ALPHA, user_id) == {ALPHA_WS: []}

    await confirm_all(app_engine, admins.checker_context, proposals)

    assert await assigned_roles(migrator_engine, ALPHA, user_id) == {ALPHA_WS: ["member"]}
    assert await _audit_actions(app_engine, user_id) == [
        "platform.membership.grant",
        "platform.role_assignment.grant",
        "platform.role_change.confirmed",
        "platform.role_change.proposed",
    ]
    async with migrator_engine.connect() as conn:
        applied = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.audit_events"
                " WHERE tenant_id = :t AND action = 'platform.role_assignment.grant'"
                " AND details->>'request_id' = :r AND actor_id = :c"
            ),
            {"t": ALPHA, "r": str(proposals[0]), "c": admins.checker},
        )
    assert applied == 1


async def test_a_plain_member_cannot_grant(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    user_id = await _sign_in(app_engine, "target@fpt.com")
    not_admin = AccessContext(
        tenant_id=ALPHA,
        workspace_id=ALPHA_WS,
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset({"crm.account.read"}),
        plan_id="professional",
    )

    with pytest.raises(PermissionDeniedError):
        await assignment_service(app_engine).grant_member(
            not_admin,
            GrantMembership(
                email="target@fpt.com", workspace_id=ALPHA_WS, role_keys=frozenset({"member"})
            ),
        )
    assert await assigned_roles(migrator_engine, ALPHA, user_id) == {}


async def test_org_admin_cannot_mint_an_administrative_role(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, admins: Admins
) -> None:
    """No escalation: an Org Admin may not hand out `tenant_owner`, whose
    privileges they do not hold (the hold rule, 403 `rbac_escalation`), nor
    `platform_admin`, which no tenant role may be (404: no such role)."""
    user_id = await _sign_in(app_engine, "crony@fpt.com")
    before = await open_proposals(migrator_engine, ALPHA)

    with pytest.raises(PermissionDeniedError) as refused:
        await _grant(app_engine, admins, "crony@fpt.com", ALPHA_WS, "tenant_owner")
    assert refused.value.details["reason_code"] == "rbac_escalation"

    with pytest.raises(NotFoundError, match="unknown role"):
        await _grant(app_engine, admins, "crony@fpt.com", ALPHA_WS, "platform_admin")

    assert await assigned_roles(migrator_engine, ALPHA, user_id) == {}
    assert await open_proposals(migrator_engine, ALPHA) == before


async def test_grant_into_another_tenants_workspace_is_refused(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, admins: Admins
) -> None:
    """Tenant rail: an admin of alpha cannot place someone in beta's workspace."""
    user_id = await _sign_in(app_engine, "outsider@fpt.com")
    beta, beta_ws = uuid.uuid4(), uuid.uuid4()
    async with migrator_engine.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(id=beta, slug=f"beta-{beta.hex[:8]}", name="BETA")
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=beta_ws, tenant_id=beta, slug="beta-sales", name="Sales"
            )
        )
    before = await open_proposals(migrator_engine, ALPHA)

    with pytest.raises(NotFoundError, match="workspace"):
        await _grant(app_engine, admins, "outsider@fpt.com", beta_ws, "member")
    assert await assigned_roles(migrator_engine, ALPHA, user_id) == {}
    assert await assigned_roles(migrator_engine, beta, user_id) == {}
    assert await open_proposals(migrator_engine, ALPHA) == before


async def test_revoke_removes_access(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, admins: Admins
) -> None:
    user_id = await _sign_in(app_engine, "leaver@fpt.com")
    _, proposals = await _grant(app_engine, admins, "leaver@fpt.com", ALPHA_WS, "member")
    await confirm_all(app_engine, admins.checker_context, proposals)

    await _revoke_handler(app_engine).handle(
        admins.maker_context, RevokeMembership(user_id=user_id, workspace_id=ALPHA_WS)
    )

    assert await assigned_roles(migrator_engine, ALPHA, user_id) == {}
    assert await _audit_actions(app_engine, user_id) == [
        "platform.membership.grant",
        "platform.membership.revoke",
        "platform.role_assignment.grant",
        "platform.role_change.confirmed",
        "platform.role_change.proposed",
    ]
