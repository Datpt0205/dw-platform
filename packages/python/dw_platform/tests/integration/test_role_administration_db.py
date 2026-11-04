"""Integration: the database holds anti-escalation and two people for every
writer (tenant-rbac ticket 03; migration d2b57239ef50).

Every case here is raw SQL under the role named, on a migrated Postgres, so a
service that forgot a check cannot hide a trigger that lost one (failure-modes
#5). Worlds are planted as the migrator (`dw_platform.testing.rbac`); a proposal
is written and confirmed in the test's own transaction as `dw_app`, exactly as
`SqlRoleAdminRepository.confirm` does, unless the case needs it otherwise.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, admin_url, provisioner_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    grants_of,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    unregister_key,
)

pytestmark = pytest.mark.integration

_BIND = sa.text(
    "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true),"
    " set_config('app.role_change_id', :r, true), set_config('app.workspace_id', :w, true)"
)


def _cause(error: BaseException) -> object:
    return getattr(getattr(error, "orig", None), "__cause__", None)


def refused(error: BaseException) -> tuple[str | None, str]:
    cause = _cause(error)
    return getattr(cause, "constraint_name", None), getattr(cause, "detail", None) or ""


async def bind(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    user: uuid.UUID | None = None,
    request: uuid.UUID | None = None,
    workspace: uuid.UUID | None = None,
) -> None:
    await conn.execute(
        _BIND,
        {
            "t": str(tenant),
            "u": str(user) if user else "",
            "r": str(request or ""),
            "w": str(workspace or ""),
        },
    )


async def propose(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    proposer: uuid.UUID,
    kind: str,
    payload: Mapping[str, object],
    *,
    role: uuid.UUID | None = None,
    base_version: int | None = None,
) -> uuid.UUID:
    """A proposal as `dw_app` writes it: by its own proposer, open."""
    request = uuid.uuid4()
    await bind(conn, tenant, proposer)
    await conn.execute(
        sa.text(
            "INSERT INTO platform.role_change_requests (id, tenant_id, kind, payload, role_id,"
            " base_version, required_permission, proposed_by, expires_at, status)"
            " VALUES (:id, :t, :k, CAST(:p AS jsonb), :r, :v, :perm, :by,"
            " now() + interval '7 days', 'proposed')"
        ),
        {
            "id": request,
            "t": tenant,
            "k": kind,
            "p": json.dumps(payload, default=str),
            "r": role,
            "v": base_version,
            "perm": "platform.roles.bind" if kind == "assignment_grant" else "platform.roles.write",
            "by": proposer,
        },
    )
    return request


async def confirm(
    conn: AsyncConnection, tenant: uuid.UUID, confirmer: uuid.UUID, request: uuid.UUID
) -> None:
    """The confirmation's first two statements, then `app.role_change_id`."""
    await bind(conn, tenant, confirmer, request)
    await conn.execute(
        sa.text(
            "UPDATE platform.role_change_requests"
            " SET status = 'confirmed', confirmed_by = :c, decided_at = now() WHERE id = :id"
        ),
        {"c": confirmer, "id": request},
    )


@dataclass(frozen=True)
class World:
    """One tenant, two workspaces. `writer` and `checker` hold
    `platform.roles.write` and `key` at `workspace` depth in ws0 (never
    `platform.roles.bind`); `holder` holds `held` (`key` at workspace) in ws0;
    `owner_a`, `owner_b` are its two owners."""

    tenant: PlantedTenant
    key: str
    other_key: str
    writer: uuid.UUID
    checker: uuid.UUID
    holder: uuid.UUID
    holder_membership: uuid.UUID
    held: uuid.UUID
    owner_a: uuid.UUID
    owner_b: uuid.UUID

    @property
    def t(self) -> uuid.UUID:
        return self.tenant.tenant_id


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
async def superuser(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def provisioner(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(provisioner_url(db_urls.migrator), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def keys(migrator: AsyncEngine) -> AsyncIterator[tuple[str, str]]:
    suffix = uuid.uuid4().hex[:10]
    made = (f"test.r{suffix}.one", f"test.r{suffix}.two")
    async with migrator.begin() as conn:
        for key in made:
            await register_key(conn, key)
    yield made
    async with migrator.begin() as conn:
        for key in made:
            await unregister_key(conn, key)


async def plant_world(
    migrator: AsyncEngine, keys: tuple[str, str], *, status: str = "active"
) -> World:
    key, other = keys
    async with migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2, status=status)
        writer_role = await plant_role(
            conn, t.tenant_id, "role_writer", {"platform.roles.write": "tenant", key: "workspace"}
        )
        held = await plant_role(conn, t.tenant_id, "held_role", {key: "workspace"})
        people: list[uuid.UUID] = []
        for _ in range(2):
            person = await plant_person(conn, t.tenant_id)
            m = await plant_membership(conn, t.tenant_id, t.main, person)
            await assign(conn, t.tenant_id, t.main, m, writer_role)
            people.append(person)
        holder = await plant_person(conn, t.tenant_id)
        holder_membership = await plant_membership(conn, t.tenant_id, t.main, holder)
        await assign(conn, t.tenant_id, t.main, holder_membership, held)
        owners: list[uuid.UUID] = []
        if status != "setup":
            owner_role = await role_id(conn, t.tenant_id, "tenant_owner")
            for _ in range(2):
                owner = await plant_person(conn, t.tenant_id)
                m = await plant_membership(conn, t.tenant_id, t.main, owner)
                await assign(conn, t.tenant_id, t.main, m, owner_role)
                owners.append(owner)
        else:
            owners = [uuid.uuid4(), uuid.uuid4()]
    return World(
        t, key, other, people[0], people[1], holder, holder_membership, held, owners[0], owners[1]
    )


async def _expect_refusal(
    engine: AsyncEngine, steps: object, constraint: str, detail: str | None = None
) -> None:
    with pytest.raises(IntegrityError) as caught:
        async with engine.begin() as conn:
            await steps(conn)  # type: ignore[operator]
    name, said = refused(caught.value)
    assert name == constraint, (name, said)
    if detail is not None:
        assert said == detail, (name, said)


async def _count(migrator: AsyncEngine, sql: str, **params: object) -> int:
    async with migrator.connect() as conn:
        return int(await conn.scalar(sa.text(sql), params) or 0)


# ---- R6.1, R6.2 (RB15): the hold rule at the trigger -------------------------


async def test_the_hold_rule_refuses_raw_sql_carrying_a_confirmed_proposal(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.2 (RB15) in an `active` company: each widening write carries a
    proposal another person confirmed in the very transaction, so only
    `platform.rbac_refusals` can still refuse it, and DETAIL says
    `rbac_escalation`, not the two-people refusal. The checker holds the key at
    `workspace` depth in ws0 only."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        version = await conn.scalar(
            sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": w.held}
        )

    async def deepen(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.writer,
            "role_permissions",
            {"permissions": [{"key": w.key, "depth": "tenant"}]},
            role=w.held,
            base_version=version,
        )
        await confirm(conn, w.t, w.checker, request)
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_role_permissions SET depth = 'tenant'"
                " WHERE role_id = :r AND permission_key = :k"
            ),
            {"r": w.held, "k": w.key},
        )

    async def add_unheld_key(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.writer,
            "role_permissions",
            {
                "permissions": [
                    {"key": w.key, "depth": "workspace"},
                    {"key": w.other_key, "depth": "workspace"},
                ]
            },
            role=w.held,
            base_version=version,
        )
        await confirm(conn, w.t, w.checker, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth) VALUES (:t, :r, :k, 'workspace')"
            ),
            {"t": w.t, "r": w.held, "k": w.other_key},
        )

    async def create_with_unheld_key(conn: AsyncConnection) -> None:
        new_role = uuid.uuid4()
        payload: dict[str, object] = {
            "role_id": str(new_role),
            "key": "made_role",
            "name": "Made",
            "kind": "role",
            "description": None,
            "template_key": None,
            "permissions": [{"key": w.other_key, "depth": "workspace"}],
        }
        request = await propose(conn, w.t, w.writer, "role_create", payload)
        await confirm(conn, w.t, w.checker, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
                " VALUES (:id, :t, 'made_role', 'Made', 'role')"
            ),
            {"id": new_role, "t": w.t},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth) VALUES (:t, :r, :k, 'workspace')"
            ),
            {"t": w.t, "r": new_role, "k": w.other_key},
        )

    for steps, table in (
        (deepen, "tenant_role_permissions"),
        (add_unheld_key, "tenant_role_permissions"),
        (create_with_unheld_key, "tenant_role_permissions"),
    ):
        await _expect_refusal(app, steps, f"rbac_refusals_{table}", "rbac_escalation")
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.tenant_roles WHERE key = 'made_role' AND tenant_id = :t",
            t=w.t,
        )
        == 0
    )

    # The same proposals within what the checker holds pass: what refused
    # above was the hold rule, nothing else.
    async def add_held_key(conn: AsyncConnection) -> None:
        new_role = uuid.uuid4()
        payload: dict[str, object] = {
            "role_id": str(new_role),
            "key": "ok_role",
            "name": "Ok",
            "kind": "role",
            "description": None,
            "template_key": None,
            "permissions": [{"key": w.key, "depth": "workspace"}],
        }
        request = await propose(conn, w.t, w.writer, "role_create", payload)
        await confirm(conn, w.t, w.checker, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
                " VALUES (:id, :t, 'ok_role', 'Ok', 'role')"
            ),
            {"id": new_role, "t": w.t},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth) VALUES (:t, :r, :k, 'workspace')"
            ),
            {"t": w.t, "r": new_role, "k": w.key},
        )

    async with app.begin() as conn:
        await add_held_key(conn)


