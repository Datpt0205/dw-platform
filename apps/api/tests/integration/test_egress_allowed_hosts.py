"""The company's Allowed hosts over HTTP, against Postgres
(connections-and-vault R3.8-R3.12, R3.18, R3.19; CV19, CV22, CV30).

The real app and container, so the strict prefix is the one `wiring.py` adds
to the approval flow; the decision is settled by `AllowedHostSettler`, as the
worker does on the decision's outbox event; and whether a destination is
allowed is asked of an `EgressClient` reading the same table, under a fake
socket layer.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_connectors.egress import EgressClient, EgressContext, EgressRequest, NoCatalogueHosts
from dw_connectors.testing import FakeDns, FakeNetwork
from dw_kernel.dispatch import NotDispatchedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.egress_allowlist_repo import (
    SqlAllowedHostRepository,
    SqlAllowedHosts,
)
from dw_platform.application.egress_allowlist import (
    EGRESS_ALLOWED_HOST_DECIDED,
    AllowedHostSettler,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)

pytestmark = pytest.mark.integration

SECRET = "egress-allowlist-secret-0123456789abcdef"
ADMIN = {
    "integrations.admin": "tenant",
    "approvals.decide": "workspace",
    "approvals.read": "workspace",
}
DECIDER = {"approvals.decide": "workspace", "approvals.read": "workspace"}
PATH = "/api/v1/egress/allowed-hosts"


@dataclass(frozen=True)
class Person:
    tenant: PlantedTenant
    user: uuid.UUID


async def _person(conn: Any, tenant: PlantedTenant, role: uuid.UUID) -> Person:
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, tenant.main, user)
    await assign(conn, tenant.tenant_id, tenant.main, membership, role)
    return Person(tenant, user)


async def _company(conn: Any, **people: dict[str, str]) -> dict[str, Person]:
    tenant = await plant_tenant(conn)
    roles: dict[str, uuid.UUID] = {}
    found = {}
    for name, privileges in people.items():
        key = "admin" if "integrations.admin" in privileges else "decider"
        if key not in roles:
            roles[key] = await plant_role(
                conn, tenant.tenant_id, f"eg_{key}_{tenant.tenant_id.hex[:6]}", privileges
            )
        found[name] = await _person(conn, tenant, roles[key])
    return found


@dataclass
class Harness:
    people: dict[str, Person]
    client: httpx.AsyncClient
    migrator: AsyncEngine
    sessions: async_sessionmaker[Any]

    def headers(self, who: str) -> dict[str, str]:
        person = self.people[who]
        token = DevTokenVerifier(SECRET).issue(f"rbac-{person.user}")
        return {
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": str(person.tenant.tenant_id),
            "X-Workspace-Id": str(person.tenant.main),
        }

    async def ask(self, who: str, pattern: str, **body: Any) -> httpx.Response:
        return await self.client.post(
            PATH,
            json={"host_pattern": pattern, "purpose": "http_tool", **body},
            headers=self.headers(who),
        )

    async def decide(self, who: str, approval: str, *, approve: bool = True) -> httpx.Response:
        return await self.client.post(
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": approve, "comment": "đã xem nhà cung cấp"},
            headers=self.headers(who),
        )

    async def settle(self, who: str, approval: str) -> str:
        """What the worker does with the decision's outbox event."""
        async with self.migrator.connect() as conn:
            payload = await conn.scalar(
                sa.text(
                    "SELECT payload FROM platform.outbox_events WHERE event_type = :e"
                    " AND aggregate_id = :a"
                ),
                {"e": EGRESS_ALLOWED_HOST_DECIDED, "a": uuid.UUID(approval)},
            )
        assert payload is not None, "the decision announced nothing"
        person = self.people[who]
        settler = AllowedHostSettler(
            repo=SqlAllowedHostRepository(self.sessions),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        )
        scope = WorkScope(tenant_id=person.tenant.tenant_id, workspace_id=person.tenant.main)
        return (await settler.settle(scope, uuid.UUID(payload["approval_id"]))).outcome

    async def count(self, sql: str, **values: Any) -> int:
        async with self.migrator.connect() as conn:
            return int(await conn.scalar(sa.text(sql), values) or 0)

    async def rows(self, who: str) -> int:
        return await self.count(
            "SELECT count(*) FROM platform.egress_allowed_hosts WHERE tenant_id = :t",
            t=self.people[who].tenant.tenant_id,
        )

    async def audits(self, who: str, action: str) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT actor_id, details FROM platform.audit_events"
                            " WHERE tenant_id = :t AND action = :a"
                        ),
                        {"t": self.people[who].tenant.tenant_id, "a": action},
                    )
                ).all()
            )

    async def reaches(self, who: str, url: str) -> bool:
        """Whether the egress client would let `who`'s company call `url`."""
        person = self.people[who]
        client = EgressClient(
            allowed_hosts=SqlAllowedHosts(self.sessions),
            catalogue=NoCatalogueHosts(),
            network=FakeNetwork(),
        )
        context = EgressContext(
            tenant_id=person.tenant.tenant_id,
            workspace_id=person.tenant.main,
            run_id=None,
            run_mode="live",
            purpose="http_tool",
        )
        try:
            await client.send(context, EgressRequest("GET", url))
        except NotDispatchedError as refused:
            assert refused.details["reason_code"] == "egress_blocked:host_not_allowed"
            return False
        return True


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> FakeDns:
    table = FakeDns()
    for name in ("api.acme.vn", "crm.acme.vn"):
        table.set(name, ["8.8.4.4"])
    monkeypatch.setattr(socket, "getaddrinfo", table.getaddrinfo(socket.getaddrinfo))
    return table


