"""Integration: a Digital Worker's work runs on its pinned workflow, on real
PostgreSQL as `dw_app`, with a fake model and counting tools (wf-lite ticket 02).

The lanes are the worker's own (`dw_work`, `dw_timers`), the runner, checkpointer,
executor, decision gate and work queue the real ones, assembled by the one
builder both processes use (`dw_agent_runtime.adapters.wflite_host`). The
document is the test pack `sample@1.0.0`: draft, approve and send, wait,
route, note.

R5.1, R5.2 (WFL9), R5.3 (WFL10), R6.1, R6.2 (WFL11), R6.3 (WFL12), R6.4,
R6.5 and R6.12 (WFL14), R6.6, R6.7, R6.8 (WFL16), R6.9 (WFL17), R6.10
(WFL18), R6.13 (the reader), R6.14, R6.15 and R6.16 (WFL22), R6.17 (WFL13),
R6.18 (WFL23, WFL26), R6.19 (WFL21), R6.20 (WFL25).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import astuple, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore, resume_context
from dw_agent_runtime.adapters.wflite_host import (
    RunTrailReader,
    build_run_starter,
    build_tool_executor,
    build_wflite_ports,
    load_handoff_copy,
    register_workflows,
)
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import DecisionCall, ToolExecutor
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_agent_runtime.wflite.catalog import PackCatalog
from dw_agent_runtime.wflite.waits import WorkQueueRunWaits
from dw_kernel.errors import ConflictError, PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.decision_gate import (
    DW_DECISION,
    DwDecisionAdmission,
    check_edited_proposal,
)
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.work_queue import WorkQueue, WorkScope
from dw_worker.consumers.dw_timers import build_dw_timers_consumer
from dw_worker.consumers.dw_work import build_dw_work_consumer

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PACKS = ROOT / "packages" / "python" / "dw_agent_runtime" / "tests" / "fixtures" / "packs"
HANDOFF_COPY = ROOT / "configs" / "copy" / "wflite_handoff.yaml"
LEAD = {"email": "an@khach.vn", "name": "Anh An"}
DRAFT = {
    "to": "an@khach.vn",
    "subject": "Chào anh An",
    "body": "Cảm ơn anh đã quan tâm.",
    "confidence": 0.9,
}
# The document's own classes; a DW carries them at these levels unless a test
# says otherwise. A2 on an external, irreversible class asks a person (R6.3).
CLASSES: dict[str, dict[str, Any]] = {
    "email.first_touch": {
        "effect_level": "external",
        "reversible": False,
        "ceiling": "A3",
        "earned_level": "A2",
    },
    "lead.note": {
        "effect_level": "internal",
        "reversible": True,
        "ceiling": "A4",
        "earned_level": "A4",
    },
}


class SpecTools:
    """The validator's view of the two tools: their effect only."""

    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> Any:
        return SimpleNamespace(side_effect_level="external" if name == "email.send" else "internal")


def load_catalog(root: Path = PACKS) -> PackCatalog:
    return PackCatalog.load(root, SpecTools())


class EmailInput(BaseModel):
    to: str
    subject: str
    body: str


class NoteInput(BaseModel):
    text: str


class Sent(BaseModel):
    ok: bool = True


@dataclass
class Gateway:
    """The model: answers every structured call with `answer`."""

    answer: dict[str, Any] = field(default_factory=lambda: dict(DRAFT))
    requests: list[Any] = field(default_factory=list)
    # The process's ledger, which the real gateway records each call's spend in.
    ledger: RunBudgetLedger | None = None

    async def generate_structured(self, request: Any, output_type: Any, *, run_context: Any) -> Any:
        self.requests.append(request)
        if self.ledger is not None:
            self.ledger.record(run_context.run_id, input_tokens=10, output_tokens=5, cost_usd=0.001)
        return output_type.model_validate(self.answer)


@dataclass
class Effects:
    sent: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    # Set to make the next email.send raise (WFL23).
    send_raises: Exception | None = None


def _definition(name: str, level: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0.0",
        description=name,
        input_schema_ref=f"contracts/tools/{name}/input.json",
        output_schema_ref=f"contracts/tools/{name}/output.json",
        required_scopes=frozenset(),
        side_effect_level=level,  # type: ignore[arg-type]
        approval_policy="conditional",
        timeout_seconds=10,
        max_retries=0,
        idempotent=True,
        data_classification=frozenset({"internal"}),
    )


