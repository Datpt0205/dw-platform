"""Unit: a dry run of a workflow draft (wf-ai R6.2, R6.9; WAI9).

The draft is the shipped `lead_care@1.0.0`, run by the compiler a live run
uses, with the Marketing pack's own tool models. Nothing here holds a model
client or a `ToolExecutor`: if the simulator reached either, there would be
nothing to call.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.pack_tools import (
    EmailInput,
    EmailSent,
    FetchInput,
    FetchOutput,
    HandoffDone,
    HandoffInput,
)
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.wflite.catalog import PinnedWorkflow, load_shipped_packs
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.registry import build_node_registry
from dw_agent_runtime.wflite.simulate import sample_of, simulate
from dw_kernel.ports import SystemClock
from dw_platform.domain.digital_worker import (
    DecisionClass,
    DigitalWorker,
    DwConfiguration,
    DwPeople,
)

pytestmark = pytest.mark.unit

CONFIGS = Path(__file__).resolve().parents[5] / "configs"
REGISTRY = build_node_registry()
_SHIPPED = load_shipped_packs(CONFIGS).workflow("lead_care", "1.0.0")
assert _SHIPPED is not None
PINNED: PinnedWorkflow = _SHIPPED
SALES = uuid.uuid4()


@dataclass(frozen=True)
class _Tool:
    input_model: type[BaseModel]
    output_model: type[BaseModel]


class Tools:
    MODELS: ClassVar[dict[str, _Tool]] = {
        "email.send": _Tool(EmailInput, EmailSent),
        "mailbox.fetch_reply": _Tool(FetchInput, FetchOutput),
        "work.handoff": _Tool(HandoffInput, HandoffDone),
    }

    def resolve(self, name: str, version: str) -> _Tool:
        return self.MODELS[name]


def worker() -> DigitalWorker:
    owner = uuid.uuid4()
    return DigitalWorker(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_user_id=uuid.uuid4(),
        configuration=DwConfiguration(
            key="lead_care",
            name="Chăm sóc lead",
            mandate="m",
            work_kinds=("marketing.lead",),
            allowed_tools=("email.send", "mailbox.fetch_reply", "work.handoff"),
            workflow_key="lead_care",
            workflow_version="1.0.0",
            parameters={"sender_address": "dw@demo.local", "sales_assignee_id": str(SALES)},
            role_keys=frozenset({"member"}),
            decision_classes=(
                DecisionClass("email.send", "external", False, "A2", "A1"),
                DecisionClass("work.handoff", "internal", True, "A3", "A3"),
            ),
        ),
        people=DwPeople(owner, uuid.uuid4(), owner, uuid.uuid4()),
        state="operating",
        created_by=owner,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def context(dw: DigitalWorker) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=dw.tenant_id,
        workspace_id=dw.workspace_id,
        actor_id=uuid.uuid4(),
        worker_id="dw:lead_care",
        worker_version="1.0.0",
        channel="simulation",
        plan_id="p",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
    )


async def run(pinned: PinnedWorkflow, dw: DigitalWorker | None = None, **kw: Any) -> Any:
    dw = dw or worker()
    return await simulate(
        pinned,
        worker=dw,
        tools=Tools(),
        registry=REGISTRY,
        run_context=context(dw),
        clock=SystemClock(),
        recommendations={"step_failed": "Xem lại bước lỗi."},
        **kw,
    )


def with_steps(steps: list[Any]) -> PinnedWorkflow:
    raw = PINNED.document.model_dump(by_alias=True, exclude_none=True)
    return replace(PINNED, document=WorkflowDocument.model_validate({**raw, "steps": steps}))


async def test_the_pack_workflow_passes_and_records_the_send_without_sending() -> None:
    """R6.2 (WAI9): the approved lane runs; the send is recorded with the
    proposal as approved, and nothing could have sent it."""
    result = await run(PINNED)
    assert result.outcome == "passed", result
    tools = [c["tool"] for c in result.tool_calls]
    assert tools[:2] == ["email.send@1.0.0", "mailbox.fetch_reply@1.0.0"]
    send = result.tool_calls[0]
    assert send["decision_class"] == "email.send"
    assert set(send["input"]) == {"to", "subject", "body"}
    done = [e["step_id"] for e in result.trail if e["status"] == "done"]
    assert {"score", "draft", "send", "wait_reply", "fetch_reply"} <= set(done)


async def test_a_step_that_fails_makes_a_failed_simulation() -> None:
    """R6.9: the integer score as the recipient fails the tool's input model
    at the send, as the executor would; the result names the step."""
    steps = copy.deepcopy(PINNED.document.model_dump(by_alias=True)["steps"])
    steps[2]["config"]["proposal"]["to"] = "{{ steps.score.score }}"
    result = await run(with_steps(steps))
    assert result.outcome == "failed"
    assert result.failed_step == "send" and result.error


async def test_past_the_step_cap_is_failed() -> None:
    """R6.9: the step cap stops the run."""
    result = await run(PINNED, max_steps=3)
    assert (result.outcome, result.error) == ("failed", "step_limit")


async def test_bad_parameters_fail_before_anything_runs() -> None:
    """R6.9: a DW whose parameters the document refuses."""
    dw = worker()
    dw = replace(dw, configuration=replace(dw.configuration, parameters={}))
    result = await run(PINNED, dw)
    assert result.outcome == "failed" and result.tool_calls == ()


def test_samples_meet_their_schema() -> None:
    assert sample_of({"type": "string", "format": "email"}) == "mau@vi-du.vn"
    assert sample_of({"type": "number", "minimum": 0, "maximum": 1}) == 1.0
    assert sample_of({"type": "string", "enum": ["A", "B"]}) == "A"
    assert sample_of({"type": "array", "minItems": 1, "items": {"type": "integer"}}) == [0]
    assert len(sample_of({"type": "string", "minLength": 10, "maxLength": 12})) == 10
