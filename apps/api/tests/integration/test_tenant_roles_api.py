"""Roles as tenant data, through the real app on a migrated Postgres.

tenant-rbac ticket 02: `GET /api/v1/me` answers from `platform.effective_grants`
(R2.2-R2.4, R2.7); a change made outside the API reaches the next request
although the context is cached (R4.1); a tenant is created with two owners and
stays `setup`, closed like `locked`, until the second one signs in (R3.1,
R3.8-R3.11, R3.13, R3.14).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls, provisioner_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.caching_lookup import CachingMembershipLookup
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.application.identity import DbAccessContextFactory
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
    register_key,
    role_id,
    unregister_key,
)

pytestmark = pytest.mark.integration

SECRET = "tenant-rbac-secret-0123456789abcdef0123"


class _MemoryCache:
    """A cache that keeps what it is given, as Valkey does."""

    def __init__(self) -> None:
        self.entries: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.entries.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self.entries[key] = value


@dataclass
class Api:
    client: httpx.AsyncClient
    migrator: AsyncEngine
    container: ApiContainer
    cache: _MemoryCache = field(default_factory=_MemoryCache)

    async def as_person(
        self, subject: str, tenant: uuid.UUID, workspace: uuid.UUID, path: str = "/api/v1/me"
    ) -> httpx.Response:
        token = DevTokenVerifier(SECRET).issue(subject)
        return await self.client.get(
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-Id": str(tenant),
                "X-Workspace-Id": str(workspace),
            },
        )

    async def as_operator(self, method: str, path: str, **kw: object) -> httpx.Response:
        token = DevTokenVerifier(SECRET).issue(self.operator_subject)
        return await self.client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {token}"},
            **kw,  # type: ignore[arg-type]
        )

    operator_subject: str = ""

    async def scalar(self, statement: str, **values: object) -> object:
        async with self.migrator.connect() as conn:
            return await conn.scalar(sa.text(statement), values)


@pytest.fixture
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            provisioner_database_url=provisioner_url(api_db.migrator),
            dev_secret=SECRET,
        )
    )
    assert container.engine is not None
    cache = _MemoryCache()
    container.access_context_factory = DbAccessContextFactory(
        CachingMembershipLookup(
            SqlMembershipLookup(async_sessionmaker(container.engine, expire_on_commit=False)),
            cache,
        )
    )
    operator = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'Op')"),
            {"u": operator, "s": f"op-{operator}"},
        )
        await conn.execute(
            sa.text("INSERT INTO platform.platform_operators (user_id) VALUES (:u)"),
            {"u": operator},
        )
    app = create_app(container)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield Api(client, migrator, container, cache, operator_subject=f"op-{operator}")
    finally:
        await container.engine.dispose()
        if container.provisioner_engine is not None:
            await container.provisioner_engine.dispose()
        await migrator.dispose()


async def _person_in(
    api: Api, t: PlantedTenant, *workspaces: uuid.UUID
) -> tuple[str, uuid.UUID, list[uuid.UUID]]:
    async with api.migrator.begin() as conn:
        person = await plant_person(conn, t.tenant_id)
        await conn.execute(
            sa.text("UPDATE platform.users SET subject = :s WHERE id = :u"),
            {"s": f"rbac-api-{person}", "u": person},
        )
        memberships = [await plant_membership(conn, t.tenant_id, ws, person) for ws in workspaces]
    return f"rbac-api-{person}", person, memberships


# ---- GET /api/v1/me (R2.2-R2.4, R2.7) -----------------------------------------


async def test_me_answers_from_the_effective_grants_across_workspaces(api: Api) -> None:
    """R2.2 (RB5), R2.3, R2.4 (RB6): a key held only through a permission set
    is there; a tenant key from A holds in B; a workspace key from A does not."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn, workspaces=2)
    subject, _, (at_a, _) = await _person_in(api, t, *t.workspaces)
    async with api.migrator.begin() as conn:
        boost = await plant_role(
            conn, t.tenant_id, "p_boost", {"approvals.decide": "workspace"}, kind="permission_set"
        )
        reader = await plant_role(
            conn, t.tenant_id, "r_reader", {"platform.members.read": "tenant"}
        )
        await assign(conn, t.tenant_id, t.workspaces[0], at_a, boost)
        await assign(conn, t.tenant_id, t.workspaces[0], at_a, reader)

    in_a = (await api.as_person(subject, t.tenant_id, t.workspaces[0])).json()
    in_b = (await api.as_person(subject, t.tenant_id, t.workspaces[1])).json()

    assert {"approvals.decide", "platform.members.read"} <= set(in_a["scopes"])
    assert "platform.members.read" in in_b["scopes"]
    assert "approvals.decide" not in in_b["scopes"]
    assert {(g["key"], g["depth"], g["anchor_workspace_id"]) for g in in_b["grants"]} == {
        ("approvals.decide", "workspace", str(t.workspaces[0])),
        ("platform.members.read", "tenant", str(t.workspaces[0])),
    }
    assert in_a["platform_bypass"] is False
    assert isinstance(in_a["access_version"], int)


