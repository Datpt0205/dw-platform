"""Unit: a pinned workflow compiled and run in memory, every port a fake
(wf-lite R5.1-R5.3, R6.1, R6.3, R6.4, R6.6, R6.10, R6.16, R6.18-R6.21; WFL9,
WFL10, WFL12, WFL15, WFL18, WFL21, WFL23, WFL25, WFL26).

The real runner, checkpointer and work queue are the integration test's; here
the graph's shape and its nodes' decisions are checked against an in-memory
checkpointer, the way the runner drives it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import DecisionCall
from dw_agent_runtime.wflite.catalog import PackCatalog
from dw_agent_runtime.wflite.compile import (
    WfPorts,
    compile_workflow,
    worker_definition_of,
)
from dw_kernel.errors import PermissionDeniedError
from dw_kernel.ports import FixedClock
from dw_platform.application.decision_gate import AskPerson, Auto
from dw_platform.domain.digital_worker import DigitalWorker, DwConfiguration, DwPeople

pytestmark = pytest.mark.unit

PACKS = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
VALIDATOR = uuid.uuid4()
DW_ID = uuid.uuid4()
DRAFT = {"to": "an@khach.vn", "subject": "Chào anh", "body": "Cảm ơn anh.", "confidence": 0.9}


class EmailInput(BaseModel):
    to: str
    subject: str
    body: str


class NoteInput(BaseModel):
    text: str


@dataclass
class _Tool:
    input_model: type[BaseModel]


class Tools:
    def resolve(self, name: str, version: str) -> _Tool:
        return _Tool(EmailInput if name == "email.send" else NoteInput)

    def all_definitions(self) -> list[Any]:
        return []


class SpecTools:
    """The validator's view: what each tool is and its effect."""

    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(side_effect_level="external" if name == "email.send" else "internal")


@dataclass
class Gateway:
    answer: dict[str, Any] = field(default_factory=lambda: dict(DRAFT))
    requests: list[Any] = field(default_factory=list)

    async def generate_structured(self, request: Any, output_type: Any, *, run_context: Any) -> Any:
        self.requests.append(request)
        return output_type.model_validate(self.answer)


class _Out(BaseModel):
    sent: bool = True


@dataclass
class Executor:
    calls: list[tuple[str, dict[str, Any], DecisionCall | None, str | None]] = field(
        default_factory=list
    )
    refuse: str | None = None
    raises: Exception | None = None

    async def execute(self, *, name: str, raw_input: dict[str, Any], **kw: Any) -> BaseModel:
        if self.raises is not None:
            raise self.raises
        if self.refuse and name == "email.send":
            raise PermissionDeniedError("refused", details={"reason_code": self.refuse})
        self.calls.append((name, raw_input, kw.get("decision"), kw.get("idempotency_key")))
        return _Out()


@dataclass
class Gate:
    ask: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)

    async def check(self, scope: Any, dw_id: Any, **kw: Any) -> Any:
        self.checks.append(kw)
        if not self.ask:
            return Auto(effective_level="A3")
        return AskPerson(
            payload={
                "approval_type": "dw.decision",
                "proposal": dict(kw["proposal"]),
                "proposal_schema": kw["proposal_schema"],
                "locked_fields": kw["locked_fields"],
                "step_id": kw["step_id"],
            }
        )


@dataclass
class Queue:
    handed: list[dict[str, Any]] = field(default_factory=list)

    async def hand_off(self, scope: Any, item_id: Any, *, to_user: Any, packet: Any) -> None:
        self.handed.append({"to": to_user, **packet})


class Workers:
    async def digital_worker(self, scope: Any, dw_id: Any) -> DigitalWorker:
        return DigitalWorker(
            id=DW_ID,
            tenant_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            principal_user_id=uuid.uuid4(),
            configuration=DwConfiguration(
                key="sample",
                name="Mẫu",
                mandate="x",
                work_kinds=("lead.new",),
                allowed_tools=("email.send", "lead.note"),
                workflow_key="sample",
                workflow_version="1.0.0",
                parameters={},
                role_keys=frozenset({"member"}),
                decision_classes=(),
            ),
            people=DwPeople(VALIDATOR, VALIDATOR, VALIDATOR, VALIDATOR),
            state="operating",
            created_by=VALIDATOR,
            created_at=NOW,
            updated_at=NOW,
        )


