"""The capability analysis of a workflow at its submit (compliance-pdpl R2.6,
R4.1, R4.2, R4.4, R4.8; ADR-0125 decisions 1, 2, 3, 5).

Pure: a sealed document, the facts its pinned closure gives
(`CapabilityFacts`, read by the composition root's adapter in the submit's
transaction, never at run time) and the label table the composition root
builds (`LabelTable`). Nothing here reads a store, a clock or a step type's
name.

Each step carries labels: `untrusted_source` (A), `private_data` (B),
`external_effect` (C). C comes, for every type, from the type's own
`side_effect_level` (`external` or `critical`); the rest from the table's
entry for the type, a pure function of the step, its type and the facts. A
type with no entry, or a type the registry does not know, carries all three
(R4.1). A trigger carries A unless the table marks its type internal, and B
when its source holds a personal field; its labels reach every step.

Three checks, the first to fail answers the submit with every path it found:

- `tool_unclassified` (R4.4): a step's tool lacks one of its three
  classifications;
- `residency_refused` (R2.6): under a route class other than `vn_only`, a
  model step whose pinned profile has a route not declared `vn` has a B step
  among its ancestors, or carries B itself;
- `trifecta_path_unapproved` (R4.2): a C step with an A step and a B step
  among itself and its ancestors (a loop's back edge counted) has no gate: a
  step of a gate type H that dominates it, holds it in its `approved` lane,
  and has every one of those A and B steps (other than C) among its own
  ancestors.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.ir import IRStep, WorkflowIR, dominators, lower, paths_to
from dw_agent_runtime.wflite.registry import NodeTypeSpec

Label = Literal["untrusted_source", "private_data", "external_effect"]
UNTRUSTED: Final[Label] = "untrusted_source"
PRIVATE: Final[Label] = "private_data"
EXTERNAL: Final[Label] = "external_effect"
EVERY_LABEL: Final[frozenset[Label]] = frozenset({UNTRUSTED, PRIVATE, EXTERNAL})

# Raised whenever what the analysis decides changes: a stored assessment of
# another analyser version is read as no assessment (R4.8).
ANALYSER_VERSION: Final = "1"

TOOL_UNCLASSIFIED: Final = "tool_unclassified"
RESIDENCY_REFUSED: Final = "residency_refused"
TRIFECTA_PATH_UNAPPROVED: Final = "trifecta_path_unapproved"
# The order in which the checks answer (spec R4, one 422 a submit).
CHECK_ORDER: Final = (TOOL_UNCLASSIFIED, RESIDENCY_REFUSED, TRIFECTA_PATH_UNAPPROVED)

# ADR-0116 decision 4: the closed vocabulary of `data_classification`.
DATA_CLASSES: Final = frozenset({"none", "internal", "personal", "sensitive", "secret"})
PRIVATE_CLASSES: Final = frozenset({"personal", "sensitive", "secret"})
EFFECT_LEVELS: Final = frozenset({"external", "critical"})
APPROVED_LANE: Final = "approved"


@dataclass(frozen=True, slots=True)
class ToolClasses:
    """A pinned tool version's three classifications; None where it has none."""

    output_trust: str | None
    data_classification: frozenset[str] | None
    side_effect_level: str | None

    @property
    def classified(self) -> bool:
        return (
            self.output_trust is not None
            and self.data_classification is not None
            and self.side_effect_level is not None
        )

    def labels(self) -> frozenset[Label]:
        found: set[Label] = set()
        if self.output_trust == "untrusted":
            found.add(UNTRUSTED)
        classes = self.data_classification or frozenset()
        # Closed when strange: an empty set, or a value outside the closed
        # vocabulary, reads as private (failure-modes #7).
        if not classes or classes & PRIVATE_CLASSES or not classes <= DATA_CLASSES:
            found.add(PRIVATE)
        if self.side_effect_level in EFFECT_LEVELS:
            found.add(EXTERNAL)
        return frozenset(found)


