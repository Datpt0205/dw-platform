"""An agent's object tools on PostgreSQL, through the real path
(tools-and-skills ticket 03: R6.1-R6.7; TS8, TS9).

The composition a Studio run will have (agent-builder/03 wires it where it
takes the run): `ObjectToolGenerator` loaded for the run's company, the
pinned object version read back from `studio.artifact_versions`, the tools
built by the runtime's `ToolAssembler` and called through a real
`ToolExecutor` over the SQL stores, `RecordObjectData` over `RecordService`,
each call's transaction opened by `agent_record_session` from the run row
(the actor `agent`, the run's principal within its published boundary). So
the record policies, the field decision and RLS decide every answer here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from studio_planted_runs import plant_run

from dw_agent_runtime.adapters.record_session import agent_record_session
from dw_agent_runtime.adapters.tool_claims import SqlToolClaims
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.ports import ObjectSearch, PinnedEntry, PinnedVersion
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.tool_kinds import ToolAssembler
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import DomainError, NotFoundError
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_kernel.run_mode import RunMode
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.adapters.rate_limit import InProcessRateLimiter
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.core.application.field_access import FieldAccessService
from dw_studio.core.domain.toolset import ObjectCrudEntry
from dw_studio.records.adapters.definition_store import SqlObjectDefinitionReader
from dw_studio.records.adapters.record_store import SqlRecordStore
from dw_studio.records.application.object_tools import ObjectToolGenerator
from dw_studio.records.application.record_service import RecordDoor, RecordService
from dw_studio.records.application.schema_projector import ObjectSchemaProjector
from dw_studio.records.presentation.object_data import RecordObjectData
from dw_studio.testing.object_tools import object_tool_copy
from dw_studio.testing.objects import object_document, object_field, plant_manager
from dw_studio.testing.record_world import (
    holder,
    person_door,
    publish_next,
    publish_object,
    sessions_of,
)
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

REPO = Path(__file__).resolve().parents[5]
LEAD = "mkt_lead"
EVENT = "mkt_event"
LEAD_FIELDS = ("name", "phone", "status", "note")
READ_ALL = {"read": "workspace"}


def lead_v1() -> dict[str, Any]:
    return object_document(
        object_field("phone", "phone", pd_category="basic", is_unique=True),
        object_field("status", "picklist", indexed=True),
        object_field("note", max_length=200),
    )


def lead_v2() -> dict[str, Any]:
    """v1 and `budget`, published after the agent pinned v1 (R6.1)."""
    document = lead_v1()
    document["fields"] = [*document["fields"], object_field("budget", "currency", indexed=True)]
    return document


def event_document() -> dict[str, Any]:
    return object_document(
        object_field("kind", "picklist", indexed=True),
        object_field("legacy_code", indexed=True),
        name_field={"labels": {"vi": "Tên"}, "pd_category": "none"},
    )


def phone() -> str:
    return "09" + str(uuid.uuid4().int)[:8]


@dataclass
class Company:
    tenant: PlantedTenant
    manager: Person
    lead: uuid.UUID


@dataclass
class World:
    a: Company
    b: Company
    event: uuid.UUID
    sessions: async_sessionmaker[AsyncSession]
    migrator: AsyncEngine
    app: AsyncEngine
    records: RecordService
    executor: ToolExecutor
    pinned_lead: PinnedEntry

    def door(self, person: Person) -> RecordDoor:
        return person_door(self.sessions, person)


async def version_row(migrator: AsyncEngine, artifact: uuid.UUID, number: int) -> PinnedEntry:
    """The manifest's entry for the object at version ``number``, its row read
    back from `studio.artifact_versions` as `SqlRunManifestStore` reads it."""
    async with migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT id, artifact_id, version_no, stage, content_hash, definition_hash,"
                    " document_schema, document FROM studio.artifact_versions"
                    " WHERE artifact_id = :a AND version_no = :n"
                ),
                {"a": artifact, "n": number},
            )
        ).one()
    version = PinnedVersion(
        id=row.id,
        artifact_id=row.artifact_id,
        version_no=row.version_no,
        stage=row.stage,
        content_hash=row.content_hash,
        definition_hash=row.definition_hash,
        document_schema=row.document_schema,
        document=row.document,
        current_hash=None,
    )
    return PinnedEntry("artifact", str(artifact), number, row.content_hash, version)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(studio_db: DatabaseUrls) -> AsyncIterator[World]:
    migrator = create_async_engine(studio_db.migrator, poolclass=NullPool)
    app = create_async_engine(studio_db.app, poolclass=NullPool)
    sessions = sessions_of(app)
    companies = []
    for _ in range(2):
        async with migrator.begin() as conn:
            tenant = await plant_tenant(conn, workspaces=1)
            manager = await plant_manager(conn, tenant)
        lead = await publish_object(sessions, manager, LEAD, lead_v1())
        companies.append(Company(tenant, manager, lead))
    a, b = companies
    pinned_lead = await version_row(migrator, a.lead, 1)
    await publish_next(sessions, a.manager, a.lead, lead_v2())
    event = await publish_object(sessions, a.manager, EVENT, event_document())
    clock = SystemClock()
    records = RecordService(
        SqlRecordStore(),
        FieldAccessService(SqlFieldSecurityInputs()),
        InProcessRateLimiter(1, clock),
        ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
        clock,
        Uuid7Generator(),
    )
    executor = ToolExecutor(
        registry=ToolRegistry(),
        execution_store=SqlToolExecutionStore(sessions),
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        clock=clock,
        id_generator=Uuid7Generator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=SqlToolClaims(sessions),
        steps=build_tool_executor_steps(),
        run_control=OpenRunControl(),
    )
    yield World(a, b, event, sessions, migrator, app, records, executor, pinned_lead)
    await app.dispose()
    await migrator.dispose()


# ---- the run, as agent-builder/03 will compose it -----------------------------


@dataclass
class Spy:
    """`RecordObjectData` that counts what reaches it."""

    inner: RecordObjectData
    calls: int = 0

    async def search(self, run: RunContext, api_name: str, request: ObjectSearch) -> Any:
        self.calls += 1
        return await self.inner.search(run, api_name, request)

    async def get(
        self, run: RunContext, api_name: str, record_id: uuid.UUID, fields: frozenset[str]
    ) -> Any:
        self.calls += 1
        return await self.inner.get(run, api_name, record_id, fields)

    async def readable(self, run: RunContext, api_name: str) -> frozenset[str]:
        return await self.inner.readable(run, api_name)


@dataclass
class Run:
    context: RunContext
    tools: Mapping[str, RegisteredTool]
    data: Spy
    world: World
    api_name: str

    async def call(self, operation: str, raw: dict[str, object]) -> dict[str, Any]:
        tool = self.tools[operation]
        output = await self.world.executor.execute(
            name=tool.definition.name,
            version=tool.definition.version,
            raw_input=raw,
            run_context=self.context,
            pinned=tool,
        )
        return output.model_dump(mode="json")

    async def readable(self) -> frozenset[str]:
        return await self.data.readable(self.context, self.api_name)


async def start(
    world: World,
    company: Company,
    principal: uuid.UUID,
    *,
    object_id: uuid.UUID | None = None,
    pinned: PinnedEntry | None = None,
    fields: Sequence[str] = LEAD_FIELDS,
    api_name: str = LEAD,
    mode: RunMode = "live",
) -> Run:
    """A run of an agent acting as ``principal`` whose published boundary
    reads ``api_name`` and ``fields``, and its pinned object tools."""
    object_id = object_id or company.lead
    pinned = pinned or world.pinned_lead
    run_id = await plant_run(
        world.migrator,
        world.app,
        company.tenant,
        principal,
        [ObjectBoundary(api_name, True, False, False, False, False)],
        [FieldBoundary(api_name, name, "read") for name in fields],
        kind="agent",
        mode=mode,
    )
    async with world.migrator.connect() as conn:
        manifest = await conn.scalar(
            sa.text("SELECT run_manifest_hash FROM platform.worker_runs WHERE id = :r"),
            {"r": run_id},
        )
    context = RunContext(
        run_id=run_id,
        tenant_id=company.tenant.tenant_id,
        workspace_id=company.tenant.main,
        # The person the run acts for; a service account would be
        # `run_as_principal_id`, which the executor reads as a DW's boundary.
        actor_id=principal,
        worker_id="studio:agent:lead",
        worker_version="1.0.0",
        channel="test",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="trace",
        run_mode=mode,
        run_manifest_hash=manifest,
        # A1 reaches rung `none`: a read runs without a person (A0 reaches nothing).
        autonomy_ceiling="A1",
        autonomy_level="A1",
    )
    sessions = world.sessions
    data = Spy(
        RecordObjectData(
            world.records,
            lambda run: RecordDoor(lambda: agent_record_session(sessions, run), run_id=run.run_id),
        )
    )
    entry = ObjectCrudEntry(kind="object_crud", object=object_id, operations=("search", "get"))
    generator = await ObjectToolGenerator.load(
        SqlObjectDefinitionReader(sessions),
        company.tenant.tenant_id,
        [entry],
        data=data,
        copy=object_tool_copy(REPO),
    )
    assembler = ToolAssembler(registry=ToolRegistry(), kinds={"object_crud": generator})
    tools = {
        compiled.contract.definition.name.rsplit(".", 1)[1]: assembler.build(
            compiled.binding, compiled.contract
        )
        for compiled in generator.compile(entry, pinned)
    }
    return Run(context, tools, data, world, api_name)


async def reader(
    world: World, company: Company, depth: str, *, creates: bool = True, **fields: str
) -> Person:
    """A member reading leads at ``depth``. One who creates also reads every
    unique field (`phone`), whatever its key (ADR-0106 decision 4)."""
    actions = {"read": depth, "create": "workspace"} if creates else {"read": depth}
    async with world.migrator.begin() as conn:
        return await holder(
            conn,
            company.tenant,
            company.lead,
            actions,
            {"name": "edit", "status": "read", "note": "read"} | fields,
        )


async def lead_of(world: World, company: Company, owner: Person, **values: Any) -> uuid.UUID:
    created = await world.records.create(
        world.door(owner),
        LEAD,
        {"name": f"Lead {uuid.uuid4().hex[:6]}", "fields": {"phone": phone(), **values}},
    )
    return created.record.id


async def statuses(world: World, run: Run) -> list[str]:
    async with world.migrator.connect() as conn:
        rows = await conn.execute(
            sa.text("SELECT status FROM platform.tool_executions WHERE run_id = :r ORDER BY 1"),
            {"r": run.context.run_id},
        )
        return [row.status for row in rows]


# ------------------------------------------------------------- R6.1, R6.2 --


async def test_r6_1_r6_2_search_reads_the_pinned_fields_as_the_runs_actor(world: World) -> None:
    """R6.1: v2 (with `budget`) is live, the run pinned v1: the search answers
    without `budget` and is no `tool_output_invalid`. R6.2: at the depth
    "Của tôi" the actor sees the leads it owns and no one else's."""
    a = world.a
    owner = await reader(world, a, "own", phone="edit", budget="edit")
    other = await reader(world, a, "workspace", phone="edit", budget="edit")
    mine = await lead_of(world, a, owner, budget="5000000")
    theirs = await lead_of(world, a, other, budget="7000000")
    run = await start(world, a, owner.id, fields=(*LEAD_FIELDS, "budget"))

    page = await run.call("search", {"limit": 50})

    assert list(page) == ["next_cursor", "items"]
    assert [item["id"] for item in page["items"]] == [str(mine)]
    item = page["items"][0]
    assert "budget" not in item["fields"]
    assert "hidden_fields" not in item and "permissions" not in item
    assert set(item["fields"]) <= {"phone", "status", "note"}
    assert str(theirs) not in str(page)
    record = await run.call("get", {"id": str(mine)})
    assert record["id"] == str(mine)
    assert "budget" not in record["fields"]
    assert await statuses(world, run) == ["succeeded", "succeeded"]


