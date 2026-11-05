# ruff: noqa: F811  (the world of test_run_control_db is imported by name)
"""A kill against PostgreSQL (agent-lifecycle ticket 05: R8.1-R8.4, R8.6,
R8.9-R8.11; AL13, AL15, AL16, AL28, AL29).

The world, the runner and the approval flow are `test_run_control_db`'s: one
planted company, a person P who sets switches, a decider Q, and the doors
over a real `SqlRunControl`. A kill is written as the kill route writes it
(as `dw_app` under the company's RLS) and lifted only as the trigger allows:
an approved, second-person `studio.lifecycle.revive` request naming it.

A parked run of a component is a demo run paused for its review whose row is
then made a Studio row of a planted workflow (the columns workflow-engine/02
added), so the lane meets a real approval card and a real resume path. The
lane is the real `ControlSwitchLane` over `SqlKilledRuns`, called as the
outbox calls it with the event's `{tenant_id, switch_id}`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_run_control_db import (  # noqa: F401  (the fixture, used by name)
    QueuedRun,
    StudioRunsLane,
    World,
    world,
)

from dw_agent_runtime.adapters.killed_runs import SqlKilledRuns
from dw_agent_runtime.adapters.run_control import SqlRunControl
from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.tool_claims import SqlToolClaims
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.control_switch_lane import ControlSwitchLane, RunCancelHooks
from dw_agent_runtime.dispatch import OutcomeUnknownError
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.ports import RunCancelUnit
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.domain.audit import AuditEvent
from dw_platform.testing.rbac import plant_tenant

pytestmark = pytest.mark.integration

# One manifest per mode: `platform.match_run_manifest()` holds a row's mode to
# the one its manifest pinned.
MANIFESTS = {"live": "sha256:" + "d" * 64, "simulate": "sha256:" + "e" * 64}


# ---- the world's switches and components ------------------------------------------


async def kill(world: World, target: uuid.UUID, *, other: Any = None) -> uuid.UUID:
    """P's kill of `target`, as the route writes it: `dw_app`, the company's
    RLS; in the planted company `other` when given."""
    switch = uuid.uuid4()
    company = world.tenant.tenant_id if other is None else other.tenant_id
    workspace = world.tenant.main if other is None else other.main
    async with world.app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(company)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type,"
                " owning_workspace_id, target_id, action, origin, reason_code, reason, set_by)"
                " VALUES (:id, :t, 'workflow', :w, :target, 'kill', 'tenant', 'incident',"
                " 'gửi sai', :by)"
            ),
            {"id": switch, "t": company, "w": workspace, "target": target, "by": world.person},
        )
    return switch


async def revive(world: World, switch: uuid.UUID) -> None:
    """As `SwitchLiftSettler` does: an approved revive decided by Q."""
    approval = uuid.uuid4()
    tenant = world.tenant.tenant_id
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, payload, status)"
                " VALUES (:a, :t, :w, 'studio.lifecycle.revive', :r,"
                " jsonb_build_object('switch_id', CAST(:s AS text)), 'approved')"
            ),
            {
                "a": approval,
                "t": tenant,
                "w": world.tenant.main,
                "r": world.person,
                "s": str(switch),
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.approval_decisions (id, request_id, tenant_id,"
                " workspace_id, decided_by, outcome, decided_at)"
                " VALUES (gen_random_uuid(), :a, :t, :w, :d, 'approved', now())"
            ),
            {"a": approval, "t": tenant, "w": world.tenant.main, "d": world.decider},
        )
    async with world.app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        await conn.execute(
            sa.text(
                "UPDATE platform.control_switches SET lifted_at = now(), lifted_by = :d,"
                " lift_approval_id = :a WHERE id = :s"
            ),
            {"d": world.decider, "a": approval, "s": switch},
        )


async def freeze_by(world: World, setter: uuid.UUID) -> uuid.UUID:
    """The company's own freeze, set by `setter`."""
    switch = uuid.uuid4()
    tenant = world.tenant.tenant_id
    async with world.app.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.control_switches (id, tenant_id, scope_type, action,"
                " origin, reason_code, reason, set_by)"
                " VALUES (:id, :t, 'tenant', 'freeze', 'tenant', 'incident', 'sự cố', :by)"
            ),
            {"id": switch, "t": tenant, "by": setter},
        )
    return switch


