"""Submit, withdraw and retire over HTTP, against Postgres (agent-lifecycle
ticket 03: R1.3, R1.5, R2.1, R2.4-R2.6, R2.12, R2.13, R7.9; AL2, AL36).

The real app, built with the test kinds and the test's segments: `agents`
names the gated `fixture` (the kind whose submit this ticket builds) and
`workflows` the `fixture_gateless` one (whose candidates and live versions
`dw_studio.testing.lifecycle` places for withdraw and retire). The freeze is
the real one: a company's switch set by its own route (ticket 01).
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
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_studio.core.application.service import ArtifactService, SealResult
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import move_for_test, publish_for_test
from dw_studio.testing.world import StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-lifecycle-secret-0123456789abcdef"
STUDIO = "/api/v1/studio"
SEGMENTS = {"agents": "fixture", "workflows": "fixture_gateless"}


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    world: StudioWorld

    @property
    def artifacts(self) -> ArtifactService:
        assert self.container.studio is not None
        return self.container.studio.artifacts

    def headers(self, who: str, **extra: str) -> dict[str, str]:
        person = self.world[who]
        return {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
            "X-Tenant-Id": str(person.tenant_id),
            "X-Workspace-Id": str(person.workspace_id),
            **extra,
        }

    async def call(self, who: str, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = self.headers(who, **kw.pop("headers", {}))
        return await self.client.request(method, url, headers=headers, **kw)

    async def create(self, who: str = "writer", *, kind: str = "fixture") -> tuple[str, str, int]:
        """(artifact id, draft id, draft ETag)."""
        response = await self.call(
            who,
            "POST",
            f"{STUDIO}/artifacts",
            json={
                "kind": kind,
                "api_name": f"a_{uuid.uuid4().hex[:12]}",
                "document": {"title": "Khách hàng"},
            },
        )
        assert response.status_code == 201, response.text
        artifact_id = response.json()["id"]
        draft = await self.call(who, "GET", f"{STUDIO}/artifacts/{artifact_id}/draft")
        return artifact_id, draft.json()["id"], draft.json()["version"]

    async def seal(self, who: str, artifact_id: str, row_version: int) -> SealResult:
        async with self.artifacts.store.transaction(self.world[who].context()) as tx:
            return await self.artifacts.seal(tx, uuid.UUID(artifact_id), row_version)

    async def submit(
        self,
        who: str,
        artifact_id: str,
        version_id: str,
        etag: int | None,
        *,
        segment: str = "agents",
    ) -> httpx.Response:
        headers = {} if etag is None else {"If-Match": f'"{etag}"'}
        return await self.call(
            who,
            "POST",
            f"{STUDIO}/{segment}/{artifact_id}/versions/{version_id}/submit",
            headers=headers,
        )

    async def sql(self, statement: str, **values: Any) -> list[Any]:
        async with self.migrator.begin() as conn:
            result = await conn.execute(sa.text(statement), values)
            return list(result.all()) if result.returns_rows else []

    async def version(self, version_id: str) -> Any:
        return (
            await self.sql(
                "SELECT * FROM studio.artifact_versions WHERE id = :v", v=uuid.UUID(version_id)
            )
        )[0]

    async def audits(self, artifact_id: str, action: str) -> int:
        found = await self.sql(
            "SELECT count(*) FROM platform.audit_events WHERE resource_id = :a AND action = :x",
            a=artifact_id,
            x=action,
        )
        return int(found[0][0])


def _same(problem: dict[str, Any]) -> dict[str, Any]:
    """A problem body without what names the request itself."""
    return {k: v for k, v in problem.items() if k not in {"instance", "request_id", "trace_id"}}


def reason(response: httpx.Response) -> str | None:
    found = response.json().get("details", {}).get("reason_code")
    return None if found is None else str(found)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            world = await plant_world(conn)
        container = build_container(
            ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET),
            studio_kinds=FIXTURE_KINDS,
            studio_segments=SEGMENTS,
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


# ================================================================ submit ==


async def test_r2_1_a_submit_answers_202_with_the_version_now_evaluating(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    answer = await api.submit("writer", artifact_id, version_id, etag)

    assert answer.status_code == 202, answer.text
    body = answer.json()
    assert (body["id"], body["stage"], body["version_no"]) == (version_id, "evaluating", 1)
    assert body["definition_hash"].startswith("sha256:")
    assert await api.audits(artifact_id, "studio.version.submitted") == 1
    shown = await api.call("writer", "GET", f"{STUDIO}/artifacts/{artifact_id}")
    assert shown.json()["display_stage"] == "evaluating"


async def test_r2_13_no_if_match_is_428_and_changes_nothing(api: Api) -> None:
    artifact_id, version_id, _ = await api.create()
    answer = await api.submit("writer", artifact_id, version_id, None)
    assert answer.status_code == 428
    row = await api.version(version_id)
    assert (row.stage, row.version_no) == ("draft", None)


async def test_r2_12_a_stale_if_match_is_412_and_the_current_one_submits(api: Api) -> None:
    """The draft saved again after the submitter read it."""
    artifact_id, version_id, etag = await api.create()
    saved = await api.call(
        "co_writer",
        "PUT",
        f"{STUDIO}/artifacts/{artifact_id}/draft",
        json={"document": {"title": "sửa"}},
        headers={"If-Match": f'"{etag}"'},
    )
    assert saved.status_code == 200

    stale = await api.submit("writer", artifact_id, version_id, etag)
    assert (stale.status_code, reason(stale)) == (412, "stale_version")
    row = await api.version(version_id)
    assert (row.stage, row.version_no) == ("draft", None)
    assert await api.audits(artifact_id, "studio.version.submitted") == 0
    fresh = await api.submit("writer", artifact_id, version_id, saved.json()["version"])
    assert fresh.status_code == 202


async def test_r1_3_two_submits_at_once_give_one_202_and_one_candidate_exists(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    answers = await asyncio.gather(
        api.submit("writer", artifact_id, version_id, etag),
        api.submit("writer", artifact_id, version_id, etag),
    )
    assert sorted(a.status_code for a in answers) == [202, 409]
    refused = next(a for a in answers if a.status_code == 409)
    assert reason(refused) == "candidate_exists"
    assert await api.audits(artifact_id, "studio.version.submitted") == 1


@pytest.mark.parametrize(
    ("who", "segment", "status"),
    [
        ("reader", "agents", 403),  # reads it, lacks the kind's submit key
        ("ws2_writer", "agents", 404),  # holds the key in ws2 only
        ("writer", "workflows", 404),  # the segment names another kind
        ("writer", "objects", 404),  # not among this test's segments
    ],
)
async def test_r2_1_who_and_where_may_submit(api: Api, who: str, segment: str, status: int) -> None:
    artifact_id, version_id, etag = await api.create()
    answer = await api.submit(who, artifact_id, version_id, etag, segment=segment)
    assert answer.status_code == status, answer.text
    row = await api.version(version_id)
    assert (row.stage, row.version_no) == ("draft", None)


async def test_r2_1_a_version_not_the_artifacts_draft_is_404(api: Api) -> None:
    artifact_id, version_id, etag = await api.create()
    _, elsewhere, _ = await api.create()
    answer = await api.submit("writer", artifact_id, elsewhere, etag)
    assert answer.status_code == 404
    assert (await api.version(version_id)).version_no is None


async def test_r7_9_a_frozen_company_submits_nothing(api: Api) -> None:
    """The company's own freeze, by the switch ticket 01 built."""
    artifact_id, version_id, etag = await api.create()
    world = api.world
    switch = uuid.uuid4()
    await api.sql(
        "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action, origin,"
        " reason_code, reason, set_by) VALUES (:id, :t, 'tenant', 'freeze', 'tenant', 'test',"
        " 'thử', :u)",
        id=switch,
        t=world.tenant.tenant_id,
        u=world["writer"].id,
    )
    try:
        # The app's own controls see it once the NOTIFY drops their snapshot
        # (the 5 s TTL bounds it besides); only then is the submit sent.
        controls = api.container.run_control
        assert controls is not None
        for _ in range(100):
            if await controls.admission_state(world.tenant.tenant_id) is not None:
                break
            await asyncio.sleep(0.1)
        refused = await api.submit("writer", artifact_id, version_id, etag)
        assert (refused.status_code, reason(refused)) == (409, "tenant_frozen"), refused.text
        row = await api.version(version_id)
        assert (row.stage, row.version_no) == ("draft", None)
    finally:
        async with api.migrator.begin() as conn:
            # The trigger lets only an approved lift through; the test's row
            # goes the way the offboarding lane removes it.
            await conn.execute(
                sa.text(
                    "ALTER TABLE platform.control_switches DISABLE TRIGGER guard_control_switch"
                )
            )
            await conn.execute(
                sa.text("DELETE FROM platform.control_switches WHERE id = :id"), {"id": switch}
            )
            await conn.execute(
                sa.text("ALTER TABLE platform.control_switches ENABLE TRIGGER guard_control_switch")
            )


