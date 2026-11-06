"""`RecordService` on PostgreSQL, through every door (custom-objects ticket 03).

The API's door (`user_session`), a workflow step's and an agent's (a run's
row bound by `bind_actor`) all reach one service; the record policies of
record-access/03 decide every row, the field decision of field-security/01
every field. The HTTP shapes (status, headers, problem+json, `Idempotency-Key`)
are `apps/api/tests/integration/test_studio_records.py`'s; this file holds
what only a door other than HTTP, a race, a simulation or the database shows:
the write keys of a step (R5.9-R5.11), `create_key` (R5.3), the run modes
(R5.4), the duplicate-probe limit by actor kind (R7.6), the soft delete's
WITH CHECK (R5.8), `permissions` against the policies (gate (l)), the purge
(gate (p)), the one transaction of a write (R5.2) and the shared lock.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_kernel.errors import (
    IdempotencyConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from dw_kernel.ids import TenantId
from dw_kernel.ports import Uuid7Generator
from dw_kernel.run_mode import RunMode
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.adapters.persistence.tenant_session import (
    TenantScope,
    bind_tenant,
    tenant_session,
)
from dw_platform.adapters.rate_limit import InProcessRateLimiter
from dw_platform.application.rate_limit import PrincipalObjectKey
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.core.application.field_access import FieldAccessService
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.records.adapters.definition_store import SqlObjectDefinitionReader
from dw_studio.records.adapters.record_policy import may_sql
from dw_studio.records.adapters.record_store import SqlRecordStore, SqlRecordWriteKeyRetention
from dw_studio.records.application.record_service import (
    DUPLICATE_LIMIT,
    RecordDoor,
    RecordService,
)
from dw_studio.records.application.schema_projector import ObjectSchemaProjector
from dw_studio.records.domain.errors import (
    DuplicateThrottledError,
    DuplicateValueError,
    FieldNotEditableError,
    RecordInvalidError,
)
from dw_studio.records.domain.locks import object_lock_key
from dw_studio.testing.objects import object_document, object_field, plant_manager
from dw_studio.testing.record_world import (
    RunKind,
    holder,
    person_door,
    publish_object,
    run_door,
    sessions_of,
)
from dw_studio.testing.records import act_as_user
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

LEAD = "mkt_lead"
FIELDS = ("name", "phone", "email", "note", "amount", "cccd")
EDIT_ALL = dict.fromkeys(("name", "phone", "email"), "edit")


def lead_document() -> dict[str, Any]:
    return object_document(
        object_field("phone", "phone", pd_category="basic", is_unique=True),
        object_field("email", "email", pd_category="basic", is_unique=True),
        object_field("note", max_length=50),
        object_field("amount", "currency", scale=0),
        object_field("cccd", pd_category="sensitive", sensitive_type="health", is_unique=True),
    )


def _digest() -> str:
    return "sha256:" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()


async def plant_run(
    migrator: AsyncEngine,
    app: AsyncEngine,
    tenant: PlantedTenant,
    principal: uuid.UUID,
    objects: Sequence[ObjectBoundary],
    fields: Sequence[FieldBoundary],
    *,
    kind: RunKind = "workflow",
    mode: str = "live",
) -> uuid.UUID:
    """A run of a sealed `workflow` (or `agent`) version acting as
    ``principal``, its row as the run door writes it, and the version's
    published boundary allowing ``objects`` and ``fields``."""
    t, run = tenant.tenant_id, uuid.uuid4()
    artifact, version, digest, manifest = uuid.uuid4(), uuid.uuid4(), _digest(), _digest()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
                " row_version) VALUES (:a, :t, :k, :n, :w, 1)"
            ),
            # A `workflow` artifact for both kinds, as the boundary tests plant
            # an agent's run (no `agent` kind is registered in W1).
            {
                "a": artifact,
                "t": t,
                "k": "workflow",
                "n": f"r_{artifact.hex[:12]}",
                "w": tenant.main,
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
                " version_no, document_schema, document, row_version, contributor_ids,"
                " content_hash, definition_hash) VALUES (:v, :t, :a, 'draft', 1, :s, '{}', 1,"
                " ARRAY[:u]::uuid[], :c, :h)"
            ),
            {
                "v": version,
                "t": t,
                "a": artifact,
                "s": "dw.workflow/v1",
                "u": principal,
                "c": _digest(),
                "h": digest,
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
                " VALUES (:t, :h, CAST(:b AS jsonb))"
            ),
            {"t": t, "h": manifest, "b": json.dumps({"run_mode": mode})},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                " worker_id, worker_version, graph_version, requested_by, run_as_principal_id,"
                " run_mode, run_manifest_hash, artifact_kind, artifact_id, artifact_version_id,"
                " definition_hash, trigger_kind, request_key, root_run_id, chain_depth)"
                " VALUES (:r, :r, :t, :w, 'studio', '1', '1', :p, :p, :m, :h, :k, :a, :v, :d,"
                " :tk, :rk, :r, 0)"
            ),
            {
                "r": run,
                "t": t,
                "w": tenant.main,
                "p": principal,
                "m": mode,
                "h": manifest,
                "k": kind,
                "a": artifact,
                "v": version,
                "d": digest,
                "tk": "test" if mode == "simulate" else "manual",
                "rk": f"k:{run}",
            },
        )
    async with app.begin() as conn:
        await bind_tenant(conn, TenantScope(tenant_id=t))
        await SqlActorBoundaries().record(conn, kind, version, digest, objects, fields)
    return run


class Clock:
    """A clock the test moves: the limiter's window and the service's stamps."""

    def __init__(self) -> None:
        self.at = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.at


@dataclass
class World:
    tenant: PlantedTenant
    lead: uuid.UUID
    sessions: async_sessionmaker[AsyncSession]
    migrator: AsyncEngine
    app: AsyncEngine
    clock: Clock
    service: RecordService

    def door(self, person: Person) -> RecordDoor:
        return person_door(self.sessions, person)

    async def person(
        self,
        actions: dict[str, str] | None = None,
        fields: dict[str, str] | None = None,
        *,
        kind: str = "human",
        workspace: uuid.UUID | None = None,
    ) -> Person:
        async with self.migrator.begin() as conn:
            return await holder(
                conn,
                self.tenant,
                self.lead,
                actions
                if actions is not None
                else dict.fromkeys(("read", "create", "update", "delete"), "workspace"),
                EDIT_ALL if fields is None else fields,
                kind=kind,
                workspace=workspace,
            )

    async def count(self, statement: str, **values: Any) -> int:
        async with self.migrator.connect() as conn:
            return int((await conn.execute(sa.text(statement), values)).scalar_one())

    async def run(
        self, principal: uuid.UUID, kind: RunKind = "workflow", mode: str = "live"
    ) -> RecordDoor:
        run = await plant_run(
            self.migrator,
            self.app,
            self.tenant,
            principal,
            [ObjectBoundary(LEAD, True, True, True, True, False)],
            [FieldBoundary(LEAD, f, "edit") for f in FIELDS],
            kind=kind,
            mode=mode,
        )
        return run_door(self.sessions, self.tenant, principal, run, kind)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(studio_db: DatabaseUrls) -> AsyncIterator[World]:
    migrator = create_async_engine(studio_db.migrator, poolclass=NullPool)
    app = create_async_engine(studio_db.app, poolclass=NullPool)
    sessions = sessions_of(app)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        manager = await plant_manager(conn, tenant)
    lead = await publish_object(sessions, manager, LEAD, lead_document())
    clock = Clock()
    service = RecordService(
        SqlRecordStore(),
        FieldAccessService(SqlFieldSecurityInputs()),
        InProcessRateLimiter(1, clock),
        ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
        clock,
        Uuid7Generator(),
    )
    yield World(tenant, lead, sessions, migrator, app, clock, service)
    await app.dispose()
    await migrator.dispose()


def phone() -> str:
    return "09" + str(uuid.uuid4().int)[:8]


async def test_smoke_create_read_change_delete(world: World) -> None:
    person = await world.person()
    door = world.door(person)
    made = await world.service.create(
        door, LEAD, {"name": "Lan", "fields": {"phone": phone(), "amount": "1000"}}
    )
    assert made.created and made.version == 1
    assert made.record.owner_id == person.id and made.record.workspace_id == person.workspace_id
    assert made.record.fields["amount"] == "1000"
    got = await world.service.get(door, LEAD, made.record.id)
    assert got.permissions.update and got.permissions.delete
    changed = await world.service.update(
        door, LEAD, got.id, {"fields": {"note": "gọi lại"}}, expected=1
    )
    assert changed.record.version == 2 and changed.record.fields["note"] == "gọi lại"
    gone = await world.service.delete(door, LEAD, got.id, expected=2)
    assert gone.record.deleted_at is not None
    with pytest.raises(NotFoundError):
        await world.service.update(door, LEAD, got.id, {"name": "x"}, expected=3)


# ---- helpers --------------------------------------------------------------------


async def events(world: World, record: uuid.UUID) -> list[str]:
    async with world.migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT event_type FROM platform.outbox_events WHERE aggregate_id = :r"
                " ORDER BY occurred_at, event_type"
            ),
            {"r": record},
        )
        return [r.event_type for r in rows]


async def audits(world: World, resource: uuid.UUID, action: str | None = None) -> list[Any]:
    async with world.migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT action, actor_id, details FROM platform.audit_events"
                " WHERE resource_id = :r AND (CAST(:a AS text) IS NULL OR action = :a)"
                " ORDER BY occurred_at"
            ),
            {"r": str(resource), "a": action},
        )
        return list(rows)


def wf_key() -> str:
    return f"wf:{uuid.uuid4()}:node_1:0"


class _FailingTx:
    """The real transaction, one of whose writes fails after the record's."""

    def __init__(self, inner: Any, fails: str) -> None:
        self._inner, self._fails = inner, fails

    def __getattr__(self, name: str) -> Any:
        if name == self._fails:

            async def refuse(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(f"{name} failed")

            return refuse
        return getattr(self._inner, name)


class FailingStore:
    def __init__(self, fails: str) -> None:
        self.fails = fails

    async def bind(self, tx: Any) -> Any:
        return _FailingTx(await SqlRecordStore().bind(tx), self.fails)


def failing(world: World, fails: str) -> RecordService:
    s = world.service
    return RecordService(FailingStore(fails), s.fields, s.limiter, s.projector, s.clock, s.ids)


async def _outbox(world: World) -> int:
    return await world.count(
        "SELECT count(*) FROM platform.outbox_events WHERE tenant_id = :t",
        t=world.tenant.tenant_id,
    )


def records_of(world: World) -> Any:
    return world.count("SELECT count(*) FROM studio.records WHERE object_id = :o", o=world.lead)


# ---- R5.2: one write, one transaction -------------------------------------------


async def test_r5_2_co11_a_write_is_its_record_one_event_and_one_audit_of_keys_only(
    world: World,
) -> None:
    person = await world.person()
    door = world.door(person)
    made = await world.service.create(
        door, LEAD, {"name": "Hà", "fields": {"phone": "0912 999 000", "note": "ghi chú riêng"}}
    )
    rid = made.record.id
    assert await events(world, rid) == ["studio.record.created"]
    (audit,) = await audits(world, rid)
    assert audit.action == "studio.record.created" and audit.actor_id == person.id
    assert audit.details == {"fields": ["name", "note", "phone"], "version": 1}
    async with world.migrator.connect() as conn:
        payload = (
            await conn.execute(
                sa.text("SELECT payload FROM platform.outbox_events WHERE aggregate_id = :r"),
                {"r": rid},
            )
        ).scalar_one()
    assert payload["channel"] == "api" and payload["run_id"] is None
    assert payload["operation_id"] is None and payload["run_mode"] == "live"
    assert payload["changed_fields"] == ["name", "note", "phone"]
    for value in ("0912", "+84912999000", "ghi chú"):
        assert value not in str(payload) and value not in str(audit.details)

    for step in ("outbox", "audit"):
        before = (await records_of(world), await _outbox(world))
        with pytest.raises(RuntimeError):
            await failing(world, step).create(door, LEAD, {"name": "Không lưu"})
        assert (await records_of(world), await _outbox(world)) == before, step
    assert (
        await world.count(
            "SELECT count(*) FROM platform.audit_events WHERE actor_id = :p", p=person.id
        )
        == 1
    )


# ---- R5.3, R5.9-R5.11: a step's `wf:` key -----------------------------------------


async def test_r5_3_co12_two_creates_with_one_wf_key_make_one_record(world: World) -> None:
    principal = await world.person(kind="service")
    door = await world.run(principal.id)
    key = wf_key()
    first, second = await asyncio.gather(
        world.service.create(door, LEAD, {"name": "A"}, write_key=key),
        world.service.create(door, LEAD, {"name": "A"}, write_key=key),
    )
    assert first.record.id == second.record.id
    assert sorted([first.replayed, second.replayed]) == [False, True]
    assert (
        await world.count("SELECT count(*) FROM studio.records WHERE create_key = :k", k=key) == 1
    )
    assert await events(world, first.record.id) == ["studio.record.created"]


async def test_r5_10_gate_b_a_rerun_upsert_meets_its_own_create_and_changes_nothing(
    world: World,
) -> None:
    principal = await world.person(kind="service")
    door = await world.run(principal.id)
    key, number = wf_key(), phone()
    made = await world.service.upsert(
        door,
        LEAD,
        {"match_field": "phone", "name": "Lần đầu", "fields": {"phone": number}},
        write_key=key,
    )
    assert made.created and not made.replayed
    again = await world.service.update(
        door, LEAD, made.record.id, {"name": "Lần sau"}, write_key=key
    )
    assert (again.created, again.replayed, again.version) == (True, True, 1)
    assert again.record.name == "Lần đầu" and again.record.version == 1
    assert await events(world, made.record.id) == ["studio.record.created"]

    # gate (u): the key of this create, from another principal.
    other = await world.person(kind="service")
    with pytest.raises(IdempotencyConflictError):
        await world.service.create(await world.run(other.id), LEAD, {"name": "Khác"}, write_key=key)
    assert (
        await world.count("SELECT count(*) FROM studio.records WHERE create_key = :k", k=key) == 1
    )


async def test_r5_9_r5_10_co26_a_step_s_change_keeps_its_key_and_a_rerun_replays_it(
    world: World,
) -> None:
    principal = await world.person(kind="service")
    door = await world.run(principal.id)
    made = await world.service.create(door, LEAD, {"name": "Gốc"})
    key = wf_key()

    with pytest.raises(RuntimeError):
        await failing(world, "audit").update(
            door, LEAD, made.record.id, {"name": "Hỏng"}, write_key=key
        )
    assert (
        await world.count(
            "SELECT count(*) FROM studio.record_write_keys WHERE write_key = :k", k=key
        )
        == 0
    )
    assert (await world.service.get(door, LEAD, made.record.id)).name == "Gốc"

    first = await world.service.update(door, LEAD, made.record.id, {"name": "Sửa"}, write_key=key)
    assert (first.version, first.replayed, first.created) == (2, False, False)
    async with world.migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT record_id, op, version, created, actor_id"
                    " FROM studio.record_write_keys WHERE write_key = :k"
                ),
                {"k": key},
            )
        ).one()
    assert tuple(row) == (made.record.id, "update", 2, False, principal.id)

    rerun = await world.service.update(
        door, LEAD, made.record.id, {"name": "Đầu vào khác"}, write_key=key
    )
    assert (rerun.version, rerun.replayed) == (2, True)
    assert rerun.record.name == "Sửa" and rerun.record.version == 2
    assert await events(world, made.record.id) == ["studio.record.created", "studio.record.updated"]
    assert len(await audits(world, made.record.id, "studio.record.updated")) == 1


