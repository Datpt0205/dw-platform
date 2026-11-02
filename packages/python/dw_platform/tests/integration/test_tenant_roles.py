"""Integration: roles as tenant data, and the one answer to "what does this person hold".

tenant-rbac ticket 02 (migration b5677d345bc1) on a migrated Postgres. Every
world here is planted in raw SQL (`dw_platform.testing.rbac`) and read back
through the database's own functions, `platform.effective_grants` and the
functions beside it, or through the adapters that read them; nothing here
recomputes a grant in Python.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, provisioner_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.scope_holders import SqlScopeHolders
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    grant_privilege,
    grants_of,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    scopes_in,
    unregister_key,
)

pytestmark = pytest.mark.integration


def _constraint(error: BaseException) -> str | None:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None)


def _detail(error: BaseException) -> str:
    cause = getattr(getattr(error, "orig", None), "__cause__", None)
    return getattr(cause, "detail", None) or ""


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def provisioner(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(provisioner_url(db_urls.migrator), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_keys(migrator: AsyncEngine) -> AsyncIterator[dict[str, str]]:
    """Test keys of each kind, registered for one test and removed after it."""
    suffix = uuid.uuid4().hex[:10]
    keys = {
        "workspace": f"test.k{suffix}.work",
        "workspace2": f"test.k{suffix}.other",
        "tenant": f"test.k{suffix}.admin",
        "record": f"test.k{suffix}.record",
    }
    async with migrator.begin() as conn:
        for name, key in keys.items():
            await register_key(conn, key, scope_kind=name.rstrip("2"))
    yield keys
    async with migrator.begin() as conn:
        for key in keys.values():
            await unregister_key(conn, key)


# ---- effective grants (R2.2-R2.5, R2.7) -------------------------------------


async def test_a_person_holds_the_union_of_their_assignments_anchored_where_assigned(
    migrator: AsyncEngine, test_keys: dict[str, str]
) -> None:
    """R2.3, R2.4 (RB6): a tenant-depth key from workspace A holds in B; a
    workspace-depth key from A does not; a permission set adds to a role."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2)
        person = await plant_person(conn, t.tenant_id)
        at_a = await plant_membership(conn, t.tenant_id, t.workspaces[0], person)
        await plant_membership(conn, t.tenant_id, t.workspaces[1], person)
        role = await plant_role(conn, t.tenant_id, "r_union", {test_keys["tenant"]: "tenant"})
        boost = await plant_role(
            conn,
            t.tenant_id,
            "p_union",
            {test_keys["workspace"]: "workspace"},
            kind="permission_set",
        )
        await assign(conn, t.tenant_id, t.workspaces[0], at_a, role)
        await assign(conn, t.tenant_id, t.workspaces[0], at_a, boost)

        assert await grants_of(conn, t.tenant_id, person) == {
            (test_keys["tenant"], "tenant"),
            (test_keys["workspace"], "workspace"),
        }
        in_a = await scopes_in(conn, t.tenant_id, person, t.workspaces[0])
        in_b = await scopes_in(conn, t.tenant_id, person, t.workspaces[1])
    assert in_a == {test_keys["tenant"], test_keys["workspace"]}
    assert in_b == {test_keys["tenant"]}, "a workspace key stays at its anchor"


@pytest.mark.parametrize("source", ["suspended", "locked", "deleted_role", "expired"])
async def test_a_source_not_in_force_grants_nothing(
    migrator: AsyncEngine, app: AsyncEngine, test_keys: dict[str, str], source: str
) -> None:
    """R2.5 (RB7): through SQL and through `scope_holders.py`, which keeps no
    filter of its own."""
    key = test_keys["workspace"]
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        role = await plant_role(conn, t.tenant_id, "r_source", {key: "workspace"})
        past = datetime.now(UTC) - timedelta(days=2)
        assignment = await assign(
            conn,
            t.tenant_id,
            t.main,
            membership,
            role,
            assigned_at=past,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        assert (key, "workspace") in await grants_of(conn, t.tenant_id, person)
        if source == "suspended":
            await conn.execute(
                sa.text(
                    "UPDATE platform.tenant_members SET status = 'suspended' WHERE user_id = :u"
                ),
                {"u": person},
            )
        elif source == "locked":
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'locked' WHERE id = :t"),
                {"t": t.tenant_id},
            )
        elif source == "deleted_role":
            await conn.execute(
                sa.text("UPDATE platform.tenant_roles SET deleted_at = now() WHERE id = :r"),
                {"r": role},
            )
        else:
            await conn.execute(
                sa.text(
                    "UPDATE platform.role_assignments SET expires_at = now() - interval '1 day'"
                    " WHERE id = :a"
                ),
                {"a": assignment},
            )
        held = await grants_of(conn, t.tenant_id, person)
    assert (key, "workspace") not in held
    holders = SqlScopeHolders(async_sessionmaker(app, expire_on_commit=False))
    assert await holders.holding(t.tenant_id, t.main, frozenset({key})) == []
    assert await holders.holds(t.tenant_id, t.main, person, key) is False


