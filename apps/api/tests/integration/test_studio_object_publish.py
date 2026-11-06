"""An object published through the version lifecycle, with the running app's
own kinds (custom-objects ticket 06; R1.2, R1.3, R1.7, R1.8, R2.4; CO3, CO6,
CO23).

The real `object` entry of `platform_kinds(...)`: its comparator
(`compare_object(...).tighten_only`), its submit check against the live
version (`live_incompatible`) and its publish hook (`MetadataService.apply`).
Two people of one company both hold `studio.objects.manage` and
`studio.publish.approve`; no fixture approval: a request is decided at
`POST /approvals/{id}/decisions` and carried out by the handler the worker
registers (`dw_worker.main.register_studio_publish`, its registry built by the
worker's own composition root) on the decision's outbox event.

A freeze is the run controls' answer, swapped on the app's `LifecycleService`
for the test: the switches themselves are agent-lifecycle/01's.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.domain.outbox import OutboxEvent
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_studio.kinds import OBJECTS_MANAGE_SCOPE
from dw_studio.lifecycle.application.publish import PUBLISH_APPROVE_SCOPE
from dw_studio.testing.objects import object_document, object_field
from dw_worker.main import register_studio_publish

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-object-publish-secret-0123456789"
STUDIO = "/api/v1/studio"
DECIDE = {"approvals.decide": "workspace", "approvals.read": "workspace"}
MANAGER = {OBJECTS_MANAGE_SCOPE: "tenant", PUBLISH_APPROVE_SCOPE: "workspace", **DECIDE}
PEOPLE = {
    "author": MANAGER,
    "second": MANAGER,
    "reviewer_only": {PUBLISH_APPROVE_SCOPE: "workspace", **DECIDE},
}


def lead(*extra: dict[str, Any], phone: str = "open", **over: Any) -> dict[str, Any]:
    """A Lead: a phone with no personal data category (so `open` unless the
    version closes it), a currency at scale 0, a note."""
    phone_field = object_field("phone", "phone", indexed=True)
    if phone != "open":
        phone_field["access_mode"] = phone
    return object_document(
        phone_field,
        object_field("amount", "currency", scale=0),
        object_field("note"),
        *extra,
        **over,
    )


class Controls:
    """The run controls' answer, set by a test."""

    def __init__(self) -> None:
        self.state: str | None = None

    async def admission_state(self, tenant_id: uuid.UUID, artifacts: Any = ()) -> str | None:
        return self.state


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    tenant: PlantedTenant
    people: dict[str, uuid.UUID]
    controls: Controls
    handlers: dict[str, Any]

    def headers(self, who: str, **extra: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(f'rbac-{self.people[who]}')}",
            "X-Tenant-Id": str(self.tenant.tenant_id),
            "X-Workspace-Id": str(self.tenant.main),
            **extra,
        }

    async def call(self, who: str, method: str, url: str, **kw: Any) -> httpx.Response:
        return await self.client.request(
            method, url, headers=self.headers(who, **kw.pop("headers", {})), **kw
        )

    async def sql(self, statement: str, **values: Any) -> list[Any]:
        async with self.migrator.begin() as conn:
            result = await conn.execute(sa.text(statement), values)
            return list(result.all()) if result.returns_rows else []

    async def create(self, document: dict[str, Any]) -> tuple[str, str, int]:
        made = await self.call(
            "author",
            "POST",
            f"{STUDIO}/artifacts",
            json={"kind": "object", "api_name": f"o_{uuid.uuid4().hex[:10]}", "document": document},
        )
        assert made.status_code == 201, made.text
        draft = await self.call("author", "GET", f"{STUDIO}/artifacts/{made.json()['id']}/draft")
        return made.json()["id"], draft.json()["id"], draft.json()["version"]

    async def submit(
        self, artifact: str, version: str, etag: int, who: str = "author"
    ) -> httpx.Response:
        return await self.call(
            who,
            "POST",
            f"{STUDIO}/objects/{artifact}/versions/{version}/submit",
            headers={"If-Match": f'"{etag}"'},
        )

    async def new_draft(self, artifact: str, document: dict[str, Any]) -> tuple[str, int]:
        """A draft after the live version, saved with ``document``."""
        etag = (await self.call("author", "GET", f"{STUDIO}/artifacts/{artifact}")).json()[
            "version"
        ]
        made = await self.call(
            "author",
            "POST",
            f"{STUDIO}/artifacts/{artifact}/draft",
            headers={"If-Match": f'"{etag}"'},
        )
        assert made.status_code == 201, made.text
        return made.json()["id"], await self.save(artifact, made.json()["version"], document)

    async def save(self, artifact: str, etag: int, document: dict[str, Any]) -> int:
        saved = await self.call(
            "author",
            "PUT",
            f"{STUDIO}/artifacts/{artifact}/draft",
            json={"document": document},
            headers={"If-Match": f'"{etag}"'},
        )
        assert saved.status_code == 200, saved.text
        return int(saved.json()["version"])

    async def approval_of(self, version: str) -> str:
        [(approval,)] = await self.sql(
            "SELECT publish_approval_id FROM studio.artifact_versions WHERE id = :v",
            v=uuid.UUID(version),
        )
        return str(approval)

    async def decide(self, who: str, approval: str, *, approve: bool = True) -> httpx.Response:
        return await self.call(
            who,
            "POST",
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": approve, "comment": "đã xem"},
        )

    async def on_worker(self, approval: str) -> str:
        """The decision's outbox event, through the worker's own handler."""
        [(event_id, event_type, workspace, payload, at)] = await self.sql(
            "SELECT id, event_type, workspace_id, payload, occurred_at FROM platform.outbox_events"
            " WHERE aggregate_id = :a AND event_type LIKE 'studio.publish.%'",
            a=uuid.UUID(approval),
        )
        event = OutboxEvent(
            id=event_id,
            tenant_id=TenantId(self.tenant.tenant_id),
            workspace_id=WorkspaceId(workspace),
            event_type=event_type,
            schema_version="1.0",
            aggregate_id=uuid.UUID(approval),
            occurred_at=at,
            payload=payload,
        )
        result: str = await self.handlers[event_type](event)
        return result

    async def stage(self, version: str) -> str:
        [(stage,)] = await self.sql(
            "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=uuid.UUID(version)
        )
        return str(stage)

    async def fields(self, artifact: str) -> dict[str, str]:
        rows = await self.sql(
            "SELECT f.api_name, f.access_mode FROM studio.field_defs f"
            " JOIN studio.object_defs o ON o.id = f.object_id AND o.tenant_id = f.tenant_id"
            " WHERE o.id = :a",
            a=uuid.UUID(artifact),
        )
        return {r.api_name: r.access_mode for r in rows}

    async def audits(self, action: str, artifact: str) -> list[Any]:
        return await self.sql(
            "SELECT actor_id, details FROM platform.audit_events WHERE tenant_id = :t"
            " AND action = :a AND (resource_id = :r OR details->>'object_id' = :r)"
            " ORDER BY occurred_at",
            t=self.tenant.tenant_id,
            a=action,
            r=artifact,
        )

    @contextmanager
    def frozen(self, state: str) -> Iterator[None]:
        self.controls.state = state
        try:
            yield
        finally:
            self.controls.state = None

    async def live_object(self, document: dict[str, Any]) -> str:
        """An object whose first version went live through a second person."""
        artifact, version, etag = await self.create(document)
        submitted = await self.submit(artifact, version, etag)
        assert submitted.status_code == 202 and submitted.json()["stage"] == "awaiting_approval"
        approval = await self.approval_of(version)
        assert (await self.decide("second", approval)).status_code == 200
        assert await self.on_worker(approval) == "studio publish published"
        return artifact


