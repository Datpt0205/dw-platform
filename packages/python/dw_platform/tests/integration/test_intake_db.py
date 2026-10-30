"""Integration: the signed lead intake on real PostgreSQL, as `dw_app`
(leadcare ticket 01; R2.1-R2.4, R2.6, R2.8-R2.11, R2.13; LCP3-LCP6, LCP8, LCP14).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_digital_workers_db import World, build_world, command, context_of, service

from dw_kernel.errors import DWError, NotFoundError, PermissionDeniedError, UnauthenticatedError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
    SqlScopedAudit,
)
from dw_platform.adapters.persistence.marketing_send_repo import SqlConsentStore, SqlIntakeScopes
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.intake import IntakeKeyReader, IntakeKeys, LeadIntake
from dw_platform.application.marketing_send import ConsentLedger
from dw_platform.application.work_queue import InMemoryWorkKindSchemas, WorkQueue
from dw_platform.domain.digital_worker import DecisionClass, DwConfiguration

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[5]
SCHEMA = json.loads(
    (ROOT / "configs" / "packs" / "marketing" / "schemas" / "marketing.lead@1.0.0.json").read_text(
        encoding="utf-8"
    )
)
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SECRET = b"integration-intake-secret-0123456789abcdef"
KEYS = IntakeKeys(SECRET)
LEAD: dict[str, Any] = {
    "name": "Anh An",
    "email": "an@khach.vn",
    "source": "website",
    "message": "Tôi muốn tư vấn.",
    "consent": {"granted": True, "text_version": "form-1.2", "captured_at": "2026-10-30T08:59:00Z"},
}


@pytest.fixture
async def world(migrator: AsyncEngine) -> World:
    return await build_world(migrator)


@pytest.fixture
async def migrator(db_urls: Any) -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(db_urls: Any) -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def lead_care_dw(
    app_engine: AsyncEngine,
    migrator: AsyncEngine,
    w: World,
    *,
    state: str = "operating",
    key: str = "lc",
) -> uuid.UUID:
    base = command(w, key=f"{key}_{uuid.uuid4().hex[:8]}")
    config = base.configuration
    lead_care = base.__class__(
        configuration=DwConfiguration(
            key=config.key,
            name=config.name,
            mandate=config.mandate,
            work_kinds=("marketing.lead",),
            allowed_tools=config.allowed_tools,
            workflow_key="lead_care",
            workflow_version="1.0.0",
            parameters={},
            role_keys=config.role_keys,
            decision_classes=(
                DecisionClass("email.send", "external", False, "A2", "A2"),
                DecisionClass("work.handoff", "internal", True, "A3", "A3"),
            ),
        ),
        people=base.people,
    )
    creator = await context_of(app_engine, w, "creator", w.tenant_a, w.ws1)
    worker = await service(app_engine).create(creator, lead_care)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.digital_workers SET state = :s WHERE id = :d"),
            {"s": state, "d": worker.id},
        )
    return worker.id


def intake(app_engine: AsyncEngine, at: datetime = NOW) -> LeadIntake:
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    clock = FixedClock(at)
    ids = Uuid4Generator()
    return LeadIntake(
        keys=KEYS,
        scopes=SqlIntakeScopes(sessions),
        queue=WorkQueue(
            repo=SqlWorkQueueRepository(sessions),
            workers=SqlDigitalWorkerRepository(sessions),
            people=SqlDwMembershipCheck(sessions),
            schemas=InMemoryWorkKindSchemas({("lead_care", "marketing.lead"): SCHEMA}),
            authz=ScopeAuthorizationService(),
            clock=clock,
            id_generator=ids,
        ),
        consents=ConsentLedger(store=SqlConsentStore(sessions), clock=clock, ids=ids),
        clock=clock,
    )


def signed(
    dw: uuid.UUID,
    body: dict[str, Any],
    *,
    event: str | None = None,
    at: datetime = NOW,
    key_of: uuid.UUID | None = None,
) -> dict[str, Any]:
    raw = json.dumps(body).encode()
    event = event or f"evt-{uuid.uuid4().hex}"
    timestamp = str(int(at.timestamp()))
    key = KEYS.key_for(key_of or dw).encode()
    signature = hmac.new(key, f"{timestamp}.{event}.".encode() + raw, hashlib.sha256).hexdigest()
    return {
        "worker": str(dw),
        "event_id": event,
        "timestamp": timestamp,
        "signature": signature,
        "body": raw,
    }


async def rows(migrator: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with migrator.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


async def test_a_signed_lead_is_one_item_with_its_audit_and_consent_record(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.1 (LCP4), R2.10, R2.13: the item is the DW's tenant's whatever the
    body names; one work_item.received as the intake lane; one consent record."""
    dw = await lead_care_dw(app_engine, migrator, world)
    call = signed(dw, LEAD)
    item = await intake(app_engine).receive(**call)
    assert (item.tenant_id, item.workspace_id, item.kind, item.status) == (
        world.tenant_a,
        world.ws1,
        "marketing.lead",
        "open",
    )
    [audit] = await rows(
        migrator,
        "SELECT details FROM platform.audit_events WHERE resource_id = :i AND action = :a",
        i=str(item.id),
        a="work_item.received",
    )
    assert audit.details["actor"] == "system:intake" and audit.details["dw_id"] == str(dw)
    [consent] = await rows(
        migrator,
        "SELECT source, evidence_ref, notice_version, subject_ref FROM platform.consent_records"
        " WHERE tenant_id = :t AND evidence_ref = :e",
        t=world.tenant_a,
        e=call["event_id"],
    )
    assert (consent.source, consent.notice_version, consent.subject_ref) == (
        "intake",
        "form-1.2",
        "an@khach.vn",
    )


