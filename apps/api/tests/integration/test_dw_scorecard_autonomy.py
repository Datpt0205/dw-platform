"""A Digital Worker's scorecard and the raising and lowering of its earned
levels, over HTTP, against Postgres (digital-worker ticket 03).

R7.1, R7.2 (the scorecard from data, its window), R8.1-R8.6 and DWK17-DWK20
(lower now, raise through a second person, settle without overwriting a
lowering). The real app and container, so the raise's decider rule is the one
`runtime.py` registers; the settlement is the worker's `RaiseSettler` over
the same database, fed the outbox row the decision wrote.
"""

from __future__ import annotations

import asyncio
import json
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
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.digital_workers_repo import SqlDecisionLevels
from dw_platform.adapters.persistence.dw_autonomy_repo import SqlDwAutonomyRepository
from dw_platform.application.digital_workers import DecisionAutonomy
from dw_platform.application.dw_autonomy import DW_AUTONOMY_RAISE_DECIDED, RaiseSettler
from dw_platform.application.work_queue import WorkScope

pytestmark = pytest.mark.integration

SECRET = "integration-secret-0123456789abcdef0123"


@dataclass
class World:
    tenant: uuid.UUID
    workspace: uuid.UUID
    other_tenant: uuid.UUID
    other_workspace: uuid.UUID
    dw: uuid.UUID
    principal: uuid.UUID
    other_dw: uuid.UUID
    other_principal: uuid.UUID
    users: dict[str, uuid.UUID]


async def _x(conn: Any, sql: str, **values: Any) -> None:
    await conn.execute(sa.text(sql), values)


async def _user(conn: Any, tenant: uuid.UUID, workspace: uuid.UUID) -> uuid.UUID:
    user = uuid.uuid4()
    await _x(
        conn,
        "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'p')",
        u=user,
        s=f"it-{user}",
    )
    await _x(
        conn,
        "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
        " VALUES (:i, :t, :w, :u, '[\"approver\"]'::jsonb)",
        i=uuid.uuid4(),
        t=tenant,
        w=workspace,
        u=user,
    )
    return user


async def _dw(
    conn: Any, world: World, key: str, people: dict[str, uuid.UUID]
) -> tuple[uuid.UUID, uuid.UUID]:
    dw, principal = uuid.uuid4(), uuid.uuid4()
    t, w = world.tenant, world.workspace
    await _x(
        conn,
        "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
        " VALUES (:u, :s, 'dw', 'service', :t)",
        u=principal,
        s=f"service:{principal}",
        t=t,
    )
    await _x(
        conn,
        "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id, name,"
        " owner_user_id) VALUES (:u, :t, :w, 'dw', :o)",
        u=principal,
        t=t,
        w=w,
        o=people["bo"],
    )
    await _x(
        conn,
        "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id, principal_user_id,"
        " key, name, mandate, work_kinds, allowed_tools, workflow_key, workflow_version, state,"
        " technical_owner_id, work_assigner_id, validator_id, created_by) VALUES (:d, :t, :w, :u,"
        " :k, 'Chăm sóc lead', 'dw', ARRAY['lead.new'], ARRAY[]::text[], 'lead_care', '1.0.0',"
        " 'operating', :to, :bo, :v, :bo)",
        d=dw,
        t=t,
        w=w,
        u=principal,
        k=key,
        to=people["to"],
        bo=people["bo"],
        v=people["validator"],
    )
    for cls, effect, ceiling, earned in (
        ("email.send", "external", "A3", "A2"),
        ("note.write", "internal", "A4", "A3"),
    ):
        await _x(
            conn,
            "INSERT INTO platform.dw_decision_classes (dw_id, key, tenant_id, workspace_id,"
            " effect_level, reversible, ceiling, earned_level) VALUES (:d, :k, :t, :w, :e, false,"
            " :c, :l)",
            d=dw,
            k=cls,
            t=t,
            w=w,
            e=effect,
            c=ceiling,
            l=earned,
        )
    return dw, principal