def reason(answer: httpx.Response) -> str | None:
    found = answer.json().get("details", {}).get("reason_code")
    return None if found is None else str(found)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    app_engine = create_async_engine(api_db.app, poolclass=NullPool)
    sessions = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    people: dict[str, uuid.UUID] = {}
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn)
        for name, keys in PEOPLE.items():
            user = await plant_person(conn, tenant.tenant_id)
            membership = await plant_membership(conn, tenant.tenant_id, tenant.main, user)
            role = await plant_role(conn, tenant.tenant_id, f"op_{user.hex[:12]}", keys)
            await assign(conn, tenant.tenant_id, tenant.main, membership, role)
            people[name] = user
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            s3_endpoint_url="http://127.0.0.1:19000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    assert container.engine is not None and container.studio is not None
    controls = Controls()
    container.studio.lifecycle.control = controls  # type: ignore[misc]
    handlers: dict[str, Any] = {}
    register_studio_publish(
        handlers, sessions, run_control=OpenRunControl(), clock=SystemClock(), ids=Uuid4Generator()
    )
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                yield Api(client, container, migrator, sessions, tenant, people, controls, handlers)
    finally:
        await container.engine.dispose()
        await app_engine.dispose()
        await migrator.dispose()


# ---- R1.2 (CO23): a widening version goes through a second person ----------------


