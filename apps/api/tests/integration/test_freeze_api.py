"""A company's freeze over HTTP, against Postgres (agent-lifecycle ticket 01:
R7.4, R7.6, R7.10, R7.11, R7.1 AL16; AL12, AL16, AL18).

The real app and container: the strict prefix is the one `wiring.py` adds,
the operator routes run as `dw_provisioner`, and a decided lift is settled by
`UnfreezeSettler`, as the worker does on the decision's outbox event.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls, provisioner_url
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
    LIFECYCLE_PREFIX,
    LIFECYCLE_UNFREEZE_DECIDED,
    UnfreezeSettler,
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

SECRET = "freeze-api-secret-0123456789abcdef"
FREEZER = {
    "studio.lifecycle.freeze": "tenant",
    "approvals.decide": "workspace",
    "approvals.read": "workspace",
}
PLAIN = {"approvals.read": "workspace"}
BODY = {"reason_code": "incident", "reason": "rò rỉ dữ liệu nghi vấn"}


@dataclass(frozen=True)
class Person:
    tenant: PlantedTenant
    user: uuid.UUID


async def _people(conn: Any, **privileges: dict[str, str]) -> dict[str, Person]:
    tenant = await plant_tenant(conn)
    found: dict[str, Person] = {}
    roles: dict[str, uuid.UUID] = {}
    for name, held in privileges.items():
        key = "freezer" if "studio.lifecycle.freeze" in held else "plain"
        if key not in roles:
            roles[key] = await plant_role(
                conn, tenant.tenant_id, f"fz_{key}_{tenant.tenant_id.hex[:6]}", held
            )
        user = await plant_person(conn, tenant.tenant_id)
        membership = await plant_membership(conn, tenant.tenant_id, tenant.main, user)
        await assign(conn, tenant.tenant_id, tenant.main, membership, roles[key])
        found[name] = Person(tenant, user)
    return found


@dataclass
class Api:
    people: dict[str, Person]
    client: httpx.AsyncClient
    migrator: AsyncEngine
    sessions: async_sessionmaker[Any]
    container: ApiContainer
    operator: str

    def headers(self, who: str, key: str | None = None) -> dict[str, str]:
        person = self.people[who]
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(f'rbac-{person.user}')}",
            "X-Tenant-Id": str(person.tenant.tenant_id),
            "X-Workspace-Id": str(person.tenant.main),
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    async def freeze(self, who: str, key: str | None = None) -> httpx.Response:
        return await self.client.post(
            "/api/v1/admin/freeze", json=BODY, headers=self.headers(who, key)
        )

    async def unfreeze(self, who: str, key: str | None = None) -> httpx.Response:
        return await self.client.post("/api/v1/admin/unfreeze", headers=self.headers(who, key))

    async def state(self, who: str) -> httpx.Response:
        return await self.client.get("/api/v1/control-state", headers=self.headers(who))

    async def decide(self, who: str, approval: str) -> httpx.Response:
        return await self.client.post(
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": True, "comment": "đã xác minh sự cố đã xử lý"},
            headers=self.headers(who),
        )

    async def as_operator(self, path: str, body: Any = None) -> httpx.Response:
        token = DevTokenVerifier(SECRET).issue(self.operator)
        return await self.client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})

    async def settle(self, who: str, approval: str) -> str:
        """What the worker does with the decision's outbox event."""
        async with self.migrator.connect() as conn:
            payload = await conn.scalar(
                sa.text(
                    "SELECT payload FROM platform.outbox_events WHERE event_type = :e"
                    " AND aggregate_id = :a"
                ),
                {"e": LIFECYCLE_UNFREEZE_DECIDED, "a": uuid.UUID(approval)},
            )
        assert payload is not None, "the decision announced nothing"
        person = self.people[who]
        settler = UnfreezeSettler(
            repo=SqlControlSwitchRepository(self.sessions),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        )
        scope = WorkScope(tenant_id=person.tenant.tenant_id, workspace_id=person.tenant.main)
        return await settler.settle(scope, uuid.UUID(payload["approval_id"]))

    async def rows(self, sql: str, **values: Any) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list((await conn.execute(sa.text(sql), values)).all())

    async def audits(self, who: str, action: str) -> list[Any]:
        return await self.rows(
            "SELECT actor_id, resource_id, details FROM platform.audit_events"
            " WHERE tenant_id = :t AND action = :a",
            t=self.people[who].tenant.tenant_id,
            a=action,
        )

    async def switches(self, who: str) -> list[Any]:
        return await self.rows(
            "SELECT id, origin, lifted_at, lifted_by, lift_approval_id"
            " FROM platform.control_switches WHERE tenant_id = :t ORDER BY set_at",
            t=self.people[who].tenant.tenant_id,
        )