@dataclass
class Bench:
    gateway: Gateway = field(default_factory=Gateway)
    executor: Executor = field(default_factory=Executor)
    gate: Gate = field(default_factory=Gate)
    queue: Queue = field(default_factory=Queue)

    def ports(self) -> WfPorts:
        return WfPorts(
            gateway=self.gateway,
            executor=self.executor,  # type: ignore[arg-type]
            tools=Tools(),  # type: ignore[arg-type]
            gate=self.gate,  # type: ignore[arg-type]
            queue=self.queue,  # type: ignore[arg-type]
            workers=Workers(),
            clock=FixedClock(NOW),
            recommendations={"step_failed": "Xem lại bước lỗi.", "low_confidence": "Viết lại thư."},
        )


def pinned() -> Any:
    found = PackCatalog.load(PACKS, SpecTools()).workflow("sample", "1.0.0")
    assert found is not None
    return found


RUN = RunContext(
    run_id=uuid.uuid4(),
    tenant_id=uuid.uuid4(),
    workspace_id=uuid.uuid4(),
    actor_id=uuid.uuid4(),
    worker_id="dw:sample",
    worker_version="1.0.0",
    channel="dw_work",
    plan_id="professional",
    roles=frozenset(),
    scopes=frozenset(),
    trace_id="t",
)