async def test_r1_2_a_new_field_waits_for_a_second_person_and_goes_live_on_the_worker(
    api: Api,
) -> None:
    artifact = await api.live_object(lead())
    version, etag = await api.new_draft(artifact, lead(object_field("city")))

    submitted = await api.submit(artifact, version, etag)

    assert submitted.status_code == 202 and submitted.json()["stage"] == "awaiting_approval"
    approval = await api.approval_of(version)
    [(payload,)] = await api.sql(
        "SELECT payload FROM platform.approval_requests WHERE id = :a", a=uuid.UUID(approval)
    )
    assert str(api.people["author"]) in payload["author_ids"]
    assert "city" not in await api.fields(artifact)
    assert (await api.decide("second", approval)).status_code == 200
    assert await api.on_worker(approval) == "studio publish published"
    assert await api.stage(version) == "live"
    assert "city" in await api.fields(artifact)
    published = await api.audits("studio.version.published", artifact)
    mine = [row for row in published if row.details["version_id"] == version]
    assert [(row.actor_id, row.details["path"]) for row in mine] == [
        (api.people["second"], "approved")
    ]
    created = await api.audits("studio.field.created", artifact)
    city = [row for row in created if row.details.get("api_name") == "city"]
    assert [(row.actor_id, row.details.get("lane")) for row in city] == [
        (api.people["second"], "outbox")
    ]


async def test_r1_2_a_rejected_version_goes_back_to_draft_and_changes_nothing(api: Api) -> None:
    artifact = await api.live_object(lead())
    version, etag = await api.new_draft(artifact, lead(object_field("city")))
    assert (await api.submit(artifact, version, etag)).status_code == 202
    approval = await api.approval_of(version)

    assert (await api.decide("second", approval, approve=False)).status_code == 200

    assert await api.on_worker(approval) == "studio publish rejected"
    assert await api.stage(version) == "draft"
    assert "city" not in await api.fields(artifact)


async def test_r1_2_the_submitter_deciding_their_own_request_is_refused(api: Api) -> None:
    artifact = await api.live_object(lead())
    version, etag = await api.new_draft(artifact, lead(object_field("city")))
    assert (await api.submit(artifact, version, etag)).status_code == 202
    approval = await api.approval_of(version)

    refused = await api.decide("author", approval)

    assert (refused.status_code, reason(refused)) == (409, "second_person_required")
    assert await api.stage(version) == "awaiting_approval"
    assert "city" not in await api.fields(artifact)


@pytest.mark.parametrize(
    "change",
    ["open_a_basic_field", "ai_description", "identical", "reordered", "mixed"],
)
async def test_r1_2_r1_8_a_version_that_does_not_only_tighten_waits(api: Api, change: str) -> None:
    def email(**over: Any) -> dict[str, Any]:
        return object_field("email", "email", pd_category="basic", **over)

    # `email` holds basic personal data: secured since it was published.
    artifact = await api.live_object(lead(email()))
    document = {
        "open_a_basic_field": lead(email(access_mode="open")),
        "ai_description": lead(email(), ai_description="Khách hàng mới"),
        "identical": lead(email()),
        "reordered": object_document(
            email(),
            object_field("note"),
            object_field("amount", "currency", scale=0),
            object_field("phone", "phone", indexed=True),
        ),
        # Closes `phone` and changes a label: not only tightening.
        "mixed": lead(email(), phone="secured", labels={"vi": "Khách hàng"}),
    }[change]
    version, etag = await api.new_draft(artifact, document)
    submitted = await api.submit(artifact, version, etag)
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["stage"] == "awaiting_approval"