async def test_an_assignment_confirmed_by_a_bind_holder_who_lacks_the_key_is_refused(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.1, R6.3 (RB15, RB16): `platform.roles.bind` covers only a role that is
    not critical; a critical role with a key the confirmer lacks at `tenant` is
    refused `rbac_escalation` at the trigger, the bind holder's own write."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        binder_role = await plant_role(
            conn, w.t, "binder", {"platform.roles.bind": "tenant", w.key: "workspace"}
        )
        binders: list[uuid.UUID] = []
        for _ in range(2):
            person = await plant_person(conn, w.t)
            m = await plant_membership(conn, w.t, w.tenant.main, person)
            await assign(conn, w.t, w.tenant.main, m, binder_role)
            binders.append(person)
        critical = await plant_role(
            conn, w.t, "critical_role", {w.key: "tenant", "platform.roles.write": "tenant"}
        )
        plain = await plant_role(conn, w.t, "plain_role", {w.other_key: "workspace"})
        target = await plant_person(conn, w.t)
        tm = await plant_membership(conn, w.t, w.tenant.main, target)

    def grant(role: uuid.UUID) -> object:
        async def steps(conn: AsyncConnection) -> None:
            payload: dict[str, object] = {
                "membership_id": str(tm),
                "workspace_id": str(w.tenant.main),
                "user_id": str(target),
            }
            request = await propose(
                conn, w.t, binders[0], "assignment_grant", payload, role=role, base_version=1
            )
            await confirm(conn, w.t, binders[1], request)
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.role_assignments"
                    " (id, tenant_id, workspace_id, membership_id, role_id)"
                    " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
                ),
                {"t": w.t, "w": w.tenant.main, "m": tm, "r": role},
            )

        return steps

    await _expect_refusal(app, grant(critical), "rbac_refusals_role_assignments", "rbac_escalation")
    # R6.3: a role with nothing critical, whose key the binder does not hold.
    async with app.begin() as conn:
        await grant(plain)(conn)  # type: ignore[operator]


@pytest.mark.parametrize("status", ["locked", "setup"])
async def test_the_hold_rule_holds_in_a_company_that_is_not_active(
    migrator: AsyncEngine, superuser: AsyncEngine, keys: tuple[str, str], status: str
) -> None:
    """R6.2 (RB15) in a `locked` and a `setup` company. Nobody there holds a
    grant (`platform.effective_grants` counts an active company only), so no
    proposal can be confirmed through its guard: the confirmed proposal is
    planted with triggers off, and the write is made by a superuser session,
    which the triggers judge like `dw_app`. The hold rule refuses it; and
    narrowing without an actor is refused too (the exemption is for
    `offboarding` alone)."""
    w = await plant_world(migrator, keys, status="active" if status == "locked" else "setup")
    async with migrator.begin() as conn:
        if status == "locked":
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'locked' WHERE id = :t"), {"t": w.t}
            )
        version = await conn.scalar(
            sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": w.held}
        )

    async def deepen(conn: AsyncConnection) -> None:
        request = uuid.uuid4()
        await conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await conn.execute(
            sa.text(
                "INSERT INTO platform.role_change_requests (id, tenant_id, kind, payload, role_id,"
                " base_version, required_permission, proposed_by, expires_at, status,"
                " confirmed_by, decided_at) VALUES (:id, :t, 'role_permissions', CAST(:p AS jsonb),"
                " :r, :v, 'platform.roles.write', :by, now() + interval '7 days', 'confirmed',"
                " :c, now())"
            ),
            {
                "id": request,
                "t": w.t,
                "r": w.held,
                "v": version,
                "by": w.writer,
                "c": w.checker,
                "p": json.dumps({"permissions": [{"key": w.key, "depth": "tenant"}]}),
            },
        )
        await conn.execute(sa.text("SET LOCAL session_replication_role = origin"))
        await bind(conn, w.t, w.checker, request)
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_role_permissions SET depth = 'tenant'"
                " WHERE role_id = :r AND permission_key = :k"
            ),
            {"r": w.held, "k": w.key},
        )

    async def revoke_without_actor(conn: AsyncConnection) -> None:
        await bind(conn, w.t)
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE membership_id = :m"),
            {"m": w.holder_membership},
        )

    await _expect_refusal(
        superuser, deepen, "rbac_refusals_tenant_role_permissions", "rbac_escalation"
    )
    await _expect_refusal(
        superuser, revoke_without_actor, "rbac_refusals_role_assignments", "rbac_actor_missing"
    )


