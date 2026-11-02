"""A pinned workflow as a person reads it, and what its decision classes may
do (digital-worker R9.2).

`outline` is the step tree the DW page draws read-only: each step with its
lanes, walked through the same registry the validator and the compiler read,
so a lane the compiler runs is a lane the page shows. `blocked_classes` says
which decision classes cannot act at all: every tool their `tool.call` steps
call is outside the DW's `allowed_tools`, which `ToolExecutor` refuses
(digital-worker R6), so no level lets them through. `decision_mode` is the one
answer to "Tự động, Hỏi or Chặn" (spec, R9).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from dw_agent_runtime.wflite.catalog import PinnedWorkflow
from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_kernel.autonomy import AutonomyLevel
from dw_kernel.errors import NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.digital_workers import ClassAutonomy
from dw_platform.domain.digital_worker import DigitalWorker

DecisionMode = Literal["auto", "ask", "blocked"]


@dataclass(frozen=True, slots=True)
class OutlineStep:
    id: str
    type: str
    description: str | None
    decision_class: str | None
    tool: str | None
    lanes: tuple[tuple[str, tuple[OutlineStep, ...]], ...]


def _lanes(step: Step, registry: Mapping[str, NodeTypeSpec]) -> list[tuple[str, list[Step]]]:
    spec = registry.get(step.type)
    if spec is None:
        return []
    return [
        (port, [Step.model_validate(raw) for raw in lane])
        for port, lane in spec.lanes(step.config).items()
    ]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def outline(
    document: WorkflowDocument, registry: Mapping[str, NodeTypeSpec]
) -> tuple[OutlineStep, ...]:
    def walk(steps: Sequence[Step]) -> tuple[OutlineStep, ...]:
        return tuple(
            OutlineStep(
                id=step.id,
                type=step.type,
                description=step.description,
                decision_class=_text(step.config.get("decision_class")),
                tool=_text(step.config.get("tool")),
                lanes=tuple((port, walk(lane)) for port, lane in _lanes(step, registry)),
            )
            for step in steps
        )

    return walk(document.steps)


def _tool_calls(
    steps: Sequence[Step], registry: Mapping[str, NodeTypeSpec]
) -> Iterator[tuple[str, str]]:
    for step in steps:
        if step.type == "tool.call@1":
            cls, tool = step.config.get("decision_class"), step.config.get("tool")
            if isinstance(cls, str) and isinstance(tool, str):
                yield cls, tool.partition("@")[0]
        for _, lane in _lanes(step, registry):
            yield from _tool_calls(lane, registry)


def blocked_classes(
    document: WorkflowDocument,
    registry: Mapping[str, NodeTypeSpec],
    allowed_tools: frozenset[str],
) -> frozenset[str]:
    """The classes whose every tool call is outside `allowed_tools`. A class
    no step calls a tool for is not blocked: nothing of it is refused."""
    tools: dict[str, set[str]] = {}
    for cls, name in _tool_calls(document.steps, registry):
        tools.setdefault(cls, set()).add(name)
    return frozenset(cls for cls, names in tools.items() if not names & allowed_tools)


@dataclass(frozen=True, slots=True)
class StepChange:
    """One line of a step-tree diff (wf-ai R4.1). `lane` is where the step is
    in the proposal (or was, when removed): `""` at the top, else
    `<step id>.<port>` segments joined by `/`, as `outline` names lanes."""

    change: Literal["added", "removed", "changed", "moved"]
    step_id: str
    type: str
    lane: str
    from_lane: str | None = None


@dataclass(frozen=True, slots=True)
class _Placed:
    lane: str
    raw: Mapping[str, Any]


def _place(
    steps: Sequence[Any], registry: Mapping[str, NodeTypeSpec], lane: str = ""
) -> tuple[dict[str, _Placed], dict[str, list[str]]]:
    """Every step dict by id with its lane, and each lane's ids in order. A
    second step with an id already seen is the validator's to report
    (`wf.duplicate_step_id`); the diff keeps the first."""
    placed: dict[str, _Placed] = {}
    order: dict[str, list[str]] = {}

    def walk(items: Sequence[Any], here: str) -> None:
        for raw in items:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
                continue
            if raw["id"] in placed:
                continue
            placed[raw["id"]] = _Placed(here, raw)
            order.setdefault(here, []).append(raw["id"])
            spec = registry.get(str(raw.get("type")))
            config = raw.get("config")
            if spec is None or not isinstance(config, Mapping):
                continue
            for port, inner in spec.lanes(config).items():
                walk(inner, "/".join(p for p in (here, f"{raw['id']}.{port}") if p))

    walk(steps, lane)
    return placed, order


def _own(raw: Mapping[str, Any], registry: Mapping[str, NodeTypeSpec]) -> dict[str, Any]:
    """A step without the steps its lanes hold, so a change inside a lane is
    that inner step's change, not its parent's."""
    config = dict(raw.get("config") or {})
    spec = registry.get(str(raw.get("type")))
    if spec is not None:
        for port in spec.lanes(config):
            if port.startswith("cases."):
                cases = dict(config.get("cases") or {})
                cases.pop(port.removeprefix("cases."), None)
                config["cases"] = cases
            else:
                config.pop(port, None)
        if config.get("cases") == {}:
            config.pop("cases")
    return {"config": config, "description": raw.get("description")}


def diff_steps(
    base: Sequence[Any], proposal: Sequence[Any], registry: Mapping[str, NodeTypeSpec]
) -> list[StepChange]:
    """wf-ai R4.1: what a proposal adds, removes, changes and moves, by step
    id. An id whose type changed is one step removed and one added."""
    before, before_order = _place(base, registry)
    after, after_order = _place(proposal, registry)
    changes: list[StepChange] = []
    for step_id, prior in before.items():
        current = after.get(step_id)
        if current is None or current.raw.get("type") != prior.raw.get("type"):
            changes.append(StepChange("removed", step_id, str(prior.raw.get("type")), prior.lane))
    for step_id, now in after.items():
        old = before.get(step_id)
        kind = str(now.raw.get("type"))
        if old is None or old.raw.get("type") != now.raw.get("type"):
            changes.append(StepChange("added", step_id, kind, now.lane))
            continue
        moved = old.lane != now.lane or _out_of_order(
            step_id, now.lane, before_order, after_order, before, after
        )
        if moved:
            changes.append(StepChange("moved", step_id, kind, now.lane, old.lane))
        if _own(old.raw, registry) != _own(now.raw, registry):
            changes.append(StepChange("changed", step_id, kind, now.lane))
    return changes


def _out_of_order(
    step_id: str,
    lane: str,
    before_order: Mapping[str, list[str]],
    after_order: Mapping[str, list[str]],
    before: Mapping[str, _Placed],
    after: Mapping[str, _Placed],
) -> bool:
    """Whether a step kept its lane but not its place among the steps that
    stayed in that lane with it: an insertion before it is not a move."""

    def stayed(ids: list[str]) -> list[str]:
        return [
            i
            for i in ids
            if i in before
            and i in after
            and before[i].lane == lane
            and after[i].lane == lane
            and before[i].raw.get("type") == after[i].raw.get("type")
        ]

    old, new = stayed(before_order.get(lane, [])), stayed(after_order.get(lane, []))
    return step_id in old and step_id in new and old.index(step_id) != new.index(step_id)


def decision_mode(*, blocked: bool, requires_person: bool) -> DecisionMode:
    if blocked:
        return "blocked"
    return "ask" if requires_person else "auto"


@dataclass(frozen=True, slots=True)
class ClassStanding:
    key: str
    effective_level: AutonomyLevel
    mode: DecisionMode


@dataclass(frozen=True, slots=True)
class WorkflowOutline:
    dw_id: uuid.UUID
    key: str
    version: str
    sha256: str
    steps: tuple[OutlineStep, ...]
    decision_classes: tuple[ClassStanding, ...]


class DwReaderPort(Protocol):
    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        """The DW, or 404 for one the caller may not read (R1.5)."""
        ...


class PinnedWorkflowsPort(Protocol):
    def workflow(self, key: str, version: str) -> PinnedWorkflow | None: ...


class ClassAutonomyPort(Protocol):
    async def class_autonomy(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> ClassAutonomy: ...


@dataclass(frozen=True)
class WorkflowOutlineReader:
    """digital-worker R9.2: a DW's pinned workflow and each decision class's
    level and mode, read as the gate reads them at this moment."""

    workers: DwReaderPort
    workflows: PinnedWorkflowsPort
    autonomy: ClassAutonomyPort
    registry: Mapping[str, NodeTypeSpec]

    async def read(self, context: AccessContext, dw_id: uuid.UUID) -> WorkflowOutline:
        worker = await self.workers.get(context, dw_id)
        config = worker.configuration
        pinned = self.workflows.workflow(config.workflow_key, config.workflow_version)
        if pinned is None:
            raise NotFoundError(
                "the digital worker's pinned workflow is not shipped",
                details={"reason_code": "workflow_not_shipped"},
            )
        blocked = blocked_classes(pinned.document, self.registry, frozenset(config.allowed_tools))
        standings = []
        for cls in config.decision_classes:
            found = await self.autonomy.class_autonomy(
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                dw_id=worker.id,
                key=cls.key,
            )
            standings.append(
                ClassStanding(
                    key=cls.key,
                    effective_level=found.effective_level,
                    mode=decision_mode(
                        blocked=cls.key in blocked, requires_person=found.requires_person
                    ),
                )
            )
        return WorkflowOutline(
            dw_id=worker.id,
            key=pinned.document.key,
            version=pinned.document.version,
            sha256=pinned.sha256,
            steps=outline(pinned.document, self.registry),
            decision_classes=tuple(standings),
        )


__all__ = [
    "ClassStanding",
    "DecisionMode",
    "OutlineStep",
    "StepChange",
    "WorkflowOutline",
    "WorkflowOutlineReader",
    "blocked_classes",
    "decision_mode",
    "diff_steps",
    "outline",
]