@pytest.fixture
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    operator = uuid.uuid4()
    async with migrator.begin() as conn:
        people = {
            **await _people(conn, asker=FREEZER, decider=FREEZER, plain=PLAIN),
            **await _people(conn, outsider=FREEZER, outsider_decider=FREEZER),
        }
        await conn.execute(
            sa.text("INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'Op')"),
            {"u": operator, "s": f"op-{operator}"},
        )
        await conn.execute(
            sa.text("INSERT INTO platform.platform_operators (user_id) VALUES (:u)"),
            {"u": operator},
        )
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            provisioner_database_url=provisioner_url(api_db.migrator),
            dev_secret=SECRET,
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
                yield Api(people, client, migrator, sessions, container, f"op-{operator}")
    finally:
        await container.engine.dispose()
        if container.provisioner_engine is not None:
            await container.provisioner_engine.dispose()
        await migrator.dispose()


def _reason(response: httpx.Response) -> object:
    return response.json().get("details", {}).get("reason_code")


# ---- R7.6, R7.10: one person freezes, one audit --------------------------------------


async def test_a_freeze_is_set_by_one_person_with_one_audit_and_never_twice(api: Api) -> None:
    """R7.6, R7.10 (AL18): 201 with the switch, one `control.freeze.set`
    carrying ids and codes; a second freeze is 409 `already_frozen` and the
    rolled-back attempt leaves no audit."""
    first = await api.freeze("asker", key="k-1")
    assert first.status_code == 201, first.text
    switch = first.json()["switch_id"]
    [audit] = await api.audits("asker", "control.freeze.set")
    assert (audit.actor_id, audit.resource_id) == (api.people["asker"].user, switch)
    assert audit.details == {"reason_code": "incident"}

    second = await api.freeze("decider")
    assert second.status_code == 409 and _reason(second) == "already_frozen"
    assert len(await api.audits("asker", "control.freeze.set")) == 1

    replay = await api.freeze("asker", key="k-1")
    assert replay.status_code == 201 and replay.json()["switch_id"] == switch


async def test_a_member_without_the_key_can_neither_freeze_nor_ask_to_lift(api: Api) -> None:
    for response in (await api.freeze("plain"), await api.unfreeze("plain")):
        assert response.status_code == 403, response.text
    assert await api.switches("plain") == []


# ---- R7.10, R7.11: lifted by a second person -----------------------------------------


async def test_a_freeze_is_lifted_only_when_another_person_approves_its_request(
    api: Api,
) -> None:
    """R7.10, R7.11 (AL18): the request names the switch and lifts nothing;
    a second request while it waits is 409 `lift_pending`; its requester
    deciding it is 409 `second_person_required` and the freeze holds; the
    other person's approval, settled, lifts it with `lift_approval_id` and an
    audit in the decider's name; the event delivered again changes nothing."""
    switch = (await api.freeze("asker")).json()["switch_id"]
    asked = await api.unfreeze("asker")
    assert asked.status_code == 202, asked.text
    approval = asked.json()["approval_id"]
    [request] = await api.rows(
        "SELECT approval_type, payload, required_scope, status FROM platform.approval_requests"
        " WHERE id = :a",
        a=uuid.UUID(approval),
    )
    assert (request.approval_type, request.payload) == (
        "studio.lifecycle.unfreeze",
        {"switch_id": switch},
    )
    assert (request.required_scope, request.status) == ("studio.lifecycle.freeze", "pending")
    assert (await api.switches("asker"))[0].lifted_at is None

    again = await api.unfreeze("decider")
    assert again.status_code == 409 and _reason(again) == "lift_pending"

    own = await api.decide("asker", approval)
    assert own.status_code == 409 and _reason(own) == "second_person_required"
    assert (await api.switches("asker"))[0].lifted_at is None

    decided = await api.decide("decider", approval)
    assert decided.status_code == 200, decided.text
    assert await api.settle("asker", approval) == "lifted"
    [row] = await api.switches("asker")
    assert row.lifted_at is not None
    assert (row.lifted_by, str(row.lift_approval_id)) == (api.people["decider"].user, approval)
    [audit] = await api.audits("asker", "control.freeze.lifted")
    assert audit.actor_id == api.people["decider"].user
    assert audit.details["lane"] == "outbox"

    assert await api.settle("asker", approval) == "already_lifted"
    assert len(await api.audits("asker", "control.freeze.lifted")) == 1
    assert (await api.state("asker")).json()["state"] == "open"


async def test_two_concurrent_lift_requests_open_one_approval(api: Api) -> None:
    """R7.10 (AL18): different keys at once, one 202 and one 409 `lift_pending`."""
    await api.freeze("asker")
    answers = await asyncio.gather(api.unfreeze("asker", key="a"), api.unfreeze("decider", key="b"))
    assert sorted(r.status_code for r in answers) == [202, 409]
    assert [_reason(r) for r in answers if r.status_code == 409] == ["lift_pending"]
    pending = await api.rows(
        "SELECT id FROM platform.approval_requests WHERE tenant_id = :t"
        " AND approval_type = 'studio.lifecycle.unfreeze'",
        t=api.people["asker"].tenant.tenant_id,
    )
    assert len(pending) == 1