async def test_without_an_actor_dw_app_changes_no_role(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.2: a `dw_app` write naming no `app.user_id` is refused, narrowing
    included, in an `active` company."""
    w = await plant_world(migrator, keys)

    async def revoke(conn: AsyncConnection) -> None:
        await bind(conn, w.t)
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE membership_id = :m"),
            {"m": w.holder_membership},
        )

    await _expect_refusal(app, revoke, "rbac_refusals_role_assignments", "rbac_actor_missing")


async def test_offboarding_exempts_what_narrows_and_nothing_that_widens(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.2 (RB15): in a company `offboarding`, the purge's narrowing writes
    need no actor; a key added or a role assigned is refused there too."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        spare = await plant_role(conn, w.t, "spare_role", {w.key: "workspace"})
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"), {"t": w.t}
        )

    async def add_key(conn: AsyncConnection) -> None:
        await bind(conn, w.t)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth) VALUES (:t, :r, :k, 'workspace')"
            ),
            {"t": w.t, "r": w.held, "k": w.other_key},
        )

    async def assign_with_actor(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.writer)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.role_assignments"
                " (id, tenant_id, workspace_id, membership_id, role_id)"
                " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
            ),
            {"t": w.t, "w": w.tenant.main, "m": w.holder_membership, "r": spare},
        )

    await _expect_refusal(
        app, add_key, "rbac_refusals_tenant_role_permissions", "rbac_actor_missing"
    )
    await _expect_refusal(
        app, assign_with_actor, "rbac_refusals_role_assignments", "rbac_two_people"
    )

    async with app.begin() as conn:
        await bind(conn, w.t)
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE membership_id = :m"),
            {"m": w.holder_membership},
        )
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_role_permissions WHERE role_id = :r"),
            {"r": w.held},
        )
        await conn.execute(sa.text("DELETE FROM platform.tenant_roles WHERE id = :r"), {"r": spare})


# ---- R6.4-R6.6 (RB17-RB19) ------------------------------------------------------


async def test_nobody_assigns_a_role_to_themselves_even_as_the_confirmer(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.4 (RB17): `app.user_id` is the grantee → `rbac_self_assignment`."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        mine = await plant_membership(conn, w.t, w.tenant.workspaces[1], w.owner_a)
        member = await role_id(conn, w.t, "member")

    async def steps(conn: AsyncConnection) -> None:
        payload: dict[str, object] = {
            "membership_id": str(mine),
            "workspace_id": str(w.tenant.workspaces[1]),
            "user_id": str(w.owner_a),
        }
        request = await propose(
            conn, w.t, w.owner_b, "assignment_grant", payload, role=member, base_version=1
        )
        await confirm(conn, w.t, w.owner_a, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.role_assignments"
                " (id, tenant_id, workspace_id, membership_id, role_id)"
                " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
            ),
            {"t": w.t, "w": w.tenant.workspaces[1], "m": mine, "r": member},
        )

    await _expect_refusal(app, steps, "rbac_refusals_role_assignments", "rbac_self_assignment")


async def test_a_key_no_tenant_may_hold_and_the_platform_admin_role_never_enter(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.5 (RB18): `platform.admin` into a role, and a role keyed
    `platform_admin`, are `rbac_not_grantable` at the trigger."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        version = await conn.scalar(
            sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": w.held}
        )

    async def add_admin_key(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            {
                "permissions": [
                    {"key": w.key, "depth": "workspace"},
                    {"key": "platform.admin", "depth": "tenant"},
                ]
            },
            role=w.held,
            base_version=version,
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth)"
                " VALUES (:t, :r, 'platform.admin', 'tenant')"
            ),
            {"t": w.t, "r": w.held},
        )

    async def make_admin_role(conn: AsyncConnection) -> None:
        new_role = uuid.uuid4()
        payload: dict[str, object] = {
            "role_id": str(new_role),
            "key": "platform_admin",
            "name": "x",
            "kind": "role",
            "description": None,
            "template_key": None,
            "permissions": [],
        }
        request = await propose(conn, w.t, w.owner_a, "role_create", payload)
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
                " VALUES (:id, :t, 'platform_admin', 'x', 'role')"
            ),
            {"id": new_role, "t": w.t},
        )

    await _expect_refusal(
        app, add_admin_key, "rbac_refusals_tenant_role_permissions", "rbac_not_grantable"
    )
    await _expect_refusal(app, make_admin_role, "rbac_refusals_tenant_roles", "rbac_not_grantable")


async def test_system_roles_keep_their_shape_against_raw_sql(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.6 (RB19): deleting `member` (hard or soft), re-keying it, and any
    privilege of `tenant_owner` are refused, by an owner too."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        member = await role_id(conn, w.t, "member")
        owner = await role_id(conn, w.t, "tenant_owner")
        owner_version = await conn.scalar(
            sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": owner}
        )

    def delete(sql: str) -> object:
        async def steps(conn: AsyncConnection) -> None:
            await bind(conn, w.t, w.owner_a)
            await conn.execute(sa.text(sql), {"r": member})

        return steps

    await _expect_refusal(
        app,
        delete("UPDATE platform.tenant_roles SET deleted_at = now() WHERE id = :r"),
        "rbac_refusals_tenant_roles",
        "role_is_system",
    )
    with pytest.raises(IntegrityError) as caught:
        async with app.begin() as conn:
            await bind(conn, w.t, w.owner_a)
            await conn.execute(
                sa.text("DELETE FROM platform.tenant_role_permissions WHERE role_id = :r"),
                {"r": member},
            )
            await conn.execute(
                sa.text("DELETE FROM platform.tenant_roles WHERE id = :r"), {"r": member}
            )
    assert refused(caught.value)[0] in {"rbac_refusals_tenant_roles", "ck_tenant_roles_in_use"}
    await _expect_refusal(
        app,
        delete("UPDATE platform.tenant_roles SET key = 'renamed' WHERE id = :r"),
        "rbac_refusals_tenant_roles",
    )

    async def owner_privilege(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            {"permissions": [{"key": w.key, "depth": "tenant"}]},
            role=owner,
            base_version=owner_version,
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth) VALUES (:t, :r, :k, 'tenant')"
            ),
            {"t": w.t, "r": owner, "k": w.key},
        )

    await _expect_refusal(
        app, owner_privilege, "rbac_refusals_tenant_role_permissions", "role_is_system"
    )


# ---- R6.7 (RB20): the last owner ----------------------------------------------


@pytest.mark.parametrize("status", ["active", "locked"])
@pytest.mark.parametrize("removal", ["assignment", "membership", "member", "suspend", "user"])
async def test_the_last_active_owner_stays(
    migrator: AsyncEngine, keys: tuple[str, str], status: str, removal: str
) -> None:
    """R6.7 (RB20): every way of removing the last active owner is refused
    `ck_role_assignments_last_owner`, cascades included, in an `active` and a
    `locked` company; the migrator is judged here too (anti-escalation exempts
    it, the last-owner rule does not)."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        # One owner left.
        await conn.execute(
            sa.text("DELETE FROM platform.memberships WHERE tenant_id = :t AND user_id = :u"),
            {"t": w.t, "u": w.owner_b},
        )
        if status == "locked":
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'locked' WHERE id = :t"), {"t": w.t}
            )
    sql = {
        "assignment": "DELETE FROM platform.role_assignments a USING platform.memberships m"
        " WHERE m.id = a.membership_id AND m.user_id = :u AND a.tenant_id = :t",
        "membership": "DELETE FROM platform.memberships WHERE tenant_id = :t AND user_id = :u",
        "member": "DELETE FROM platform.tenant_members WHERE tenant_id = :t AND user_id = :u",
        "suspend": "UPDATE platform.tenant_members SET status = 'suspended'"
        " WHERE tenant_id = :t AND user_id = :u",
        "user": "DELETE FROM platform.users WHERE id = :u",
    }[removal]
    with pytest.raises(IntegrityError) as caught:
        async with migrator.begin() as conn:
            await conn.execute(sa.text(sql), {"t": w.t, "u": w.owner_a})
    assert refused(caught.value)[0] == "ck_role_assignments_last_owner"
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.active_tenant_owners(:t)",
            t=w.t,
        )
        == 1
    )