async def test_r5_11_co26_another_principal_s_key_is_a_conflict_and_not_even_seen(
    world: World,
) -> None:
    first = await world.person(kind="service")
    second = await world.person(kind="service")
    door = await world.run(first.id)
    made = await world.service.create(door, LEAD, {"name": "Một"})
    key = wf_key()
    await world.service.update(door, LEAD, made.record.id, {"name": "Hai"}, write_key=key)
    other = await world.run(second.id)
    with pytest.raises(IdempotencyConflictError):
        await world.service.update(other, LEAD, made.record.id, {"name": "Ba"}, write_key=key)
    got = await world.service.get(door, LEAD, made.record.id)
    assert (got.name, got.version) == ("Hai", 2)
    async with world.app.begin() as conn:
        await act_as_user(conn, world.tenant.tenant_id, second.id)
        seen = await conn.scalar(
            sa.text("SELECT count(*) FROM studio.record_write_keys WHERE write_key = :k"),
            {"k": key},
        )
    assert seen == 0


async def test_gate_a_only_a_step_s_wf_key_reaches_a_write_key(world: World) -> None:
    person = await world.person()
    with pytest.raises(ValueError, match="wf:"):
        await world.service.create(world.door(person), LEAD, {"name": "x"}, write_key="http:abc")


