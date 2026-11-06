"""A Studio run that waits, resumes and is checked before it goes on
(workflow-engine/05: R6.1, R6.4, R6.5, R6.7, R6.8, R6.12, R6.16, R6.37; WE9,
WE10, WE23).

In memory: the wait rows are `FakeRunWaits` in a `FakeUnitOfWork` that writes
only on commit, the run store is `FakeTake` of `test_studio_runner`, the saver
LangGraph's own in-memory one. The rows, the trigger, the decision's
transaction and the park's locks against PostgreSQL are
`dw_studio/tests/integration/test_run_waits_db.py`'s.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_studio_runner import FakeTake, go, pinned_engine, studio_run

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.ports import RunWait, StudioRun, WaitKind
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.run_waits import FakeRunWaits, FakeUnitOfWork, FakeUowFactory
from dw_agent_runtime.testing.studio_runs import (
    FakeBindingReview,
    NoExpressions,
    RecordingAlerts,
    ScriptedDoor,
    StudioHarness,
    document,
    step,
    studio_run_context,
)
from dw_agent_runtime.testing.workflow_types import FIXTURE_WAIT, fixture_node_registry
from dw_agent_runtime.wflite import node_wrapper
from dw_agent_runtime.wflite.node_wrapper import (
    WAIT_REASONS,
    StudioRunPorts,
    StudioWaits,
    wait_node,
)
from dw_agent_runtime.wflite.registry import WaitSpec
from dw_agent_runtime.wflite.resume import BuildFacts, Parked, check_resume

pytestmark = pytest.mark.unit

REGISTRY = fixture_node_registry()


def waiting_doc() -> dict[str, Any]:
    """A send, a wait, a send."""
    return document(
        step("truoc", "fixture.effect@1"),
        step("cho", "fixture.wait@1"),
        step("sau", "fixture.effect@1"),
    )


def two_waits_doc() -> dict[str, Any]:
    return document(step("cho_mot", "fixture.wait@1"), step("cho_hai", "fixture.wait@1"))


@dataclasses.dataclass
class Stack:
    harness: StudioHarness
    door: ScriptedDoor
    waits: FakeRunWaits
    uows: FakeUowFactory
    store: FakeTake
    runner: LangGraphWorkflowRunner


class FixedScopes:
    def __init__(self, scopes: frozenset[str] | None = frozenset(), *, fails: bool = False):
        self.answer, self.fails = scopes, fails
        self.asked: list[uuid.UUID] = []

    async def scopes(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID, principal_id: uuid.UUID
    ) -> frozenset[str] | None:
        self.asked.append(principal_id)
        if self.fails:
            raise ConnectionError("the database is gone")
        return self.answer


def stack(doc: Mapping[str, Any], *, scopes: Any = None, **over: Any) -> Stack:
    waits, uows = FakeRunWaits(), FakeUowFactory()
    h = StudioHarness(REGISTRY, waits=StudioWaits(cast(Any, uows), waits))
    door = ScriptedDoor()
    h.doors["tool"] = door
    store = FakeTake(studio_run(doc, h, deadline_at=None, **over))
    h.runs = cast(Any, store)
    graphs = GraphRegistry()
    runner = LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=cast(Any, InMemorySaver()),
        run_store=cast(Any, None),
        uow_factory=cast(Any, None),
        clock=h.clock,
        id_generator=cast(Any, None),
        limits=OpenLimits(),
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
        studio=StudioRunPorts(
            nodes=h.ports(),
            registry=REGISTRY,
            binding_review=FakeBindingReview(),
            alerts=RecordingAlerts(),
            expressions=NoExpressions(),
            live_scopes=scopes,
        ),
    )
    return Stack(h, door, waits, uows, store, runner)


def taken_again(s: Stack, **over: Any) -> None:
    """The next take of the same run: admitted before, its waits re-read."""
    taken = s.store.taken
    assert isinstance(taken, StudioRun)
    rows = tuple(
        RunWait(r.interrupt_id, r.node_id, r.iteration_path, r.kind, r.status, r.resolution)  # type: ignore[arg-type]
        for r in s.waits.of(taken.run_id)
        if r.status in ("open", "resolved")
    )
    over.setdefault("deadline_at", taken.deadline_at or s.harness.clock.now() + timedelta(days=30))
    s.store.taken = replace(taken, waits=rows, **over)


def run_id_of(s: Stack) -> uuid.UUID:
    assert isinstance(s.store.taken, StudioRun)
    return s.store.taken.run_id


async def decide(s: Stack, decision: str = "approved", resolution: Any = None) -> None:
    (row,) = [r for r in s.waits.of(run_id_of(s)) if r.status == "open"]
    s.waits.runs[run_id_of(s)] = "waiting"
    uow = FakeUnitOfWork()
    await s.waits.resolve(
        uow,
        run_id_of(s),
        row.interrupt_id,
        resolution if resolution is not None else {"decision": decision, "decided_by": "u"},
    )
    await uow.commit()


async def consume(s: Stack) -> None:
    for used in s.store.consumed[-1:]:
        for row in s.waits.of(run_id_of(s)):
            if row.interrupt_id in used:
                row.status = "consumed"


# ---- R6.1, R6.37: a waiting step opens one wait and parks the run ---------------------


async def test_a_waiting_step_opens_one_wait_and_parks_the_run() -> None:
    s = stack(waiting_doc())
    assert await go(s.runner) == RunStatus.WAITING
    (row,) = s.waits.of(run_id_of(s))
    assert (row.interrupt_id, row.node_id, row.kind, row.status) == (
        "wait:cho::0",
        "cho",
        "approval",
        "open",
    )
    assert s.store.parked == ["waiting"]
    # One send before the wait, none after.
    assert len(s.door.calls) == 1
    (waiting,) = s.harness.recorder.waiting
    assert (waiting.node_id, waiting.reason_code, waiting.attempt) == ("cho", "approval_pending", 1)


async def test_a_decision_and_the_resume_go_on_after_the_wait_with_its_resolution() -> None:
    s = stack(waiting_doc())
    await go(s.runner)
    await decide(s)
    taken_again(s)
    assert await go(s.runner) == RunStatus.COMPLETED
    assert len(s.door.calls) == 2
    assert s.store.consumed[-1] == ["wait:cho::0"]
    (cho,) = s.harness.recorder.of("cho")
    assert cho.output == {"decision": "approved", "decided_by": "u"}
    # The finished step run carries the waiting one's start (telemetry R3.8).
    assert cho.started_at == s.harness.recorder.waiting[0].started_at


async def test_two_waits_in_series_open_two_rows_and_the_second_resume_carries_only_its_own() -> (
    None
):
    s = stack(two_waits_doc())
    await go(s.runner)
    await decide(s)
    taken_again(s)
    assert await go(s.runner) == RunStatus.WAITING
    await consume(s)
    rows = s.waits.of(run_id_of(s))
    assert [(r.interrupt_id, r.status) for r in rows] == [
        ("wait:cho_mot::0", "consumed"),
        ("wait:cho_hai::0", "open"),
    ]
    await decide(s, "rejected")
    taken_again(s)
    assert await go(s.runner) == RunStatus.COMPLETED
    assert s.store.consumed[-1] == ["wait:cho_hai::0"]
    assert s.harness.recorder.of("cho_hai")[0].output["decision"] == "rejected"


async def test_a_decision_before_the_park_queues_the_run_instead_of_losing_it() -> None:
    """R6.3: decided between the open and the park, the park reads it."""
    s = stack(waiting_doc())

    original = s.store.park

    async def decided_first(*args: Any, **kwargs: Any) -> Any:
        taken_again(s)
        await decide(s)
        taken_again(s)
        s.store.taken = replace(cast(StudioRun, s.store.taken), deadline_at=None)
        return await original(*args, **kwargs)

    s.store.park = decided_first  # type: ignore[method-assign]
    s.waits.runs[run_id_of(s)] = "running"
    assert await go(s.runner) == RunStatus.QUEUED


async def test_open_called_again_while_open_hands_back_the_same_row() -> None:
    waits, run_id = FakeRunWaits(), uuid.uuid4()
    first = FakeUnitOfWork()
    one = await waits.open(first, run_id, "cho", "", "approval")
    await first.commit()
    again = FakeUnitOfWork()
    assert await waits.open(again, run_id, "cho", "", "approval") == one
    await again.commit()
    assert len(waits.of(run_id)) == 1
    waits.of(run_id)[0].status = "consumed"
    later = FakeUnitOfWork()
    assert await waits.open(later, run_id, "cho", "", "approval") == "wait:cho::1"


async def test_a_wait_whose_transaction_rolls_back_leaves_no_row_and_no_step_run() -> None:
    """R6.37: the step run `waiting` is written in the wait's transaction."""

    async def refuses(opening: Any) -> None:
        raise RuntimeError("the approval request could not be written")

    registry = dict(REGISTRY)
    registry["fixture.wait@1"] = dataclasses.replace(
        REGISTRY["fixture.wait@1"],
        wait=WaitSpec(kind="approval", resume=FIXTURE_WAIT.resume, opener=refuses),
    )
    waits, uows = FakeRunWaits(), FakeUowFactory()
    h = StudioHarness(registry, waits=StudioWaits(cast(Any, uows), waits))
    run = studio_run_context()
    with pytest.raises(RuntimeError):
        await h.run(document(step("cho", "fixture.wait@1")), run=run)
    assert waits.of(run.run_id) == [] and h.recorder.waiting == []
    assert uows.opened and not uows.opened[0].committed


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("approval", "approval_pending"),
        ("incident", "incident_open"),
        ("outcome_review", "outcome_unknown"),
        ("child_run", "child_run_pending"),
    ],
)
async def test_each_kind_of_wait_records_its_reason_code(kind: WaitKind, reason: str) -> None:
    registry = dict(REGISTRY)
    registry["fixture.wait@1"] = dataclasses.replace(
        REGISTRY["fixture.wait@1"], wait=WaitSpec(kind=kind, resume=FIXTURE_WAIT.resume)
    )
    waits, uows = FakeRunWaits(), FakeUowFactory()
    h = StudioHarness(registry, waits=StudioWaits(cast(Any, uows), waits))
    run = studio_run_context()
    await h.run(document(step("cho", "fixture.wait@1")), run=run)
    ((row,), (waiting,)) = waits.of(run.run_id), h.recorder.waiting
    assert row.kind == kind and waiting.reason_code == reason == WAIT_REASONS[kind]


