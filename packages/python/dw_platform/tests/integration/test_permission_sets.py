"""Integration: Permission Sets add scopes on top of a role (ADR-001 Phase 3).

The seed gives Diệu (an AM) the ``approver_boost`` set, so her resolved access
carries ``approvals.decide`` her role does not — the whole point. An admin can
assign another set and it shows up once a second holder of
``platform.roles.bind`` confirms it (tenant-rbac ticket 03, R7.1); a critical
set carrying a key the admin does not hold is refused (the hold rule, no
escalation).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from rbac_world import (
    Admins,
    assignment_service,
    confirm_all,
    open_proposals,
    plant_admins,
    tenant_role,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import NotFoundError, PermissionDeniedError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.application.role_assignments import SetPermissionSets
from dw_platform.testing.seed_env import seed_test_env

pytestmark = pytest.mark.integration

ALPHA = uuid.UUID("d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d")
ALPHA_WS = uuid.UUID("64764894-718d-5558-ba17-9a2949214063")
# The dev issuer: these users are known by `users.subject` alone, which only
# the dev issuer resolves (foundations-hardening R4.3).
ISSUER = "dw-dev"


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


async def _uid(engine: AsyncEngine, subject: str) -> uuid.UUID:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        row = (
            await session.execute(
                sa.select(tables.users.c.id).where(tables.users.c.subject == subject)
            )
        ).scalar_one()
    return uuid.UUID(str(row))


def _lookup(engine: AsyncEngine) -> SqlMembershipLookup:
    return SqlMembershipLookup(async_sessionmaker(engine, expire_on_commit=False))


async def test_a_seeded_permission_set_adds_a_scope_the_role_lacks(
    app_engine: AsyncEngine,
) -> None:
    access = await _lookup(app_engine).find_access("dev|dieu.hoang", ISSUER, ALPHA, ALPHA_WS)
    assert access is not None
    # From the approver_boost set, not from the AM role.
    assert "approvals.decide" in access.scopes


async def test_admin_assigns_a_set_and_it_takes_effect(
    app_engine: AsyncEngine, admins: Admins
) -> None:
    an = await _uid(app_engine, "dev|an.nguyen")
    before = await _lookup(app_engine).find_access("dev|an.nguyen", ISSUER, ALPHA, ALPHA_WS)
    assert before is not None and "approvals.decide" not in before.scopes

    outcome = await assignment_service(app_engine).set_permission_sets(
        admins.maker_context,
        SetPermissionSets(user_id=an, permission_set_keys=frozenset({"approver_boost"})),
    )
    assert len(outcome.proposals) == 1
    proposed = await _lookup(app_engine).find_access("dev|an.nguyen", ISSUER, ALPHA, ALPHA_WS)
    assert proposed is not None and "approvals.decide" not in proposed.scopes

    await confirm_all(app_engine, admins.checker_context, outcome.proposals)

    after = await _lookup(app_engine).find_access("dev|an.nguyen", ISSUER, ALPHA, ALPHA_WS)
    assert after is not None and "approvals.decide" in after.scopes


async def test_unknown_set_is_refused(app_engine: AsyncEngine, admins: Admins) -> None:
    an = await _uid(app_engine, "dev|an.nguyen")
    with pytest.raises(NotFoundError):
        await assignment_service(app_engine).set_permission_sets(
            admins.maker_context,
            SetPermissionSets(user_id=an, permission_set_keys=frozenset({"ghost"})),
        )


async def _set_restricted(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.update(tables.tenants)
            .where(tables.tenants.c.id == ALPHA)
            .values(record_visibility="restricted")
        )


async def test_platform_admin_sees_everything_in_a_restricted_tenant(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """ADR-003 roll-up must honour the platform-admin bypass. Chi is a
    platform_admin with no place in the reporting tree, so her subtree is only
    herself. Before the fix, a restricted tenant narrowed her to that subtree and
    she saw no records at all; the bypass gives her the whole workspace (None)."""
    await _set_restricted(migrator_engine)

    chi = await _lookup(app_engine).find_access("dev|chi.le", ISSUER, ALPHA, ALPHA_WS)
    assert chi is not None
    assert chi.record_visibility == "restricted"
    assert chi.visible_owners is None  # sees everything, not just her own subtree


async def test_restricted_tenant_still_narrows_a_plain_rep(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The bypass is only for the admin: a plain sales rep is still rolled up to
    their own subtree, so the fix does not widen anyone it should not."""
    await _set_restricted(migrator_engine)

    an = await _lookup(app_engine).find_access("dev|an.nguyen", ISSUER, ALPHA, ALPHA_WS)
    assert an is not None
    assert an.visible_owners is not None
    assert an.visible_owners == frozenset({an.principal_id})