def tool_registry(effects: Effects) -> ToolRegistry:
    async def send(payload: BaseModel, run_context: RunContext) -> Sent:
        if effects.send_raises is not None:
            raise effects.send_raises
        effects.sent.append(payload.model_dump())
        return Sent()

    async def note(payload: BaseModel, run_context: RunContext) -> Sent:
        effects.notes.append(payload.model_dump())
        return Sent()

    tools = ToolRegistry()
    tools.register(RegisteredTool(_definition("email.send", "external"), EmailInput, Sent, send))
    tools.register(RegisteredTool(_definition("lead.note", "internal"), NoteInput, Sent, note))
    return tools


@dataclass
class Stack:
    """One process hosting the wf-lite graphs: what `build_wflite_runtime`
    builds, with the model and tools replaced."""

    runner: LangGraphWorkflowRunner
    queue: WorkQueue
    flow: ApproveAndResumeService
    executor: ToolExecutor
    run_store: SqlWorkerRunStore
    trails: RunTrailReader
    starter: Any

    async def work(self) -> None:
        await build_dw_work_consumer(self.queue, self.starter)()

    async def timers(self) -> None:
        await build_dw_timers_consumer(self.queue, self.run_store, self.runner, SystemClock())()


def build(
    app: AsyncEngine,
    *,
    gateway: Gateway,
    effects: Effects,
    catalog: PackCatalog | None = None,
    node_clock: Any = None,
) -> Stack:
    catalog = catalog or load_catalog()
    sessions = async_sessionmaker(app, expire_on_commit=False)
    clock = SystemClock()
    ids = Uuid4Generator()
    uow = SqlPlatformUnitOfWorkFactory(sessions)
    tools = tool_registry(effects)
    policy = AutonomyApprovalPolicy()
    executor = build_tool_executor(
        tools=tools,
        session_factory=sessions,
        uow_factory=uow,
        approval_policy=policy,
        telemetry=_null_telemetry(),
        clock=clock,
        ids=ids,
    )
    queue = WorkQueue(
        repo=SqlWorkQueueRepository(sessions),
        workers=SqlDigitalWorkerRepository(sessions),
        people=SqlDwMembershipCheck(sessions),
        schemas=catalog,
        authz=ScopeAuthorizationService(),
        clock=clock,
        id_generator=ids,
    )
    graphs = GraphRegistry()
    workers = WorkerRegistry(graph_registry=graphs)
    budget = RunBudgetLedger()
    gateway.ledger = budget
    run_store = SqlWorkerRunStore(sessions, stale_run_after_seconds=3600)
    checkpoints = SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer())
    runner = LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=checkpoints,
        run_store=run_store,
        uow_factory=uow,
        clock=clock,
        id_generator=ids,
        allowance=PlanEntitlementService(DEFAULT_PLANS),
        budget=budget,
        approval_policy=policy,
        run_waits=WorkQueueRunWaits(queue),
    )
    register_workflows(
        catalog,
        build_wflite_ports(
            session_factory=sessions,
            gateway=gateway,
            executor=executor,
            tools=tools,
            queue=queue,
            recommendations=load_handoff_copy(HANDOFF_COPY),
            clock=node_clock or clock,
            ids=ids,
        ),
        graphs=graphs,
        workers=workers,
    )
    flow = ApproveAndResumeService(
        uow_factory=uow,
        runner=runner,
        run_store=run_store,
        clock=clock,
        id_generator=ids,
        type_admissions={DW_DECISION: DwDecisionAdmission()},
        proposal_editors={DW_DECISION: check_edited_proposal},
    )
    return Stack(
        runner=runner,
        queue=queue,
        flow=flow,
        executor=executor,
        run_store=run_store,
        trails=RunTrailReader(run_store=run_store, checkpoints=checkpoints),
        starter=build_run_starter(
            catalog=catalog, session_factory=sessions, tools=tools, runner=runner
        ),
    )


def _null_telemetry() -> Any:
    from dw_observability.telemetry import NullTelemetry

    return NullTelemetry()


# ------------------------------------------------------------------ seed --


@dataclass
class World:
    tenant: uuid.UUID
    workspace: uuid.UUID
    dw: uuid.UUID
    principal: uuid.UUID
    owner: uuid.UUID
    validator: uuid.UUID
    item: uuid.UUID


