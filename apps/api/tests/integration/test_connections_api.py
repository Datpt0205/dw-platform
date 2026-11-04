"""The shared connections over HTTP, against Postgres (connections-and-vault 04:
R1.15, R5.1-R5.3, R5.8, R5.10-R5.13, R5.18-R5.21; CV12-CV14, CV21, CV28, CV31).

The real app and container: the key service is the development one, the
strict prefix is the one `wiring.py` adds, and a decision is settled by
`ConnectionEnableSettler` as the worker does on the decision's outbox event.
Only two ports are the test's: the connector catalogue (ticket 05 wires the
manifests; W1's knows none) and the dependents (tenant-config/05's), each
answering as its contract says.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.routes.v1.connections import _without_secret_values
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.connections_repo import SqlConnectionStore
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.connection_admin import (
    CONNECTIONS_ENABLE_DECIDED,
    ConnectionDependents,
    ConnectionEnableSettler,
    ConnectionService,
    DependentRef,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)

pytestmark = pytest.mark.integration

SECRET = "connections-api-secret-0123456789abcdef"
MASTER = base64.b64encode(bytes(range(32))).decode()
CANARY = "canary-c04-không-được-lộ"
PATH = "/api/v1/connections"
DECIDE = {"approvals.decide": "workspace", "approvals.read": "workspace"}
ADMIN = {"connections.read": "tenant", "connections.manage": "tenant", **DECIDE}
W1_ONLY = {"connections.read": "workspace", "connections.manage": "workspace", **DECIDE}
READS_ALL_MANAGES_W1 = {
    "connections.read": "tenant",
    "connections.manage": "workspace",
    **DECIDE,
}


@dataclass
class FakeCatalog:
    """`ConnectorCatalogPort` as ticket 05's manifests will answer it."""

    fields: dict[tuple[str, int], frozenset[str]] = field(
        default_factory=lambda: {
            ("probe", 1): frozenset({"api_key", "password"}),
            ("smtp", 1): frozenset({"password"}),
        }
    )

    def secret_fields(self, connector_key: str, connector_major: int) -> frozenset[str] | None:
        return self.fields.get((connector_key, connector_major))


@dataclass
class FakeDependents:
    """`ConnectionDependentsPort` per its contract: what the fixture says, or a raise."""

    answer: ConnectionDependents = field(default_factory=lambda: ConnectionDependents(total=0))
    fails: bool = False
    asked: list[uuid.UUID] = field(default_factory=list)

    async def dependents(
        self, context: AccessContext, connection_id: uuid.UUID
    ) -> ConnectionDependents:
        self.asked.append(connection_id)
        if self.fails:
            raise RuntimeError("the dependents could not be read")
        return self.answer


@dataclass(frozen=True)
class Person:
    tenant: PlantedTenant
    user: uuid.UUID
    workspace: uuid.UUID


async def _person(
    conn: Any,
    tenant: PlantedTenant,
    privileges: dict[str, str] | None,
    *,
    at: uuid.UUID | None = None,
    acting_in: uuid.UUID | None = None,
) -> Person:
    """A member of every workspace of `tenant`, holding `privileges` through one
    role assigned at `at` (the main workspace by default)."""
    user = await plant_person(conn, tenant.tenant_id)
    anchor = at or tenant.main
    for workspace in tenant.workspaces:
        membership = await plant_membership(conn, tenant.tenant_id, workspace, user)
        if privileges is not None and workspace == anchor:
            role = await plant_role(
                conn, tenant.tenant_id, f"cn_{uuid.uuid4().hex[:12]}", privileges
            )
            await assign(conn, tenant.tenant_id, workspace, membership, role)
    return Person(tenant, user, acting_in or tenant.main)