# ============================================================== withdraw ==


async def test_r2_4_a_candidate_is_withdrawn_by_another_holder_of_the_submit_key(
    api: Api,
) -> None:
    artifact_id, version_id, etag = await api.create(kind="fixture_gateless")
    await api.seal("writer", artifact_id, etag)
    await move_for_test(api.migrator, uuid.UUID(version_id), "awaiting_approval")
    url = f"{STUDIO}/workflows/{artifact_id}/versions/{version_id}/withdraw"

    assert (await api.call("reader", "POST", url)).status_code == 403
    # The `agents` segment names the gated kind: this candidate is not there.
    wrong = url.replace("/workflows/", "/agents/")
    assert (await api.call("co_writer", "POST", wrong)).status_code == 404
    assert (await api.version(version_id)).stage == "awaiting_approval"
    answer = await api.call("co_writer", "POST", url)

    assert answer.status_code == 200, answer.text
    assert answer.json()["stage"] == "draft"
    again = await api.call("co_writer", "POST", url)
    assert (again.status_code, reason(again)) == (409, "not_a_candidate")


# ================================================================ retire ==


async def test_r2_5_a_live_version_is_retired_and_r2_6_a_used_one_is_not(api: Api) -> None:
    target, target_v, etag = await api.create(kind="fixture_gateless")
    await api.seal("writer", target, etag)
    await publish_for_test(api.migrator, uuid.UUID(target_v))
    user, user_v, user_etag = await api.create(kind="fixture_gateless")
    saved = await api.call(
        "writer",
        "PUT",
        f"{STUDIO}/artifacts/{user}/draft",
        json={"document": {"title": "dùng", "uses": [target]}},
        headers={"If-Match": f'"{user_etag}"'},
    )
    await api.seal("writer", user, saved.json()["version"])
    await publish_for_test(api.migrator, uuid.UUID(user_v))
    url = f"{STUDIO}/workflows/{target}/versions/{target_v}/retire"

    assert (await api.call("writer", "POST", url)).status_code == 403  # no retire key
    in_use = await api.call("retirer", "POST", url)
    assert (in_use.status_code, reason(in_use)) == (409, "artifact_in_use")
    assert [d["artifact_id"] for d in in_use.json()["details"]["dependents"]] == [user]

    unused = f"{STUDIO}/workflows/{user}/versions/{user_v}/retire"
    answer = await api.call("retirer", "POST", unused)
    assert answer.status_code == 200, answer.text
    assert answer.json()["stage"] == "retired"
    again = await api.call("retirer", "POST", unused)
    assert (again.status_code, reason(again)) == (409, "not_live")
    shown = await api.call("writer", "GET", f"{STUDIO}/artifacts/{user}")
    assert shown.json()["display_stage"] == "retired"


