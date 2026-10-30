# ruff: noqa: F811  (the fixtures of test_digital_workers_db are imported by name)
"""Integration: the shared work queue on real PostgreSQL, as `dw_app` under RLS.

digital-worker ticket 02: R3.1-R3.15 (DWK3, DWK8-DWK13, DWK27-DWK29, DWK31,
DWK35, DWK40), R4.1-R4.3 (DWK13, DWK14, DWK39), and retirement R1.12, R1.14
(DWK32).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_digital_workers_db import (  # noqa: F401  (fixtures, used by name)
    World,
    app_engine,
    command,
    context_of,
    migrator,
    service,
    world,
)

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.pagination import PageQuery, page_request
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.digital_workers import ChangeState
from dw_platform.application.work_queue import (
    InMemoryWorkKindSchemas,
    NewWork,
    WorkListFilter,
    WorkQueue,
    WorkScope,
)
from dw_platform.domain.digital_worker import DigitalWorker
from dw_platform.domain.work_item import payload_hash

pytestmark = pytest.mark.integration

LEAD_SCHEMA = {
    "type": "object",
    "required": ["email", "name"],
    "properties": {"email": {"type": "string", "format": "email"}, "name": {"type": "string"}},
}
LEAD = {"email": "an@khach.vn", "name": "Anh"}
PACKET = {
    "problem": "Khách hỏi giá đặc biệt",
    "context": "Lead từ hội chợ",
    "tried": "Gửi bảng giá chuẩn",
    "recommendation": "Gọi lại trong hôm nay",
}


def queue(app_engine: AsyncEngine) -> WorkQueue:
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    return WorkQueue(
        repo=SqlWorkQueueRepository(sessions),
        workers=SqlDigitalWorkerRepository(sessions),
        people=SqlDwMembershipCheck(sessions),
        schemas=InMemoryWorkKindSchemas({("leadcare", "lead.new"): LEAD_SCHEMA}),
        authz=ScopeAuthorizationService(),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


async def _dw(
    app_engine: AsyncEngine,
    migrator: AsyncEngine,
    w: World,
    key: str = "lead_care",
    *,
    state: str = "operating",
) -> DigitalWorker:
    creator = await context_of(app_engine, w, "creator", w.tenant_a, w.ws1)
    worker = await service(app_engine).create(creator, command(w, key))
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.digital_workers SET state = :s WHERE id = :id"),
            {"s": state, "id": worker.id},
        )
    return worker


def scope(w: World) -> WorkScope:
    return WorkScope(tenant_id=w.tenant_a, workspace_id=w.ws1)


async def _set(migrator: AsyncEngine, item_id: uuid.UUID, **values: Any) -> None:
    columns = ", ".join(f"{k} = :{k}" for k in values)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(f"UPDATE platform.work_items SET {columns} WHERE id = :id"),
            {**values, "id": item_id},
        )


async def _count(migrator: AsyncEngine, sql: str, **params: object) -> int:
    async with migrator.connect() as conn:
        return int((await conn.execute(sa.text(sql), params)).scalar_one())


# ----------------------------------------------------------------- intake --


async def test_work_lands_open_with_the_dw_holding_it(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R3.1."""
    worker = await _dw(app_engine, migrator, world)
    item = await queue(app_engine).enqueue(
        scope(world), worker.id, NewWork("lead.new", "form-1", LEAD)
    )
    assert (item.status, item.holder_kind, item.holder_id, item.dw_id) == (
        "open",
        "digital_worker",
        worker.id,
        worker.id,
    )
    assert item.payload_hash == payload_hash({"name": "Anh", "email": "an@khach.vn"})


