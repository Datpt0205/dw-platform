"""The one lowering of a `dw.workflow/v1` tree to `WorkflowIR` (workflow-engine
R2.12, WE14; ADR-0112 decision 3 and Amendments 2026-11-03).

The validator and the compiler read the tree through this module and nothing
else, so the tree that is checked is the tree that is compiled:

- `iter_lanes` is the one reader of where a step's lanes sit: inside its
  `config` under the port's name, as its type's `NodeTypeSpec.lanes` lists
  them (a port named `a.b` sits at `config[a][b]`), and its own `error_lane`;
- `lower` parses every step of the tree once, at every depth, and wires one
  node per step, a `Join` closing every block, and the edges a run can take:
  in order along a lane, into each lane by the block its type declares
  (`choice` runs one lane, `parallel` every lane, `loop` its `body` lane with
  an edge back to the loop step, its other lanes being ways out), into the
  error lane of a step and back out at its join, none out of a step whose type
  `ends_run`, and from one that `exits_loop` to its loop's join;
- `reachable` and `dominators` answer the graph's two questions the
  validator asks (R2.1, R2.5). `paths_to` and branch exclusivity arrive with
  their first readers (ADR-0125's capability analysis, R2.7).

A join is `Join(index)`, never a string of the step id space, so no step can
name one; the compiler keeps the node names it has always used (`join__<id>`,
`wait__<id>`), which a parked wf-lite run's checkpoint names, and the
validator refuses a step id with either prefix.

The lowering stops past `MAX_NESTING` and after `MAX_TREE_STEPS` and says
where, so a tree nested hundreds deep is one `wf.limit_above_plan`, never a
`RecursionError` (R2.10).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from pydantic import ValidationError

from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.registry import NodeTypeSpec

# Two platform caps, the same for every tenant and path, read from nothing so
# nothing can fail open (R2.10; ADR-0112 Amendments 2026-11-03).
MAX_TREE_STEPS: Final = 500
MAX_NESTING: Final = 10

ERROR_LANE: Final = "error_lane"
# The lane a `loop` block runs again; its other lanes (`max_reached`) are exits.
LOOP_BODY: Final = "body"


def segment(text: object) -> str:
    """One JSON pointer segment (RFC 6901): `~` and `/` escaped, so a case
    value with either names one key, not two."""
    return str(text).replace("~", "~0").replace("/", "~1")


def join_path(*parts: object) -> str:
    return "/".join(str(p) for p in parts if p != "")


@dataclass(frozen=True, slots=True)
class Lane:
    """One lane of a step: its port, its items as written, and where it sits
    under the step (`("config", "cases", "a")`, `("error_lane",)`)."""

    port: str
    items: tuple[Any, ...]
    at: tuple[str, ...]
    is_error: bool

    @property
    def path(self) -> str:
        return join_path(*(segment(part) for part in self.at))


def iter_lanes(
    step: Step | Mapping[str, Any], registry: Mapping[str, NodeTypeSpec]
) -> tuple[Lane, ...]:
    """Every lane `step` holds, its type's first, its error lane last. A step
    as parsed or as written (a dict); what does not read as a lane is the
    validator's to report, not this function's to guess."""
    type_: object
    config: object
    error: object
    if isinstance(step, Step):
        type_, config, error = step.type, step.config, step.error_lane
    else:
        type_, config, error = step.get("type"), step.get("config"), step.get(ERROR_LANE)
    found: list[Lane] = []
    spec = registry.get(str(type_))
    if spec is not None and isinstance(config, Mapping):
        for port, items in spec.lanes(config).items():
            head, _, rest = port.partition(".")
            at = ("config", head, rest) if rest else ("config", head)
            found.append(Lane(port, tuple(items), at, is_error=False))
    if isinstance(error, list):
        found.append(Lane(ERROR_LANE, tuple(error), (ERROR_LANE,), is_error=True))
    return tuple(found)


class Terminal(Enum):
    START = "start"
    END = "end"


@dataclass(frozen=True, slots=True)
class Join:
    """The node that closes the block or error lane of step `of`."""

    of: int


Node = int | Join | Terminal


@dataclass(frozen=True, slots=True)
class IRStep:
    """One step of the tree. `index` is its node; a trigger's is its place in
    `WorkflowIR.triggers`, and a trigger is no node of the graph."""

    index: int
    step: Step
    spec: NodeTypeSpec | None
    path: str
    depth: int
    # The step whose lane holds this one, and that lane's port.
    parent: int | None
    port: str | None
    # Each lane with the indices of the steps of it that were lowered.
    lanes: tuple[tuple[Lane, tuple[int, ...]], ...]


@dataclass(frozen=True, slots=True)
class LoweringIssue:
    """A problem the lowering met: a lane item that is not a step, or a cap."""

    path: str
    code: str
    detail: str


@dataclass(frozen=True)
class WorkflowIR:
    triggers: tuple[IRStep, ...]
    steps: tuple[IRStep, ...]
    edges: Mapping[Node, tuple[Node, ...]]
    issues: tuple[LoweringIssue, ...]

    def lanes_of(self, index: int, *, errors: bool = False) -> dict[str, list[Step]]:
        """The steps of each lane of step `index`, by port: its type's lanes,
        and its error lane when `errors`."""
        return {
            lane.port: [self.steps[i].step for i in kids]
            for lane, kids in self.steps[index].lanes
            if errors or not lane.is_error
        }

    def ancestors(self, index: int) -> Iterator[tuple[IRStep, str]]:
        """Each step whose lane holds `index`, innermost first, with the port
        of the lane the walk came through."""
        here = self.steps[index]
        while here.parent is not None and here.port is not None:
            yield self.steps[here.parent], here.port
            here = self.steps[here.parent]


class _Lowering:
    def __init__(self, registry: Mapping[str, NodeTypeSpec]) -> None:
        self.registry = registry
        self.steps: list[IRStep] = []
        self.issues: list[LoweringIssue] = []
        self.edges: dict[Node, list[Node]] = {}
        self.full = False

    # ------------------------------------------------------------- parsing --

    def parse(self, raw: Any, path: str) -> Step | None:
        if isinstance(raw, Step):
            return raw
        try:
            return Step.model_validate(raw)
        except ValidationError as exc:
            for error in exc.errors():
                self.issues.append(
                    LoweringIssue(
                        join_path(path, *(segment(p) for p in error["loc"])),
                        "wf.schema_invalid",
                        error["msg"],
                    )
                )
            return None

    def trigger(self, step: Step, index: int) -> IRStep:
        spec = self.registry.get(step.type)
        return IRStep(index, step, spec, join_path("triggers", index), 0, None, None, ())

    def lane(
        self, items: Sequence[Any], path: str, depth: int, parent: int | None, port: str | None
    ) -> tuple[int, ...]:
        lowered: list[int] = []
        for i, raw in enumerate(items):
            here = join_path(path, i)
            if self.full:
                break
            if depth > MAX_NESTING:
                self.issues.append(
                    LoweringIssue(
                        here, "wf.limit_above_plan", f"steps nest deeper than {MAX_NESTING}"
                    )
                )
                break
            step = self.parse(raw, here)
            if step is None:
                continue
            if len(self.steps) >= MAX_TREE_STEPS:
                self.issues.append(
                    LoweringIssue(here, "wf.limit_above_plan", f"more than {MAX_TREE_STEPS} steps")
                )
                self.full = True
                break
            index = len(self.steps)
            spec = self.registry.get(step.type)
            # A placeholder holds the index while the lanes below are lowered.
            self.steps.append(IRStep(index, step, spec, here, depth, parent, port, ()))
            lanes = tuple(
                (
                    lane,
                    self.lane(lane.items, join_path(here, lane.path), depth + 1, index, lane.port),
                )
                for lane in iter_lanes(step, self.registry)
            )
            self.steps[index] = IRStep(index, step, spec, here, depth, parent, port, lanes)
            lowered.append(index)
        return tuple(lowered)

    # -------------------------------------------------------------- wiring --

    def edge(self, source: Node, target: Node) -> None:
        targets = self.edges.setdefault(source, [])
        if target not in targets:
            targets.append(target)

    def link(self, indices: Sequence[int], after: Node) -> Node:
        """Wire a lane's steps in order, its last to `after`; return the node a
        run enters the lane by (`after` itself for an empty lane)."""
        entry: Node = after
        for index in reversed(indices):
            self.wire(index, entry)
            entry = index
        return entry

    def wire(self, index: int, after: Node) -> None:
        here = self.steps[index]
        spec = here.spec
        block = spec.block if spec is not None else "none"
        kinds = [(lane, kids) for lane, kids in here.lanes if not lane.is_error]
        errors = [(lane, kids) for lane, kids in here.lanes if lane.is_error]
        exit_node: Node = index
        if here.lanes or block != "none":
            join = Join(index)
            exit_node = join
            for lane, kids in kinds:
                if block == "loop" and lane.port == LOOP_BODY:
                    entry = self.link(kids, index)  # the body's last returns to the loop
                    if entry != index:
                        self.edge(index, entry)
                else:
                    self.edge(index, self.link(kids, join))
            # `none` succeeds straight on; a `choice` may take no lane (no case
            # matches); a loop leaves when its iterations end; a `parallel`
            # with no lane has nothing to wait for.
            if block in ("none", "choice", "loop") or not kinds:
                self.edge(index, join)
            for _, kids in errors:
                self.edge(index, self.link(kids, join))
        if spec is not None and spec.ends_run:
            return
        if spec is not None and spec.exits_loop:
            loop = self.enclosing_loop(index)
            if loop is not None:
                self.edge(exit_node, Join(loop))
            return
        self.edge(exit_node, after)

    def enclosing_loop(self, index: int) -> int | None:
        child = self.steps[index]
        while child.parent is not None:
            parent = self.steps[child.parent]
            if parent.spec is not None and parent.spec.block == "loop" and child.port == LOOP_BODY:
                return parent.index
            child = parent
        return None


def lower(document: WorkflowDocument, registry: Mapping[str, NodeTypeSpec]) -> WorkflowIR:
    """The document's IR: every step it can lower, the graph between them,
    and every issue met on the way."""
    lowering = _Lowering(registry)
    triggers = tuple(lowering.trigger(t, i) for i, t in enumerate(document.triggers))
    top = lowering.lane(document.steps, "steps", 1, None, None)
    lowering.edge(Terminal.START, lowering.link(top, Terminal.END))
    return WorkflowIR(
        triggers=triggers,
        steps=tuple(lowering.steps),
        edges={source: tuple(targets) for source, targets in lowering.edges.items()},
        issues=tuple(lowering.issues),
    )


# ---------------------------------------------------------------- the graph --


def _postorder(ir: WorkflowIR) -> list[Node]:
    """The nodes reachable from START, in postorder, without recursion."""
    order: list[Node] = []
    seen: set[Node] = {Terminal.START}
    stack: list[tuple[Node, Iterator[Node]]] = [
        (Terminal.START, iter(ir.edges.get(Terminal.START, ())))
    ]
    while stack:
        node, targets = stack[-1]
        nxt = next(targets, None)
        if nxt is None:
            stack.pop()
            order.append(node)
        elif nxt not in seen:
            seen.add(nxt)
            stack.append((nxt, iter(ir.edges.get(nxt, ()))))
    return order


def reachable(ir: WorkflowIR) -> frozenset[Node]:
    """Every node some run can get to from the start (R2.1)."""
    return frozenset(_postorder(ir))


@dataclass(frozen=True)
class Dominators:
    """Each reachable node's immediate dominator: a node `d` dominates `n`
    when every path from the start to `n` passes `d`."""

    idom: Mapping[Node, Node]

    def dominates(self, d: Node, n: Node) -> bool:
        if n not in self.idom:
            return False
        here = n
        while True:
            if here == d:
                return True
            above = self.idom[here]
            if above == here:
                return False
            here = above


def dominators(ir: WorkflowIR) -> Dominators:
    """Cooper, Harvey and Kennedy's iteration over reverse postorder (R2.5)."""
    post = _postorder(ir)
    number = {node: n for n, node in enumerate(post)}
    preds: dict[Node, list[Node]] = {node: [] for node in post}
    for source in post:
        for target in ir.edges.get(source, ()):
            preds[target].append(source)
    idom: dict[Node, Node] = {Terminal.START: Terminal.START}

    def meet(a: Node, b: Node) -> Node:
        while a != b:
            while number[a] < number[b]:
                a = idom[a]
            while number[b] < number[a]:
                b = idom[b]
        return a

    changed = True
    while changed:
        changed = False
        for node in reversed(post):
            if node == Terminal.START:
                continue
            ready = [p for p in preds[node] if p in idom]
            if not ready:
                continue
            new = ready[0]
            for other in ready[1:]:
                new = meet(other, new)
            if idom.get(node) != new:
                idom[node] = new
                changed = True
    return Dominators(idom)


__all__ = [
    "ERROR_LANE",
    "LOOP_BODY",
    "MAX_NESTING",
    "MAX_TREE_STEPS",
    "Dominators",
    "IRStep",
    "Join",
    "Lane",
    "LoweringIssue",
    "Node",
    "Terminal",
    "WorkflowIR",
    "dominators",
    "iter_lanes",
    "join_path",
    "lower",
    "reachable",
    "segment",
]