async def build_world(migrator: AsyncEngine) -> World:
    t, w, t2, w2 = (uuid.uuid4() for _ in range(4))
    async with migrator.begin() as conn:
        for tenant, workspace in ((t, w), (t2, w2)):
            await _x(
                conn,
                "INSERT INTO platform.tenants (id, slug, name, status)"
                " VALUES (:t, :s, :s, 'active')",
                t=tenant,
                s=f"sc-{tenant.hex[:12]}",
            )
            await _x(
                conn,
                "INSERT INTO platform.entitlements (id, tenant_id, plan_id) VALUES (:i, :t,"
                " 'professional')",
                i=uuid.uuid4(),
                t=tenant,
            )
            await _x(
                conn,
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name) VALUES (:w, :t, 'm',"
                " 'm')",
                w=workspace,
                t=tenant,
            )
        users = {name: await _user(conn, t, w) for name in ("bo", "to", "validator", "outsider")}
        users["stranger"] = await _user(conn, t2, w2)
        world = World(t, w, t2, w2, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), users)
        world.dw, world.principal = await _dw(conn, world, f"dw_{t.hex[:8]}", users)
        world.other_dw, world.other_principal = await _dw(conn, world, f"ow_{t.hex[:8]}", users)
    return world


@dataclass
class Harness:
    world: World
    client: httpx.AsyncClient
    migrator: AsyncEngine
    settler: RaiseSettler
    autonomy: DecisionAutonomy

    def headers(self, who: str, *, key: str | None = None) -> dict[str, str]:
        user = self.world.users[who]
        stranger = who == "stranger"
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(f'it-{user}')}",
            "X-Tenant-Id": str(self.world.other_tenant if stranger else self.world.tenant),
            "X-Workspace-Id": str(self.world.other_workspace if stranger else self.world.workspace),
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    async def change(self, who: str, cls: str, level: str, **kw: Any) -> httpx.Response:
        return await self.client.post(
            f"/api/v1/digital-workers/{self.world.dw}/decision-classes/{cls}/autonomy",
            json={"level": level},
            headers=self.headers(who, **kw),
        )

    async def decide(
        self, who: str, approval: str, *, approve: bool = True, comment: str = "đủ dữ liệu"
    ) -> httpx.Response:
        return await self.client.post(
            f"/api/v1/approvals/{approval}/decisions",
            json={"approve": approve, "comment": comment},
            headers=self.headers(who),
        )

    async def scorecard(self, who: str = "bo", **params: Any) -> httpx.Response:
        return await self.client.get(
            f"/api/v1/digital-workers/{self.world.dw}/scorecard",
            params=params,
            headers=self.headers(who),
        )

    async def earned(self, cls: str) -> str:
        async with self.migrator.connect() as conn:
            return str(
                await conn.scalar(
                    sa.text(
                        "SELECT earned_level FROM platform.dw_decision_classes"
                        " WHERE dw_id = :d AND key = :k"
                    ),
                    {"d": self.world.dw, "k": cls},
                )
            )

    async def count(self, sql: str, **values: Any) -> int:
        async with self.migrator.connect() as conn:
            return int(await conn.scalar(sa.text(sql), values) or 0)

    async def audits(self, action: str) -> list[Any]:
        async with self.migrator.connect() as conn:
            return list(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT actor_id, details FROM platform.audit_events"
                            " WHERE tenant_id = :t AND action = :a ORDER BY occurred_at"
                        ),
                        {"t": self.world.tenant, "a": action},
                    )
                ).all()
            )

    async def raises(self) -> int:
        return await self.count(
            "SELECT count(*) FROM platform.approval_requests WHERE tenant_id = :t"
            " AND approval_type = 'dw.autonomy.raise'",
            t=self.world.tenant,
        )

    async def settle(self, approval: str) -> str:
        """What the worker does with the decision's outbox event."""
        async with self.migrator.connect() as conn:
            payload = await conn.scalar(
                sa.text(
                    "SELECT payload FROM platform.outbox_events WHERE event_type = :e"
                    " AND aggregate_id = :a"
                ),
                {"e": DW_AUTONOMY_RAISE_DECIDED, "a": uuid.UUID(approval)},
            )
        assert payload is not None, "the decision announced nothing"
        scope = WorkScope(tenant_id=self.world.tenant, workspace_id=self.world.workspace)
        settled = await self.settler.settle_raise(scope, uuid.UUID(payload["approval_id"]))
        return settled.outcome