async def test_the_owner_holds_every_grantable_active_key_registered_even_later(
    migrator: AsyncEngine,
) -> None:
    """R2.7 (RB34): computed, never stored; `platform.admin` and a retired key
    stay out."""
    later, retired = f"test.k{uuid.uuid4().hex[:8]}.later", f"test.k{uuid.uuid4().hex[:8]}.old"
    try:
        async with migrator.begin() as conn:
            t = await plant_tenant(conn)
            owner = await plant_person(conn, t.tenant_id)
            membership = await plant_membership(conn, t.tenant_id, t.main, owner)
            owner_role = await role_id(conn, t.tenant_id, "tenant_owner")
            await assign(conn, t.tenant_id, t.main, membership, owner_role)
            await register_key(conn, later)
            await register_key(conn, retired, status="retired")
            held = await grants_of(conn, t.tenant_id, owner)
            rows = await conn.scalar(
                sa.text("SELECT count(*) FROM platform.tenant_role_permissions WHERE role_id = :r"),
                {"r": owner_role},
            )
            grantable = set(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT key FROM platform.permissions"
                            " WHERE status = 'active' AND tenant_grantable"
                        )
                    )
                ).scalars()
            )
    finally:
        async with migrator.begin() as conn:
            await unregister_key(conn, later)
            await unregister_key(conn, retired)
    assert (later, "tenant") in held
    assert {key for key, _ in held} == grantable
    assert all(depth == "tenant" for _, depth in held)
    assert "platform.admin" not in {key for key, _ in held}
    assert retired not in {key for key, _ in held}
    assert rows == 0, "tenant_owner carries no privilege row"


async def test_the_checkers_are_the_holders_the_holders_query_names_but_the_proposer(
    migrator: AsyncEngine, app: AsyncEngine, test_keys: dict[str, str]
) -> None:
    """R2.2: `platform.checker_candidates` and `scope_holders.py` agree; a
    suspended holder is in neither, a Digital Worker's principal is no checker."""
    key = test_keys["workspace"]
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        role = await plant_role(conn, t.tenant_id, "r_checker", {key: "workspace"})
        people = {}
        for name, status, kind in (
            ("proposer", "active", "human"),
            ("first", "active", "human"),
            ("second", "active", "human"),
            ("suspended", "suspended", "human"),
            ("worker", "active", "service"),
        ):
            person = await plant_person(conn, t.tenant_id, status=status, kind=kind)  # type: ignore[arg-type]
            membership = await plant_membership(conn, t.tenant_id, t.main, person)
            await assign(conn, t.tenant_id, t.main, membership, role)
            people[name] = person
        checkers = set(
            (
                await conn.execute(
                    sa.text("SELECT platform.checker_candidates(:t, :k, :p, :w)"),
                    {"t": t.tenant_id, "k": key, "p": people["proposer"], "w": t.main},
                )
            ).scalars()
        )
    holders = SqlScopeHolders(async_sessionmaker(app, expire_on_commit=False))
    named = set(await holders.holding(t.tenant_id, t.main, frozenset({key})))
    assert checkers == {people["first"], people["second"]}
    assert checkers == named - {people["proposer"]}


async def test_reach_follows_depth_and_own_reaches_no_workspace(
    migrator: AsyncEngine, test_keys: dict[str, str]
) -> None:
    """`platform.workspace_reach` (R9.4's shape in W1): own nothing, workspace
    its anchor, tenant every live workspace."""
    key = test_keys["record"]
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=3)
        await conn.execute(
            sa.text("UPDATE platform.workspaces SET archived_at = now() WHERE id = :w"),
            {"w": t.workspaces[2]},
        )
        reach: dict[str, set[uuid.UUID]] = {}
        for depth in ("own", "workspace", "tenant"):
            person = await plant_person(conn, t.tenant_id)
            membership = await plant_membership(conn, t.tenant_id, t.workspaces[1], person)
            role = await plant_role(conn, t.tenant_id, f"r_reach_{depth}", {key: depth})
            await assign(conn, t.tenant_id, t.workspaces[1], membership, role)
            reach[depth] = set(
                (
                    await conn.execute(
                        sa.text("SELECT platform.workspace_reach(:t, :u, :k)"),
                        {"t": t.tenant_id, "u": person, "k": key},
                    )
                ).scalars()
            )
    assert reach == {
        "own": set(),
        "workspace": {t.workspaces[1]},
        "tenant": {t.workspaces[0], t.workspaces[1]},
    }


async def test_cover_needs_every_key_at_the_same_or_a_broader_depth(
    migrator: AsyncEngine, test_keys: dict[str, str]
) -> None:
    key = test_keys["workspace"]
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2)
        by_depth = {}
        for depth, ws in (("workspace", t.workspaces[0]), ("tenant", t.workspaces[1])):
            person = await plant_person(conn, t.tenant_id)
            membership = await plant_membership(conn, t.tenant_id, ws, person)
            role = await plant_role(conn, t.tenant_id, f"r_cover_{depth}", {key: depth})
            await assign(conn, t.tenant_id, ws, membership, role)
            by_depth[depth] = person

        async def covers(holder: uuid.UUID, subject: uuid.UUID) -> bool:
            return bool(
                await conn.scalar(
                    sa.text("SELECT platform.grants_cover(:t, :h, :s)"),
                    {"t": t.tenant_id, "h": holder, "s": subject},
                )
            )

        assert await covers(by_depth["tenant"], by_depth["workspace"])
        assert not await covers(by_depth["workspace"], by_depth["tenant"])


