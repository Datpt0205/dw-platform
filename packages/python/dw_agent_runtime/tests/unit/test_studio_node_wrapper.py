"""The node wrapper of a Studio run, on LangGraph with an in-memory saver
(workflow-engine/03: R4.1, R4.3-R4.13, R4.21, R4.23-R4.30, R6.28; WE5, WE7,
WE13, WE23, WE37, WE40).

Every door is a `ScriptedDoor` (`dw_agent_runtime.testing.studio_runs`) that
answers the way the real door's contract says a door may: a typed dispatch
error, an untyped one, a hang past `timeout_s`, an output. The provider "got a
call" when the door's `sends` counts it. The cases that need PostgreSQL (the
row, the audit, the manifest, the boundary) are in
`dw_studio/tests/integration/test_studio_runs.py`.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from dw_agent_runtime.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError
from dw_agent_runtime.ports import StepRun
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.testing import step_recorder_contract
from dw_agent_runtime.testing.step_recorder import FakeStepRecorder
from dw_agent_runtime.testing.studio_runs import (
    ScriptedDoor,
    StudioHarness,
    document,
    step,
    studio_run_context,
    trail_of,
    with_error_lane,
)
from dw_agent_runtime.testing.workflow_types import fixture_node_registry, fixture_node_types
from dw_agent_runtime.wflite.doors import BodyResult, EffectDoors
from dw_agent_runtime.wflite.node_wrapper import (
    MAX_OUTPUT_BYTES,
    RunDeadlineExceededError,
    StudioRunFailedError,
    classify,
    error_type_label,
    output_bytes,
)
from dw_agent_runtime.wflite.registry import (
    NO_PORTS,
    FixedOutput,
    NodeTypeSpec,
    no_dependencies,
    registry_of,
)
from dw_kernel.errors import ConfigError, ConflictError, DomainError, PermissionDeniedError
from dw_observability.metrics import DW_NODE_FAILURE_TOTAL
from dw_observability.semconv import DW_NODE

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]


# ---- types only these tests need ------------------------------------------------


def _probe(
    name: str, body: Any, *, door: Any = None, output: Mapping[str, Any] | None = None
) -> NodeTypeSpec:
    return NodeTypeSpec(
        type=name,
        label_vi=name,
        config_schema={"type": "object"},
        output=FixedOutput(output or {"type": "object", "properties": {}}),
        ports=NO_PORTS,
        block="none",
        ends_run=False,
        exits_loop=False,
        dependencies=no_dependencies,
        effect_door=door,
        body=body,
    )


async def _two_effects(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    await doors.call("tool", "fixture.send@1", {})
    return await doors.call("tool", "fixture.send@1", {})


async def _other_door(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    return await doors.call("records", "update", {"object": "x"})


async def _cel_error(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    raise ConfigError("the expression does not evaluate", details={"reason_code": "wf.cel_invalid"})


async def _sized(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    size = int(config["size"])
    overhead = output_bytes({"x": ""})
    return {"x": "a" * (size - overhead)}


def registry() -> Mapping[str, NodeTypeSpec]:
    return registry_of(
        (
            *fixture_node_registry().values(),
            _probe("test.two_effects@1", _two_effects, door="tool"),
            _probe("test.other_door@1", _other_door, door="tool"),
            _probe("test.cel@1", _cel_error),
            _probe("test.sized@1", _sized),
        )
    )


def harness(*script: Any, hangs: bool = False) -> tuple[StudioHarness, ScriptedDoor]:
    h = StudioHarness(registry())
    door = ScriptedDoor(list(script) or [{"done": True}], hangs=hangs)
    h.doors["tool"] = door
    return h, door


def send(step_id: str, **policy: Any) -> dict[str, Any]:
    return step(step_id, "fixture.effect@1", **policy)


def runs(h: StudioHarness, node_id: str) -> list[StepRun]:
    return h.recorder.of(node_id)


# ---- R4.1: blocks meet at their join ----------------------------------------------


def three_lanes() -> dict[str, Any]:
    return document(
        step(
            "re",
            "logic.switch@1",
            on="{{ work.kenh }}",
            cases={"a": [send("a1")], "b": [send("b1"), send("b2")], "c": []},
        ),
        send("x"),
    )


@pytest.mark.parametrize(
    ("kenh", "lane"), [("a", ["a1"]), ("b", ["b1", "b2"]), ("c", []), ("z", [])]
)
async def test_the_step_after_a_switch_runs_once_whichever_lane_ran(
    kenh: str, lane: list[str]
) -> None:
    h, door = harness()
    state = await h.run(three_lanes(), work={"kenh": kenh})
    assert trail_of(state) == ["re", *lane, "join__re", "x"]
    assert [c.idempotency_key.split(":")[2] for c in door.calls].count("x") == 1


@pytest.mark.parametrize(("decision", "ran"), [("rejected", []), ("approved", ["gui"])])
async def test_an_empty_rejected_lane_goes_to_the_step_after(decision: str, ran: list[str]) -> None:
    h, _ = harness()
    doc = document(
        step(
            "duyet",
            "human.approval@1",
            decision_class="lead.send",
            proposal={"x": 1},
            approved=[send("gui")],
            rejected=[],
        ),
        send("sau"),
    )
    run = studio_run_context(run_mode="simulate")
    state = await h.run(doc, run=run, approval_decisions={"duyet": decision})
    assert trail_of(state) == ["duyet", *ran, "join__duyet", "sau"]
    assert runs(h, "duyet")[0].port == decision


# ---- R4.3, R4.12, R4.13: on_error -------------------------------------------------


async def test_continue_goes_on_with_the_error_in_the_steps_channel() -> None:
    down = NotDispatchedError("down")
    h, _ = harness(down, down, down, {"done": True})
    state = await h.run(document(send("goi", on_error="continue", attempts=3), send("sau")))
    assert trail_of(state) == ["goi", "sau"]
    assert state["out__goi"]["status"] == "error"
    assert state["out__goi"]["error"]["code"] == "not_dispatched"
    assert [r.attempt for r in runs(h, "goi")] == [1, 2, 3]


async def test_fail_ends_the_run_and_the_next_step_does_not_run() -> None:
    h, door = harness(NotDispatchedError("down"))
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(document(send("goi", on_error="fail", attempts=3), send("sau")))
    assert failed.value.code == "not_dispatched"
    assert all(c.idempotency_key.split(":")[2] == "goi" for c in door.calls)


async def test_route_runs_the_error_lane_and_the_run_goes_on_once() -> None:
    h, door = harness(
        RejectedError("bad", provider_code="400"),
        {"done": True},
    )
    doc = document(
        with_error_lane(send("goi", on_error="route", attempts=3), [send("bao")]), send("sau")
    )
    state = await h.run(doc)
    assert trail_of(state) == ["goi", "bao", "join__goi", "sau"]
    # One call for the one attempt the undeclared `rejected` allows, none after the lane began.
    assert [c.idempotency_key.split(":")[2] for c in door.calls] == ["goi", "bao", "sau"]
    assert runs(h, "goi")[-1].port == "error"


async def test_each_attempt_of_a_routed_step_is_one_call_and_none_after_the_lane_starts() -> None:
    h, door = harness(
        NotDispatchedError("a"), NotDispatchedError("b"), NotDispatchedError("c"), {"done": True}
    )
    doc = document(
        with_error_lane(send("goi", on_error="route", attempts=3), [send("bao")]), send("sau")
    )
    await h.run(doc)
    steps = [c.idempotency_key.split(":")[2] for c in door.calls]
    assert steps == ["goi", "goi", "goi", "bao", "sau"]
    assert [(r.attempt, r.port) for r in runs(h, "goi")] == [(1, None), (2, None), (3, "error")]


async def test_route_without_an_error_lane_fails_like_fail() -> None:
    """Only a hand-built IR reaches it (ticket 01 refuses the document)."""
    h, door = harness(NotDispatchedError("down"))
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(document(with_error_lane(send("goi", on_error="route"), None), send("sau")))
    assert failed.value.step_id == "goi"
    assert "sau" not in [c.idempotency_key.split(":")[2] for c in door.calls]


async def test_an_empty_error_lane_joins_at_once() -> None:
    h, _ = harness(NotDispatchedError("down"), {"done": True})
    state = await h.run(document(with_error_lane(send("goi", on_error="route"), []), send("sau")))
    assert trail_of(state) == ["goi", "join__goi", "sau"]


async def test_an_error_lane_ending_in_a_stop_stops_the_run() -> None:
    h, door = harness(NotDispatchedError("down"), {"done": True})
    doc = document(
        with_error_lane(
            send("goi", on_error="route"), [send("bao"), step("dung", "fixture.stop@1")]
        ),
        send("sau"),
    )
    state = await h.run(doc)
    assert trail_of(state) == ["goi", "bao", "dung"]
    assert "sau" not in [c.idempotency_key.split(":")[2] for c in door.calls]


# ---- R4.4: one effect, through its own door --------------------------------------


async def test_a_second_effect_in_one_attempt_is_refused() -> None:
    h, door = harness()
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(document(step("hai", "test.two_effects@1", attempts=3)))
    assert failed.value.code == "second_effect"
    assert door.sends == 1  # the first call, once: a refused body is never retried


async def test_a_door_the_type_does_not_declare_is_refused() -> None:
    h, _door = harness()
    h.doors["records"] = ScriptedDoor()
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(document(step("khac", "test.other_door@1")))
    assert failed.value.code == "effect_door_undeclared"


@pytest.mark.parametrize(
    ("exc", "retried", "code"),
    [
        (ConflictError("a live claim holds the key"), True, "not_dispatched"),
        (
            DomainError("bad output", details={"reason_code": "tool_output_invalid"}),
            False,
            "tool_output_invalid",
        ),
        (
            PermissionDeniedError("policy", details={"reason_code": "policy_denied"}),
            False,
            "rejected",
        ),
    ],
)
async def test_the_tool_doors_named_errors(exc: Exception, retried: bool, code: str) -> None:
    h, _door = harness(exc, {"done": True})
    state = await h.run(document(send("goi", on_error="continue", attempts=2), send("sau")))
    first = runs(h, "goi")[0]
    assert (first.error_type, len(runs(h, "goi")) == 2) == (code, retried)
    if not retried:
        assert state["out__goi"]["error"]["code"] == code


# ---- R4.5, R4.23: one key, typed outcomes ---------------------------------------


async def test_three_not_dispatched_attempts_carry_one_key() -> None:
    h, door = harness(NotDispatchedError("a"), NotDispatchedError("b"), {"done": True})
    run = studio_run_context()
    await h.run(document(send("goi", attempts=3)), run=run)
    assert door.keys == [f"wf:{run.run_id}:goi:"] * 3
    assert door.sends == 1


async def test_a_live_claim_then_a_send_is_one_call_to_the_provider() -> None:
    """R4.5 (WE7): another worker's live claim makes this attempt send
    nothing; the next attempt under the same key sends once."""
    h, door = harness(ConflictError("held"), {"done": True})
    await h.run(document(send("goi", attempts=2)))
    assert door.sends == 1 and len(set(door.keys)) == 1


async def test_a_rejection_the_action_declares_retryable_is_retried() -> None:
    h, door = harness(RejectedError("busy", provider_code="429"), {"done": True})
    h.retryable = frozenset({"429"})
    await h.run(document(send("goi", attempts=2)))
    assert len(door.calls) == 2


async def test_a_rejection_it_does_not_declare_is_not_retried_and_on_error_applies() -> None:
    h, door = harness(RejectedError("bad", provider_code="400"), {"done": True})
    state = await h.run(document(send("goi", on_error="continue", attempts=3), send("sau")))
    assert [c.idempotency_key.split(":")[2] for c in door.calls] == ["goi", "sau"]
    assert state["out__goi"]["error"]["code"] == "rejected"
    assert runs(h, "goi")[0].error_type == "rejected"  # R6.28: not outcome_unknown


# ---- R4.24, R4.30, R6.28: an outcome nobody knows ----------------------------------


@pytest.mark.parametrize("policy", ["route", "continue"])
async def test_outcome_unknown_is_never_retried_routed_or_followed(policy: str) -> None:
    h, door = harness(OutcomeUnknownError("may have been applied"), {"done": True})
    doc = document(
        with_error_lane(send("goi", on_error=policy, attempts=3), [send("bao")]), send("sau")
    )
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(doc)
    assert failed.value.code == "outcome_unknown"
    assert door.sends == 1 and len(door.calls) == 1
    assert [(r.status, r.error_type) for r in runs(h, "goi")] == [
        ("outcome_unknown", "outcome_unknown")
    ]


async def test_a_timeout_after_dispatch_is_outcome_unknown() -> None:
    """R4.24 (T), R4.30, R6.28: the call hangs past `timeout_s` with an
    unresolved `dispatched` row of its key."""
    h, door = harness(hangs=True)
    run = studio_run_context()
    h.claims.unresolved.add(f"wf:{run.run_id}:goi:")
    doc = document(
        with_error_lane(
            {**send("goi", on_error="route", attempts=3), "timeout_s": 1}, [send("bao")]
        )
    )
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(doc, run=run)
    assert failed.value.code == "outcome_unknown"
    assert len(door.calls) == 1
    assert h.claims.asked == [("fixture.send", f"wf:{run.run_id}:goi:")]
    assert runs(h, "goi")[0].error_type == "outcome_unknown"


async def test_a_timeout_before_dispatch_is_retried_under_the_same_key() -> None:
    h, door = harness(hangs=True)
    doc = document({**send("goi", on_error="continue", attempts=2), "timeout_s": 1})
    state = await h.run(doc)
    assert len(door.calls) == 2 and len(set(door.keys)) == 1
    assert state["out__goi"]["error"]["code"] == "not_dispatched"


async def test_an_untyped_failure_of_the_tool_door_is_outcome_unknown() -> None:
    h, door = harness(RuntimeError("ECONNRESET at 0912345678"), {"done": True})
    doc = document(with_error_lane(send("goi", on_error="route", attempts=3), [send("bao")]))
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(doc)
    assert failed.value.code == "outcome_unknown"
    assert len(door.calls) == 1


async def test_an_ordinary_failure_of_an_internal_door_is_retried_under_the_key() -> None:
    """The record doors replay by key (the fakes' contract, in dw_studio's
    tests), so an ordinary failure is tried again under the same key."""
    h, _ = harness()
    records = ScriptedDoor([RuntimeError("the store blinked"), {"record": {}, "replayed": True}])
    h.doors["records"] = records
    doc = document(
        step("sua", "fixture.records@1", object="mkt_lead", command="update", attempts=2)
    )
    state = await h.run(doc)
    assert len(records.calls) == 2 and len(set(records.keys)) == 1
    assert state["out__sua"]["replayed"] is True


async def test_a_body_without_an_effect_that_refuses_is_not_retried() -> None:
    h, _ = harness()
    state = await h.run(
        document(step("tinh", "test.cel@1", on_error="continue", attempts=3), send("sau"))
    )
    assert len(runs(h, "tinh")) == 1
    assert state["out__tinh"]["error"]["code"] == "wf.cel_invalid"


def test_classify_reads_an_untyped_tool_failure_as_outcome_unknown() -> None:
    assert classify(RuntimeError("x"), "tool", frozenset()).unknown
    assert classify(RuntimeError("x"), "records", frozenset()).retryable
    assert not classify(ConfigError("x"), None, frozenset()).retryable


# ---- R4.6: the output cap -------------------------------------------------------


@pytest.mark.parametrize(("size", "ok"), [(MAX_OUTPUT_BYTES, True), (MAX_OUTPUT_BYTES + 1, False)])
async def test_the_output_cap_is_64_kib(size: int, ok: bool) -> None:
    h, _ = harness()
    state = await h.run(
        document(step("to", "test.sized@1", on_error="continue", attempts=3, size=size))
    )
    if ok:
        assert output_bytes(state["out__to"]) == size
    else:
        assert state["out__to"]["error"]["code"] == "output_too_large"
        assert len(runs(h, "to")) == 1


# ---- R4.7, R4.27-R4.29: simulate and pinned results -------------------------------


async def test_a_simulated_run_reaches_the_door_with_its_mode() -> None:
    h, door = harness()
    await h.run(document(send("goi")), run=studio_run_context(run_mode="simulate"))
    assert [c.run_mode for c in door.calls] == ["simulate"]


async def test_pinned_results_stand_in_for_the_doors_in_simulate() -> None:
    h, door = harness()
    model = ScriptedDoor()
    h.doors["model"] = model
    doc = document(
        send("gui_email"),
        step(
            "soan",
            "ai.llm@1",
            prompt="lead.reply@1.0.0",
            inputs={},
            output_schema={"type": "object", "properties": {"body": {"type": "string"}}},
        ),
        send("khong_ghim"),
    )
    pinned = {"gui_email": {"output": {"done": True}}, "soan": {"output": {"body": "Chào anh"}}}
    state = await h.run(doc, run=studio_run_context(run_mode="simulate"), pinned_results=pinned)
    assert state["out__soan"] == {"body": "Chào anh"}
    assert model.calls == []
    assert [c.idempotency_key.split(":")[2] for c in door.calls] == ["khong_ghim"]
    pinned_run = runs(h, "gui_email")[0]
    assert (pinned_run.simulated, pinned_run.source) == (True, "pinned")
    assert runs(h, "khong_ghim")[0].source == "door"


async def test_a_pinned_error_applies_the_steps_on_error() -> None:
    h, _door = harness()
    doc = document(with_error_lane(send("goi", on_error="route", attempts=3), [send("bao")]))
    pinned = {"goi": {"error": {"code": "rejected", "message": "Từ chối"}}}
    state = await h.run(doc, run=studio_run_context(run_mode="simulate"), pinned_results=pinned)
    assert trail_of(state) == ["goi", "bao", "join__goi"]
    assert len(runs(h, "goi")) == 1


async def test_a_live_run_never_reads_pinned_results() -> None:
    h, door = harness()
    await h.run(document(send("goi")), pinned_results={"goi": {"output": {"done": False}}})
    assert len(door.calls) == 1


@pytest.mark.parametrize(
    "pinned",
    [
        {"output": {"done": "không phải boolean"}},
        {"output": {"done": True, "pad": "a" * MAX_OUTPUT_BYTES}},
        {"output": {}, "error": {"code": "x", "message": "y"}},
    ],
)
async def test_a_pinned_result_that_does_not_check_fails_the_run(pinned: dict[str, Any]) -> None:
    h, door = harness()
    doc = document(with_error_lane(send("goi", on_error="route"), [send("bao")]))
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(
            doc, run=studio_run_context(run_mode="simulate"), pinned_results={"goi": pinned}
        )
    assert failed.value.code == "pinned_result_invalid"
    assert door.calls == []


async def test_a_pinned_result_for_an_approval_fails_the_run_at_that_step() -> None:
    """R4.29: a row written past the door; the step before still ran."""
    h, door = harness()
    doc = document(
        send("truoc"),
        step(
            "duyet",
            "human.approval@1",
            decision_class="lead.send",
            proposal={"x": 1},
            approved=[send("gui")],
            rejected=[],
        ),
    )
    run = studio_run_context(run_mode="simulate")
    pinned = {"duyet": {"output": {"approved": True}}}
    with pytest.raises(StudioRunFailedError) as failed:
        await h.run(doc, run=run, pinned_results=pinned, approval_decisions={"duyet": "rejected"})
    assert (failed.value.code, failed.value.step_id) == ("pinned_result_invalid", "duyet")
    assert [c.idempotency_key.split(":")[2] for c in door.calls] == ["truoc"]


# ---- R4.8, R4.11: the run's guards at each node ---------------------------------


async def test_a_freeze_between_nodes_stops_the_next_one() -> None:
    h, _door = harness()

    async def frozen_after_first(call: Any) -> Mapping[str, Any]:
        h.run_control.refuse(HaltReason.TENANT_FROZEN)
        return {"done": True}

    h.doors["tool"] = frozen_after_first
    with pytest.raises(RunHaltedError):
        await h.run(document(send("mot"), send("hai")))
    assert [door for door, _ in h.run_control.asked] == [RunControlDoor.NODE] * 2
    assert runs(h, "hai") == []


async def test_a_suspended_principal_does_not_stop_a_node() -> None:
    """The principal is asked at admission, start and resume only (ADR-0120
    Amendments 2026-11-04): a node's door does not see it."""
    h, door = harness()
    h.run_control.refuse(
        HaltReason.PRINCIPAL_INACTIVE,
        doors=[RunControlDoor.ADMISSION, RunControlDoor.START, RunControlDoor.RESUME],
    )
    await h.run(document(send("mot"), send("hai")))
    assert len(door.calls) == 2


