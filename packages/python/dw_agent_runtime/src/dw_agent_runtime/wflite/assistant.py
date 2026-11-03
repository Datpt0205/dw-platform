"""The assistant that edits a Digital Worker's template workflow (wf-ai R1-R5;
D16 (3), D18 (4)).

One turn: the owner of a DW says what they want changed, and the model answers
with a question back, or with a plan and a new step tree. The model writes the
steps and nothing else: the proposal is the base document with its `steps`
replaced (R2.1), checked by the one validator of wf-lite with the base's own
registry, tools and kinds (R3.1), and by two checks of its own: no tool and no
prompt the pack's workflow does not already use (R2.2, R2.3). A proposal is
`publishable` only when nothing is wrong. Nothing is stored here: saving,
simulating and publishing are wf-ai tickets 02 and 03.

Who may ask is who may change the DW (R1.2), checked before the model is
called, and the base is read from the DW's own pin, never from the request
(R1.3). What the person typed, the history and the base document reach the
prompt only as `<input>` blocks (R5.1, ADR-0010).
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ModelGateway, ModelRequest
from dw_agent_runtime.wflite.assistant_wire import OutputSchemas, WireStep, from_wire, to_wire
from dw_agent_runtime.wflite.catalog import PinnedWorkflow
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.outline import OutlineStep, StepChange, diff_steps, outline
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.validate import Problem, ToolSpecLookup, validate
from dw_agent_runtime.wflite.versions import PinnedWorkflowsPort, not_shipped
from dw_kernel.errors import DomainError
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.digital_worker import DigitalWorker

PROMPT_ID = "wf_ai.workflow_edit"
PROMPT_VERSION = "1.1.0"
MAX_TEXT = 4000
MAX_HISTORY = 10


class AssistantTurn(BaseModel):
    """What the model may answer, and nothing else (R2.4): a question back, or
    a plan with a step tree. An extra field, a question carrying steps or a
    proposal without them is not this shape (R1.7), and the gateway's retries
    end in `ModelOutputInvalidError` (R1.5). The steps are in the wire form
    strict structured output can send (`assistant_wire`, wf-ai/05)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["question", "proposal"]
    question: str | None = Field(default=None, max_length=1000)
    plan: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=8)
    steps: list[WireStep] | None = None

    @model_validator(mode="after")
    def _shape(self) -> AssistantTurn:
        if self.kind == "question" and (not self.question or self.steps is not None):
            raise ValueError("a question carries its question and no steps")
        if self.kind == "proposal" and not self.steps:
            raise ValueError("a proposal carries a non-empty step tree")
        return self


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    kind: Literal["question", "proposal"]
    question: str | None
    plan: tuple[str, ...]
    steps: tuple[dict[str, Any], ...] | None
    diff: tuple[StepChange, ...]
    problems: tuple[Problem, ...]
    publishable: bool
    # The proposed tree as `outline` reads a pinned one (R4.1, R7.1); empty
    # for a question, or for steps no document can be read from.
    outline: tuple[OutlineStep, ...] = ()