# ---- roles are tenant data (R3.2-R3.4, R3.7) --------------------------------


async def test_a_template_edited_later_leaves_its_clone_as_it_was(migrator: AsyncEngine) -> None:
    """R3.2 (RB10): a migration edits `approver`; the tenant's clone keeps its
    privileges and depths. Rolled back, so the shared catalogue is untouched."""
    async with migrator.connect() as conn, conn.begin() as tx:
        t = await plant_tenant(conn)
        clone = await conn.scalar(
            sa.text("SELECT platform.install_role_template(:t, 'approver')"), {"t": t.tenant_id}
        )
        before = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT permission_key, depth FROM platform.tenant_role_permissions"
                        " WHERE role_id = :r"
                    ),
                    {"r": clone},
                )
            ).all()
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.roles SET scopes = '[\"audit.events\"]'::jsonb"
                " WHERE key = 'approver'"
            )
        )
        after = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT permission_key, depth FROM platform.tenant_role_permissions"
                        " WHERE role_id = :r"
                    ),
                    {"r": clone},
                )
            ).all()
        )
        await tx.rollback()
    assert ("approvals.decide", "workspace") in before
    assert after == before


async def test_one_tenant_reads_and_names_none_of_anothers_roles(
    migrator: AsyncEngine, app: AsyncEngine, test_keys: dict[str, str]
) -> None:
    """R3.3 (RB8): RLS on all four tables; the composite key refuses B's role
    in A's assignment; an unscoped connection reads nothing."""
    async with migrator.begin() as conn:
        a, b = await plant_tenant(conn), await plant_tenant(conn)
        person = await plant_person(conn, a.tenant_id)
        membership = await plant_membership(conn, a.tenant_id, a.main, person)
        b_role = await plant_role(conn, b.tenant_id, "r_b", {test_keys["workspace"]: "workspace"})
        b_person = await plant_person(conn, b.tenant_id)
        b_membership = await plant_membership(conn, b.tenant_id, b.main, b_person)
        await assign(conn, b.tenant_id, b.main, b_membership, b_role)
    tables = (
        "tenant_roles",
        "tenant_role_permissions",
        "role_assignments",
        "tenant_access_versions",
    )
    async with app.connect() as conn:
        for table in tables:
            assert (await conn.scalar(sa.text(f"SELECT count(*) FROM platform.{table}"))) == 0, (
                f"an unscoped connection read {table}"
            )
        await conn.rollback()
        async with conn.begin():
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a.tenant_id)}
            )
            for table in tables:
                seen = await conn.scalar(
                    sa.text(f"SELECT count(*) FROM platform.{table} WHERE tenant_id = :b"),
                    {"b": b.tenant_id},
                )
                assert seen == 0, f"tenant A read B's {table}"
        with pytest.raises(IntegrityError) as refused:
            async with conn.begin():
                await conn.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(a.tenant_id)},
                )
                await assign(conn, a.tenant_id, a.main, membership, b_role)
        assert _constraint(refused.value) == "fk_role_assignments_tenant_id_tenant_roles"


async def test_a_privilege_takes_only_a_depth_its_kind_allows(
    migrator: AsyncEngine, test_keys: dict[str, str]
) -> None:
    """R3.4 (RB9): a tenant key at workspace depth, a workspace key at own;
    a record key takes own."""
    async with migrator.connect() as conn:
        async with conn.begin():
            t = await plant_tenant(conn)
            role = await plant_role(conn, t.tenant_id, "r_depth", {})
        for key, depth in ((test_keys["tenant"], "workspace"), (test_keys["workspace"], "own")):
            with pytest.raises(IntegrityError) as refused:
                async with conn.begin():
                    await grant_privilege(conn, t.tenant_id, role, key, depth)
            assert _constraint(refused.value) == "ck_tenant_role_permissions_depth_kind"
        async with conn.begin():
            await grant_privilege(conn, t.tenant_id, role, test_keys["record"], "own")