# ---- R1.7 (CO23): a version that only tightens goes live on its submit ------------


async def test_r1_7_closing_phone_goes_live_in_the_submitters_transaction(api: Api) -> None:
    artifact = await api.live_object(lead())
    [(live_hash,)] = await api.sql(
        "SELECT definition_hash FROM studio.artifact_versions WHERE artifact_id = :a"
        " AND stage = 'live'",
        a=uuid.UUID(artifact),
    )
    version, etag = await api.new_draft(artifact, lead(phone="secured"))

    submitted = await api.submit(artifact, version, etag)

    assert submitted.status_code == 202 and submitted.json()["stage"] == "live"
    [(tighten, compared, approval)] = await api.sql(
        "SELECT tighten_only, compared_live_hash, publish_approval_id"
        " FROM studio.artifact_versions WHERE id = :v",
        v=uuid.UUID(version),
    )
    assert (tighten, compared, approval) == (True, live_hash, None)
    assert (await api.fields(artifact))["phone"] == "secured"
    published = [
        row
        for row in await api.audits("studio.version.published", artifact)
        if row.details["version_id"] == version
    ]
    assert [(r.actor_id, r.details["path"]) for r in published] == [
        (api.people["author"], "tighten_only")
    ]
    updated = await api.audits("studio.field.updated", artifact)
    phone = [row for row in updated if row.details.get("api_name") == "phone"]
    assert [(r.actor_id, "lane" in r.details) for r in phone] == [(api.people["author"], False)]


async def test_r1_7_narrowing_default_access_goes_live_on_its_submit(api: Api) -> None:
    artifact = await api.live_object(lead(default_access="public_read"))
    version, etag = await api.new_draft(artifact, lead(default_access="private"))
    submitted = await api.submit(artifact, version, etag)
    assert submitted.status_code == 202 and submitted.json()["stage"] == "live"


async def test_r1_7_a_company_freeze_lets_only_tightening_through(api: Api) -> None:
    artifact = await api.live_object(lead())
    widening, wide_etag = await api.new_draft(artifact, lead(object_field("city")))
    with api.frozen("tenant_frozen"):
        refused = await api.submit(artifact, widening, wide_etag)
    assert (refused.status_code, reason(refused)) == (409, "tenant_frozen")
    assert await api.stage(widening) == "draft"
    etag = await api.save(
        artifact,
        (await api.call("author", "GET", f"{STUDIO}/artifacts/{artifact}/draft")).json()["version"],
        lead(phone="secured"),
    )
    with api.frozen("tenant_frozen"):
        through = await api.submit(artifact, widening, etag)
    assert through.status_code == 202 and through.json()["stage"] == "live"


async def test_r1_7_a_platform_freeze_stops_even_tightening(api: Api) -> None:
    artifact = await api.live_object(lead())
    version, etag = await api.new_draft(artifact, lead(phone="secured"))
    with api.frozen("platform_frozen"):
        refused = await api.submit(artifact, version, etag)
    assert (refused.status_code, reason(refused)) == (409, "platform_frozen")
    assert await api.stage(version) == "draft"


# ---- V4.17: one candidate at a time ---------------------------------------------


