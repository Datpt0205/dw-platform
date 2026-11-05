"""Two-person publication over HTTP, against Postgres (agent-lifecycle ticket
04: R2.8, R5.1-R5.5, R5.8, R5.11, R5.12; AL5, AL6, AL25, AL36).

The real app and container, the runtime wired (so the approval flow is the
one `bootstrap.runtime` builds, its `studio.publish.` prefix strict from
`wiring.py` and its guards from `build_studio`), with the test kinds: `object`
registered with the real kind's key (`studio.objects.manage`, tenant depth), a
fake comparator and a hook that does nothing, beside the fixture kinds. The
segments are the running app's (`SUBMIT_SEGMENTS`), so `objects` names the
test `object` and `data-sources` the `endpoint` kind no one registered yet. A
decision is made at `POST /approvals/{id}/decisions` and carried out by
`PublishSettler`, as the worker does with the decision's outbox event.
"""

from __future__ import annotations

import json
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
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.kinds import OBJECTS_MANAGE_SCOPE
from dw_studio.lifecycle.application.publish import PUBLISH_APPROVE_SCOPE, PUBLISH_PREFIX
from dw_studio.lifecycle.application.review import PublishSettler
from dw_studio.testing.fixture_kinds import (
    FIXTURE,
    FIXTURE_GATELESS,
    FIXTURE_READ,
    FIXTURE_SUBMIT,
    FIXTURE_WRITE,
    extract_fixture,
    planted_fixture_kinds,
    validate_fixture,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-publish-secret-0123456789abcdef"
STUDIO = "/api/v1/studio"
COMMENT = "đã xem bản ứng viên"


async def _no_hook(_tx: Any, _version_id: uuid.UUID) -> None:
    return None


API_OBJECT = ArtifactKindEntry(
    kind="object",
    document_schema="dw.fixture/v1",
    read_key=OBJECTS_MANAGE_SCOPE,
    write_key=OBJECTS_MANAGE_SCOPE,
    submit_key=OBJECTS_MANAGE_SCOPE,
    publish_hook=_no_hook,
    validate=validate_fixture,
    extract=extract_fixture,
    compare=lambda _live, doc: isinstance(doc, dict) and doc.get("tighten") is True,
)
KINDS = (FIXTURE, FIXTURE_GATELESS, API_OBJECT)

DECIDE = {"approvals.decide": "workspace", "approvals.read": "workspace"}
STAMP = {PUBLISH_APPROVE_SCOPE: "workspace"}
OBJECTS = {OBJECTS_MANAGE_SCOPE: "tenant"}
PEOPLE: dict[str, dict[str, str]] = {
    # writes and submits, may decide and holds the stamp: refused as the requester.
    "author": {**OBJECTS, **DECIDE, **STAMP},
    # saves the draft, may decide and holds the stamp: refused as an author.
    "co_author": {**OBJECTS, **DECIDE, **STAMP},
    # writes and submits, no stamp: reads their own request, cannot decide it.
    "plain_author": {**OBJECTS, "approvals.read": "workspace"},
    # decides, holds the stamp, no author key, may also decide an unfreeze.
    "approver": {**DECIDE, **STAMP, "studio.lifecycle.freeze": "tenant"},
    # the author key and `approvals.decide`, no stamp.
    "key_only": {**OBJECTS, **DECIDE},
    # `platform_admin` by its membership, no stamp.
    "admin": {"approvals.read": "workspace"},
    # a member with neither key.
    "nobody": {"approvals.read": "workspace"},
    # writes a `fixture_gateless` artifact.
    "fixture_writer": {
        FIXTURE_READ: "workspace",
        FIXTURE_WRITE: "workspace",
        FIXTURE_SUBMIT: "workspace",
    },
}


@dataclass(frozen=True)
class Who:
    tenant: PlantedTenant
    user: uuid.UUID


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    people: dict[str, Who]

    def headers(self, who: str, **extra: str) -> dict[str, str]:
        person = self.people[who]
        return {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(f'rbac-{person.user}')}",
            "X-Tenant-Id": str(person.tenant.tenant_id),
            "X-Workspace-Id": str(person.tenant.main),
            **extra,
        }

    async def call(self, who: str, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = self.headers(who, **kw.pop("headers", {}))
        return await self.client.request(method, url, headers=headers, **kw)

    async def sql(self, statement: str, **values: Any) -> list[Any]:
        async with self.migrator.begin() as conn:
            result = await conn.execute(sa.text(statement), values)
            return list(result.all()) if result.returns_rows else []

    async def create(self, who: str, kind: str = "object", **doc: Any) -> tuple[str, str, int]:
        answer = await self.call(
            who,
            "POST",
            f"{STUDIO}/artifacts",
            json={
                "kind": kind,
                "api_name": f"a_{uuid.uuid4().hex[:12]}",
                "document": {"title": "Khách hàng", **doc},
            },
        )
        assert answer.status_code == 201, answer.text
        artifact_id = answer.json()["id"]
        draft = await self.call(who, "GET", f"{STUDIO}/artifacts/{artifact_id}/draft")
        return artifact_id, draft.json()["id"], draft.json()["version"]

    async def save(self, who: str, artifact_id: str, etag: int, **doc: Any) -> int:
        saved = await self.call(
            who,
            "PUT",
            f"{STUDIO}/artifacts/{artifact_id}/draft",
            json={"document": {"title": "Khách hàng", **doc}},
            headers={"If-Match": f'"{etag}"'},
        )
        assert saved.status_code == 200, saved.text
        return int(saved.json()["version"])

    async def submit(
        self, who: str, artifact_id: str, version_id: str, etag: int, segment: str = "objects"
    ) -> httpx.Response:
        return await self.call(
            who,
            "POST",
            f"{STUDIO}/{segment}/{artifact_id}/versions/{version_id}/submit",
            headers={"If-Match": f'"{etag}"'},
        )

    async def candidate_request(self, submitter: str = "author") -> tuple[str, str, str]:
        """An object written by `submitter` and `co_author`, submitted with
        no live version, waiting: (artifact, version, request)."""
        artifact_id, version_id, etag = await self.create(submitter)
        etag = await self.save("co_author", artifact_id, etag, note="đã sửa")
        answer = await self.submit(submitter, artifact_id, version_id, etag)
        assert answer.status_code == 202, answer.text
        assert answer.json()["stage"] == "awaiting_approval"
        [(approval,)] = await self.sql(
            "SELECT publish_approval_id FROM studio.artifact_versions WHERE id = :v",
            v=uuid.UUID(version_id),
        )
        return artifact_id, version_id, str(approval)

    async def decide(self, who: str, approval: str, *, approve: bool = True) -> httpx.Response:
        return await self.call(
            who,
            "POST",
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": approve, "comment": COMMENT},
        )

    async def candidate(self, who: str, approval: str) -> httpx.Response:
        return await self.call(who, "GET", f"{STUDIO}/publish-approvals/{approval}/candidate")

    async def audits(self, action: str, tenant: uuid.UUID | None = None) -> int:
        found = await self.sql(
            "SELECT count(*) FROM platform.audit_events WHERE tenant_id = :t AND action = :a",
            t=tenant or self.people["author"].tenant.tenant_id,
            a=action,
        )
        return int(found[0][0])

    async def settle(self, approval: str) -> str:
        """What the worker does with the decision's outbox event."""
        [(event_type, tenant_id, payload)] = await self.sql(
            "SELECT event_type, tenant_id, payload FROM platform.outbox_events"
            " WHERE aggregate_id = :a AND event_type LIKE 'studio.publish.%'",
            a=uuid.UUID(approval),
        )
        assert event_type == "studio.publish.object.decided"
        assert self.container.studio is not None
        return await PublishSettler(self.container.studio.lifecycle).settle(
            tenant_id, uuid.UUID(payload["approval_id"])
        )


def reason(answer: httpx.Response) -> str | None:
    found = answer.json().get("details", {}).get("reason_code")
    return None if found is None else str(found)


async def _plant(
    conn: Any, tenant: PlantedTenant, keys: dict[str, str]
) -> tuple[uuid.UUID, uuid.UUID]:
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, tenant.main, user)
    role = await plant_role(conn, tenant.tenant_id, f"pub_{user.hex[:12]}", keys)
    await assign(conn, tenant.tenant_id, tenant.main, membership, role)
    return user, membership


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with planted_fixture_kinds(migrator):
        people: dict[str, Who] = {}
        async with migrator.begin() as conn:
            tenant, other = await plant_tenant(conn), await plant_tenant(conn)
            for name, keys in PEOPLE.items():
                user, membership = await _plant(conn, tenant, keys)
                people[name] = Who(tenant, user)
                if name == "admin":
                    await conn.execute(
                        sa.text(
                            "UPDATE platform.memberships"
                            " SET role_keys = role_keys || '[\"platform_admin\"]' WHERE id = :m"
                        ),
                        {"m": membership},
                    )
            for name, keys in {"outsider": {**OBJECTS, **DECIDE, **STAMP}}.items():
                user, _ = await _plant(conn, other, keys)
                people[name] = Who(other, user)
        container = build_container(
            ApiSettings(
                profile="test",
                database_url=api_db.app,
                dev_secret=SECRET,
                s3_endpoint_url="http://127.0.0.1:19000",
                s3_access_key="placeholder",
                s3_secret_key="placeholder",
                model_provider="mock",
            ),
            studio_kinds=KINDS,
        )
        assert container.engine is not None and container.approval_flow is not None
        app = create_app(container)
        try:
            async with LifespanManager(app):
                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    yield Api(client, container, migrator, people)
        finally:
            await container.engine.dispose()
        # The planted kinds' cleanup deletes the company's versions; their
        # publish requests and the `object` rows go with the company's own.
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
                {"t": tenant.tenant_id},
            )
            for statement in (
                "DELETE FROM studio.dependencies WHERE tenant_id = :t",
                "DELETE FROM studio.artifact_versions WHERE tenant_id = :t",
                "DELETE FROM studio.artifacts WHERE tenant_id = :t",
                "DELETE FROM studio.definition_manifests WHERE tenant_id = :t",
            ):
                await conn.execute(sa.text(statement), {"t": tenant.tenant_id})
    await migrator.dispose()