async def test_the_201st_role_is_refused_and_two_racing_for_the_200th_get_one(
    migrator: AsyncEngine, db_urls: DatabaseUrls
) -> None:
    """R3.7 (RB11): the system roles count; the advisory lock serialises the race."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        live = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.tenant_roles WHERE tenant_id = :t"),
            {"t": t.tenant_id},
        )
        for n in range(199 - int(live or 0)):
            await plant_role(conn, t.tenant_id, f"r_fill_{n}", {})

    first = create_async_engine(db_urls.migrator, poolclass=NullPool)
    second = create_async_engine(db_urls.migrator, poolclass=NullPool)
    results: list[str] = []
    try:
        async with first.connect() as c1, second.connect() as c2:
            await c1.begin()
            await plant_role(c1, t.tenant_id, "r_race_one", {})

            async def other() -> None:
                try:
                    async with c2.begin():
                        await plant_role(c2, t.tenant_id, "r_race_two", {})
                    results.append("accepted")
                except IntegrityError as exc:
                    results.append(str(_constraint(exc)))

            racer = asyncio.create_task(other())
            await asyncio.sleep(0.5)
            assert not racer.done(), "the second insert must wait on the first"
            await c1.commit()
            await racer
    finally:
        await first.dispose()
        await second.dispose()
    assert results == ["role_limit_reached"]
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await plant_role(conn, t.tenant_id, "r_over", {})
    assert _constraint(refused.value) == "role_limit_reached"


async def test_an_assigned_role_of_an_active_tenant_is_not_deleted(migrator: AsyncEngine) -> None:
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        role = await plant_role(conn, t.tenant_id, "r_kept", {})
        await assign(conn, t.tenant_id, t.main, membership, role)
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM platform.tenant_roles WHERE id = :r"), {"r": role}
            )
    assert _constraint(refused.value) == "ck_tenant_roles_in_use"


async def test_a_system_flag_follows_the_key(migrator: AsyncEngine) -> None:
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        role = await plant_role(conn, t.tenant_id, "r_plain", {})
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET is_system = true WHERE id = :r"), {"r": role}
        )
        flags: dict[str, bool] = {
            row[0]: row[1]
            for row in (
                await conn.execute(
                    sa.text(
                        "SELECT key, is_system FROM platform.tenant_roles WHERE tenant_id = :t"
                    ),
                    {"t": t.tenant_id},
                )
            ).all()
        }
    assert flags == {"tenant_owner": True, "member": True, "r_plain": False}


# ---- the legacy columns (R4.1) ----------------------------------------------


async def test_the_legacy_columns_copy_what_they_add_and_remove_and_nothing_else(
    migrator: AsyncEngine,
) -> None:
    """R4.1: removing `approver` from `role_keys` revokes it in the same
    statement and leaves `tenant_owner`; a template the tenant lacks is cloned;
    a key that is neither a role nor a template is refused."""
    async with migrator.connect() as conn:
        async with conn.begin():
            t = await plant_tenant(conn)
            person = await plant_person(conn, t.tenant_id)
            membership = await plant_membership(conn, t.tenant_id, t.main, person)
            await assign(
                conn,
                t.tenant_id,
                t.main,
                membership,
                await role_id(conn, t.tenant_id, "tenant_owner"),
            )
            await conn.execute(
                sa.text(
                    'UPDATE platform.memberships SET role_keys = \'["member", "approver"]\','
                    " permission_set_keys = '[\"approver_boost\"]' WHERE id = :m"
                ),
                {"m": membership},
            )

        async def assigned() -> set[str]:
            return set(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT r.key FROM platform.role_assignments a"
                            " JOIN platform.tenant_roles r ON r.id = a.role_id"
                            " WHERE a.membership_id = :m"
                        ),
                        {"m": membership},
                    )
                ).scalars()
            )

        assert await assigned() == {"tenant_owner", "member", "approver", "approver_boost"}
        await conn.rollback()
        async with conn.begin():
            await conn.execute(
                sa.text(
                    "UPDATE platform.memberships SET role_keys = '[\"member\"]',"
                    " permission_set_keys = '[]' WHERE id = :m"
                ),
                {"m": membership},
            )
            assert await assigned() == {"tenant_owner", "member"}
            # The owner's computed grants hold `approvals.decide` too; what went
            # is every grant the `approver` assignment gave.
            from_approver = await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.effective_grants(:t, :u) g"
                    " JOIN platform.tenant_roles r ON r.id = g.role_id WHERE r.key = 'approver'"
                ),
                {"t": t.tenant_id, "u": person},
            )
            assert from_approver == 0
        with pytest.raises(IntegrityError) as refused:
            async with conn.begin():
                await conn.execute(
                    sa.text(
                        "UPDATE platform.memberships SET role_keys = '[\"no_such_role\"]'"
                        " WHERE id = :m"
                    ),
                    {"m": membership},
                )
        assert _constraint(refused.value) == "ck_memberships_role_keys_known"


# ---- the access version (R4.1, R4.2) -----------------------------------------


async def test_every_table_feeding_authorization_bumps_the_version(migrator: AsyncEngine) -> None:
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)

        async def version() -> int:
            return int(
                await conn.scalar(
                    sa.text(
                        "SELECT version FROM platform.tenant_access_versions WHERE tenant_id = :t"
                    ),
                    {"t": t.tenant_id},
                )
                or -1
            )

        seen = [await version()]
        person = await plant_person(conn, t.tenant_id)
        seen.append(await version())
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        seen.append(await version())
        role = await plant_role(conn, t.tenant_id, "r_bump", {})
        seen.append(await version())
        await grant_privilege(conn, t.tenant_id, role, "approvals.read", "workspace")
        seen.append(await version())
        await assign(conn, t.tenant_id, t.main, membership, role)
        seen.append(await version())
        await conn.execute(
            sa.text(
                "UPDATE platform.entitlements SET feature_overrides = '[]' WHERE tenant_id = :t"
            ),
            {"t": t.tenant_id},
        )
        seen.append(await version())
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'locked' WHERE id = :t"),
            {"t": t.tenant_id},
        )
        seen.append(await version())
    assert seen == sorted(set(seen)), f"every write bumps the version: {seen}"


async def test_the_version_row_is_purged_only_for_an_offboarding_tenant(
    migrator: AsyncEngine, app: AsyncEngine
) -> None:
    """R4.2: `platform.purge_tenant_access_version` refuses an active tenant."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
    with pytest.raises(IntegrityError) as refused:
        async with app.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.tenant_id)}
            )
            await conn.execute(
                sa.text("SELECT platform.purge_tenant_access_version(:t)"), {"t": t.tenant_id}
            )
    assert _constraint(refused.value) == "ck_tenant_access_versions_purge"
    async with migrator.connect() as conn:
        assert (
            await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.tenant_access_versions WHERE tenant_id = :t"
                ),
                {"t": t.tenant_id},
            )
            == 1
        )