async def test_a_waiting_step_with_no_wait_path_fails_the_run() -> None:
    h = StudioHarness(REGISTRY)
    with pytest.raises(node_wrapper.StudioRunFailedError) as failed:
        await h.run(document(step("cho", "fixture.wait@1")))
    assert failed.value.code == "wait_unwired"


async def test_step_waiting_without_a_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="reason code"):
        await StudioHarness(REGISTRY).recorder.step_waiting(
            None,
            tenant_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            node_id="cho",
            lane_path=(),
            iteration_path="",
            attempt=1,
            started_at=StudioHarness(REGISTRY).clock.now(),
            reason_code="",
        )


# ---- R6.5, R6.7, R6.8: the checks of a run taken again --------------------------------


def build() -> BuildFacts:
    return BuildFacts(
        registry=REGISTRY,
        checkpoint_format="1",
        checkpoint_formats=frozenset({"1"}),
        langgraph="1.2.11",
    )


def wait(status: str = "resolved", resolution: Any = None, node: str = "cho") -> RunWait:
    return RunWait(
        f"wait:{node}::0",
        node,
        "",
        "approval",
        status,  # type: ignore[arg-type]
        ({"decision": "approved"} if resolution is None else resolution)
        if status == "resolved"
        else None,
    )


PARKED = Parked("lg-1", "wait:cho::0", wait_node("cho"))