class DwOwnerPort(Protocol):
    async def require_owner(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        """The DW for its Business or Technical Owner: 404 for one the caller
        may not read, 403 `not_dw_owner` for anyone else (digital-worker R1.6)."""
        ...


# The trusted run context of the one call the turn makes, built from the
# caller's verified access context (`ApiContainer.run_context_for`).
RunContextFactory = Callable[[AccessContext, uuid.UUID], RunContext]


def _too_long(instruction: str, history: Sequence[HistoryTurn]) -> bool:
    return (
        len(instruction) > MAX_TEXT
        or len(history) > MAX_HISTORY
        or any(len(turn.text) > MAX_TEXT for turn in history)
    )


def _raw_steps(
    steps: Sequence[Any], registry: Mapping[str, NodeTypeSpec], path: str = "steps"
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every step dict of a raw tree with its path, lanes included; what is not
    a step dict is the validator's to report, not this walk's to guess."""
    for i, raw in enumerate(steps):
        if not isinstance(raw, Mapping):
            continue
        here = f"{path}/{i}"
        yield here, raw
        spec = registry.get(str(raw.get("type")))
        config = raw.get("config")
        if spec is None or not isinstance(config, Mapping):
            continue
        for port, lane in spec.lanes(config).items():
            yield from _raw_steps(lane, registry, f"{here}/config/{port.replace('.', '/')}")


def _uses(
    steps: Sequence[Any], registry: Mapping[str, NodeTypeSpec], step_type: str, key: str
) -> set[str]:
    return {
        str(raw["config"][key])
        for _, raw in _raw_steps(steps, registry)
        if raw.get("type") == step_type
        and isinstance(raw.get("config"), Mapping)
        and isinstance(raw["config"].get(key), str)
    }


def not_in_base(
    proposal_steps: Sequence[Any],
    pack_steps: Sequence[Any],
    registry: Mapping[str, NodeTypeSpec],
) -> list[Problem]:
    """R2.2, R2.3: a tool or a prompt the pack's workflow of the same key does
    not use anywhere, one problem per step that names it."""
    tools = _uses(pack_steps, registry, "tool.call@1", "tool")
    prompts = _uses(pack_steps, registry, "ai.llm@1", "prompt")
    found: list[Problem] = []
    for path, raw in _raw_steps(proposal_steps, registry):
        config = raw.get("config")
        if not isinstance(config, Mapping):
            continue
        tool, prompt = config.get("tool"), config.get("prompt")
        if raw.get("type") == "tool.call@1" and isinstance(tool, str) and tool not in tools:
            found.append(Problem.of(path, "wf.tool_not_in_base", tool))
        if raw.get("type") == "ai.llm@1" and isinstance(prompt, str) and prompt not in prompts:
            found.append(Problem.of(path, "wf.prompt_not_in_base", prompt))
    return found


def base_raw(pinned: PinnedWorkflow) -> dict[str, Any]:
    """A pinned document as plain data, the shape a proposal replaces `steps` in."""
    return pinned.document.model_dump(by_alias=True, exclude_none=True)


@dataclass(frozen=True, slots=True)
class Bases:
    """What a proposal is made from and checked against: the document the DW
    pins, and the pack's workflow of the same key, whose tools and prompts
    are the ones allowed (R2.2, R2.3)."""

    pinned: PinnedWorkflow
    pack: PinnedWorkflow


async def bases_of(workflows: PinnedWorkflowsPort, worker: DigitalWorker) -> Bases:
    """R1.3: from the DW's own pin, a pack's or its tenant's version (R6.16);
    404 `workflow_not_shipped` when it is not there any more."""
    config = worker.configuration
    pinned = await workflows.pinned(worker)
    pack = workflows.pack(config.workflow_key, config.workflow_version)
    if pinned is None or pack is None:
        raise not_shipped()
    return Bases(pinned=pinned, pack=pack)


def output_schemas(bases: Bases, registry: Mapping[str, NodeTypeSpec]) -> OutputSchemas:
    """The output schema of each `ai.llm@1` prompt, from the first step that
    uses it in the pinned document, else in the pack's (wf-ai/05): what
    `from_wire` gives back to a step the model wrote without one."""
    found: dict[str, Mapping[str, Any]] = {}
    for pinned in (bases.pinned, bases.pack):
        for _, raw in _raw_steps(base_raw(pinned)["steps"], registry):
            config = raw.get("config")
            if raw.get("type") != "ai.llm@1" or not isinstance(config, Mapping):
                continue
            prompt, schema = config.get("prompt"), config.get("output_schema")
            if isinstance(prompt, str) and isinstance(schema, Mapping):
                found.setdefault(prompt, schema)
    return found


def outline_of(
    document: Mapping[str, Any], registry: Mapping[str, NodeTypeSpec]
) -> tuple[OutlineStep, ...]:
    """A document's tree as the page draws it; () when it does not read as
    a document (its problems say why)."""
    try:
        return outline(WorkflowDocument.model_validate(dict(document)), registry)
    except ValidationError:
        return ()


def checked_proposal(
    bases: Bases,
    steps: Sequence[Any],
    *,
    registry: Mapping[str, NodeTypeSpec],
    tools: ToolSpecLookup,
) -> tuple[dict[str, Any], list[Problem]]:
    """R2.1, R3.1: the base with its steps replaced, and every problem the
    wf-lite validator and the assistant's own checks find in it. The one
    check, for a turn's proposal and for a draft the server stores (R6.1)."""
    base = base_raw(bases.pinned)
    proposal = {**copy.deepcopy(base), "steps": list(steps)}
    problems = validate(
        proposal,
        registry=registry,
        tools=tools,
        work_schemas=bases.pinned.work_schemas,
    ) + not_in_base(steps, base_raw(bases.pack)["steps"], registry)
    return proposal, problems


@dataclass(frozen=True)
class WorkflowAssistant:
    workers: DwOwnerPort
    workflows: PinnedWorkflowsPort
    gateway: ModelGateway
    registry: Mapping[str, NodeTypeSpec]
    tools: ToolSpecLookup
    run_context: RunContextFactory

    async def turn(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        *,
        instruction: str,
        history: Sequence[HistoryTurn],
    ) -> AssistantAnswer:
        if _too_long(instruction, history):
            raise DomainError(
                "the instruction or the history is too long",
                details={"reason_code": "assistant_input_too_long"},
            )
        worker = await self.workers.require_owner(context, dw_id)
        bases = await bases_of(self.workflows, worker)
        base = base_raw(bases.pinned)
        # The model sees the steps in the form it writes them back in.
        shown = {**base, "steps": [s.model_dump(exclude_none=True) for s in to_wire(base["steps"])]}
        request = ModelRequest(
            task="wf_ai.workflow_edit",
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            variables={
                "instruction": instruction,
                "history": json.dumps(
                    [{"role": t.role, "text": t.text} for t in history], ensure_ascii=False
                ),
                "base_document": yaml.safe_dump(shown, allow_unicode=True, sort_keys=False),
                # A trigger is not a step the tree can hold (wf-ai/05).
                "node_types": "\n".join(
                    sorted(t for t, spec in self.registry.items() if not spec.is_trigger)
                ),
            },
        )
        answer = await self.gateway.generate_structured(
            request, AssistantTurn, run_context=self.run_context(context, uuid.uuid4())
        )
        if answer.kind == "question":
            return AssistantAnswer(
                "question", answer.question, tuple(answer.plan), None, (), (), False
            )
        steps = from_wire(answer.steps or [], output_schemas(bases, self.registry))
        proposal, problems = checked_proposal(
            bases, steps, registry=self.registry, tools=self.tools
        )
        return AssistantAnswer(
            kind="proposal",
            question=None,
            plan=tuple(answer.plan),
            steps=tuple(steps),
            diff=tuple(diff_steps(base["steps"], steps, self.registry)),
            problems=tuple(problems),
            publishable=not problems,
            outline=outline_of(proposal, self.registry),
        )


__all__ = [
    "AssistantAnswer",
    "AssistantTurn",
    "Bases",
    "HistoryTurn",
    "WorkflowAssistant",
    "base_raw",
    "bases_of",
    "checked_proposal",
    "not_in_base",
    "outline_of",
    "output_schemas",
]