@pytest.fixture
async def engines(worker_db: DatabaseUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(worker_db.migrator, poolclass=NullPool)
    app = create_async_engine(worker_db.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


async def seed(
    migrator: AsyncEngine,
    *,
    classes: dict[str, dict[str, Any]] | None = None,
    parameters: dict[str, Any] | None = None,
    state: str = "operating",
) -> World:
    t, w, owner, validator, principal, dw, item = (uuid.uuid4() for _ in range(7))
    classes = CLASSES if classes is None else classes
    async with migrator.begin() as conn:

        async def run(sql: str, **values: Any) -> None:
            await conn.execute(sa.text(sql), values)

        await run(
            "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)",
            t=t,
            s=f"wfl-{t.hex[:12]}",
        )
        await run(
            "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
            " VALUES (:i, :t, 'professional')",
            i=uuid.uuid4(),
            t=t,
        )
        await run(
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
            " VALUES (:w, :t, 'main', 'main')",
            w=w,
            t=t,
        )
        for user in (owner, validator):
            await run(
                "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'p')",
                u=user,
                s=f"wfl-{user}",
            )
            await run(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                " role_keys) VALUES (:i, :t, :w, :u, '[\"approver\"]'::jsonb)",
                i=uuid.uuid4(),
                t=t,
                w=w,
                u=user,
            )
        await run(
            "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
            " VALUES (:u, :s, 'dw', 'service', :t)",
            u=principal,
            s=f"service:{principal}",
            t=t,
        )
        await run(
            "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
            " name, owner_user_id) VALUES (:u, :t, :w, 'dw', :o)",
            u=principal,
            t=t,
            w=w,
            o=owner,
        )
        await run(
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
            " role_keys) VALUES (:i, :t, :w, :u, '[\"member\"]'::jsonb)",
            i=uuid.uuid4(),
            t=t,
            w=w,
            u=principal,
        )
        await run(
            "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
            " principal_user_id, key, name, mandate, work_kinds, allowed_tools, workflow_key,"
            " workflow_version, parameters, state, technical_owner_id, work_assigner_id,"
            " validator_id, created_by) VALUES (:d, :t, :w, :u, :k, 'dw', 'dw',"
            " ARRAY['lead.new'], ARRAY['email.send', 'lead.note'], 'sample', '1.0.0',"
            " CAST(:p AS jsonb), :st, :o, :o, :v, :o)",
            d=dw,
            t=t,
            w=w,
            u=principal,
            k=f"wfl_{dw.hex[:12]}",
            p=json.dumps(parameters or {}),
            st=state,
            o=owner,
            v=validator,
        )
        for key, c in classes.items():
            await run(
                "INSERT INTO platform.dw_decision_classes (dw_id, key, tenant_id, workspace_id,"
                " effect_level, reversible, ceiling, earned_level)"
                " VALUES (:d, :k, :t, :w, :e, :r, :c, :earned)",
                d=dw,
                k=key,
                t=t,
                w=w,
                e=c["effect_level"],
                r=c["reversible"],
                c=c["ceiling"],
                earned=c["earned_level"],
            )
        await run(
            "INSERT INTO platform.work_items (id, tenant_id, workspace_id, dw_id, kind,"
            " source_key, payload, payload_hash, holder_kind, holder_id)"
            " VALUES (:i, :t, :w, :d, 'lead.new', :k, CAST(:p AS jsonb), repeat('a', 64),"
            " 'digital_worker', :d)",
            i=item,
            t=t,
            w=w,
            d=dw,
            k=f"k-{item}",
            p=json.dumps(LEAD),
        )
    return World(t, w, dw, principal, owner, validator, item)


# ----------------------------------------------------------------- reads --


async def item_row(migrator: AsyncEngine, world: World) -> Any:
    async with migrator.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT status, run_id, wake_at, closed_at, error, handoff, holder_kind,"
                    " holder_id, wake_at > now() + interval '14 minutes' AS leased"
                    " FROM platform.work_items WHERE id = :i"
                ),
                {"i": world.item},
            )
        ).one()


async def run_row(migrator: AsyncEngine, run_id: uuid.UUID) -> Any:
    async with migrator.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT status, definition_hash, approval_request_id, result"
                    " FROM platform.worker_runs WHERE id = :r"
                ),
                {"r": run_id},
            )
        ).one()


async def approvals_of(migrator: AsyncEngine, run_id: uuid.UUID) -> list[Any]:
    async with migrator.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT id, approval_type, payload FROM platform.approval_requests"
                        " WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            ).all()
        )


async def executions(migrator: AsyncEngine, run_id: uuid.UUID, tool: str) -> list[str]:
    async with migrator.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT status FROM platform.tool_executions"
                        " WHERE run_id = :r AND tool_name = :n AND status <> 'dispatched'"
                        " ORDER BY started_at"
                    ),
                    {"r": run_id, "n": tool},
                )
            ).scalars()
        )