@pytest.fixture
async def harness(api_db: DatabaseUrls, dns: FakeDns) -> AsyncIterator[Harness]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        people = {
            **await _company(conn, maker=ADMIN, checker=ADMIN, plain=DECIDER),
            **await _company(conn, other_admin=ADMIN),
            **await _company(conn, lonely=ADMIN, lonely_decider=DECIDER),
        }
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            # The approval flow comes with the agent runtime, which composes
            # over lazy clients: a placeholder store is enough.
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    assert container.engine is not None and container.approval_flow is not None
    sessions = async_sessionmaker(container.engine, expire_on_commit=False)
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://it") as client:
                yield Harness(people, client, migrator, sessions)
    finally:
        await container.engine.dispose()
        await migrator.dispose()


def _reason(response: httpx.Response) -> object:
    return response.json().get("details", {}).get("reason_code")


# -- R3.8 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "reason"),
    [
        ("*.com.vn", "host_pattern_public_suffix"),
        ("*.github.io", "host_pattern_public_suffix"),
        ("203.0.113.5", "host_pattern_ip_literal"),
    ],
)
async def test_a_pattern_on_a_public_suffix_or_an_ip_is_422_and_opens_nothing(
    harness: Harness, pattern: str, reason: str
) -> None:
    """R3.8 (CV19)."""
    response = await harness.ask("maker", pattern)

    assert response.status_code == 422, response.text
    assert _reason(response) == reason
    assert (
        await harness.count(
            "SELECT count(*) FROM platform.approval_requests WHERE tenant_id = :t",
            t=harness.people["maker"].tenant.tenant_id,
        )
        == 0
    )


# -- R3.9-R3.11 ---------------------------------------------------------------------------------


async def test_a_host_is_allowed_only_once_a_second_person_approves_it(harness: Harness) -> None:
    """R3.9, R3.10, R3.11 (CV22), end to end."""
    asked = await harness.ask("maker", "*.ACME.vn.", ports=[443], note="CRM của công ty")
    assert asked.status_code == 202, asked.text
    approval = asked.json()["approval_id"]
    assert asked.headers["location"] == f"/api/v1/approvals/{approval}"

    # R3.9: an approval stamped with the key, no row, nothing reachable.
    async with harness.migrator.connect() as conn:
        stamped = (
            await conn.execute(
                sa.text(
                    "SELECT approval_type, required_scope, run_id, payload"
                    " FROM platform.approval_requests WHERE id = :i"
                ),
                {"i": uuid.UUID(approval)},
            )
        ).one()
    assert (stamped.approval_type, stamped.required_scope, stamped.run_id) == (
        "egress.allowed_host",
        "integrations.admin",
        None,
    )
    assert stamped.payload["host_pattern"] == "*.acme.vn"
    assert await harness.rows("maker") == 0
    assert not await harness.reaches("maker", "https://api.acme.vn/")

    # R3.10: the requester cannot decide it; someone without the key does not see it.
    own = await harness.decide("maker", approval)
    assert own.status_code == 409 and _reason(own) == "second_person_required", own.text
    keyless = await harness.decide("plain", approval)
    assert keyless.status_code == 404, keyless.text
    assert await harness.rows("maker") == 0

    # R3.11: a second holder approves; the settlement adds one row, once.
    decided = await harness.decide("checker", approval)
    assert decided.status_code == 200, decided.text
    assert await harness.settle("checker", approval) == "added"
    assert await harness.settle("checker", approval) == "already_present"
    assert await harness.rows("maker") == 1
    assert (
        await harness.count(
            "SELECT count(*) FROM platform.egress_allowed_hosts WHERE id = :i",
            i=uuid.UUID(approval),
        )
        == 1
    )
    ((actor, details),) = await harness.audits("maker", "egress.allowlist.added")
    assert actor == harness.people["checker"].user and details["lane"] == "outbox"
    assert await harness.reaches("maker", "https://api.acme.vn/")

    listed = await harness.client.get(PATH, headers=harness.headers("checker"))
    assert listed.status_code == 200
    (item,) = listed.json()["items"]
    assert (item["id"], item["host_pattern"], item["ports"]) == (approval, "*.acme.vn", [443])
    assert item["created_by"] == str(harness.people["maker"].user)