@pytest.fixture
async def harness(api_db: DatabaseUrls) -> AsyncIterator[Harness]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    container = build_container(
        ApiSettings(
            profile="test",
            database_url=api_db.app,
            dev_secret=SECRET,
            # The agent runtime, which the DW routes are wired with, composes
            # over lazy clients: a placeholder store is enough, nothing here
            # touches it (as `test_memory_review_wiring.py` builds it).
            s3_endpoint_url="http://localhost:9000",
            s3_access_key="placeholder",
            s3_secret_key="placeholder",
            model_provider="mock",
        )
    )
    assert container.engine is not None and container.approval_flow is not None
    sessions = async_sessionmaker(container.engine, expire_on_commit=False)
    world = await build_world(migrator)
    app = create_app(container)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://it") as client:
                yield Harness(
                    world,
                    client,
                    migrator,
                    RaiseSettler(
                        repo=SqlDwAutonomyRepository(sessions),
                        clock=SystemClock(),
                        id_generator=Uuid4Generator(),
                    ),
                    DecisionAutonomy(SqlDecisionLevels(sessions)),
                )
    finally:
        await container.engine.dispose()
        await migrator.dispose()


def _reason(response: httpx.Response) -> str | None:
    return response.json().get("details", {}).get("reason_code")


# ---------------------------------------------------------------------------
# R7: the scorecard
# ---------------------------------------------------------------------------


async def _item(conn: Any, world: World, dw: uuid.UUID, status: str, **kw: Any) -> None:
    await _x(
        conn,
        "INSERT INTO platform.work_items (id, tenant_id, workspace_id, dw_id, kind, source_key,"
        " payload, payload_hash, holder_kind, holder_id, status, available_at, handoff,"
        " created_at, updated_at, closed_at) VALUES (:i, :t, :w, :d, 'lead.new', :s,"
        " '{}'::jsonb, repeat('0', 64), 'digital_worker', :d, :st, now(), CAST(:h AS jsonb),"
        " now() - :age * interval '1 day', now(),"
        " CASE WHEN :st IN ('done', 'failed', 'cancelled') THEN now() END)",
        i=uuid.uuid4(),
        t=world.tenant,
        w=world.workspace,
        d=dw,
        s=uuid.uuid4().hex,
        st=status,
        h=json.dumps(kw["handoff"]) if "handoff" in kw else None,
        age=kw.get("age", 1),
    )


async def _decision(
    conn: Any, world: World, dw: uuid.UUID, outcome: str, *, edited: bool = False, age: int = 1
) -> None:
    request = uuid.uuid4()
    await _x(
        conn,
        "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id, approval_type,"
        " requested_by, payload, status, decided_at) VALUES (:r, :t, :w, 'dw.decision', :p,"
        " CAST(:pl AS jsonb), :o, now() - :age * interval '1 day')",
        r=request,
        t=world.tenant,
        w=world.workspace,
        p=world.principal,
        pl=json.dumps({"dw_id": str(dw), "decision_class": "email.send"}),
        o=outcome,
        age=age,
    )
    await _x(
        conn,
        "INSERT INTO platform.approval_decisions (id, request_id, tenant_id, workspace_id,"
        " decided_by, outcome, decided_at, edited, edited_payload) VALUES (:i, :r, :t, :w, :v, :o,"
        " now() - :age * interval '1 day', :e, CAST(:ep AS jsonb))",
        i=uuid.uuid4(),
        r=request,
        t=world.tenant,
        w=world.workspace,
        v=world.users["validator"],
        o=outcome,
        age=age,
        e=edited,
        ep=json.dumps({"subject": "sửa"}) if edited else None,
    )


async def _run(conn: Any, world: World, principal: uuid.UUID, cost: str, age: int = 1) -> None:
    await _x(
        conn,
        "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id, worker_id,"
        " worker_version, graph_version, requested_by, run_as_principal_id, model_cost_usd,"
        " created_at) VALUES (:i, :i, :t, :w, 'dw', '1.0.0', '1', :p, :p, CAST(:c AS numeric),"
        " now() - :age * interval '1 day')",
        i=uuid.uuid4(),
        t=world.tenant,
        w=world.workspace,
        p=principal,
        c=cost,
        age=age,
    )