async def workflow(world: World) -> tuple[uuid.UUID, uuid.UUID]:
    """A planted workflow, its draft and a manifest: what a Studio row names."""
    artifact, version = uuid.uuid4(), uuid.uuid4()
    tenant = world.tenant.tenant_id
    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name,"
                " owning_workspace_id, row_version) VALUES (:a, :t, 'workflow', :n, :w, 1)"
            ),
            {"a": artifact, "t": tenant, "n": f"qt_{artifact.hex[:12]}", "w": world.tenant.main},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
                " document_schema, document, row_version, contributor_ids)"
                " VALUES (:v, :t, :a, 'draft', 'dw.workflow/v1', '{}'::jsonb, 1,"
                " ARRAY[CAST(:p AS uuid)])"
            ),
            {"v": version, "t": tenant, "a": artifact, "p": world.person},
        )
        for mode, manifest in MANIFESTS.items():
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.run_manifests (tenant_id, hash, body)"
                    " VALUES (:t, :h, jsonb_build_object('run_mode', CAST(:m AS text)))"
                    " ON CONFLICT DO NOTHING"
                ),
                {"t": tenant, "h": manifest, "m": mode},
            )
    return artifact, version


async def studio_row(
    world: World,
    run_id: uuid.UUID,
    component: tuple[uuid.UUID, uuid.UUID],
    *,
    status: str | None = None,
    run_mode: str = "live",
) -> None:
    """The paused demo run, made a run of `component` in `status`."""
    artifact, version = component
    await world.sql(
        world.migrator,
        "UPDATE platform.worker_runs SET artifact_kind = 'workflow', artifact_id = :a,"
        " artifact_version_id = :v, trigger_kind = 'manual', run_manifest_hash = :h,"
        " run_as_principal_id = :p, request_key = :k, run_mode = :m,"
        " status = coalesce(CAST(:s AS text), status) WHERE id = :r",
        a=artifact,
        v=version,
        h=MANIFESTS[run_mode],
        p=world.person,
        k=f"k-{run_id.hex}",
        m=run_mode,
        s=status,
        r=run_id,
    )


def lane_of(world: World, hooks: RunCancelHooks | None = None) -> ControlSwitchLane:
    return ControlSwitchLane(
        store=SqlKilledRuns(world.sessions),
        hooks=(hooks or RunCancelHooks()).freeze(),
        clock=SystemClock(),
        ids=Uuid4Generator(),
    )


async def run_and_request(world: World, run_id: uuid.UUID) -> tuple[Any, list[Any]]:
    run = await world.sql(
        world.migrator, "SELECT status, error FROM platform.worker_runs WHERE id = :r", r=run_id
    )
    async with world.migrator.connect() as conn:
        requests = list(
            (
                await conn.execute(
                    sa.text("SELECT id, status FROM platform.approval_requests WHERE run_id = :r"),
                    {"r": run_id},
                )
            ).all()
        )
    return run, requests


async def audits(world: World, action: str, run_id: uuid.UUID) -> list[Any]:
    async with world.migrator.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT actor_id, resource_id, details FROM platform.audit_events"
                        " WHERE action = :a AND run_id = :r ORDER BY occurred_at"
                    ),
                    {"a": action, "r": run_id},
                )
            ).all()
        )


async def refused(
    control: SqlRunControl, run: RunContext, door: RunControlDoor, **kw: Any
) -> RunHaltedError | None:
    try:
        await control.require_open(run, door=door, **kw)
    except RunHaltedError as halted:
        return halted
    return None


def changed(control: SqlRunControl, world: World, switch: uuid.UUID) -> None:
    """What the switch's NOTIFY does, without waiting for it."""
    control.invalidate(f'{{"tenant_id": "{world.tenant.tenant_id}", "id": "{switch}"}}')


# ---- R8.1, R8.11: at the doors ---------------------------------------------------


async def test_a_new_live_or_test_run_of_a_killed_component_is_cancelled_at_its_start(
    world: World,
) -> None:
    """R8.1: the runner's start door, the run's own component named by its
    context alone: `cancelled` `artifact_killed`, no model call."""
    component = uuid.uuid4()
    await kill(world, component)
    stack = world.stack(world.control(listen=False))
    for mode in ("live", "test"):
        run = world.run(artifact_id=component, run_mode=mode)
        with pytest.raises(RunHaltedError) as halted:
            await stack.runner.start(run_context=run, input_payload={"subject": "x"})
        assert halted.value.reason is HaltReason.ARTIFACT_KILLED
        row = await world.run_row(run.run_id)
        assert (row.status, row.error["reason_code"]) == ("cancelled", "artifact_killed")