@dataclass
class Harness:
    people: dict[str, Person]
    client: httpx.AsyncClient
    migrator: AsyncEngine
    sessions: async_sessionmaker[Any]
    catalog: FakeCatalog
    dependents: FakeDependents
    openapi: dict[str, Any]

    def headers(
        self, who: str, *, workspace: uuid.UUID | None = None, **extra: str
    ) -> dict[str, str]:
        person = self.people[who]
        token = DevTokenVerifier(SECRET).issue(f"rbac-{person.user}")
        return {
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": str(person.tenant.tenant_id),
            "X-Workspace-Id": str(workspace or person.workspace),
            **extra,
        }

    def second(self, who: str) -> uuid.UUID:
        return self.people[who].tenant.workspaces[1]

    async def create(
        self,
        who: str,
        *,
        workspace: uuid.UUID | None = None,
        key: str | None = None,
        **body: Any,
    ) -> httpx.Response:
        payload = {
            "name": "Hộp thư bán hàng",
            "connector_key": "probe",
            "connector_major": 1,
            "external_account": f"{uuid.uuid4().hex[:10]}@acme.vn",
            "secrets": {"api_key": CANARY, "password": CANARY + "-pw"},
            **body,
        }
        extra = {"Idempotency-Key": key} if key else {}
        return await self.client.post(
            PATH, json=payload, headers=self.headers(who, workspace=workspace, **extra)
        )

    async def created(self, who: str, **body: Any) -> uuid.UUID:
        response = await self.create(who, **body)
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    async def call(
        self, who: str, method: str, suffix: str, *, workspace: uuid.UUID | None = None, **kw: Any
    ) -> httpx.Response:
        return await self.client.request(
            method, f"{PATH}{suffix}", headers=self.headers(who, workspace=workspace), **kw
        )

    async def decide(self, who: str, approval: str, *, approve: bool = True) -> httpx.Response:
        person = self.people[who]
        return await self.client.post(
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": approve, "comment": "đã xem lại kết nối"},
            headers=self.headers(who, workspace=person.workspace),
        )

    async def settle(self, who: str, approval: str) -> str:
        """What the worker does with the decision's outbox event."""
        async with self.migrator.connect() as conn:
            event = (
                await conn.execute(
                    sa.text(
                        "SELECT tenant_id, workspace_id, payload FROM platform.outbox_events"
                        " WHERE event_type = :e AND aggregate_id = :a"
                    ),
                    {"e": CONNECTIONS_ENABLE_DECIDED, "a": uuid.UUID(approval)},
                )
            ).one()
        settler = ConnectionEnableSettler(
            store=SqlConnectionStore(self.sessions),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        )
        scope = WorkScope(tenant_id=event.tenant_id, workspace_id=event.workspace_id)
        return await settler.settle(scope, uuid.UUID(event.payload["approval_id"]))

    async def scalar(self, sql: str, **values: Any) -> Any:
        async with self.migrator.connect() as conn:
            return await conn.scalar(sa.text(sql), values)

    async def row(self, connection: uuid.UUID) -> Any:
        async with self.migrator.connect() as conn:
            return (
                await conn.execute(
                    sa.text("SELECT * FROM platform.connections WHERE id = :c"), {"c": connection}
                )
            ).first()

    async def envelopes(self, connection: uuid.UUID) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list(
                await conn.execute(
                    sa.text(
                        "SELECT field, secret_version, revoked_at, replaced_at"
                        " FROM platform.secret_envelopes WHERE connection_id = :c"
                        " ORDER BY field, secret_version"
                    ),
                    {"c": connection},
                )
            )

    async def audits(self, who: str, action: str) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list(
                await conn.execute(
                    sa.text(
                        "SELECT actor_id, workspace_id, resource_id, details::text AS details"
                        " FROM platform.audit_events WHERE tenant_id = :t AND action = :a"
                        " ORDER BY occurred_at"
                    ),
                    {"t": self.people[who].tenant.tenant_id, "a": action},
                )
            )

    async def approvals(self, who: str) -> int:
        return int(
            await self.scalar(
                "SELECT count(*) FROM platform.approval_requests WHERE tenant_id = :t"
                " AND approval_type = 'connections.enable'",
                t=self.people[who].tenant.tenant_id,
            )
        )