# ---- R5.9: the purge of the keys (gate (p)) -------------------------------------


async def _keyed_record(world: World, tenant: PlantedTenant, lead: uuid.UUID, age: int) -> str:
    """A record and one write key of a new principal, ``age`` days old."""
    key, record = wf_key(), uuid.uuid4()
    async with world.migrator.begin() as conn:
        person = await holder(conn, tenant, lead, {"read": "workspace"})
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.tenant_id)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id,"
                " owner_kind, owner_id, name, created_by, updated_by)"
                " VALUES (:r, :t, :o, :w, 'user', :p, 'k', :p, :p)"
            ),
            {"r": record, "t": tenant.tenant_id, "o": lead, "w": tenant.main, "p": person.id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.record_write_keys (tenant_id, write_key, record_id, op,"
                " version, actor_id, created_at)"
                " VALUES (:t, :k, :r, 'update', 1, :p, now() - make_interval(days => :d))"
            ),
            {"t": tenant.tenant_id, "k": key, "r": record, "p": person.id, "d": age},
        )
    return key


async def test_r5_9_gate_p_the_definer_purges_every_company_s_expired_keys(
    world: World,
) -> None:
    async with world.migrator.begin() as conn:
        other = await plant_tenant(conn)
        manager = await plant_manager(conn, other)
    other_lead = await publish_object(world.sessions, manager, LEAD, lead_document())
    old = [
        await _keyed_record(world, world.tenant, world.lead, 32),
        await _keyed_record(world, other, other_lead, 32),
    ]
    young = [await _keyed_record(world, world.tenant, world.lead, 30)]

    async def left(keys: list[str]) -> int:
        return await world.count(
            "SELECT count(*) FROM studio.record_write_keys WHERE write_key = ANY(:k)", k=keys
        )

    # `dw_app` alone sees no other principal's key: a plain DELETE removes none.
    async with world.app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(world.tenant.tenant_id)},
        )
        removed = await conn.execute(
            sa.text("DELETE FROM studio.record_write_keys WHERE write_key = ANY(:k)"), {"k": old}
        )
    assert removed.rowcount == 0 and await left(old) == 2

    # No term, no purge: the function raises and the transaction keeps every row.
    with pytest.raises(DBAPIError):
        async with world.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "DELETE FROM platform.retention_terms"
                    " WHERE store_key = 'studio.record_write_keys'"
                )
            )
            await conn.execute(sa.text("SELECT studio.purge_expired_record_write_keys()"))
    assert await left(old) == 2

    await SqlRecordWriteKeyRetention(world.sessions).purge()
    assert await left(old) == 0
    assert await left(young) == 1