# ==================================================== AL36: another company ==


async def test_al36_another_company_meets_every_route_as_a_random_id(api: Api) -> None:
    """Their call on our ids answers what a random id answers; nothing of ours
    moves, nothing is audited in our company."""
    drafted, draft_v, etag = await api.create()
    candidate, candidate_v, candidate_etag = await api.create()
    assert (await api.submit("writer", candidate, candidate_v, candidate_etag)).status_code == 202
    live, live_v, live_etag = await api.create(kind="fixture_gateless")
    await api.seal("writer", live, live_etag)
    await publish_for_test(api.migrator, uuid.UUID(live_v))
    before = [await api.version(v) for v in (draft_v, candidate_v, live_v)]
    audits = await api.sql("SELECT count(*) FROM platform.audit_events")

    for who, segment, artifact_id, version_id, action, headers in (
        ("outsider", "agents", drafted, draft_v, "submit", {"If-Match": f'"{etag}"'}),
        ("outsider", "agents", candidate, candidate_v, "withdraw", {}),
        ("outsider_retirer", "workflows", live, live_v, "retire", {}),
    ):
        theirs = await api.call(
            who,
            "POST",
            f"{STUDIO}/{segment}/{artifact_id}/versions/{version_id}/{action}",
            headers=headers,
        )
        random_id = await api.call(
            who,
            "POST",
            f"{STUDIO}/{segment}/{uuid.uuid4()}/versions/{uuid.uuid4()}/{action}",
            headers=headers,
        )
        assert theirs.status_code == random_id.status_code == 404, action
        assert _same(theirs.json()) == _same(random_id.json()), action

    assert [await api.version(v) for v in (draft_v, candidate_v, live_v)] == before
    assert await api.sql("SELECT count(*) FROM platform.audit_events") == audits


async def test_r1_5_the_list_and_the_read_carry_the_displayed_stage(api: Api) -> None:
    artifact_id, _, _ = await api.create()
    listed = await api.call("writer", "GET", f"{STUDIO}/artifacts", params={"limit": 200})
    stages = {i["id"]: i["display_stage"] for i in listed.json()["items"]}
    assert stages[artifact_id] == "draft"
    read = await api.call("writer", "GET", f"{STUDIO}/artifacts/{artifact_id}")
    assert read.json()["display_stage"] == "draft"