# ---- two owners, `setup` (R3.1, R3.10, R3.15) ---------------------------------


async def _setup_tenant(conn: AsyncConnection) -> tuple[PlantedTenant, list[uuid.UUID]]:
    t = await plant_tenant(conn, status="setup")
    owner_role = await role_id(conn, t.tenant_id, "tenant_owner")
    owners = []
    for _ in range(2):
        person = await plant_person(conn, t.tenant_id, status="invited")
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        await assign(conn, t.tenant_id, t.main, membership, owner_role)
        owners.append(person)
    return t, owners


async def _status(conn: AsyncConnection, tenant_id: uuid.UUID) -> str:
    return str(
        await conn.scalar(
            sa.text("SELECT status FROM platform.tenants WHERE id = :t"), {"t": tenant_id}
        )
    )


async def _setup_audits(conn: AsyncConnection, tenant_id: uuid.UUID) -> list[str]:
    rows = await conn.execute(
        sa.text(
            "SELECT actor_id FROM platform.audit_events"
            " WHERE tenant_id = :t AND action = 'platform.tenant.setup_completed'"
        ),
        {"t": tenant_id},
    )
    return [str(r.actor_id) for r in rows]


async def _activate(conn: AsyncConnection, tenant_id: uuid.UUID, user: uuid.UUID) -> None:
    await conn.execute(
        sa.text(
            "UPDATE platform.tenant_members SET status = 'active'"
            " WHERE tenant_id = :t AND user_id = :u"
        ),
        {"t": tenant_id, "u": user},
    )


async def test_the_second_owner_activated_opens_the_tenant_in_the_same_transaction(
    migrator: AsyncEngine,
) -> None:
    """R3.10 (RB38)."""
    async with migrator.connect() as conn:
        async with conn.begin():
            t, owners = await _setup_tenant(conn)
            await _activate(conn, t.tenant_id, owners[0])
        assert await _status(conn, t.tenant_id) == "setup"
        await conn.rollback()
        tx = await conn.begin()
        await _activate(conn, t.tenant_id, owners[1])
        assert await _status(conn, t.tenant_id) == "active"
        assert await _setup_audits(conn, t.tenant_id) == [str(owners[1])]
        await tx.rollback()
        assert await _status(conn, t.tenant_id) == "setup"
        assert await _setup_audits(conn, t.tenant_id) == []
        await conn.rollback()


async def test_an_active_member_who_owns_nothing_leaves_the_tenant_in_setup(
    migrator: AsyncEngine,
) -> None:
    async with migrator.begin() as conn:
        t, owners = await _setup_tenant(conn)
        await _activate(conn, t.tenant_id, owners[0])
        other = await plant_person(conn, t.tenant_id, status="invited")
        await plant_membership(conn, t.tenant_id, t.main, other)
        await _activate(conn, t.tenant_id, other)
        assert await _status(conn, t.tenant_id) == "setup"


async def test_assigning_the_owner_role_to_an_active_member_opens_the_tenant(
    migrator: AsyncEngine,
) -> None:
    """R3.10 (RB38): the writers that insert an `active` company row directly
    are covered by the trigger on `platform.role_assignments`."""
    async with migrator.begin() as conn:
        t, owners = await _setup_tenant(conn)
        await _activate(conn, t.tenant_id, owners[0])
        direct = await plant_person(conn, t.tenant_id, status="active")
        membership = await plant_membership(conn, t.tenant_id, t.main, direct)
        await assign(
            conn,
            t.tenant_id,
            t.main,
            membership,
            await role_id(conn, t.tenant_id, "tenant_owner"),
        )
        assert await _status(conn, t.tenant_id) == "active"
        assert await _setup_audits(conn, t.tenant_id) == [str(direct)]