# ---- R5.9 (gate (c)): the door binds, the service never does -------------------


async def test_r5_9_a_transaction_bound_to_no_actor_reads_nothing(world: World) -> None:
    person = await world.person()
    made = await world.service.create(world.door(person), LEAD, {"name": "Thấy"})
    bare = RecordDoor(
        lambda: tenant_session(
            world.sessions,
            TenantScope(
                tenant_id=person.tenant_id,
                workspace_id=person.workspace_id,
                principal_id=person.id,
            ),
        )
    )
    with pytest.raises(NotFoundError, match="record not found"):
        await world.service.get(bare, LEAD, made.record.id)
    with pytest.raises(NotFoundError, match="record not found"):
        await world.service.create(bare, LEAD, {"name": "Không"})


# ---- R5.4: simulate and test ----------------------------------------------------


async def _totals(world: World) -> tuple[int, int, int]:
    return (
        await records_of(world),
        await world.count("SELECT count(*) FROM platform.outbox_events"),
        await world.count("SELECT count(*) FROM platform.audit_events"),
    )


async def test_r5_4_co13_a_simulated_write_checks_everything_and_writes_nothing(
    world: World,
) -> None:
    person = await world.person()
    door = world.door(person)
    stranger = await world.person(workspace=world.tenant.workspaces[1])
    taken, mine = phone(), phone()
    await world.service.create(
        world.door(stranger), LEAD, {"name": "Ở ws2", "fields": {"phone": taken}}
    )
    kept = await world.service.create(door, LEAD, {"name": "Của tôi", "fields": {"phone": mine}})
    before = await _totals(world)
    modes: tuple[RunMode, ...] = ("simulate", "test")
    for mode in modes:
        made = await world.service.create(
            door,
            LEAD,
            {"name": "Giả", "fields": {"phone": taken}},
            run_mode=mode,
        )
        assert (
            made.created and made.version == 1 and made.record.fields["phone"] == "+84" + taken[1:]
        )
        with pytest.raises(DuplicateValueError):
            await world.service.create(
                door,
                LEAD,
                {"name": "Giả", "fields": {"phone": mine}},
                run_mode=mode,
            )
        changed = await world.service.update(
            door,
            LEAD,
            kept.record.id,
            {"name": "Đổi"},
            expected=1,
            run_mode=mode,
        )
        assert changed.record.version == 2 and changed.record.name == "Đổi"
        upserted = await world.service.upsert(
            door,
            LEAD,
            {"match_field": "phone", "name": "U", "fields": {"phone": taken}},
            run_mode=mode,
        )
        assert upserted.created
        deleted = await world.service.delete(door, LEAD, kept.record.id, expected=1, run_mode=mode)
        assert deleted.record.deleted_at is not None
    assert await _totals(world) == before
    assert (await world.service.get(door, LEAD, kept.record.id)).version == 1
    decision = await world.service.limiter.peek(
        PrincipalObjectKey(TenantId(person.tenant_id), person.id, world.lead),
        DUPLICATE_LIMIT,
        timedelta(minutes=10),
    )
    assert decision.allowed


# ---- R7.3, R7.4, R7.2: the upsert ------------------------------------------------