async def test_the_scorecard_counts_this_dws_own_rows_in_the_window(harness: Harness) -> None:
    """R7.1: 3 done, 1 handed off, 2 approved (1 edited), 1 rejected, 0.012 +
    0.003; the other DW's rows and rows older than the window do not count."""
    world = harness.world
    async with harness.migrator.begin() as conn:
        for _ in range(3):
            await _item(conn, world, world.dw, "done")
        await _item(conn, world, world.dw, "handed_off", handoff={"to": "người"})
        await _item(conn, world, world.dw, "done", age=40)
        await _item(conn, world, world.other_dw, "done")
        await _decision(conn, world, world.dw, "approved")
        await _decision(conn, world, world.dw, "approved", edited=True)
        await _decision(conn, world, world.dw, "rejected")
        await _decision(conn, world, world.dw, "approved", age=40)
        await _decision(conn, world, world.other_dw, "rejected")
        await _run(conn, world, world.principal, "0.012")
        await _run(conn, world, world.principal, "0.003")
        await _run(conn, world, world.principal, "1.0", age=40)
        await _run(conn, world, world.other_principal, "0.5")

    response = await harness.scorecard()

    assert response.status_code == 200, response.text
    card = response.json()
    assert card["days"] == 30
    assert card["items"]["by_status"]["done"] == 3
    assert card["items"]["by_status"]["handed_off"] == 1
    assert card["items"]["by_status"]["open"] == 0
    assert card["items"]["total"] == 4
    assert card["items"]["done_alone_rate"] == 0.75
    assert card["items"]["handed_off_rate"] == 0.25
    assert card["decisions"] == {"approved_as_is": 1, "approved_edited": 1, "rejected": 1}
    assert card["model_cost_usd"] == "0.015000"


async def test_an_empty_window_has_no_rates(harness: Harness) -> None:
    response = await harness.scorecard()

    assert response.status_code == 200, response.text
    card = response.json()
    assert card["items"]["total"] == 0
    assert card["items"]["done_alone_rate"] is None
    assert card["model_cost_usd"] == "0"


@pytest.mark.parametrize(("days", "status"), [(0, 422), (91, 422), (1, 200), (90, 200)])
async def test_days_is_one_to_ninety(harness: Harness, days: int, status: int) -> None:
    """R7.2."""
    response = await harness.scorecard(days=days)

    assert response.status_code == status, response.text
    if status == 422:
        assert _reason(response) == "days_out_of_range"


async def test_another_tenant_reads_no_scorecard(harness: Harness) -> None:
    """R1.5 at the new route: 404, the same as a DW that does not exist."""
    response = await harness.scorecard("stranger")

    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# R8: lowering and raising
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["bo", "to"])
async def test_an_owner_lowers_at_once_and_the_gate_reads_it(harness: Harness, who: str) -> None:
    """R8.1."""
    world = harness.world

    response = await harness.change(who, "note.write", "A2")

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "lowered"
    assert await harness.earned("note.write") == "A2"
    level = await harness.autonomy.effective_level(
        tenant_id=world.tenant, workspace_id=world.workspace, dw_id=world.dw, key="note.write"
    )
    assert level == "A2"
    [lowered] = await harness.audits("dw.autonomy.lowered")
    assert lowered.actor_id == world.users[who]
    assert lowered.details["from"] == "A3" and lowered.details["to"] == "A2"


async def test_a_validator_lowers_nothing_and_a_technical_owner_raises_nothing(
    harness: Harness,
) -> None:
    """R8.5 (DWK20)."""
    lowered = await harness.change("validator", "note.write", "A1")
    raised = await harness.change("to", "email.send", "A3")

    assert lowered.status_code == 403 and _reason(lowered) == "not_dw_owner"
    assert raised.status_code == 403 and _reason(raised) == "not_dw_owner"
    assert await harness.earned("note.write") == "A3"
    assert await harness.earned("email.send") == "A2"
    assert await harness.raises() == 0