async def test_an_owner_holds_a_key_registered_after_the_assignment(api: Api) -> None:
    """R2.7 (RB34), through `/me`: at tenant depth, with no privilege row."""
    key = f"test.k{uuid.uuid4().hex[:8]}.later"
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
    subject, _, (membership,) = await _person_in(api, t, t.main)
    try:
        async with api.migrator.begin() as conn:
            await assign(
                conn,
                t.tenant_id,
                t.main,
                membership,
                await role_id(conn, t.tenant_id, "tenant_owner"),
            )
            await register_key(conn, key)
        me = (await api.as_person(subject, t.tenant_id, t.main)).json()
    finally:
        async with api.migrator.begin() as conn:
            await unregister_key(conn, key)
    assert key in me["scopes"]
    assert {"key": key, "depth": "tenant", "anchor_workspace_id": str(t.main)} in me["grants"]
    assert "platform.admin" not in me["scopes"]


# ---- the first request after a commit (R4.1) ---------------------------------


async def test_an_assignment_revoked_in_raw_sql_is_refused_at_the_next_request(api: Api) -> None:
    """R4.1 (RB12): the context is cached; nothing evicts it; the version moved."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
    subject, _, (membership,) = await _person_in(api, t, t.main)
    async with api.migrator.begin() as conn:
        role = await plant_role(conn, t.tenant_id, "r_dir", {"directory.read": "workspace"})
        assignment = await assign(conn, t.tenant_id, t.main, membership, role)
    path = "/api/v1/directory/members"
    assert (await api.as_person(subject, t.tenant_id, t.main, path)).status_code == 200
    assert api.cache.entries, "the premise: the context is cached"

    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.role_assignments WHERE id = :a"), {"a": assignment}
        )
    started = time.monotonic()
    refused = await api.as_person(subject, t.tenant_id, t.main, path)
    assert refused.status_code == 403
    assert time.monotonic() - started < 1


async def test_a_lock_through_the_route_refuses_the_next_request(api: Api) -> None:
    """foundations-hardening FH8 with no `delete_pattern` left at the route."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
    subject, _, _ = await _person_in(api, t, t.main)
    assert (await api.as_person(subject, t.tenant_id, t.main)).status_code == 200
    locked = await api.as_operator("POST", f"/api/v1/platform/tenants/{t.tenant_id}/lock")
    assert locked.status_code == 204, locked.text
    assert (await api.as_person(subject, t.tenant_id, t.main)).status_code == 403


# ---- two owners, `setup` (R3.1, R3.8-R3.11, R3.13, R3.14) ---------------------


def _new_tenant(owners: list[str]) -> dict[str, object]:
    slug = f"two-{uuid.uuid4().hex[:10]}"
    return {"slug": slug, "name": slug, "plan_id": "professional", "owners": owners}


async def _tenants_with(api: Api, slug: str) -> int:
    return int(
        await api.scalar("SELECT count(*) FROM platform.tenants WHERE slug = :s", s=slug) or 0
    )


