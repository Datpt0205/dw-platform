"""`POST /api/v1/runs/{run_id}/resume-check` over HTTP, against Postgres
(workflow-engine ticket 05: R6.39, R6.22, R6.23; WE53).

The real app and container. What the check decides on a blocked run (the
checks, the deadline, the switches, the requeue and its audit) is
`dw_studio/tests/integration/test_run_waits_db.py`'s, over the same service;
here the route itself: the `Idempotency-Key` it requires, and a run the
caller cannot see answered 404 before any key row.
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

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.testing.workflows import plant_holder
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "resume-check-secret-0123456789abcdef"
KEYS = ("runs.read", "studio.workflows.resume_check")


@dataclass
class Api:
    client: httpx.AsyncClient
    migrator: AsyncEngine
    tenant: PlantedTenant
    other: PlantedTenant
    people: dict[str, Person]

    async def check(self, who: str, run_id: uuid.UUID, key: str | None) -> httpx.Response:
        person = self.people[who]
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
            "X-Tenant-Id": str(person.tenant_id),
            "X-Workspace-Id": str(person.workspace_id),
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.post(f"/api/v1/runs/{run_id}/resume-check", headers=headers)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        other = await plant_tenant(conn)
        people = {
            "checker": await plant_holder(conn, tenant, KEYS),
            "reader": await plant_holder(conn, tenant, ("runs.read",)),
            "outsider": await plant_holder(conn, other, KEYS),
        }
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    assert container.engine is not None and container.studio is not None
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                yield Api(client, migrator, tenant, other, people)
    finally:
        await container.engine.dispose()
        await migrator.dispose()


def reason(response: httpx.Response) -> Any:
    return (response.json().get("details") or {}).get("reason_code")


async def test_r6_39_the_check_requires_an_idempotency_key(api: Api) -> None:
    refused = await api.check("checker", uuid.uuid4(), None)
    assert refused.status_code == 422, refused.text
    assert reason(refused) == "idempotency_key_required"


async def test_r6_22_a_run_the_caller_cannot_see_is_404_for_every_caller(api: Api) -> None:
    """Another company's run, out-of-reach runs and the 403 without the key
    are the service's, over real runs, in `test_run_waits_db.py`; here the
    route answers before any key row is written."""
    for who in ("checker", "reader", "outsider"):
        missing = await api.check(who, uuid.uuid4(), uuid.uuid4().hex)
        assert missing.status_code == 404, missing.text
    async with api.migrator.connect() as conn:
        keys = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.idempotency_keys WHERE request_path LIKE :t"),
            {"t": "%/resume-check"},
        )
    assert keys == 0