@pytest.fixture
async def harness(api_db: DatabaseUrls) -> AsyncIterator[Harness]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        a = await plant_tenant(conn, workspaces=2)
        b = await plant_tenant(conn, workspaces=2)
        lonely = await plant_tenant(conn)
        people = {
            "maker": await _person(conn, a, ADMIN),
            "checker": await _person(conn, a, ADMIN),
            "w1_only": await _person(conn, a, W1_ONLY),
            "reads_all": await _person(conn, a, READS_ALL_MANAGES_W1),
            "decider_only": await _person(conn, a, DECIDE),
            "w2_manager": await _person(
                conn, a, W1_ONLY, at=a.workspaces[1], acting_in=a.workspaces[1]
            ),
            "other_admin": await _person(conn, b, ADMIN),
            "lonely": await _person(conn, lonely, ADMIN),
            "lonely_decider": await _person(conn, lonely, DECIDE),
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
            kms_provider="local",
            local_kms_master_key=SecretStr(MASTER),
        )
    )
    assert container.engine is not None and container.connections is not None
    assert container.secret_store is not None
    sessions = async_sessionmaker(container.engine, expire_on_commit=False)
    catalog, dependents = FakeCatalog(), FakeDependents()
    # The same service the wiring builds, with the two ports this ticket
    # leaves to tickets 05 and tenant-config/05.
    container.connections = ConnectionService(
        store=SqlConnectionStore(sessions),
        secrets=container.secret_store,
        catalog=catalog,
        dependents_port=dependents,
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://it") as client:
                yield Harness(
                    people, client, migrator, sessions, catalog, dependents, app.openapi()
                )
    finally:
        await container.engine.dispose()
        await migrator.dispose()


def _reason(response: httpx.Response) -> object:
    return response.json().get("details", {}).get("reason_code")


@pytest.fixture
def failing_audit(monkeypatch: pytest.MonkeyPatch) -> Iterator[set[str]]:
    """The actions whose audit row fails to write, inside the caller's transaction."""
    actions: set[str] = set()
    original = SqlAuditRepository.append

    async def append(self: SqlAuditRepository, event: AuditEvent) -> None:
        if event.action in actions:
            raise RuntimeError("the audit log is unavailable")
        await original(self, event)

    monkeypatch.setattr(SqlAuditRepository, "append", append)
    yield actions


# -- R5.1, R5.2 (CV12) -------------------------------------------------------------


async def test_a_create_seals_every_declared_field_and_returns_no_value(harness: Harness) -> None:
    response = await harness.create("maker", external_account="  Ban.Hang@ACME.vn ")

    assert response.status_code == 201, response.text
    assert CANARY not in response.text
    body = response.json()
    connection = uuid.UUID(body["id"])
    assert response.headers["Location"] == f"{PATH}/{connection}"
    assert body["status"] == "active"
    assert body["external_account"] == "Ban.Hang@ACME.vn"
    assert body["secret_fields"] == [
        {"field": "api_key", "configured": True},
        {"field": "password", "configured": True},
    ]
    row = await harness.row(connection)
    assert row.owning_workspace_id == harness.people["maker"].tenant.main
    assert row.share_scope == "workspace"
    assert [(e.field, e.secret_version) for e in await harness.envelopes(connection)] == [
        ("api_key", 1),
        ("password", 1),
    ]
    created = await harness.audits("maker", "connection.created")
    assert [(a.actor_id, a.workspace_id) for a in created] == [
        (harness.people["maker"].user, harness.people["maker"].tenant.main)
    ]
    assert CANARY not in created[0].details
    read = await harness.call("maker", "GET", f"/{connection}")
    assert read.status_code == 200 and CANARY not in read.text
    assert read.json()["secret_fields"] == body["secret_fields"]


async def test_w1_wiring_knows_no_connector_and_creates_nothing(api_db: DatabaseUrls) -> None:
    """The composition root's catalogue until ticket 05: every create is 422."""
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        person = await _person(conn, tenant, ADMIN)
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
            kms_provider="local",
            local_kms_master_key=SecretStr(MASTER),
        )
    )
    assert container.engine is not None
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://it") as client:
                response = await client.post(
                    PATH,
                    json={
                        "name": "Hộp thư",
                        "connector_key": "smtp",
                        "connector_major": 1,
                        "external_account": "a@x.vn",
                        "secrets": {"password": CANARY},
                    },
                    headers={
                        "Authorization": "Bearer "
                        + DevTokenVerifier(SECRET).issue(f"rbac-{person.user}"),
                        "X-Tenant-Id": str(tenant.tenant_id),
                        "X-Workspace-Id": str(tenant.main),
                    },
                )
        assert response.status_code == 422, response.text
        assert _reason(response) == "connector_unknown"
        async with migrator.connect() as conn:
            assert (
                await conn.scalar(
                    sa.text("SELECT count(*) FROM platform.connections WHERE tenant_id = :t"),
                    {"t": tenant.tenant_id},
                )
                == 0
            )
    finally:
        await container.engine.dispose()
        await migrator.dispose()


