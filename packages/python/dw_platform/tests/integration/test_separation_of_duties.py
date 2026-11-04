"""Integration: static separation of duties, enforced by the database.

A rule says two sets of scopes must never meet in one person. Since tenant-rbac
ticket 02 the one place that decides is the AFTER trigger on
`platform.role_assignments` and `platform.tenant_role_permissions`; a write to
`memberships.role_keys` reaches it through the trigger that copies the column
into assignments. Since ticket 03 an assignment written as the application is
a proposal applied when a second holder of `platform.roles.bind` confirms it,
so the rule is judged at that confirmation. These tests reach it through every
kind of writer: the confirmed role proposal, the confirmed permission-set
proposal, raw SQL as the application carrying out a confirmed proposal (the
rbac guard lets that write through; the rule still does not), and raw SQL as
the migrator, which no rbac guard judges. They show that no writer gets around
it, and that the application reads the refusal back as a 409 naming the rule
(`separation_of_duties_conflict` reading `ck_roles_sod_memberships`).

The rule, roles and permission set here are this file's own, with a per-test
suffix, in a tenant of their own (a proposal is deleted only while its tenant
is offboarding, so a shared tenant could not drop this file's roles). The
shared catalogue's real rules are checked for consistency, not used as
fixtures.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from rbac_world import Admins, assigned_roles, assignment_service, confirm_all, plant_admins
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables
from dw_platform.application.role_assignments import (
    SetMemberships,
    SetPermissionSets,
    WorkspaceRoles,
)
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.rbac import (
    catalogue_test_keys,
    plant_membership,
    plant_person,
    plant_tenant,
    unregister_key,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _Catalogue:
    rule: str
    orderer: str
    payer: str
    bystander: str
    pay_set: str
    admins: Admins

    @property
    def tenant(self) -> uuid.UUID:
        return self.admins.tenant_id

    @property
    def workspace(self) -> uuid.UUID:
        return self.admins.workspace_id


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
    suffix = uuid.uuid4().hex[:10]
    rule = f"sod_test_order_vs_pay_{suffix}"
    orderer, payer = f"test_orderer_{suffix}", f"test_payer_{suffix}"
    bystander, pay_set = f"test_bystander_{suffix}", f"test_pay_set_{suffix}"
    order, pay = f"test.{suffix}.order", f"test.{suffix}.pay"
    keys = (order, pay, f"test.{suffix}.read")
    templates = [orderer, payer, bystander, pay_set]
    async with migrator_engine.begin() as conn:
        await catalogue_test_keys(conn, keys)
        for key, scopes in (
            (orderer, [order]),
            (payer, [pay]),
            (bystander, [f"test.{suffix}.read"]),
        ):
            await conn.execute(sa.insert(tables.roles).values(key=key, name=key, scopes=scopes))
        await conn.execute(
            sa.insert(tables.permission_sets).values(key=pay_set, name=pay_set, scopes=[pay])
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.sod_rules (key, description, left_scopes, right_scopes)"
                " VALUES (:key, 'orders are not paid by who placed them',"
                " CAST(:left AS jsonb), CAST(:right AS jsonb))"
            ),
            {"key": rule, "left": json.dumps([order]), "right": json.dumps([pay])},
        )
        tenant = await plant_tenant(conn)
        # The tenant's own roles of this file's templates (none is installed on
        # demand by an assignment since ticket 03).
        for key in templates:
            await conn.execute(
                sa.text("SELECT platform.install_role_template(:t, :k)"),
                {"t": tenant.tenant_id, "k": key},
            )
    admins = await plant_admins(migrator_engine, tenant.tenant_id, tenant.main)
    yield _Catalogue(rule, orderer, payer, bystander, pay_set, admins)
    async with migrator_engine.begin() as conn:
        # The tenant's clones keep their rows (its proposals name them) and
        # lose their privileges with the keys; then the rule and templates.
        for key in keys:
            await unregister_key(conn, key)
        await conn.execute(sa.text("DELETE FROM platform.sod_rules WHERE key = :k"), {"k": rule})
        await conn.execute(
            sa.delete(tables.permission_sets).where(tables.permission_sets.c.key == pay_set)
        )
        await conn.execute(
            sa.delete(tables.roles).where(tables.roles.c.key.in_([orderer, payer, bystander]))
        )


async def _user(migrator: AsyncEngine, made: _Catalogue) -> uuid.UUID:
    """A member of the tenant with a membership in its workspace and no role."""
    async with migrator.begin() as conn:
        user = await plant_person(conn, made.tenant)
        await plant_membership(conn, made.tenant, made.workspace, user)
    return user


async def _grant(engine: AsyncEngine, made: _Catalogue, user_id: uuid.UUID, *roles: str) -> None:
    """The person's roles in the workspace become exactly `roles`: what goes is
    revoked at once, each role that comes is proposed by one admin and
    confirmed by the other, in key order (the first refusal is raised)."""
    outcome = await assignment_service(engine).set_memberships(
        made.admins.maker_context,
        SetMemberships(user_id, (WorkspaceRoles(made.workspace, frozenset(roles)),)),
    )
    await confirm_all(engine, made.admins.checker_context, outcome.proposals)


async def _roles_of(migrator: AsyncEngine, made: _Catalogue, user_id: uuid.UUID) -> list[str]:
    return (await assigned_roles(migrator, made.tenant, user_id)).get(made.workspace, [])


async def _open_proposals_for(migrator: AsyncEngine, user_id: uuid.UUID) -> list[str]:
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT payload->>'role_key' AS k FROM platform.role_change_requests"
                " WHERE payload->>'user_id' = :u AND status = 'proposed'"
            ),
            {"u": str(user_id)},
        )
        return sorted(r.k for r in rows)


def _refused_as_the_rule(refused: ConflictError, made: _Catalogue, user_id: uuid.UUID) -> None:
    assert refused.details["reason_code"] == "ck_roles_sod_memberships"
    assert refused.details["rule"] == made.rule
    assert refused.details["reason"] == "orders are not paid by who placed them"
    assert refused.details["holders"] == [str(user_id)]


async def test_granting_both_sides_of_a_rule_is_refused_as_a_conflict(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    """Each role is its own proposal: the first side is confirmed, the second
    side's confirmation is refused and leaves its proposal open, unapplied."""
    user_id = await _user(migrator_engine, catalogue)

    with pytest.raises(ConflictError) as refused:
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    _refused_as_the_rule(refused.value, catalogue, user_id)
    assert await _roles_of(migrator_engine, catalogue, user_id) == [catalogue.orderer]
    assert await _open_proposals_for(migrator_engine, user_id) == [catalogue.payer]


