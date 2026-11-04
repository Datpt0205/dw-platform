"""The `workflow` kind over HTTP, against Postgres (workflow-engine ticket 01:
R1.1, R1.2, R1.5, R1.8, R2.10, R2.13, R2.14; WE36).

The real app, built with the test's kinds: `workflow` as `platform_kinds`
builds it but over the fixture step types (`dw_studio.testing.workflows`),
and `fixture_gateless`, whose live versions stand in for the data source a
trigger uses. A draft is saved with `PUT .../draft` and sealed by the real
submit route, `POST /studio/workflows/{id}/versions/{vid}/submit`, which runs
the kind's check (tenant-config R2.6). People hold the workflow keys at
workspace depth; `outsider` holds all of them in another company.
"""

from __future__ import annotations

import time
import unicodedata
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
from dw_studio.kinds import WORKFLOWS_EDIT_SCOPE, WORKFLOWS_READ_SCOPE
from dw_studio.lifecycle.application.service import VERSIONS_SUBMIT_SCOPE
from dw_studio.testing.fixture_kinds import FIXTURE_GATELESS, planted_fixture_kinds
from dw_studio.testing.lifecycle import move_for_test
from dw_studio.testing.workflows import plant_holder, studio_document, studio_step, workflow_entry
from dw_studio.testing.world import Person, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-workflows-secret-0123456789abcdef"
STUDIO = "/api/v1/studio"


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    people: dict[str, Person]
    source: str

    async def call(self, who: str, method: str, url: str, **kw: Any) -> httpx.Response:
        person = self.people[who]
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
            "X-Tenant-Id": str(person.tenant_id),
            "X-Workspace-Id": str(person.workspace_id),
            **kw.pop("headers", {}),
        }
        return await self.client.request(method, url, headers=headers, **kw)

    def document(self, *steps: dict[str, Any]) -> dict[str, Any]:
        return studio_document(*(steps or (studio_step("dau"),)), source=self.source)

    async def create(self, document: dict[str, Any] | None = None) -> tuple[str, str, int]:
        """(artifact id, draft id, draft ETag), as `author`."""
        response = await self.call(
            "author",
            "POST",
            f"{STUDIO}/artifacts",
            json={
                "kind": "workflow",
                "api_name": f"qt_{uuid.uuid4().hex[:12]}",
                "document": document or self.document(),
            },
        )
        assert response.status_code == 201, response.text
        artifact_id = response.json()["id"]
        draft = await self.call("author", "GET", f"{STUDIO}/artifacts/{artifact_id}/draft")
        return artifact_id, draft.json()["id"], draft.json()["version"]

    async def save(
        self, artifact_id: str, etag: int, document: Any, who: str = "author"
    ) -> httpx.Response:
        return await self.call(
            who,
            "PUT",
            f"{STUDIO}/artifacts/{artifact_id}/draft",
            json={"document": document},
            headers={"If-Match": f'"{etag}"'},
        )

    async def submit(self, artifact_id: str, version_id: str, etag: int) -> httpx.Response:
        return await self.call(
            "author",
            "POST",
            f"{STUDIO}/workflows/{artifact_id}/versions/{version_id}/submit",
            headers={"If-Match": f'"{etag}"'},
        )

    async def version(self, version_id: str) -> Any:
        async with self.migrator.connect() as conn:
            return (
                await conn.execute(
                    sa.text(
                        "SELECT stage, version_no, content_hash, row_version"
                        " FROM studio.artifact_versions WHERE id = :v"
                    ),
                    {"v": uuid.UUID(version_id)},
                )
            ).one()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            world = await plant_world(conn)
            people = {
                "writer": world["writer"],
                "author": await plant_holder(conn, world.tenant, workspace=world.ws1),
                "reader": await plant_holder(
                    conn, world.tenant, (WORKFLOWS_READ_SCOPE,), workspace=world.ws1
                ),
                "no_read": await plant_holder(
                    conn,
                    world.tenant,
                    (WORKFLOWS_EDIT_SCOPE, VERSIONS_SUBMIT_SCOPE),
                    workspace=world.ws1,
                ),
                "outsider": await plant_holder(conn, world.other),
            }
        container = build_container(
            ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET),
            studio_kinds=(FIXTURE_GATELESS, workflow_entry()),
        )
        app = create_app(container)
        assert container.engine is not None
        try:
            async with LifespanManager(app):
                transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    api = Api(client, container, migrator, people, source="")
                    api.source = await _live_source(api)
                    yield api
        finally:
            await container.engine.dispose()
    await migrator.dispose()


