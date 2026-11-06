"""A pinned `dw.workflow/v1` document, compiled once into a StateGraph (wf-lite
R5, R6; ADR-0112 decision 4).

The tree becomes the graph: each list a chain, each block (an approval, a
switch) a node whose lanes are entered by a conditional edge and meet again at
a join node after the block. The lanes are the regions of the document's
`WorkflowIR` (`wflite.ir.lower`), the one lowering the validator checks, so
the tree compiled is the tree checked (workflow-engine R2.12). State has one
channel per step, `out__<id>`, the work item's payload under `work`, the DW's
parameters under `params`, the pinned document hash, and `trail`, one id-only
entry per node run.

Every node runs inside one wrapper, the only place a step's failure becomes
something else:

- a document whose bytes changed since the run pinned them hands the work off
  (`definition_changed`, R6.19), running nothing;
- LangGraph's pause signal (`GraphBubbleUp`, which `interrupt()` raises)
  passes through untouched (R6.18): a wait is not a failure;
- any other error hands the work to the DW's Validator with a four-field
  packet (R6.18, R6.20), and nothing after it runs.

A wait is `interrupt()` on the first line of its own node, so a resumed node
repeats nothing before it: an approval is two nodes, the gate that asks
`DecisionGate` (and may let the DW decide alone), then the wait.

A Studio run (workflow-engine/03) compiles through the same lowering and the
same chains, joins and node names, with its own wrapper: each step's node is
a `StudioNode` (`wflite.node_wrapper`) running its type's `body` through the
door its type declares, a block's lanes are entered by the port its body
answers (`port__<id>`), and a step's error lane by `err__<id>`, both meeting
at `join__<id>`; a step whose type `ends_run` goes to the end. The graph is a
function of the document and `COMPILER_VERSION` only: what a run pinned (its
manifest, its mode, its pinned results) reaches the nodes at run time through
the run's context, so two runs of one version share one compiled graph. A
pack's run keeps everything above, and reads no `retry`, `timeout_s` or
`on_error`, which `PACK_RULES` refuses anyway.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from itertools import pairwise
from typing import Annotated, Any, Final, Protocol, TypedDict, cast
from uuid import UUID

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict

from dw_agent_runtime.contracts import RunContext, WorkerDefinition
from dw_agent_runtime.executor import DecisionCall
from dw_agent_runtime.ports import ModelGateway, ModelOutputInvalidError, ModelRequest
from dw_agent_runtime.run_control import RunHaltedError
from dw_agent_runtime.tools import ToolBehaviour
from dw_agent_runtime.wflite.catalog import PinnedWorkflow
from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.ir import ERROR_LANE, lower
from dw_agent_runtime.wflite.node_wrapper import (
    ERROR_PORT,
    StudioNode,
    StudioNodePorts,
    port_label,
    wait_channel,
    wait_node,
)
from dw_agent_runtime.wflite.registry import KeyedPorts, NodeTypeSpec, build_node_registry
from dw_kernel.errors import ConfigError, DWError
from dw_kernel.ids import TenantId
from dw_kernel.ports import UtcClock
from dw_platform.application.decision_gate import AskPerson, Auto
from dw_platform.application.json_schema import problems
from dw_platform.application.work_queue import DwLookupPort, WorkScope

WORKER_PREFIX = "dw:"
_MAX_FIELD = 4000
# Raised whenever the way a document becomes a graph changes: a Studio graph is
# cached under it, so a process never runs a graph built the old way (R4.2).
COMPILER_VERSION: Final = "1"


def worker_id_of(key: str) -> str:
    return f"{WORKER_PREFIX}{key}"


class ToolExecutionPort(Protocol):
    """The one door a `tool.call` node goes through: `ToolExecutor` in a run,
    a recorder in a simulation (wf-ai R6.2)."""

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
    ) -> BaseModel: ...


class ToolModels(Protocol):
    """A registered tool as a node reads it: how it checks what it takes and
    gives (`ToolBehaviour`)."""

    @property
    def behaviour(self) -> ToolBehaviour: ...


class ToolModelsPort(Protocol):
    """The tool register as nodes read it: `ToolRegistry`, its platform layer
    (`tenant_id=None`): a pinned workflow's tools are the platform's."""

    def resolve(self, name: str, version: str, *, tenant_id: TenantId | None) -> ToolModels: ...


class DecisionGatePort(Protocol):
    """What an approval node asks: `DecisionGate` in a run."""

    async def check(
        self,
        scope: WorkScope,
        dw_id: UUID,
        *,
        decision_class: str,
        proposal: Mapping[str, Any],
        proposal_schema: Mapping[str, Any],
        locked_fields: Sequence[str],
        reason: str,
        run_id: UUID | None = None,
        step_id: str | None = None,
    ) -> Auto | AskPerson: ...


class HandOffPort(Protocol):
    """Where a failed step hands its work: `WorkQueue` in a run."""

    async def hand_off(
        self,
        scope: WorkScope,
        item_id: UUID,
        *,
        to_user: UUID,
        packet: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True)
class WfPorts:
    """What the nodes of every compiled workflow use, built once at the
    composition root."""

    gateway: ModelGateway
    executor: ToolExecutionPort
    tools: ToolModelsPort
    gate: DecisionGatePort
    queue: HandOffPort
    workers: DwLookupPort
    clock: UtcClock
    # The sentence a hand-off recommends, by code (configs/copy/wflite_handoff.yaml).
    recommendations: Mapping[str, str]


class _AnyObject(BaseModel):
    """What the gateway parses a model's answer into; the step's own JSON
    Schema is checked after (R5.1)."""

    model_config = ConfigDict(extra="allow")


class StepHandedOff(Exception):  # noqa: N818 - a control signal, like ReplayedResponse
    """Raised by a node to end the run by handing the work to a person."""

    def __init__(self, code: str, output: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.output = output


# ----------------------------------------------------------------- refs --


def _resolve(value: Any, state: Mapping[str, Any]) -> Any:
    """A config value with every reference replaced by what it names. A
    reference is a whole string (the validator held that, R3.7)."""
    if isinstance(value, Mapping):
        return {k: _resolve(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, state) for v in value]
    if isinstance(value, str) and value.strip().startswith("{{"):
        inner = value.strip()[2:-2].strip()
        root, _, rest = inner.partition(".")
        name, _, field = rest.partition(".")
        if root == "work":
            return (state.get("work") or {}).get(name)
        if root == "params":
            return (state.get("params") or {}).get(name)
        return (state.get(f"out__{name}") or {}).get(field)
    return value


# ------------------------------------------------------------- the graph --


@dataclass(frozen=True)
class StudioWorkflow:
    """A Studio run's pinned document: the root version's content read where
    the run is taken, its pinned hash, and the registry it is compiled with."""

    document: WorkflowDocument
    pinned_hash: str
    registry: Mapping[str, NodeTypeSpec]


class _Builder:
    def __init__(self, pinned: PinnedWorkflow, ports: WfPorts) -> None:
        self.pinned = pinned
        self.ports = ports
        self._lower(pinned.document, build_node_registry())
        channels: dict[str, Any] = {
            "work": dict,
            "params": dict,
            "dw_id": str,
            "work_item_id": str,
            "definition_hash": str,
            "handed_off": bool,
            "trail": Annotated[list, operator.add],
        }
        for step in self.steps:
            channels[f"out__{step.id}"] = dict
            if step.type == "human.approval@1":
                channels[f"ask__{step.id}"] = dict
        self._graph_of(channels)

    def _lower(self, document: WorkflowDocument, registry: Mapping[str, NodeTypeSpec]) -> None:
        self.registry: Mapping[str, NodeTypeSpec] = registry
        self.ir = lower(document, registry)
        # A pinned document passed the validator, so its ids are unique.
        self._index = {placed.step.id: placed.index for placed in self.ir.steps}
        self.steps: list[Step] = [placed.step for placed in self.ir.steps]

    def _graph_of(self, channels: dict[str, Any]) -> None:
        self.state = TypedDict("WorkflowState", channels, total=False)  # type: ignore[misc]
        self.graph: StateGraph = StateGraph(self.state)  # type: ignore[type-arg]

    def _lanes(self, step: Step) -> dict[str, list[Step]]:
        """The steps of each lane of `step`, by port, from the IR."""
        return self.ir.lanes_of(self._index[step.id])

    # A chain of steps from `entry` ends at `exit`; returns the first node.
    def chain(self, steps: Sequence[Step], exit_node: str) -> str:
        if not steps:
            return exit_node
        nodes = [self._block(step) for step in steps]
        # Each block's last node goes to the next block's first node, and the
        # last one to `exit`; a step that ends the run goes to the end.
        for step, ((_, last), (first, _)) in zip(steps, pairwise(nodes), strict=False):
            self._edge(last, END if self._ends(step) else first)
        self._edge(nodes[-1][1], END if self._ends(steps[-1]) else exit_node)
        return nodes[0][0]

    def _ends(self, step: Step) -> bool:
        """No pack type ends the run (wf-lite R2.1)."""
        return False

    def _edge(self, source: str, target: str) -> None:
        """An edge that ends the run once the work is handed off."""

        def route(state: Mapping[str, Any]) -> str:
            return END if state.get("handed_off") else target

        self.graph.add_conditional_edges(source, route, [target, END])

    def _block(self, step: Step) -> tuple[str, str]:
        """Add `step` (and its lanes); return its first and last node."""
        if step.type == "human.approval@1":
            return self._approval(step)
        if step.type == "logic.switch@1":
            return self._switch(step)
        self.graph.add_node(step.id, self._wrap(step, self._simple(step)))
        return step.id, step.id

    def _approval(self, step: Step) -> tuple[str, str]:
        ask, wait, join = f"{step.id}", f"wait__{step.id}", f"join__{step.id}"
        lanes = self._lanes(step)
        self.graph.add_node(ask, self._wrap(step, self._ask(step)))
        self.graph.add_node(wait, self._wrap(step, self._wait_decision(step), trail=False))
        self.graph.add_node(join, _noop)
        approved = self.chain(lanes.get("approved", []), join)
        rejected = self.chain(lanes.get("rejected", []), join)

        def after_ask(state: Mapping[str, Any]) -> str:
            if state.get("handed_off"):
                return END
            # The DW decided alone: no wait, straight to the approved lane.
            return wait if state.get(f"ask__{step.id}") else approved

        self.graph.add_conditional_edges(ask, after_ask, sorted({wait, approved, END}))

        def after_wait(state: Mapping[str, Any]) -> str:
            if state.get("handed_off"):
                return END
            return approved if (state.get(f"out__{step.id}") or {}).get("approved") else rejected

        self.graph.add_conditional_edges(wait, after_wait, sorted({approved, rejected, END}))
        return ask, join

    def _switch(self, step: Step) -> tuple[str, str]:
        join = f"join__{step.id}"
        self.graph.add_node(step.id, self._wrap(step, self._choose(step)))
        self.graph.add_node(join, _noop)
        targets = {port: self.chain(lane, join) for port, lane in self._lanes(step).items()}

        def route(state: Mapping[str, Any]) -> str:
            if state.get("handed_off"):
                return END
            case = str((state.get(f"out__{step.id}") or {}).get("case"))
            return targets.get(f"cases.{case}", targets.get("default", join))

        self.graph.add_conditional_edges(step.id, route, sorted({*targets.values(), join, END}))
        return step.id, join

    # ---------------------------------------------------------- the nodes --

    def _simple(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        if step.type == "ai.llm@1":
            return self._llm(step)
        if step.type == "tool.call@1":
            return self._tool(step)
        if step.type == "time.wait@1":
            return self._timer(step)
        raise DWError(f"no node for {step.type}")

    def _llm(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        config = step.config
        prompt_id, _, prompt_version = str(config["prompt"]).partition("@")
        schema = config["output_schema"]
        floor_ref = config.get("min_confidence")

        async def node(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            inputs = _resolve(config["inputs"], state)
            request = ModelRequest(
                task=f"wflite.{step.id}",
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                variables={
                    k: v if isinstance(v, str) else json.dumps(v) for k, v in inputs.items()
                },
                # The model is asked in the step's own schema; `_AnyObject`
                # only parses, and `problems` checks the answer after.
                output_schema=schema,
            )
            try:
                answer = await self.ports.gateway.generate_structured(
                    request, _AnyObject, run_context=runtime.context
                )
            except ModelOutputInvalidError as exc:
                raise StepHandedOff("model_output_invalid") from exc
            output = answer.model_dump()
            if problems(schema, output):
                raise StepHandedOff("model_output_invalid", output)
            floor = _resolve(floor_ref, state)
            if floor is not None and float(output.get("confidence", 0)) < float(floor):
                raise StepHandedOff("low_confidence", output)
            return {f"out__{step.id}": output}

        return node

    def _tool(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        config = step.config
        name, _, version = str(config["tool"]).partition("@")
        gate = self._gate_of(step)

        async def node(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            run = runtime.context
            raw_input = _resolve(config["input"], state)
            approval_id = None
            if gate is not None:
                found = (state.get(f"out__{gate}") or {}).get("approval_id")
                approval_id = UUID(found) if isinstance(found, str) else None
            result = await self.ports.executor.execute(
                name=name,
                version=version,
                raw_input=dict(raw_input) if isinstance(raw_input, Mapping) else {},
                run_context=run,
                idempotency_key=f"wf:{run.run_id}:{step.id}:",
                decision=DecisionCall(
                    decision_class=str(config["decision_class"]),
                    gate_step_id=gate,
                    approval_id=approval_id,
                ),
            )
            output = result.model_dump(mode="json")
            # `result` whole, and its top-level fields beside it, which the
            # validator lets a step reference when the tool declares them.
            return {f"out__{step.id}": {**output, "result": output}}

        return node

    def _timer(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        config = step.config

        async def node(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            seconds = config.get("seconds") or (state.get("params") or {}).get(
                str(config.get("seconds_param"))
            )
            wake_at = self.ports.clock.now() + timedelta(seconds=int(seconds or 0))
            woke = interrupt({"wait": "timer", "wake_at": wake_at.isoformat()})
            return {f"out__{step.id}": {"woke_at": str((woke or {}).get("woke_at", ""))}}

        return node

    def _choose(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        on = step.config["on"]

        async def node(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            value = _resolve(on, state)
            case = json.dumps(value) if isinstance(value, bool) else str(value)
            return {f"out__{step.id}": {"case": case}}

        return node

    def _ask(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        config = step.config
        proposal_schema = self._proposal_schema(step)

        async def node(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            run = runtime.context
            proposal = _resolve(config["proposal"], state)
            answer = await self.ports.gate.check(
                WorkScope(tenant_id=run.tenant_id, workspace_id=run.workspace_id),
                UUID(str(state["dw_id"])),
                decision_class=str(config["decision_class"]),
                proposal=proposal if isinstance(proposal, Mapping) else {"value": proposal},
                proposal_schema=proposal_schema,
                locked_fields=list(config.get("locked_fields") or []),
                reason=step.description or step.id,
                run_id=run.run_id,
                step_id=step.id,
            )
            if isinstance(answer, AskPerson):
                return {f"ask__{step.id}": dict(answer.payload)}
            return {
                f"ask__{step.id}": {},
                f"out__{step.id}": {"proposal": proposal, "approved": True, "comment": ""},
            }

        return node

    def _wait_decision(self, step: Step) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def node(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            decision = interrupt(state[f"ask__{step.id}"])
            asked = state[f"ask__{step.id}"]
            edited = decision.get("edited_proposal")
            approved = bool(decision.get("approved"))
            return {
                f"out__{step.id}": {
                    # What was approved, edited or as asked (R6.10, D18).
                    "proposal": edited if edited is not None else asked.get("proposal"),
                    "approved": approved,
                    "comment": str(decision.get("comment", "")),
                    "approval_id": decision.get("approval_id"),
                }
            }

        return node

    def _gate_of(self, step: Step) -> str | None:
        """The approval whose approved lane holds `step` with its class."""

        def search(steps: Sequence[Step], gates: tuple[tuple[str, str], ...]) -> str | None:
            for s in steps:
                if s.id == step.id:
                    match = [g for g, cls in gates if cls == step.config.get("decision_class")]
                    return match[-1] if match else None
                for port, lane in self._lanes(s).items():
                    inner = gates
                    if s.type == "human.approval@1" and port == "approved":
                        inner = (*gates, (s.id, str(s.config.get("decision_class"))))
                    found = search(lane, inner)
                    if found is not None:
                        return found
            return None

        return search(self.pinned.document.steps, ())

    def _proposal_schema(self, step: Step) -> dict[str, Any]:
        """R6.21: the input schema of the tool its approved lane calls for its
        class, computed here, never declared by the document."""
        cls = step.config.get("decision_class")

        def find(steps: Sequence[Step]) -> dict[str, Any] | None:
            for s in steps:
                if s.type == "tool.call@1" and s.config.get("decision_class") == cls:
                    name, _, version = str(s.config["tool"]).partition("@")
                    tool = self.ports.tools.resolve(name, version, tenant_id=None)
                    return tool.behaviour.input_schema()
                for lane in self._lanes(s).values():
                    found = find(lane)
                    if found is not None:
                        return found
            return None

        return find(self._lanes(step).get("approved", [])) or {"type": "object"}

    # -------------------------------------------------------- the wrapper --

    def _wrap(
        self, step: Step, impl: Callable[..., Awaitable[dict[str, Any]]], *, trail: bool = True
    ) -> Callable[..., Awaitable[dict[str, Any]]]:
        sha = self.pinned.sha256

        async def wrapped(state: Mapping[str, Any], runtime: Runtime[RunContext]) -> dict[str, Any]:
            if state.get("handed_off"):
                return {}
            if state.get("definition_hash") != sha:
                return await self._hand_off(state, runtime, step, "definition_changed", None)
            try:
                update = await impl(state, runtime)
            except (GraphBubbleUp, RunHaltedError):
                # A door refusing the run (agent-lifecycle R7.1) ends the run,
                # cancelled by the runner: never a hand-off of this step.
                raise
            except StepHandedOff as stop:
                return await self._hand_off(state, runtime, step, stop.code, stop.output)
            except Exception as exc:
                code = (
                    str(exc.details.get("reason_code", exc.code))
                    if isinstance(exc, DWError)
                    else "step_failed"
                )
                return await self._hand_off(state, runtime, step, code, None, failed=True)
            if trail:
                update["trail"] = [self._entry(step, "done")]
            return update

        return wrapped

    def _entry(self, step: Step, status: str) -> dict[str, str]:
        return {
            "step_id": step.id,
            "type": step.type,
            "status": status,
            "at": self.ports.clock.now().isoformat(),
        }

    async def _hand_off(
        self,
        state: Mapping[str, Any],
        runtime: Runtime[RunContext],
        step: Step,
        code: str,
        output: Mapping[str, Any] | None,
        *,
        failed: bool = False,
    ) -> dict[str, Any]:
        """R6.20: problem, context, tried and recommendation, none empty, to the
        DW's Validator."""
        run = runtime.context
        scope = WorkScope(tenant_id=run.tenant_id, workspace_id=run.workspace_id)
        entry = self._entry(step, "failed" if failed else "handed_off")
        trail = [*list(state.get("trail") or []), entry]
        done = [e["step_id"] for e in trail if e.get("status") == "done"]
        context: dict[str, Any] = {"trail": trail}
        if output is not None:
            context["output"] = dict(output)
        worker = await self.ports.workers.digital_worker(scope, UUID(str(state["dw_id"])))
        if worker is None:
            raise DWError("the digital worker of this run is gone")
        await self.ports.queue.hand_off(
            scope,
            UUID(str(state["work_item_id"])),
            to_user=worker.people.validator_id,
            packet={
                "problem": f"{code} at {step.id}"[:_MAX_FIELD],
                "context": json.dumps(context, ensure_ascii=False, default=str)[:_MAX_FIELD],
                "tried": (", ".join(done) or "(none)")[:_MAX_FIELD],
                "recommendation": self.ports.recommendations.get(
                    code, self.ports.recommendations.get("step_failed", code)
                )[:_MAX_FIELD],
            },
        )
        return {"handed_off": True, "trail": [entry]}