# ========================================================== the startup ==


async def test_the_api_decides_every_kind_under_the_guard_and_the_strict_prefix(
    api: Api,
) -> None:
    """Step 2: one guard per kind of the registry, by a loop, never a list."""
    flow = api.container.approval_flow
    assert flow is not None and api.container.studio is not None
    assert PUBLISH_PREFIX in flow.strict_approval_prefixes
    kinds = api.container.studio.kinds.kinds
    assert kinds == {"fixture", "fixture_gateless", "object"}
    assert {k for k in flow.decision_guards if k.startswith(PUBLISH_PREFIX)} == {
        f"studio.publish.{kind}" for kind in kinds
    }


# ========================================== R5.1-R5.5: deciding the request ==


async def test_r5_1_r2_11_the_202_carries_the_request_and_no_unset_binding(api: Api) -> None:
    artifact_id, version_id, etag = await api.create("author")
    answer = await api.submit("author", artifact_id, version_id, etag)
    assert answer.status_code == 202, answer.text
    body = answer.json()
    assert (body["stage"], body["binding_unset"]) == ("awaiting_approval", [])
    [request] = await api.sql(
        "SELECT r.approval_type, r.requested_by, r.required_scope, r.payload"
        " FROM platform.approval_requests r JOIN studio.artifact_versions v"
        " ON v.publish_approval_id = r.id WHERE v.id = :v",
        v=uuid.UUID(version_id),
    )
    assert (request.approval_type, request.requested_by, request.required_scope) == (
        "studio.publish.object",
        api.people["author"].user,
        PUBLISH_APPROVE_SCOPE,
    )
    assert request.payload["author_ids"] == [str(api.people["author"].user)]


