"""The `object` kind in the running app (custom-objects ticket 02).

The app is built with no `studio_kinds=`, so it registers what
`build_studio` registers by default, `platform_kinds(...)`: the composition
root's registry against the rows of `studio.artifact_kinds`, and R1.3 (CO3)
over HTTP: `studio.objects.manage` is the kind's read, write and submit key,
so a member without it is refused a create (403) and cannot even find an
object to save a draft of (404, tenant-config R2.11, TC24). The submit
command is ticket 06's.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.testing.rbac import (
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_studio.testing.objects import object_document, object_field, plant_manager
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-objects-secret-0123456789abcdef"
BASE = "/api/v1/studio/artifacts"


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    people: dict[str, Person]

    async def call(self, who: str, method: str, url: str, **kw: Any) -> httpx.Response:
        person = self.people[who]
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
            "X-Tenant-Id": str(person.tenant_id),
            "X-Workspace-Id": str(person.workspace_id),
            **kw.pop("headers", {}),
        }
        return await self.client.request(method, url, headers=headers, **kw)

    async def count(self, statement: str, **values: Any) -> int:
        async with self.migrator.connect() as conn:
            return int((await conn.execute(sa.text(statement), values)).scalar_one())


def name() -> str:
    return f"o_{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        manager = await plant_manager(conn, tenant)
        user = await plant_person(conn, tenant.tenant_id)
        membership = await plant_membership(conn, tenant.tenant_id, tenant.main, user)
        role = await plant_role(conn, tenant.tenant_id, f"plain_{user.hex[:12]}", {})
        await assign(conn, tenant.tenant_id, tenant.main, membership, role)
    member = Person(user, tenant.tenant_id, tenant.main)
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    app = create_app(container)
    assert container.engine is not None
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                yield Api(client, container, migrator, {"manager": manager, "member": member})
    finally:
        await container.engine.dispose()
        await migrator.dispose()


async def test_the_running_registry_is_the_kind_table(api: Api) -> None:
    """The registry the composition root built, against `studio.artifact_kinds`."""
    assert api.container.studio is not None
    async with api.migrator.connect() as conn:
        rows = {
            r.kind for r in await conn.execute(sa.text("SELECT kind FROM studio.artifact_kinds"))
        }
    assert api.container.studio.kinds.kinds == rows == {"object", "workflow"}


async def test_r1_3_only_a_holder_of_the_object_key_creates_or_finds_an_object(api: Api) -> None:
    """R1.3 (CO3): 403 on create and 404 on a draft save for the member
    without `studio.objects.manage`, nothing written; 201 for the manager."""
    document = object_document(object_field("ghi_chu"))
    versions = "SELECT count(*) FROM studio.artifact_versions"
    before = await api.count(versions)

    refused = await api.call(
        "member", "POST", BASE, json={"kind": "object", "api_name": name(), "document": document}
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "permission_denied")
    assert await api.count(versions) == before

    created = await api.call(
        "manager", "POST", BASE, json={"kind": "object", "api_name": name(), "document": document}
    )
    assert created.status_code == 201, created.text
    artifact_id = created.json()["id"]
    after_create = await api.count(versions)

    hidden = await api.call(
        "member",
        "PUT",
        f"{BASE}/{artifact_id}/draft",
        json={"document": object_document(object_field("khac"))},
        headers={"If-Match": '"1"'},
    )
    assert hidden.status_code == 404, hidden.text
    assert await api.count(versions) == after_create
    stored = await api.count(
        "SELECT count(*) FROM studio.artifact_versions"
        " WHERE artifact_id = :a AND document -> 'fields' -> 0 ->> 'api_name' = 'ghi_chu'",
        a=uuid.UUID(artifact_id),
    )
    assert stored == 1