async def _noop(state: Mapping[str, Any]) -> dict[str, Any]:
    return {}


def studio_channels(steps: Sequence[Step], registry: Mapping[str, NodeTypeSpec]) -> dict[str, Any]:
    """The state channels of a Studio graph, by name: what `_StudioBuilder`
    builds the graph with and what `state_schema` hashes, so the two never
    disagree (R6.7 (c))."""
    channels: dict[str, Any] = {"work": dict, "trail": Annotated[list, operator.add]}
    for step in steps:
        channels[f"out__{step.id}"] = dict
        channels[f"port__{step.id}"] = str
        channels[f"err__{step.id}"] = bool
        spec = registry.get(step.type)
        if spec is not None and spec.wait is not None:
            channels[wait_channel(step.id)] = dict
    return channels


def _channel_label(kind: Any) -> str:
    """A channel's type as text: its class, and its reducer when it has one."""
    metadata = getattr(kind, "__metadata__", ())
    origin = getattr(kind, "__origin__", kind)
    label = getattr(origin, "__name__", str(origin))
    reducers = [getattr(m, "__name__", str(m)) for m in metadata]
    return "+".join([label, *reducers])


def state_schema(
    document: WorkflowDocument, registry: Mapping[str, NodeTypeSpec]
) -> dict[str, str]:
    """The names and types of the channels the compiler builds for
    `document` (ADR-0109 decision 8 (c)): what the manifest's
    `state_schema_hash` hashes when a run is pinned and when it resumes."""
    steps = [placed.step for placed in lower(document, registry).steps]
    return {name: _channel_label(kind) for name, kind in studio_channels(steps, registry).items()}