async def test_r6_1_a_filter_on_a_field_with_no_slot_never_reaches_the_handler(
    world: World,
) -> None:
    """R6.1, R6.6: `note` has no slot, eleven leaves, `limit` 51: each is
    `validation_failed` at the executor, the port is never asked."""
    owner = await reader(world, world.a, "own", phone="read")
    run = await start(world, world.a, owner.id)
    leaf = {"field": "status", "op": "$eq", "value": "moi"}
    refused: list[dict[str, object]] = [
        {"filters": [{"field": "note", "op": "$eq", "value": "x"}]},
        {"filters": [leaf] * 11},
        {"limit": 51},
    ]
    for raw in refused:
        with pytest.raises(DomainError) as caught:
            await run.call("search", raw)
        assert caught.value.code == "validation_failed"
    assert run.data.calls == 0


async def test_r6_2_a_reach_narrowed_between_two_calls_hides_the_record_from_the_next(
    world: World,
) -> None:
    """R6.2: asked again at every call. A workspace reader's agent reads a
    colleague's lead; the reader's read drops to "Của tôi" between two calls
    of the same run; the second call finds nothing (`not_found`)."""
    a = world.a
    colleague = await reader(world, a, "workspace", phone="edit")
    person = await reader(world, a, "workspace", phone="read")
    lead = await lead_of(world, a, colleague)
    run = await start(world, a, person.id)

    first = await run.call("get", {"id": str(lead)})
    assert first["id"] == str(lead)

    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.tenant_role_object_privileges SET depth = 'own'"
                " WHERE tenant_id = :t AND object_id = :o AND action = 'read' AND role_id IN"
                " (SELECT ra.role_id FROM platform.role_assignments ra"
                "  JOIN platform.memberships m ON m.id = ra.membership_id"
                "  WHERE m.user_id = :u AND m.tenant_id = :t)"
            ),
            {"t": a.tenant.tenant_id, "o": a.lead, "u": person.id},
        )
    with pytest.raises(NotFoundError):
        await run.call("get", {"id": str(lead)})


