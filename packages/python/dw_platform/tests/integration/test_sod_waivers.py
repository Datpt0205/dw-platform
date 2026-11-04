"""Integration: a tenant's waiver of a separation-of-duty rule (6b26771e549d).

A waiver lifts one waivable rule for one tenant, on the record. What these
tests hold the database and the service to:

- a waiver lets one membership hold both sides, in that tenant only, once a
  second admin has confirmed it (f381f1694395) - never the one who proposed it;
  since tenant-rbac ticket 03 a role reaches a person when a second holder of
  `platform.roles.bind` confirms its proposal, so the rule (and the waiver) is
  judged at that confirmation;
- a role or permission set cannot gain a scope that would make a membership
  holding it break a rule its tenant has not waived;
- a rule its author did not mark waivable is a floor, for every writer;
- every waiver decision needs a reason, a scope, and leaves an audit row
  written in the same transaction;
- a waiver cannot be revoked while memberships rely on it, including when the
  revoke and the membership write race each other;
- a closed waiver is history: it cannot be reopened, rewritten or deleted.

The rules, roles, users and tenants are this file's own, with a per-test
suffix (a proposal is deleted only while its tenant is offboarding, so a shared
tenant could not drop this file's roles again).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from rbac_world import Admins, assigned_roles, assignment_service, confirm_all, plant_admins
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.separation_of_duties_repo import (
    SqlSeparationOfDutiesRepository,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.role_assignments import SetMemberships, WorkspaceRoles
from dw_platform.application.separation_of_duties import (
    SOD_WAIVERS_WRITE,
    ConfirmWaiver,
    RevokeWaiver,
    SeparationOfDutiesService,
    WaiveRule,
)
from dw_platform.testing.rbac import (
    catalogue_test_keys,
    plant_membership,
    plant_person,
    plant_tenant,
    unregister_key,
)

pytestmark = pytest.mark.integration

REASON = "Công ty 3 người, một người vừa đặt hàng vừa thanh toán"


@dataclass(frozen=True)
class _Catalogue:
    rule: str
    floor: str
    orderer: str
    payer: str
    # Two tenants, each with this file's roles and two admins (one proposes,
    # the other confirms a role); `alpha` is the one a test waives in.
    alpha: Admins
    beta: Admins

    def tenant(self, beta: bool = False) -> Admins:
        return self.beta if beta else self.alpha


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def catalogue(migrator_engine: AsyncEngine) -> AsyncIterator[_Catalogue]:
    """A waivable rule and a floor over the same two scopes, one role on each
    side, and two tenants holding those roles."""
    suffix = uuid.uuid4().hex[:10]
    rule, floor = f"sod_test_waivable_{suffix}", f"sod_test_floor_{suffix}"
    orderer, payer = f"test_orderer_{suffix}", f"test_payer_{suffix}"
    order, pay = f"test.{suffix}.order", f"test.{suffix}.pay"
    async with migrator_engine.begin() as conn:
        await catalogue_test_keys(conn, [order, pay])
        for key, scopes in ((orderer, [order]), (payer, [pay])):
            await conn.execute(sa.insert(tables.roles).values(key=key, name=key, scopes=scopes))
        await conn.execute(
            sa.insert(tables.sod_rules).values(
                key=rule,
                description="orders are not paid by who placed them",
                left_scopes=[order],
                right_scopes=[pay],
                waivable=True,
            )
        )
        tenants = [await plant_tenant(conn), await plant_tenant(conn)]
        for tenant in tenants:
            for key in (orderer, payer):
                await conn.execute(
                    sa.text("SELECT platform.install_role_template(:t, :k)"),
                    {"t": tenant.tenant_id, "k": key},
                )
    alpha, beta = [await plant_admins(migrator_engine, t.tenant_id, t.main) for t in tenants]
    yield _Catalogue(rule, floor, orderer, payer, alpha, beta)
    async with migrator_engine.begin() as conn:
        rule_keys = [rule, floor]
        await conn.execute(
            sa.delete(tables.sod_waivers).where(tables.sod_waivers.c.rule_key.in_(rule_keys))
        )
        await conn.execute(sa.delete(tables.sod_rules).where(tables.sod_rules.c.key.in_(rule_keys)))
        # The tenants' clones keep their rows (their proposals name them) and
        # lose their privileges with the keys; then the templates.
        await conn.execute(sa.delete(tables.roles).where(tables.roles.c.key.in_([orderer, payer])))
        for key in (order, pay):
            await unregister_key(conn, key)


async def _add_floor(engine: AsyncEngine, made: _Catalogue) -> None:
    """The same conflict as `made.rule`, with its author not letting any
    tenant waive it."""
    async with engine.begin() as conn:
        rule = (
            await conn.execute(
                sa.select(tables.sod_rules).where(tables.sod_rules.c.key == made.rule)
            )
        ).one()
        await conn.execute(
            sa.insert(tables.sod_rules).values(
                key=made.floor,
                description="a floor",
                left_scopes=rule.left_scopes,
                right_scopes=rule.right_scopes,
            )
        )


def _admin(made: _Catalogue, beta: bool = False) -> AccessContext:
    """A holder of the waiver scope in one of the two tenants; the waiver
    service asks the authorization port, never the role tables."""
    admins = made.tenant(beta)
    return AccessContext(
        tenant_id=admins.tenant_id,
        workspace_id=admins.workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        scopes=frozenset({"platform.members.write", "platform.roles.read", SOD_WAIVERS_WRITE}),
        plan_id="professional",
    )


def _service(engine: AsyncEngine) -> SeparationOfDutiesService:
    return SeparationOfDutiesService(
        SqlSeparationOfDutiesRepository(async_sessionmaker(engine, expire_on_commit=False)),
        ScopeAuthorizationService(),
        SystemClock(),
        Uuid4Generator(),
    )


async def _user(migrator: AsyncEngine, made: _Catalogue, beta: bool = False) -> uuid.UUID:
    """A member of the tenant with a membership in its workspace and no role."""
    admins = made.tenant(beta)
    async with migrator.begin() as conn:
        user = await plant_person(conn, admins.tenant_id)
        await plant_membership(conn, admins.tenant_id, admins.workspace_id, user)
    return user


async def _propose(
    engine: AsyncEngine, made: _Catalogue, user_id: uuid.UUID, *roles: str, beta: bool = False
) -> tuple[uuid.UUID, ...]:
    """The person's roles in the workspace become exactly `roles`: what goes is
    revoked at once, each role that comes is proposed by the tenant's maker."""
    admins = made.tenant(beta)
    outcome = await assignment_service(engine).set_memberships(
        admins.maker_context,
        SetMemberships(user_id, (WorkspaceRoles(admins.workspace_id, frozenset(roles)),)),
    )
    return outcome.proposals