_VALID = {
    "name": "Hộp thư",
    "connector_key": "probe",
    "connector_major": 1,
    "external_account": "a@x.vn",
    "secrets": {"api_key": CANARY, "password": CANARY},
}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"secrets": {"api_key": CANARY}}, "secret_fields_mismatch"),
        (
            {"secrets": {"api_key": CANARY, "password": CANARY, "token": CANARY}},
            "secret_fields_mismatch",
        ),
        ({"name": "   "}, "name_required"),
        ({"external_account": "   "}, "external_account_required"),
        ({"connector_key": "nobody"}, "connector_unknown"),
        ({"name": None}, None),
        ({"external_account": None}, None),
        ({"share_scope": "owner"}, None),
        ({"share_scope": "workspace_subtree"}, None),
    ],
)
async def test_a_create_that_does_not_match_the_connector_writes_nothing(
    harness: Harness, change: dict[str, Any], reason: str | None
) -> None:
    """R5.1, R5.20 (CV14): None drops the field from the body."""
    payload = {**_VALID, **change}
    payload = {k: v for k, v in payload.items() if v is not None}

    response = await harness.client.post(PATH, json=payload, headers=harness.headers("maker"))

    assert response.status_code == 422, response.text
    if reason is not None:
        assert _reason(response) == reason
    assert CANARY not in response.text
    assert (
        await harness.scalar(
            "SELECT count(*) FROM platform.connections WHERE tenant_id = :t",
            t=harness.people["maker"].tenant.tenant_id,
        )
        == 0
    )


@pytest.mark.parametrize(
    "body",
    [
        {"external_account": "b@x.vn"},
        {"share_scope": "workspace_subtree"},
        {"status": "active"},
        {"connector_key": "smtp"},
        {"owning_workspace_id": str(uuid.uuid4())},
        {"secrets": {"token": CANARY}},
    ],
)
async def test_a_patch_takes_the_name_and_declared_secrets_only(
    harness: Harness, body: dict[str, Any]
) -> None:
    """R5.1, R5.10, R5.20."""
    connection = await harness.created("maker")
    before = await harness.row(connection)

    # With a valid name beside it, so only the refused part can make it a 422.
    response = await harness.call(
        "maker", "PATCH", f"/{connection}", json={"name": "Tên mới", **body}
    )

    assert response.status_code == 422, response.text
    after = await harness.row(connection)
    assert after.updated_at == before.updated_at
    assert len(await harness.envelopes(connection)) == 2


async def test_an_audit_that_fails_leaves_no_connection_and_no_envelope(
    harness: Harness, failing_audit: set[str]
) -> None:
    """R5.1: the row, its envelopes and the audit row are one transaction."""
    failing_audit.add("connection.created")

    response = await harness.create("maker")

    assert response.status_code == 500
    tenant = harness.people["maker"].tenant.tenant_id
    assert (
        await harness.scalar(
            "SELECT count(*) FROM platform.connections WHERE tenant_id = :t", t=tenant
        )
        == 0
    )
    assert (
        await harness.scalar(
            "SELECT count(*) FROM platform.secret_envelopes WHERE tenant_id = :t", t=tenant
        )
        == 0
    )


async def test_the_idempotency_fingerprint_never_hashes_a_secret_value(harness: Harness) -> None:
    """R5.1, R1.2: the stored hash is of the body without values; the same key
    with another value replays the first answer and stores no new version."""
    key = f"c04-{uuid.uuid4()}"
    account = f"{uuid.uuid4().hex[:8]}@acme.vn"

    async def send(secret: str) -> tuple[bytes, httpx.Response]:
        raw = json.dumps(
            {
                **_VALID,
                "external_account": account,
                "secrets": {"api_key": secret, "password": secret},
            }
        ).encode()
        headers = harness.headers(
            "maker", **{"Idempotency-Key": key, "Content-Type": "application/json"}
        )
        return raw, await harness.client.post(PATH, content=raw, headers=headers)

    raw, first = await send(CANARY)
    assert first.status_code == 201, first.text
    connection = uuid.UUID(first.json()["id"])
    _, replay = await send("another value")

    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == str(connection)
    assert len(await harness.envelopes(connection)) == 2
    async with harness.migrator.connect() as conn:
        stored = (
            await conn.execute(
                sa.text(
                    "SELECT body_hash, response_body::text AS body FROM platform.idempotency_keys"
                    " WHERE idempotency_key = :k"
                ),
                {"k": key},
            )
        ).one()
    assert stored.body_hash == hashlib.sha256(_without_secret_values(raw)).hexdigest()
    assert stored.body_hash != hashlib.sha256(raw).hexdigest()
    assert CANARY.encode() not in _without_secret_values(raw)
    assert CANARY not in stored.body