@pytest.mark.parametrize(
    ("work", "code"),
    [
        (NewWork("invoice.new", "x-1", LEAD), "work_kind_outside_mandate"),  # DWK8
        (NewWork("lead.new", "x-2", {"name": "Anh"}), "payload_invalid"),  # DWK9
    ],
)
async def test_work_outside_the_mandate_or_its_schema_is_refused(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine, work: NewWork, code: str
) -> None:
    worker = await _dw(app_engine, migrator, world)
    with pytest.raises(DomainError) as refused:
        await queue(app_engine).enqueue(scope(world), worker.id, work)
    assert refused.value.details["reason_code"] == code
    assert (
        await _count(
            migrator, "SELECT count(*) FROM platform.work_items WHERE dw_id = :d", d=worker.id
        )
        == 0
    )


async def test_a_kind_without_a_schema_is_refused(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK9: no schema declared at all."""
    worker = await _dw(app_engine, migrator, world)
    no_schemas = replace(queue(app_engine), schemas=InMemoryWorkKindSchemas({}))
    with pytest.raises(DomainError) as refused:
        await no_schemas.enqueue(scope(world), worker.id, NewWork("lead.new", "x-3", LEAD))
    assert refused.value.details["reason_code"] == "payload_invalid"


async def test_a_retired_or_draft_dw_takes_no_work(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK40."""
    for key, state in (("retired_dw", "retired"), ("draft_dw", "draft")):
        worker = await _dw(app_engine, migrator, world, key, state=state)
        with pytest.raises(DomainError) as refused:
            await queue(app_engine).enqueue(scope(world), worker.id, NewWork("lead.new", "k", LEAD))
        assert refused.value.details["reason_code"] == "dw_not_accepting_work"
        assert (
            await _count(
                migrator, "SELECT count(*) FROM platform.work_items WHERE dw_id = :d", d=worker.id
            )
            == 0
        )


async def test_one_source_is_one_item_per_dw(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK28."""
    first_dw = await _dw(app_engine, migrator, world, "first_dw")
    second_dw = await _dw(app_engine, migrator, world, "second_dw")
    q = queue(app_engine)
    one = await q.enqueue(scope(world), first_dw.id, NewWork("lead.new", "form-9", LEAD))
    again = await q.enqueue(scope(world), first_dw.id, NewWork("lead.new", "form-9", dict(LEAD)))
    assert again.id == one.id
    with pytest.raises(DomainError) as reused:
        await q.enqueue(
            scope(world), first_dw.id, NewWork("lead.new", "form-9", {**LEAD, "name": "Bình"})
        )
    assert reused.value.details["reason_code"] == "source_key_reused"
    other = await q.enqueue(scope(world), second_dw.id, NewWork("lead.new", "form-9", LEAD))
    assert other.id != one.id


# ------------------------------------------------------------------ reads --


async def test_another_tenant_or_an_unscoped_read_sees_no_work(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK3, R3.5."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    item = await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    query = PageQuery(key="work_items")

    owner = await context_of(app_engine, world, "owner", world.tenant_a, world.ws1)
    mine = await q.page(owner, page_request(limit=50, cursor=None, query=query), WorkListFilter())
    assert [i.id for i in mine.items] == [item.id]
    assert mine.items[0].payload == {}

    in_b = await context_of(app_engine, world, "b_member", world.tenant_b, world.ws_b)
    theirs = await q.page(in_b, page_request(limit=50, cursor=None, query=query), WorkListFilter())
    assert not theirs.items
    with pytest.raises(NotFoundError):
        await q.get(in_b, item.id)
    async with app_engine.connect() as conn:
        assert (
            await conn.execute(sa.text("SELECT count(*) FROM platform.work_items"))
        ).scalar() == 0


async def test_only_the_holder_and_the_dws_people_read_the_payload(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK29: `creator` holds `dw.read` and is none of the four people."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    item = await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    outsider = await context_of(app_engine, world, "creator", world.tenant_a, world.ws1)
    validator = await context_of(app_engine, world, "validator", world.tenant_a, world.ws1)
    assert (await q.get(outsider, item.id)).payload == {}
    assert (await q.get(validator, item.id)).payload == LEAD


# ---------------------------------------------------------- transitions --


async def test_a_payload_is_fixed_and_a_done_item_stays_done(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK31."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    item = await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    with pytest.raises(DBAPIError, match="keeps what it was given"):
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "SELECT set_config('app.tenant_id', :t, true),"
                    " set_config('app.workspace_id', :w, true)"
                ),
                {"t": str(world.tenant_a), "w": str(world.ws1)},
            )
            await conn.execute(
                sa.text("UPDATE platform.work_items SET payload = '{}'::jsonb WHERE id = :id"),
                {"id": item.id},
            )
    await _set(migrator, item.id, status="in_progress", run_id=uuid.uuid4())
    await q.finish(scope(world), item.id, outcome="done")
    with pytest.raises(ConflictError) as refused:
        await q.resume_claimed(scope(world), item.id)
    assert refused.value.details["reason_code"] == "invalid_transition"


# ------------------------------------------------------------------- lane --


async def test_two_lanes_take_one_item_once(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK10."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    item = await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    first, second = await asyncio.gather(
        q.claim_for_lane(scope(world), limit=10), q.claim_for_lane(scope(world), limit=10)
    )
    taken = [c for c in (*first, *second) if c.item.id == item.id]
    assert len(taken) == 1
    assert taken[0].item.status == "in_progress" and taken[0].item.run_id == taken[0].run_id


async def test_a_paused_dw_or_one_without_an_owner_is_not_given_work(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK11, and a DW whose Business Owner is gone (R3.6)."""
    paused = await _dw(app_engine, migrator, world, "paused_dw", state="paused")
    orphan = await _dw(app_engine, migrator, world, "orphan_dw")
    q = queue(app_engine)
    for worker in (paused, orphan):
        await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    await _set_owner_none(migrator, orphan)
    assert await q.claim_for_lane(scope(world), limit=10) == []
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.work_items WHERE dw_id IN (:a, :b) AND status = 'open'",
            a=paused.id,
            b=orphan.id,
        )
        == 2
    )