async def test_r7_3_co17_two_concurrent_upserts_of_one_number_make_one_record(
    world: World,
) -> None:
    person = await world.person()
    door = world.door(person)
    digits = str(uuid.uuid4().int)[:8]
    national, e164 = f"09{digits[:1]} {digits[1:4]} {digits[4:]}", f"+849{digits}"
    results = await asyncio.gather(
        world.service.upsert(
            door, LEAD, {"match_field": "phone", "name": "Một", "fields": {"phone": national}}
        ),
        world.service.upsert(
            door, LEAD, {"match_field": "phone", "name": "Một", "fields": {"phone": e164}}
        ),
    )
    assert results[0].record.id == results[1].record.id
    assert sorted(r.created for r in results) == [False, True]
    assert (
        await world.count(
            "SELECT count(*) FROM studio.records WHERE object_id = :o AND u01 = :p",
            o=world.lead,
            p=e164,
        )
        == 1
    )
    other = await world.service.upsert(
        door, LEAD, {"match_field": "phone", "name": "Một", "fields": {"phone": phone()}}
    )
    assert other.created and other.record.id != results[0].record.id


async def test_r7_3_co17_an_old_and_a_new_writing_of_one_number_race_to_one_record(
    world: World,
) -> None:
    """Custom-objects ticket 10: "0168 456 7890", written before decision
    `798/QĐ-BTTTT` renumbered Viettel's 168 as 38, is the person's "038 456
    7890"; two concurrent upserts of the two leave one record, kept under the
    new number."""
    person = await world.person()
    door = world.door(person)
    tail = str(uuid.uuid4().int)[:7]
    old, new = f"0168 {tail[:3]} {tail[3:]}", f"038 {tail[:3]} {tail[3:]}"
    results = await asyncio.gather(
        world.service.upsert(
            door, LEAD, {"match_field": "phone", "name": "Cũ", "fields": {"phone": old}}
        ),
        world.service.upsert(
            door, LEAD, {"match_field": "phone", "name": "Mới", "fields": {"phone": new}}
        ),
    )
    assert results[0].record.id == results[1].record.id
    assert sorted(r.created for r in results) == [False, True]
    assert {r.record.fields["phone"] for r in results} == {f"+8438{tail}"}
    assert (
        await world.count(
            "SELECT count(*) FROM studio.records WHERE object_id = :o AND u01 IN (:new, :old)",
            o=world.lead,
            new=f"+8438{tail}",
            old=f"+84168{tail}",
        )
        == 1
    )


async def test_r7_2_s_the_update_branch_is_a_merge_patch_and_no_change_writes_nothing(
    world: World,
) -> None:
    person = await world.person()
    door = world.door(person)
    number = phone()
    made = await world.service.upsert(
        door,
        LEAD,
        {"match_field": "phone", "name": "Tên", "fields": {"phone": number, "note": "đầu"}},
    )
    assert made.created
    again = await world.service.upsert(
        door, LEAD, {"match_field": "phone", "fields": {"phone": number, "amount": "5"}}
    )
    assert not again.created and again.record.version == 2
    assert again.record.name == "Tên" and again.record.fields["note"] == "đầu"
    assert again.record.fields["amount"] == "5"
    same = await world.service.upsert(
        door, LEAD, {"match_field": "phone", "fields": {"phone": number, "amount": "5"}}
    )
    assert not same.created and same.record.version == 2
    assert await events(world, made.record.id) == ["studio.record.created", "studio.record.updated"]


async def test_r7_4_co16_a_match_the_caller_cannot_change_is_a_plain_duplicate(
    world: World,
) -> None:
    owner = await world.person()
    number = phone()
    made = await world.service.create(
        world.door(owner), LEAD, {"name": "Chủ", "fields": {"phone": number}}
    )
    reader_creator = await world.person({"read": "workspace", "create": "workspace"})
    with pytest.raises(DuplicateValueError) as refused:
        await world.service.upsert(
            world.door(reader_creator),
            LEAD,
            {"match_field": "phone", "name": "Đè", "fields": {"phone": number}},
        )
    assert [p.pointer for p in refused.value.problems] == ["/fields/phone"]
    got = await world.service.get(world.door(owner), LEAD, made.record.id)
    assert (got.name, got.version) == ("Chủ", 1)
    (audit,) = (await audits(world, world.lead, "studio.record.duplicate_refused"))[-1:]
    assert audit.actor_id == reader_creator.id
    assert audit.details == {"object_id": str(world.lead), "field": "phone"}


async def _refused_upsert(
    world: World,
    prober: Person,
    body: dict[str, Any],
    made: uuid.UUID,
    number: str,
    *,
    door: RecordDoor | None = None,
    write_key: str | None = None,
) -> None:
    """One upsert onto ``made``, refused as a plain duplicate: the field's
    pointer and nothing else, no record id or number in what the caller gets,
    one audit of keys only, and ``made`` as its owner left it."""
    before = await records_of(world)
    with pytest.raises(DuplicateValueError) as refused:
        await world.service.upsert(door or world.door(prober), LEAD, body, write_key=write_key)
    assert [(p.pointer, p.code) for p in refused.value.problems] == [
        ("/fields/phone", "duplicate_value")
    ]
    said = f"{refused.value} {refused.value.details} {refused.value.problems}"
    assert str(made) not in said and number[1:] not in said
    assert await records_of(world) == before
    assert await events(world, made) == ["studio.record.created"]
    (audit,) = (await audits(world, world.lead, "studio.record.duplicate_refused"))[-1:]
    assert audit.actor_id == prober.id
    assert audit.details == {"object_id": str(world.lead), "field": "phone"}