async def test_a_tenant_is_created_in_setup_with_two_invited_owners(api: Api) -> None:
    """R3.1 (RB37), and the partner from outside the customer as second owner."""
    first, partner = f"{uuid.uuid4().hex[:8]}@khach.vn", f"{uuid.uuid4().hex[:8]}@doitac.vn"
    body = _new_tenant([first, partner.upper()])
    created = await api.as_operator("POST", "/api/v1/platform/tenants", json=body)
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["status"] == "setup"
    tenant = view["tenant_id"]
    async with api.migrator.connect() as conn:
        roles = dict(
            (
                await conn.execute(
                    sa.text(
                        "SELECT key, is_system FROM platform.tenant_roles WHERE tenant_id = :t"
                    ),
                    {"t": tenant},
                )
            ).all()
        )
        owners = (
            await conn.execute(
                sa.text(
                    "SELECT u.email, tm.status, w.slug FROM platform.role_assignments a"
                    " JOIN platform.tenant_roles r ON r.id = a.role_id AND r.key = 'tenant_owner'"
                    " JOIN platform.memberships m ON m.id = a.membership_id"
                    " JOIN platform.workspaces w ON w.id = m.workspace_id"
                    " JOIN platform.users u ON u.id = m.user_id"
                    " JOIN platform.tenant_members tm"
                    "   ON tm.tenant_id = m.tenant_id AND tm.user_id = m.user_id"
                    " WHERE a.tenant_id = :t ORDER BY u.email"
                ),
                {"t": tenant},
            )
        ).all()
    assert roles == {"tenant_owner": True, "member": True}
    assert sorted((o.email, o.status, o.slug) for o in owners) == sorted(
        [(first, "invited", "main"), (partner, "invited", "main")]
    )
    listed = await api.as_operator("GET", "/api/v1/platform/tenants")
    mine = next(t for t in listed.json() if t["id"] == tenant)
    assert (mine["status"], mine["owner_coverage_low_since"]) == ("setup", None)


@pytest.mark.parametrize(
    "owners",
    [["one@khach.vn"], ["a@khach.vn", "b@khach.vn", "c@khach.vn"], ["Ai@khach.vn", "ai@KHACH.vn"]],
)
async def test_anything_but_two_different_owners_writes_nothing(
    api: Api, owners: list[str]
) -> None:
    """R3.9 (RB37)."""
    body = _new_tenant(owners)
    refused = await api.as_operator("POST", "/api/v1/platform/tenants", json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "validation_failed"
    assert await _tenants_with(api, str(body["slug"])) == 0


async def _listed(api: Api, table: str) -> str:
    """A person on `platform.<table>`, by email, who holds nothing anywhere."""
    user = uuid.uuid4()
    email = f"{user.hex[:10]}@ops.vn"
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, email, display_name)"
                " VALUES (:u, :s, :e, 'Ops')"
            ),
            {"u": user, "s": f"ops-{user}", "e": email},
        )
        await conn.execute(
            sa.text(f"INSERT INTO platform.{table} (user_id) VALUES (:u)"),
            {"u": user},
        )
    return email