async def test_a_simulate_run_of_a_killed_component_still_runs(world: World) -> None:
    """R8.1: "still allows `simulate` runs so a fix can be evaluated"."""
    component = uuid.uuid4()
    await kill(world, component)
    stack = world.stack(world.control(listen=False))
    run = world.run(artifact_id=component, run_mode="simulate")
    await stack.runner.start(run_context=run, input_payload={"subject": "x"})
    row = await world.run_row(run.run_id)
    assert row.status == RunStatus.WAITING_APPROVAL.value


async def test_another_companys_kill_naming_the_same_id_refuses_nothing_here(
    world: World,
) -> None:
    """AL16: a switch is read under the run's company alone."""
    component = uuid.uuid4()
    async with world.migrator.begin() as conn:
        other = await plant_tenant(conn)
    await kill(world, component, other=other)
    control = world.control(listen=False)
    assert await refused(control, world.run(artifact_id=component), RunControlDoor.TOOL) is None


async def test_the_answer_names_who_set_the_switch_that_refused(world: World) -> None:
    """R8.11 (AL29): P's kill names P; Q's freeze of the company over it names
    Q; an operator O's platform freeze names O with its id; a locked company
    names nobody. Without `set_by` in the snapshot each goes red."""
    component = uuid.uuid4()
    switch = await kill(world, component)
    control = world.control(listen=False)
    run = world.run(artifact_id=component)

    halted = await refused(control, run, RunControlDoor.NODE)
    assert halted is not None and halted.reason is HaltReason.ARTIFACT_KILLED
    assert (halted.set_by, halted.switch_id) == (world.person, switch)

    freeze = await freeze_by(world, world.decider)
    changed(control, world, freeze)
    halted = await refused(control, run, RunControlDoor.NODE)
    assert halted is not None and halted.reason is HaltReason.TENANT_FROZEN
    assert (halted.set_by, halted.switch_id) == (world.decider, freeze)

    operator, freeze_id = uuid.uuid4(), uuid.uuid4()
    async with world.provisioner.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.platform_freezes (id, reason_code, reason, set_by)"
                " VALUES (:i, 'maintenance', 'bảo trì', :o)"
            ),
            {"i": freeze_id, "o": operator},
        )
    try:
        control.invalidate('{"platform": true}')
        halted = await refused(control, run, RunControlDoor.NODE)
        assert halted is not None and halted.reason is HaltReason.PLATFORM_FROZEN
        assert (halted.set_by, halted.switch_id) == (operator, freeze_id)
    finally:
        async with world.provisioner.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.platform_freezes SET lifted_at = now(), lifted_by = :o"
                    " WHERE id = :i"
                ),
                {"i": freeze_id, "o": operator},
            )

    await world.company("locked")
    halted = await refused(control, run, RunControlDoor.START)
    assert halted is not None and halted.reason is HaltReason.TENANT_LOCKED
    assert (halted.set_by, halted.switch_id) == (None, None)


@pytest.mark.parametrize("trigger", ["datahub", "manual"])
async def test_at_admission_a_killed_components_queued_run_is_cancelled_even_when_frozen(
    world: World, trigger: Any
) -> None:
    """R8.1 (DO-28 C): a trigger's queued run is cancelled `artifact_killed`,
    not held by the freeze over it; the same component's `simulate` run is
    admitted."""
    component = uuid.uuid4()
    await kill(world, component)
    await world.freeze()
    lane = StudioRunsLane(world.control(listen=False))
    queued = QueuedRun(trigger, world.run(artifact_id=component, run_as_principal_id=world.service))
    lane.queue.append(queued)
    await lane.tick()
    assert (queued.status, queued.reason) == ("cancelled", "artifact_killed")
    assert lane.model_calls == []


async def test_at_admission_a_killed_components_simulate_run_is_admitted(world: World) -> None:
    component = uuid.uuid4()
    await kill(world, component)
    lane = StudioRunsLane(world.control(listen=False))
    queued = QueuedRun("test", world.run(artifact_id=component, run_mode="simulate"))
    lane.queue.append(queued)
    await lane.tick()
    assert queued.status == "ran"