async def test_two_owners_activated_at_once_still_open_the_tenant(
    migrator: AsyncEngine, db_urls: DatabaseUrls
) -> None:
    """R3.10 (RB38): the row lock makes the second count both."""
    async with migrator.begin() as conn:
        t, owners = await _setup_tenant(conn)
    tenant_id = t.tenant_id
    one = create_async_engine(db_urls.migrator, poolclass=NullPool)
    two = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with one.connect() as c1, two.connect() as c2:
            await c1.begin()
            # The trigger locks the tenant row before it counts, owner one.
            await _activate(c1, tenant_id, owners[0])

            async def second() -> None:
                async with c2.begin():
                    await _activate(c2, tenant_id, owners[1])

            racer = asyncio.create_task(second())
            await asyncio.sleep(0.5)
            assert not racer.done(), "the second activation waits on the tenant row"
            await c1.commit()
            await racer
    finally:
        await one.dispose()
        await two.dispose()
    async with migrator.connect() as conn:
        assert await _status(conn, tenant_id) == "active"


@pytest.mark.parametrize(
    ("start", "to", "allowed"),
    [
        ("active", "setup", False),
        ("locked", "setup", False),
        ("setup", "locked", False),
        ("setup", "offboarded", False),
        ("setup", "active", False),  # with no owner active (gate M3)
        ("setup", "offboarding", True),
    ],
)
async def test_setup_is_entered_at_creation_and_left_for_active_or_offboarding_only(
    migrator: AsyncEngine, provisioner: AsyncEngine, start: str, to: str, allowed: bool
) -> None:
    """R3.1, R3.15 (RB41), as `dw_provisioner`."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, status=start)
    statement = sa.text("UPDATE platform.tenants SET status = :s WHERE id = :t")
    if allowed:
        async with provisioner.begin() as conn:
            await conn.execute(statement, {"s": to, "t": t.tenant_id})
    else:
        with pytest.raises(IntegrityError) as refused:
            async with provisioner.begin() as conn:
                await conn.execute(statement, {"s": to, "t": t.tenant_id})
        assert _constraint(refused.value) == "ck_tenants_status_transition"
    async with migrator.connect() as conn:
        assert await _status(conn, t.tenant_id) == (to if allowed else start)


# ---- operators and support staff hold no owner authority (R3.11) -------------


@pytest.fixture
async def owner_keys(migrator: AsyncEngine) -> AsyncIterator[tuple[str, str]]:
    """The two keys of R3.11 and R3.12, registered as their clusters will
    register them, for one test (neither is in the catalogue yet)."""
    keys = ("platform.roles.write", "studio.publish.approve")
    async with migrator.begin() as conn:
        for key in keys:
            await register_key(conn, key, scope_kind="tenant")
    yield keys
    async with migrator.begin() as conn:
        for key in keys:
            await unregister_key(conn, key)


@pytest.mark.parametrize("writer", ["migrator", "provisioner"])
@pytest.mark.parametrize("listed_in", ["platform_operators", "support_staff"])
async def test_no_operator_or_support_staff_member_is_made_an_owner(
    migrator: AsyncEngine, provisioner: AsyncEngine, writer: str, listed_in: str
) -> None:
    """R3.11 (RB39): a person listed before they were given a membership, then
    assigned `tenant_owner`, by either role."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        await conn.execute(
            sa.text(f"INSERT INTO platform.{listed_in} (user_id) VALUES (:u)"), {"u": person}
        )
        owner_role = await role_id(conn, t.tenant_id, "tenant_owner")
    engine = migrator if writer == "migrator" else provisioner
    with pytest.raises(IntegrityError) as refused:
        async with engine.begin() as conn:
            await assign(conn, t.tenant_id, t.main, membership, owner_role)
    assert _constraint(refused.value) == "ck_role_assignments_operator_not_owner"


async def test_an_owner_key_reaches_no_operator_and_no_owner_becomes_an_operator(
    migrator: AsyncEngine, owner_keys: tuple[str, str]
) -> None:
    """R3.11 (RB39): a key added to a role an operator holds; an owner listed."""
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        operator = await plant_person(conn, t.tenant_id)
        await conn.execute(
            sa.text("INSERT INTO platform.platform_operators (user_id) VALUES (:u)"),
            {"u": operator},
        )
        membership = await plant_membership(conn, t.tenant_id, t.main, operator)
        role = await plant_role(conn, t.tenant_id, "r_operator", {"approvals.read": "workspace"})
        await assign(conn, t.tenant_id, t.main, membership, role)
        owner = await plant_person(conn, t.tenant_id)
        owner_membership = await plant_membership(conn, t.tenant_id, t.main, owner)
        await assign(
            conn,
            t.tenant_id,
            t.main,
            owner_membership,
            await role_id(conn, t.tenant_id, "tenant_owner"),
        )
    for key in owner_keys:
        with pytest.raises(IntegrityError) as refused:
            async with migrator.begin() as conn:
                await grant_privilege(conn, t.tenant_id, role, key, "tenant")
        assert _constraint(refused.value) == "ck_role_assignments_operator_not_owner"
    for listed_in in ("platform_operators", "support_staff"):
        with pytest.raises(IntegrityError) as refused:
            async with migrator.begin() as conn:
                await conn.execute(
                    sa.text(f"INSERT INTO platform.{listed_in} (user_id) VALUES (:u)"),
                    {"u": owner},
                )
        assert _constraint(refused.value) == "ck_role_assignments_operator_not_owner"


