"""The `workflow` kind's capability check at submit (compliance-pdpl R2.6,
R4.1-R4.8; ADR-0125 decisions 1-3), and the label table of the step types the
platform registers.

`platform_label_table` is the dispatch table the composition root hands the
pure analysis (`capability.capability_analysis`): one entry per registered
type, each a pure function of the step, its type and the closure's facts.
`WorkflowCapabilityCheck` is the `SubmitCheck` the composition root registers
for `workflow` in agent-lifecycle/03's table: the facts read in the submit's
transaction (`CapabilityFactsPort`), the analysis, then either the 422 of the
first failing check with every path, or the assessment row written in the same
transaction (`AssessmentWriterPort`). A port that raises fails the submit;
nothing is ever read as an empty label set.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_studio.core.application.ports import ArtifactTx, VersionRow
from dw_studio.core.domain.artifacts import ClosureItem, DocumentProblem
from dw_studio.workflows.application.capability import (
    ANALYSER_VERSION,
    EVERY_LABEL,
    CapabilityAnalysis,
    CapabilityFacts,
    Label,
    LabelTable,
    capability_analysis,
)

GATE_TYPES: Final = frozenset({"human.approval@1"})
INTERNAL_TRIGGERS: Final = frozenset[str]()


def _no_labels(step: Step, spec: NodeTypeSpec, facts: CapabilityFacts) -> frozenset[Label]:
    return frozenset()


def tool_ref(step: Step) -> str | None:
    tool = step.config.get("tool")
    return tool if isinstance(tool, str) else None


def tool_labels(step: Step, spec: NodeTypeSpec, facts: CapabilityFacts) -> frozenset[Label]:
    """The three classifications of the pinned tool version (ADR-0116)."""
    classes = facts.tools.get(tool_ref(step) or "")
    if classes is None or not classes.classified:
        return EVERY_LABEL
    return classes.labels()


def child_labels(step: Step, spec: NodeTypeSpec, facts: CapabilityFacts) -> frozenset[Label]:
    """A step on another pinned version (a child workflow, an agent): the
    union of that version's assessment, which already holds its own
    children's; no row of this analyser version reads as every label
    (R4.8)."""
    ref = step.config.get("version_id")
    found = facts.assessments.get(str(ref)) if ref is not None else None
    return EVERY_LABEL if found is None else found


def platform_label_table(default_profile: str | None) -> LabelTable:
    """The table of the platform's registered step types
    (`build_node_registry()`); the test that compares the two keeps a type
    from ever reaching the analysis through the unknown-type net."""
    return LabelTable(
        rules={
            "trigger.work_item@1": _no_labels,
            "ai.llm@1": _no_labels,
            "tool.call@1": tool_labels,
            "human.approval@1": _no_labels,
            "time.wait@1": _no_labels,
            "logic.switch@1": _no_labels,
            # workflow-nodes/08's child workflow; until it is registered a step
            # of it is an unknown type and carries every label (R4.8).
            "flow.subworkflow@1": child_labels,
        },
        internal_triggers=INTERNAL_TRIGGERS,
        gates=GATE_TYPES,
        tool_of={"tool.call@1": tool_ref},
        profile_of={"ai.llm@1": lambda step: default_profile},
        child_types=frozenset({"flow.subworkflow@1"}),
    )


class VersionAssessmentLookup(Protocol):
    """The labels of each pinned child version's assessment of this analyser
    version, read under the submitting company's RLS (R4.8): a version with
    no such row is absent from the answer. Raises when it cannot say."""

    async def labels(
        self, tx: ArtifactTx, version_ids: Iterable[uuid.UUID]
    ) -> Mapping[uuid.UUID, frozenset[Label]]: ...


class CapabilityFactsPort(Protocol):
    """What the closure a submit pinned says, read in the submit's
    transaction (`tx`), under the submitting company's RLS."""

    async def facts(
        self, tx: ArtifactTx, version: VersionRow, document: WorkflowDocument, table: LabelTable
    ) -> CapabilityFacts: ...


class AssessmentWriterPort(Protocol):
    """Writes the version's assessment in `tx`, once per `(version, definition
    hash, analyser version)` (R4.6)."""

    async def write(
        self, tx: ArtifactTx, version: VersionRow, analysis: CapabilityAnalysis
    ) -> None: ...


@dataclass(frozen=True)
class CapabilityRefusal:
    """The 422 of the first failing check: its code, one `errors[]` entry and
    one `details.paths` entry per path. The composition root hands it to
    agent-lifecycle/03's submit as its `SubmitRefusal` (this package never
    imports `lifecycle`)."""

    reason_code: str
    detail: str
    errors: tuple[DocumentProblem, ...]
    details: Mapping[str, object] = field(default_factory=dict)


def refusal_of(analysis: CapabilityAnalysis) -> CapabilityRefusal | None:
    found = analysis.refusal
    if found is None:
        return None
    code, paths = found
    return CapabilityRefusal(
        code,
        "the workflow's capability analysis refused it",
        tuple(DocumentProblem("/steps", code, " -> ".join(path)) for path in paths),
        details={"paths": [list(path) for path in paths]},
    )


@dataclass(frozen=True)
class WorkflowCapabilityCheck:
    registry: Mapping[str, NodeTypeSpec]
    table: LabelTable
    facts: CapabilityFactsPort
    assessments: AssessmentWriterPort

    async def __call__(
        self, tx: ArtifactTx, version: VersionRow, closure: Sequence[ClosureItem]
    ) -> CapabilityRefusal | None:
        document = WorkflowDocument.model_validate(version.document)
        facts = await self.facts.facts(tx, version, document, self.table)
        analysis = capability_analysis(document, self.registry, self.table, facts)
        refused = refusal_of(analysis)
        if refused is not None:
            return refused
        await self.assessments.write(tx, version, analysis)
        return None


__all__ = [
    "ANALYSER_VERSION",
    "GATE_TYPES",
    "AssessmentWriterPort",
    "CapabilityFactsPort",
    "CapabilityRefusal",
    "VersionAssessmentLookup",
    "WorkflowCapabilityCheck",
    "child_labels",
    "platform_label_table",
    "refusal_of",
    "tool_labels",
    "tool_ref",
]