async def test_a_second_owner_may_go_and_a_company_without_owners_is_not_held(
    migrator: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.7: only the write that takes the count from one to none is refused;
    a company that had no owner (a seed without `org_admin`) is not blocked."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.memberships WHERE tenant_id = :t AND user_id = :u"),
            {"t": w.t, "u": w.owner_b},
        )
        bare = await plant_tenant(conn)
        person = await plant_person(conn, bare.tenant_id)
        await plant_membership(conn, bare.tenant_id, bare.main, person)
        await conn.execute(
            sa.text("DELETE FROM platform.memberships WHERE tenant_id = :t AND user_id = :u"),
            {"t": bare.tenant_id, "u": person},
        )


async def test_a_tenant_owner_assignment_never_expires(
    migrator: AsyncEngine, keys: tuple[str, str]
) -> None:
    w = await plant_world(migrator, keys)
    with pytest.raises(IntegrityError) as caught:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.role_assignments a SET expires_at = now() + interval '1 day'"
                    " FROM platform.memberships m WHERE m.id = a.membership_id AND m.user_id = :u"
                ),
                {"u": w.owner_a},
            )
    assert refused(caught.value)[0] == "ck_role_assignments_last_owner"


async def test_two_removals_of_the_last_two_owners_queue_and_one_is_refused(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R6.7 (RB20): two administrators remove the last two owners at once;
    the tenant row lock makes the second count after the first commits, so
    exactly one is refused. Without the lock both pass."""
    w = await plant_world(migrator, keys)
    revoke = sa.text(
        "DELETE FROM platform.role_assignments a USING platform.memberships m"
        " WHERE m.id = a.membership_id AND m.user_id = :u AND a.tenant_id = :t"
    )
    first = await migrator.connect()
    second = await migrator.connect()
    try:
        tx1 = await first.begin()
        await first.execute(revoke, {"u": w.owner_a, "t": w.t})
        tx2 = await second.begin()
        racing = asyncio.create_task(second.execute(revoke, {"u": w.owner_b, "t": w.t}))
        await asyncio.sleep(0.5)
        assert not racing.done(), "the second removal waits on the tenant row"
        await tx1.commit()
        with pytest.raises(IntegrityError) as caught:
            await racing
        assert refused(caught.value)[0] == "ck_role_assignments_last_owner"
        await tx2.rollback()
    finally:
        await first.close()
        await second.close()
    assert (
        await _count(migrator, "SELECT count(*) FROM platform.active_tenant_owners(:t)", t=w.t) == 1
    )


# ---- R7.5 (RB21): two people at the trigger ----------------------------------


async def test_a_widening_write_opens_only_with_its_own_confirmed_proposal(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.5 (RB21): each way of borrowing a proposal is refused
    `rbac_two_people`; the write it confirms, as its payload says, passes."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        other = await plant_role(conn, w.t, "other_role", {w.key: "workspace"})
        versions = {
            r: await conn.scalar(
                sa.text("SELECT version FROM platform.tenant_roles WHERE id = :r"), {"r": r}
            )
            for r in (w.held, other)
        }
        target = await plant_person(conn, w.t)
        tm = await plant_membership(conn, w.t, w.tenant.main, target)

    add_key = sa.text(
        "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key, depth)"
        " VALUES (:t, :r, :k, :d)"
    )
    grant = sa.text(
        "INSERT INTO platform.role_assignments"
        " (id, tenant_id, workspace_id, membership_id, role_id)"
        " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
    )
    target_payload = {
        "permissions": [
            {"key": w.key, "depth": "workspace"},
            {"key": w.other_key, "depth": "workspace"},
        ]
    }

    async def no_proposal(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": tm, "r": w.held})

    async def own_proposal(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            target_payload,
            role=w.held,
            base_version=versions[w.held],
        )
        await bind(conn, w.t, w.owner_a, request)
        await conn.execute(add_key, {"t": w.t, "r": w.held, "k": w.other_key, "d": "workspace"})

    async def other_role(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            target_payload,
            role=w.held,
            base_version=versions[w.held],
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(add_key, {"t": w.t, "r": other, "k": w.other_key, "d": "workspace"})

    async def wrong_kind(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_update",
            {"name": "Renamed", "description": None},
            role=w.held,
            base_version=versions[w.held],
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": tm, "r": w.held})

    async def still_proposed(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            target_payload,
            role=w.held,
            base_version=versions[w.held],
        )
        await bind(conn, w.t, w.owner_b, request)
        await conn.execute(add_key, {"t": w.t, "r": w.held, "k": w.other_key, "d": "workspace"})

    async def off_payload(conn: AsyncConnection) -> None:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            target_payload,
            role=w.held,
            base_version=versions[w.held],
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(add_key, {"t": w.t, "r": w.held, "k": w.other_key, "d": "tenant"})

    for steps, table in (
        (no_proposal, "role_assignments"),
        (own_proposal, "tenant_role_permissions"),
        (other_role, "tenant_role_permissions"),
        (wrong_kind, "role_assignments"),
        (still_proposed, "tenant_role_permissions"),
        (off_payload, "tenant_role_permissions"),
    ):
        await _expect_refusal(app, steps, f"rbac_refusals_{table}", "rbac_two_people")

    # Confirmed in a transaction before this one: opens nothing now.
    async with app.begin() as conn:
        earlier = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            target_payload,
            role=w.held,
            base_version=versions[w.held],
        )
        await confirm(conn, w.t, w.owner_b, earlier)

    async def confirmed_before(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_b, earlier)
        await conn.execute(add_key, {"t": w.t, "r": w.held, "k": w.other_key, "d": "workspace"})

    await _expect_refusal(
        app, confirmed_before, "rbac_refusals_tenant_role_permissions", "rbac_two_people"
    )

    # The write the proposal confirms, as its payload says.
    async with app.begin() as conn:
        request = await propose(
            conn,
            w.t,
            w.owner_a,
            "role_permissions",
            target_payload,
            role=w.held,
            base_version=versions[w.held],
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(add_key, {"t": w.t, "r": w.held, "k": w.other_key, "d": "workspace"})
    # And a narrowing write needs only its actor.
    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE membership_id = :m"),
            {"m": w.holder_membership},
        )


async def test_a_proposal_moves_only_as_its_state_machine_allows(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.5, R7.8 (RB21, RB43): proposed by its own proposer, open; confirmed
    only by a holder of its permission; a closed row is never touched again,
    even by an UPDATE that changes nothing."""
    w = await plant_world(migrator, keys)
    insert = sa.text(
        "INSERT INTO platform.role_change_requests (id, tenant_id, kind, payload, role_id,"
        " base_version, required_permission, proposed_by, expires_at, status, confirmed_by,"
        " decided_at) VALUES (gen_random_uuid(), :t, 'role_update', '{}'::jsonb, :r, 1,"
        " 'platform.roles.write', :by, now() + interval '7 days', :s, :c, :d)"
    )

    async def foreign_proposer(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            insert, {"t": w.t, "r": w.held, "by": w.owner_b, "s": "proposed", "c": None, "d": None}
        )

    async def born_confirmed(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            insert,
            {"t": w.t, "r": w.held, "by": w.owner_a, "s": "proposed", "c": w.owner_b, "d": None},
        )

    await _expect_refusal(app, foreign_proposer, "ck_role_change_requests_insert")
    with pytest.raises(IntegrityError):
        async with app.begin() as conn:
            await born_confirmed(conn)

    async with migrator.begin() as conn:
        # Someone holding the change's keys but not `platform.roles.write`.
        keyholder = await plant_person(conn, w.t)
        m = await plant_membership(conn, w.t, w.tenant.main, keyholder)
        await assign(conn, w.t, w.tenant.main, m, w.held)

    async def confirmed_by_a_non_holder(conn: AsyncConnection) -> None:
        request = await propose(
            conn, w.t, w.owner_a, "role_update", {"name": "N"}, role=w.held, base_version=1
        )
        await confirm(conn, w.t, keyholder, request)

    await _expect_refusal(app, confirmed_by_a_non_holder, "ck_role_change_requests_transition")

    async with app.begin() as conn:
        closed = await propose(
            conn, w.t, w.owner_a, "role_update", {"name": "N"}, role=w.held, base_version=1
        )
        await confirm(conn, w.t, w.owner_b, closed)

    async def touch_closed(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_b, closed)
        await conn.execute(
            sa.text(
                "UPDATE platform.role_change_requests SET decided_at = decided_at WHERE id = :id"
            ),
            {"id": closed},
        )
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET name = 'N' WHERE id = :r"), {"r": w.held}
        )

    async def reopen(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_b)
        await conn.execute(
            sa.text(
                "UPDATE platform.role_change_requests SET status = 'proposed',"
                " confirmed_by = NULL, decided_at = NULL WHERE id = :id"
            ),
            {"id": closed},
        )

    await _expect_refusal(app, touch_closed, "ck_role_change_requests_closed")
    await _expect_refusal(app, reopen, "ck_role_change_requests_closed")