async def test_r7_4_co16_an_upsert_onto_a_record_the_caller_cannot_read_reveals_nothing(
    world: World,
) -> None:
    """Discovery 10 (b), FOG-42: the upsert's SELECT, `ON CONFLICT DO NOTHING`
    and conditional UPDATE under the full record policies. The prober holds
    every action on the object at workspace depth, in another workspace than
    the record's, so only the read reach keeps the row from it. Sent with the
    record's own values the update branch would write nothing and answer with
    the record, so those bodies are the ones only the SELECT policy refuses."""
    owner = await world.person(workspace=world.tenant.workspaces[1])
    number = phone()
    made = await world.service.create(
        world.door(owner), LEAD, {"name": "Gốc", "fields": {"phone": number, "note": "gốc"}}
    )
    prober = await world.person()
    with pytest.raises(NotFoundError):
        await world.service.get(world.door(prober), LEAD, made.record.id)

    for body in (
        {"match_field": "phone", "name": "Đè", "fields": {"phone": number, "note": "đè"}},
        {"match_field": "phone", "name": "Gốc", "fields": {"phone": number, "note": "gốc"}},
        # Another writing of the same number reaches the same row (R6.2).
        {"match_field": "phone", "name": "Gốc", "fields": {"phone": "+84" + number[1:]}},
    ):
        await _refused_upsert(world, prober, body, made.record.id, number)
    got = await world.service.get(world.door(owner), LEAD, made.record.id)
    assert (got.name, got.version, got.fields["note"]) == ("Gốc", 1, "gốc")

    # Without a name the upsert is a create that lacks one: the same 422 as
    # for a number nobody holds, so the answer cannot tell the two apart.
    answers = []
    for held in (number, phone()):
        with pytest.raises(RecordInvalidError) as invalid:
            await world.service.upsert(
                world.door(prober), LEAD, {"match_field": "phone", "fields": {"phone": held}}
            )
        answers.append([(p.pointer, p.code) for p in invalid.value.problems])
    assert answers == [[("/name", "required")]] * 2


async def test_r7_4_co16_a_readable_match_out_of_update_reach_is_a_plain_duplicate(
    world: World,
) -> None:
    """The UPDATE policy's own half (failure-modes #3, one test per layer):
    the prober reads the record across the company but changes only its own
    workspace's, so its upsert reaches the update branch and the policy's
    USING refuses the row."""
    owner = await world.person(workspace=world.tenant.workspaces[1])
    number = phone()
    made = await world.service.create(
        world.door(owner), LEAD, {"name": "Gốc", "fields": {"phone": number, "note": "gốc"}}
    )
    prober = await world.person({"read": "tenant", "create": "workspace", "update": "workspace"})
    seen = await world.service.get(world.door(prober), LEAD, made.record.id)
    assert not seen.permissions.update
    await _refused_upsert(
        world,
        prober,
        {"match_field": "phone", "name": "Đè", "fields": {"phone": number, "note": "đè"}},
        made.record.id,
        number,
    )
    got = await world.service.get(world.door(owner), LEAD, made.record.id)
    assert (got.name, got.version, got.fields["note"]) == ("Gốc", 1, "gốc")


async def _keys(world: World, key: str) -> int:
    return await world.count(
        "SELECT count(*) FROM studio.record_write_keys WHERE write_key = :k", k=key
    )


async def _out_of_reach(world: World) -> tuple[Person, uuid.UUID, str]:
    """A record in the second workspace and a prober who reads it across the
    company and changes only its own workspace's records: `may_update` is
    false by the record's reach alone, the key `update` held."""
    owner = await world.person(workspace=world.tenant.workspaces[1])
    number = phone()
    made = await world.service.create(
        world.door(owner), LEAD, {"name": "Gốc", "fields": {"phone": number, "note": "gốc"}}
    )
    prober = await world.person({"read": "tenant", "create": "workspace", "update": "workspace"})
    seen = await world.service.get(world.door(prober), LEAD, made.record.id)
    assert not seen.permissions.update
    return prober, made.record.id, number


async def test_r7_4_co16_an_unchanged_upsert_out_of_update_reach_is_a_duplicate(
    world: World,
) -> None:
    """Custom-objects ticket 11: an upsert that changes nothing runs no UPDATE
    for the policy to refuse, so the row's `may_update` does; every shape of
    the unchanged upsert is the plain 409 of R7.4, and a step's `wf:` key
    keeps no row for a record it may not change."""
    prober, made, number = await _out_of_reach(world)
    for body in (
        {"match_field": "phone", "name": "Gốc", "fields": {"phone": number, "note": "gốc"}},
        {"match_field": "phone", "fields": {"phone": number}},
        {"match_field": "phone", "name": "Gốc", "fields": {"phone": "+84" + number[1:]}},
        {"match_field": "phone", "fields": {"phone": number[:4] + " " + number[4:], "note": "gốc"}},
    ):
        await _refused_upsert(world, prober, body, made, number)

    run = await world.run(prober.id)
    key = wf_key()
    await _refused_upsert(
        world,
        prober,
        {"match_field": "phone", "fields": {"phone": number}},
        made,
        number,
        door=run,
        write_key=key,
    )
    assert await _keys(world, key) == 0


async def test_r5_8_an_unchanged_patch_out_of_update_reach_is_refused(world: World) -> None:
    """The same branch through `PATCH` (app-standards R3.16): 403, nothing
    written, no key kept."""
    prober, made, _ = await _out_of_reach(world)
    run = await world.run(prober.id)
    for door, patch, key in (
        (world.door(prober), {"name": "Gốc", "fields": {"note": "gốc"}}, None),
        (world.door(prober), {}, None),
        (run, {"fields": {"note": "gốc"}}, wf_key()),
    ):
        with pytest.raises(PermissionDeniedError):
            await world.service.update(door, LEAD, made, patch, write_key=key)
        if key is not None:
            assert await _keys(world, key) == 0
    assert await events(world, made) == ["studio.record.created"]
    seen = await world.service.get(world.door(prober), LEAD, made)
    assert (seen.version, seen.fields["note"]) == (1, "gốc")