async def test_r5_2_the_submitter_needs_a_second_person_and_an_author_is_refused(
    api: Api,
) -> None:
    """AL5: the strict prefix runs before the guard: the submitter meets
    `second_person_required`, a contributor who is not the requester
    `author_cannot_approve`; the request stays pending."""
    _, version_id, approval = await api.candidate_request()

    own = await api.decide("author", approval)
    assert (own.status_code, own.json()["type"]) == (409, "urn:dw:problem:conflict")
    assert reason(own) == "second_person_required"
    contributor = await api.decide("co_author", approval)
    assert (contributor.status_code, reason(contributor)) == (409, "author_cannot_approve")

    [(status,)] = await api.sql(
        "SELECT status FROM platform.approval_requests WHERE id = :a", a=uuid.UUID(approval)
    )
    [(stage,)] = await api.sql(
        "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=uuid.UUID(version_id)
    )
    assert (status, stage) == ("pending", "awaiting_approval")


async def test_r5_3_a_request_without_its_authors_is_not_decided(api: Api) -> None:
    _, _, approval = await api.candidate_request()
    await api.sql(
        "UPDATE platform.approval_requests SET payload = payload - 'author_ids' WHERE id = :a",
        a=uuid.UUID(approval),
    )
    refused = await api.decide("approver", approval)
    assert (refused.status_code, reason(refused)) == (409, "author_ids_missing")