async def test_a_decision_on_a_killed_components_paused_run_is_refused(world: World) -> None:
    """The decide door: 409 `artifact_killed`, the request still pending."""
    control = world.control(listen=False)
    stack = world.stack(control)
    _, run_id, approval = await stack.paused()
    component = await workflow(world)
    await studio_row(world, run_id, component)
    changed(control, world, await kill(world, component[0]))
    with pytest.raises(RunHaltedError) as halted:
        await stack.decide(approval)
    assert halted.value.reason is HaltReason.ARTIFACT_KILLED
    _, [request] = await run_and_request(world, run_id)
    assert request.status == "pending"


# ---- R8.2, R8.3, R8.10: the lane ------------------------------------------------


async def test_the_lane_cancels_the_parked_runs_and_their_requests_in_ps_name(
    world: World,
) -> None:
    """R8.2 (AL13): a run waiting for its approval, a Studio run `waiting`,
    one `waiting_timer` and one `queued`: each `cancelled` `artifact_killed`,
    its pending request `cancelled`, audited with P as actor and
    `details.lane` `control_switch`. A `simulate` run waiting is left."""
    stack = world.stack(world.control(listen=False))
    component = await workflow(world)
    parked: dict[str, uuid.UUID] = {}
    for status in ("waiting_approval", "waiting", "waiting_timer", "queued"):
        _, run_id, _ = await stack.paused()
        await studio_row(world, run_id, component, status=status)
        parked[status] = run_id
    _, simulated, _ = await stack.paused()
    await studio_row(world, simulated, component, status="waiting", run_mode="simulate")
    switch = await kill(world, component[0])

    assert await lane_of(world).handle(world.tenant.tenant_id, switch) == 4

    for status, run_id in parked.items():
        run, requests = await run_and_request(world, run_id)
        assert run.status == "cancelled", status
        assert run.error == {"code": "artifact_killed", "switch_id": str(switch)}
        assert [r.status for r in requests] == ["cancelled"]
        [cancelled_request] = await audits(world, "approval.cancelled", run_id)
        [cancelled_run] = await audits(world, "run.cancelled", run_id)
        for audit in (cancelled_request, cancelled_run):
            assert audit.actor_id == world.person
            assert audit.details["lane"] == "control_switch"
            assert audit.details["switch_id"] == str(switch)
        assert cancelled_run.details["reason_code"] == "artifact_killed"
    run, requests = await run_and_request(world, simulated)
    assert run.status == "waiting" and [r.status for r in requests] == ["pending"]

    # Delivered again: nothing parked, nothing written twice.
    assert await lane_of(world).handle(world.tenant.tenant_id, switch) == 0
    assert len(await audits(world, "run.cancelled", parked["waiting"])) == 1


async def test_a_decision_after_the_lane_is_a_409_and_resumes_nothing(world: World) -> None:
    """R8.3 (AL13): the request is no longer pending and the run no longer
    waiting; the run stays `cancelled`."""
    stack = world.stack(world.control(listen=False))
    _, run_id, approval = await stack.paused()
    component = await workflow(world)
    await studio_row(world, run_id, component)
    switch = await kill(world, component[0])
    await lane_of(world).handle(world.tenant.tenant_id, switch)

    with pytest.raises(ConflictError):
        await stack.decide(approval)
    run, _ = await run_and_request(world, run_id)
    assert run.status == "cancelled"


async def test_a_lifted_kill_or_another_companys_event_cancels_nothing(world: World) -> None:
    """The lift's own event, and an event replayed under another company:
    the switch is not an open kill there, nothing changes."""
    stack = world.stack(world.control(listen=False))
    _, run_id, _ = await stack.paused()
    component = await workflow(world)
    await studio_row(world, run_id, component)
    switch = await kill(world, component[0])
    async with world.migrator.begin() as conn:
        other = await plant_tenant(conn)

    assert await lane_of(world).handle(other.tenant_id, switch) == 0
    await revive(world, switch)
    assert await lane_of(world).handle(world.tenant.tenant_id, switch) == 0
    run, _ = await run_and_request(world, run_id)
    assert run.status == "waiting_approval"