async def _grant(
    engine: AsyncEngine, made: _Catalogue, user_id: uuid.UUID, *roles: str, beta: bool = False
) -> None:
    """`_propose`, each proposal confirmed by the tenant's checker in key order;
    the first refusal is raised."""
    proposals = await _propose(engine, made, user_id, *roles, beta=beta)
    await confirm_all(engine, made.tenant(beta).checker_context, proposals)


async def _roles_of(
    migrator: AsyncEngine, made: _Catalogue, user_id: uuid.UUID, beta: bool = False
) -> list[str]:
    admins = made.tenant(beta)
    return (await assigned_roles(migrator, admins.tenant_id, user_id)).get(admins.workspace_id, [])


async def _waived(
    engine: AsyncEngine, made: _Catalogue, rule_key: str, reason: str = REASON
) -> None:
    """Proposed by one admin and confirmed by another: a waiver in effect."""
    service = _service(engine)
    await service.waive(_admin(made), WaiveRule(rule_key, reason))
    await service.confirm(_admin(made), ConfirmWaiver(rule_key, "đã xem, đồng ý"))


async def _scoped(conn: AsyncConnection, tenant: uuid.UUID) -> None:
    await conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})


async def _as_checker(conn: AsyncConnection, made: _Catalogue) -> None:
    """Bound to alpha as its checker, the person who confirms a role there."""
    await conn.execute(
        sa.text(
            "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"
        ),
        {"t": str(made.alpha.tenant_id), "u": str(made.alpha.checker)},
    )