async def test_r5_3_a_contributor_with_the_stamp_does_not_read_the_candidate(api: Api) -> None:
    _, _, approval = await api.candidate_request()
    before = await api.audits("studio.version.candidate_read")
    answer = await api.candidate("co_author", approval)
    assert answer.status_code == 404
    assert await api.audits("studio.version.candidate_read") == before


async def test_r5_4_platform_admin_without_the_stamp_neither_reads_nor_decides(
    api: Api,
) -> None:
    """AL6: no role stands in for the stamp, `platform_admin` included."""
    _, _, approval = await api.candidate_request()
    read = await api.call("admin", "GET", f"/api/v1/approvals/{approval}")
    decide = await api.decide("admin", approval)
    assert (read.status_code, decide.status_code) == (404, 404)


async def test_r5_8_the_submitter_without_the_stamp_reads_their_own_request(api: Api) -> None:
    """AL6: 200 with `can_decide` false, through `ApprovalAudience`."""
    _, _, approval = await api.candidate_request("plain_author")
    answer = await api.call("plain_author", "GET", f"/api/v1/approvals/{approval}")
    assert answer.status_code == 200, answer.text
    assert answer.json()["can_decide"] is False


async def test_r5_5_approved_at_the_door_and_settled_goes_live(api: Api) -> None:
    artifact_id, version_id, approval = await api.candidate_request()
    decided = await api.decide("approver", approval)
    assert decided.status_code == 200, decided.text
    assert await api.settle(approval) == "published"
    [(stage, published_by)] = await api.sql(
        "SELECT stage, published_by FROM studio.artifact_versions WHERE id = :v",
        v=uuid.UUID(version_id),
    )
    assert (stage, published_by) == ("live", api.people["approver"].user)
    [details] = [
        row.details
        for row in await api.sql(
            "SELECT details FROM platform.audit_events WHERE resource_id = :a"
            " AND action = 'studio.version.published'",
            a=artifact_id,
        )
    ]
    assert (details["path"], details["lane"]) == ("approved", "outbox")


async def test_r2_8_a_tighten_only_object_goes_live_on_submit(api: Api) -> None:
    artifact_id, version_id, approval = await api.candidate_request()
    assert (await api.decide("approver", approval)).status_code == 200
    assert await api.settle(approval) == "published"
    draft = await api.call(
        "author",
        "POST",
        f"{STUDIO}/artifacts/{artifact_id}/draft",
        headers={"If-Match": f'"{await _artifact_etag(api, artifact_id)}"'},
    )
    assert draft.status_code in (200, 201), draft.text
    etag = await api.save("author", artifact_id, draft.json()["version"], tighten=True)
    answer = await api.submit("author", artifact_id, draft.json()["id"], etag)
    assert answer.status_code == 202, answer.text
    assert (answer.json()["stage"], answer.json()["binding_unset"]) == ("live", [])
    [(old,)] = await api.sql(
        "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=uuid.UUID(version_id)
    )
    assert old == "retired"