async def test_past_the_deadline_the_next_node_cancels_the_run_and_sends_nothing() -> None:
    h, door = harness()
    run = studio_run_context()
    with pytest.raises(RunDeadlineExceededError):
        await h.run(document(send("goi")), run=run, deadline_at=h.clock.now())
    assert h.runs.cancelled == [run.run_id]
    assert door.calls == []


async def test_a_second_before_the_deadline_the_node_runs() -> None:
    h, door = harness()
    await h.run(document(send("goi")), deadline_at=h.clock.now() + timedelta(seconds=1))
    assert len(door.calls) == 1 and h.runs.cancelled == []


async def test_a_run_without_a_deadline_runs_nothing() -> None:
    h, door = harness()
    graph = h.compile(document(send("goi")))
    run = studio_run_context()
    context = h.context(run)
    context = type(context)(run=run, deadline_at=None)
    with pytest.raises(StudioRunFailedError) as failed:
        await graph.ainvoke(
            {"work": {}},
            {"configurable": {"thread_id": str(run.run_id)}, "recursion_limit": 10},
            context=context,
            durability="sync",
        )
    assert failed.value.code == "deadline_unset" and door.calls == []


# ---- R4.9, R4.21, R4.26: what each attempt records ------------------------------


async def test_the_lane_path_and_port_of_each_step() -> None:
    h, _ = harness()
    doc = document(
        send("dau"),
        step(
            "re", "logic.switch@1", on="{{ work.kenh }}", cases={"b": [send("trong_b")]}, default=[]
        ),
        step(
            "duyet",
            "human.approval@1",
            decision_class="lead.send",
            proposal={"x": 1},
            approved=[],
            rejected=[send("sau_tu_choi")],
        ),
    )
    run = studio_run_context(run_mode="simulate")
    await h.run(doc, run=run, work={"kenh": "b"}, approval_decisions={"duyet": "rejected"})
    seen = {r.node_id: (r.lane_path, r.iteration_path, r.port) for r in h.recorder.finished}
    assert seen == {
        "dau": ((), "", None),
        "re": ((), "", "b"),
        "trong_b": ((("re", "b"),), "", None),
        "duyet": ((), "", "rejected"),
        "sau_tu_choi": ((("duyet", "rejected"),), "", None),
    }