# ---------------------------------------------------------------- R6.3 (TS8) --


async def test_r6_3_ts8_a_hidden_phone_is_absent_and_a_filter_on_it_is_refused(
    world: World,
) -> None:
    """R6.3 (TS8): a reader without `phone` gets records without it and
    without `hidden_fields`; the fields it is narrowed to lack it; a filter
    on it reaches RecordService and is `field_not_readable`, no row."""
    a = world.a
    writer = await reader(world, a, "workspace", phone="edit")
    blind = await reader(world, a, "workspace", creates=False)
    number = phone()
    await lead_of(world, a, writer, phone=number)
    run = await start(world, a, blind.id)

    page = await run.call("search", {"limit": 50})
    assert page["items"]
    assert all("phone" not in item["fields"] for item in page["items"])
    assert number not in str(page)
    assert "hidden_fields" not in str(page)
    assert "phone" not in await run.readable()

    with pytest.raises(DomainError) as caught:
        await run.call("search", {"filters": [{"field": "phone", "op": "$eq", "value": number}]})
    assert caught.value.details["reason_codes"] == ["field_not_readable"]
    assert number not in str(caught.value.details) + caught.value.message


# ---------------------------------------------------------------- R6.4 (TS9) --


async def test_r6_4_ts9_another_companys_lead_is_not_found_like_no_lead(world: World) -> None:
    """R6.4 (TS9): company B's agent asks `obj_mkt_lead__get` for company A's
    lead: `not_found`, the same body as a random id, nothing of it shown."""
    a, b = world.a, world.b
    writer = await reader(world, a, "workspace", phone="edit")
    secret = await lead_of(world, a, writer)
    async with world.migrator.begin() as conn:
        b_reader = await holder(
            conn, b.tenant, b.lead, {"read": "tenant"}, dict.fromkeys(LEAD_FIELDS, "read")
        )
    b_pinned = await version_row(world.migrator, b.lead, 1)
    run = await start(world, b, b_reader.id, pinned=b_pinned)

    answers = []
    for record in (secret, uuid.uuid4()):
        with pytest.raises(NotFoundError) as caught:
            await run.call("get", {"id": str(record)})
        answers.append((caught.value.code, caught.value.message, caught.value.details))

    assert answers[0] == answers[1]
    assert str(secret) not in str(answers)