@pytest.mark.parametrize(
    ("table", "reason"),
    [
        ("platform_operators", "operator_not_assignable"),
        ("support_staff", "support_staff_not_member"),
    ],
)
async def test_an_operator_or_support_staff_owner_is_refused_and_nothing_is_written(
    api: Api, table: str, reason: str
) -> None:
    """R3.11 (RB39): the support staff member meets the membership door first."""
    body = _new_tenant([await _listed(api, table), f"{uuid.uuid4().hex[:8]}@khach.vn"])
    refused = await api.as_operator("POST", "/api/v1/platform/tenants", json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["details"]["reason_code"] == reason
    assert await _tenants_with(api, str(body["slug"])) == 0


async def test_an_owner_cannot_be_listed_as_operator_or_support_staff(api: Api) -> None:
    """R3.11 (RB39): 409 `operator_not_assignable`, not 500."""
    owner = f"{uuid.uuid4().hex[:8]}@khach.vn"
    created = await api.as_operator(
        "POST", "/api/v1/platform/tenants", json=_new_tenant([owner, f"x{owner}"])
    )
    assert created.status_code == 201, created.text
    for path in ("/api/v1/platform/operators", "/api/v1/platform/support-staff"):
        refused = await api.as_operator("POST", path, json={"email": owner})
        assert refused.status_code == 409, (path, refused.text)
        assert refused.json()["details"]["reason_code"] == "operator_not_assignable"


async def test_the_org_admins_route_assigns_the_owner_role_not_org_admin(api: Api) -> None:
    """R3.8, and the same refusal for an operator there."""
    async with api.migrator.begin() as conn:
        t = await plant_tenant(conn)
    email = f"{uuid.uuid4().hex[:8]}@khach.vn"
    async with api.migrator.begin() as conn:
        person = await plant_person(conn, t.tenant_id, email=email)
    assigned = await api.as_operator(
        "POST", f"/api/v1/platform/tenants/{t.tenant_id}/org-admins", json={"email": email}
    )
    assert assigned.status_code == 201, assigned.text
    role_keys = await api.scalar(
        "SELECT role_keys FROM platform.memberships WHERE tenant_id = :t AND user_id = :u",
        t=t.tenant_id,
        u=person,
    )
    owners = await api.scalar(
        "SELECT count(*) FROM platform.role_assignments a JOIN platform.tenant_roles r"
        " ON r.id = a.role_id WHERE a.tenant_id = :t AND r.key = 'tenant_owner'",
        t=t.tenant_id,
    )
    assert role_keys == [] and owners == 1
    operator = await _listed(api, "platform_operators")
    refused = await api.as_operator(
        "POST", f"/api/v1/platform/tenants/{t.tenant_id}/org-admins", json={"email": operator}
    )
    assert refused.status_code == 409
    assert refused.json()["details"]["reason_code"] == "operator_not_assignable"


async def test_a_setup_tenant_is_closed_until_its_second_owner_signs_in(api: Api) -> None:
    """R3.14, R3.10 (RB41, RB38): the first owner's sign-in activates them and
    lists the workspace, every route then refuses as for `locked`; the
    operators still list the tenant; the second sign-in opens it."""
    first, second = (f"{uuid.uuid4().hex[:8]}@khach.vn" for _ in range(2))
    created = await api.as_operator(
        "POST", "/api/v1/platform/tenants", json=_new_tenant([first, second])
    )
    tenant, workspace = created.json()["tenant_id"], created.json()["workspace_id"]

    async def sign_in(email: str) -> httpx.Response:
        token = DevTokenVerifier(SECRET).issue(f"dev-{email}", email=email)
        return await api.client.get(
            "/api/v1/auth/bootstrap", headers={"Authorization": f"Bearer {token}"}
        )

    async def door(email: str, method: str, path: str, **kw: object) -> int:
        token = DevTokenVerifier(SECRET).issue(f"dev-{email}", email=email)
        response = await api.client.request(
            method,
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-Id": tenant,
                "X-Workspace-Id": workspace,
            },
            **kw,  # type: ignore[arg-type]
        )
        return response.status_code

    booted = await sign_in(first)
    assert booted.status_code == 200, booted.text
    assert [m["workspace_id"] for m in booted.json()["memberships"]] == [workspace]
    assert (
        await api.scalar("SELECT status FROM platform.tenants WHERE id = :t", t=tenant) == "setup"
    )
    assert await door(first, "GET", "/api/v1/me") == 403
    invitation = {
        "display_name": "Người mới",
        "email": f"{uuid.uuid4().hex[:8]}@khach.vn",
        "memberships": [{"workspace_id": workspace, "role_keys": ["member"]}],
    }
    assert await door(first, "POST", "/api/v1/admin/invitations", json=invitation) == 403
    listed = await api.as_operator("GET", "/api/v1/platform/tenants")
    assert listed.status_code == 200
    assert next(t for t in listed.json() if t["id"] == tenant)["status"] == "setup"

    assert (await sign_in(second)).status_code == 200
    assert (
        await api.scalar("SELECT status FROM platform.tenants WHERE id = :t", t=tenant) == "active"
    )
    assert await door(first, "GET", "/api/v1/me") == 200
