"""Only an active company member passes the AccessContext door, at every route.

org-and-principals R4.3 (OP5), through the real app on a migrated Postgres with
no access cache (no `redis_url`, so every request builds its context): a person
with memberships in two workspaces of one company reaches `GET /api/v1/me` (no
scope check) and `GET /api/v1/directory/members` (`directory.read`) in both,
and once their company row is `suspended`, or gone, every one of those answers
403 and changes nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.testing.members import TENANT_MEMBER_SQL, tenant_member_params

pytestmark = pytest.mark.integration

SECRET = "member-door-secret-0123456789abcdef0123"
ROUTES = ("/api/v1/me", "/api/v1/directory/members")


@dataclass(frozen=True)
class World:
    tenant: uuid.UUID
    workspaces: tuple[uuid.UUID, uuid.UUID]
    user: uuid.UUID


async def _seed(migrator: AsyncEngine) -> World:
    world = World(uuid.uuid4(), (uuid.uuid4(), uuid.uuid4()), uuid.uuid4())
    t, u = world.tenant, world.user
    role = f"door_{t.hex[:10]}"
    statements: list[tuple[str, dict[str, object]]] = [
        (
            "INSERT INTO platform.roles (key, name, scopes)"
            " VALUES (:k, :k, '[\"directory.read\"]'::jsonb)",
            {"k": role},
        ),
        (
            "INSERT INTO platform.tenants (id, slug, name, status)"
            " VALUES (:t, :slug, :slug, 'active')",
            {"t": t, "slug": f"door-{t.hex[:12]}"},
        ),
        (
            "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
            " VALUES (:id, :t, 'professional')",
            {"id": uuid.uuid4(), "t": t},
        ),
        (
            "INSERT INTO platform.users (id, subject, email, display_name)"
            " VALUES (:u, :sub, :email, 'Người dùng')",
            {"u": u, "sub": f"door-{u}", "email": f"{u.hex[:12]}@door.test"},
        ),
        (TENANT_MEMBER_SQL, tenant_member_params(t, u)),
    ]
    for n, ws in enumerate(world.workspaces):
        statements += [
            (
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, :slug, :slug)",
                {"w": ws, "t": t, "slug": f"door{n}"},
            ),
            (
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                " role_keys) VALUES (:id, :t, :w, :u, CAST(:r AS jsonb))",
                {"id": uuid.uuid4(), "t": t, "w": ws, "u": u, "r": f'["{role}"]'},
            ),
        ]
    async with migrator.begin() as conn:
        for statement, values in statements:
            await conn.execute(sa.text(statement), values)
    return world


@dataclass
class Door:
    world: World
    client: httpx.AsyncClient
    migrator: AsyncEngine

    async def answers(self) -> list[int]:
        token = DevTokenVerifier(SECRET).issue(f"door-{self.world.user}")
        codes = []
        for ws in self.world.workspaces:
            for route in ROUTES:
                response = await self.client.get(
                    route,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Tenant-Id": str(self.world.tenant),
                        "X-Workspace-Id": str(ws),
                    },
                )
                codes.append(response.status_code)
        return codes

    async def execute(self, statement: str) -> None:
        async with self.migrator.begin() as conn:
            await conn.execute(sa.text(statement), {"t": self.world.tenant, "u": self.world.user})

    async def memberships(self) -> int:
        async with self.migrator.connect() as conn:
            return int(
                await conn.scalar(
                    sa.text("SELECT count(*) FROM platform.memberships WHERE user_id = :u"),
                    {"u": self.world.user},
                )
                or 0
            )


@pytest.fixture
async def door(api_db: DatabaseUrls) -> AsyncIterator[Door]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    world = await _seed(migrator)
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    assert container.engine is not None
    app = create_app(container)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield Door(world, client, migrator)
    finally:
        await container.engine.dispose()
        await migrator.dispose()


_WHERE = " WHERE tenant_id = :t AND user_id = :u"


async def test_an_active_member_passes_in_both_workspaces(door: Door) -> None:
    assert await door.answers() == [200, 200, 200, 200]


async def test_a_suspended_member_is_refused_at_every_route_in_every_workspace(
    door: Door,
) -> None:
    await door.execute("UPDATE platform.tenant_members SET status = 'suspended'" + _WHERE)
    assert await door.answers() == [403, 403, 403, 403]
    assert await door.memberships() == 2, "refusing changes nothing"


async def test_an_invited_member_is_refused_too(door: Door) -> None:
    await door.execute("UPDATE platform.tenant_members SET status = 'invited'" + _WHERE)
    assert await door.answers() == [403, 403, 403, 403]


async def test_a_person_without_a_company_row_is_refused(door: Door) -> None:
    await door.execute("DELETE FROM platform.tenant_members" + _WHERE)
    assert await door.answers() == [403, 403, 403, 403]