async def test_r6_4_another_companys_object_builds_no_tool(world: World) -> None:
    """A toolset entry naming company A's object in company B's run: the
    generator loaded under B holds no such object and refuses the set."""
    async with world.migrator.begin() as conn:
        b_reader = await holder(conn, world.b.tenant, world.b.lead, READ_ALL)
    with pytest.raises(Exception) as caught:
        await start(world, world.b, b_reader.id, object_id=world.a.lead)
    assert getattr(caught.value, "details", {}).get("reason") == "object_unavailable"


# ------------------------------------------------------------------- R6.6 --


async def test_r6_6_a_simulated_run_reads_real_records_and_writes_no_simulated_row(
    world: World,
) -> None:
    """R6.6: `simulate_safe`, so a `simulate` run's `get` reads the record
    the tester reads, recorded `succeeded`, never `simulated`."""
    tester = await reader(world, world.a, "own", phone="edit")
    lead = await lead_of(world, world.a, tester)
    run = await start(world, world.a, tester.id, mode="simulate")

    record = await run.call("get", {"id": str(lead)})

    assert record["id"] == str(lead)
    assert "simulated" not in await statuses(world, run)
    assert await statuses(world, run) == ["succeeded"]


# ------------------------------------------------------------- R6.5, R6.7 --