async def _live_source(api: Api) -> str:
    """A `fixture_gateless` artifact with a live v1: the trigger's source."""
    created = await api.call(
        "writer",
        "POST",
        f"{STUDIO}/artifacts",
        json={"kind": "fixture_gateless", "api_name": "nguon_lead", "document": {"title": "x"}},
    )
    assert created.status_code == 201, created.text
    artifact_id = created.json()["id"]
    draft = (await api.call("writer", "GET", f"{STUDIO}/artifacts/{artifact_id}/draft")).json()
    assert api.container.studio is not None
    service = api.container.studio.artifacts
    async with service.store.transaction(api.people["writer"].context()) as tx:
        sealed = await service.seal(tx, uuid.UUID(artifact_id), draft["version"])
    await move_for_test(api.migrator, sealed.version_id, "live")
    return str(artifact_id)


def errors(response: httpx.Response) -> list[tuple[str, str]]:
    return [(e["code"], e["pointer"]) for e in response.json().get("errors", [])]


def unreachable_document(api: Api) -> dict[str, Any]:
    return api.document(studio_step("dung", "fixture.stop@1"), studio_step("sau_dung"))


# ================================================================ R2.13 ==


async def test_r2_13_a_draft_saves_with_warnings_and_the_same_problems_refuse_a_submit(
    api: Api,
) -> None:
    artifact_id, version_id, etag = await api.create()
    saved = await api.save(artifact_id, etag, unreachable_document(api))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["document"]["steps"][1]["id"] == "sau_dung"
    assert [(w["code"], w["pointer"]) for w in body["warnings"]] == [
        ("wf.unreachable_node", "/steps/1")
    ]

    refused = await api.submit(artifact_id, version_id, body["version"])
    assert refused.status_code == 422, refused.text
    assert errors(refused) == [("wf.unreachable_node", "/steps/1")]
    row = await api.version(version_id)
    assert (row.stage, row.version_no, row.content_hash) == ("draft", None, None)


async def test_r2_13_an_empty_draft_saves_with_its_warning(api: Api) -> None:
    artifact_id, _, etag = await api.create()
    empty = {**api.document(), "steps": []}
    saved = await api.save(artifact_id, etag, empty)
    assert saved.status_code == 200, saved.text
    assert [w["code"] for w in saved.json()["warnings"]] == ["wf.schema_invalid"]


