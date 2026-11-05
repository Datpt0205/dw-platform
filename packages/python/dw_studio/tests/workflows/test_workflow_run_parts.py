"""What Studio's `workflow` kind brings to a run (workflow-engine/03): its data
boundary's derivation (R1.7, R3.13), the steps a pinned result may stand in for
(R3.23), the record doors and their fakes under their contract (R4.7, R4.22;
H-7, H-30), the crash matrix around a record write and an assignment (R4.22,
WE38), and the golden traces of the W1 core (R7.1, WE45).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import InMemorySaver

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import LanePath, StepRun
from dw_agent_runtime.run_control import RunControlDoor
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.step_recorder import FakeStepRecorder
from dw_agent_runtime.testing.studio_runs import (
    StudioHarness,
    document,
    langgraph_trace,
    step,
    studio_run_context,
    with_error_lane,
)
from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.doors import DoorCall, StepDoor
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.workflows.application.boundary import derive_workflow_boundary, pinnable_steps
from dw_studio.workflows.application.doors import assign_door, records_door
from dw_studio.workflows.testing import records_port_contract
from dw_studio.workflows.testing.fakes import FakeRecordAssignPort, FakeRecordsPort
from dw_studio.workflows.testing.golden import CASES, GoldenCase, GoldenTrace, compare

pytestmark = pytest.mark.unit

REGISTRY = fixture_node_registry()


def records(step_id: str, command: str, **config: Any) -> dict[str, Any]:
    return step(
        step_id,
        "fixture.records@1",
        object=config.pop("object", "mkt_lead"),
        command=command,
        **config,
    )


# ---- R1.7: the boundary, from every depth ------------------------------------------


def test_the_boundary_is_one_row_per_object_with_the_union_of_its_flags() -> None:
    doc = document(
        with_error_lane(
            records("doc", "read", fields=["ten"]),
            [
                records("tao", "create", writes=["ghi_chu"]),
                step("giao", "fixture.assign@1", object="mkt_lead"),
            ],
        ),
        records(
            "sua_don", "update", object="don_hang", writes=["trang_thai"], fields=["trang_thai"]
        ),
    )
    found = derive_workflow_boundary(doc, REGISTRY)
    assert found.objects == (
        ObjectBoundary("don_hang", True, False, True, False, False),
        ObjectBoundary("mkt_lead", True, True, False, False, True),
    )
    assert found.fields == (
        FieldBoundary("don_hang", "trang_thai", "edit"),
        FieldBoundary("mkt_lead", "ghi_chu", "edit"),
        FieldBoundary("mkt_lead", "ten", "read"),
    )


def test_a_document_that_touches_no_record_has_an_empty_boundary() -> None:
    found = derive_workflow_boundary(document(step("a", "fixture.effect@1")), REGISTRY)
    assert found.objects == () and found.fields == ()


def test_a_field_no_step_names_is_not_granted() -> None:
    found = derive_workflow_boundary(document(records("doc", "read")), REGISTRY)
    assert found.fields == ()


# ---- R3.23: the steps a pinned result may stand in for -----------------------------


def test_only_steps_with_a_door_take_a_pinned_result() -> None:
    doc = document(
        step("gui", "fixture.effect@1"),
        step(
            "soan",
            "ai.llm@1",
            prompt="lead.reply@1.0.0",
            inputs={},
            output_schema={"type": "object"},
        ),
        step("re", "logic.switch@1", on="{{ work.x }}", cases={"a": [records("trong", "read")]}),
        step("duyet", "human.approval@1", decision_class="x", proposal={"a": 1}),
    )
    assert pinnable_steps(doc, REGISTRY) == {"gui", "soan", "trong"}


# ---- H-7, H-30: the fakes under the contract the real doors run too ---------------


async def _world() -> records_port_contract.RecordsWorld:
    port = FakeRecordsPort()
    record = port.plant({"ghi_chu": ""})
    principal_a, principal_b = uuid.uuid4(), uuid.uuid4()
    run_a = studio_run_context().model_copy(update={"run_as_principal_id": principal_a})
    run_b = run_a.model_copy(update={"run_as_principal_id": principal_b})
    return records_port_contract.RecordsWorld(
        records=port,
        assign=FakeRecordAssignPort(),
        run_a=run_a,
        run_b=run_b,
        api_name="mkt_lead",
        record_id=record,
    )


@pytest.mark.parametrize("check", records_port_contract.CHECKS, ids=lambda c: c.__name__)
async def test_the_fakes_honour_the_record_doors_contract(check: Any) -> None:
    await check(_world)


async def test_a_simulated_record_step_reaches_the_port_with_its_mode_and_writes_nothing() -> None:
    """R4.7: the door simulates; the wrapper has no way around it."""
    harness = StudioHarness(REGISTRY)
    port = FakeRecordsPort()
    record = port.plant({"ten": "An"})
    harness.doors["records"] = records_door(port)
    await harness.run(
        document(records("sua", "update", record=str(record), values={"ten": "Bình"})),
        run=studio_run_context(run_mode="simulate"),
    )
    ((_, _, mode),) = port.calls
    assert mode == "simulate" and port.applied == 0 and port.records[record] == {"ten": "An"}


async def test_an_ordinary_failure_of_the_record_door_replays_the_stored_result() -> None:
    """R4.30: the write was made, its answer lost; the next attempt under the
    same key gets the stored result back."""
    harness = StudioHarness(REGISTRY)
    port = FakeRecordsPort(fail_after_apply=1)
    record = port.plant({"ten": "An"})
    harness.doors["records"] = records_door(port)
    state = await harness.run(
        document(records("sua", "update", record=str(record), values={"ten": "Bình"}, attempts=2))
    )
    assert port.applied == 1 and len({key for _, key, _ in port.calls}) == 1
    assert state["out__sua"]["replayed"] is True


# ---- R4.22 (WE38): the crash matrix around an update and an assignment -------------


class Crash(BaseException):
    """A worker dying: not an `Exception`, so no wrapper can mistake it for a
    step's failure and retry or route it."""