async def test_r7_4_an_unchanged_upsert_in_reach_answers_with_the_record(world: World) -> None:
    """The other side of ticket 11's check: in the prober's own workspace the
    unchanged upsert is still 200 `created: false`, and a step's key is kept
    (R5.9)."""
    prober = await world.person({"read": "tenant", "create": "workspace", "update": "workspace"})
    number = phone()
    made = await world.service.create(
        world.door(prober), LEAD, {"name": "Mình", "fields": {"phone": number}}
    )
    same = {"match_field": "phone", "fields": {"phone": number}}
    again = await world.service.upsert(world.door(prober), LEAD, same)
    assert (again.created, again.version, again.record.permissions.update) == (False, 1, True)
    key = wf_key()
    stepped = await world.service.upsert(await world.run(prober.id), LEAD, same, write_key=key)
    assert (stepped.created, stepped.version) == (False, 1)
    assert await _keys(world, key) == 1
    assert await events(world, made.record.id) == ["studio.record.created"]


# ---- R7.6: the duplicate-probe limit, by actor kind (gate (d)) -------------------


async def _probe(world: World, door: RecordDoor, number: str) -> str:
    try:
        await world.service.create(door, LEAD, {"name": "Dò", "fields": {"phone": number}})
    except DuplicateValueError:
        return "409"
    except DuplicateThrottledError:
        return "429"
    return "201"


async def test_r7_6_co18_an_agent_counts_and_a_workflow_never_does(world: World) -> None:
    owner = await world.person()
    number = phone()
    await world.service.create(world.door(owner), LEAD, {"name": "Có", "fields": {"phone": number}})

    agent = await world.person()
    agent_door = await world.run(agent.id, kind="agent")
    answers = [await _probe(world, agent_door, number) for _ in range(DUPLICATE_LIMIT + 1)]
    assert answers == ["409"] * DUPLICATE_LIMIT + ["429"]
    # Every later write of the agent on the object waits, a new number too.
    assert await _probe(world, agent_door, phone()) == "429"
    # Its person through the API shares the window: one key, gate (v).
    assert await _probe(world, world.door(agent), phone()) == "429"

    intake = await world.person(kind="service")
    intake_door = await world.run(intake.id)
    before = len(await audits(world, world.lead, "studio.record.duplicate_refused"))
    answers = [await _probe(world, intake_door, number) for _ in range(DUPLICATE_LIMIT + 3)]
    assert answers == ["409"] * (DUPLICATE_LIMIT + 3)
    refused = await audits(world, world.lead, "studio.record.duplicate_refused")
    assert len(refused) - before == DUPLICATE_LIMIT + 3
    assert refused[-1].actor_id == intake.id


async def test_r7_6_the_window_slides_and_holds_one_person_on_one_object(world: World) -> None:
    owner = await world.person()
    number = phone()
    await world.service.create(world.door(owner), LEAD, {"name": "Có", "fields": {"phone": number}})
    prober = await world.person()
    door = world.door(prober)
    started = world.clock.at
    for _ in range(DUPLICATE_LIMIT):
        assert await _probe(world, door, number) == "409"
    with pytest.raises(DuplicateThrottledError) as throttled:
        await world.service.create(door, LEAD, {"name": "Mới", "fields": {"phone": phone()}})
    assert throttled.value.retry_after_seconds == 600
    assert await _probe(world, world.door(owner), phone()) == "201"
    world.clock.at = started + timedelta(minutes=10, seconds=1)
    try:
        assert await _probe(world, door, phone()) == "201"
    finally:
        world.clock.at = started


# ---- R5.8: what the policies refuse ---------------------------------------------


async def test_r5_8_gate_f_a_soft_delete_needs_delete_reach_in_with_check(world: World) -> None:
    owner = await world.person()
    made = await world.service.create(world.door(owner), LEAD, {"name": "Giữ"})
    # Update across the workspace, delete only on its own records: the key is
    # held, the UPDATE's USING admits the row, its WITH CHECK refuses it.
    near = await world.person({"read": "workspace", "update": "workspace", "delete": "own"})
    got = await world.service.get(world.door(near), LEAD, made.record.id)
    assert got.permissions.update and not got.permissions.delete
    with pytest.raises(PermissionDeniedError):
        await world.service.delete(world.door(near), LEAD, made.record.id, expected=1)
    assert (await world.service.get(world.door(owner), LEAD, made.record.id)).deleted_at is None

    far = await world.person()
    assert (await world.service.get(world.door(far), LEAD, made.record.id)).permissions.delete
    gone = await world.service.delete(world.door(far), LEAD, made.record.id, expected=1)
    assert gone.record.deleted_by == far.id
    with pytest.raises(NotFoundError):
        await world.service.update(world.door(far), LEAD, made.record.id, {"name": "x"}, expected=2)


async def test_r5_8_gate_l_permissions_are_what_the_policies_do(world: World) -> None:
    """`permissions` beside what an UPDATE (rolled back) actually does, for
    readers of every shape; the expression is the policy module's own."""
    owner = await world.person()
    made = await world.service.create(world.door(owner), LEAD, {"name": "So"})
    shapes = [
        {"read": "workspace"},
        {"read": "workspace", "update": "workspace"},
        {"read": "workspace", "update": "workspace", "delete": "own"},
        {"read": "workspace", "update": "workspace", "delete": "workspace"},
        {"read": "workspace", "update": "own", "delete": "workspace"},
    ]
    for shape in shapes:
        person = await world.person(shape)
        said = (await world.service.get(world.door(person), LEAD, made.record.id)).permissions
        did: dict[str, bool] = {}
        for command, statement in (
            ("update", "UPDATE studio.records SET name = name WHERE id = :r"),
            ("delete", "UPDATE studio.records SET deleted_at = now() WHERE id = :r"),
        ):
            async with world.app.connect() as conn:
                transaction = await conn.begin()
                await act_as_user(conn, person.tenant_id, person.id)
                try:
                    did[command] = (
                        await conn.execute(sa.text(statement), {"r": made.record.id})
                    ).rowcount == 1
                except DBAPIError:
                    did[command] = False
                await transaction.rollback()
        assert (said.update, said.delete) == (did["update"], did["delete"]), shape
    assert "acl_objects('update'" in may_sql("update")