def engine(**over: Any) -> dict[str, Any]:
    return {**pinned_engine(waiting_doc()), **over}


def test_a_run_whose_pins_this_build_has_passes_and_resumes_by_interrupt_id() -> None:
    verdict = check_resume(engine(), waiting_doc(), build(), [PARKED], [wait()])
    assert verdict.failed == () and verdict.resume == {"lg-1": {"decision": "approved"}}
    assert verdict.consumed == ("wait:cho::0",)


@pytest.mark.parametrize(
    ("over", "check"),
    [
        ({"compiler_version": "0"}, "a"),
        ({"node_types": ["fixture.effect@1", "fixture.gone@1"]}, "a"),
        ({"state_schema_hash": "sha256:" + "0" * 64}, "c"),
        ({"checkpoint_format": "0"}, "d"),
        ({"langgraph": "1.3.0"}, "d"),
        ({"langgraph": "2.2.11"}, "d"),
    ],
)
def test_each_engine_check_fails_on_its_own_pin(over: dict[str, Any], check: str) -> None:
    verdict = check_resume(engine(**over), waiting_doc(), build(), [PARKED], [wait()])
    assert verdict.failed == (check,) and verdict.resume == {}


def test_another_patch_of_langgraph_passes_check_d() -> None:
    assert check_resume(engine(langgraph="1.2.0"), waiting_doc(), build(), [], []).failed == ()