POINTS = ("K1", "K2", "K3", "K4", "K5", "K6")


@dataclass
class Fuse:
    """Where the run dies, once: `point` around `target`."""

    point: str
    target: str
    armed: bool = True

    def blow(self, point: str, node: str) -> None:
        if self.armed and self.point == point and node == self.target:
            self.armed = False
            raise Crash(point)


class DyingRecorder(FakeStepRecorder):
    def __init__(self, fuse: Fuse) -> None:
        super().__init__()
        self.fuse = fuse

    async def step_started(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        node_id: str,
        lane_path: LanePath,
        iteration_path: str,
        attempt: int,
    ) -> datetime:
        self.fuse.blow("K1", node_id)
        return await super().step_started(
            tenant_id=tenant_id,
            run_id=run_id,
            node_id=node_id,
            lane_path=lane_path,
            iteration_path=iteration_path,
            attempt=attempt,
        )

    async def step_finished(self, step: StepRun) -> None:
        self.fuse.blow("K4", step.node_id)
        await super().step_finished(step)


class DyingControl(OpenRunControl):
    """Dies at the first guard of the node after the target (K6)."""

    def __init__(self, fuse: Fuse) -> None:
        super().__init__()
        self.fuse = fuse
        self.nth = {"sua": 2, "giao": 3}[fuse.target]

    async def require_open(
        self,
        run_context: RunContext,
        *,
        door: RunControlDoor,
        artifacts: Sequence[uuid.UUID] = (),
    ) -> None:
        await super().require_open(run_context, door=door, artifacts=artifacts)
        if len(self.asked) == self.nth:
            self.fuse.blow("K6", self.fuse.target)


class DyingSaver(InMemorySaver):
    """Dies before the checkpoint that holds the target's answer (K5)."""

    def __init__(self, fuse: Fuse) -> None:
        super().__init__()
        self.fuse = fuse

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        if f"out__{self.fuse.target}" in (checkpoint.get("channel_values") or {}):
            self.fuse.blow("K5", self.fuse.target)
        return await super().aput(config, checkpoint, metadata, new_versions)


def dying_door(inner: StepDoor, node: str, fuse: Fuse) -> StepDoor:
    async def door(call: DoorCall) -> Mapping[str, Any]:
        fuse.blow("K2", node)
        answer = await inner(call)
        fuse.blow("K3", node)
        return answer

    return door