@dataclass(frozen=True)
class CapabilityFacts:
    """What the closure pinned at the submit says, by the keys the table's
    entries read: a tool's classifications by `name@version`; whether an
    object (by the key a step names it with) or a trigger's source holds a
    field whose `pd_category` is not `none`; the labels of a pinned child
    version's assessment (None: no row of this analyser version); the route
    class of the submit; each model profile's routes' `data_location`."""

    tools: Mapping[str, ToolClasses] = field(default_factory=dict)
    personal_objects: Mapping[str, bool] = field(default_factory=dict)
    personal_sources: Mapping[str, bool] = field(default_factory=dict)
    assessments: Mapping[str, frozenset[Label] | None] = field(default_factory=dict)
    route_class: str = "vn_only"
    model_locations: Mapping[str, tuple[str | None, ...]] = field(default_factory=dict)


LabelRule = Callable[[Step, NodeTypeSpec, CapabilityFacts], frozenset[Label]]


@dataclass(frozen=True)
class LabelTable:
    """Built at the composition root (ADR-0125 decision 1): an entry per step
    type, the trigger types that are internal, the gate types, which step
    names a tool (`tool_of`) and which a model profile (`profile_of`)."""

    rules: Mapping[str, LabelRule]
    internal_triggers: frozenset[str] = frozenset()
    gates: frozenset[str] = frozenset()
    tool_of: Mapping[str, Callable[[Step], str | None]] = field(default_factory=dict)
    profile_of: Mapping[str, Callable[[Step], str | None]] = field(default_factory=dict)
    source_of: Callable[[Step], str | None] = lambda step: None
    # The types whose step runs another pinned version named by its
    # `version_id` (a child workflow), whose assessment the facts read.
    child_types: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    # The ids of the steps on the path: the A and B steps, then the one the
    # check is about; `trigger:<id>` for a trigger.
    path: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityAnalysis:
    labels: Mapping[str, frozenset[Label]]
    violations: tuple[Violation, ...]

    @property
    def signals(self) -> frozenset[Label]:
        found: set[Label] = set()
        for labels in self.labels.values():
            found |= labels
        return frozenset(found)

    @property
    def refusal(self) -> tuple[str, tuple[tuple[str, ...], ...]] | None:
        """The first failing check in `CHECK_ORDER` and every path of it."""
        for code in CHECK_ORDER:
            paths = tuple(v.path for v in self.violations if v.code == code)
            if paths:
                return code, paths
        return None


def trigger_labels(step: Step, table: LabelTable, facts: CapabilityFacts) -> frozenset[Label]:
    found: set[Label] = set()
    if step.type not in table.internal_triggers:
        found.add(UNTRUSTED)
    source = table.source_of(step)
    # A source the closure does not describe reads as personal: closed.
    if source is not None and facts.personal_sources.get(source, True):
        found.add(PRIVATE)
    return frozenset(found)


def step_labels(
    step: Step, spec: NodeTypeSpec | None, table: LabelTable, facts: CapabilityFacts
) -> frozenset[Label]:
    rule = table.rules.get(step.type)
    if spec is None or rule is None:
        return EVERY_LABEL
    own: frozenset[Label] = (
        frozenset({EXTERNAL}) if spec.side_effect_level in EFFECT_LEVELS else frozenset()
    )
    return own | rule(step, spec, facts)


def _ancestors(ir: WorkflowIR, index: int) -> frozenset[int]:
    return frozenset(n for n in paths_to(ir, index) if isinstance(n, int))


def _in_approved_lane(ir: WorkflowIR, gate: int, index: int) -> bool:
    return any(
        parent.index == gate and port == APPROVED_LANE for parent, port in ir.ancestors(index)
    )


def _sorted(ids: Iterable[str]) -> list[str]:
    return sorted(set(ids))