async def test_a_regrant_that_would_add_the_other_side_is_refused_and_changes_nothing(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    """A person already holding one side: the confirmation that would add the
    other is judged too, and nothing they hold changes."""
    user_id = await _user(migrator_engine, catalogue)
    await _grant(app_engine, catalogue, user_id, catalogue.orderer)

    with pytest.raises(ConflictError) as refused:
        await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.payer)

    _refused_as_the_rule(refused.value, catalogue, user_id)
    assert await _roles_of(migrator_engine, catalogue, user_id) == [catalogue.orderer]


async def test_roles_that_break_no_rule_are_granted(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    user_id = await _user(migrator_engine, catalogue)
    await _grant(app_engine, catalogue, user_id, catalogue.orderer, catalogue.bystander)
    assert await _roles_of(migrator_engine, catalogue, user_id) == sorted(
        [catalogue.orderer, catalogue.bystander]
    )
    assert await _open_proposals_for(migrator_engine, user_id) == []


async def test_a_permission_set_cannot_carry_the_other_side_past_the_rule(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, catalogue: _Catalogue
) -> None:
    user_id = await _user(migrator_engine, catalogue)
    await _grant(app_engine, catalogue, user_id, catalogue.orderer)
    outcome = await assignment_service(app_engine).set_permission_sets(
        catalogue.admins.maker_context,
        SetPermissionSets(user_id, frozenset({catalogue.pay_set})),
    )

    with pytest.raises(ConflictError) as refused:
        await confirm_all(app_engine, catalogue.admins.checker_context, outcome.proposals)
    _refused_as_the_rule(refused.value, catalogue, user_id)
    assert await _roles_of(migrator_engine, catalogue, user_id) == [catalogue.orderer]


@pytest.mark.parametrize("writer", ["app", "migrator"])
async def test_raw_sql_is_refused_too_whoever_writes_it(
    app_engine: AsyncEngine,
    migrator_engine: AsyncEngine,
    catalogue: _Catalogue,
    writer: str,
) -> None:
    """The rule lives in the database: a writer that skips the adapter meets
    the same refusal. As the application, a raw INSERT carrying out a proposal
    a second admin confirmed in this very transaction (what the rbac guard lets
    through); as the migrator, which bypasses RLS and the rbac guard, a
    membership whose legacy columns carry both sides."""
    user_id = await _user(migrator_engine, catalogue)

    with pytest.raises(IntegrityError, match="orders are not paid by who placed them") as refused:
        if writer == "app":
            await _grant(app_engine, catalogue, user_id, catalogue.orderer)
            outcome = await assignment_service(app_engine).set_memberships(
                catalogue.admins.maker_context,
                SetMemberships(
                    user_id,
                    (
                        WorkspaceRoles(
                            catalogue.workspace, frozenset({catalogue.orderer, catalogue.payer})
                        ),
                    ),
                ),
            )
            (request,) = outcome.proposals
            async with app_engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "SELECT set_config('app.tenant_id', :t, true),"
                        " set_config('app.user_id', :u, true)"
                    ),
                    {"t": str(catalogue.tenant), "u": str(catalogue.admins.checker)},
                )
                await conn.execute(
                    sa.text(
                        "UPDATE platform.role_change_requests SET status = 'confirmed',"
                        " confirmed_by = :u, decided_at = now() WHERE id = :id"
                    ),
                    {"u": catalogue.admins.checker, "id": request},
                )
                await conn.execute(
                    sa.text("SELECT set_config('app.role_change_id', :id, true)"),
                    {"id": str(request)},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.role_assignments"
                        " (id, tenant_id, workspace_id, membership_id, role_id)"
                        " SELECT gen_random_uuid(), m.tenant_id, m.workspace_id, m.id, r.id"
                        " FROM platform.memberships m JOIN platform.tenant_roles r"
                        "   ON r.tenant_id = m.tenant_id AND r.key = :k"
                        " WHERE m.user_id = :p AND m.workspace_id = :w"
                    ),
                    {"k": catalogue.payer, "p": user_id, "w": catalogue.workspace},
                )
        else:
            async with migrator_engine.begin() as conn:
                await conn.execute(
                    sa.text("DELETE FROM platform.memberships WHERE user_id = :u"), {"u": user_id}
                )
                await add_tenant_member(conn, catalogue.tenant, user_id)
                await conn.execute(
                    sa.insert(tables.memberships).values(
                        id=uuid.uuid4(),
                        tenant_id=catalogue.tenant,
                        workspace_id=catalogue.workspace,
                        user_id=user_id,
                        role_keys=[catalogue.orderer],
                        permission_set_keys=[catalogue.pay_set],
                    )
                )

    # The rule is named in HINT, the holders in DETAIL (tenant-rbac R5.1).
    assert getattr(refused.value.orig.__cause__, "hint", None) == catalogue.rule  # type: ignore[union-attr]
    assert getattr(refused.value.orig.__cause__, "detail", None) == str(user_id)  # type: ignore[union-attr]
    expected = [catalogue.orderer] if writer == "app" else []
    assert await _roles_of(migrator_engine, catalogue, user_id) == expected


async def test_the_application_cannot_rewrite_the_rules(app_engine: AsyncEngine) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with app_engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM platform.sod_rules"))


async def test_no_single_role_or_permission_set_in_the_catalogue_breaks_a_rule(
    app_engine: AsyncEngine,
) -> None:
    """Every rule in the shared catalogue, context rules included, can be met
    by assigning roles carefully: no template, cloned alone into a tenant,
    breaks one on its own. Since tenant-rbac ticket 02 this replaces the
    triggers b9862fa13a80 and f381f1694395 put on the templates."""
    async with app_engine.begin() as conn:
        broken = (
            (
                await conn.execute(
                    sa.text(
                        "SELECT t.key FROM ("
                        "  SELECT key, scopes FROM platform.roles"
                        "  UNION ALL SELECT key, scopes FROM platform.permission_sets) t"
                        " CROSS JOIN platform.sod_rules s"
                        " WHERE platform.sod_rule_broken("
                        "   s.key, ARRAY(SELECT jsonb_array_elements_text(t.scopes)))"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert list(broken) == []