async def test_the_guard_and_the_coverage_name_the_same_two_keys(migrator: AsyncEngine) -> None:
    """One place for the two keys (step 16): `platform.owner_permission_keys()`,
    which both functions read, and each key, once registered, is a tenant key."""
    async with migrator.connect() as conn:
        keys = await conn.scalar(sa.text("SELECT platform.owner_permission_keys()"))
        bodies = {
            name: await conn.scalar(
                sa.text("SELECT pg_get_functiondef(CAST(:f AS regprocedure))"), {"f": signature}
            )
            for name, signature in (
                ("guard", "platform.guard_operator_tenant_grants()"),
                ("coverage", "platform.check_owner_coverage(uuid)"),
            )
        }
        registered: dict[str, str] = {
            row[0]: row[1]
            for row in (
                await conn.execute(
                    sa.text("SELECT key, scope_kind FROM platform.permissions WHERE key = ANY(:k)"),
                    {"k": list(keys)},
                )
            ).all()
        }
    assert sorted(keys) == ["platform.roles.write", "studio.publish.approve"]
    for name, body in bodies.items():
        assert "owner_permission_keys()" in str(body), name
        assert not any(key in str(body) for key in keys), f"{name} spells a key out itself"
    assert all(kind == "tenant" for kind in registered.values())


# ---- separation of duties across workspaces (R5.1, R5.2) ---------------------


@pytest.fixture
async def rule(migrator: AsyncEngine) -> AsyncIterator[tuple[str, str, str]]:
    suffix = uuid.uuid4().hex[:10]
    rule_key, order, pay = f"sod_test_{suffix}", f"test.s{suffix}.order", f"test.s{suffix}.pay"
    async with migrator.begin() as conn:
        for key in (order, pay):
            await register_key(conn, key)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.sod_rules (key, description, left_scopes, right_scopes,"
                " waivable) VALUES (:k, 'who orders does not pay', CAST(:l AS jsonb),"
                " CAST(:r AS jsonb), true)"
            ),
            {"k": rule_key, "l": f'["{order}"]', "r": f'["{pay}"]'},
        )
    yield rule_key, order, pay
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.sod_waivers WHERE rule_key = :k"), {"k": rule_key}
        )
        await conn.execute(
            sa.text("DELETE FROM platform.sod_rules WHERE key = :k"), {"k": rule_key}
        )
        for key in (order, pay):
            await unregister_key(conn, key)


async def test_two_sides_of_a_rule_in_two_workspaces_are_refused_with_the_holder(
    migrator: AsyncEngine, rule: tuple[str, str, str]
) -> None:
    """R5.1 (RB14)."""
    rule_key, order, pay = rule
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2)
        person = await plant_person(conn, t.tenant_id)
        at_a = await plant_membership(conn, t.tenant_id, t.workspaces[0], person)
        at_b = await plant_membership(conn, t.tenant_id, t.workspaces[1], person)
        orderer = await plant_role(conn, t.tenant_id, "r_order", {order: "workspace"})
        payer = await plant_role(conn, t.tenant_id, "r_pay", {pay: "workspace"})
        await assign(conn, t.tenant_id, t.workspaces[0], at_a, orderer)
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await assign(conn, t.tenant_id, t.workspaces[1], at_b, payer)
    assert _constraint(refused.value) == "ck_roles_sod_memberships"
    assert _detail(refused.value) == str(person)
    hint = getattr(refused.value.orig.__cause__, "hint", None)  # type: ignore[union-attr]
    assert hint == rule_key


async def test_a_role_changed_under_two_holders_names_both(
    migrator: AsyncEngine, rule: tuple[str, str, str]
) -> None:
    _, order, pay = rule
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        role = await plant_role(conn, t.tenant_id, "r_both", {order: "workspace"})
        people = []
        for _ in range(2):
            person = await plant_person(conn, t.tenant_id)
            membership = await plant_membership(conn, t.tenant_id, t.main, person)
            await assign(conn, t.tenant_id, t.main, membership, role)
            people.append(person)
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await grant_privilege(conn, t.tenant_id, role, pay, "workspace")
    assert sorted(_detail(refused.value).split(", ")) == sorted(str(p) for p in people)


