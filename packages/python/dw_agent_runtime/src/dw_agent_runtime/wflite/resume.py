"""What a Studio run's manifest pins of the engine, and the checks a run passes
before it goes on after a wait or is taken again (workflow-engine R6.4, R6.5,
R6.7; ADR-0109 decision 8).

`engine_facts` is the one computation of the five facts a manifest's `engine`
section pins (`compiler_version`, `node_types`, `state_schema_hash`,
`checkpoint_format`, `langgraph`): the manifest builder pins what it returns
for the root's document, and `check_resume` compares the pinned section with
what this build has, so no value has two owners.

`check_resume` runs the five checks on the pinned section, the run's pinned
document, the interrupts its checkpoint has pending and its waits not yet
used:

- (a) the pinned compiler and every pinned `type@major` are this build's;
- (b) each pending interrupt is a waiting node of the pinned graph and the
  node its wait row names (`run_waits.node_id`);
- (c) the state schema hashes the same;
- (d) the pinned checkpoint format is one this build's saver reads, and
  LangGraph is the same `major.minor` (another patch passes);
- (e) each resolution resumed with is a non-empty object.

(b) and (e) run only for a run going on after a wait (it has pending
interrupts), never for an orphan taken again between two nodes. A section
missing a fact fails its check: a run pinned before the fact existed is not
let through on a guess. No check asks a secret's version (V4.35).

The verdict also says what to resume with (each pending interrupt's LangGraph
id to its wait's resolution) and which `resolved` waits this pass uses up,
including one whose interrupt is no longer pending (its node ran past it
before a crash). A pending interrupt with no resolved wait and no failed check
is an empty resume (R6.5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from dw_agent_runtime.ports import RunWait
from dw_agent_runtime.wflite.compile import COMPILER_VERSION, state_schema
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.ir import lower
from dw_agent_runtime.wflite.node_wrapper import wait_node
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_kernel.canonical import content_hash

ENGINE_FACTS: Final = (
    "compiler_version",
    "node_types",
    "state_schema_hash",
    "checkpoint_format",
    "langgraph",
)
WORKFLOW_SCHEMA: Final = "dw.workflow/v1"


@dataclass(frozen=True, slots=True)
class BuildFacts:
    """What this build runs: its compilers, the checkpoint formats its saver
    reads, its LangGraph `major.minor` and its step-type registry."""

    registry: Mapping[str, NodeTypeSpec]
    checkpoint_format: str
    checkpoint_formats: frozenset[str]
    langgraph: str
    compilers: frozenset[str] = frozenset({COMPILER_VERSION})


@dataclass(frozen=True, slots=True)
class Parked:
    """One interrupt a run's checkpoint has pending: LangGraph's id, and the
    wait and node its value names."""

    langgraph_id: str
    interrupt_id: str | None
    node: str | None


@dataclass(frozen=True, slots=True)
class ResumeVerdict:
    failed: tuple[str, ...] = ()
    after_wait: bool = False
    # Each pending interrupt's LangGraph id, to the resolution it resumes with.
    resume: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # The `resolved` waits this pass uses up, by interrupt id.
    consumed: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        """R6.5: after a wait, and nothing to resume with."""
        return self.after_wait and not self.failed and not self.resume


def engine_facts(document: Mapping[str, Any], build: BuildFacts) -> dict[str, Any]:
    """The five facts a manifest pins for `document`; none for a root that is
    not a workflow (it has no graph)."""
    if document.get("schema") != WORKFLOW_SCHEMA:
        return {}
    parsed = WorkflowDocument.model_validate(document)
    steps = lower(parsed, build.registry).steps
    return {
        "compiler_version": COMPILER_VERSION,
        "node_types": sorted({placed.step.type for placed in steps}),
        "state_schema_hash": content_hash(state_schema(parsed, build.registry)),
        "checkpoint_format": build.checkpoint_format,
        "langgraph": build.langgraph,
    }


def _major_minor(version: object) -> str | None:
    if not isinstance(version, str):
        return None
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else None


def _engine_checks(
    engine: Mapping[str, Any], document: Mapping[str, Any], build: BuildFacts
) -> list[str]:
    failed: list[str] = []
    types = engine.get("node_types")
    if (
        engine.get("compiler_version") not in build.compilers
        or not isinstance(types, list)
        or not all(isinstance(t, str) and t in build.registry for t in types)
    ):
        failed.append("a")
    try:
        schema = content_hash(
            state_schema(WorkflowDocument.model_validate(document), build.registry)
        )
    except Exception:
        # A document this build cannot lower has no schema to compare.
        schema = None
    pinned_schema = engine.get("state_schema_hash")
    if schema is None or not isinstance(pinned_schema, str) or pinned_schema != schema:
        failed.append("c")
    pinned_langgraph = _major_minor(engine.get("langgraph"))
    if (
        engine.get("checkpoint_format") not in build.checkpoint_formats
        or pinned_langgraph is None
        or pinned_langgraph != _major_minor(build.langgraph)
    ):
        failed.append("d")
    return failed


def _waiting_steps(document: Mapping[str, Any], build: BuildFacts) -> frozenset[str]:
    try:
        steps = lower(WorkflowDocument.model_validate(document), build.registry).steps
    except Exception:
        return frozenset()
    found = set()
    for placed in steps:
        spec = build.registry.get(placed.step.type)
        if spec is not None and spec.wait is not None:
            found.add(placed.step.id)
    return frozenset(found)


def check_resume(
    engine: Mapping[str, Any],
    document: Mapping[str, Any],
    build: BuildFacts,
    parked: Sequence[Parked],
    waits: Sequence[RunWait],
) -> ResumeVerdict:
    failed = _engine_checks(engine, document, build)
    resolved = [w for w in waits if w.status == "resolved"]
    consumed = tuple(w.interrupt_id for w in resolved)
    if not parked:
        return ResumeVerdict(failed=tuple(failed), consumed=consumed)
    by_id = {w.interrupt_id: w for w in waits}
    waiting = _waiting_steps(document, build)
    resume: dict[str, Mapping[str, Any]] = {}
    matched = True
    envelopes = True
    for interrupt in parked:
        wait = by_id.get(interrupt.interrupt_id or "")
        if wait is None or wait.node_id not in waiting or interrupt.node != wait_node(wait.node_id):
            matched = False
            continue
        if wait.status != "resolved":
            continue
        if not isinstance(wait.resolution, Mapping) or not wait.resolution:
            envelopes = False
            continue
        resume[interrupt.langgraph_id] = wait.resolution
    if not matched:
        failed.append("b")
    if not envelopes:
        failed.append("e")
    return ResumeVerdict(
        failed=tuple(sorted(failed)),
        after_wait=True,
        resume={} if failed else resume,
        consumed=consumed,
    )
