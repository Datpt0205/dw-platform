"""A component's kill and its revive over HTTP, against Postgres
(agent-lifecycle ticket 05: R8.1, R8.6-R8.8; AL14, AL16).

The real app and container: `studio.lifecycle.` is strict at the API's
composition root, the kill route and the revive request are the Studio
group's, a decision goes through `/api/v1/approvals/{id}/decisions`, and a
decided revive is settled by `SwitchLiftSettler` (`REVIVE_LIFT`), as the
worker does on the decision's outbox event.

A company with two workspaces: `killer` and `decider` hold the workflow read
key, `studio.lifecycle.kill` and the approval keys at workspace depth in
`ws1`; `reader` only reads there; `outsider` holds all of it in another
company. Workflows are planted as the migrator in `ws1` and `ws2`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.control_switches_repo import SqlControlSwitchRepository
from dw_platform.application.control_switches import (
    CONTROL_SWITCH_CHANGED,
    LIFECYCLE_KILL_SCOPE,
    LIFECYCLE_REVIVE,
    LIFECYCLE_REVIVE_DECIDED,
    REVIVE_LIFT,
    SwitchLiftSettler,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import APPROVALS_DECIDE
from dw_platform.domain.outbox import OutboxEvent
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.kinds import WORKFLOWS_READ_SCOPE
from dw_studio.lifecycle.application.kill import KillSwitchService
from dw_studio.testing.workflows import plant_holder
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "kill-api-secret-0123456789abcdef"
STUDIO = "/api/v1/studio"
KILLER = (WORKFLOWS_READ_SCOPE, LIFECYCLE_KILL_SCOPE, APPROVALS_DECIDE, "approvals.read")
BODY = {"reason_code": "incident", "reason": "gửi nhầm tin cho khách"}


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    sessions: async_sessionmaker[Any]
    tenant: PlantedTenant
    other: PlantedTenant
    people: dict[str, Person]

    async def call(
        self, who: str, method: str, url: str, key: str | None = None, **kw: Any
    ) -> httpx.Response:
        person = self.people[who]
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(person.subject)}",
            "X-Tenant-Id": str(person.tenant_id),
            "X-Workspace-Id": str(person.workspace_id),
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.request(method, url, headers=headers, **kw)

    async def kill(
        self, who: str, artifact: uuid.UUID, segment: str = "workflows", key: str | None = None
    ) -> httpx.Response:
        return await self.call(
            who, "POST", f"{STUDIO}/{segment}/{artifact}/kill", key=key, json=BODY
        )

    async def revive(self, who: str, artifact: uuid.UUID) -> httpx.Response:
        return await self.call(who, "POST", f"{STUDIO}/workflows/{artifact}/revive-requests")

    async def decide(self, who: str, approval: str, *, approve: bool = True) -> httpx.Response:
        return await self.call(
            who,
            "POST",
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": approve, "comment": "đã kiểm tra bản sửa"},
        )

    async def settle(self, approval: str) -> str:
        """What the worker does with the decision's outbox event."""
        [event] = await self.rows(
            "SELECT payload FROM platform.outbox_events WHERE event_type = :e"
            " AND aggregate_id = :a",
            e=LIFECYCLE_REVIVE_DECIDED,
            a=uuid.UUID(approval),
        )
        settler = SwitchLiftSettler(
            repo=SqlControlSwitchRepository(self.sessions),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
            lift=REVIVE_LIFT,
        )
        scope = WorkScope(tenant_id=self.tenant.tenant_id, workspace_id=self.tenant.main)
        return await settler.settle(scope, uuid.UUID(event.payload["approval_id"]))

    async def rows(self, sql: str, **values: Any) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list((await conn.execute(sa.text(sql), values)).all())

    async def workflow(self, workspace: uuid.UUID) -> uuid.UUID:
        artifact = uuid.uuid4()
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name,"
                    " owning_workspace_id, row_version) VALUES (:a, :t, 'workflow', :n, :w, 1)"
                ),
                {
                    "a": artifact,
                    "t": self.tenant.tenant_id,
                    "n": f"qt_{artifact.hex[:12]}",
                    "w": workspace,
                },
            )
        return artifact

    async def switches(self, artifact: uuid.UUID) -> list[Any]:
        return await self.rows(
            "SELECT id, tenant_id, scope_type, owning_workspace_id, action, origin, set_by,"
            " lifted_at, lifted_by, lift_approval_id FROM platform.control_switches"
            " WHERE target_id = :a ORDER BY set_at",
            a=artifact,
        )

    async def audits(self, action: str, resource: Any) -> list[Any]:
        return await self.rows(
            "SELECT tenant_id, workspace_id, actor_id, details FROM platform.audit_events"
            " WHERE action = :a AND resource_id = :r",
            a=action,
            r=str(resource),
        )

    async def changes(self, switch: Any) -> list[Any]:
        return await self.rows(
            "SELECT tenant_id, workspace_id, schema_version, payload, actor_id"
            " FROM platform.outbox_events WHERE event_type = :e AND aggregate_id = :s",
            e=CONTROL_SWITCH_CHANGED,
            s=uuid.UUID(str(switch)),
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        other = await plant_tenant(conn)
        ws1 = tenant.workspaces[0]
        people = {
            "killer": await plant_holder(conn, tenant, KILLER, workspace=ws1),
            "decider": await plant_holder(conn, tenant, KILLER, workspace=ws1),
            "reader": await plant_holder(conn, tenant, (WORKFLOWS_READ_SCOPE,), workspace=ws1),
            "outsider": await plant_holder(conn, other, KILLER),
        }
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            # The runtime seam, which builds the approval flow decisions go through.
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    assert container.engine is not None and container.studio is not None
    sessions = async_sessionmaker(container.engine, expire_on_commit=False)
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                yield Api(client, container, migrator, sessions, tenant, other, people)
    finally:
        await container.engine.dispose()
        await migrator.dispose()


def reason(response: httpx.Response) -> str | None:
    details: dict[str, Any] = response.json().get("details") or {}
    return details.get("reason_code")


# ---- R8.1, R8.8: kill ---------------------------------------------------------------


async def test_r8_1_a_kill_writes_its_switch_one_audit_and_one_event_and_a_second_is_409(
    api: Api,
) -> None:
    artifact = await api.workflow(api.tenant.main)
    killed = await api.kill("killer", artifact)
    assert killed.status_code == 201, killed.text
    switch = killed.json()["switch_id"]

    [row] = await api.switches(artifact)
    assert str(row.id) == switch
    assert (row.tenant_id, row.scope_type, row.owning_workspace_id) == (
        api.tenant.tenant_id,
        "workflow",
        api.tenant.main,
    )
    assert (row.action, row.origin, row.set_by, row.lifted_at) == (
        "kill",
        "tenant",
        api.people["killer"].id,
        None,
    )
    [audit] = await api.audits("control.kill.set", switch)
    assert audit.actor_id == api.people["killer"].id
    assert audit.details == {
        "reason_code": "incident",
        "artifact_id": str(artifact),
        "kind": "workflow",
    }
    [event] = await api.changes(switch)
    assert event.payload == {"tenant_id": str(api.tenant.tenant_id), "switch_id": switch}
    assert (event.schema_version, event.workspace_id) == ("1", api.tenant.main)

    again = await api.kill("decider", artifact)
    assert again.status_code == 409, again.text
    assert reason(again) == "already_killed"
    assert len(await api.audits("control.kill.set", switch)) == 1
    assert len(await api.switches(artifact)) == 1


async def test_r8_1_a_retried_key_answers_the_same_switch_once(api: Api) -> None:
    artifact = await api.workflow(api.tenant.main)
    key = f"kill-{uuid.uuid4().hex}"
    first = await api.kill("killer", artifact, key=key)
    second = await api.kill("killer", artifact, key=key)
    assert (first.status_code, second.status_code) == (201, 201), second.text
    assert first.json() == second.json()
    assert len(await api.switches(artifact)) == 1


async def test_al16_another_company_or_another_workspace_is_404_and_writes_nothing(
    api: Api,
) -> None:
    """AL16: the outsider holds every key in their own company; `killer` holds
    the keys at workspace depth in ws1, not ws2; neither learns the component
    exists, as with a random id. Without the depth filter the ws2 case is red."""
    in_ws1 = await api.workflow(api.tenant.main)
    in_ws2 = await api.workflow(api.tenant.workspaces[1])
    cases = [
        await api.kill("outsider", in_ws1),
        await api.call("outsider", "POST", f"{STUDIO}/workflows/{in_ws1}/revive-requests"),
        await api.kill("killer", in_ws2),
        await api.revive("killer", in_ws2),
        await api.kill("killer", uuid.uuid4()),
    ]
    assert [c.status_code for c in cases] == [404] * 5, [c.text for c in cases]
    assert await api.switches(in_ws1) == [] and await api.switches(in_ws2) == []
    assert (
        await api.rows(
            "SELECT 1 FROM platform.audit_events WHERE tenant_id = :t"
            " AND action LIKE 'control.kill%' AND details->>'artifact_id' IN (:a, :b)",
            t=api.tenant.tenant_id,
            a=str(in_ws1),
            b=str(in_ws2),
        )
        == []
    )


async def test_al16_a_workflow_under_the_agents_segment_is_404(api: Api) -> None:
    artifact = await api.workflow(api.tenant.main)
    refused = await api.kill("killer", artifact, segment="agents")
    assert refused.status_code == 404, refused.text
    assert await api.switches(artifact) == []


async def test_r8_1_a_reader_without_the_key_is_403(api: Api) -> None:
    artifact = await api.workflow(api.tenant.main)
    assert (await api.kill("reader", artifact)).status_code == 403
    assert (await api.revive("reader", artifact)).status_code == 403
    assert await api.switches(artifact) == []


class _AnnounceFailedError(Exception):
    pass


@dataclass
class _Switches:
    inner: Any

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def announce(self, event: OutboxEvent) -> None:
        raise _AnnounceFailedError


@dataclass
class _Tx:
    envelope: Any
    switches: Any


@dataclass
class _FailingStore:
    """The kill's store, its outbox write failing after the switch and audit."""

    inner: Any

    @asynccontextmanager
    async def transaction(self, context: Any) -> AsyncIterator[_Tx]:
        async with self.inner.transaction(context) as tx:
            yield _Tx(tx.envelope, _Switches(tx.switches))


async def test_r8_8_a_kill_rolled_back_leaves_no_switch_and_no_audit(api: Api) -> None:
    assert api.container.studio is not None
    real = api.container.studio.kill_switches
    failing = KillSwitchService(_FailingStore(real.store), real.artifacts, real.clock, real.ids)
    artifact = await api.workflow(api.tenant.main)
    with pytest.raises(_AnnounceFailedError):
        await failing.kill(
            api.people["killer"].context(), "workflow", artifact, reason_code="test", reason="x"
        )
    assert await api.switches(artifact) == []
    assert (
        await api.rows(
            "SELECT 1 FROM platform.audit_events WHERE action = 'control.kill.set'"
            " AND details->>'artifact_id' = :a",
            a=str(artifact),
        )
        == []
    )


# ---- R8.6, R8.7: revive -------------------------------------------------------------


async def test_r8_6_a_revive_needs_a_kill_and_waits_once(api: Api) -> None:
    artifact = await api.workflow(api.tenant.main)
    not_killed = await api.revive("killer", artifact)
    assert not_killed.status_code == 409 and reason(not_killed) == "not_killed"

    switch = (await api.kill("killer", artifact)).json()["switch_id"]
    asked = await api.revive("killer", artifact)
    assert asked.status_code == 202, asked.text
    approval = asked.json()["approval_id"]
    assert asked.headers["Location"] == f"/api/v1/approvals/{approval}"
    [request] = await api.rows(
        "SELECT approval_type, required_scope, payload, workspace_id, run_id, status,"
        " requested_by FROM platform.approval_requests WHERE id = :a",
        a=uuid.UUID(approval),
    )
    assert (request.approval_type, request.required_scope) == (
        LIFECYCLE_REVIVE,
        LIFECYCLE_KILL_SCOPE,
    )
    assert request.payload == {"switch_id": switch}
    assert (request.workspace_id, request.run_id, request.status) == (
        api.tenant.main,
        None,
        "pending",
    )

    pending = await api.revive("decider", artifact)
    assert pending.status_code == 409 and reason(pending) == "lift_pending"


async def test_r8_7_the_asker_deciding_is_409_second_person_required_and_nothing_lifts(
    api: Api,
) -> None:
    artifact = await api.workflow(api.tenant.main)
    await api.kill("killer", artifact)
    approval = (await api.revive("killer", artifact)).json()["approval_id"]
    own = await api.decide("killer", approval)
    assert own.status_code == 409, own.text
    assert reason(own) == "second_person_required"
    [row] = await api.switches(artifact)
    assert row.lifted_at is None


async def test_r8_6_a_second_person_revives_exactly_that_switch_and_a_replay_lifts_no_new_one(
    api: Api,
) -> None:
    """P kills, asks; Q approves; the settlement lifts the switch with
    `lift_approval_id`, audits `control.kill.lifted` as Q with `details.lane`
    and announces the change. P kills again; the old decision delivered again
    leaves the new switch open."""
    artifact = await api.workflow(api.tenant.main)
    first = (await api.kill("killer", artifact)).json()["switch_id"]
    approval = (await api.revive("killer", artifact)).json()["approval_id"]
    decided = await api.decide("decider", approval)
    assert decided.status_code == 200, decided.text
    assert await api.settle(approval) == "lifted"

    [row] = await api.switches(artifact)
    assert (row.lifted_by, str(row.lift_approval_id)) == (api.people["decider"].id, approval)
    [audit] = await api.audits("control.kill.lifted", first)
    assert audit.actor_id == api.people["decider"].id
    assert audit.details["lane"] == "outbox"
    assert audit.details["requested_by"] == str(api.people["killer"].id)
    assert len(await api.changes(first)) == 2

    second = (await api.kill("killer", artifact)).json()["switch_id"]
    assert await api.settle(approval) == "already_lifted"
    rows = await api.switches(artifact)
    assert [str(r.id) for r in rows] == [first, second]
    assert rows[1].lifted_at is None
    assert len(await api.audits("control.kill.lifted", first)) == 1


async def test_r8_6_a_rejected_revive_leaves_the_kill_and_writes_no_lift(api: Api) -> None:
    artifact = await api.workflow(api.tenant.main)
    switch = (await api.kill("killer", artifact)).json()["switch_id"]
    approval = (await api.revive("killer", artifact)).json()["approval_id"]
    rejected = await api.decide("decider", approval, approve=False)
    assert rejected.status_code == 200, rejected.text
    assert await api.settle(approval) == "rejected"
    [row] = await api.switches(artifact)
    assert row.lifted_at is None
    assert await api.audits("control.kill.lifted", switch) == []
    assert len(await api.changes(switch)) == 1
