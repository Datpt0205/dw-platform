"""`/api/v1/studio/artifacts` over HTTP, against Postgres (tenant-config ticket 02;
studio-skeleton R6.11).

The real app, built with `studio_kinds=FIXTURE_KINDS` and never reassigned
after, on a world of two workspaces, people at each depth of the fixture keys,
and another company (`dw_studio.testing.world`). A version outside `draft`
is placed by the migrator, as `LifecycleService` (agent-lifecycle/03) will;
a seal runs through `ArtifactService.seal` in a transaction of the store, as
agent-lifecycle/03's submit route will.
"""

from __future__ import annotations

import asyncio
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
from dw_api.bootstrap.paths import release_manifest_ref
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_studio.core.adapters.artifact_store import SqlArtifactTx
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.application.service import ArtifactService, SealResult
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.world import StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-artifacts-secret-0123456789abcdef"
BASE = "/api/v1/studio/artifacts"


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    world: StudioWorld

    @property
    def service(self) -> ArtifactService:
        assert self.container.studio is not None
        return self.container.studio.artifacts

    def headers(self, who: str, workspace: uuid.UUID | None = None, **extra: str) -> dict[str, str]:
        person = self.world[who]
        return {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
            "X-Tenant-Id": str(person.tenant_id),
            "X-Workspace-Id": str(workspace or person.workspace_id),
            **extra,
        }

    async def call(
        self, who: str, method: str, url: str, *, headers: dict[str, str] | None = None, **kw: Any
    ) -> httpx.Response:
        return await self.client.request(
            method, url, headers=self.headers(who, **(headers or {})), **kw
        )

    async def create(
        self, who: str = "writer", *, kind: str = "fixture", document: Any = None, **kw: Any
    ) -> dict[str, Any]:
        body = {"kind": kind, "api_name": name(), "document": document or doc(), **kw}
        response = await self.call(who, "POST", BASE, json=body)
        assert response.status_code == 201, response.text
        created: dict[str, Any] = response.json()
        return created

    async def draft(self, who: str, artifact_id: str) -> httpx.Response:
        return await self.call(who, "GET", f"{BASE}/{artifact_id}/draft")

    async def seal(self, who: str, artifact_id: str) -> SealResult:
        draft = (await self.draft(who, artifact_id)).json()
        async with self.service.store.transaction(self.world[who].context()) as tx:
            return await self.service.seal(tx, uuid.UUID(artifact_id), draft["version"])

    async def stage(self, version_id: uuid.UUID, to: str) -> None:
        await self.sql(
            "UPDATE studio.artifact_versions SET stage = :s WHERE id = :v", s=to, v=version_id
        )

    async def published(self, who: str = "writer", **kw: Any) -> tuple[str, SealResult]:
        created = await self.create(who, **kw)
        sealed = await self.seal(who, created["id"])
        await self.stage(sealed.version_id, "live")
        return created["id"], sealed

    async def sql(self, statement: str, **values: Any) -> list[Any]:
        async with self.migrator.begin() as conn:
            result = await conn.execute(sa.text(statement), values)
            return list(result.all()) if result.returns_rows else []

    async def count(self, table: str, **where: Any) -> int:
        clause = " AND ".join(f"{k} = :{k}" for k in where) or "true"
        rows = await self.sql(f"SELECT count(*) FROM {table} WHERE {clause}", **where)
        return int(rows[0][0])


def name() -> str:
    return f"a_{uuid.uuid4().hex[:12]}"


def doc(*uses: str, title: str = "Khách hàng") -> dict[str, Any]:
    return {"title": title, "uses": list(uses)}


def match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            world = await plant_world(conn)
        container = build_container(
            ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET),
            studio_kinds=FIXTURE_KINDS,
        )
        app = create_app(container)
        assert container.engine is not None
        try:
            async with LifespanManager(app):
                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    yield Api(client, container, migrator, world)
        finally:
            await container.engine.dispose()
    await migrator.dispose()