async def test_a_rotation_writes_a_new_version_and_audits_its_number_only(
    harness: Harness,
) -> None:
    """R5.2 (CV12): `connection.updated` names the field and the version."""
    connection = await harness.created("maker")
    key = f"c04-{uuid.uuid4()}"

    response = await harness.client.patch(
        f"{PATH}/{connection}",
        json={"name": "Hộp thư mới", "secrets": {"api_key": CANARY + "-v2"}},
        headers=harness.headers("maker", **{"Idempotency-Key": key}),
    )
    replay = await harness.client.patch(
        f"{PATH}/{connection}",
        json={"name": "Hộp thư mới", "secrets": {"api_key": "a third value"}},
        headers=harness.headers("maker", **{"Idempotency-Key": key}),
    )

    assert response.status_code == 200, response.text
    assert replay.status_code == 200 and replay.json() == response.json()
    assert response.json()["name"] == "Hộp thư mới"
    versions = [(e.field, e.secret_version) for e in await harness.envelopes(connection)]
    assert versions == [("api_key", 1), ("api_key", 2), ("password", 1)]
    updated = await harness.audits("maker", "connection.updated")
    assert len(updated) == 1
    details = json.loads(updated[0].details)
    assert details["changed"] == ["secrets", "name"]
    assert details["secret_fields"] == {"api_key": 2}
    assert CANARY not in updated[0].details


async def test_no_answer_of_the_connections_router_has_a_secret_field(harness: Harness) -> None:
    """R5.2 (CV12): every 2xx schema of the router, walked whole."""
    spec = harness.openapi
    schemas = spec["components"]["schemas"]

    def walk(node: Any, seen: set[str]) -> Iterator[tuple[str, Any]]:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    yield from walk(schemas[name], seen)
            for key, value in node.items():
                yield key, value
                yield from walk(value, seen)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item, seen)

    answers = 0
    for path, operations in spec["paths"].items():
        if not path.startswith(PATH):
            continue
        for operation in operations.values():
            for status, answer in operation.get("responses", {}).items():
                if not status.startswith("2"):
                    continue
                answers += 1
                for key, value in walk(answer, set()):
                    assert key != "secrets", (path, status)
                    assert key != "writeOnly", (path, status)
                    assert value != "password", (path, status)
    assert answers >= 9


# -- R5.3 (CV13) -------------------------------------------------------------------


async def test_another_company_reaches_none_of_this_companys_connections(
    harness: Harness,
) -> None:
    connection = await harness.created("maker")
    before = await harness.row(connection)
    envelopes = await harness.envelopes(connection)
    harness.dependents.asked.clear()

    for method, suffix, kw in (
        ("GET", f"/{connection}", {}),
        ("PATCH", f"/{connection}", {"json": {"secrets": {"api_key": "x"}}}),
        ("DELETE", f"/{connection}", {}),
        ("POST", f"/{connection}/disable", {}),
        ("POST", f"/{connection}/enable", {}),
        ("POST", f"/{connection}/revoke-credentials", {}),
        ("GET", f"/{connection}/dependents", {}),
    ):
        response = await harness.call("other_admin", method, suffix, **kw)
        assert response.status_code == 404, (method, suffix, response.text)
        assert response.json()["code"] == "not_found"

    listed = await harness.call("other_admin", "GET", "")
    assert listed.status_code == 200
    assert str(connection) not in listed.text
    assert await harness.row(connection) == before
    assert await harness.envelopes(connection) == envelopes
    assert harness.dependents.asked == []
    assert await harness.approvals("maker") == 0


# -- R5.18 (CV31) ------------------------------------------------------------------


async def test_reading_takes_connections_read_reaching_the_owning_workspace(
    harness: Harness,
) -> None:
    in_w2 = await harness.created("maker", workspace=harness.second("maker"))
    in_w1 = await harness.created("maker")

    listed = await harness.call("w1_only", "GET", "")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert str(in_w1) in ids and str(in_w2) not in ids
    for suffix in (f"/{in_w2}", f"/{in_w2}/dependents"):
        assert (await harness.call("w1_only", "GET", suffix)).status_code == 404, suffix
    assert (await harness.call("w1_only", "GET", f"/{in_w1}")).status_code == 200