@dataclass
class _Hook:
    """Writes one audit row through the unit it is handed; raises when told."""

    calls: list[tuple[uuid.UUID, uuid.UUID, str]] = field(default_factory=list)
    fail: bool = False
    tenant: uuid.UUID = field(default_factory=uuid.uuid4)
    workspace: uuid.UUID = field(default_factory=uuid.uuid4)

    async def on_cancel(
        self, unit: RunCancelUnit, run_id: uuid.UUID, *, actor: uuid.UUID, lane: str
    ) -> None:
        self.calls.append((run_id, actor, lane))
        await unit.audit(
            AuditEvent(
                id=uuid.uuid4(),
                tenant_id=TenantId(self.tenant),
                workspace_id=WorkspaceId(self.workspace),
                actor_id=UserId(actor),
                action="run.effect_unresolved",
                resource_type="worker_run",
                resource_id=str(run_id),
                occurred_at=SystemClock().now(),
                run_id=run_id,
                details={"lane": lane},
            )
        )
        if self.fail:
            raise RuntimeError("the hook could not record")


async def test_a_registered_hook_writes_in_the_cancel_and_a_failing_one_keeps_the_run(
    world: World,
) -> None:
    """R8.10 (AL29): the hook is called once with the run, P and the lane, and
    what it writes through the unit commits with the cancel; when it raises,
    the run stays `waiting`, its row is gone with the cancel, and the event
    delivered again cancels it."""
    stack = world.stack(world.control(listen=False))
    _, run_id, _ = await stack.paused()
    component = await workflow(world)
    await studio_row(world, run_id, component, status="waiting")
    switch = await kill(world, component[0])
    hook = _Hook(fail=True, tenant=world.tenant.tenant_id, workspace=world.tenant.main)
    hooks = RunCancelHooks()
    hooks.register("effects", hook)
    lane = lane_of(world, hooks)

    with pytest.raises(RuntimeError):
        await lane.handle(world.tenant.tenant_id, switch)
    run, requests = await run_and_request(world, run_id)
    assert run.status == "waiting" and [r.status for r in requests] == ["pending"]
    assert await audits(world, "run.effect_unresolved", run_id) == []

    hook.fail = False
    assert await lane.handle(world.tenant.tenant_id, switch) == 1
    assert hook.calls == [(run_id, world.person, "control_switch")] * 2
    [written] = await audits(world, "run.effect_unresolved", run_id)
    assert (written.actor_id, written.details["lane"]) == (world.person, "control_switch")
    run, _ = await run_and_request(world, run_id)
    assert run.status == "cancelled"


# ---- R8.9: a provider call in flight ---------------------------------------------

TOOL = "mail.send"


class SendInput(BaseModel):
    to: str


class SendOutput(BaseModel):
    message_id: str


def _executor(
    sessions: async_sessionmaker[AsyncSession],
    control: SqlRunControl,
    handler: Callable[[BaseModel, RunContext], Any],
) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=ToolDefinition(
                name=TOOL,
                version="1.0.0",
                description="Send a message",
                input_schema_ref="contracts/tools/mail.send/input.json",
                output_schema_ref="contracts/tools/mail.send/output.json",
                required_scopes=frozenset({"demo.write"}),
                side_effect_level="external",
                approval_policy="conditional",
                timeout_seconds=10,
                max_retries=0,
                idempotent=True,
                data_classification=frozenset({"internal"}),
            ),
            behaviour=pydantic_behaviour(SendInput, SendOutput, handler),
        )
    )
    return ToolExecutor(
        registry=registry,
        execution_store=SqlToolExecutionStore(sessions),
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=SqlToolClaims(sessions),
        steps=build_tool_executor_steps(),
        run_control=control,
    )