async def _set_owner_none(migrator: AsyncEngine, worker: DigitalWorker) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.service_principals SET owner_user_id = NULL WHERE user_id = :p"
            ),
            {"p": worker.principal_user_id},
        )


async def test_work_refused_for_the_limit_waits_five_minutes(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK27."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    [claimed] = await q.claim_for_lane(scope(world), limit=10)
    released = await q.release_for_limit(scope(world), claimed.item.id)
    assert released.status == "open" and released.run_id == claimed.run_id
    assert released.available_at - claimed.item.updated_at >= timedelta(minutes=4, seconds=59)
    assert await q.claim_for_lane(scope(world), limit=10) == []
    assert (
        await _count(
            migrator, "SELECT count(*) FROM platform.work_items WHERE dw_id = :d", d=worker.id
        )
        == 1
    )


async def test_work_claimed_and_never_started_goes_back_with_its_run_id(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK35, DWK37: 16 minutes without a run row returns it, 14 do not."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    for key in ("old", "young"):
        await q.enqueue(scope(world), worker.id, NewWork("lead.new", key, LEAD))
    claimed = {c.item.source_key: c for c in await q.claim_for_lane(scope(world), limit=10)}
    async with migrator.begin() as conn:
        for key, minutes in (("old", 16), ("young", 14)):
            await conn.execute(
                sa.text(
                    "UPDATE platform.work_items SET updated_at = now() - make_interval(mins => :m)"
                    " WHERE id = :id"
                ),
                {"m": minutes, "id": claimed[key].item.id},
            )
    assert await q.release_stuck(scope(world)) == 1
    old = await q.repo.get(scope(world), claimed["old"].item.id)
    young = await q.repo.get(scope(world), claimed["young"].item.id)
    assert old is not None and old.status == "open" and old.run_id == claimed["old"].run_id
    assert young is not None and young.status == "in_progress"
    [again] = await q.claim_for_lane(scope(world), limit=10)
    assert again.run_id == claimed["old"].run_id


async def test_a_start_that_fails_otherwise_fails_the_item(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R3.15."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    [claimed] = await q.claim_for_lane(scope(world), limit=10)
    failed = await q.fail_start(scope(world), claimed.item.id, "workflow_not_loaded")
    assert (failed.status, failed.error) == ("failed", "workflow_not_loaded")
    assert failed.closed_at is not None
    assert await q.claim_for_lane(scope(world), limit=10) == []


# --------------------------------------------------------------- hand-off --


async def _in_progress(app_engine: AsyncEngine, migrator: AsyncEngine, w: World) -> Any:
    worker = await _dw(app_engine, migrator, w)
    q = queue(app_engine)
    await q.enqueue(scope(w), worker.id, NewWork("lead.new", "form-1", LEAD))
    [claimed] = await q.claim_for_lane(scope(w), limit=10)
    return worker, q, claimed.item


async def test_a_hand_off_moves_the_work_to_a_person_with_its_packet(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R4.1, then R3.8 and R3.13 on the person's side."""
    worker, q, item = await _in_progress(app_engine, migrator, world)
    handed = await q.hand_off(
        scope(world), item.id, to_user=world.users["validator"], packet=PACKET
    )
    assert (handed.status, handed.holder_kind, handed.holder_id) == (
        "handed_off",
        "person",
        world.users["validator"],
    )
    assert handed.handoff is not None and handed.handoff.as_dict() == PACKET
    async with migrator.connect() as conn:
        actor = (
            await conn.execute(
                sa.text(
                    "SELECT actor_id FROM platform.audit_events"
                    " WHERE resource_id = :id AND action = 'work_item.handed_off'"
                ),
                {"id": str(item.id)},
            )
        ).scalar_one()
    assert actor == worker.principal_user_id

    owner = await context_of(app_engine, world, "owner", world.tenant_a, world.ws1)
    with pytest.raises(PermissionDeniedError) as not_holder:
        await q.complete(owner, item.id)
    assert not_holder.value.details["reason_code"] == "not_holder"
    validator = await context_of(app_engine, world, "validator", world.tenant_a, world.ws1)
    done = await q.complete(validator, item.id)
    assert done.status == "done" and done.closed_at is not None
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.audit_events"
            " WHERE resource_id = :id AND action = 'work_item.completed' AND actor_id = :a",
            id=str(item.id),
            a=world.users["validator"],
        )
        == 1
    )


async def test_the_holder_cannot_close_work_that_was_not_handed_over(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK12: an `in_progress` item a person holds (set by hand) is not closed."""
    _, q, item = await _in_progress(app_engine, migrator, world)
    await _set(migrator, item.id, holder_kind="person", holder_id=world.users["validator"])
    validator = await context_of(app_engine, world, "validator", world.tenant_a, world.ws1)
    with pytest.raises(ConflictError) as refused:
        await q.complete(validator, item.id)
    assert refused.value.details["reason_code"] == "invalid_transition"


@pytest.mark.parametrize(
    "packet",
    [
        {k: v for k, v in PACKET.items() if k != "recommendation"},
        {**PACKET, "tried": "x" * 4001},
        {**PACKET, "context": "   "},
    ],
)
async def test_a_packet_holds_four_short_fields(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine, packet: dict[str, str]
) -> None:
    """DWK13."""
    _, q, item = await _in_progress(app_engine, migrator, world)
    with pytest.raises(DomainError) as refused:
        await q.hand_off(scope(world), item.id, to_user=world.users["validator"], packet=packet)
    assert refused.value.details["reason_code"] == "handoff_packet_invalid"
    assert (await q.repo.get(scope(world), item.id)).status == "in_progress"


async def test_a_packet_of_four_thousand_characters_is_taken(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    _, q, item = await _in_progress(app_engine, migrator, world)
    handed = await q.hand_off(
        scope(world),
        item.id,
        to_user=world.users["validator"],
        packet={**PACKET, "tried": "x" * 4000},
    )
    assert handed.status == "handed_off"


async def test_work_is_handed_only_to_a_person_of_the_workspace(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK14, DWK39: a member of tenant B, and a DW's service principal."""
    worker, q, item = await _in_progress(app_engine, migrator, world)
    for target in (world.users["b_member"], worker.principal_user_id):
        with pytest.raises(DomainError) as refused:
            await q.hand_off(scope(world), item.id, to_user=target, packet=PACKET)
        assert refused.value.details["reason_code"] == "handoff_target_invalid"
    after = await q.repo.get(scope(world), item.id)
    assert after is not None and (after.holder_kind, after.status) == (
        "digital_worker",
        "in_progress",
    )


# ------------------------------------------------------------- retirement --


async def test_a_dw_with_work_in_flight_does_not_retire(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK32, R1.12."""
    worker, q, item = await _in_progress(app_engine, migrator, world)
    await q.record_wait(scope(world), item.id, target="waiting_approval")
    owner = await context_of(app_engine, world, "owner", world.tenant_a, world.ws1)
    with pytest.raises(ConflictError) as refused:
        await service(app_engine).change_state(owner, worker.id, ChangeState("retired"))
    assert refused.value.details["reason_code"] == "dw_has_work_in_flight"
    assert (await service(app_engine).get(owner, worker.id)).state == "operating"


async def test_retiring_cancels_open_work_and_removes_only_its_principal(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK32, R1.14."""
    worker = await _dw(app_engine, migrator, world)
    other = await _dw(app_engine, migrator, world, "other_dw")
    q = queue(app_engine)
    item = await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    owner = await context_of(app_engine, world, "owner", world.tenant_a, world.ws1)
    retired = await service(app_engine).change_state(owner, worker.id, ChangeState("retired"))
    assert retired.state == "retired"
    after = await q.repo.get(scope(world), item.id)
    assert after is not None and after.status == "cancelled" and after.closed_at is not None
    members = "SELECT count(*) FROM platform.memberships WHERE user_id = :u"
    assert await _count(migrator, members, u=worker.principal_user_id) == 0
    assert await _count(migrator, members, u=other.principal_user_id) == 1
    assert await _count(migrator, members, u=world.users["owner"]) == 1


async def test_the_principal_is_removed_only_for_a_retired_dw_of_the_bound_tenant(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    worker = await _dw(app_engine, migrator, world)
    with pytest.raises(DBAPIError, match="only a retired digital worker"):
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(world.tenant_a)},
            )
            await conn.execute(sa.text("SELECT platform.retire_dw_principal(:d)"), {"d": worker.id})
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.memberships WHERE user_id = :u",
            u=worker.principal_user_id,
        )
        == 1
    )


async def test_a_retirement_and_a_claim_do_not_cross(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """DWK32: run at once, either the claim wins (and the retirement is
    refused) or the retirement wins (and nothing is claimed); never an
    `in_progress` item of a retired DW."""
    worker = await _dw(app_engine, migrator, world)
    q = queue(app_engine)
    await q.enqueue(scope(world), worker.id, NewWork("lead.new", "form-1", LEAD))
    owner = await context_of(app_engine, world, "owner", world.tenant_a, world.ws1)
    claim, retire = await asyncio.gather(
        q.claim_for_lane(scope(world), limit=10),
        service(app_engine).change_state(owner, worker.id, ChangeState("retired")),
        return_exceptions=True,
    )
    assert (
        await _count(
            migrator,
            "SELECT count(*) FROM platform.work_items w JOIN platform.digital_workers d"
            " ON d.id = w.dw_id WHERE d.id = :d AND d.state = 'retired'"
            " AND w.status = 'in_progress'",
            d=worker.id,
        )
        == 0
    )
    assert isinstance(retire, ConflictError) or claim == []