async def test_a_failed_attempt_counts_on_the_metric_by_its_label_and_opens_a_span() -> None:
    h, _ = harness()
    provider = DomainError("reset", details={"reason_code": "ECONNRESET at 0912345678"})
    h.doors["records"] = ScriptedDoor([provider, {"record": {}}])
    doc = document(step("sua", "fixture.records@1", object="mkt_lead", command="read", attempts=2))
    await h.run(doc)
    failures = [m for m in h.telemetry.metrics if m[0] == DW_NODE_FAILURE_TOTAL]
    assert failures == [(DW_NODE_FAILURE_TOTAL, 1, {"error_type": "unknown_error"})]
    assert [name for name, _ in h.telemetry.spans].count(DW_NODE) == 2


def test_error_type_label_is_a_closed_set() -> None:
    assert error_type_label("not_dispatched") == "not_dispatched"
    assert error_type_label("wf.schema_invalid") == "wf.schema_invalid"
    assert error_type_label("ECONNRESET at 0912345678") == "unknown_error"


async def test_the_recorder_refuses_what_the_wrapper_must_give() -> None:
    tenant, run = uuid.uuid4(), uuid.uuid4()

    async def make() -> FakeStepRecorder:
        return FakeStepRecorder()

    for check in step_recorder_contract.CHECKS:
        await check(make, tenant, run)