async def test_writing_takes_connections_manage_reaching_the_owning_workspace(
    harness: Harness,
) -> None:
    in_w2 = await harness.created("maker", workspace=harness.second("maker"))
    await harness.call("maker", "POST", f"/{in_w2}/disable")
    before = await harness.row(in_w2)
    envelopes = await harness.envelopes(in_w2)

    for method, suffix, kw in (
        ("PATCH", f"/{in_w2}", {"json": {"secrets": {"api_key": "rotated"}}}),
        ("DELETE", f"/{in_w2}", {}),
        ("POST", f"/{in_w2}/disable", {}),
        ("POST", f"/{in_w2}/enable", {}),
        ("POST", f"/{in_w2}/revoke-credentials", {}),
    ):
        response = await harness.call("reads_all", method, suffix, **kw)
        assert response.status_code == 403, (method, suffix, response.text)
        assert response.json()["code"] == "permission_denied"

    assert await harness.row(in_w2) == before
    assert await harness.envelopes(in_w2) == envelopes
    assert await harness.approvals("maker") == 0
    # Creating in W2's context: 403; in W1's: allowed; at tenant depth: allowed.
    refused = await harness.create("reads_all", workspace=harness.second("reads_all"))
    assert refused.status_code == 403, refused.text
    assert (await harness.create("reads_all")).status_code == 201
    in_w1 = await harness.created("maker")
    assert (
        await harness.call("reads_all", "PATCH", f"/{in_w1}", json={"name": "Đổi tên"})
    ).status_code == 200
    assert (
        await harness.call("maker", "PATCH", f"/{in_w2}", json={"name": "Đổi tên"})
    ).status_code == 200
    # Audited in the connection's workspace, not the caller's working one.
    renamed = await harness.audits("maker", "connection.updated")
    assert [a.workspace_id for a in renamed if a.resource_id == str(in_w2)] == [
        harness.second("maker")
    ]


# -- R5.5 (CV15), disable --------------------------------------------------------


async def test_disabling_is_at_once_and_only_from_active(harness: Harness) -> None:
    connection = await harness.created("maker")

    first = await harness.call("maker", "POST", f"/{connection}/disable")
    disabled_at = (await harness.row(connection)).disabled_at
    again = await harness.call("maker", "POST", f"/{connection}/disable")

    assert first.status_code == 200 and first.json()["status"] == "disabled"
    assert first.json()["disabled_at"] is not None
    assert again.status_code == 409 and _reason(again) == "connection_not_active"
    assert (await harness.row(connection)).disabled_at == disabled_at
    assert len(await harness.audits("maker", "connection.disabled")) == 1


# -- R5.8 --------------------------------------------------------------------------


async def test_a_connection_in_use_is_not_deleted(harness: Harness) -> None:
    connection = await harness.created("maker")
    harness.dependents.answer = ConnectionDependents(
        total=2, visible=(DependentRef("binding_set", uuid.uuid4(), "Bán hàng"),)
    )

    response = await harness.call("maker", "DELETE", f"/{connection}")
    listed = await harness.call("maker", "GET", f"/{connection}/dependents")

    assert response.status_code == 409 and _reason(response) == "connection_in_use"
    assert await harness.row(connection) is not None
    assert listed.status_code == 200
    assert listed.json()["total"] == 2 and listed.json()["visible"][0]["kind"] == "binding_set"


async def test_a_port_that_fails_stops_the_delete(harness: Harness) -> None:
    connection = await harness.created("maker")
    harness.dependents.fails = True

    response = await harness.call("maker", "DELETE", f"/{connection}")

    assert response.status_code == 500
    assert await harness.row(connection) is not None
    assert len(await harness.envelopes(connection)) == 2


async def test_a_connection_nothing_uses_is_deleted_with_its_envelopes(harness: Harness) -> None:
    connection = await harness.created("maker", external_account="xoa@acme.vn")

    response = await harness.call("maker", "DELETE", f"/{connection}")

    assert response.status_code == 204, response.text
    assert await harness.row(connection) is None
    assert await harness.envelopes(connection) == []
    deleted = await harness.audits("maker", "connection.deleted")
    assert [a.resource_id for a in deleted] == [str(connection)]
    assert "xoa@acme.vn" in deleted[0].details