@dataclass
class Matrix:
    """A run of `sua` (an update) then `giao` (an assignment), dying once
    around `target`, then taken again on the same checkpoint:

    - K1 before the attempt's start is recorded; K2 after it, before the door;
    - K3 after the door applied, before its answer reaches the wrapper;
    - K4 after the answer, before the attempt's end is recorded;
    - K5 with the node's answer in hand, before its checkpoint commits;
    - K6 after the checkpoint, at the next node's first guard."""

    fuse: Fuse
    records: FakeRecordsPort = field(default_factory=FakeRecordsPort)
    assign: FakeRecordAssignPort = field(default_factory=FakeRecordAssignPort)

    def __post_init__(self) -> None:
        self.record = self.records.plant({"ten": "An"})
        self.harness = StudioHarness(
            REGISTRY, recorder=DyingRecorder(self.fuse), run_control=DyingControl(self.fuse)
        )
        self.harness.doors["records"] = dying_door(records_door(self.records), "sua", self.fuse)
        self.harness.doors["assign"] = dying_door(assign_door(self.assign), "giao", self.fuse)

    def document(self) -> dict[str, Any]:
        return document(
            records("sua", "update", record=str(self.record), values={"ten": "Bình"}),
            step("giao", "fixture.assign@1", object="mkt_lead", record=str(self.record)),
            step("xong", "fixture.choice@1", on="yes"),
        )


async def _run_dying(point: str, target: str) -> Matrix:
    matrix = Matrix(Fuse(point, target))
    harness = matrix.harness
    graph = harness.compile(matrix.document(), saver=DyingSaver(matrix.fuse))
    run = studio_run_context()
    with pytest.raises(Crash):
        await harness.run(None, graph=graph, run=run)
    assert not matrix.fuse.armed, "the crash never happened"
    await harness.run(None, graph=graph, run=run, resume=True)
    return matrix


@pytest.mark.parametrize("target", ["sua", "giao"])
@pytest.mark.parametrize("point", POINTS)
async def test_a_crash_anywhere_around_a_write_applies_it_once(point: str, target: str) -> None:
    matrix = await _run_dying(point, target)
    assert matrix.records.applied == 1, "the update was applied twice"
    assert matrix.records.records[matrix.record]["ten"] == "Bình"
    assert matrix.assign.turn == 1, "the lead was assigned twice"
    assert len(set(matrix.assign.owners.values())) == 1
    assert len({key for _, key, _ in matrix.assign.calls}) == 1
    assert len({key for _, key, _ in matrix.records.calls}) == 1


async def test_a_new_key_on_the_run_again_assigns_the_lead_to_the_next_person() -> None:
    """The matrix can fail: a run again under a key of its own (another run
    id) is a second assignment, the rotation's next person."""
    port = FakeRecordAssignPort()
    record = uuid.uuid4()
    run = studio_run_context()
    first = await port.assign(
        run, "mkt_lead", record, write_key=f"wf:{run.run_id}:giao:", run_mode="live"
    )
    other = uuid.uuid4()
    again = await port.assign(
        run, "mkt_lead", record, write_key=f"wf:{other}:giao:", run_mode="live"
    )
    assert again.assignee_id != first.assignee_id


# ---- R7.1 (WE45): the golden traces ---------------------------------------------


class LangGraphGoldenRunner:
    """The golden runner on LangGraph: `compile_workflow`, as the runner runs it."""

    name = "langgraph"

    async def run(self, case: GoldenCase) -> GoldenTrace:
        nodes, failed = await langgraph_trace(
            case.document,
            REGISTRY,
            tool_script=case.tool_script,
            approval_decisions=case.approval_decisions,
            run_mode=case.run_mode,
            work=case.work,
        )
        return GoldenTrace(nodes, failed)


RUNNERS = (LangGraphGoldenRunner(),)


@pytest.mark.parametrize("runner", RUNNERS, ids=lambda r: r.name)
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_every_reference_document_gives_its_golden_trace(
    case: GoldenCase, runner: Any
) -> None:
    observed = await runner.run(case)
    assert compare(case.expected, observed) == []


def test_two_steps_swapped_in_a_trace_are_seen() -> None:
    expected = GoldenTrace(("a", "b", "c"))
    assert compare(expected, GoldenTrace(("b", "a", "c")))


async def test_an_outcome_unknown_that_entered_its_error_lane_would_be_seen() -> None:
    case = next(c for c in CASES if "outcome_unknown" in c.name)
    entered = GoldenTrace(("goi", "bao_loi", "join__goi", "sau"))
    assert compare(case.expected, entered)
    assert compare(case.expected, await LangGraphGoldenRunner().run(case)) == []
    assert replace(case.expected, failed=None) != case.expected