# ---- R4.25: the run's durability ------------------------------------------------


class SlowSaver(InMemorySaver):
    """Commits a checkpoint after a delay, and says when it did."""

    def __init__(self, delay: float, events: list[str]) -> None:
        super().__init__()
        self.delay = delay
        self.events = events

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        await asyncio.sleep(self.delay)
        result = await super().aput(config, checkpoint, metadata, new_versions)
        written = sorted(
            k for k in (checkpoint.get("channel_values") or {}) if k.startswith("out__")
        )
        self.events.append(f"checkpoint:{written}")
        return result


@pytest.mark.parametrize(("durability", "durable_first"), [("sync", True), ("async", False)])
async def test_the_next_step_sends_only_after_the_last_ones_checkpoint(
    durability: Any, durable_first: bool
) -> None:
    events: list[str] = []
    h, _ = harness()

    async def door(call: Any) -> Mapping[str, Any]:
        events.append(f"send:{call.idempotency_key.split(':')[2]}")
        return {"done": True}

    h.doors["tool"] = door
    saver = SlowSaver(0.5, events)
    graph = h.compile(document(send("mot"), send("hai")), saver=saver)
    await h.run(None, graph=graph, durability=durability)
    hai = events.index("send:hai")
    committed_mot = [i for i, e in enumerate(events) if e.startswith("checkpoint") and "mot" in e]
    assert committed_mot, events
    assert (committed_mot[0] < hai) is durable_first, events