async def test_nothing_to_lift_is_409_not_frozen(api: Api) -> None:
    response = await api.unfreeze("asker")
    assert response.status_code == 409 and _reason(response) == "not_frozen"


async def test_the_lifecycle_prefix_is_strict_in_the_apis_decision_door(api: Api) -> None:
    """R7.11 (AL18), the API's half: the worker's is `test_channel_commands`."""
    assert api.container.approval_flow is not None
    assert LIFECYCLE_PREFIX in api.container.approval_flow.strict_approval_prefixes


# ---- R7.4: the operator's freeze is not the company's to lift -------------------------


async def test_a_company_cannot_lift_an_operators_freeze_and_lifting_its_own_leaves_it(
    api: Api,
) -> None:
    """R7.4 (AL12): only the operator's freeze open, the company's request is
    403 and lifts nothing; with both open, the company lifts its own and the
    operator's still holds the company."""
    tenant = api.people["asker"].tenant.tenant_id
    operator = await api.as_operator(f"/api/v1/platform/tenants/{tenant}/freeze", BODY)
    assert operator.status_code == 201, operator.text

    refused = await api.unfreeze("asker")
    assert refused.status_code == 403
    assert (await api.state("plain")).json()["freezes"][0]["origin"] == "platform"

    await api.freeze("asker")
    approval = (await api.unfreeze("asker")).json()["approval_id"]
    await api.decide("decider", approval)
    assert await api.settle("asker", approval) == "lifted"

    rows = await api.switches("asker")
    assert {(r.origin, r.lifted_at is None) for r in rows} == {
        ("platform", True),
        ("tenant", False),
    }
    state = (await api.state("asker")).json()
    assert state["state"] == "tenant_frozen"
    assert [f["origin"] for f in state["freezes"]] == ["platform"]

    lifted = await api.as_operator(f"/api/v1/platform/tenants/{tenant}/unfreeze")
    assert lifted.status_code == 200, lifted.text
    assert (await api.state("asker")).json()["state"] == "open"
    actions = [
        r.action
        for r in await api.rows(
            "SELECT action FROM platform.provisioning_audit WHERE details->>'tenant_id' = :t"
            " ORDER BY occurred_at",
            t=str(tenant),
        )
    ]
    assert actions == ["platform.tenant_freeze.set", "platform.tenant_freeze.lifted"]


async def test_the_operator_routes_refuse_a_member_and_answer_codes(api: Api) -> None:
    member = await api.client.post(
        "/api/v1/platform/freeze", json=BODY, headers=api.headers("asker")
    )
    assert member.status_code == 403
    unknown = await api.as_operator(f"/api/v1/platform/tenants/{uuid.uuid4()}/freeze", BODY)
    assert unknown.status_code == 404
    nothing = await api.as_operator("/api/v1/platform/unfreeze")
    assert nothing.status_code == 409 and _reason(nothing) == "not_frozen"


async def test_a_platform_freeze_holds_every_company_until_the_operator_lifts_it(
    api: Api,
) -> None:
    """R7.4: set and lifted by the operator, audited in the provisioning
    record; a second is 409 `already_frozen`."""
    set_ = await api.as_operator("/api/v1/platform/freeze", BODY)
    assert set_.status_code == 201, set_.text
    try:
        again = await api.as_operator("/api/v1/platform/freeze", BODY)
        assert again.status_code == 409 and _reason(again) == "already_frozen"
        for who in ("asker", "outsider"):
            assert (await api.state(who)).json()["state"] == "platform_frozen"
    finally:
        lifted = await api.as_operator("/api/v1/platform/unfreeze")
    assert lifted.status_code == 200 and lifted.json()["id"] == set_.json()["id"]
    actions = [
        r.action
        for r in await api.rows(
            "SELECT action FROM platform.provisioning_audit WHERE target_id = :f",
            f=set_.json()["id"],
        )
    ]
    assert sorted(actions) == ["platform.freeze.lifted", "platform.freeze.set"]


# ---- AL16: one company's freeze is its own ----------------------------------------------


async def test_another_companys_freeze_is_neither_seen_nor_lifted(api: Api) -> None:
    """R7.1 (AL16): B frozen, A's control state is open and A's request to
    lift finds nothing to lift; B's row is untouched."""
    await api.freeze("outsider")
    state = await api.state("asker")
    assert state.status_code == 200
    assert state.json() == {"state": "open", "platform_freeze": None, "freezes": []}

    response = await api.unfreeze("asker")
    assert response.status_code == 409 and _reason(response) == "not_frozen"
    assert [r.lifted_at for r in await api.switches("outsider")] == [None]