def reason(response: httpx.Response) -> str | None:
    details: dict[str, Any] = response.json().get("details", {})
    found = details.get("reason_code")
    return None if found is None else str(found)


# ======================================================= create and read ====


async def test_a_create_makes_the_artifact_its_draft_and_its_audit_in_one_go(api: Api) -> None:
    """R2.1: a UUIDv7 id, one draft, one `studio.artifact.created`."""
    created = await api.create(labels=["hot"])
    artifact_id = uuid.UUID(created["id"])

    assert artifact_id.version == 7
    assert created["owning_workspace_id"] == str(api.world.ws1)
    assert created["version"] == 1 and created["labels"] == ["hot"]
    assert await api.count("studio.artifact_versions", artifact_id=artifact_id, stage="draft") == 1
    assert (
        await api.count(
            "platform.audit_events", resource_id=str(artifact_id), action="studio.artifact.created"
        )
        == 1
    )


async def test_a_create_that_fails_midway_leaves_no_row(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2.1: the audit write fails after both inserts; nothing stays."""

    async def fail(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("the audit store went away")

    monkeypatch.setattr(SqlArtifactTx, "audit", fail)
    api_name = name()
    response = await api.call(
        "writer", "POST", BASE, json={"kind": "fixture", "api_name": api_name}
    )

    assert response.status_code == 500
    assert await api.count("studio.artifacts", api_name=api_name) == 0


@pytest.mark.parametrize(
    ("api_name", "status"),
    [("a" * 40, 201), ("a" * 41, 422), ("a", 422), ("Lead", 422), ("1lead", 422)],
)
async def test_the_api_name_is_two_to_forty_lower_case(
    api: Api, api_name: str, status: int
) -> None:
    """R2.2."""
    unique = api_name if status == 422 else f"z{uuid.uuid4().hex[:39]}"
    response = await api.call("writer", "POST", BASE, json={"kind": "fixture", "api_name": unique})

    assert response.status_code == status, response.text
    if status == 422:
        assert response.json()["errors"][0]["pointer"] == "/api_name"
        assert await api.count("studio.artifacts", api_name=unique) == 0


async def test_an_api_name_is_unique_among_live_artifacts_of_one_kind_and_company(api: Api) -> None:
    """R2.3."""
    first = await api.create()
    body = {"kind": "fixture", "api_name": first["api_name"]}

    taken = await api.call("writer", "POST", BASE, json=body)
    assert (taken.status_code, reason(taken)) == (409, "api_name_taken")
    assert (await api.call("outsider", "POST", BASE, json=body)).status_code == 201
    assert (
        await api.call("writer", "POST", BASE, json={**body, "kind": "fixture_gateless"})
    ).status_code == 201

    gone = await api.call("writer", "DELETE", f"{BASE}/{first['id']}", headers=match(1))
    assert gone.status_code == 204
    assert (await api.call("writer", "POST", BASE, json=body)).status_code == 201


async def test_an_unregistered_kind_or_a_write_key_out_of_reach_creates_nothing(api: Api) -> None:
    """R2.12, R2.15."""
    api_name = name()
    unknown = await api.call(
        "writer", "POST", BASE, json={"kind": "dw_nothing", "api_name": api_name}
    )
    reader = await api.call("reader", "POST", BASE, json={"kind": "fixture", "api_name": api_name})

    assert unknown.status_code == 422
    assert unknown.json()["errors"][0]["pointer"] == "/kind"
    assert reader.status_code == 403 and reader.json()["code"] == "permission_denied"
    assert await api.count("studio.artifacts", api_name=api_name) == 0


async def test_the_app_without_test_kinds_takes_no_fixture(api_db: DatabaseUrls) -> None:
    """R2.15: built with the default kinds, `fixture` is not a kind; `object`
    is (custom-objects 02). Ticket 04: the run manifest builder pins the
    release this process serves, and a run reads its manifest through
    Studio's store."""
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    assert container.studio is not None and container.studio.kinds.kinds == {"object"}
    assert container.studio.run_manifests.registry is container.studio.kinds
    assert container.studio.run_manifests.release_manifest_ref == release_manifest_ref()
    assert container.studio.pinned_manifests is SqlRunManifestStore
    assert container.engine is not None
    await container.engine.dispose()


async def test_a_retried_create_answers_once_and_only_to_its_caller(api: Api) -> None:
    """R2.1 (ADR-0108 decision 4): same key, same body, same 201 with `ETag`
    and `Location`; another person's use of the key is a conflict."""
    body = {"kind": "fixture", "api_name": name()}
    key = {"Idempotency-Key": f"k-{uuid.uuid4()}"}
    first = await api.call("writer", "POST", BASE, json=body, headers=key)
    again = await api.call("writer", "POST", BASE, json=body, headers=key)
    other = await api.call("ws2_writer", "POST", BASE, json=body, headers=key)

    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    for header in ("ETag", "Location"):
        assert first.headers[header] == again.headers[header]
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"
    assert await api.count("studio.artifacts", api_name=body["api_name"]) == 1


# ================================================================ reach =====


async def test_an_artifact_out_of_reach_is_not_there(api: Api) -> None:
    """R2.11 (TC24): another workspace past the reader's depth, another company."""
    in_ws2 = await api.create("ws2_writer")
    url = f"{BASE}/{in_ws2['id']}"

    assert (await api.call("reader", "GET", url)).status_code == 404
    assert (await api.call("outsider", "GET", url)).status_code == 404
    assert (await api.call("tenant_reader", "GET", url)).status_code == 200
    assert (await api.call("ws2_writer", "GET", url)).status_code == 200


async def _all_pages(api: Api, who: str, **params: Any) -> list[list[str]]:
    pages: list[list[str]] = []
    cursor: str | None = None
    while True:
        query = {"limit": 2, **params, **({"cursor": cursor} if cursor else {})}
        response = await api.call(who, "GET", BASE, params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append([item["id"] for item in body["items"]])
        cursor = body["next_cursor"]
        if not cursor:
            return pages


@pytest.mark.parametrize("kind", [None, "fixture"])
async def test_a_list_holds_only_what_the_caller_reads_and_pages_stay_full(
    api: Api, kind: str | None
) -> None:
    """R2.11 (TC24): no ws2 artifact, no deleted one, every page but the last full."""
    deleted = await api.create()
    await api.call("writer", "DELETE", f"{BASE}/{deleted['id']}", headers=match(1))
    for _ in range(3):
        await api.create("ws2_writer")
        await api.create("writer")
    params = {} if kind is None else {"kind": kind}

    pages = await _all_pages(api, "reader", **params)
    seen = {i for page in pages for i in page}
    rows = await api.sql(
        "SELECT id::text, owning_workspace_id, deleted_at, kind FROM studio.artifacts"
        " WHERE id::text = ANY(:ids)",
        ids=list(seen),
    )
    assert {r.owning_workspace_id for r in rows} == {api.world.ws1}
    assert all(r.deleted_at is None for r in rows)
    assert deleted["id"] not in seen
    assert all(len(page) == 2 for page in pages[:-1])
    if kind is not None:
        assert {r.kind for r in rows} == {kind}
    every = {i for page in await _all_pages(api, "tenant_reader", **params) for i in page}
    owners = await api.sql(
        "SELECT DISTINCT owning_workspace_id FROM studio.artifacts WHERE id::text = ANY(:ids)",
        ids=list(every),
    )
    assert {r[0] for r in owners} == {api.world.ws1, api.world.ws2}


async def test_a_label_narrows_the_list(api: Api) -> None:
    labelled = await api.create(labels=["mua_he"])
    await api.create()
    response = await api.call("writer", "GET", BASE, params={"label": "mua_he", "limit": 100})
    assert [item["id"] for item in response.json()["items"]] == [labelled["id"]]


_ROUTES = [
    ("GET", ""),
    ("PATCH", ""),
    ("DELETE", ""),
    ("GET", "/draft"),
    ("PUT", "/draft"),
    ("POST", "/draft"),
    ("GET", "/versions"),
    ("GET", "/versions/1"),
    ("GET", "/dependents"),
    ("GET", "/draft/dependencies"),
]
_WRITES = {("PATCH", ""), ("DELETE", ""), ("PUT", "/draft"), ("POST", "/draft")}


def _request(method: str, suffix: str) -> dict[str, Any]:
    if (method, suffix) == ("PATCH", ""):
        return {
            "json": {"labels": ["x"]},
            "headers": {**match(1), "Content-Type": "application/merge-patch+json"},
        }
    if (method, suffix) == ("PUT", "/draft"):
        return {"json": {"document": doc()}, "headers": match(1)}
    if method in {"DELETE", "POST"}:
        return {"headers": match(1)}
    return {}


async def _rows_of(api: Api, artifact_id: str) -> tuple[Any, ...]:
    artifact = await api.sql(
        "SELECT * FROM studio.artifacts WHERE id = :a", a=uuid.UUID(artifact_id)
    )
    versions = await api.sql(
        "SELECT * FROM studio.artifact_versions WHERE artifact_id = :a ORDER BY id",
        a=uuid.UUID(artifact_id),
    )
    return (tuple(artifact), tuple(versions))


@pytest.mark.parametrize("kind", [k.kind for k in FIXTURE_KINDS])
@pytest.mark.parametrize(("method", "suffix"), _ROUTES, ids=[f"{m} {s or '/'}" for m, s in _ROUTES])
async def test_every_id_route_checks_tenant_reach_and_write(
    api: Api, kind: str, method: str, suffix: str
) -> None:
    """R2.11, R2.12 (TC24), for every registered kind: another company or a
    soft-deleted artifact is a 404, a reader's write a 403, nothing written."""
    created = await api.create(kind=kind)
    url = f"{BASE}/{created['id']}{suffix}"
    before = await _rows_of(api, created["id"])

    outsider = await api.call("outsider", method, url, **_request(method, suffix))
    assert outsider.status_code == 404, outsider.text
    if (method, suffix) in _WRITES:
        reader = await api.call("reader", method, url, **_request(method, suffix))
        assert (reader.status_code, reader.json()["code"]) == (403, "permission_denied")
    assert await _rows_of(api, created["id"]) == before

    gone = await api.create(kind=kind)
    await api.call("writer", "DELETE", f"{BASE}/{gone['id']}", headers=match(1))
    deleted = await api.call(
        "writer", method, f"{BASE}/{gone['id']}{suffix}", **_request(method, suffix)
    )
    assert deleted.status_code == 404


# ================================================================ draft =====


async def test_a_draft_is_read_and_saved_under_its_own_etag(api: Api) -> None:
    """R2.4, R2.5 (TC3)."""
    created = await api.create()
    read = await api.draft("writer", created["id"])
    assert read.status_code == 200 and read.headers["ETag"] == f'"{read.json()["version"]}"'
    url = f"{BASE}/{created['id']}/draft"

    saved = await api.call(
        "writer", "PUT", url, json={"document": doc(title="mới")}, headers=match(1)
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 2 and saved.headers["ETag"] == '"2"'
    assert saved.json()["document"]["title"] == "mới"

    stale = await api.call(
        "writer", "PUT", url, json={"document": doc(title="cũ")}, headers=match(1)
    )
    assert (stale.status_code, reason(stale)) == (412, "stale_version")
    assert (await api.draft("writer", created["id"])).json()["document"]["title"] == "mới"

    missing = await api.call("writer", "PUT", url, json={"document": doc()})
    assert missing.status_code == 428
    for method in ("DELETE", "POST"):
        target = url if method == "POST" else f"{BASE}/{created['id']}"
        assert (await api.call("writer", method, target)).status_code == 428


async def test_two_saves_with_one_etag_give_one_200_and_one_412(api: Api) -> None:
    """R2.5 (TC3)."""
    created = await api.create()
    url = f"{BASE}/{created['id']}/draft"
    answers = await asyncio.gather(
        api.call("writer", "PUT", url, json={"document": doc(title="một")}, headers=match(1)),
        api.call("writer", "PUT", url, json={"document": doc(title="hai")}, headers=match(1)),
    )
    assert sorted(a.status_code for a in answers) == [200, 412]


async def test_a_reader_cannot_save_a_draft(api: Api) -> None:
    """R2.12 (TC24)."""
    created = await api.create()
    url = f"{BASE}/{created['id']}/draft"
    refused = await api.call(
        "reader", "PUT", url, json={"document": doc(title="x")}, headers=match(1)
    )
    assert refused.status_code == 403
    assert (await api.draft("writer", created["id"])).json()["version"] == 1


async def test_no_draft_and_a_pending_candidate_are_told_apart(api: Api) -> None:
    """R2.5: `no_draft` to read; `candidate_pending` to save beside a candidate."""
    created = await api.create(kind="fixture_gateless")
    sealed = await api.seal("writer", created["id"])
    await api.stage(sealed.version_id, "awaiting_approval")
    url = f"{BASE}/{created['id']}/draft"

    read = await api.call("writer", "GET", url)
    save = await api.call("writer", "PUT", url, json={"document": doc()}, headers=match(2))
    assert (read.status_code, reason(read)) == (404, "no_draft")
    assert (save.status_code, reason(save)) == (409, "candidate_pending")

    live_only, _ = await api.published()
    url = f"{BASE}/{live_only}/draft"
    for method, kw in (("GET", {}), ("PUT", {"json": {"document": doc()}, "headers": match(1)})):
        answer = await api.call("writer", method, url, **kw)
        assert (answer.status_code, reason(answer)) == (404, "no_draft")


async def test_a_resealed_draft_saved_again_drops_its_number_and_hashes(api: Api) -> None:
    """R2.8: a version back in `draft` keeps no number or hash of old content."""
    created = await api.create()
    sealed = await api.seal("writer", created["id"])
    await api.stage(sealed.version_id, "evaluating")
    await api.stage(sealed.version_id, "draft")
    url = f"{BASE}/{created['id']}/draft"
    saved = await api.call(
        "writer", "PUT", url, json={"document": doc(title="lại")}, headers=match(2)
    )

    assert saved.status_code == 200
    row = await api.sql(
        "SELECT version_no, content_hash, definition_hash FROM studio.artifact_versions"
        " WHERE id = :v",
        v=sealed.version_id,
    )
    assert row == [(None, None, None)]


@pytest.mark.parametrize("v2_stage", ["live", "retired"])
async def test_a_new_draft_copies_the_live_version_or_the_highest(api: Api, v2_stage: str) -> None:
    """R2.21: v1 retired and v2 live, or both retired: the draft copies v2."""
    artifact_id, v1 = await api.published(document=doc(title="v1"))
    created = await api.call("writer", "POST", f"{BASE}/{artifact_id}/draft", headers=match(1))
    assert created.status_code == 201
    await api.call(
        "writer",
        "PUT",
        f"{BASE}/{artifact_id}/draft",
        json={"document": doc(title="v2")},
        headers=match(created.json()["version"]),
    )
    v2 = await api.seal("writer", artifact_id)
    await api.stage(v1.version_id, "retired")
    await api.stage(v2.version_id, v2_stage)
    action = "studio.artifact.draft_created"
    audits = await api.count("platform.audit_events", resource_id=artifact_id, action=action)

    answer = await api.call("writer", "POST", f"{BASE}/{artifact_id}/draft", headers=match(1))

    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["document"]["title"] == "v2"
    assert body["based_on_version_id"] == str(v2.version_id)
    assert answer.headers["ETag"] == f'"{body["version"]}"'
    assert answer.headers["Location"] == f"{BASE}/{artifact_id}/draft"
    number = await api.sql(
        "SELECT version_no FROM studio.artifact_versions WHERE id = :v", v=uuid.UUID(body["id"])
    )
    assert number == [(None,)]
    assert await api.count("platform.audit_events", resource_id=artifact_id, action=action) == (
        audits + 1
    )


async def test_a_draft_beside_a_draft_or_a_candidate_is_refused(api: Api) -> None:
    """R2.22, R2.23 (TC27): nothing written, nothing audited."""
    has_draft = await api.create()
    answer = await api.call("writer", "POST", f"{BASE}/{has_draft['id']}/draft", headers=match(1))
    assert (answer.status_code, reason(answer)) == (409, "draft_exists")

    for kind, to in (("fixture_gateless", "awaiting_approval"), ("fixture", "evaluating")):
        created = await api.create(kind=kind)
        sealed = await api.seal("writer", created["id"])
        await api.stage(sealed.version_id, to)
        rows = await api.count("studio.artifact_versions", artifact_id=uuid.UUID(created["id"]))
        answer = await api.call("writer", "POST", f"{BASE}/{created['id']}/draft", headers=match(1))
        assert (answer.status_code, reason(answer)) == (409, "candidate_pending"), kind
        assert (
            await api.count("studio.artifact_versions", artifact_id=uuid.UUID(created["id"]))
            == rows
        )
        assert (
            await api.count(
                "platform.audit_events",
                resource_id=created["id"],
                action="studio.artifact.draft_created",
            )
            == 0
        )


async def test_draft_dependencies_are_extracted_and_never_written(api: Api) -> None:
    """R3.5."""
    target, _ = await api.published()
    created = await api.create(document=doc(target))
    before = await api.count("studio.dependencies")
    answer = await api.call("writer", "GET", f"{BASE}/{created['id']}/draft/dependencies")
    assert answer.json()["items"] == [
        {"to_kind": "artifact", "to_key": target, "usage": "read", "path": "/uses/0"}
    ]
    assert await api.count("studio.dependencies") == before


# ======================================================= patch and delete ====


async def test_the_api_name_changes_until_a_version_was_live(api: Api) -> None:
    """R2.10 (TC4)."""
    patch_headers = {"Content-Type": "application/merge-patch+json"}
    fresh = await api.create()
    renamed = await api.call(
        "writer",
        "PATCH",
        f"{BASE}/{fresh['id']}",
        json={"api_name": name()},
        headers={**patch_headers, **match(1)},
    )
    assert renamed.status_code == 200 and renamed.json()["version"] == 2
    assert renamed.headers["ETag"] == '"2"'

    artifact_id, _ = await api.published()
    refused = await api.call(
        "writer",
        "PATCH",
        f"{BASE}/{artifact_id}",
        json={"api_name": name()},
        headers={**patch_headers, **match(1)},
    )
    assert (refused.status_code, reason(refused)) == (409, "api_name_immutable")


async def test_a_soft_delete_hides_the_artifact_and_is_audited(api: Api) -> None:
    """R3.2."""
    created = await api.create()
    gone = await api.call("writer", "DELETE", f"{BASE}/{created['id']}", headers=match(1))
    assert gone.status_code == 204
    row = await api.sql(
        "SELECT deleted_at FROM studio.artifacts WHERE id = :a", a=uuid.UUID(created["id"])
    )
    assert row[0][0] is not None
    assert (
        await api.count(
            "platform.audit_events", resource_id=created["id"], action="studio.artifact.deleted"
        )
        == 1
    )
    listed = await api.call("writer", "GET", BASE, params={"limit": 200})
    assert created["id"] not in {i["id"] for i in listed.json()["items"]}


async def test_an_artifact_in_use_elsewhere_is_not_deleted(api: Api) -> None:
    """R3.3 (TC5): a live version in another workspace uses it; retired, it does not."""
    target, _ = await api.published()
    user = await api.create("ws2_writer", document=doc(target))
    sealed = await api.seal("ws2_writer", user["id"])
    await api.stage(sealed.version_id, "live")

    refused = await api.call("writer", "DELETE", f"{BASE}/{target}", headers=match(1))
    assert (refused.status_code, reason(refused)) == (409, "artifact_in_use")
    assert refused.json()["details"]["in_use"] == {"live": 1}

    await api.stage(sealed.version_id, "retired")
    assert (
        await api.call("writer", "DELETE", f"{BASE}/{target}", headers=match(1))
    ).status_code == 204


async def test_where_used_names_only_what_the_caller_reads(api: Api) -> None:
    """R3.4 (TC7)."""
    target, _ = await api.published()
    mine = await api.create("writer", document=doc(target))
    theirs = await api.create("ws2_writer", document=doc(target))
    for who, created in (("writer", mine), ("ws2_writer", theirs)):
        sealed = await api.seal(who, created["id"])
        await api.stage(sealed.version_id, "live")

    answer = await api.call("reader", "GET", f"{BASE}/{target}/dependents")
    body = answer.json()
    assert [i["artifact_id"] for i in body["live"]["items"]] == [mine["id"]]
    assert body["live"]["hidden"] == 1
    assert body["candidate"] == {"items": [], "hidden": 0}
    assert (await api.call("outsider", "GET", f"{BASE}/{target}/dependents")).status_code == 404


async def test_versions_list_only_sealed_ones(api: Api) -> None:
    artifact_id, sealed = await api.published()
    await api.call("writer", "POST", f"{BASE}/{artifact_id}/draft", headers=match(1))
    listed = (await api.call("writer", "GET", f"{BASE}/{artifact_id}/versions")).json()["items"]
    assert [(v["version_no"], v["stage"]) for v in listed] == [(1, "live")]
    one = await api.call("writer", "GET", f"{BASE}/{artifact_id}/versions/1")
    assert one.json()["content_hash"] == sealed.content_hash
    assert (await api.call("writer", "GET", f"{BASE}/{artifact_id}/versions/2")).status_code == 404


# ============================================== the group's context, R6.11 ==


async def test_the_group_refuses_whom_the_platform_refuses_the_same_way(api: Api) -> None:
    """studio-skeleton R6.11 (SKEL30): a suspended member, a locked company and
    a support grant header on an active member's token answer alike at a
    Studio route and at `GET /api/v1/runs/{run_id}`."""
    async with api.migrator.begin() as conn:
        local = await plant_world(conn)
    api_world, api.world = api.world, local
    try:
        run = f"/api/v1/runs/{uuid.uuid4()}"
        support = {"X-DW-Support-Grant": str(uuid.uuid4())}
        cases: dict[str, tuple[str, dict[str, str]]] = {"support": ("writer", support)}

        async def both(who: str, extra: dict[str, str]) -> list[tuple[int, str, Any]]:
            found = []
            for url in (BASE, run):
                answer = await api.call(who, "GET", url, headers=extra)
                body = answer.json()
                found.append((answer.status_code, body["code"], body["details"].get("reason_code")))
            return found

        support_answers = await both(*cases["support"])
        assert support_answers[0] == support_answers[1]
        assert support_answers[0][2] == "support_context_not_allowed"

        await api.sql(
            "UPDATE platform.tenant_members SET status = 'suspended'"
            " WHERE tenant_id = :t AND user_id = :u",
            t=local.tenant.tenant_id,
            u=local["reader"].id,
        )
        suspended = await both("reader", {})
        assert suspended[0] == suspended[1] and suspended[0][0] in {401, 403}

        await api.sql(
            "UPDATE platform.tenants SET status = 'locked' WHERE id = :t", t=local.tenant.tenant_id
        )
        locked = await both("writer", {})
        assert locked[0] == locked[1] and locked[0][0] in {401, 403}
    finally:
        api.world = api_world