# ---- R4.2: the graph holds nothing a run pinned ---------------------------------


async def test_two_runs_share_one_graph_and_each_door_call_carries_its_own_run() -> None:
    """Each run's manifest reaches the door at call time through its context
    (the `tool` door resolves the tool its manifest pinned), never baked into
    the graph."""
    h, door = harness()
    graph = h.compile(
        document(step("goi", "tool.call@1", tool="crm.send@1.0.0", input={}, decision_class="x"))
    )
    first = studio_run_context().model_copy(update={"run_manifest_hash": "sha256:" + "1" * 64})
    second = studio_run_context().model_copy(update={"run_manifest_hash": "sha256:" + "2" * 64})
    await h.run(None, graph=graph, run=first)
    await h.run(None, graph=graph, run=second)
    assert h.compiled == 1
    assert [c.run.run_manifest_hash for c in door.calls] == [
        first.run_manifest_hash,
        second.run_manifest_hash,
    ]


# ---- R4.10: a node holds no SQL and no provider SDK -----------------------------

_NODE_MODULES = (
    REPO / "packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/bodies.py",
    REPO / "packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/doors.py",
    REPO / "packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/node_wrapper.py",
    REPO / "packages/python/dw_studio/src/dw_studio/workflows/application/doors.py",
)
_FORBIDDEN_IMPORTS = ("sqlalchemy", "asyncpg", "openai", "anthropic", "httpx", "langchain_openai")
_SQL = ("SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM", "set_config(")