@pytest.mark.parametrize(
    "fact",
    ["compiler_version", "node_types", "state_schema_hash", "checkpoint_format", "langgraph"],
)
def test_a_manifest_missing_a_fact_fails_closed(fact: str) -> None:
    pinned = engine()
    del pinned[fact]
    assert check_resume(pinned, waiting_doc(), build(), [], []).failed


def test_check_b_fails_on_a_node_that_is_not_the_waits() -> None:
    renamed = Parked("lg-1", "wait:cho::0", "wait_renamed__cho")
    assert check_resume(engine(), waiting_doc(), build(), [renamed], [wait()]).failed == ("b",)
    other = wait(node="sau")
    other_parked = Parked("lg-1", "wait:sau::0", wait_node("cho"))
    assert check_resume(engine(), waiting_doc(), build(), [other_parked], [other]).failed == ("b",)


def test_check_b_fails_on_an_interrupt_no_wait_row_matches() -> None:
    assert check_resume(engine(), waiting_doc(), build(), [PARKED], []).failed == ("b",)


def test_check_b_fails_when_the_waiting_node_is_gone_from_this_build() -> None:
    registry = dict(REGISTRY)
    registry["fixture.wait@1"] = dataclasses.replace(REGISTRY["fixture.wait@1"], wait=None)
    gone = dataclasses.replace(build(), registry=registry)
    assert "b" in check_resume(engine(), waiting_doc(), gone, [PARKED], [wait()]).failed


def test_check_e_fails_on_an_empty_resolution() -> None:
    verdict = check_resume(engine(), waiting_doc(), build(), [PARKED], [wait(resolution={})])
    assert verdict.failed == ("e",)


def test_no_resolved_wait_after_a_wait_is_an_empty_resume() -> None:
    verdict = check_resume(engine(), waiting_doc(), build(), [PARKED], [wait("open")])
    assert verdict.empty and verdict.failed == () and verdict.resume == {}