async def _artifact_etag(api: Api, artifact_id: str) -> int:
    [(row_version,)] = await api.sql(
        "SELECT row_version FROM studio.artifacts WHERE id = :a", a=uuid.UUID(artifact_id)
    )
    return int(row_version)


# ============================================ R5.11, R5.12: the candidate ==


async def test_r5_11_the_decider_reads_the_candidate_and_what_it_changes(api: Api) -> None:
    """AL25: the stamp and `approvals.decide`, no author key: the sealed
    document, every field an `add` against no live version, one audit."""
    artifact_id, version_id, approval = await api.candidate_request()
    before = await api.audits("studio.version.candidate_read")

    answer = await api.candidate("approver", approval)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["approval_id"], body["version_id"], body["artifact_id"]) == (
        approval,
        version_id,
        artifact_id,
    )
    assert (body["kind"], body["version_no"], body["live_version_id"]) == ("object", 1, None)
    assert body["document"]["note"] == "đã sửa"
    assert body["definition_hash"].startswith("sha256:")
    assert {c["path"] for c in body["changes"]} == {f"/{k}" for k in body["document"]}
    assert {c["op"] for c in body["changes"]} == {"add"}
    assert await api.audits("studio.version.candidate_read") == before + 1
    [details] = [
        row.details
        for row in await api.sql(
            "SELECT details FROM platform.audit_events WHERE resource_id = :a"
            " AND action = 'studio.version.candidate_read'",
            a=artifact_id,
        )
    ]
    assert details == {"approval_id": approval, "version_id": version_id}


async def test_r5_11_changes_against_the_version_it_was_compared_with(api: Api) -> None:
    artifact_id, v1, approval = await api.candidate_request()
    assert (await api.decide("approver", approval)).status_code == 200
    assert await api.settle(approval) == "published"
    draft = await api.call(
        "author",
        "POST",
        f"{STUDIO}/artifacts/{artifact_id}/draft",
        headers={"If-Match": f'"{await _artifact_etag(api, artifact_id)}"'},
    )
    etag = await api.save("author", artifact_id, draft.json()["version"], note="lần hai")
    assert (await api.submit("author", artifact_id, draft.json()["id"], etag)).status_code == 202
    [(second,)] = await api.sql(
        "SELECT publish_approval_id FROM studio.artifact_versions WHERE id = :v",
        v=uuid.UUID(draft.json()["id"]),
    )

    body = (await api.candidate("approver", str(second))).json()
    assert body["live_version_id"] == v1
    assert body["changes"] == [
        {"path": "/note", "op": "replace", "before": "đã sửa", "after": "lần hai"}
    ]


@pytest.mark.parametrize("who", ["author", "plain_author", "key_only", "admin", "outsider"])
async def test_r5_12_no_one_who_may_not_decide_reads_it(api: Api, who: str) -> None:
    """AL25: the requester (with or without the stamp), the author key
    alone, `platform_admin` without the stamp, another company: 404 as an
    id that does not exist, nothing audited."""
    submitter = "plain_author" if who == "plain_author" else "author"
    _, _, approval = await api.candidate_request(submitter)
    tenant = api.people[who].tenant.tenant_id
    before = await api.audits("studio.version.candidate_read", tenant)
    answer = await api.candidate(who, approval)
    unknown = await api.candidate(who, str(uuid.uuid4()))
    assert (answer.status_code, unknown.status_code) == (404, 404)
    assert answer.json()["type"] == unknown.json()["type"]
    assert await api.audits("studio.version.candidate_read", tenant) == before


@pytest.mark.parametrize("approve", [True, False])
async def test_r5_12_a_decided_request_is_not_read(api: Api, approve: bool) -> None:
    _, _, approval = await api.candidate_request()
    assert (await api.decide("approver", approval, approve=approve)).status_code == 200
    assert (await api.candidate("approver", approval)).status_code == 404