async def test_two_approvals_of_one_pattern_leave_one_row(harness: Harness) -> None:
    """R3.11: the second settlement ends without error and audits nothing."""
    approvals = []
    for _ in range(2):
        asked = await harness.ask("maker", "crm.acme.vn")
        approvals.append(asked.json()["approval_id"])
    for approval in approvals:
        assert (await harness.decide("checker", approval)).status_code == 200

    outcomes = [await harness.settle("checker", approval) for approval in approvals]

    assert outcomes == ["added", "already_present"]
    assert await harness.rows("maker") == 1
    assert len(await harness.audits("maker", "egress.allowlist.added")) == 1


async def test_a_rejection_allows_nothing(harness: Harness) -> None:
    approval = (await harness.ask("maker", "api.acme.vn")).json()["approval_id"]

    assert (await harness.decide("checker", approval, approve=False)).status_code == 200
    assert await harness.settle("checker", approval) == "rejected"
    assert await harness.rows("maker") == 0


# -- R3.12 ------------------------------------------------------------------------------


async def test_without_a_second_holder_no_approval_is_opened(harness: Harness) -> None:
    """R3.12 (CV22): the only holder asks; then a second holder joins."""
    tenant = harness.people["lonely"].tenant

    refused = await harness.ask("lonely", "api.acme.vn")

    assert refused.status_code == 409 and _reason(refused) == "no_checker_available"
    assert (
        await harness.count(
            "SELECT count(*) FROM platform.approval_requests WHERE tenant_id = :t",
            t=tenant.tenant_id,
        )
        == 0
    )
    assert await harness.rows("lonely") == 0

    async with harness.migrator.begin() as conn:
        role = await plant_role(
            conn, tenant.tenant_id, "eg_second", {"integrations.admin": "tenant"}
        )
        await _person(conn, tenant, role)
    assert (await harness.ask("lonely", "api.acme.vn")).status_code == 202


# -- R3.18, R3.19 ------------------------------------------------------------------------------


async def _allowed(harness: Harness, pattern: str) -> str:
    approval = str((await harness.ask("maker", pattern)).json()["approval_id"])
    assert (await harness.decide("checker", approval)).status_code == 200
    assert await harness.settle("checker", approval) == "added"
    return approval


async def test_a_removal_takes_effect_at_the_next_call(harness: Harness) -> None:
    """R3.18 (CV30): one person, at once, audited."""
    host = await _allowed(harness, "*.acme.vn")
    assert await harness.reaches("maker", "https://api.acme.vn/")

    removed = await harness.client.delete(f"{PATH}/{host}", headers=harness.headers("maker"))

    assert removed.status_code == 204, removed.text
    async with harness.migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT removed_at, removed_by FROM platform.egress_allowed_hosts WHERE id = :i"
                ),
                {"i": uuid.UUID(host)},
            )
        ).one()
    assert row.removed_at is not None and row.removed_by == harness.people["maker"].user
    ((actor, _),) = await harness.audits("maker", "egress.allowlist.removed")
    assert actor == harness.people["maker"].user
    listed = await harness.client.get(PATH, headers=harness.headers("maker"))
    assert listed.json()["items"] == []
    assert not await harness.reaches("maker", "https://api.acme.vn/")
    again = await harness.client.delete(f"{PATH}/{host}", headers=harness.headers("maker"))
    assert again.status_code == 404


async def test_another_company_cannot_see_or_remove_a_row(harness: Harness) -> None:
    """R3.19 (CV30): 404, the same as an id that never existed; the row lives."""
    host = await _allowed(harness, "*.acme.vn")

    removed = await harness.client.delete(f"{PATH}/{host}", headers=harness.headers("other_admin"))
    listed = await harness.client.get(PATH, headers=harness.headers("other_admin"))
    unknown = await harness.client.delete(
        f"{PATH}/{uuid.uuid4()}", headers=harness.headers("other_admin")
    )

    assert removed.status_code == 404 and unknown.status_code == 404
    assert listed.status_code == 200 and listed.json()["items"] == []
    assert await harness.reaches("maker", "https://api.acme.vn/")
    assert not await harness.reaches("other_admin", "https://api.acme.vn/")


async def test_without_the_key_every_route_is_403_and_the_row_lives(harness: Harness) -> None:
    """R3.19 (CV30)."""
    host = await _allowed(harness, "*.acme.vn")

    removed = await harness.client.delete(f"{PATH}/{host}", headers=harness.headers("plain"))
    listed = await harness.client.get(PATH, headers=harness.headers("plain"))
    asked = await harness.ask("plain", "api.acme.vn")

    assert (removed.status_code, listed.status_code, asked.status_code) == (403, 403, 403)
    assert await harness.reaches("maker", "https://api.acme.vn/")