class Run:
    def __init__(self, bench: Bench, *, sha: str | None = None) -> None:
        self.pinned = pinned()
        self.graph: Any = compile_workflow(self.pinned, bench.ports()).compile(
            checkpointer=InMemorySaver()
        )
        self.config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        self.sha = sha or self.pinned.sha256

    async def start(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "work": {"name": "Anh", "email": "an@khach.vn"},
            "params": {"reply_wait_seconds": 60},
            "dw_id": str(DW_ID),
            "work_item_id": str(uuid.uuid4()),
            "definition_hash": self.sha,
            "trail": [],
        }
        result: dict[str, Any] = await self.graph.ainvoke(
            state, self.config, context=RUN, durability="sync"
        )
        return result

    async def resume(self, value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await self.graph.ainvoke(
            Command(resume=value), self.config, context=RUN, durability="sync"
        )
        return result


def interrupted(state: dict[str, Any]) -> dict[str, Any]:
    [pause] = state["__interrupt__"]
    value: dict[str, Any] = pause.value
    return value


def worker_and_graph() -> None:
    """R6.1: the worker a pinned document runs as."""


def test_a_pinned_document_runs_as_dw_key_at_its_version() -> None:
    definition = worker_definition_of(pinned())
    assert (definition.worker_id, definition.worker_version, definition.graph_version) == (
        "dw:sample",
        "1.0.0",
        "1.0.0",
    )


async def test_the_gate_asks_with_the_tools_input_schema_and_waits() -> None:
    """R6.3, R6.21, WFL12, WFL26: an approval pauses the run, nothing is sent,
    and nothing is handed off."""
    bench = Bench()
    run = Run(bench)
    state = await run.start()
    asked = interrupted(state)
    assert asked["approval_type"] == "dw.decision"
    assert asked["step_id"] == "approve_send"
    assert asked["proposal_schema"] == EmailInput.model_json_schema()
    assert asked["proposal"] == {k: DRAFT[k] for k in ("to", "subject", "body")}
    assert bench.executor.calls == [] and bench.queue.handed == []
    request = bench.gateway.requests[0]
    assert (request.prompt_id, request.prompt_version) == ("sample.first_touch", "1.0.0")
    assert request.variables == {"name": "Anh", "email": "an@khach.vn"}


async def test_an_approved_edit_is_what_is_sent_with_the_approval_shown() -> None:
    """R6.4, R6.10, WFL18: the edited subject goes out, keyed by run and step."""
    bench = Bench()
    run = Run(bench)
    await run.start()
    approval = str(uuid.uuid4())
    edited = {"to": "an@khach.vn", "subject": "Đã sửa", "body": "Cảm ơn anh."}
    state = await run.resume(
        {"approved": True, "comment": "", "edited_proposal": edited, "approval_id": approval}
    )
    interrupted(state)  # now waiting on the reply timer
    name, sent, decision, key = bench.executor.calls[0]
    assert (name, sent) == ("email.send", edited)
    assert decision == DecisionCall("email.first_touch", "approve_send", uuid.UUID(approval))
    assert key == f"wf:{RUN.run_id}:send:"


async def test_a_rejection_takes_the_rejected_lane() -> None:
    bench = Bench()
    run = Run(bench)
    await run.start()
    await run.resume({"approved": False, "comment": "không"})
    assert [c[0] for c in bench.executor.calls] == ["lead.note"]
    assert bench.executor.calls[0][1] == {"text": "không"}


async def test_a_decision_within_its_level_goes_straight_to_the_approved_lane() -> None:
    bench = Bench(gate=Gate(ask=False))
    run = Run(bench)
    state = await run.start()
    assert interrupted(state)["wait"] == "timer"
    assert [c[0] for c in bench.executor.calls] == ["email.send"]


async def test_the_timer_waits_then_the_switch_routes() -> None:
    """R6.5: the wait is an interrupt with `wait: timer`; then `route` takes
    the `true` lane and notes the sent subject."""
    bench = Bench(gate=Gate(ask=False))
    run = Run(bench)
    state = await run.start()
    timer = interrupted(state)
    assert timer["wake_at"] == "2026-10-30T09:01:00+00:00"
    state = await run.resume({"woke_at": "2026-10-30T09:01:00+00:00"})
    assert "__interrupt__" not in state
    assert [c[0] for c in bench.executor.calls] == ["email.send", "lead.note"]
    trail = state["trail"]
    assert [e["step_id"] for e in trail] == [
        "draft",
        "approve_send",
        "send",
        "wait_reply",
        "route",
        "note_sent",
    ]
    assert all(set(e) == {"step_id", "type", "status", "at"} for e in trail)
    assert "Chào anh" not in str(trail) and "an@khach.vn" not in str(trail)


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        ({k: v for k, v in DRAFT.items() if k != "subject"}, "model_output_invalid"),
        ({**DRAFT, "confidence": 0.4}, "low_confidence"),
    ],
    ids=["invalid", "low-confidence"],
)
async def test_a_model_answer_out_of_bounds_hands_off_to_the_validator(
    answer: dict[str, Any], code: str
) -> None:
    """WFL9, WFL10, WFL25: handed off, nothing after it runs."""
    bench = Bench(gateway=Gateway(answer=answer))
    run = Run(bench)
    state = await run.start()
    assert "__interrupt__" not in state and state["handed_off"] is True
    [packet] = bench.queue.handed
    assert packet["to"] == VALIDATOR and packet["problem"] == f"{code} at draft"
    assert all(packet[k] for k in ("problem", "context", "tried", "recommendation"))
    assert bench.gate.checks == [] and bench.executor.calls == []
    assert [e["status"] for e in state["trail"]] == ["handed_off"]


async def test_a_refused_tool_call_hands_off_and_stops() -> None:
    """R6.16 (WFL22): the executor refuses at the DW's boundary."""
    bench = Bench(gate=Gate(ask=False), executor=Executor(refuse="dw_not_operating"))
    run = Run(bench)
    state = await run.start()
    assert state["handed_off"] is True
    assert bench.queue.handed[0]["problem"] == "dw_not_operating at send"


async def test_a_failing_step_is_a_failed_trail_entry_and_a_hand_off() -> None:
    """R6.18 (WFL23)."""
    bench = Bench(gate=Gate(ask=False), executor=Executor(raises=RuntimeError("boom")))
    run = Run(bench)
    state = await run.start()
    assert state["trail"][-1]["status"] == "failed"
    assert bench.queue.handed[0]["problem"] == "step_failed at send"
    assert bench.queue.handed[0]["recommendation"] == "Xem lại bước lỗi."


async def test_a_changed_document_hands_off_before_any_step() -> None:
    """R6.19 (WFL21): the run pinned another sha256."""
    bench = Bench()
    run = Run(bench, sha="0" * 64)
    state = await run.start()
    assert bench.queue.handed[0]["problem"] == "definition_changed at draft"
    assert bench.gateway.requests == [] and state["handed_off"] is True