async def test_another_tenants_proposal_opens_nothing_here(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R3.3 (RB8): a proposal of company B, confirmed in this transaction, named
    while bound to company A, opens nothing in A; the reader of proposals
    filters by `app.tenant_id`, its only layer (the guard runs as definer)."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        b = await plant_tenant(conn)
        owner = await role_id(conn, b.tenant_id, "tenant_owner")
        from dw_platform.testing.members import add_tenant_member

        await add_tenant_member(conn, b.tenant_id, w.owner_a, "active")
        await add_tenant_member(conn, b.tenant_id, w.owner_b, "active")
        for person in (w.owner_a, w.owner_b):
            m = await plant_membership(conn, b.tenant_id, b.main, person)
            await assign(conn, b.tenant_id, b.main, m, owner)

    new_role = uuid.uuid4()
    payload: dict[str, object] = {
        "role_id": str(new_role),
        "key": "borrowed",
        "name": "B",
        "kind": "role",
        "description": None,
        "template_key": None,
        "permissions": [],
    }

    async def steps(conn: AsyncConnection) -> None:
        request = await propose(conn, b.tenant_id, w.owner_a, "role_create", payload)
        await confirm(conn, b.tenant_id, w.owner_b, request)
        await bind(conn, w.t, w.owner_b, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
                " VALUES (:id, :t, 'borrowed', 'B', 'role')"
            ),
            {"id": new_role, "t": w.t},
        )

    await _expect_refusal(app, steps, "rbac_refusals_tenant_roles", "rbac_two_people")


async def test_dw_app_deletes_a_proposal_only_while_offboarding(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.7 (RB36)."""
    w = await plant_world(migrator, keys)
    async with app.begin() as conn:
        request = await propose(
            conn, w.t, w.owner_a, "role_update", {"name": "N"}, role=w.held, base_version=1
        )

    async def delete(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            sa.text("DELETE FROM platform.role_change_requests WHERE id = :id"), {"id": request}
        )

    await _expect_refusal(app, delete, "ck_role_change_requests_delete")
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"), {"t": w.t}
        )
    async with app.begin() as conn:
        await delete(conn)
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.role_change_requests WHERE id = :id",
            id=request,
        )
        == 0
    )


# ---- R7.5 (RB21): the Digital Worker exception ---------------------------------


async def _plant_dw(
    conn: AsyncConnection,
    w: World,
    creator: uuid.UUID,
    *,
    principal: uuid.UUID | None = None,
    state: str = "draft",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A DW and its principal as `DigitalWorkerService.create` writes them, up
    to the principal's membership; returns (principal, membership)."""
    if principal is None:
        principal = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                " VALUES (:u, :s, 'DW', 'service', :t)"
            ),
            {"u": principal, "s": f"service:{principal}", "t": w.t},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.service_principals"
                " (user_id, tenant_id, owning_workspace_id, name, owner_user_id)"
                " VALUES (:u, :t, :w, :n, :o)"
            ),
            {"u": principal, "t": w.t, "w": w.tenant.main, "n": f"dw-{principal}", "o": creator},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
                " VALUES (:t, :u, 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": w.t, "u": principal},
        )
    await conn.execute(
        sa.text(
            "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id, principal_user_id,"
            " key, name, mandate, work_kinds, allowed_tools, workflow_key, workflow_version,"
            " parameters, state, technical_owner_id, work_assigner_id, validator_id, created_by)"
            " VALUES (gen_random_uuid(), :t, :w, :p, :k, 'DW', 'm', ARRAY['marketing.lead'],"
            " '{}'::text[], 'lead_care', '1.0.0', '{}'::jsonb, :s, :c, :c, :c, :c)"
        ),
        {
            "t": w.t,
            "w": w.tenant.main,
            "p": principal,
            "k": f"dw_{principal.hex[:8]}",
            "s": state,
            "c": creator,
        },
    )
    membership = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
            " VALUES (:m, :t, :w, :u) ON CONFLICT DO NOTHING"
        ),
        {"m": membership, "t": w.t, "w": w.tenant.main, "u": principal},
    )
    found = await conn.scalar(
        sa.text("SELECT id FROM platform.memberships WHERE tenant_id = :t AND user_id = :u"),
        {"t": w.t, "u": principal},
    )
    return principal, uuid.UUID(str(found))


