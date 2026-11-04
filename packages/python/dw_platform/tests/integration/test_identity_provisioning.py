"""Integration: first-login provisioning is default-deny.

A brand-new verified identity gets a platform user but no membership, so it
lands on the "no workspace, contact an admin" state. The legacy
auto-provision-into-the-default-tenant behaviour survives only behind an
explicit flag, which the demo seed and these tests can opt into.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.seed_env import seed_test_env

pytestmark = pytest.mark.integration

# uuid5 of tenant-alpha / main — matches dw_platform.testing.seed_env and the API's
# default_tenant_id/default_workspace_id settings.
DEFAULT_TENANT = uuid.UUID("d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d")
DEFAULT_WORKSPACE = uuid.UUID("64764894-718d-5558-ba17-9a2949214063")


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


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    # Seed first so the default tenant/workspace exist for the opt-in path.
    await seed_test_env(db_urls.migrator)
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _grant_membership_in_new_tenant(
    migrator: AsyncEngine, user_id: uuid.UUID, *, slug: str
) -> uuid.UUID:
    """As the migrator (BYPASSRLS), stand up a fresh tenant/workspace and put
    the user in it — the shape an Org Admin's grant produces. Returns the new
    tenant id."""
    tenant_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(id=tenant_id, slug=slug, name=slug.upper())
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=workspace_id, tenant_id=tenant_id, slug=f"{slug}-sales", name="Sales"
            )
        )
        await add_tenant_member(conn, tenant_id, user_id)
        await conn.execute(
            sa.insert(tables.memberships).values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                role_keys=["member"],
            )
        )
    return tenant_id


def _bootstrap(engine: AsyncEngine, *, auto_provision: bool) -> SqlIdentityBootstrap:
    return SqlIdentityBootstrap(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        default_tenant_id=DEFAULT_TENANT,
        default_workspace_id=DEFAULT_WORKSPACE,
        auto_provision_default_membership=auto_provision,
    )


async def test_a_new_identity_gets_no_membership_by_default(app_engine: AsyncEngine) -> None:
    """Default-deny: the user is created, but with nothing to enter."""
    bootstrap = _bootstrap(app_engine, auto_provision=False)
    identity = _Identity(subject=f"sub-{uuid.uuid4()}", email="newcomer@example.com")

    view = await bootstrap.bootstrap(identity)

    assert view.email == "newcomer@example.com"
    assert view.memberships == ()  # no workspace → "contact an admin"


async def test_email_links_a_keycloak_login_to_the_imported_user(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The SugarCRM importer creates people as ``sugar:<name>`` and their records
    hang off that user id. When they later sign in through Keycloak — a different
    subject, the same email — they must land on their own account, not a fresh
    empty one (and not crash on the unique email)."""
    bootstrap = _bootstrap(app_engine, auto_provision=False)

    # The importer's user: its own subject, a real email, and no sign-in, so no
    # login identity (an importer writes the row; it does not sign anyone in).
    imported_id = uuid.uuid4()
    async with migrator_engine.begin() as conn:
        await conn.execute(
            sa.insert(tables.users).values(
                id=imported_id,
                subject="sugar:tuanbta@fpt.com",
                email="tuanbta@fpt.com",
                display_name="Tuan Bui Trieu Anh",
            )
        )
    # Their workspace + records would reference this user id.
    await _grant_membership_in_new_tenant(migrator_engine, imported_id, slug="fis")

    # Tuan signs in through Keycloak: same email, Keycloak's own subject/issuer.
    login = await bootstrap.bootstrap(_Identity(subject="kc-sub-abc", email="TuanBTA@fpt.com"))

    # Same person: resolves to the imported user, with their workspace and name.
    assert login.principal_id == imported_id
    assert login.display_name == "Tuan Bui Trieu Anh"
    assert {m.tenant_slug for m in login.memberships} == {"fis"}

    # The Keycloak identity is now linked, so a later login resolves directly.
    async with async_sessionmaker(app_engine, expire_on_commit=False)() as session:
        issuers = (
            (
                await session.execute(
                    sa.select(tables.external_identities.c.issuer).where(
                        tables.external_identities.c.user_id == imported_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert issuers == ["https://issuer.test/realms/dw"]


async def test_the_opt_in_flag_restores_the_default_membership(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The legacy path still places a person when a deployment explicitly asks
    for it, and grants nothing: assigning `member` takes two people
    (tenant-rbac ticket 03, step 9), so the membership carries no role, no
    legacy key and no scope until an administrator's proposal is confirmed."""
    bootstrap = _bootstrap(app_engine, auto_provision=True)
    identity = _Identity(subject=f"sub-{uuid.uuid4()}", email="demo@example.com")

    view = await bootstrap.bootstrap(identity)

    assert [m.tenant_id for m in view.memberships] == [DEFAULT_TENANT]
    lookup = SqlMembershipLookup(async_sessionmaker(app_engine, expire_on_commit=False))
    access = await lookup.find_access(
        identity.subject, identity.issuer, DEFAULT_TENANT, view.memberships[0].workspace_id
    )
    assert access is not None
    assert access.roles == frozenset() and access.scopes == frozenset()
    async with migrator_engine.connect() as conn:
        held = (
            await conn.execute(
                sa.text(
                    "SELECT m.role_keys, m.permission_set_keys,"
                    " (SELECT count(*) FROM platform.role_assignments a"
                    "  WHERE a.membership_id = m.id) AS assigned"
                    " FROM platform.memberships m WHERE m.user_id = :u"
                ),
                {"u": view.principal_id},
            )
        ).one()
    assert (held.role_keys, held.permission_set_keys, held.assigned) == ([], [], 0)


async def test_bootstrap_sees_a_membership_in_a_non_default_tenant(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The real multi-tenant flow: a person logs in (default-deny, no access),
    an admin grants them a membership in *their* tenant — not the default one —
    and on the next login bootstrap returns it. Before migration 0065 the read
    was pinned to the default tenant and this came back empty."""
    bootstrap = _bootstrap(app_engine, auto_provision=False)
    identity = _Identity(subject=f"sub-{uuid.uuid4()}", email="partner@example.com")

    first = await bootstrap.bootstrap(identity)
    assert first.memberships == ()  # default-deny on first login

    other_tenant = await _grant_membership_in_new_tenant(
        migrator_engine, first.principal_id, slug=f"beta-{uuid.uuid4().hex[:8]}"
    )

    second = await bootstrap.bootstrap(identity)
    assert [m.tenant_id for m in second.memberships] == [other_tenant]
    assert second.memberships[0].workspace_name == "Sales"


async def _membership(
    migrator: AsyncEngine,
    user_id: uuid.UUID,
    *,
    slug: str,
    permission_sets: list[str],
) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with a plan, one workspace and the user in it as `member`
    with these permission sets."""
    tenant_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.tenants).values(id=tenant_id, slug=slug, name=slug.upper())
        )
        await conn.execute(
            sa.insert(tables.entitlements).values(
                id=uuid.uuid4(), tenant_id=tenant_id, plan_id="professional"
            )
        )
        await conn.execute(
            sa.insert(tables.workspaces).values(
                id=workspace_id, tenant_id=tenant_id, slug=f"{slug}-ops", name="Ops"
            )
        )
        await add_tenant_member(conn, tenant_id, user_id)
        await conn.execute(
            sa.insert(tables.memberships).values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                role_keys=["member"],
                permission_set_keys=permission_sets,
            )
        )
    return tenant_id, workspace_id


async def test_bootstrap_scopes_are_the_access_contexts_permission_sets_included(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """tenant-rbac R2.1, R2.2 (RB4, RB5): sign-in names the two workspaces and
    nothing held there (R2.6: `/me` answers that); the access context of a
    request holds `approvals.decide` through `approver_boost` in tenant A and
    not as plain `member` in tenant B, so nothing is pooled across tenants."""
    bootstrap = _bootstrap(app_engine, auto_provision=False)
    identity = _Identity(subject=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4().hex[:8]}@rbac.test")
    principal = (await bootstrap.bootstrap(identity)).principal_id
    tag = uuid.uuid4().hex[:8]
    a = await _membership(
        migrator_engine, principal, slug=f"a-{tag}", permission_sets=["approver_boost"]
    )
    b = await _membership(migrator_engine, principal, slug=f"b-{tag}", permission_sets=[])

    memberships = (await bootstrap.bootstrap(identity)).memberships
    assert {m.tenant_id for m in memberships} >= {a[0], b[0]}
    assert not any(hasattr(m, "scopes") or hasattr(m, "roles") for m in memberships)
    lookup = SqlMembershipLookup(async_sessionmaker(app_engine, expire_on_commit=False))
    held = {}
    for tenant_id, workspace_id in (a, b):
        access = await lookup.find_access(
            identity.subject, identity.issuer, tenant_id, workspace_id
        )
        assert access is not None
        held[tenant_id] = access.scopes
    assert "approvals.decide" in held[a[0]]
    assert "approvals.decide" not in held[b[0]]