async def test_org_admin_cannot_assign_an_administrative_set(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, admins: Admins
) -> None:
    """No escalation: a set carrying `platform.roles.write`, a critical key
    `org_admin` does not hold, is refused 403 `rbac_escalation` naming the key,
    nothing proposed (the hold rule, ADR-0104 decision 6)."""
    an = await _uid(app_engine, "dev|an.nguyen")
    key = f"superpowers_{uuid.uuid4().hex[:8]}"
    async with migrator_engine.begin() as conn:
        await conn.execute(
            sa.insert(tables.permission_sets).values(
                key=key, name="Superpowers", scopes=["platform.roles.write"]
            )
        )
    await tenant_role(migrator_engine, ALPHA, key)
    before = await open_proposals(migrator_engine, ALPHA)

    with pytest.raises(PermissionDeniedError) as refused:
        await assignment_service(app_engine).set_permission_sets(
            admins.maker_context,
            SetPermissionSets(user_id=an, permission_set_keys=frozenset({key})),
        )
    assert refused.value.details["reason_code"] == "rbac_escalation"
    assert refused.value.details["keys"] == ["platform.roles.write:tenant"]
    assert await open_proposals(migrator_engine, ALPHA) == before


@pytest.fixture
async def ceiling_reset(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    """Put tenant ALPHA's ceiling back to its default around a test.

    The test database lives for the whole session and ALPHA is shared by every
    module. A test that set the ceiling and left it leaked into the next module
    that read the default — measured: `test_permission_sets` saw A1 because
    `test_admin_console` ran first and set it, green alone and red together.
    """

    async def _reset() -> None:
        async with migrator_engine.begin() as conn:
            await conn.execute(
                sa.update(tables.tenants)
                .where(tables.tenants.c.id == ALPHA)
                .values(max_autonomy_level="A4")
            )

    await _reset()
    yield
    await _reset()


# --------------------------------------------------------- autonomy ceiling --
#
# The tenant's ceiling travels the same road as `record_visibility`: read in the
# same tenants join, carried on the access, stamped on the run. Asserted against
# real SQL because the column, its default and its CHECK constraint are 0006.


async def _set_ceiling(engine: AsyncEngine, level: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.update(tables.tenants)
            .where(tables.tenants.c.id == ALPHA)
            .values(max_autonomy_level=level)
        )


async def test_a_tenant_with_no_ceiling_holds_its_workers_to_nothing_extra(
    app_engine: AsyncEngine, ceiling_reset: None
) -> None:
    """A4 is the absence of a tenant restriction, not a grant: every run is still
    capped by the level its worker was built for."""
    an = await _lookup(app_engine).find_access("dev|an.nguyen", ISSUER, ALPHA, ALPHA_WS)

    assert an is not None
    assert an.max_autonomy_level == "A4"


async def test_the_lookup_carries_the_ceiling_the_tenant_set(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, ceiling_reset: None
) -> None:
    await _set_ceiling(migrator_engine, "A1")

    an = await _lookup(app_engine).find_access("dev|an.nguyen", ISSUER, ALPHA, ALPHA_WS)

    assert an is not None
    assert an.max_autonomy_level == "A1"


async def test_the_database_refuses_a_ceiling_nobody_can_read(
    migrator_engine: AsyncEngine, ceiling_reset: None
) -> None:
    """`record_visibility`, the setting this is modelled on, has no such constraint —
    only the service that writes it validates. A second writer, or a direct UPDATE,
    would leave a value no code knows how to read. This one the database refuses."""
    with pytest.raises(sa.exc.IntegrityError, match="ck_tenants_max_autonomy_level"):
        await _set_ceiling(migrator_engine, "A9")