async def test_r5_12_another_kind_of_request_is_not_read(api: Api) -> None:
    """A pending `studio.lifecycle.unfreeze` its reader may decide (decide
    and `studio.lifecycle.freeze`): 404 from the type, not the stamp."""
    approval = uuid.uuid4()
    person = api.people["author"]
    await api.sql(
        "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id, approval_type,"
        " requested_by, reason, payload, required_scope, status)"
        " VALUES (:id, :t, :w, 'studio.lifecycle.unfreeze', :by, 'studio.lifecycle.unfreeze',"
        " CAST(:p AS jsonb), 'studio.lifecycle.freeze', 'pending')",
        id=approval,
        t=person.tenant.tenant_id,
        w=person.tenant.main,
        by=person.user,
        p=json.dumps({"switch_id": str(uuid.uuid4()), "author_ids": [str(person.user)]}),
    )
    seen = await api.call("approver", "GET", f"/api/v1/approvals/{approval}")
    assert seen.status_code == 200 and seen.json()["can_decide"] is True
    assert (await api.candidate("approver", str(approval))).status_code == 404

    # A version naming a request of another type: only the type check is
    # left between the reader and the candidate (found by mutation, 5/11/2026).
    _, _, renamed = await api.candidate_request()
    await api.sql(
        "UPDATE platform.approval_requests SET approval_type = 'studio.lifecycle.unfreeze',"
        " required_scope = 'studio.lifecycle.freeze' WHERE id = :a",
        a=uuid.UUID(renamed),
    )
    seen = await api.call("approver", "GET", f"/api/v1/approvals/{renamed}")
    assert seen.status_code == 200 and seen.json()["can_decide"] is True
    assert (await api.candidate("approver", renamed)).status_code == 404


# ======================================== R2.8 (AL36): the new segments ==


@pytest.mark.parametrize("action", ["submit", "withdraw"])
async def test_r2_8_another_companys_object_is_a_random_id(api: Api, action: str) -> None:
    artifact_id, version_id, etag = await api.create("author")
    tenant = api.people["author"].tenant.tenant_id
    before = await api.sql(
        "SELECT count(*) FROM platform.audit_events WHERE tenant_id = :t", t=tenant
    )
    answers = [
        await api.call(
            "outsider",
            "POST",
            f"{STUDIO}/objects/{a}/versions/{v}/{action}",
            headers={"If-Match": f'"{etag}"'},
        )
        for a, v in ((artifact_id, version_id), (uuid.uuid4(), uuid.uuid4()))
    ]
    assert [a.status_code for a in answers] == [404, 404]
    assert answers[0].json()["type"] == answers[1].json()["type"]
    after = await api.sql(
        "SELECT count(*) FROM platform.audit_events WHERE tenant_id = :t", t=tenant
    )
    assert after == before


async def test_r2_8_without_the_object_key_it_is_not_found(api: Api) -> None:
    """The `object` kind's read key is its submit key: no 403 to build."""
    artifact_id, version_id, etag = await api.create("author")
    answer = await api.submit("nobody", artifact_id, version_id, etag)
    assert answer.status_code == 404


async def test_r2_8_objects_names_one_kind_and_data_sources_none_yet(api: Api) -> None:
    gateless, gateless_v, gateless_etag = await api.create("fixture_writer", "fixture_gateless")
    under_objects = await api.submit("fixture_writer", gateless, gateless_v, gateless_etag)
    assert under_objects.status_code == 404
    artifact_id, version_id, etag = await api.create("author")
    for a, v in ((artifact_id, version_id), (str(uuid.uuid4()), str(uuid.uuid4()))):
        answer = await api.submit("author", a, v, etag, segment="data-sources")
        assert answer.status_code == 404, answer.text
    [(stage,)] = await api.sql(
        "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=uuid.UUID(version_id)
    )
    assert stage == "draft"


async def test_retire_is_not_mounted_under_objects(api: Api) -> None:
    answer = await api.call(
        "author", "POST", f"{STUDIO}/objects/{uuid.uuid4()}/versions/{uuid.uuid4()}/retire"
    )
    assert answer.status_code in (404, 405)