async def make_due(migrator: AsyncEngine, world: World) -> None:
    """The timer's minute, passed without waiting for it."""
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.work_items SET wake_at = now() - interval '1 second' WHERE id = :i"
            ),
            {"i": world.item},
        )


def as_validator(world: World) -> AccessContext:
    return AccessContext(
        tenant_id=world.tenant,
        workspace_id=world.workspace,
        principal_id=world.validator,
        roles=frozenset({"approver"}),
        scopes=frozenset({"approvals.read", "approvals.decide"}),
        plan_id="professional",
    )


async def decide(stack: Stack, world: World, approval: uuid.UUID, **kw: Any) -> None:
    await stack.flow.decide(
        approval_id=approval,
        approve=kw.pop("approve", True),
        comment=kw.pop("comment", "ok"),
        context=as_validator(world),
        authorization=ScopeAuthorizationService(),
        **kw,
    )


async def trail_of(stack: Stack, world: World, run_id: uuid.UUID) -> list[dict[str, str]]:
    return await stack.trails.trail(
        tenant_id=world.tenant, workspace_id=world.workspace, run_id=run_id
    )


def steps(trail: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(e["step_id"], e["status"]) for e in trail]


async def paused_on_approval(
    migrator: AsyncEngine, stack: Stack, world: World
) -> tuple[uuid.UUID, uuid.UUID]:
    """Take the item, run to the approval; the run and its approval."""
    await stack.work()
    item = await item_row(migrator, world)
    assert item.status == "waiting_approval", item
    [approval] = await approvals_of(migrator, item.run_id)
    return item.run_id, approval.id


# ----------------------------------------------------------------- tests --