# -- R5.21 (CV21) ------------------------------------------------------------------


async def test_a_disabled_connection_holds_its_account(harness: Harness) -> None:
    connection = await harness.created(
        "maker", connector_key="smtp", external_account="a@x.vn", secrets={"password": CANARY}
    )
    await harness.call("maker", "POST", f"/{connection}/disable")

    for account in ("a@x.vn", "A@X.vn ", " a@x.vn"):
        response = await harness.create(
            "maker", connector_key="smtp", external_account=account, secrets={"password": "p"}
        )
        assert response.status_code == 409, (account, response.text)
        assert _reason(response) == "connection_exists"
    assert (
        await harness.scalar(
            "SELECT count(*) FROM platform.connections WHERE tenant_id = :t",
            t=harness.people["maker"].tenant.tenant_id,
        )
        == 1
    )

    assert (await harness.call("maker", "DELETE", f"/{connection}")).status_code == 204
    again = await harness.create(
        "maker", connector_key="smtp", external_account="a@x.vn", secrets={"password": "p"}
    )
    assert again.status_code == 201, again.text
    assert "a@x.vn" in (await harness.audits("maker", "connection.deleted"))[0].details
    assert "a@x.vn" in (await harness.audits("maker", "connection.created"))[-1].details


# -- R5.10-R5.13, R5.19 (CV21) ------------------------------------------------------


async def test_enabling_opens_a_request_in_the_owning_workspace_and_changes_nothing(
    harness: Harness,
) -> None:
    connection = await harness.created("maker", workspace=harness.second("maker"))
    active = await harness.call("maker", "POST", f"/{connection}/enable")
    assert active.status_code == 409 and _reason(active) == "connection_not_disabled"
    await harness.call("maker", "POST", f"/{connection}/disable")

    response = await harness.call("maker", "POST", f"/{connection}/enable")
    again = await harness.call("maker", "POST", f"/{connection}/enable")

    assert response.status_code == 202, response.text
    approval = response.json()["approval_id"]
    assert response.headers["Location"] == f"/api/v1/approvals/{approval}"
    async with harness.migrator.connect() as conn:
        opened = (
            await conn.execute(
                sa.text(
                    "SELECT approval_type, required_scope, workspace_id, payload, status"
                    " FROM platform.approval_requests WHERE id = :a"
                ),
                {"a": uuid.UUID(approval)},
            )
        ).one()
    assert opened.approval_type == "connections.enable"
    assert opened.required_scope == "connections.manage"
    assert opened.workspace_id == harness.second("maker")
    assert opened.payload == {"connection_id": str(connection)}
    assert (await harness.row(connection)).status == "disabled"
    assert again.status_code == 409 and _reason(again) == "enable_pending"
    assert await harness.approvals("maker") == 1
    detail = await harness.call("maker", "GET", f"/{connection}")
    assert detail.json()["pending_enable_approval_id"] == approval


async def test_a_second_person_enables_and_a_replay_changes_nothing(harness: Harness) -> None:
    """R5.11, R5.12."""
    connection = await harness.created("maker")
    await harness.call("maker", "POST", f"/{connection}/disable")
    approval = (await harness.call("maker", "POST", f"/{connection}/enable")).json()["approval_id"]

    own = await harness.decide("maker", approval)
    not_holding = await harness.decide("decider_only", approval)
    other_workspace = await harness.decide("w2_manager", approval)
    assert own.status_code == 409 and _reason(own) == "second_person_required"
    assert not_holding.status_code == 404, not_holding.text
    assert other_workspace.status_code == 404, other_workspace.text
    assert (await harness.row(connection)).status == "disabled"

    decided = await harness.decide("checker", approval)
    assert decided.status_code == 200, decided.text
    assert await harness.settle("checker", approval) == "enabled"
    assert await harness.settle("checker", approval) == "not_disabled"

    assert (await harness.row(connection)).status == "active"
    enabled = await harness.audits("maker", "connection.enabled")
    assert len(enabled) == 1
    assert enabled[0].actor_id == harness.people["checker"].user
    assert json.loads(enabled[0].details)["lane"] == "outbox"