@pytest.mark.parametrize(
    ("switch", "answer", "status", "reason"),
    [
        ("kill", "unknown", "outcome_unknown", HaltReason.ARTIFACT_KILLED),
        ("freeze", "unknown", "outcome_unknown", HaltReason.TENANT_FROZEN),
        ("kill", "succeeded", "succeeded", HaltReason.ARTIFACT_KILLED),
    ],
)
async def test_a_call_in_flight_ends_by_its_typed_outcome_and_the_next_door_cancels(
    world: World, switch: str, answer: str, status: str, reason: HaltReason
) -> None:
    """R8.9 (AL28): the provider holds the call while the switch is set; the
    call is not cut, its end row is what the egress answered (never `failed`
    or `cancelled`), the provider got one call, and the next door refuses."""
    component = uuid.uuid4()
    control = world.control(listen=False)
    run = world.run(artifact_id=component)
    received: list[str] = []
    in_flight, release = asyncio.Event(), asyncio.Event()

    async def provider(payload: BaseModel, run_context: RunContext) -> SendOutput:
        assert isinstance(payload, SendInput)
        received.append(payload.to)
        in_flight.set()
        await release.wait()
        if answer == "unknown":
            raise OutcomeUnknownError("connection reset after DATA")
        return SendOutput(message_id="m-1")

    executor = _executor(world.sessions, control, provider)
    key = f"k-{uuid.uuid4().hex}"
    call = asyncio.create_task(
        executor.execute(
            name=TOOL,
            version="1.0.0",
            raw_input={"to": "a@x.vn"},
            run_context=run,
            idempotency_key=key,
        )
    )
    await in_flight.wait()
    set_switch = await (kill(world, component) if switch == "kill" else world.freeze())
    changed(control, world, set_switch)
    release.set()
    if answer == "unknown":
        with pytest.raises(OutcomeUnknownError):
            await call
    else:
        await call

    async with world.migrator.connect() as conn:
        rows = [
            r.status
            for r in await conn.execute(
                sa.text(
                    "SELECT status FROM platform.tool_executions"
                    " WHERE tenant_id = :t AND tool_name = :n AND idempotency_key = :k"
                    " ORDER BY status <> 'dispatched'"
                ),
                {"t": world.tenant.tenant_id, "n": TOOL, "k": key},
            )
        ]
    assert rows == ["dispatched", status]
    assert received == ["a@x.vn"]
    halted = await refused(control, run, RunControlDoor.TOOL)
    assert halted is not None and halted.reason is reason


# ---- R8.4, R8.6: the lanes that ask `admission_state` ------------------------------


@dataclass
class QueuedMessage:
    artifact_id: uuid.UUID
    sent: bool = False


@dataclass
class SendLane:
    """A stand-in for connections-and-vault's W2 lane: before each queued
    message it asks the component's admission and calls no provider while
    it is refused."""

    control: SqlRunControl
    tenant: uuid.UUID
    queue: list[QueuedMessage] = field(default_factory=list)
    provider: list[uuid.UUID] = field(default_factory=list)

    async def tick(self) -> None:
        for message in [m for m in self.queue if not m.sent]:
            if await self.control.admission_state(self.tenant, [message.artifact_id]) is not None:
                continue
            self.provider.append(message.artifact_id)
            message.sent = True


async def test_a_queued_message_of_a_killed_component_reaches_no_provider(world: World) -> None:
    """R8.4 (AL15): the contract, with a stand-in lane; another component's
    message goes; after the revive, the held one goes."""
    component, other = uuid.uuid4(), uuid.uuid4()
    control = world.control(listen=False)
    lane = SendLane(control, world.tenant.tenant_id)
    lane.queue = [QueuedMessage(component), QueuedMessage(other)]
    switch = await kill(world, component)
    await lane.tick()
    assert lane.provider == [other]

    await revive(world, switch)
    changed(control, world, switch)
    await lane.tick()
    assert lane.provider == [other, component]


@dataclass
class TriggerLane:
    """A stand-in for workflow-triggers' lane: each fire asks the workflow's
    admission, records `refused_killed` while it is killed, and asks for a
    run once it is not. No state of its own to undo on a revive."""

    control: SqlRunControl
    tenant: uuid.UUID
    workflow: uuid.UUID
    fires: list[str] = field(default_factory=list)

    async def fire(self) -> None:
        state = await self.control.admission_state(self.tenant, [self.workflow])
        self.fires.append("refused_killed" if state is HaltReason.ARTIFACT_KILLED else "requested")


async def test_a_killed_workflows_trigger_records_refused_then_asks_after_the_revive(
    world: World,
) -> None:
    """R8.6: no step turns the trigger back on; the revive alone does."""
    component = uuid.uuid4()
    control = world.control(listen=False)
    lane = TriggerLane(control, world.tenant.tenant_id, component)
    switch = await kill(world, component)
    await lane.fire()
    await revive(world, switch)
    changed(control, world, switch)
    await lane.fire()
    assert lane.fires == ["refused_killed", "requested"]