async def test_a_dw_principal_gets_its_first_roles_only_in_its_creators_draft_transaction(
    migrator: AsyncEngine, app: AsyncEngine, superuser: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.5 (RB21), ADR-0104 Amendments 2026-11-03/04: the one assignment
    without a proposal. Each case builds every other part of the exception
    right in one transaction, so dropping one condition makes its case pass."""
    w = await plant_world(migrator, keys)
    grant = sa.text(
        "INSERT INTO platform.role_assignments"
        " (id, tenant_id, workspace_id, membership_id, role_id)"
        " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
    )

    async def happy(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        _, m = await _plant_dw(conn, w, w.owner_a)
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": m, "r": w.held})

    async with app.begin() as conn:
        await happy(conn)

    async def made_operating(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        principal, m = await _plant_dw(conn, w, w.owner_a)
        await conn.execute(
            sa.text(
                "UPDATE platform.digital_workers SET state = 'operating'"
                " WHERE principal_user_id = :p"
            ),
            {"p": principal},
        )
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": m, "r": w.held})

    async def other_creator(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        _, m = await _plant_dw(conn, w, w.owner_a)
        await bind(conn, w.t, w.owner_b, workspace=w.tenant.main)
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": m, "r": w.held})

    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        _, earlier_m = await _plant_dw(conn, w, w.owner_a)

    async def dw_from_before(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": earlier_m, "r": w.held})

    async with app.begin() as conn:
        # An existing run-as account, with its principal row, no DW yet.
        await bind(conn, w.t, w.owner_a)
        run_as = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                " VALUES (:u, :s, 'run-as', 'service', :t)"
            ),
            {"u": run_as, "s": f"service:{run_as}", "t": w.t},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.service_principals"
                " (user_id, tenant_id, owning_workspace_id, name, owner_user_id)"
                " VALUES (:u, :t, :w, 'run-as', :o)"
            ),
            {"u": run_as, "t": w.t, "w": w.tenant.main, "o": w.owner_a},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_members (tenant_id, user_id, status)"
                " VALUES (:t, :u, 'active')"
            ),
            {"t": w.t, "u": run_as},
        )

    async def existing_account(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        _, m = await _plant_dw(conn, w, w.owner_a, principal=run_as)
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": m, "r": w.held})

    for steps in (made_operating, other_creator, dw_from_before, existing_account):
        await _expect_refusal(app, steps, "rbac_refusals_role_assignments", "rbac_two_people")

    async def age_the_account(conn: AsyncConnection) -> None:
        # Only the migrator holds UPDATE on users; the guard holds against any
        # other session that could (a superuser's, here), so an old account
        # cannot be made to look made in this transaction.
        await conn.execute(
            sa.text("UPDATE platform.users SET created_at = now() WHERE id = :u"), {"u": run_as}
        )

    await _expect_refusal(superuser, age_the_account, "ck_users_created_at_fixed")

    async def human_principal(conn: AsyncConnection) -> None:
        # The foreign keys and the principal guard keep a DW from pointing at
        # a human; planted past them, the exception's own `kind` arm refuses.
        human = await plant_person(conn, w.t)
        await conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await conn.execute(
            sa.text("UPDATE platform.users SET created_at = now() WHERE id = :u"), {"u": human}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.service_principals"
                " (user_id, tenant_id, owning_workspace_id, name, owner_user_id)"
                " VALUES (:u, :t, :w, 'human', :o)"
            ),
            {"u": human, "t": w.t, "w": w.tenant.main, "o": w.owner_a},
        )
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        _, m = await _plant_dw(conn, w, w.owner_a, principal=human)
        await conn.execute(sa.text("SET LOCAL session_replication_role = origin"))
        await conn.execute(grant, {"t": w.t, "w": w.tenant.main, "m": m, "r": w.held})

    await _expect_refusal(
        superuser, human_principal, "rbac_refusals_role_assignments", "rbac_two_people"
    )


async def test_a_confirmed_grant_to_an_operating_dws_principal_meets_the_dw_guard(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.5 (RB21), digital-worker R1.17: through two people, the DW guard
    (named to fire after the two-people trigger) refuses by its own name."""
    w = await plant_world(migrator, keys)
    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_a, workspace=w.tenant.main)
        principal, m = await _plant_dw(conn, w, w.owner_a, state="draft")
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.digital_workers SET state = 'operating'"
                " WHERE principal_user_id = :p"
            ),
            {"p": principal},
        )

    async def steps(conn: AsyncConnection) -> None:
        payload: dict[str, object] = {
            "membership_id": str(m),
            "workspace_id": str(w.tenant.main),
            "user_id": str(principal),
        }
        request = await propose(
            conn, w.t, w.owner_a, "assignment_grant", payload, role=w.held, base_version=1
        )
        await confirm(conn, w.t, w.owner_b, request)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.role_assignments"
                " (id, tenant_id, workspace_id, membership_id, role_id)"
                " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
            ),
            {"t": w.t, "w": w.tenant.main, "m": m, "r": w.held},
        )

    await _expect_refusal(app, steps, "ck_memberships_dw_principal_roles_fixed")


# ---- RB48-RB50: the legacy columns and the membership's identity ------------


