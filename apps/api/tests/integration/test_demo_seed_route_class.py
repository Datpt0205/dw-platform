"""The digital-worker demo's tenant runs `cross_border_full`; every other tenant
is born `vn_only` (compliance-pdpl ticket 03).

Every shipped model profile is foreign, so the demo seed moves its own synthetic
tenant, as the migrator, before its first run pins a class. The tenant the
operator creates through `POST /platform/tenants` is untouched by that: the
default holds, and the seed's write reaches the one tenant it names.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls, provisioner_url
from scripts.demo_dw_api import DemoError
from scripts.demo_dw_seed import DEMO_ROUTE_CLASS, allow_cross_border
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier

pytestmark = pytest.mark.integration

# Minted per run: a dev-issuer secret in the source is one a scanner rightly flags.
SECRET = secrets.token_hex(24)


@dataclass
class Operator:
    client: httpx.AsyncClient
    migrator: AsyncEngine
    migrator_url: str
    subject: str

    async def create_tenant(self) -> str:
        slug = f"rc-{uuid.uuid4().hex[:10]}"
        owners = [f"{uuid.uuid4().hex[:8]}@khach.vn", f"{uuid.uuid4().hex[:8]}@doitac.vn"]
        created = await self.client.post(
            "/api/v1/platform/tenants",
            headers={"Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(self.subject)}"},
            json={"slug": slug, "name": slug, "plan_id": "professional", "owners": owners},
        )
        assert created.status_code == 201, created.text
        return str(created.json()["tenant_id"])

    async def route_class(self, tenant_id: str) -> str | None:
        async with self.migrator.connect() as conn:
            found = await conn.scalar(
                sa.text("SELECT data_route_class FROM platform.tenants WHERE id = :t"),
                {"t": uuid.UUID(tenant_id)},
            )
        return None if found is None else str(found)


@pytest.fixture
async def operator(api_db: DatabaseUrls) -> AsyncIterator[Operator]:
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
    user = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'Op')"),
            {"u": user, "s": f"op-{user}"},
        )
        await conn.execute(
            sa.text("INSERT INTO platform.platform_operators (user_id) VALUES (:u)"), {"u": user}
        )
    app = create_app(container)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield Operator(client, migrator, api_db.migrator, f"op-{user}")
    finally:
        await container.engine.dispose()
        if container.provisioner_engine is not None:
            await container.provisioner_engine.dispose()
        await migrator.dispose()


async def test_a_tenant_the_operator_creates_is_born_vn_only(operator: Operator) -> None:
    tenant = await operator.create_tenant()
    assert await operator.route_class(tenant) == "vn_only"


async def test_the_demo_seed_moves_its_own_tenant_and_no_other(operator: Operator) -> None:
    demo, other = await operator.create_tenant(), await operator.create_tenant()
    await allow_cross_border(operator.migrator_url, demo)
    assert DEMO_ROUTE_CLASS == "cross_border_full"
    assert await operator.route_class(demo) == "cross_border_full"
    assert await operator.route_class(other) == "vn_only"


async def test_the_seed_stops_on_a_tenant_it_cannot_find(operator: Operator) -> None:
    with pytest.raises(DemoError, match="not found"):
        await allow_cross_border(operator.migrator_url, str(uuid.uuid4()))