# ---- R6.6, R3.6: fields --------------------------------------------------------


async def test_r6_6_co7_name_goes_through_the_field_decision(world: World) -> None:
    owner = await world.person()
    made = await world.service.create(
        world.door(owner), LEAD, {"name": "Bí mật", "fields": {"phone": phone()}}
    )
    blind = await world.person(fields={"phone": "edit"})
    got = await world.service.get(world.door(blind), LEAD, made.record.id)
    assert got.name is None and "name" in got.hidden_fields
    assert "Bí mật" not in str(got)
    with pytest.raises(FieldNotEditableError) as refused:
        await world.service.update(
            world.door(blind), LEAD, made.record.id, {"name": "Lộ"}, expected=1
        )
    assert [p.pointer for p in refused.value.problems] == ["/name"]


async def test_a_service_account_never_reads_a_sensitive_unique_field(world: World) -> None:
    """tenant-rbac R9.9 over field-security's unique rule (ADR-0106, 2026-11-05):
    a person who creates sees the unique sensitive field, a service account
    with the same keys does not."""
    owner = await world.person(fields={**EDIT_ALL, "cccd": "edit"})
    made = await world.service.create(
        world.door(owner), LEAD, {"name": "Có CCCD", "fields": {"cccd": "079123456789"}}
    )
    person = await world.person()
    service = await world.person(kind="service")
    seen = await world.service.get(world.door(person), LEAD, made.record.id)
    hidden = await world.service.get(world.door(service), LEAD, made.record.id)
    assert seen.fields.get("cccd") == "079123456789"
    assert "cccd" in hidden.hidden_fields and "cccd" not in hidden.fields
    assert "079123456789" not in str(hidden)


async def test_r3_6_r3_7_the_schemas_hold_what_the_caller_may_see_and_write(world: World) -> None:
    reader = await world.person({"read": "workspace"}, {"name": "read"})
    seen = await world.service.schemas(world.door(reader), LEAD)
    filters = seen.query["$defs"]["node_1"]["properties"]
    assert "phone" not in filters and "cccd" not in filters
    assert "phone" not in seen.ai_descriptions.fields
    assert seen.create["properties"] == {} and seen.update["properties"] == {}
    creator = await world.person({"read": "workspace", "create": "workspace"}, {"name": "edit"})
    made = await world.service.schemas(world.door(creator), LEAD)
    # A unique field is readable to a creator, never writable without its key.
    assert set(made.create["properties"]) == {"name", "note", "amount"}
    assert "phone" in made.query["$defs"]["node_1"]["properties"]
    assert made.create["properties"]["amount"]["anyOf"][0]["type"] == "string"


# ---- the shared lock -----------------------------------------------------------


async def test_a_write_waits_for_the_definition_s_exclusive_lock(world: World) -> None:
    person = await world.person()
    async with world.migrator.connect() as conn:
        transaction = await conn.begin()
        await conn.execute(
            sa.text("SELECT pg_advisory_xact_lock(:k)"),
            {"k": object_lock_key(world.tenant.tenant_id, world.lead)},
        )
        write = asyncio.ensure_future(
            world.service.create(world.door(person), LEAD, {"name": "Chờ"})
        )
        await asyncio.sleep(1.0)
        assert not write.done()
        await transaction.rollback()
    assert (await asyncio.wait_for(write, 10)).created


# ---- R4.4: offboarding ---------------------------------------------------------


async def test_r4_4_co20_offboarding_exports_each_record_and_key_once(world: World) -> None:
    async with world.migrator.begin() as conn:
        leaving = await plant_tenant(conn, workspaces=2)
        manager = await plant_manager(conn, leaving)
    lead = await publish_object(world.sessions, manager, LEAD, lead_document())
    made = 0
    for workspace in leaving.workspaces:
        async with world.migrator.begin() as conn:
            person = await holder(
                conn,
                leaving,
                lead,
                dict.fromkeys(("read", "create", "update"), "workspace"),
                EDIT_ALL,
                workspace=workspace,
            )
        if workspace == leaving.main:
            principal = person
        door = person_door(world.sessions, person)
        for n in range(2):
            await world.service.create(door, LEAD, {"name": f"R{n}"})
            made += 1
    run = await plant_run(
        world.migrator,
        world.app,
        leaving,
        principal.id,
        [ObjectBoundary(LEAD, True, True, True, False, False)],
        [FieldBoundary(LEAD, "name", "edit")],
    )
    step = run_door(world.sessions, leaving, principal.id, run)
    record = await world.service.create(step, LEAD, {"name": "Bước"})
    made += 1
    await world.service.update(step, LEAD, record.record.id, {"name": "Đổi"}, write_key=wf_key())
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": leaving.tenant_id},
        )
    lane = SqlTenantOffboarding(session_factory=world.sessions, scopes=OFFBOARDING_SCOPES)
    exported: dict[str, list[Any]] = {}
    async for batch in lane.export_rows(leaving.tenant_id):
        exported.setdefault(f"{batch.schema}.{batch.table}", []).extend(batch.rows)
    ids = [row["id"] for row in exported["studio.records"]]
    assert len(ids) == len(set(ids)) == made
    assert len(exported["studio.record_write_keys"]) == 1
    await lane.purge_rows(leaving.tenant_id)
    assert (
        await world.count(
            "SELECT count(*) FROM studio.records WHERE tenant_id = :t", t=leaving.tenant_id
        )
        == 0
    )
    assert (
        await world.count(
            "SELECT count(*) FROM studio.record_write_keys WHERE tenant_id = :t",
            t=leaving.tenant_id,
        )
        == 0
    )