async def test_a_rejection_enables_nothing(harness: Harness) -> None:
    connection = await harness.created("maker")
    await harness.call("maker", "POST", f"/{connection}/disable")
    approval = (await harness.call("maker", "POST", f"/{connection}/enable")).json()["approval_id"]

    assert (await harness.decide("checker", approval, approve=False)).status_code == 200
    assert await harness.settle("checker", approval) == "rejected"
    assert (await harness.row(connection)).status == "disabled"


async def test_a_request_older_than_the_latest_disable_enables_nothing(harness: Harness) -> None:
    """R5.19: the handler skips it, without an error, before the trigger would refuse."""
    connection = await harness.created("maker")
    await harness.call("maker", "POST", f"/{connection}/disable")
    stale = (await harness.call("maker", "POST", f"/{connection}/enable")).json()["approval_id"]
    # Enabled another way (another approved request), then disabled again at t1.
    other = uuid.uuid4()
    tenant = harness.people["maker"].tenant
    async with harness.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, reason, payload, status, required_scope,"
                " created_at)"
                " VALUES (:id, :t, :w, 'connections.enable', :u, 'đường khác',"
                " jsonb_build_object('connection_id', CAST(:c AS text)), 'approved',"
                " 'connections.manage', clock_timestamp())"
            ),
            {
                "id": other,
                "t": tenant.tenant_id,
                "w": tenant.main,
                "u": harness.people["checker"].user,
                "c": str(connection),
            },
        )
        await conn.execute(
            sa.text("SELECT set_config('app.connection_enable_approval', :a, true)"),
            {"a": str(other)},
        )
        await conn.execute(
            sa.text("UPDATE platform.connections SET status = 'active' WHERE id = :c"),
            {"c": connection},
        )
    await harness.call("maker", "POST", f"/{connection}/disable")

    assert (await harness.decide("checker", stale)).status_code == 200
    assert await harness.settle("checker", stale) == "stale"

    assert (await harness.row(connection)).status == "disabled"
    assert await harness.audits("maker", "connection.enabled") == []


async def test_nobody_but_the_requester_to_decide_opens_nothing(harness: Harness) -> None:
    """R5.13."""
    connection = await harness.created("lonely")
    await harness.call("lonely", "POST", f"/{connection}/disable")

    response = await harness.call("lonely", "POST", f"/{connection}/enable")

    assert response.status_code == 409 and _reason(response) == "no_checker_available"
    assert await harness.approvals("lonely") == 0
    assert (await harness.row(connection)).status == "disabled"
    # A second holder of the key in that workspace: the request opens.
    async with harness.migrator.begin() as conn:
        harness.people["lonely_admin_2"] = await _person(
            conn, harness.people["lonely"].tenant, ADMIN
        )
    opened = await harness.call("lonely", "POST", f"/{connection}/enable")
    assert opened.status_code == 202, opened.text


# -- R1.15 (CV28) ------------------------------------------------------------------


async def test_revoking_for_compromise_is_one_persons_and_at_once(harness: Harness) -> None:
    connection = await harness.created("maker")
    other = await harness.created("maker")
    await harness.call("maker", "PATCH", f"/{connection}", json={"secrets": {"api_key": "v2"}})
    other_envelopes = await harness.envelopes(other)

    response = await harness.call("maker", "POST", f"/{connection}/revoke-credentials")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["compromised_at"] is not None
    assert body["secret_fields"] == [
        {"field": "api_key", "configured": False},
        {"field": "password", "configured": False},
    ]
    row = await harness.row(connection)
    live = {(e.field, e.secret_version): e for e in await harness.envelopes(connection)}
    assert live[("api_key", 2)].revoked_at == row.compromised_at
    assert live[("password", 1)].revoked_at == row.compromised_at
    assert live[("api_key", 2)].replaced_at is None
    assert await harness.envelopes(other) == other_envelopes
    revoked = await harness.audits("maker", "connection.credentials_revoked")
    assert len(revoked) == 1 and CANARY not in revoked[0].details
    assert json.loads(revoked[0].details)["versions_revoked"] == 2


async def test_a_revocation_whose_audit_fails_revokes_nothing(
    harness: Harness, failing_audit: set[str]
) -> None:
    connection = await harness.created("maker")
    failing_audit.add("connection.credentials_revoked")

    response = await harness.call("maker", "POST", f"/{connection}/revoke-credentials")

    assert response.status_code == 500
    assert all(e.revoked_at is None for e in await harness.envelopes(connection))
    assert (await harness.row(connection)).compromised_at is None