async def test_the_legacy_columns_are_no_way_around_two_people(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.5 (RB48): the copy trigger's writes are judged as their writer's;
    adding through the columns is refused, removing is a narrowing."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        for key in ("approver", "approver_boost"):
            found = await conn.scalar(
                sa.text("SELECT id FROM platform.tenant_roles WHERE tenant_id = :t AND key = :k"),
                {"t": w.t, "k": key},
            )
            if found is None:
                await conn.execute(
                    sa.text("SELECT platform.install_role_template(:t, :k)"), {"t": w.t, "k": key}
                )
        # A key with a template the tenant has no role for yet.
        assert (
            await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.tenant_roles"
                    " WHERE tenant_id = :t AND key = 'director'"
                ),
                {"t": w.t},
            )
            == 0
        )

    def write(sql: str) -> object:
        async def steps(conn: AsyncConnection) -> None:
            await bind(conn, w.t, w.owner_a)
            await conn.execute(
                sa.text(sql),
                {"m": w.holder_membership, "t": w.t, "w": w.tenant.workspaces[1], "u": w.holder},
            )

        return steps

    await _expect_refusal(
        app,
        write(
            "UPDATE platform.memberships SET role_keys = role_keys || '[\"approver\"]'"
            " WHERE id = :m"
        ),
        "rbac_refusals_role_assignments",
        "rbac_two_people",
    )
    await _expect_refusal(
        app,
        write(
            "UPDATE platform.memberships SET permission_set_keys ="
            " permission_set_keys || '[\"approver_boost\"]' WHERE id = :m"
        ),
        "rbac_refusals_role_assignments",
        "rbac_two_people",
    )
    await _expect_refusal(
        app,
        write(
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
            " VALUES (gen_random_uuid(), :t, :w, :u, '[\"member\"]')"
        ),
        "rbac_refusals_role_assignments",
        "rbac_two_people",
    )
    await _expect_refusal(
        app,
        write(
            "UPDATE platform.memberships SET role_keys = role_keys || '[\"director\"]'"
            " WHERE id = :m"
        ),
        "rbac_refusals_tenant_roles",
        "rbac_two_people",
    )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.role_assignments WHERE membership_id = :m",
            m=w.holder_membership,
        )
        == 1
    )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.tenant_roles WHERE tenant_id = :t AND key = 'director'",
            t=w.t,
        )
        == 0
    )

    # The migrator adds through the columns; a person holding the role's keys
    # removes it again through them, a narrowing with an actor.
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.memberships SET role_keys = role_keys || '[\"approver\"]'"
                " WHERE id = :m"
            ),
            {"m": w.holder_membership},
        )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.role_assignments a JOIN platform.tenant_roles r"
            " ON r.id = a.role_id WHERE a.membership_id = :m AND r.key = 'approver'",
            m=w.holder_membership,
        )
        == 1
    )
    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            sa.text(
                "UPDATE platform.memberships SET role_keys = role_keys - 'approver' WHERE id = :m"
            ),
            {"m": w.holder_membership},
        )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.role_assignments a JOIN platform.tenant_roles r"
            " ON r.id = a.role_id WHERE a.membership_id = :m AND r.key = 'approver'",
            m=w.holder_membership,
        )
        == 0
    )


async def test_only_the_migrator_adds_platform_admin_and_the_provisioner_adds_nothing(
    migrator: AsyncEngine,
    app: AsyncEngine,
    provisioner: AsyncEngine,
    db_urls: DatabaseUrls,
    keys: tuple[str, str],
) -> None:
    """R6.2, R6.5 (RB49): `ck_memberships_legacy_role_writer`."""
    w = await plant_world(migrator, keys)
    add_admin = sa.text(
        "UPDATE platform.memberships SET role_keys = role_keys || '[\"platform_admin\"]'"
        " WHERE id = :m"
    )

    async def as_app(conn: AsyncConnection) -> None:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(add_admin, {"m": w.holder_membership})

    await _expect_refusal(app, as_app, "ck_memberships_legacy_role_writer")

    def provisioner_insert(role_keys: str, set_keys: str) -> object:
        async def steps(conn: AsyncConnection) -> None:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships"
                    " (id, tenant_id, workspace_id, user_id, role_keys, permission_set_keys)"
                    " VALUES (gen_random_uuid(), :t, :w, :u, CAST(:r AS jsonb), CAST(:s AS jsonb))"
                ),
                {
                    "t": w.t,
                    "w": w.tenant.workspaces[1],
                    "u": w.holder,
                    "r": role_keys,
                    "s": set_keys,
                },
            )

        return steps

    for role_keys, set_keys in (
        ('["platform_admin"]', "[]"),
        ('["member"]', "[]"),
        ("[]", '["approver_boost"]'),
    ):
        await _expect_refusal(
            provisioner,
            provisioner_insert(role_keys, set_keys),
            "ck_memberships_legacy_role_writer",
        )

    lookup = SqlMembershipLookup(async_sessionmaker(app))
    access = await lookup.find_linked_access(w.holder, w.t, w.tenant.main, frozenset({w.key}))
    assert access is not None and "platform_admin" not in access.roles

    async with migrator.begin() as conn:
        await conn.execute(add_admin, {"m": w.holder_membership})
    # Keeping it is not judged: another column, then the key removed.
    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            sa.text("UPDATE platform.memberships SET department = 'ops' WHERE id = :m"),
            {"m": w.holder_membership},
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.memberships SET role_keys = role_keys - 'platform_admin'"
                " WHERE id = :m"
            ),
            {"m": w.holder_membership},
        )


async def test_grant_platform_admin_adds_to_role_keys_and_keeps_what_is_there(
    migrator: AsyncEngine, db_urls: DatabaseUrls, keys: tuple[str, str]
) -> None:
    """RB49: the script adds `platform_admin` and leaves the person's `member`
    assignment (from the columns) in place."""
    import importlib.util
    from pathlib import Path

    w = await plant_world(migrator, keys)
    email = f"pa-{uuid.uuid4().hex[:8]}@example.com"
    async with migrator.begin() as conn:
        person = await plant_person(conn, w.t, email=email)
        await conn.execute(
            sa.text(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
                " VALUES (gen_random_uuid(), :t, :w, :u, '[\"member\"]')"
            ),
            {"t": w.t, "w": w.tenant.main, "u": person},
        )
        slug = await conn.scalar(
            sa.text("SELECT slug FROM platform.tenants WHERE id = :t"), {"t": w.t}
        )
    script = Path(__file__).resolve().parents[5] / "scripts" / "grant_platform_admin.py"
    spec = importlib.util.spec_from_file_location("grant_platform_admin", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert await module._run(db_urls.migrator, email, slug) == 0
    async with migrator.connect() as conn:
        keys_now = await conn.scalar(
            sa.text("SELECT role_keys FROM platform.memberships WHERE user_id = :u"), {"u": person}
        )
        member_held = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.role_assignments a JOIN platform.memberships m"
                " ON m.id = a.membership_id JOIN platform.tenant_roles r ON r.id = a.role_id"
                " WHERE m.user_id = :u AND r.key = 'member'"
            ),
            {"u": person},
        )
    assert keys_now == ["member", "platform_admin"]
    assert member_held == 1


