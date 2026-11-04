"""Integration: the backfill of migration b5677d345bc1 on planted tenants.

tenant-rbac R3.5, R3.6. The database is already at head, so the backfill's own
statements (the migration's `BACKFILL`, idempotent) run again on tenants whose
assignments and roles this test first wipes, inside one transaction that rolls
back: the state the migration met. What a membership held before is read the
way it was held before, from `role_keys`, `permission_set_keys` and the
templates; what it holds after is `platform.scopes_in`.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.domain.audit import system_actor
from dw_platform.testing.members import add_tenant_member
from dw_platform.testing.seed_env import TENANTS, seed_test_env, sid

pytestmark = pytest.mark.integration

_MIGRATION = (
    Path(__file__).resolve().parents[5] / "db/migrations/versions/b5677d345bc1_tenant_roles.py"
)


def _migration() -> Any:
    spec = importlib.util.spec_from_file_location("tenant_roles_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Before: a membership's scopes as `effective_scopes` read them until this
# migration, its roles' and its permission sets' templates, unioned.
_BEFORE = sa.text(
    """
    SELECT m.id, m.tenant_id, m.workspace_id, m.user_id, m.role_keys,
           ARRAY(
               SELECT DISTINCT s FROM platform.roles r,
                    jsonb_array_elements_text(r.scopes) s
               WHERE m.role_keys ? r.key
               UNION
               SELECT DISTINCT s FROM platform.permission_sets p,
                    jsonb_array_elements_text(p.scopes) s
               WHERE m.permission_set_keys ? p.key
           ) AS scopes
    FROM platform.memberships m WHERE m.tenant_id = ANY(:tenants)
      -- Active members only: since tenant_members (349080a62e41) an invited or
      -- suspended person holds nothing through `scopes_in`, whatever this
      -- migration did, and the seed tenants carry such people other suites plant.
      AND EXISTS (
          SELECT 1 FROM platform.tenant_members tm
          WHERE tm.tenant_id = m.tenant_id AND tm.user_id = m.user_id
            AND tm.status = 'active'
      )
    """
)


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    await seed_test_env(db_urls.migrator)
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def _plant(conn: AsyncConnection) -> dict[str, Any]:
    """A tenant with an `org_admin` at `main`, a person in two workspaces with
    tenant keys in one, and a person whose only authority is a permission set."""
    tenant, main, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slug = f"mig-{tenant.hex[:10]}"
    await conn.execute(
        sa.text("INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)"),
        {"t": tenant, "s": slug},
    )
    for ws, ws_slug in ((main, "main"), (other, "sales")):
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, :s, :s)"
            ),
            {"w": ws, "t": tenant, "s": ws_slug},
        )
    people: dict[str, uuid.UUID] = {}
    for name, rows in (
        ("admin", ((main, ["org_admin", "member"], []),)),
        ("two_workspaces", ((main, ["member"], []), (other, ["org_admin"], []))),
        ("boosted", ((main, [], ["approver_boost"]),)),
    ):
        user = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'Người')"
            ),
            {"u": user, "s": f"mig-{user}"},
        )
        await add_tenant_member(conn, tenant, user)
        for ws, roles, sets in rows:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys, permission_set_keys)"
                    " VALUES (gen_random_uuid(), :t, :w, :u, CAST(:r AS jsonb), CAST(:p AS jsonb))"
                ),
                {"t": tenant, "w": ws, "u": user, "r": _json(roles), "p": _json(sets)},
            )
        people[name] = user
    return {"tenant": tenant, "slug": slug, "main": main, "other": other, "people": people}


def _json(values: list[str]) -> str:
    return "[" + ", ".join(f'"{v}"' for v in values) + "]"


async def _as_the_migration_found_them(conn: AsyncConnection, tenants: list[uuid.UUID]) -> None:
    """No assignment, no tenant role and no role change request: what the
    backfill met. A request (tenant-rbac ticket 03) a test of another file left
    on a seeded tenant holds its role by a foreign key and is deleted only by
    the offboarding lane, so its guard is set aside here, in the caller's
    transaction, which is rolled back."""
    await conn.execute(
        sa.text(
            "ALTER TABLE platform.role_change_requests DISABLE TRIGGER guard_role_change_request"
        )
    )
    await conn.execute(
        sa.text("DELETE FROM platform.role_change_requests WHERE tenant_id = ANY(:t)"),
        {"t": tenants},
    )
    await conn.execute(
        sa.text(
            "ALTER TABLE platform.role_change_requests ENABLE TRIGGER guard_role_change_request"
        )
    )
    await conn.execute(
        sa.text("DELETE FROM platform.role_assignments WHERE tenant_id = ANY(:t)"), {"t": tenants}
    )
    await conn.execute(
        sa.text("DELETE FROM platform.tenant_roles WHERE tenant_id = ANY(:t)"), {"t": tenants}
    )


async def test_every_membership_keeps_its_keys_and_gains_only_the_owners_or_a_tenant_key(
    migrator: AsyncEngine,
) -> None:
    """R3.5 on the seed and on a planted tenant with the three cases."""
    migration = _migration()
    async with migrator.connect() as conn, conn.begin() as tx:
        world = await _plant(conn)
        tenants = [world["tenant"], *(sid("tenant", t["slug"]) for t in TENANTS)]
        before = (await conn.execute(_BEFORE, {"tenants": tenants})).all()
        await _as_the_migration_found_them(conn, tenants)
        for statement in migration.BACKFILL:
            await conn.execute(sa.text(statement))
        owner_keys = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT key FROM platform.permissions"
                        " WHERE status = 'active' AND tenant_grantable"
                    )
                )
            ).scalars()
        )
        tenant_keys = set(
            (
                await conn.execute(
                    sa.text("SELECT key FROM platform.permissions WHERE scope_kind = 'tenant'")
                )
            ).scalars()
        )
        checked = 0
        for row in before:
            after = set(
                (
                    await conn.execute(
                        sa.text("SELECT platform.scopes_in(:t, :u, :w)"),
                        {"t": row.tenant_id, "u": row.user_id, "w": row.workspace_id},
                    )
                ).scalars()
            )
            kept = set(row.scopes) - {"platform.admin"}
            assert kept <= after, f"membership {row.id} lost {sorted(kept - after)}"
            gained = after - kept
            is_owner = "org_admin" in row.role_keys and row.workspace_id in (
                world["main"],
                sid("workspace", "tenant-alpha:main"),
                sid("workspace", "tenant-beta:main"),
            )
            if (
                row.user_id == world["people"]["two_workspaces"]
                and row.workspace_id == world["main"]
            ):
                assert gained <= tenant_keys and gained, "a tenant key from the other workspace"
            elif is_owner:
                assert gained <= owner_keys
            else:
                assert gained == set(), f"membership {row.id} gained {sorted(gained)}"
            checked += 1
        boosted = set(
            (
                await conn.execute(
                    sa.text("SELECT platform.scopes_in(:t, :u, :w)"),
                    {"t": world["tenant"], "u": world["people"]["boosted"], "w": world["main"]},
                )
            ).scalars()
        )
        await tx.rollback()
    assert checked >= 12, "the seed and the three planted people were all compared"
    assert "approvals.decide" in boosted, "a permission set alone still grants"


async def test_the_main_org_admin_becomes_owner_audited_by_the_lane_and_the_rest_are_reported(
    migrator: AsyncEngine,
) -> None:
    """R3.6: one audit per new owner as `system:rbac_migration`; a tenant with
    one owner and one with no `org_admin` at `main` are in the printout."""
    migration = _migration()
    assert str(system_actor("rbac_migration").value) == migration.RBAC_MIGRATION_ACTOR
    async with migrator.connect() as conn, conn.begin() as tx:
        world = await _plant(conn)
        await _as_the_migration_found_them(conn, [world["tenant"]])
        for statement in migration.BACKFILL:
            await conn.execute(sa.text(statement))
        owners = (
            await conn.execute(
                sa.text(
                    "SELECT m.user_id, m.workspace_id FROM platform.role_assignments a"
                    " JOIN platform.tenant_roles r ON r.id = a.role_id"
                    " JOIN platform.memberships m ON m.id = a.membership_id"
                    " WHERE a.tenant_id = :t AND r.key = 'tenant_owner'"
                ),
                {"t": world["tenant"]},
            )
        ).all()
        audits = (
            await conn.execute(
                sa.text(
                    "SELECT actor_id, details FROM platform.audit_events"
                    " WHERE tenant_id = :t AND action = 'platform.role_assignment.grant'"
                ),
                {"t": world["tenant"]},
            )
        ).all()
        below_two = set((await conn.execute(sa.text(migration.REPORT_BELOW_TWO_OWNERS))).scalars())
        no_admin = set((await conn.execute(sa.text(migration.REPORT_NO_MAIN_ORG_ADMIN))).scalars())
        await tx.rollback()
    assert [(o.user_id, o.workspace_id) for o in owners] == [
        (world["people"]["admin"], world["main"])
    ], "only the org_admin of main, not the one of another workspace"
    assert len(audits) == 1
    assert audits[0].actor_id == system_actor("rbac_migration").value
    assert audits[0].details["actor"] == "system:rbac_migration"
    assert world["slug"] in below_two
    assert "tenant-alpha" in no_admin and world["slug"] not in no_admin