class _StudioBuilder(_Builder):
    """The same lowering, chains and node names as a pack's, with a Studio
    run's wrapper and routing (workflow-engine/03). A step whose type waits
    (`NodeTypeSpec.wait`, workflow-engine/05) is two nodes: its own, which
    opens the wait, then `wait__<id>`, whose first line is `interrupt()`; its
    lanes leave from the second."""

    def __init__(self, workflow: StudioWorkflow, ports: StudioNodePorts) -> None:
        self.workflow = workflow
        self.studio = ports
        self._lower(workflow.document, workflow.registry)
        self._graph_of(studio_channels(self.steps, self.registry))

    def _spec(self, step: Step) -> NodeTypeSpec:
        spec = self.registry.get(step.type)
        # Parallel lanes and loops are workflow-engine/06's; a type with
        # neither a body nor a wait cannot run in a Studio run.
        if (
            spec is None
            or (spec.body is None and spec.wait is None)
            or spec.block in ("parallel", "loop")
        ):
            raise ConfigError(
                "this step type cannot run in a Studio run yet",
                details={"reason_code": "step_type_unavailable", "type": step.type},
            )
        return spec

    def _ends(self, step: Step) -> bool:
        return self._spec(step).ends_run

    def _edge(self, source: str, target: str) -> None:
        self.graph.add_edge(source, target)

    def _lane_path(self, step: Step) -> tuple[tuple[str, str], ...]:
        path = [
            (parent.step.id, ERROR_PORT if port == ERROR_LANE else (port_label(port) or port))
            for parent, port in self.ir.ancestors(self._index[step.id])
        ]
        return tuple(reversed(path))

    def _block(self, step: Step) -> tuple[str, str]:
        spec = self._spec(step)
        lanes = self._lanes(step)
        # The error lane as the IR lowered it; None when the step has none.
        errors = self.ir.lanes_of(self._index[step.id], errors=True).get(ERROR_LANE)
        default = spec.ports.default if isinstance(spec.ports, KeyedPorts) else None
        fallback = default.name if default is not None and default.name in lanes else None

        def lane_taken(port: str | None) -> str | None:
            """The lane a body's port names, or the type's default lane."""
            return port if port in lanes else fallback

        studio_node = StudioNode(
            step=step,
            spec=spec,
            lane_path=self._lane_path(step),
            ports=self.studio,
            resolve=_resolve,
            has_error_lane=errors is not None,
            lane_taken=lane_taken,
        )
        tail = step.id
        if spec.wait is not None:
            tail = wait_node(step.id)
            opens: Callable[..., Awaitable[dict[str, Any]]] = studio_node.open_wait
            resumes: Callable[..., Awaitable[dict[str, Any]]] = studio_node.resume_wait
            self.graph.add_node(step.id, opens)
            self.graph.add_node(tail, resumes)
            self.graph.add_edge(step.id, tail)
        else:
            node: Callable[..., Awaitable[dict[str, Any]]] = studio_node.__call__
            self.graph.add_node(step.id, node)
        if not lanes and errors is None and spec.block == "none":
            return step.id, tail
        join = f"join__{step.id}"
        self.graph.add_node(join, _studio_join(step.id))
        targets = {port: self.chain(lane, join) for port, lane in lanes.items()}
        error_entry = self.chain(errors, join) if errors is not None else None

        def route(state: Mapping[str, Any]) -> str:
            if error_entry is not None and state.get(f"err__{step.id}"):
                return error_entry
            return targets.get(str(state.get(f"port__{step.id}") or ""), join)

        destinations = {*targets.values(), join}
        if error_entry is not None:
            destinations.add(error_entry)
        self.graph.add_conditional_edges(tail, route, sorted(destinations))
        return step.id, join