async def test_a_tenant_named_in_the_body_is_ignored(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """LCP4: the schema refuses an unknown field, so a body naming tenant B
    writes nothing anywhere, B's least of all."""
    dw = await lead_care_dw(app_engine, migrator, world)
    with pytest.raises(DWError) as refused:
        await intake(app_engine).receive(**signed(dw, {**LEAD, "tenant_id": str(world.tenant_b)}))
    assert refused.value.details["reason_code"] == "payload_invalid"
    assert (
        await rows(
            migrator, "SELECT 1 FROM platform.work_items WHERE tenant_id = :t", t=world.tenant_b
        )
        == []
    )


async def test_a_paused_dw_still_takes_its_leads(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.1."""
    dw = await lead_care_dw(app_engine, migrator, world, state="paused")
    item = await intake(app_engine).receive(**signed(dw, LEAD))
    assert item.status == "open"


async def test_every_untrusted_call_is_the_same_refusal_and_writes_nothing(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.2 (LCP3, LCP14)."""
    dw = await lead_care_dw(app_engine, migrator, world)
    other = await lead_care_dw(app_engine, migrator, world, key="other")
    retired = await lead_care_dw(app_engine, migrator, world, state="retired", key="ret")
    draft = await lead_care_dw(app_engine, migrator, world, state="draft", key="dra")
    door = intake(app_engine)
    swapped = signed(dw, LEAD)
    swapped["event_id"] = "evt-swapped"
    cases = [
        signed(dw, LEAD, key_of=other),  # another DW's key
        signed(dw, LEAD, at=datetime.fromtimestamp(NOW.timestamp() - 301, UTC)),
        {**signed(dw, LEAD), "signature": ""},
        signed(retired, LEAD),
        signed(draft, LEAD),
        swapped,  # LCP14: the event id changed under the old signature
        {**signed(dw, LEAD), "worker": str(uuid.uuid4())},
    ]
    answers = []
    for case in cases:
        with pytest.raises(UnauthenticatedError) as refused:
            await door.receive(**case)
        answers.append((str(refused.value), refused.value.details))
    assert len(set(map(str, answers))) == 1
    assert (
        await rows(
            migrator,
            "SELECT 1 FROM platform.work_items WHERE dw_id = ANY(:d)",
            d=[dw, retired, draft],
        )
        == []
    )
    # 300 seconds off is still on time.
    on_time = signed(dw, LEAD, at=datetime.fromtimestamp(NOW.timestamp() - 300, UTC))
    assert (await door.receive(**on_time)).dw_id == dw


async def test_a_lead_without_consent_is_refused_before_its_schema(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.3 (LCP5)."""
    dw = await lead_care_dw(app_engine, migrator, world)
    for body in ({**LEAD, "consent": {**LEAD["consent"], "granted": False}}, {"name": "x"}):
        with pytest.raises(DWError) as refused:
            await intake(app_engine).receive(**signed(dw, body))
        assert refused.value.details["reason_code"] == "consent_missing"
    assert await rows(migrator, "SELECT 1 FROM platform.work_items WHERE dw_id = :d", d=dw) == []


async def test_the_same_event_again_is_the_same_item_and_another_body_is_refused(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.9."""
    dw = await lead_care_dw(app_engine, migrator, world)
    door = intake(app_engine)
    first = await door.receive(**signed(dw, LEAD, event="evt-1"))
    again = await door.receive(**signed(dw, LEAD, event="evt-1"))
    assert again.id == first.id
    with pytest.raises(DWError) as refused:
        await door.receive(**signed(dw, {**LEAD, "message": "khác"}, event="evt-1"))
    assert refused.value.details["reason_code"] == "source_key_reused"
    assert (
        len(await rows(migrator, "SELECT 1 FROM platform.work_items WHERE dw_id = :d", d=dw)) == 1
    )
    assert (
        len(
            await rows(
                migrator,
                "SELECT 1 FROM platform.consent_records WHERE evidence_ref = 'evt-1'"
                " AND tenant_id = :t",
                t=world.tenant_a,
            )
        )
        == 1
    )


async def test_the_scope_function_answers_three_columns_and_nothing_else(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.6 (LCP8)."""
    dw = await lead_care_dw(app_engine, migrator, world)
    async with app_engine.connect() as conn:
        found = await conn.execute(
            sa.text("SELECT * FROM platform.intake_worker_scope(:d)"), {"d": dw}
        )
        assert list(found.keys()) == ["tenant_id", "workspace_id", "state"]
        seen = await conn.scalar(sa.text("SELECT count(*) FROM platform.digital_workers"))
    assert seen == 0


async def test_only_the_dws_owners_read_its_key_on_the_record(
    world: World, app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R2.4, R2.8, R2.11 (LCP6)."""
    dw = await lead_care_dw(app_engine, migrator, world)
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    reader = IntakeKeyReader(
        keys=KEYS,
        workers=service(app_engine),
        audit=SqlScopedAudit(sessions),
        clock=FixedClock(NOW),
        ids=Uuid4Generator(),
    )
    validator = await context_of(app_engine, world, "validator", world.tenant_a, world.ws1)
    with pytest.raises(PermissionDeniedError) as refused:
        await reader.read(validator, dw)
    assert refused.value.details["reason_code"] == "not_dw_owner"
    stranger = await context_of(app_engine, world, "b_member", world.tenant_b, world.ws_b)
    with pytest.raises(NotFoundError):
        await reader.read(stranger, dw)
    tech = await context_of(app_engine, world, "tech", world.tenant_a, world.ws1)
    assert await reader.read(tech, dw) == KEYS.key_for(dw)
    reads = await rows(
        migrator,
        "SELECT actor_id FROM platform.audit_events WHERE action = 'dw.intake_key.read'"
        " AND resource_id = :d",
        d=str(dw),
    )
    assert [r.actor_id for r in reads] == [world.users["tech"]]
