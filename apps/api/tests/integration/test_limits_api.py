"""The limits routes through the real app on a migrated Postgres
(usage-and-limits ticket 03: R4.5, R4.6, R4.8, R4.9, R4.14, R4.15; UL9, UL10,
UL15, UL19, UL20).

A person is planted with a role holding `platform.limits.manage` and
`platform.usage.read` at company depth; another holds nothing. Every answer is
read as the problem+json the web gets.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls, provisioner_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)

pytestmark = pytest.mark.integration

# Minted per run: a dev-issuer secret in the source is one a scanner rightly flags.
SECRET = secrets.token_hex(24)


@dataclass
class Caller:
    subject: str
    tenant: PlantedTenant


@dataclass
class Api:
    client: httpx.AsyncClient
    migrator: AsyncEngine

    async def call(
        self,
        caller: Caller,
        method: str,
        path: str,
        *,
        json: Any = None,
        if_match: str | None = None,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(caller.subject)}",
            "X-Tenant-Id": str(caller.tenant.tenant_id),
            "X-Workspace-Id": str(caller.tenant.main),
        }
        if if_match is not None:
            headers["If-Match"] = if_match
        return await self.client.request(method, f"/api/v1{path}", headers=headers, json=json)

    async def person(self, tenant: PlantedTenant, *, manager: bool) -> Caller:
        async with self.migrator.begin() as conn:
            user = await plant_person(conn, tenant.tenant_id)
            subject = f"limits-api-{user}"
            await conn.execute(
                sa.text("UPDATE platform.users SET subject = :s WHERE id = :u"),
                {"s": subject, "u": user},
            )
            membership = await plant_membership(conn, tenant.tenant_id, tenant.main, user)
            if manager:
                role = await plant_role(
                    conn,
                    tenant.tenant_id,
                    f"r_limits_{user.hex[:8]}",
                    {"platform.limits.manage": "tenant", "platform.usage.read": "tenant"},
                )
                await assign(conn, tenant.tenant_id, tenant.main, membership, role)
        return Caller(subject, tenant)

    async def policies(self, tenant: PlantedTenant) -> list[tuple[Any, ...]]:
        async with self.migrator.connect() as conn:
            rows = await conn.execute(
                sa.text(
                    "SELECT scope_type, metric, window_kind, limit_value, version"
                    " FROM platform.limit_policies WHERE tenant_id = :t ORDER BY metric"
                ),
                {"t": tenant.tenant_id},
            )
            return [tuple(row) for row in rows]


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
    app = create_app(container)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield Api(client, migrator)
    finally:
        await container.engine.dispose()
        if container.provisioner_engine is not None:
            await container.provisioner_engine.dispose()
        await migrator.dispose()


async def _company(api: Api, *, workspaces: int = 1) -> PlantedTenant:
    async with api.migrator.begin() as conn:
        return await plant_tenant(conn, workspaces=workspaces)


def _tenant_path(tenant: PlantedTenant, pair: str = "cost_usd/month") -> str:
    return f"/limits/tenant/{tenant.tenant_id}/{pair}"


def _reason(response: httpx.Response) -> object:
    return response.json().get("details", {}).get("reason_code")


async def test_a_lowered_limit_applies_at_once_and_a_raise_or_removal_is_refused(
    api: Api,
) -> None:
    """R4.8, R4.9 (UL15), R4.15 (UL20) over HTTP."""
    company = await _company(api)
    owner = await api.person(company, manager=True)
    path = _tenant_path(company)

    created = await api.call(owner, "PUT", path, json={"limit_value": "50", "kind": "hard"})
    assert created.status_code == 200, created.text
    assert created.headers["ETag"] == '"1"'
    lowered = await api.call(
        owner, "PUT", path, json={"limit_value": "10", "kind": "hard"}, if_match='"1"'
    )
    assert (lowered.status_code, lowered.json()["version"]) == (200, 2)

    missing = await api.call(owner, "PUT", path, json={"limit_value": "5", "kind": "hard"})
    assert missing.status_code == 428
    stale = await api.call(
        owner, "PUT", path, json={"limit_value": "5", "kind": "hard"}, if_match='"1"'
    )
    assert stale.status_code == 412
    raised = await api.call(
        owner, "PUT", path, json={"limit_value": "50", "kind": "hard"}, if_match='"2"'
    )
    assert (raised.status_code, _reason(raised)) == (409, "second_person_required")
    removed = await api.call(owner, "DELETE", path, if_match='"2"')
    assert (removed.status_code, _reason(removed)) == (409, "second_person_required")
    assert await api.policies(company) == [("tenant", "cost_usd", "month", pytest.approx(10), 2)]

    listed = await api.call(owner, "GET", "/limits")
    assert listed.status_code == 200
    (line,) = [
        row
        for row in listed.json()
        if (row["scope_type"], row["metric"], row["window_kind"]) == ("tenant", "cost_usd", "month")
    ]
    assert (line["limit_value"], line["effective_limit"], line["version"]) == (
        "10.00000000",
        "10.00000000",
        2,
    )


async def test_a_limit_above_the_plans_cap_is_refused(api: Api) -> None:
    """R4.5 (UL9): `professional` runs 200 a day."""
    company = await _company(api)
    owner = await api.person(company, manager=True)
    refused = await api.call(
        owner, "PUT", _tenant_path(company, "runs/day"), json={"limit_value": "201", "kind": "hard"}
    )
    assert (refused.status_code, _reason(refused)) == (422, "limit_above_plan")
    assert await api.policies(company) == []


@pytest.mark.parametrize(
    ("pair", "body"),
    [
        ("cost_usd_per_week/month", {"limit_value": "1", "kind": "hard"}),
        ("tokens/day", {"limit_value": "1", "kind": "hard"}),
        ("cost_usd/month", {"limit_value": "1", "kind": "soft"}),
    ],
)
async def test_a_pair_or_a_kind_outside_w1_is_a_validation_failure(
    api: Api, pair: str, body: dict[str, str]
) -> None:
    """R4.14 (UL19), R4.8: 422 `validation_failed`, no row."""
    company = await _company(api)
    owner = await api.person(company, manager=True)
    refused = await api.call(owner, "PUT", _tenant_path(company, pair), json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["type"] == "urn:dw:problem:validation_failed"
    assert await api.policies(company) == []


async def test_without_the_key_the_caller_is_refused_and_nothing_changes(api: Api) -> None:
    """R4.6 (UL10): 403 for the write and for the read."""
    company = await _company(api)
    member = await api.person(company, manager=False)
    put = await api.call(
        member, "PUT", _tenant_path(company), json={"limit_value": "1", "kind": "hard"}
    )
    assert put.status_code == 403
    assert (await api.call(member, "GET", "/limits")).status_code == 403
    assert await api.policies(company) == []


async def test_another_companys_scope_is_404_and_a_component_of_another_kind_422(
    api: Api,
) -> None:
    """R4.6: the company is the caller's, never the path's; a workspace of
    another company is 404 like one that never existed; an `agent` limit on a
    workflow is 422 `scope_kind_mismatch`."""
    mine, theirs = await _company(api), await _company(api)
    owner = await api.person(mine, manager=True)
    body = {"limit_value": "1", "kind": "hard"}
    for path in (
        _tenant_path(theirs),
        f"/limits/workspace/{theirs.main}/cost_usd/month",
    ):
        refused = await api.call(owner, "PUT", path, json=body)
        assert refused.status_code == 404, (path, refused.text)
    workflow = uuid.uuid4()
    async with api.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name,"
                " owning_workspace_id, row_version) VALUES (:a, :t, 'workflow', :n, :w, 1)"
            ),
            {"a": workflow, "t": mine.tenant_id, "n": f"l_{workflow.hex[:10]}", "w": mine.main},
        )
    mismatch = await api.call(owner, "PUT", f"/limits/agent/{workflow}/cost_usd/month", json=body)
    assert (mismatch.status_code, _reason(mismatch)) == (422, "scope_kind_mismatch")
    assert await api.policies(mine) == []
    assert await api.policies(theirs) == []
