"""The Allowed hosts against Postgres (connections-and-vault R3.8, R3.11,
R3.18, R3.19, R3.21; CV19, CV22, CV30; migration 20bb9a2210cf).

- the CHECK refuses an IP literal and a malformed pattern from `dw_app`
  itself, below the API;
- what the egress client reads (`SqlAllowedHosts`) is one company's live rows:
  another company's are invisible, and a removed row is gone at the next call;
- the settlement inserts the row named by the approval `ON CONFLICT DO
  NOTHING` and audits only a new row: a replay, a replay after removal and a
  second approval of the same pattern add nothing;
- a removal of another company's id finds nothing and changes nothing.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_connectors.egress import EgressClient, EgressContext, EgressRequest, NoCatalogueHosts
from dw_connectors.testing import FakeDns, FakeNetwork
from dw_kernel.dispatch import NotDispatchedError
from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.egress_allowlist_repo import (
    SqlAllowedHostRepository,
    SqlAllowedHosts,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.egress_allowlist import (
    ALLOWLIST_ADDED,
    EGRESS_ALLOWED_HOST,
    AllowedHostSettler,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.allowed_hosts import AllowedHost
from dw_platform.domain.audit import AuditEvent
from dw_platform.testing.rbac import PlantedTenant, plant_person, plant_tenant

pytestmark = pytest.mark.integration

_TENANT = "SELECT set_config('app.tenant_id', :t, true)"


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


@dataclass
class Company:
    tenant: PlantedTenant
    person: uuid.UUID
    decider: uuid.UUID

    @property
    def id(self) -> uuid.UUID:
        return self.tenant.tenant_id

    @property
    def scope(self) -> WorkScope:
        return WorkScope(tenant_id=self.id, workspace_id=self.tenant.main)

    def context(self) -> AccessContext:
        return AccessContext(
            tenant_id=self.id,
            workspace_id=self.tenant.main,
            principal_id=self.person,
            roles=frozenset(),
            plan_id="professional",
        )


async def _company(migrator: AsyncEngine) -> Company:
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        person = await plant_person(conn, tenant.tenant_id)
        decider = await plant_person(conn, tenant.tenant_id)
    return Company(tenant, person, decider)


async def _row(
    migrator: AsyncEngine,
    company: Company,
    pattern: str,
    *,
    ports: tuple[int, ...] = (443,),
    purpose: str = "http_tool",
    removed: bool = False,
) -> uuid.UUID:
    row = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.egress_allowed_hosts (id, tenant_id, owning_workspace_id,"
                " host_pattern, ports, purpose, created_by, removed_at, removed_by)"
                " VALUES (:id, :t, :w, :p, :ports, :purpose, :u,"
                " CASE WHEN :gone THEN now() END, CASE WHEN :gone THEN CAST(:u AS uuid) END)"
            ),
            {
                "id": row,
                "t": company.id,
                "w": company.tenant.main,
                "p": pattern,
                "ports": list(ports),
                "purpose": purpose,
                "u": company.person,
                "gone": removed,
            },
        )
    return row


async def _decided(
    migrator: AsyncEngine, company: Company, pattern: str, *, approved: bool = True
) -> uuid.UUID:
    """A decided `egress.allowed_host` approval, as the approval flow leaves it."""
    approval = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, reason, payload, required_scope, status)"
                " VALUES (:id, :t, :w, :type, :u, 'x', CAST(:payload AS jsonb),"
                " 'integrations.admin', :status)"
            ),
            {
                "id": approval,
                "t": company.id,
                "w": company.tenant.main,
                "type": EGRESS_ALLOWED_HOST,
                "u": company.person,
                "payload": (
                    f'{{"host_pattern": "{pattern}", "ports": [443],'
                    ' "purpose": "http_tool", "note": null}'
                ),
                "status": "approved" if approved else "rejected",
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_decisions (id, request_id, tenant_id, workspace_id,"
                " decided_by, outcome, comment, decided_at)"
                " VALUES (:id, :r, :t, :w, :d, :o, 'ok', now())"
            ),
            {
                "id": uuid.uuid4(),
                "r": approval,
                "t": company.id,
                "w": company.tenant.main,
                "d": company.decider,
                "o": "approved" if approved else "rejected",
            },
        )
    return approval


async def _count(migrator: AsyncEngine, sql: str, **values: object) -> int:
    async with migrator.connect() as conn:
        return int(await conn.scalar(sa.text(sql), values) or 0)


# -- R3.8: the CHECK, below the API ------------------------------------------------------


@pytest.mark.parametrize(
    "pattern", ["203.0.113.5", "*.203.0.113", "API.acme.vn", "a_b.acme.vn", "*.*.acme.vn", "::1"]
)
async def test_the_application_role_cannot_write_a_pattern_the_api_would_refuse(
    migrator: AsyncEngine, app: AsyncEngine, pattern: str
) -> None:
    """R3.8 (CV19): an IP literal or a malformed pattern, written straight by
    `dw_app` with its tenant bound, breaks the CHECK."""
    company = await _company(migrator)
    async with app.connect() as conn:
        await conn.execute(sa.text(_TENANT), {"t": str(company.id)})
        with pytest.raises(IntegrityError, match="ck_egress_allowed_hosts_host_pattern"):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.egress_allowed_hosts (id, tenant_id,"
                    " owning_workspace_id, host_pattern, purpose, created_by)"
                    " VALUES (gen_random_uuid(), :t, :w, :p, 'http_tool', :u)"
                ),
                {"t": company.id, "w": company.tenant.main, "p": pattern, "u": company.person},
            )


async def test_a_removal_names_both_its_time_and_its_person(
    migrator: AsyncEngine, app: AsyncEngine
) -> None:
    company = await _company(migrator)
    row = await _row(migrator, company, "api.acme.vn")
    async with app.connect() as conn:
        await conn.execute(sa.text(_TENANT), {"t": str(company.id)})
        with pytest.raises(IntegrityError, match="ck_egress_allowed_hosts_removed"):
            await conn.execute(
                sa.text(
                    "UPDATE platform.egress_allowed_hosts SET removed_at = now() WHERE id = :i"
                ),
                {"i": row},
            )


# -- R3.7, R3.21: what egress reads -----------------------------------------------------------


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> FakeDns:
    table = FakeDns()
    monkeypatch.setattr(socket, "getaddrinfo", table.getaddrinfo(socket.getaddrinfo))
    return table


def _egress(app: AsyncEngine, network: FakeNetwork) -> EgressClient:
    return EgressClient(
        allowed_hosts=SqlAllowedHosts(async_sessionmaker(app, expire_on_commit=False)),
        catalogue=NoCatalogueHosts(),
        network=network,
    )


def _call(company: Company) -> EgressContext:
    return EgressContext(
        tenant_id=company.id,
        workspace_id=company.tenant.main,
        run_id=None,
        run_mode="live",
        purpose="http_tool",
    )


async def test_a_company_neither_sees_nor_uses_another_companys_list(
    migrator: AsyncEngine, app: AsyncEngine, dns: FakeDns
) -> None:
    """R3.8, R3.7 (CV19): B's row is invisible to A's call, under RLS."""
    a, b = await _company(migrator), await _company(migrator)
    await _row(migrator, b, "*.vendor-b.vn")
    dns.set("api.vendor-b.vn", ["8.8.4.4"])
    network = FakeNetwork()
    hosts = SqlAllowedHosts(async_sessionmaker(app, expire_on_commit=False))

    assert await hosts.live(a.id) == []
    assert [r.host_pattern for r in await hosts.live(b.id)] == ["*.vendor-b.vn"]
    with pytest.raises(NotDispatchedError) as refused:
        await _egress(app, network).send(_call(a), EgressRequest("GET", "https://api.vendor-b.vn/"))
    assert refused.value.details["reason_code"] == "egress_blocked:host_not_allowed"
    await _egress(app, network).send(_call(b), EgressRequest("GET", "https://api.vendor-b.vn/"))
    assert network.opened == ["8.8.4.4"]


async def test_a_removed_row_admits_nothing(
    migrator: AsyncEngine, app: AsyncEngine, dns: FakeDns
) -> None:
    """R3.21, R3.18 (CV19, CV30): `removed_at` filters the list egress reads."""
    company = await _company(migrator)
    await _row(migrator, company, "*.acme.vn", removed=True)
    await _row(migrator, company, "live.acme.vn", ports=(8443,))
    dns.set("api.acme.vn", ["8.8.4.4"])
    network = FakeNetwork()

    with pytest.raises(NotDispatchedError) as refused:
        await _egress(app, network).send(
            _call(company), EgressRequest("GET", "https://api.acme.vn/")
        )

    assert refused.value.details["reason_code"] == "egress_blocked:host_not_allowed"
    assert network.opened == []


# -- R3.11: the settlement --------------------------------------------------------------------


def _settler(app: AsyncEngine) -> AllowedHostSettler:
    return AllowedHostSettler(
        repo=SqlAllowedHostRepository(async_sessionmaker(app, expire_on_commit=False)),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


async def _added(migrator: AsyncEngine, company: Company) -> list[tuple[str, dict[str, object]]]:
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT actor_id::text, details FROM platform.audit_events"
                " WHERE tenant_id = :t AND action = :a"
            ),
            {"t": company.id, "a": ALLOWLIST_ADDED},
        )
        return [(row[0], dict(row[1])) for row in rows]


async def test_an_approval_adds_the_row_named_by_it_once_whatever_is_replayed(
    migrator: AsyncEngine, app: AsyncEngine
) -> None:
    """R3.11 (CV22): one row, id the approval's, one audit in the decider's
    name; a replay, a replay after removal and a second approval of the same
    pattern each end without error and write nothing."""
    company = await _company(migrator)
    first = await _decided(migrator, company, "*.acme.vn")
    second = await _decided(migrator, company, "*.acme.vn")
    settler = _settler(app)

    assert (await settler.settle(company.scope, first)).outcome == "added"
    assert (await settler.settle(company.scope, first)).outcome == "already_present"
    assert (await settler.settle(company.scope, second)).outcome == "already_present"
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.egress_allowed_hosts SET removed_at = now(), removed_by = :u"
                " WHERE id = :i"
            ),
            {"i": first, "u": company.person},
        )
    assert (await settler.settle(company.scope, first)).outcome == "already_present"

    rows = await _count(
        migrator,
        "SELECT count(*) FROM platform.egress_allowed_hosts WHERE tenant_id = :t",
        t=company.id,
    )
    live = await _count(
        migrator,
        "SELECT count(*) FROM platform.egress_allowed_hosts"
        " WHERE tenant_id = :t AND removed_at IS NULL",
        t=company.id,
    )
    assert (rows, live) == (1, 0)
    ((actor, details),) = await _added(migrator, company)
    assert actor == str(company.decider)
    assert details["lane"] == "outbox" and details["approval_id"] == str(first)
    async with migrator.connect() as conn:
        owner = (
            await conn.execute(
                sa.text(
                    "SELECT id, created_by, owning_workspace_id FROM platform.egress_allowed_hosts"
                    " WHERE tenant_id = :t"
                ),
                {"t": company.id},
            )
        ).one()
    assert tuple(owner) == (first, company.person, company.tenant.main)


async def test_a_rejection_adds_nothing(migrator: AsyncEngine, app: AsyncEngine) -> None:
    company = await _company(migrator)
    approval = await _decided(migrator, company, "api.acme.vn", approved=False)

    assert (await _settler(app).settle(company.scope, approval)).outcome == "rejected"
    assert await _added(migrator, company) == []
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.egress_allowed_hosts WHERE tenant_id = :t",
            t=company.id,
        )
        == 0
    )


async def test_another_companys_approval_is_not_found_under_this_tenant(
    migrator: AsyncEngine, app: AsyncEngine
) -> None:
    a, b = await _company(migrator), await _company(migrator)
    approval = await _decided(migrator, b, "api.acme.vn")

    with pytest.raises(NotFoundError):
        await _settler(app).settle(a.scope, approval)


# -- R3.18, R3.19: removal -----------------------------------------------------------------------


async def test_another_companys_id_is_not_removed(migrator: AsyncEngine, app: AsyncEngine) -> None:
    """R3.19 (CV30): under RLS the row is not there to stamp."""
    a, b = await _company(migrator), await _company(migrator)
    row = await _row(migrator, a, "api.acme.vn")
    repo = SqlAllowedHostRepository(async_sessionmaker(app, expire_on_commit=False))

    removed = await repo.remove(b.context(), row, audit_for=lambda _: pytest.fail("no audit"))

    assert removed is None
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.egress_allowed_hosts"
            " WHERE id = :i AND removed_at IS NULL",
            i=row,
        )
        == 1
    )


async def test_a_live_row_is_removed_by_its_company_once(
    migrator: AsyncEngine, app: AsyncEngine
) -> None:
    """R3.18: stamped with the caller and audited in the same transaction."""
    company = await _company(migrator)
    row = await _row(migrator, company, "api.acme.vn")
    repo = SqlAllowedHostRepository(async_sessionmaker(app, expire_on_commit=False))
    seen: list[uuid.UUID] = []

    def audit(host: AllowedHost) -> AuditEvent:
        seen.append(host.id)
        return AuditEvent(
            id=uuid.uuid4(),
            tenant_id=TenantId(company.id),
            workspace_id=WorkspaceId(company.tenant.main),
            actor_id=UserId(company.person),
            action="egress.allowlist.removed",
            resource_type="egress_allowed_host",
            resource_id=str(row),
            occurred_at=datetime.now(UTC),
        )

    first = await repo.remove(company.context(), row, audit_for=audit)
    again = await repo.remove(company.context(), row, audit_for=audit)

    assert first is not None and again is None and seen == [row]
    async with migrator.connect() as conn:
        removed_by = await conn.scalar(
            sa.text("SELECT removed_by FROM platform.egress_allowed_hosts WHERE id = :i"),
            {"i": row},
        )
    assert removed_by == company.person