async def test_a_raise_changes_nothing_until_a_second_person_approves(harness: Harness) -> None:
    """R8.2, R8.6 (DWK17): rejected stays, approved moves, a redelivery is one move."""
    first = await harness.change("bo", "email.send", "A3")
    assert first.status_code == 202, first.text
    assert first.json()["earned_level"] == "A2"
    assert await harness.earned("email.send") == "A2"

    rejected = await harness.decide("validator", first.json()["approval_id"], approve=False)
    assert rejected.status_code == 200, rejected.text
    assert await harness.settle(first.json()["approval_id"]) == "rejected"
    assert await harness.earned("email.send") == "A2"

    second = await harness.change("bo", "email.send", "A3")
    assert second.status_code == 202, second.text
    approval = second.json()["approval_id"]
    approved = await harness.decide("validator", approval)
    assert approved.status_code == 200, approved.text
    assert await harness.earned("email.send") == "A2"

    assert await harness.settle(approval) == "raised"
    assert await harness.earned("email.send") == "A3"
    assert await harness.settle(approval) == "already_raised"
    [raised] = await harness.audits("dw.autonomy.raised")
    assert raised.actor_id == harness.world.users["validator"]
    assert raised.details["lane"] == "outbox"


async def test_an_approved_raise_does_not_overwrite_an_emergency_lowering(
    harness: Harness,
) -> None:
    """R8.6 (DWK17): lowered to A0 while A2→A3 waited; approving keeps A0."""
    opened = await harness.change("bo", "email.send", "A3")
    assert opened.status_code == 202, opened.text
    lowered = await harness.change("to", "email.send", "A0")
    assert lowered.status_code == 200, lowered.text

    approved = await harness.decide("validator", opened.json()["approval_id"])
    assert approved.status_code == 200, approved.text

    assert await harness.settle(opened.json()["approval_id"]) == "stale"
    assert await harness.earned("email.send") == "A0"
    [stale] = await harness.audits("dw.autonomy.raise_stale")
    assert stale.details["earned_level"] == "A0"


async def test_a_retired_dw_is_not_raised(harness: Harness) -> None:
    """R8.6: an approval settled after the DW was retired changes nothing."""
    opened = await harness.change("bo", "email.send", "A3")
    approval = opened.json()["approval_id"]
    assert (await harness.decide("validator", approval)).status_code == 200
    async with harness.migrator.begin() as conn:
        await _x(
            conn,
            "UPDATE platform.digital_workers SET state = 'retired' WHERE id = :d",
            d=harness.world.dw,
        )

    assert await harness.settle(approval) == "stale"
    assert await harness.earned("email.send") == "A2"


@pytest.mark.parametrize(
    ("who", "comment"),
    [("bo", "tự duyệt"), ("outsider", "tôi giữ approvals.decide"), ("validator", "")],
)
async def test_only_a_second_eligible_person_with_a_reason_decides_a_raise(
    harness: Harness, who: str, comment: str
) -> None:
    """R8.3 (DWK18): the requester, a holder of `approvals.decide` outside the
    DW, and no reason: 409, no decision row, the level unchanged."""
    opened = await harness.change("bo", "email.send", "A3")
    approval = opened.json()["approval_id"]

    response = await harness.decide(who, approval, comment=comment)

    assert response.status_code == 409, response.text
    decided = await harness.count(
        "SELECT count(*) FROM platform.approval_decisions WHERE request_id = :a",
        a=uuid.UUID(approval),
    )
    assert decided == 0
    assert await harness.earned("email.send") == "A2"


async def test_a_technical_owner_decides_a_raise_too(harness: Harness) -> None:
    """R8.3: the Validator or the Technical Owner."""
    opened = await harness.change("bo", "email.send", "A3")

    response = await harness.decide("to", opened.json()["approval_id"])

    assert response.status_code == 200, response.text


async def test_a_raise_above_the_ceiling_or_beside_a_pending_one_opens_nothing(
    harness: Harness,
) -> None:
    """R8.4 (DWK19)."""
    above = await harness.change("bo", "email.send", "A4")
    assert above.status_code == 422 and _reason(above) == "above_ceiling"
    assert await harness.raises() == 0

    first = await harness.change("bo", "email.send", "A3")
    assert first.status_code == 202, first.text
    second = await harness.change("bo", "email.send", "A3")

    assert second.status_code == 409 and _reason(second) == "raise_pending"
    assert await harness.raises() == 1


async def test_two_raises_at_once_open_one_approval(harness: Harness) -> None:
    """R8.4 (DWK19): the partial unique index lets one in."""
    responses = await asyncio.gather(
        harness.change("bo", "email.send", "A3"), harness.change("bo", "email.send", "A3")
    )

    assert sorted(r.status_code for r in responses) == [202, 409]
    assert [_reason(r) for r in responses if r.status_code == 409] == ["raise_pending"]
    assert await harness.raises() == 1