def node_violations(paths: tuple[Path, ...]) -> list[str]:
    found: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in _FORBIDDEN_IMPORTS:
                    found.append(f"{path.name}: imports {name}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(word in node.value for word in _SQL)
            ):
                found.append(f"{path.name}: SQL {node.value[:30]!r}")
    return found


def test_the_node_modules_hold_no_sql_and_no_provider_sdk() -> None:
    assert node_violations(_NODE_MODULES) == []


def test_a_node_module_with_sql_or_a_provider_sdk_is_seen(tmp_path: Path) -> None:
    sql = tmp_path / "sql_node.py"
    sql.write_text('Q = "SELECT * FROM studio.records"\n', encoding="utf-8")
    sdk = tmp_path / "sdk_node.py"
    sdk.write_text("import openai\n", encoding="utf-8")
    assert len(node_violations((sql, sdk))) == 2


def test_no_module_of_dw_studio_imports_langgraph() -> None:
    root = REPO / "packages/python/dw_studio/src/dw_studio"
    importers = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if any(
            (isinstance(n, ast.Import) and any(a.name.startswith("langgraph") for a in n.names))
            or (isinstance(n, ast.ImportFrom) and (n.module or "").startswith("langgraph"))
            for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    ]
    assert importers == []


# ---- R4.3: the pack path is untouched -----------------------------------------


def test_the_fixture_types_a_studio_run_runs_declare_a_body() -> None:
    bodies = {spec.type for spec in fixture_node_types() if spec.body is not None}
    assert {
        "fixture.effect@1",
        "fixture.records@1",
        "fixture.assign@1",
        "fixture.choice@1",
    } <= bodies


async def test_the_lead_document_does_not_compile_for_a_studio_run_with_a_wait() -> None:
    """`time.wait@1` has no body until workflow-engine/05: a Studio run is
    refused at compile time, closed, never a wait that cannot resume."""
    h, _ = harness()
    doc = document(step("cho", "time.wait@1", seconds=60))
    with pytest.raises(ConfigError) as refused:
        h.compile(doc)
    assert refused.value.details["reason_code"] == "step_type_unavailable"
