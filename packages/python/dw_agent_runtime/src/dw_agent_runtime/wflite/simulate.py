"""A dry run of a workflow draft (wf-ai R6.2, R6.9; WAI9).

The draft is compiled by the same builder a run uses (`compile_workflow`), so
the simulation exercises the graph that would go live: its lanes, its joins,
its references and its gates. What would reach outside is replaced:

- every `tool.call` checks its input against the tool's input model, as the
  executor does first, records it and answers a sample of the tool's output
  schema; `ToolExecutor` is never called, so nothing is sent;
- every `ai.llm` answers a sample of its step's `output_schema` with full
  confidence, and no model is called (decided 2/11/2026: a simulation checks
  the path through the tree and its gates; the wording is the eval's);
- every `human.approval` approves its proposal as proposed;
- every `time.wait` is resumed at once.

A step that fails, or a run past `max_steps`, is `failed`, with the step and
its reason; nothing about a failed simulation is `passed` (R6.9).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from pydantic import BaseModel

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import DecisionCall
from dw_agent_runtime.ports import ModelRequest
from dw_agent_runtime.samples import SampleOutput, sample_of
from dw_agent_runtime.wflite.catalog import PinnedWorkflow
from dw_agent_runtime.wflite.compile import ToolModelsPort, WfPorts, compile_workflow
from dw_agent_runtime.wflite.document import Step
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.starter import checked_parameters
from dw_kernel.errors import DWError
from dw_kernel.ports import UtcClock
from dw_platform.application.decision_gate import Auto
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.digital_worker import DigitalWorker

MAX_STEPS = 200
# How many waits one simulation resumes before it calls the run endless.
_MAX_RESUMES = 100


@dataclass
class _Executor:
    """Records what each tool would have been given; sends nothing."""

    tools: ToolModelsPort
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def execute(
        self,
        *,
        name: str,
        version: str,
        raw_input: dict[str, object],
        run_context: RunContext,
        idempotency_key: str | None = None,
        approved: bool = False,
        decision: DecisionCall | None = None,
    ) -> BaseModel:
        tool = self.tools.resolve(name, version, tenant_id=None)
        # What the executor's input step does: an input the tool's schema
        # refuses fails here as it would fail live.
        tool.behaviour.validate_input(raw_input)
        self.calls.append(
            {
                "tool": f"{name}@{version}",
                "input": raw_input,
                "decision_class": decision.decision_class if decision else None,
            }
        )
        output = tool.behaviour.output_schema()
        return SampleOutput.model_validate(sample_of(output))


@dataclass(frozen=True)
class _Gateway:
    """Answers each `ai.llm` step with a sample of its own output schema."""

    schemas: Mapping[str, Mapping[str, Any]]

    async def generate_structured(
        self, request: ModelRequest, output_type: type[Any], *, run_context: RunContext
    ) -> Any:
        step_id = request.task.removeprefix("wflite.")
        return output_type.model_validate(sample_of(self.schemas[step_id]))


class _Gate:
    """Every approval approves its proposal as proposed."""

    async def check(self, scope: WorkScope, dw_id: uuid.UUID, **_: Any) -> Auto:
        return Auto(effective_level="A4")


@dataclass
class _HandOffs:
    packets: list[Mapping[str, object]] = field(default_factory=list)

    async def hand_off(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        to_user: uuid.UUID,
        packet: Mapping[str, object],
    ) -> None:
        self.packets.append(packet)


@dataclass(frozen=True)
class _Workers:
    worker: DigitalWorker

    async def digital_worker(self, scope: WorkScope, dw_id: uuid.UUID) -> DigitalWorker | None:
        return self.worker


@dataclass(frozen=True, slots=True)
class SimulationResult:
    outcome: Literal["passed", "failed"]
    trail: tuple[Mapping[str, Any], ...]
    tool_calls: tuple[Mapping[str, Any], ...]
    failed_step: str | None
    error: str | None


def _llm_schemas(steps: Sequence[Step], registry: Mapping[str, NodeTypeSpec]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for step in steps:
        if step.type == "ai.llm@1":
            found[step.id] = step.config.get("output_schema") or {"type": "object"}
        spec = registry.get(step.type)
        for lane in (spec.lanes(step.config) if spec else {}).values():
            found.update(_llm_schemas([Step.model_validate(raw) for raw in lane], registry))
    return found


def _work_sample(pinned: PinnedWorkflow) -> dict[str, Any]:
    kind = next(
        (t.config.get("kind") for t in pinned.document.triggers if t.config.get("kind")), None
    )
    schema = pinned.work_schemas.get(str(kind)) or {"type": "object"}
    examples = schema.get("examples")
    if isinstance(examples, list) and examples and isinstance(examples[0], Mapping):
        return dict(examples[0])
    sampled = sample_of(schema)
    return sampled if isinstance(sampled, dict) else {}


def _failed(trail: Sequence[Mapping[str, Any]], error: str) -> SimulationResult:
    last = next((e for e in reversed(trail) if e.get("status") in {"failed", "handed_off"}), None)
    return SimulationResult(
        "failed",
        tuple(trail),
        (),
        str(last["step_id"]) if last else "(start)",
        error,
    )


async def simulate(
    pinned: PinnedWorkflow,
    *,
    worker: DigitalWorker,
    tools: ToolModelsPort,
    registry: Mapping[str, NodeTypeSpec],
    run_context: RunContext,
    clock: UtcClock,
    recommendations: Mapping[str, str],
    max_steps: int = MAX_STEPS,
) -> SimulationResult:
    executor, handoffs = _Executor(tools), _HandOffs()
    ports = WfPorts(
        gateway=_Gateway(_llm_schemas(pinned.document.steps, registry)),
        executor=executor,
        tools=tools,
        gate=_Gate(),
        queue=handoffs,
        workers=_Workers(worker),
        clock=clock,
        recommendations=recommendations,
    )
    try:
        params = checked_parameters(pinned.document.variables, worker.configuration.parameters)
    except DWError as exc:
        return _failed([], str(exc.details.get("reason_code", exc.code)))
    graph: Any = compile_workflow(pinned, ports).compile(checkpointer=InMemorySaver())
    config: Any = {
        "configurable": {"thread_id": str(uuid.uuid4())},
        "recursion_limit": max_steps,
    }
    context = run_context.model_copy(update={"definition_hash": pinned.sha256})
    payload: Any = {
        "work": _work_sample(pinned),
        "params": params,
        "dw_id": str(worker.id),
        "work_item_id": str(uuid.uuid4()),
        "definition_hash": pinned.sha256,
        "trail": [],
    }
    state: Mapping[str, Any] = {}
    try:
        for _ in range(_MAX_RESUMES):
            state = await graph.ainvoke(payload, config, context=context)
            snapshot = await graph.aget_state(config)
            if not snapshot.next:
                break
            payload = Command(resume={"woke_at": clock.now().isoformat(), "approved": True})
        else:
            return _failed(list(state.get("trail") or []), "step_limit")
    except GraphRecursionError:
        return _failed(list(state.get("trail") or []), "step_limit")
    trail = list(state.get("trail") or [])
    if handoffs.packets or state.get("handed_off"):
        problem = str(handoffs.packets[-1].get("problem", "")) if handoffs.packets else ""
        return _failed(trail, problem or "handed_off")
    return SimulationResult("passed", tuple(trail), tuple(executor.calls), None, None)


__all__ = ["MAX_STEPS", "SimulationResult", "sample_of", "simulate"]