async def test_r6_5_r6_7_a_soft_deleted_field_leaves_the_view_and_a_call_naming_it_is_refused(
    world: World,
) -> None:
    """R6.5 (TS9): `legacy_code` leaves the object's live definition after the
    pin (custom-objects W2's soft delete; here its row is removed as the
    migrator): the tools built for the next run do not show it. R6.7: a call
    that still names it reaches RecordService and is refused, no row."""
    async with world.migrator.begin() as conn:
        person = await holder(
            conn,
            world.a.tenant,
            world.event,
            READ_ALL,
            {"name": "read", "kind": "read", "legacy_code": "read"},
        )
    pinned = await version_row(world.migrator, world.event, 1)
    before = await start(
        world,
        world.a,
        person.id,
        object_id=world.event,
        pinned=pinned,
        fields=("name", "kind"),
        api_name=EVENT,
    )
    assert "legacy_code" in str(before.tools["search"].behaviour.args_schema)
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM studio.field_defs WHERE object_id = :o AND api_name = :n"),
            {"o": world.event, "n": "legacy_code"},
        )

    run = await start(
        world,
        world.a,
        person.id,
        object_id=world.event,
        pinned=pinned,
        fields=("name", "kind"),
        api_name=EVENT,
    )

    search = run.tools["search"]
    assert "legacy_code" not in str(search.behaviour.args_schema)
    assert "legacy_code" in str(search.behaviour.input_schema())
    with pytest.raises(DomainError) as caught:
        await run.call(
            "search", {"filters": [{"field": "legacy_code", "op": "$eq", "value": "X-1"}]}
        )
    assert caught.value.details["reason_codes"] == ["field_not_readable"]
    assert await statuses(world, run) == ["failed"]