async def _confirm_in(conn: AsyncConnection, made: _Catalogue, request: uuid.UUID) -> None:
    """What `RoleAdminService.confirm` writes for an `assignment_grant`, in the
    caller's open transaction as alpha's checker: the proposal confirmed, then
    its assignment (which the separation-of-duty trigger judges)."""
    await conn.execute(
        sa.text(
            "UPDATE platform.role_change_requests SET status = 'confirmed',"
            " confirmed_by = :u, decided_at = now() WHERE id = :id"
        ),
        {"u": made.alpha.checker, "id": request},
    )
    await conn.execute(
        sa.text("SELECT set_config('app.role_change_id', :id, true)"), {"id": str(request)}
    )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.role_assignments"
            " (id, tenant_id, workspace_id, membership_id, role_id)"
            " SELECT gen_random_uuid(), r.tenant_id, CAST(q.payload->>'workspace_id' AS uuid),"
            "   CAST(q.payload->>'membership_id' AS uuid), r.id"
            " FROM platform.role_change_requests q JOIN platform.tenant_roles r ON r.id = q.role_id"
            " WHERE q.id = :id"
        ),
        {"id": request},
    )


async def _audit_actions(
    engine: AsyncEngine, made: _Catalogue, rule_key: str
) -> list[tuple[str, object]]:
    async with engine.begin() as conn:
        await _scoped(conn, made.alpha.tenant_id)
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT action, details FROM platform.audit_events"
                    " WHERE resource_type = 'sod_rule' AND resource_id = :k ORDER BY occurred_at"
                ),
                {"k": rule_key},
            )
        ).all()
    return [(row.action, row.details.get("reason")) for row in rows]


async def _open_waivers(
    engine: AsyncEngine, made: _Catalogue, rule_key: str, beta: bool = False
) -> int:
    async with engine.begin() as conn:
        await _scoped(conn, made.tenant(beta).tenant_id)
        return int(
            await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.sod_waivers"
                    " WHERE rule_key = :k AND revoked_at IS NULL"
                ),
                {"k": rule_key},
            )
            or 0
        )


# ---- what a waiver lifts, and for whom ------------------------------------


async def test_a_waived_rule_lets_one_membership_hold_both_sides(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    user_id = await _user(migrator_engine, catalogue)
    with pytest.raises(ConflictError):
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    proposer, confirmer = _admin(catalogue), _admin(catalogue)
    await _service(app_engine).waive(proposer, WaiveRule(catalogue.rule, REASON))
    # Proposed, not confirmed: it lifts nothing yet.
    with pytest.raises(ConflictError):
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)
    listed = {r.key: r for r in await _service(app_engine).list_rules(_admin(catalogue))}
    pending = listed[catalogue.rule].waiver
    assert pending is not None and pending.confirmed_by is None

    await _service(app_engine).confirm(confirmer, ConfirmWaiver(catalogue.rule, "đồng ý"))
    await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    listed = {r.key: r for r in await _service(app_engine).list_rules(_admin(catalogue))}
    waiver = listed[catalogue.rule].waiver
    assert waiver is not None and waiver.reason == REASON
    assert (waiver.granted_by, waiver.confirmed_by) == (
        proposer.principal_id,
        confirmer.principal_id,
    )
    assert await _audit_actions(app_engine, catalogue, catalogue.rule) == [
        ("platform.sod.waive", REASON),
        ("platform.sod.waiver_confirm", "đồng ý"),
    ]