async def test_r2_13_a_valid_draft_has_no_warning_and_submits(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    saved = await api.save(artifact_id, etag, api.document(studio_step("mot")))
    assert (saved.status_code, saved.json()["warnings"]) == (200, [])
    answer = await api.submit(artifact_id, version_id, saved.json()["version"])
    assert answer.status_code == 202, answer.text
    assert answer.json()["stage"] == "evaluating"


# ================================================================= R1.2 ==


async def test_r1_2_a_float_is_refused_with_its_pointer_and_nothing_is_written(
    api: Api,
) -> None:
    artifact_id, version_id, etag = await api.create()
    document = api.document(studio_step("mot", note="x"))
    document["steps"][0]["config"]["score"] = 1.0
    refused = await api.save(artifact_id, etag, document)
    assert refused.status_code == 422, refused.text
    assert errors(refused) == [("float_forbidden", "/document/steps/0/config/score")]
    row = await api.version(version_id)
    assert (row.row_version, row.content_hash) == (etag, None)


async def test_r1_2_a_string_not_in_nfc_is_stored_and_hashed_in_nfc(api: Api) -> None:
    """The envelope's edge repairs NFC before its check (tenant-config 02,
    `canonical_document`), so no NFD string reaches a hash."""
    artifact_id, version_id, etag = await api.create()
    nfd = unicodedata.normalize("NFD", "Gửi lời chào")
    saved = await api.save(artifact_id, etag, api.document(studio_step("mot", note=nfd)))
    assert saved.status_code == 200, saved.text
    note = saved.json()["document"]["steps"][0]["config"]["note"]
    assert note == unicodedata.normalize("NFC", nfd) and note != nfd
    answer = await api.submit(artifact_id, version_id, saved.json()["version"])
    assert answer.status_code == 202, answer.text


# ======================================================== R1.1, R2.14 ==


async def test_r1_1_a_step_three_deep_without_retry_is_not_sealed(api: Api) -> None:
    handler = {k: v for k, v in studio_step("xu_ly").items() if k != "retry"}
    risky = {**studio_step("gui"), "on_error": "route", "error_lane": [handler]}
    gate = studio_step(
        "duyet",
        "human.approval@1",
        decision_class="lead.reply",
        proposal="x",
        approved=[risky],
        rejected=[],
    )
    document = {
        **api.document(gate),
        "decision_classes": [
            {"key": "lead.reply", "effect_level": "internal", "reversible": True, "ceiling": "A2"}
        ],
    }
    artifact_id, version_id, etag = await api.create(document)
    refused = await api.submit(artifact_id, version_id, etag)
    assert refused.status_code == 422, refused.text
    assert errors(refused) == [
        ("wf.schema_invalid", "/steps/0/config/approved/0/error_lane/0/retry")
    ]


async def test_r2_14_an_unregistered_type_warns_on_save_and_refuses_the_seal(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    saved = await api.save(artifact_id, etag, api.document(studio_step("la", "foo.bar@1")))
    assert saved.status_code == 200
    assert [(w["code"], w["pointer"]) for w in saved.json()["warnings"]] == [
        ("wf.unknown_type", "/steps/0/type")
    ]
    refused = await api.submit(artifact_id, version_id, saved.json()["version"])
    assert (refused.status_code, errors(refused)) == (422, [("wf.unknown_type", "/steps/0/type")])
    assert (await api.version(version_id)).version_no is None


# ========================================================== R1.8, WE36 ==


async def test_r1_8_a_position_is_refused_so_it_never_changes_a_hash(api: Api) -> None:
    """Two documents that differ by a position alone: one seals, the other
    is refused, so no second definition hash exists for one workflow."""
    plain = api.document(studio_step("mot"))
    placed = api.document({**studio_step("mot"), "position": {"x": 1, "y": 2}})
    artifact_id, version_id, etag = await api.create(placed)
    refused = await api.submit(artifact_id, version_id, etag)
    assert refused.status_code == 422, refused.text
    assert [code for code, _ in errors(refused)] == ["wf.schema_invalid"]
    assert errors(refused)[0][1].startswith("/steps/0")

    edged = {**plain, "edges": [{"from": "mot", "to": "mot"}]}
    artifact_id, version_id, etag = await api.create(edged)
    refused = await api.submit(artifact_id, version_id, etag)
    assert (refused.status_code, errors(refused)) == (422, [("wf.schema_invalid", "/edges")])


# ================================================================ R2.10 ==


async def test_r2_10_a_tree_nested_two_hundred_deep_is_a_422_in_well_under_a_second(
    api: Api,
) -> None:
    inner: list[dict[str, Any]] = [studio_step("la")]
    for level in range(200):
        inner = [studio_step(f"c{level}", "fixture.choice@1", on="x", yes=inner, no=[])]
    artifact_id, _, etag = await api.create()
    started = time.perf_counter()
    refused = await api.save(artifact_id, etag, api.document(*inner))
    assert time.perf_counter() - started < 1.0
    assert refused.status_code == 422, refused.text
    assert errors(refused)[0][0] == "depth_exceeded"


async def test_r2_10_depth_eleven_saves_with_a_warning_and_is_not_sealed(api: Api) -> None:
    inner: list[dict[str, Any]] = [studio_step("la")]
    for level in range(10):
        inner = [studio_step(f"c{level}", "fixture.choice@1", on="x", yes=inner, no=[])]
    artifact_id, version_id, etag = await api.create()
    saved = await api.save(artifact_id, etag, api.document(*inner))
    assert [w["code"] for w in saved.json()["warnings"]] == ["wf.limit_above_plan"]
    refused = await api.submit(artifact_id, version_id, saved.json()["version"])
    assert [code for code, _ in errors(refused)] == ["wf.limit_above_plan"]


# ================================================================= R1.5 ==


async def test_r1_5_without_the_read_key_the_workflow_is_not_there(api: Api) -> None:
    artifact_id, _, etag = await api.create()
    read = await api.call("no_read", "GET", f"{STUDIO}/artifacts/{artifact_id}")
    assert read.status_code == 404
    saved = await api.save(artifact_id, etag, api.document(), who="no_read")
    assert saved.status_code == 404


async def test_r1_5_with_the_read_key_and_not_the_edit_key_a_save_is_403(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    assert (await api.call("reader", "GET", f"{STUDIO}/artifacts/{artifact_id}")).status_code == 200
    saved = await api.save(artifact_id, etag, api.document(studio_step("khac")), who="reader")
    assert (saved.status_code, saved.json()["code"]) == (403, "permission_denied")
    assert (await api.version(version_id)).row_version == etag


async def test_r1_5_another_company_holding_every_key_meets_a_random_id(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    read = await api.call("outsider", "GET", f"{STUDIO}/artifacts/{artifact_id}")
    saved = await api.save(artifact_id, etag, api.document(), who="outsider")
    assert (read.status_code, saved.status_code) == (404, 404)
    assert (await api.version(version_id)).row_version == etag