def capability_analysis(
    document: WorkflowDocument,
    registry: Mapping[str, NodeTypeSpec],
    table: LabelTable,
    facts: CapabilityFacts,
) -> CapabilityAnalysis:
    ir = lower(document, registry)
    labels: dict[str, frozenset[Label]] = {}
    trigger_ids: dict[Label, list[str]] = {UNTRUSTED: [], PRIVATE: [], EXTERNAL: []}
    for placed in ir.triggers:
        found = trigger_labels(placed.step, table, facts)
        labels[f"trigger:{placed.step.id}"] = found
        for label in found:
            trigger_ids[label].append(f"trigger:{placed.step.id}")
    by_index: dict[int, frozenset[Label]] = {}
    violations: list[Violation] = []
    for placed in ir.steps:
        step_found = step_labels(placed.step, placed.spec, table, facts)
        tool = table.tool_of.get(placed.step.type)
        ref = tool(placed.step) if tool is not None else None
        if tool is not None:
            classes = facts.tools.get(ref or "")
            if classes is None or not classes.classified:
                violations.append(Violation(TOOL_UNCLASSIFIED, (placed.step.id,)))
                step_found = EVERY_LABEL
        by_index[placed.index] = step_found
        labels[placed.step.id] = step_found
    doms = dominators(ir)

    def carrying(nodes: Iterable[int], label: Label) -> list[str]:
        return [ir.steps[n].step.id for n in nodes if label in by_index.get(n, frozenset())]

    for placed in ir.steps:
        index = placed.index
        above = _ancestors(ir, index)
        if facts.route_class != "vn_only":
            violations += _residency(ir, placed, table, facts, above, by_index, trigger_ids)
        if EXTERNAL not in by_index[index]:
            continue
        mine = {*above, index}
        a_steps = carrying(mine, UNTRUSTED) + trigger_ids[UNTRUSTED]
        b_steps = carrying(mine, PRIVATE) + trigger_ids[PRIVATE]
        if not a_steps or not b_steps:
            continue
        others = {n for n in above if n != index and by_index[n] & {UNTRUSTED, PRIVATE}}
        gated = any(
            gate.step.type in table.gates
            and doms.dominates(gate.index, index)
            and _in_approved_lane(ir, gate.index, index)
            and others <= _ancestors(ir, gate.index)
            for gate in ir.steps
        )
        if not gated:
            violations.append(
                Violation(
                    TRIFECTA_PATH_UNAPPROVED,
                    (*_sorted(a_steps), *_sorted(b_steps), placed.step.id),
                )
            )
    return CapabilityAnalysis(labels, tuple(violations))


def _residency(
    ir: WorkflowIR,
    placed: IRStep,
    table: LabelTable,
    facts: CapabilityFacts,
    above: frozenset[int],
    by_index: Mapping[int, frozenset[Label]],
    trigger_ids: Mapping[Label, list[str]],
) -> list[Violation]:
    """R2.6: a model step on a route not declared `vn` with a private step
    among its ancestors or itself (W1 reads ancestry, not a field's flow)."""
    profile_of = table.profile_of.get(placed.step.type)
    if profile_of is None:
        return []
    profile = profile_of(placed.step)
    locations = facts.model_locations.get(profile or "")
    # A profile the closure does not describe, or a route that says nothing,
    # is foreign.
    foreign = locations is None or not locations or any(loc != "vn" for loc in locations)
    if not foreign:
        return []
    private = [ir.steps[n].step.id for n in {*above, placed.index} if PRIVATE in by_index[n]]
    private += trigger_ids[PRIVATE]
    if not private:
        return []
    return [Violation(RESIDENCY_REFUSED, (*_sorted(private), placed.step.id))]


__all__ = [
    "ANALYSER_VERSION",
    "CHECK_ORDER",
    "EVERY_LABEL",
    "EXTERNAL",
    "PRIVATE",
    "RESIDENCY_REFUSED",
    "TOOL_UNCLASSIFIED",
    "TRIFECTA_PATH_UNAPPROVED",
    "UNTRUSTED",
    "CapabilityAnalysis",
    "CapabilityFacts",
    "Label",
    "LabelRule",
    "LabelTable",
    "ToolClasses",
    "Violation",
    "capability_analysis",
    "step_labels",
    "trigger_labels",
]