def _studio_join(step_id: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    """A Studio join leaves a trail entry, so a golden trace sees it fire."""

    async def join(state: Mapping[str, Any]) -> dict[str, Any]:
        return {"trail": [{"step_id": f"join__{step_id}", "status": "join"}]}

    return join


def compile_workflow(
    pinned: PinnedWorkflow | StudioWorkflow, ports: WfPorts | StudioNodePorts
) -> StateGraph:  # type: ignore[type-arg]
    """R6.1: the uncompiled StateGraph of one pinned document: a pack's with
    the pack's nodes, a Studio run's with the Studio wrapper."""
    builder: _Builder
    if isinstance(pinned, StudioWorkflow):
        if not isinstance(ports, StudioNodePorts):
            raise TypeError("a Studio workflow compiles with StudioNodePorts")
        builder = _StudioBuilder(pinned, ports)
    else:
        builder = _Builder(pinned, cast(WfPorts, ports))
    first = builder.chain(pinned.document.steps, END)
    builder.graph.add_edge(START, first)
    return builder.graph


def worker_definition_of(pinned: PinnedWorkflow) -> WorkerDefinition:
    """The worker a pinned document runs as: `dw:<key>` at its version. A0,
    because every effect of a workflow goes through its decision class's gate
    (`DecisionCall`), and anything that does not reaches nothing unasked.
    A tenant's version runs at its `run_version` (wf-ai R6.5)."""
    version = pinned.version
    return WorkerDefinition(
        worker_id=worker_id_of(pinned.key),
        worker_version=pinned.run_version,
        domain="dw",
        graph_version=pinned.run_version,
        prompt_bundle_version=version,
        policy_version=version,
        memory_policy_version=version,
        default_model_profile="balanced",
        supported_channels=frozenset({"dw_work"}),
        autonomy_level="A0",
        recursion_limit=200,
    )