async def test_a_run_waits_for_approval_sends_once_waits_and_finishes(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R5.1, R6.1, R6.3 (WFL12 approved), R6.4, R6.5 (WFL14), R6.6, R6.7,
    R6.14, R6.21: the whole run, one approval, one send."""
    migrator, app = engines
    world = await seed(migrator)
    gateway, effects = Gateway(), Effects()
    stack = build(app, gateway=gateway, effects=effects)
    catalog = load_catalog()
    pinned = catalog.workflow("sample", "1.0.0")
    assert pinned is not None
    assert stack.runner.hosts(worker_id="dw:sample", worker_version="1.0.0", graph_version="1.0.0")

    run_id, approval = await paused_on_approval(migrator, stack, world)
    # R5.1: the prompt by id@version, its variables from the work item.
    [request] = gateway.requests
    assert (request.prompt_id, request.prompt_version) == ("sample.first_touch", "1.0.0")
    assert request.variables == {"name": "Anh An", "email": "an@khach.vn"}
    run = await run_row(migrator, run_id)
    assert run.status == "waiting_approval"
    assert run.definition_hash == pinned.sha256  # R6.14
    [row] = await approvals_of(migrator, run_id)
    assert row.approval_type == DW_DECISION
    assert row.payload["step_id"] == "approve_send"
    # R6.21: the proposal's schema is email.send's input schema.
    assert row.payload["proposal_schema"] == EmailInput.model_json_schema()
    assert effects.sent == []
    # The draft's spend is on this process's ledger until the pause, and freed
    # at it: the decision may resume the run in another process.
    assert run_id not in stack.runner.budget.spend

    await decide(stack, world, approval)
    assert effects.sent == [{k: DRAFT[k] for k in ("to", "subject", "body")}]
    # R6.5: a timer opens no approval; the item waits with its wake time.
    assert len(await approvals_of(migrator, run_id)) == 1
    item = await item_row(migrator, world)
    assert (item.status, (await run_row(migrator, run_id)).status) == (
        "waiting_timer",
        "waiting_timer",
    )
    assert item.wake_at is not None and not item.leased

    # R6.13: the trail of a waiting run, read from its checkpoint.
    assert steps(await trail_of(stack, world, run_id)) == [
        ("draft", "done"),
        ("approve_send", "done"),
        ("send", "done"),
    ]

    await make_due(migrator, world)
    await stack.timers()
    item = await item_row(migrator, world)
    assert item.status == "done" and item.closed_at is not None  # R6.7
    assert effects.notes == [{"text": DRAFT["subject"]}]
    assert len(effects.sent) == 1
    trail = await trail_of(stack, world, run_id)
    assert steps(trail) == [
        ("draft", "done"),
        ("approve_send", "done"),
        ("send", "done"),
        ("wait_reply", "done"),
        ("route", "done"),
        ("note_sent", "done"),
    ]
    # R6.6: ids and states only; nothing of what the model wrote.
    assert all(set(entry) == {"step_id", "type", "status", "at"} for entry in trail)
    flat = json.dumps(trail, ensure_ascii=False)
    for value in (*DRAFT.values(), *LEAD.values()):
        if isinstance(value, str):
            assert value not in flat
    # R6.4: the send's key is the step's.
    async with migrator.connect() as conn:
        key = (
            await conn.execute(
                sa.text(
                    "SELECT idempotency_key FROM platform.tool_executions"
                    " WHERE run_id = :r AND tool_name = 'email.send' AND status = 'succeeded'"
                ),
                {"r": run_id},
            )
        ).scalar_one()
    assert key.startswith(f"wf:{run_id}:send:")


async def test_a_rejection_takes_the_rejected_lane(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.3 (WFL12 rejected): no send, the rejection's comment noted."""
    migrator, app = engines
    world = await seed(migrator)
    effects = Effects()
    stack = build(app, gateway=Gateway(), effects=effects)
    run_id, approval = await paused_on_approval(migrator, stack, world)
    await decide(stack, world, approval, approve=False, comment="chưa gửi")
    assert effects.sent == []
    assert effects.notes == [{"text": "chưa gửi"}]
    assert ("note_rejected", "done") in steps(await trail_of(stack, world, run_id))


async def test_an_edited_proposal_is_what_is_sent(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.10 (WFL18)."""
    migrator, app = engines
    world = await seed(migrator)
    effects = Effects()
    stack = build(app, gateway=Gateway(), effects=effects)
    _, approval = await paused_on_approval(migrator, stack, world)
    edited = {"to": DRAFT["to"], "subject": "Tiêu đề đã sửa", "body": DRAFT["body"]}
    await decide(stack, world, approval, edited_proposal=edited)
    assert effects.sent == [edited]


async def test_the_tool_door_takes_only_this_runs_approved_content(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.17 (WFL13) on the real door: no approval, another run's approval, or
    other content is refused before the tool; the approved content runs once."""
    migrator, app = engines
    world = await seed(migrator)
    effects = Effects()
    stack = build(app, gateway=Gateway(), effects=effects)
    run_id, approval = await paused_on_approval(migrator, stack, world)
    await decide(stack, world, approval)
    assert len(effects.sent) == 1
    record = await stack.run_store.get_in(
        tenant_id=world.tenant, workspace_id=world.workspace, run_id=run_id
    )
    context = resume_context(record, tenant_id=world.tenant, channel="test")
    approved = {k: DRAFT[k] for k in ("to", "subject", "body")}

    async def call(
        content: dict[str, Any], approval_id: uuid.UUID | None, ctx: RunContext, key: str
    ) -> str:
        try:
            await stack.executor.execute(
                name="email.send",
                version="1.0.0",
                raw_input=content,
                run_context=ctx,
                idempotency_key=key,
                decision=DecisionCall("email.first_touch", "approve_send", approval_id),
            )
        except PermissionDeniedError as refused:
            return str(refused.details["reason_code"])
        return "ran"

    assert await call(approved, None, context, "k1") == "approval_missing"
    other_run = context.model_copy(update={"run_id": uuid.uuid4()})
    assert await call(approved, approval, other_run, "k2") == "approval_missing"
    changed = {**approved, "subject": "khác"}
    assert await call(changed, approval, context, "k3") == "subject_changed"
    assert len(effects.sent) == 1
    assert await call(approved, approval, context, "k4") == "ran"
    assert len(effects.sent) == 2


async def test_a_dw_without_the_documents_classes_or_parameters_fails_the_item(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.2 (WFL11), R6.9 (WFL17): refused before anything runs."""
    migrator, app = engines
    first_touch = CLASSES["email.first_touch"]
    cases: list[tuple[dict[str, Any], dict[str, Any], str]] = [
        ({"lead.note": CLASSES["lead.note"]}, {}, "decision_class_missing"),
        (CLASSES, {"reply_wait_seconds": "a minute"}, "parameter_invalid"),
        (
            {**CLASSES, "email.first_touch": {**first_touch, "effect_level": "none"}},
            {},
            "decision_class_mismatch",
        ),
        (
            {**CLASSES, "email.first_touch": {**first_touch, "reversible": True}},
            {},
            "decision_class_mismatch",
        ),
    ]
    for classes, parameters, code in cases:
        world = await seed(migrator, classes=classes, parameters=parameters)
        gateway, effects = Gateway(), Effects()
        await build(app, gateway=gateway, effects=effects).work()
        item = await item_row(migrator, world)
        assert (item.status, item.error) == ("failed", code)
        async with migrator.connect() as conn:
            runs = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM platform.worker_runs WHERE id = :r"),
                    {"r": item.run_id},
                )
            ).scalar_one()
        assert runs == 0 and gateway.requests == [] and effects.sent == []


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        ({"to": "an@khach.vn", "subject": "x", "confidence": 0.9}, "model_output_invalid"),
        ({**DRAFT, "confidence": 0.4}, "low_confidence"),
    ],
)
async def test_a_model_answer_that_cannot_go_on_hands_off_to_the_validator(
    engines: tuple[AsyncEngine, AsyncEngine], answer: dict[str, Any], code: str
) -> None:
    """R5.2 (WFL9), R5.3 (WFL10), R6.20 (WFL25)."""
    migrator, app = engines
    world = await seed(migrator)
    effects = Effects()
    stack = build(app, gateway=Gateway(answer=answer), effects=effects)
    await stack.work()
    item = await item_row(migrator, world)
    assert item.status == "handed_off"
    assert (item.holder_kind, item.holder_id) == ("person", world.validator)
    packet = item.handoff
    assert packet["problem"] == f"{code} at draft"
    assert all(str(packet[f]).strip() for f in ("problem", "context", "tried", "recommendation"))
    assert packet["recommendation"] == load_handoff_copy(HANDOFF_COPY)[code]
    assert effects.sent == [] and await approvals_of(migrator, item.run_id) == []
    assert steps(await trail_of(stack, world, item.run_id)) == [("draft", "handed_off")]


async def test_a_step_that_fails_hands_off_with_its_code(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.18 (WFL23, WFL26): the approval node waits like any other; the send
    that raises is a `failed` entry and a hand-off, and nothing after it runs."""
    migrator, app = engines
    world = await seed(migrator)
    effects = Effects(send_raises=RuntimeError("smtp down"))
    stack = build(app, gateway=Gateway(), effects=effects)
    run_id, approval = await paused_on_approval(migrator, stack, world)  # WFL26
    await decide(stack, world, approval)
    item = await item_row(migrator, world)
    assert item.status == "handed_off"
    assert item.handoff["problem"].endswith("at send")
    assert all(str(item.handoff[f]).strip() for f in ("context", "tried", "recommendation"))
    assert steps(await trail_of(stack, world, run_id))[-1] == ("send", "failed")
    assert effects.notes == []


async def test_a_changed_document_hands_off_instead_of_resuming(
    engines: tuple[AsyncEngine, AsyncEngine], tmp_path: Path
) -> None:
    """R6.19 (WFL21): the file changes, keeping key@version, while the run
    waits for approval; the decision resumes it on the new bytes and nothing
    runs."""
    migrator, app = engines
    world = await seed(migrator)
    shutil.copytree(PACKS, tmp_path / "packs")
    effects = Effects()
    packs = tmp_path / "packs"
    before = build(app, gateway=Gateway(), effects=effects, catalog=load_catalog(packs))
    _, approval = await paused_on_approval(migrator, before, world)
    path = tmp_path / "packs" / "sample" / "workflows" / "sample@1.0.0.yaml"
    path.write_bytes(path.read_bytes() + b"\n# edited while a run waited\n")
    # The process that decides loaded the edited file.
    after = build(app, gateway=Gateway(), effects=effects, catalog=load_catalog(tmp_path / "packs"))
    await decide(after, world, approval)
    item = await item_row(migrator, world)
    assert item.status == "handed_off"
    assert item.handoff["problem"].startswith("definition_changed")
    assert effects.sent == []


async def test_a_paused_dw_neither_wakes_nor_sends(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.15, R6.16 (WFL22)."""
    migrator, app = engines
    effects = Effects()
    stack = build(app, gateway=Gateway(), effects=effects)

    # A decision on a paused DW: refused at the tool door, handed off.
    world = await seed(migrator)
    run_id, approval = await paused_on_approval(migrator, stack, world)
    await set_state(migrator, world, "paused")
    await decide(stack, world, approval)
    item = await item_row(migrator, world)
    assert item.status == "handed_off" and item.holder_id == world.validator
    assert item.handoff["problem"] == "dw_not_operating at send"
    assert effects.sent == []

    # A due timer of a paused DW: not taken, the item as it was.
    world = await seed(migrator)
    run_id, approval = await paused_on_approval(migrator, stack, world)
    await decide(stack, world, approval)
    await set_state(migrator, world, "paused")
    await make_due(migrator, world)
    before = await item_row(migrator, world)
    await stack.timers()
    after = await item_row(migrator, world)
    assert (after.status, after.wake_at) == ("waiting_timer", before.wake_at)
    assert (await run_row(migrator, run_id)).status == "waiting_timer"


async def set_state(migrator: AsyncEngine, world: World, state: str) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.digital_workers SET state = :s WHERE id = :d"),
            {"s": state, "d": world.dw},
        )


async def to_the_timer(migrator: AsyncEngine, stack: Stack) -> tuple[World, uuid.UUID]:
    world = await seed(migrator)
    run_id, approval = await paused_on_approval(migrator, stack, world)
    await decide(stack, world, approval)
    assert (await item_row(migrator, world)).status == "waiting_timer"
    return world, run_id


async def test_two_timer_lanes_resume_a_due_run_once_and_leave_the_rest(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.12 (WFL14): two lanes at once, one resume; a timer not due yet is
    not resumed."""
    migrator, app = engines
    effects = Effects()
    stack = build(app, gateway=Gateway(), effects=effects)
    due, due_run = await to_the_timer(migrator, stack)
    waiting, waiting_run = await to_the_timer(migrator, stack)
    await make_due(migrator, due)
    other = build(app, gateway=Gateway(), effects=effects)
    await asyncio.gather(stack.timers(), other.timers())
    assert (await item_row(migrator, due)).status == "done"
    assert await executions(migrator, due_run, "lead.note") == ["succeeded"]
    assert (await item_row(migrator, waiting)).status == "waiting_timer"
    assert (await run_row(migrator, waiting_run)).status == "waiting_timer"


async def test_a_lane_that_dies_after_its_claim_leaves_the_timer_due_after_the_lease(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.12 (WFL14): the claim leases the item for 15 minutes; once the lease
    has run out (aged here, not waited for), the next pass resumes it."""
    migrator, app = engines
    stack = build(app, gateway=Gateway(), effects=Effects())
    world, run_id = await to_the_timer(migrator, stack)
    await make_due(migrator, world)
    scope = WorkScope(tenant_id=world.tenant, workspace_id=world.workspace)
    [claimed] = await stack.queue.claim_timers(scope, limit=5)  # and the lane dies here
    assert claimed.id == world.item
    assert (await item_row(migrator, world)).leased
    await stack.timers()
    assert (await item_row(migrator, world)).status == "waiting_timer"
    await make_due(migrator, world)
    await stack.timers()
    assert (await item_row(migrator, world)).status == "done"
    # A lane that lost its answer and resumes the run again is refused by the
    # runner, which the lane takes as a no-op: nothing runs twice.
    record = await stack.run_store.get_in(
        tenant_id=world.tenant, workspace_id=world.workspace, run_id=run_id
    )
    with pytest.raises(ConflictError):
        await stack.runner.resume(
            run_context=resume_context(record, tenant_id=world.tenant, channel="test"),
            run_id=run_id,
            resume_payload={"woke_at": ""},
        )
    assert await executions(migrator, run_id, "lead.note") == ["succeeded"]


async def test_another_tenants_timer_lane_scope_sees_nothing_of_this_one(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """WFL14: the claim runs under its scope's RLS; another tenant's scope
    takes nothing of this tenant's due item, and the trail reader under
    another workspace reads nothing (R6.13)."""
    migrator, app = engines
    stack = build(app, gateway=Gateway(), effects=Effects())
    world, run_id = await to_the_timer(migrator, stack)
    stranger = await seed(migrator)
    await make_due(migrator, world)
    taken = await stack.queue.claim_timers(
        WorkScope(tenant_id=stranger.tenant, workspace_id=stranger.workspace), limit=50
    )
    assert world.item not in {i.id for i in taken}
    assert not (await item_row(migrator, world)).leased
    assert (
        await stack.trails.trail(
            tenant_id=stranger.tenant, workspace_id=stranger.workspace, run_id=run_id
        )
        == []
    )
    assert (
        await stack.trails.trail(tenant_id=world.tenant, workspace_id=uuid.uuid4(), run_id=run_id)
        == []
    )


class ExitingClock:
    """The nodes' clock in the dying process. Its second reading ends the
    process at once (`os._exit`: no `finally`, no flush of a pending write):
    the first reading is the send's trail entry, the second the timer node's,
    the step after the send."""

    def __init__(self, readings: int) -> None:
        self.readings = readings

    def now(self) -> Any:
        self.readings -= 1
        if self.readings == 0:
            os._exit(DIED)
        return SystemClock().now()


DIED = 17


async def _die_after_the_send(app_url: str, world: World, approval: uuid.UUID) -> None:
    """The child process: decides, sends, and dies before the next step."""
    app = create_async_engine(app_url, poolclass=NullPool)
    stack = build(app, gateway=Gateway(), effects=Effects(), node_clock=ExitingClock(2))
    await decide(stack, world, approval)


async def audits(migrator: AsyncEngine, run_id: uuid.UUID, action: str) -> int:
    async with migrator.connect() as conn:
        return int(
            (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM platform.audit_events"
                        " WHERE run_id = :r AND action = :a"
                    ),
                    {"r": run_id, "a": action},
                )
            ).scalar_one()
        )


async def test_a_run_that_died_after_its_send_does_not_send_again(
    engines: tuple[AsyncEngine, AsyncEngine], worker_db: DatabaseUrls
) -> None:
    """R6.8 (WFL16): a process dies between the send and the next step, and
    a new process carries the run on from its last checkpoint. The send's
    step is not run again, not even to be replayed by its key: its checkpoint
    was on disk before the next step began (durability="sync").

    The death is a real one, in a child process, because a failure raised
    inside the process lets LangGraph flush its pending checkpoint writes on
    the way out, and then a run without "sync" survives too (measured
    30/10/2026). No lane resumes a run that died while `running` (the stale
    run reaper fails it), so the test re-arms the run by hand to ask the one
    question R6.8 asks: does a resume from the last checkpoint repeat the
    send? It is re-armed as a due timer, the wait the step after the send
    reaches, and woken the way `dw_timers` wakes one; a resume value with no
    pause pending is taken by the next pause the run reaches (LangGraph,
    measured 30/10/2026)."""
    migrator, app = engines
    world = await seed(migrator)
    stack = build(app, gateway=Gateway(), effects=Effects())
    run_id, approval = await paused_on_approval(migrator, stack, world)
    child = "\n".join(
        (
            "import asyncio, sys, uuid",
            "import test_wflite_runs_db as t",
            "ids = [uuid.UUID(v) for v in sys.argv[2:]]",
            "asyncio.run(t._die_after_the_send(sys.argv[1], t.World(*ids[:7]), ids[7]))",
        )
    )
    args = [str(v) for v in (*astuple(world), approval)]
    result = subprocess.run(
        [sys.executable, "-c", child, worker_db.app, *args],
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(HERE), *sys.path])},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == DIED, result.stderr[-2000:]
    assert await executions(migrator, run_id, "email.send") == ["succeeded"]

    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.worker_runs SET status = 'waiting_timer' WHERE id = :r"),
            {"r": run_id},
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.work_items SET status = 'waiting_timer', wake_at = now()"
                " WHERE id = :i"
            ),
            {"i": world.item},
        )
    effects = Effects()
    fresh = build(app, gateway=Gateway(), effects=effects)
    record = await fresh.run_store.get_in(
        tenant_id=world.tenant, workspace_id=world.workspace, run_id=run_id
    )
    await fresh.runner.resume(
        run_context=resume_context(record, tenant_id=world.tenant, channel="test"),
        run_id=run_id,
        resume_payload={"woke_at": SystemClock().now().isoformat()},
    )
    assert effects.sent == []
    assert await audits(migrator, run_id, "tool.replayed") == 0
    assert await executions(migrator, run_id, "email.send") == ["succeeded"]
    assert (await item_row(migrator, world)).status == "done"
    assert effects.notes == [{"text": DRAFT["subject"]}]


async def test_each_layer_of_the_timer_lane_takes_only_due_timers_of_operating_dws(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R6.12, R6.15 (WFL14, WFL22), at each layer on its own: the scopes the
    cross-tenant function names, and the claim under one scope. The lane
    stops at the first layer, so a lane test cannot see the second."""
    migrator, app = engines
    stack = build(app, gateway=Gateway(), effects=Effects())
    world, _ = await to_the_timer(migrator, stack)
    scope = WorkScope(tenant_id=world.tenant, workspace_id=world.workspace)

    async def named() -> bool:
        return scope in await stack.queue.due_timer_scopes(limit=10_000)

    # Not due yet.
    assert not await named()
    assert await stack.queue.claim_timers(scope, limit=5) == []
    # Due, of a paused DW.
    await make_due(migrator, world)
    await set_state(migrator, world, "paused")
    assert not await named()
    assert await stack.queue.claim_timers(scope, limit=5) == []
    # Due, of an operating DW.
    await set_state(migrator, world, "operating")
    assert await named()
    assert [i.id for i in await stack.queue.claim_timers(scope, limit=5)] == [world.item]