def test_an_orphan_between_two_nodes_skips_b_and_e_and_consumes_a_used_resolution() -> None:
    """A resolved wait whose node already ran on before a crash is used up."""
    verdict = check_resume(engine(), waiting_doc(), build(), [], [wait(resolution={})])
    assert verdict.failed == () and not verdict.after_wait and not verdict.empty
    assert verdict.consumed == ("wait:cho::0",)


# ---- the runner on a run taken again --------------------------------------------------


async def test_a_resume_with_a_failing_check_is_blocked_and_runs_nothing() -> None:
    s = stack(waiting_doc())
    await go(s.runner)
    await decide(s)
    taken_again(s, engine={**pinned_engine(waiting_doc()), "langgraph": "1.9.0"})
    sends = len(s.door.calls)
    assert await go(s.runner) == RunStatus.BLOCKED
    assert s.store.blocked == [("incompatible_resume", {"checks": ["d"]})]
    assert len(s.door.calls) == sends and s.store.finished == []


async def test_a_resume_with_an_empty_resolution_is_blocked_by_check_e() -> None:
    s = stack(waiting_doc())
    await go(s.runner)
    await decide(s, resolution={})
    taken_again(s)
    assert await go(s.runner) == RunStatus.BLOCKED
    assert s.store.blocked == [("incompatible_resume", {"checks": ["e"]})]


async def test_a_resume_with_nothing_resolved_is_blocked_empty_resume_without_the_graph() -> None:
    """R6.5 (WE9)."""
    s = stack(waiting_doc())
    await go(s.runner)
    taken_again(s)
    sends = len(s.door.calls)
    assert await go(s.runner) == RunStatus.BLOCKED
    assert s.store.blocked == [("empty_resume", None)]
    assert len(s.door.calls) == sends


async def test_an_orphan_taken_again_runs_on_without_checks_b_and_e() -> None:
    s = stack(waiting_doc())
    s.door.script = [RuntimeError("die"), {"done": True}]
    s.store.taken = replace(cast(StudioRun, s.store.taken), deadline_at=None)
    taken_again(s)
    s.door.script = [{"done": True}]
    assert await go(s.runner) == RunStatus.WAITING


async def test_a_resume_past_the_deadline_is_cancelled_before_any_check() -> None:
    """R6.16 (WE23): even with a failing check, the deadline wins."""
    s = stack(waiting_doc())
    await go(s.runner)
    await decide(s)
    taken_again(s, deadline_at=s.harness.clock.now(), engine={"durability": "sync"})
    sends = len(s.door.calls)
    assert await go(s.runner) == RunStatus.CANCELLED
    assert len(s.store.cancelled) == 1 and s.store.blocked == [] and s.store.finished == []
    assert len(s.door.calls) == sends


async def test_a_resume_before_the_deadline_goes_on() -> None:
    s = stack(waiting_doc())
    await go(s.runner)
    await decide(s)
    taken_again(s, deadline_at=s.harness.clock.now() + timedelta(seconds=1))
    assert await go(s.runner) == RunStatus.COMPLETED


# ---- R6.12: the scopes a run is given are its principal's now ------------------------


async def test_the_run_is_given_its_principals_scopes_now_at_every_take() -> None:
    scopes = FixedScopes(frozenset({"tool.send"}))
    s = stack(waiting_doc(), scopes=scopes)
    await go(s.runner)
    assert s.door.calls[0].run.scopes == frozenset({"tool.send"})
    scopes.answer = frozenset()
    await decide(s)
    taken_again(s)
    await go(s.runner)
    assert s.door.calls[-1].run.scopes == frozenset()
    assert len(scopes.asked) == 2


@pytest.mark.parametrize("scopes", [FixedScopes(None), FixedScopes(fails=True)])
async def test_a_principal_gone_or_a_broken_port_holds_the_run(scopes: FixedScopes) -> None:
    s = stack(waiting_doc(), scopes=scopes)
    assert await go(s.runner) == RunStatus.QUEUED
    assert s.store.held and s.door.calls == [] and s.store.finished == []