async def test_a_confirmed_waiver_lets_both_sides_through_and_cannot_be_revoked_while_relied_on(
    migrator: AsyncEngine, rule: tuple[str, str, str]
) -> None:
    rule_key, order, pay = rule
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2)
        granter, confirmer = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.sod_waivers (id, tenant_id, rule_key, reason, granted_by)"
                " VALUES (gen_random_uuid(), :t, :k, 'nhỏ', :g)"
            ),
            {"t": t.tenant_id, "k": rule_key, "g": granter},
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.sod_waivers SET confirmed_at = now(), confirmed_by = :c,"
                " confirm_reason = 'đồng ý' WHERE tenant_id = :t AND rule_key = :k"
            ),
            {"t": t.tenant_id, "k": rule_key, "c": confirmer},
        )
        person = await plant_person(conn, t.tenant_id)
        at_a = await plant_membership(conn, t.tenant_id, t.workspaces[0], person)
        at_b = await plant_membership(conn, t.tenant_id, t.workspaces[1], person)
        await assign(
            conn,
            t.tenant_id,
            t.workspaces[0],
            at_a,
            await plant_role(conn, t.tenant_id, "r_o", {order: "workspace"}),
        )
        await assign(
            conn,
            t.tenant_id,
            t.workspaces[1],
            at_b,
            await plant_role(conn, t.tenant_id, "r_p", {pay: "workspace"}),
        )
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.sod_waivers SET revoked_at = now(), revoked_by = :c,"
                    " revoke_reason = 'thôi' WHERE tenant_id = :t AND rule_key = :k"
                ),
                {"t": t.tenant_id, "k": rule_key, "c": confirmer},
            )
    assert _constraint(refused.value) == "ck_sod_waivers_not_in_use"
    assert _detail(refused.value) == "1", "one person relies on it"


async def test_the_owner_role_is_not_judged_but_an_ordinary_role_it_adds_is(
    migrator: AsyncEngine, rule: tuple[str, str, str]
) -> None:
    """R5.2: the owner's computed grants hold both sides (the test keys are
    grantable and active) and pass; an ordinary role carrying both is refused."""
    _, order, pay = rule
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        owner = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, owner)
        await assign(
            conn, t.tenant_id, t.main, membership, await role_id(conn, t.tenant_id, "tenant_owner")
        )
        held = {key for key, _ in await grants_of(conn, t.tenant_id, owner)}
        both = await plant_role(
            conn, t.tenant_id, "r_both_sides", {order: "workspace", pay: "workspace"}
        )
    assert {order, pay} <= held
    with pytest.raises(IntegrityError) as refused:
        async with migrator.begin() as conn:
            await assign(conn, t.tenant_id, t.main, membership, both)
    assert _constraint(refused.value) == "ck_roles_sod_memberships"


async def test_no_role_template_breaks_a_rule_on_its_own(migrator: AsyncEngine) -> None:
    """Replaces the template triggers b9862fa13a80 and f381f1694395 put on the
    catalogue: no template, cloned alone, breaks any rule of the catalogue."""
    async with migrator.connect() as conn:
        broken = (
            await conn.execute(
                sa.text(
                    "SELECT t.key, s.key FROM ("
                    "  SELECT key, scopes FROM platform.roles"
                    "  UNION ALL SELECT key, scopes FROM platform.permission_sets) t"
                    " CROSS JOIN platform.sod_rules s"
                    " WHERE platform.sod_rule_broken("
                    "   s.key, ARRAY(SELECT jsonb_array_elements_text(t.scopes)))"
                )
            )
        ).all()
    assert broken == []


async def test_a_refusal_rolls_back_the_whole_write(
    migrator: AsyncEngine, rule: tuple[str, str, str]
) -> None:
    """The AFTER trigger's refusal leaves nothing behind."""
    _, order, pay = rule
    async with migrator.begin() as conn:
        t = await plant_tenant(conn)
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        both = await plant_role(
            conn, t.tenant_id, "r_rollback", {order: "workspace", pay: "workspace"}
        )
    with pytest.raises(DBAPIError):
        async with migrator.begin() as conn:
            await assign(conn, t.tenant_id, t.main, membership, both)
    async with migrator.connect() as conn:
        assert (
            await conn.scalar(
                sa.text("SELECT count(*) FROM platform.role_assignments WHERE membership_id = :m"),
                {"m": membership},
            )
            == 0
        )


# ---- below two holders, before either key exists (R3.12) ----------------------


async def test_no_warning_while_neither_owner_key_is_in_the_catalogue(
    migrator: AsyncEngine, test_keys: dict[str, str]
) -> None:
    """R3.12 (RB40): a key not registered yet is held by nobody and counted by
    nobody, so revoking an assignment in an active tenant sets nothing."""
    async with migrator.begin() as conn:
        registered = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.permissions"
                " WHERE key = ANY(platform.owner_permission_keys())"
            )
        )
        assert registered == 0, "the premise: neither key is registered yet"
        t = await plant_tenant(conn)
        person = await plant_person(conn, t.tenant_id)
        membership = await plant_membership(conn, t.tenant_id, t.main, person)
        role = await plant_role(conn, t.tenant_id, "r_quiet", {test_keys["workspace"]: "workspace"})
        assignment = await assign(conn, t.tenant_id, t.main, membership, role)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
        )
        since = await conn.scalar(
            sa.text("SELECT owner_coverage_low_since FROM platform.tenants WHERE id = :t"),
            {"t": t.tenant_id},
        )
        events = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.outbox_events WHERE tenant_id = :t"
                " AND event_type = 'platform.tenant.owner_coverage_low'"
            ),
            {"t": t.tenant_id},
        )
    assert (since, events) == (None, 0)