async def test_a_membership_never_changes_hands(
    migrator: AsyncEngine, app: AsyncEngine, provisioner: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R7.5 (RB50): `ck_memberships_identity_fixed` for everyone but the
    migrator; the owner's assignments stay the owner's."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        b = await plant_tenant(conn)
    for column, value in (
        ("user_id", w.holder),
        ("workspace_id", w.tenant.workspaces[1]),
        ("tenant_id", b.tenant_id),
    ):

        async def steps(conn: AsyncConnection, column: str = column, value: object = value) -> None:
            await bind(conn, w.t, w.owner_b)
            await conn.execute(
                sa.text(
                    f"UPDATE platform.memberships SET {column} = :v"
                    " WHERE tenant_id = :t AND user_id = :u"
                ),
                {"v": value, "t": w.t, "u": w.owner_a},
            )

        await _expect_refusal(app, steps, "ck_memberships_identity_fixed")
    with pytest.raises(DBAPIError) as denied:
        async with provisioner.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.memberships SET user_id = :v WHERE tenant_id = :t"
                    " AND user_id = :u"
                ),
                {"v": w.holder, "t": w.t, "u": w.owner_a},
            )
    assert refused(denied.value)[0] in {"ck_memberships_identity_fixed", None}
    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_b)
        await conn.execute(
            sa.text(
                "UPDATE platform.memberships SET department = 'x', manager_user_id = :b"
                " WHERE tenant_id = :t AND user_id = :u"
            ),
            {"b": w.owner_b, "t": w.t, "u": w.owner_a},
        )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.active_tenant_owners(:t) o WHERE o = :u",
            t=w.t,
            u=w.owner_a,
        )
    ) == 1


# ---- Q1: the provisioner, narrowed --------------------------------------------


async def test_the_provisioner_installs_system_roles_and_assigns_owners_only(
    migrator: AsyncEngine, provisioner: AsyncEngine, keys: tuple[str, str]
) -> None:
    """Q1 (Đạt's delegation, 31/10/2026): each other write of the three role
    tables by `dw_provisioner` is refused `rbac_provisioner_scope`."""
    w = await plant_world(migrator, keys)
    async with migrator.begin() as conn:
        member = await role_id(conn, w.t, "member")
        target = await plant_person(conn, w.t)
        tm = await plant_membership(conn, w.t, w.tenant.main, target)

    cases: dict[str, tuple[sa.TextClause, dict[str, object]]] = {
        "tenant_roles": (
            sa.text(
                "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
                " VALUES (gen_random_uuid(), :t, 'custom', 'c', 'role')"
            ),
            {},
        ),
        "tenant_role_permissions": (
            sa.text(
                "INSERT INTO platform.tenant_role_permissions"
                " (tenant_id, role_id, permission_key, depth) VALUES (:t, :r, :k, 'workspace')"
            ),
            {"r": member, "k": w.other_key},
        ),
        "role_assignments": (
            sa.text(
                "INSERT INTO platform.role_assignments"
                " (id, tenant_id, workspace_id, membership_id, role_id)"
                " VALUES (gen_random_uuid(), :t, :w, :m, :r)"
            ),
            {"w": w.tenant.main, "m": tm, "r": member},
        ),
    }
    for table, (statement, params) in cases.items():

        async def steps(
            conn: AsyncConnection,
            statement: sa.TextClause = statement,
            params: dict[str, object] = params,
        ) -> None:
            await conn.execute(statement, {"t": w.t, **params})

        await _expect_refusal(
            provisioner, steps, f"rbac_refusals_{table}", "rbac_provisioner_scope"
        )

    # What it is for: a new company's system roles, and an owner.
    async with provisioner.begin() as conn:
        t = uuid.uuid4()
        ws = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status) VALUES (:t, :s, :s, 'setup')"
            ),
            {"t": t, "s": f"q1-{t.hex[:8]}"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'main', 'main')"
            ),
            {"w": ws, "t": t},
        )
        await conn.execute(sa.text("SELECT platform.install_system_roles(:t)"), {"t": t})


# ---- version, catalogue, one owner of the owner's grants ----------------------


async def test_a_roles_version_moves_with_it_and_its_privileges(
    migrator: AsyncEngine, app: AsyncEngine, keys: tuple[str, str]
) -> None:
    """R8.5, R8.7: the database numbers every change, a no-op none."""
    w = await plant_world(migrator, keys)

    async def version() -> int:
        return await _count(
            migrator, "SELECT version FROM platform.tenant_roles WHERE id = :r", r=w.held
        )

    start = await version()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET name = name WHERE id = :r"), {"r": w.held}
        )
    assert await version() == start
    async with app.begin() as conn:
        await bind(conn, w.t, w.owner_a)
        await conn.execute(
            sa.text("DELETE FROM platform.tenant_role_permissions WHERE role_id = :r"),
            {"r": w.held},
        )
    assert await version() == start + 1
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenant_roles SET description = 'd' WHERE id = :r"),
            {"r": w.held},
        )
    assert await version() == start + 2


async def test_the_role_triggers_fire_in_the_order_the_lock_rule_needs(
    migrator: AsyncEngine,
) -> None:
    """R7.8 (RB43), step 2: the version trigger on the privileges sorts before
    `trg_z_bump_access_version` (role row before version row); the DW guard
    after `rbac_refusals_role_assignments`; one `rbac_refusals_*` per table."""
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'platform' AND NOT t.tgisinternal"
            )
        )
        by_table: dict[str, list[str]] = {}
        for row in rows:
            by_table.setdefault(row.relname, []).append(row.tgname)
    for table in ("tenant_roles", "tenant_role_permissions", "role_assignments"):
        assert f"rbac_refusals_{table}" in by_table[table]
    perms = sorted(by_table["tenant_role_permissions"])
    assert perms.index("trg_tenant_role_permissions_role_version") < perms.index(
        "trg_z_bump_access_version"
    )
    assigned = sorted(by_table["role_assignments"])
    assert assigned.index("rbac_refusals_role_assignments") < assigned.index(
        "trg_role_assignments_dw_principal_roles_fixed"
    )
    assert "dw_principal_roles_fixed" not in by_table["memberships"]


async def test_role_privileges_of_the_owner_match_its_effective_grants(
    migrator: AsyncEngine, keys: tuple[str, str]
) -> None:
    """`platform.role_privileges` repeats `tenant_owner`'s computed grants for
    the hold rule; this keeps the two copies equal (failure-modes #2)."""
    w = await plant_world(migrator, keys)
    async with migrator.connect() as conn:
        owner = await role_id(conn, w.t, "tenant_owner")
        rows = await conn.execute(
            sa.text("SELECT permission_key, depth FROM platform.role_privileges(:t, :r)"),
            {"t": w.t, "r": owner},
        )
        listed = {(r.permission_key, r.depth) for r in rows}
        held = await grants_of(conn, w.t, w.owner_a)
    assert listed and listed <= held
    assert {k for k, _ in held} - {k for k, _ in listed} <= {w.key}