async def test_one_tenants_waiver_lifts_nothing_for_another(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    await _service(app_engine).waive(_admin(catalogue), WaiveRule(catalogue.rule, REASON))
    beta_admin = _admin(catalogue, beta=True)

    beta_user = await _user(migrator_engine, catalogue, beta=True)
    with pytest.raises(ConflictError):
        await _grant(
            app_engine, catalogue, beta_user, catalogue.orderer, catalogue.payer, beta=True
        )
    # Beta sees the rule and no waiver, and cannot revoke Alpha's.
    listed = {r.key: r for r in await _service(app_engine).list_rules(beta_admin)}
    assert listed[catalogue.rule].waiver is None
    with pytest.raises(NotFoundError):
        await _service(app_engine).revoke(beta_admin, RevokeWaiver(catalogue.rule, "not ours"))
    assert await _open_waivers(app_engine, catalogue, catalogue.rule, beta=True) == 0
    assert await _open_waivers(app_engine, catalogue, catalogue.rule) == 1


# ---- floors ------------------------------------------------------------------


async def test_a_rule_its_author_did_not_mark_waivable_cannot_be_waived(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    await _add_floor(migrator_engine, catalogue)

    with pytest.raises(ConflictError, match="cannot be waived"):
        await _service(app_engine).waive(_admin(catalogue), WaiveRule(catalogue.floor, REASON))
    async with app_engine.begin() as conn:
        await _scoped(conn, catalogue.alpha.tenant_id)
        assert (
            await conn.scalar(
                sa.text("SELECT count(*) FROM platform.sod_waivers WHERE rule_key = :k"),
                {"k": catalogue.floor},
            )
            == 0
        )
    assert await _audit_actions(app_engine, catalogue, catalogue.floor) == []
    # Not for the migrator either: the guard is the database's.
    with pytest.raises(IntegrityError, match="cannot be waived"):
        async with migrator_engine.begin() as conn:
            await conn.execute(
                sa.insert(tables.sod_waivers).values(
                    id=uuid.uuid4(),
                    tenant_id=catalogue.alpha.tenant_id,
                    rule_key=catalogue.floor,
                    reason=REASON,
                    granted_by=uuid.uuid4(),
                )
            )


async def test_waiving_the_rule_lifts_nothing_while_a_floor_forbids_the_same_pair(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    await _add_floor(migrator_engine, catalogue)
    await _waived(app_engine, catalogue, catalogue.rule)
    user_id = await _user(migrator_engine, catalogue)

    with pytest.raises(ConflictError) as refused:
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)
    assert refused.value.details["rule"] == catalogue.floor


# ---- who may decide, and what a decision needs --------------------------------


async def test_waiving_needs_the_waiver_scope_and_a_reason(
    app_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    member = AccessContext(
        tenant_id=catalogue.alpha.tenant_id,
        workspace_id=catalogue.alpha.workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        scopes=frozenset({"platform.members.write", "platform.roles.read"}),
        plan_id="professional",
    )
    with pytest.raises(PermissionDeniedError):
        await _service(app_engine).waive(member, WaiveRule(catalogue.rule, REASON))
    with pytest.raises(DomainError, match="reason"):
        await _service(app_engine).waive(_admin(catalogue), WaiveRule(catalogue.rule, "   "))
    assert await _open_waivers(app_engine, catalogue, catalogue.rule) == 0


async def test_org_admin_holds_the_waiver_scope(app_engine: AsyncEngine) -> None:
    """Otherwise nobody in a tenant could reach the feature at all."""
    async with app_engine.connect() as conn:
        scopes = await conn.scalar(
            sa.text("SELECT scopes FROM platform.roles WHERE key = 'org_admin'")
        )
    assert SOD_WAIVERS_WRITE in scopes


async def test_a_second_open_waiver_of_one_rule_is_a_conflict(
    app_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    await _service(app_engine).waive(_admin(catalogue), WaiveRule(catalogue.rule, REASON))
    with pytest.raises(ConflictError, match="already waived"):
        await _service(app_engine).waive(_admin(catalogue), WaiveRule(catalogue.rule, REASON))
    assert await _audit_actions(app_engine, catalogue, catalogue.rule) == [
        ("platform.sod.waive", REASON)
    ]


# ---- revoking ----------------------------------------------------------------


async def test_a_waiver_memberships_rely_on_cannot_be_revoked(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    service = _service(app_engine)
    await _waived(app_engine, catalogue, catalogue.rule)
    user_id = await _user(migrator_engine, catalogue)
    await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    with pytest.raises(ConflictError) as refused:
        await service.revoke(_admin(catalogue), RevokeWaiver(catalogue.rule, "đã tuyển thêm người"))
    assert refused.value.details["memberships"] == 1
    assert await _open_waivers(app_engine, catalogue, catalogue.rule) == 1

    # Once the membership no longer holds both sides, the revoke goes through
    # and the rule applies again.
    await _grant(app_engine, catalogue, user_id, catalogue.orderer)
    await service.revoke(_admin(catalogue), RevokeWaiver(catalogue.rule, "đã tuyển thêm người"))
    assert await _open_waivers(app_engine, catalogue, catalogue.rule) == 0
    with pytest.raises(ConflictError):
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)
    assert await _audit_actions(app_engine, catalogue, catalogue.rule) == [
        ("platform.sod.waive", REASON),
        ("platform.sod.waiver_confirm", "đã xem, đồng ý"),
        ("platform.sod.waiver_revoke", "đã tuyển thêm người"),
    ]


async def test_revoking_without_an_open_waiver_is_not_found(
    app_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    with pytest.raises(NotFoundError):
        await _service(app_engine).revoke(_admin(catalogue), RevokeWaiver(catalogue.rule, "x"))
    assert await _audit_actions(app_engine, catalogue, catalogue.rule) == []


async def test_a_revoke_waits_for_a_grant_relying_on_the_waiver_then_refuses(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    """The grant is the confirmation of a proposal adding the other side: it
    holds the waiver FOR SHARE until it commits, the revoke waits for it and
    then finds a person relying on the waiver."""
    await _waived(app_engine, catalogue, catalogue.rule)
    user_id = await _user(migrator_engine, catalogue)
    await _grant(app_engine, catalogue, user_id, catalogue.orderer)
    (request,) = await _propose(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    async with app_engine.connect() as grant_conn:
        grant = await grant_conn.begin()
        await _as_checker(grant_conn, catalogue)
        await _confirm_in(grant_conn, catalogue, request)
        revoke = asyncio.create_task(
            _service(app_engine).revoke(_admin(catalogue), RevokeWaiver(catalogue.rule, "race"))
        )
        await asyncio.sleep(1.0)
        assert not revoke.done(), "the revoke did not wait for the grant relying on the waiver"
        await grant.commit()
    with pytest.raises(ConflictError):
        await revoke
    assert await _open_waivers(app_engine, catalogue, catalogue.rule) == 1
    assert await _roles_of(migrator_engine, catalogue, user_id) == sorted(
        [catalogue.orderer, catalogue.payer]
    )


async def test_a_grant_arriving_during_a_revoke_waits_then_is_refused(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    """The confirmation of the other side, through the service, arrives while a
    revoke of the waiver is in flight: it waits for the revoke, then the rule
    applies again and refuses it."""
    await _waived(app_engine, catalogue, catalogue.rule)
    user_id = await _user(migrator_engine, catalogue)
    await _grant(app_engine, catalogue, user_id, catalogue.orderer)
    proposals = await _propose(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    async with app_engine.connect() as revoke_conn:
        revoking = await revoke_conn.begin()
        await _scoped(revoke_conn, catalogue.alpha.tenant_id)
        await revoke_conn.execute(
            sa.text(
                "UPDATE platform.sod_waivers"
                " SET revoked_at = now(), revoked_by = :who, revoke_reason = 'race'"
                " WHERE rule_key = :k AND revoked_at IS NULL"
            ),
            {"who": uuid.uuid4(), "k": catalogue.rule},
        )
        grant = asyncio.create_task(
            confirm_all(app_engine, catalogue.alpha.checker_context, proposals)
        )
        await asyncio.sleep(1.0)
        assert not grant.done(), "the grant did not wait for the revoke in flight"
        await revoking.commit()
    with pytest.raises(ConflictError) as refused:
        await grant
    assert refused.value.details["rule"] == catalogue.rule
    assert await _roles_of(migrator_engine, catalogue, user_id) == [catalogue.orderer]


# ---- a decision is history ---------------------------------------------------


async def test_a_waiver_can_be_revoked_once_and_never_rewritten_or_deleted(
    app_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    service = _service(app_engine)
    await service.waive(_admin(catalogue), WaiveRule(catalogue.rule, REASON))

    rewrites = (
        "UPDATE platform.sod_waivers SET reason = 'rewritten' WHERE rule_key = :k",
        "UPDATE platform.sod_waivers SET granted_by = gen_random_uuid() WHERE rule_key = :k",
        # Revoking is the one update allowed; it may not rewrite the decision
        # it closes on the way.
        "UPDATE platform.sod_waivers SET revoked_at = now(), revoked_by = gen_random_uuid(),"
        " revoke_reason = 'closing', reason = 'rewritten' WHERE rule_key = :k",
    )
    for statement in rewrites:
        with pytest.raises(IntegrityError, match="revoked, once"):
            async with app_engine.begin() as conn:
                await _scoped(conn, catalogue.alpha.tenant_id)
                await conn.execute(sa.text(statement), {"k": catalogue.rule})

    await service.revoke(_admin(catalogue), RevokeWaiver(catalogue.rule, "không cần nữa"))
    with pytest.raises(IntegrityError, match="revoked, once"):
        async with app_engine.begin() as conn:
            await _scoped(conn, catalogue.alpha.tenant_id)
            await conn.execute(
                sa.text(
                    "UPDATE platform.sod_waivers"
                    " SET revoked_at = NULL, revoked_by = NULL, revoke_reason = NULL"
                    " WHERE rule_key = :k"
                ),
                {"k": catalogue.rule},
            )
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with app_engine.begin() as conn:
            await _scoped(conn, catalogue.alpha.tenant_id)
            await conn.execute(
                sa.text("DELETE FROM platform.sod_waivers WHERE rule_key = :k"),
                {"k": catalogue.rule},
            )
    # Reopening means a new decision, with its own reason and audit row.
    await service.waive(_admin(catalogue), WaiveRule(catalogue.rule, "lại thiếu người"))
    assert [a for a, _ in await _audit_actions(app_engine, catalogue, catalogue.rule)] == [
        "platform.sod.waive",
        "platform.sod.waiver_revoke",
        "platform.sod.waive",
    ]


async def test_a_rule_made_a_floor_later_stops_honouring_its_open_waivers(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    """Clearing `waivable` is the rule author's call, made in a migration.
    From then on the tenant's open waiver lifts nothing: fail closed."""
    await _waived(app_engine, catalogue, catalogue.rule)
    async with migrator_engine.begin() as conn:
        await conn.execute(
            sa.update(tables.sod_rules)
            .where(tables.sod_rules.c.key == catalogue.rule)
            .values(waivable=False)
        )
    user_id = await _user(migrator_engine, catalogue)

    with pytest.raises(ConflictError) as refused:
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)
    assert refused.value.details["rule"] == catalogue.rule


# ---- a second person (f381f1694395) --------------------------------------------


async def test_the_admin_who_proposed_a_waiver_cannot_confirm_it(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    proposer = _admin(catalogue)
    service = _service(app_engine)
    await service.waive(proposer, WaiveRule(catalogue.rule, REASON))

    with pytest.raises(ConflictError, match="second person"):
        await service.confirm(proposer, ConfirmWaiver(catalogue.rule, "tôi tự đồng ý"))

    listed = {r.key: r for r in await service.list_rules(_admin(catalogue))}
    waiver = listed[catalogue.rule].waiver
    assert waiver is not None and waiver.confirmed_by is None
    assert await _audit_actions(app_engine, catalogue, catalogue.rule) == [
        ("platform.sod.waive", REASON)
    ]
    # The database's rule, for every writer: not even the migrator confirms a
    # waiver in its proposer's name, or creates one already confirmed.
    with pytest.raises(IntegrityError, match="second_person"):
        async with migrator_engine.begin() as conn:
            await conn.execute(
                sa.update(tables.sod_waivers)
                .where(tables.sod_waivers.c.rule_key == catalogue.rule)
                .values(
                    confirmed_by=tables.sod_waivers.c.granted_by,
                    confirmed_at=sa.func.now(),
                    confirm_reason="x",
                )
            )
    with pytest.raises(IntegrityError, match="never on creation"):
        async with migrator_engine.begin() as conn:
            await conn.execute(
                sa.insert(tables.sod_waivers).values(
                    id=uuid.uuid4(),
                    tenant_id=catalogue.beta.tenant_id,
                    rule_key=catalogue.rule,
                    reason=REASON,
                    granted_by=uuid.uuid4(),
                    confirmed_by=uuid.uuid4(),
                    confirmed_at=sa.func.now(),
                    confirm_reason="x",
                )
            )


async def test_confirming_needs_the_scope_a_reason_and_a_waiver_waiting_for_it(
    app_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    service = _service(app_engine)
    with pytest.raises(NotFoundError):
        await service.confirm(_admin(catalogue), ConfirmWaiver(catalogue.rule, "ok"))
    await service.waive(_admin(catalogue), WaiveRule(catalogue.rule, REASON))
    without_scope = AccessContext(
        tenant_id=catalogue.alpha.tenant_id,
        workspace_id=catalogue.alpha.workspace_id,
        principal_id=uuid.uuid4(),
        roles=frozenset({"org_admin"}),
        scopes=frozenset({"platform.roles.read"}),
        plan_id="professional",
    )
    with pytest.raises(PermissionDeniedError):
        await service.confirm(without_scope, ConfirmWaiver(catalogue.rule, "ok"))
    with pytest.raises(DomainError, match="reason"):
        await service.confirm(_admin(catalogue), ConfirmWaiver(catalogue.rule, "  "))

    await service.confirm(_admin(catalogue), ConfirmWaiver(catalogue.rule, "ok"))
    # Confirmed once; a second confirmation finds nothing waiting, and the
    # confirmation itself cannot be rewritten.
    with pytest.raises(NotFoundError):
        await service.confirm(_admin(catalogue), ConfirmWaiver(catalogue.rule, "again"))
    with pytest.raises(IntegrityError, match="confirmed, once"):
        async with app_engine.begin() as conn:
            await _scoped(conn, catalogue.alpha.tenant_id)
            await conn.execute(
                sa.text(
                    "UPDATE platform.sod_waivers SET confirmed_by = gen_random_uuid()"
                    " WHERE rule_key = :k"
                ),
                {"k": catalogue.rule},
            )


# A template cannot widen a role under its holders any more: a tenant's role is
# a clone a template edit never reaches (tenant-rbac R3.2), and widening the
# clone itself is judged by the AFTER trigger on `platform.tenant_role_permissions`
# (`test_tenant_roles.py::test_a_role_changed_under_two_holders_names_both`).
# The template triggers of f381f1694395 and their tests went with migration
# b5677d345bc1; `test_no_single_role_or_permission_set_in_the_catalogue_breaks_a_rule`
# keeps the catalogue honest instead.