async def test_r1_2_v4_17_a_waiting_candidate_is_withdrawn_then_tightened(api: Api) -> None:
    artifact = await api.live_object(lead())
    version, etag = await api.new_draft(artifact, lead(object_field("city")))
    assert (await api.submit(artifact, version, etag)).status_code == 202
    approval = await api.approval_of(version)
    before = await api.sql(
        "SELECT count(*) FROM studio.artifact_versions WHERE artifact_id = :a",
        a=uuid.UUID(artifact),
    )
    current = (await api.call("author", "GET", f"{STUDIO}/artifacts/{artifact}")).json()["version"]

    refused = await api.call(
        "author",
        "POST",
        f"{STUDIO}/artifacts/{artifact}/draft",
        headers={"If-Match": f'"{current}"'},
    )

    assert (refused.status_code, reason(refused)) == (409, "candidate_pending")
    assert before == await api.sql(
        "SELECT count(*) FROM studio.artifact_versions WHERE artifact_id = :a",
        a=uuid.UUID(artifact),
    )
    assert await api.stage(version) == "awaiting_approval"
    assert "city" not in await api.fields(artifact)

    withdrawn = await api.call(
        "author", "POST", f"{STUDIO}/objects/{artifact}/versions/{version}/withdraw"
    )
    assert withdrawn.status_code == 200, withdrawn.text
    draft = (await api.call("author", "GET", f"{STUDIO}/artifacts/{artifact}/draft")).json()
    etag = await api.save(artifact, draft["version"], lead(phone="secured"))
    tightened = await api.submit(artifact, draft["id"], etag)
    assert tightened.status_code == 202 and tightened.json()["stage"] == "live"
    [(status,)] = await api.sql(
        "SELECT status FROM platform.approval_requests WHERE id = :a", a=uuid.UUID(approval)
    )
    assert status in ("cancelled", "withdrawn")


# ---- R1.3 (CO3): the submit key is the read key ---------------------------------


async def test_r1_3_without_the_object_key_the_submit_is_not_found(api: Api) -> None:
    artifact, version, etag = await api.create(lead())
    refused = await api.submit(artifact, version, etag, who="reviewer_only")
    assert refused.status_code == 404
    assert await api.stage(version) == "draft"
    assert await api.sql(
        "SELECT count(*) FROM platform.approval_requests WHERE payload->>'version_id' = :v",
        v=version,
    ) == [(0,)]


# ---- R2.4 (CO6): a version that breaks the live one is refused at submit --------


async def test_r2_4_dropping_and_changing_published_fields_is_refused_before_approval(
    api: Api,
) -> None:
    artifact = await api.live_object(lead())
    broken = object_document(
        object_field("phone", "phone", indexed=True),
        object_field("amount", "currency", scale=2),
    )
    version, etag = await api.new_draft(artifact, broken)

    refused = await api.submit(artifact, version, etag)

    body = refused.json()
    assert (refused.status_code, body["code"], reason(refused)) == (
        422,
        "validation_failed",
        "live_incompatible",
    ), refused.text
    errors = sorted((e["pointer"], e["code"]) for e in body["errors"])
    # `amount` is the second field of the version: its `scale` changed.
    assert errors == [("/fields", "field_removed"), ("/fields/1/scale", "field_immutable")]
    removed = next(e for e in body["errors"] if e["code"] == "field_removed")
    assert "note" in removed["detail"]
    assert await api.stage(version) == "draft"
    assert await api.sql(
        "SELECT count(*) FROM platform.approval_requests WHERE payload->>'version_id' = :v",
        v=version,
    ) == [(0,)]


async def test_gate_g_the_hook_refuses_a_definition_that_is_not_the_compared_live_one(
    api: Api,
) -> None:
    """The comparator, the check and the hook judge against one live version:
    a definition applied from another (here the first, put back by the
    migrator) is refused at the hook and the tightening submit changes nothing."""
    artifact = await api.live_object(lead(default_access="public_read"))
    [(first,)] = await api.sql(
        "SELECT id FROM studio.artifact_versions WHERE artifact_id = :a AND stage = 'live'",
        a=uuid.UUID(artifact),
    )
    version, etag = await api.new_draft(
        artifact, lead(phone="secured", default_access="public_read")
    )
    assert (await api.submit(artifact, version, etag)).json()["stage"] == "live"
    await api.sql(
        "UPDATE studio.object_defs SET applied_version_id = :v WHERE id = :a",
        v=first,
        a=uuid.UUID(artifact),
    )
    narrower, etag = await api.new_draft(artifact, lead(phone="secured", default_access="private"))

    refused = await api.submit(artifact, narrower, etag)

    assert (refused.status_code, reason(refused)) == (409, "base_changed"), refused.text
    assert await api.stage(narrower) == "draft"
    assert (await api.fields(artifact))["phone"] == "secured"
