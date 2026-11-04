"""One pass over a `dw.workflow/v1` document: every problem at once (wf-lite R3,
R4; workflow-engine R1, R2; ADR-0112 decision 3 and Amendments 2026-11-03).

A problem is `{path, code, message_vi, message_en}`, the path into the
document as written (`steps/2/config/approved/0/config/input`), each segment
escaped as a JSON pointer's is. The codes are stable; the words are for a
person. `MESSAGES` is the repository's one table of `wf.*` codes: a check
elsewhere (`dw_studio`, a later ticket) builds its problem with `Problem.of`.

The pass runs over the document's `WorkflowIR` (`wflite.ir.lower`), the IR
the compiler builds from, so the tree checked is the tree compiled (R2.12).
"Comes before on every path" is dominance on that IR: a step in one lane of a
block is on no path through another lane, nor after the block, and a step of
an error lane is not after the step that failed into it. "Inside the approved
lane" of a gate means in that lane, or in a lane nested in it, at any depth.

What differs between a pack and a Studio document is a `PathRules`, never a
second validator: the caller passes one, and the HITL floor runs the same on
every path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import ValidationError

from dw_agent_runtime.tool_specs import ToolSpec
from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.ir import (
    ERROR_LANE,
    IRStep,
    WorkflowIR,
    dominators,
    join_path,
    lower,
    reachable,
    segment,
)
from dw_agent_runtime.wflite.registry import JsonSchema, NodeTypeSpec
from dw_kernel.errors import NotFoundError
from dw_platform.application.json_schema import problems as schema_problems

_EFFECT_RANK = {"none": 0, "internal": 1, "external": 2, "critical": 3}
_GATED = frozenset({"external", "critical"})
# A reference replaces a whole value and nothing else (R3.7, ADR-0114).
_REFERENCE = re.compile(
    r"^\{\{\s*(steps|work|params)\.([A-Za-z0-9_]+)(?:\.([A-Za-z0-9_]+))?\s*\}\}$"
)
# A config key holding a JSON Schema, which no reference fills. Lane keys are
# the IR's to name, per step.
_SCHEMA_KEYS = frozenset({"output_schema"})
# Two prefixes the compiler names its own nodes with (`compile.py`).
_RESERVED_PREFIXES = ("join__", "wait__")
# A lane a block may leave out under `every_port_lane`: a loop's way out
# when its cap is reached (R2.2). The error lane is the step's own key.
_OPTIONAL_PORTS = frozenset({"max_reached"})

MESSAGES: Mapping[str, tuple[str, str]] = {
    "wf.schema_invalid": ("Tài liệu sai cấu trúc: {detail}", "The document is malformed: {detail}"),
    "wf.duplicate_step_id": ("Hai bước cùng id {detail}", "Two steps share the id {detail}"),
    "wf.unknown_type": ("Loại bước không có: {detail}", "No such step type: {detail}"),
    "wf.config_invalid": ("Cấu hình bước sai: {detail}", "The step's config is invalid: {detail}"),
    "wf.ref_not_dominating": (
        "Bước {detail} không chắc đã chạy trước chỗ này",
        "Step {detail} has not run on every path to here",
    ),
    "wf.ref_unknown": ("Tham chiếu không có: {detail}", "Unknown reference: {detail}"),
    "wf.router_not_total": (
        "Bước thiếu làn cho nhánh ra {detail}",
        "The step has no lane for its port {detail}",
    ),
    "wf.unreachable_node": (
        "Không đường nào tới được bước {detail}",
        "No path reaches step {detail}",
    ),
    "wf.limit_above_plan": (
        "Quy trình vượt trần của nền tảng: {detail}",
        "The workflow goes past the platform's cap: {detail}",
    ),
    "wf.tool_unknown": ("Công cụ không có: {detail}", "No such tool: {detail}"),
    "wf.decision_class_undeclared": (
        "Loại quyết định chưa khai: {detail}",
        "Undeclared decision class: {detail}",
    ),
    "wf.hitl_gate_missing": (
        "Hiệu ứng ra ngoài {detail} không nằm trong lane Duyệt của cổng cùng loại quyết định",
        "Outward effect {detail} is not inside the approved lane of a gate of its decision class",
    ),
    "wf.effect_above_class": (
        "Công cụ {detail} vượt mức hiệu ứng của loại quyết định",
        "Tool {detail} goes beyond its decision class's effect level",
    ),
    "wf.unapproved_input": (
        "Đầu vào của {detail} không phải nguyên bản đã duyệt",
        "The input of {detail} is not exactly what was approved",
    ),
    "wf.param_undeclared": ("Tham số chưa khai: {detail}", "Undeclared parameter: {detail}"),
    # The assistant's own checks (wf-ai R2.2, R2.3): it composes from what the
    # pack's workflow already uses, never a new tool or prompt.
    "wf.tool_not_in_base": (
        "Công cụ {detail} không có trong quy trình gốc",
        "Tool {detail} is not used by the base workflow",
    ),
    "wf.prompt_not_in_base": (
        "Prompt {detail} không có trong quy trình gốc",
        "Prompt {detail} is not used by the base workflow",
    ),
}


@dataclass(frozen=True, slots=True)
class Problem:
    path: str
    code: str
    message_vi: str
    message_en: str

    @classmethod
    def of(cls, path: str, code: str, detail: object = "") -> Problem:
        vi, en = MESSAGES[code]
        return cls(path, code, vi.format(detail=detail), en.format(detail=detail))

    def as_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "code": self.code,
            "message_vi": self.message_vi,
            "message_en": self.message_en,
        }


class ToolSpecLookup(Protocol):
    """What the validator asks of the tool register (`ToolSpecRegistry`)."""

    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> ToolSpec: ...


@dataclass(frozen=True)
class PathRules:
    """What one path requires and refuses of a document (R2.2; ADR-0112
    Amendments 2026-11-03). Step keys apply to every step of the `steps[]`
    tree; `every_port_lane` asks each port its type lists for a lane, `[]`
    counting as one. A violation is `wf.schema_invalid` at the key."""

    required_document_keys: frozenset[str]
    refused_document_keys: frozenset[str]
    required_step_keys: frozenset[str]
    refused_step_keys: frozenset[str]
    every_port_lane: bool


# A step's own policy. Refused on a trigger on every path: nothing runs it.
STEP_POLICY_KEYS: Final = frozenset({"retry", "timeout_s", "on_error", ERROR_LANE})

# A pack and a wf-ai proposal: the file names its key and version, and the
# wf-lite compiler runs none of a step's own policy yet (workflow-engine 03
# loosens this as it does), so a key nobody would read is refused. An
# approval's empty lane may be left out, as wf-ai's wire leaves `rejected`.
PACK_RULES: Final = PathRules(
    required_document_keys=frozenset({"key", "version"}),
    refused_document_keys=frozenset(),
    required_step_keys=frozenset(),
    refused_step_keys=STEP_POLICY_KEYS,
    every_port_lane=False,
)


@dataclass(frozen=True)
class _Gate:
    step_id: str
    decision_class: str


def validate(
    raw: Mapping[str, Any],
    *,
    registry: Mapping[str, NodeTypeSpec],
    rules: PathRules,
    tools: ToolSpecLookup,
    work_schemas: Mapping[str, JsonSchema],
    file_key: tuple[str, str] | None = None,
) -> list[Problem]:
    """Every problem of `raw` on the path `rules` describes, empty when it is
    valid. `work_schemas` is the JSON Schema of each declared kind;
    `file_key` the `(key, version)` the file's name states."""
    try:
        document = WorkflowDocument.model_validate(raw)
    except ValidationError as exc:
        return [
            Problem.of(
                join_path(*(segment(p) for p in error["loc"])), "wf.schema_invalid", error["msg"]
            )
            for error in exc.errors()
        ]
    found = _document_rules(document, rules)
    if file_key is not None and file_key != (document.key, document.version):
        found.append(
            Problem.of(
                "version",
                "wf.schema_invalid",
                f"{document.key}@{document.version} ≠ {file_key[0]}@{file_key[1]}",
            )
        )
    return found + _Check(document, registry, rules, tools, work_schemas).run()


def _document_rules(document: WorkflowDocument, rules: PathRules) -> list[Problem]:
    found = [
        Problem.of(key, "wf.schema_invalid", f"{key} is required here")
        for key in sorted(rules.required_document_keys)
        if getattr(document, key) is None
    ]
    found += [
        Problem.of(key, "wf.schema_invalid", f"{key} is not allowed here")
        for key in sorted(rules.refused_document_keys & document.model_fields_set)
    ]
    return found


def _present(config: Mapping[str, Any], keys: Sequence[str]) -> bool:
    here: Any = config
    for key in keys:
        if not isinstance(here, Mapping) or key not in here:
            return False
        here = here[key]
    return True


class _Check:
    def __init__(
        self,
        document: WorkflowDocument,
        registry: Mapping[str, NodeTypeSpec],
        rules: PathRules,
        tools: ToolSpecLookup,
        work_schemas: Mapping[str, JsonSchema],
    ) -> None:
        self.document = document
        self.registry = registry
        self.rules = rules
        self.tools = tools
        self.classes = {c.key: c for c in document.decision_classes}
        self.variables = {v.name for v in document.variables}
        self.problems: list[Problem] = []
        self.ir: WorkflowIR = lower(document, registry)
        self.reach = reachable(self.ir)
        self.doms = dominators(self.ir)
        # Every step and trigger by id: the first of a repeated id.
        self.placed: dict[str, IRStep] = {}
        kinds = [
            str(t.config.get("kind"))
            for t in document.triggers
            if t.type == "trigger.work_item@1" and isinstance(t.config.get("kind"), str)
        ]
        schema = work_schemas.get(kinds[0]) if kinds else None
        properties = (schema or {}).get("properties") if schema else None
        self.work_fields = frozenset(properties) if isinstance(properties, Mapping) else frozenset()

    def run(self) -> list[Problem]:
        for issue in self.ir.issues:
            self._add(issue.path, issue.code, issue.detail)
        for trigger in self.ir.triggers:
            self._trigger(trigger)
        for placed in self.ir.steps:
            self._place(placed)
        for placed in self.ir.steps:
            self._shape(placed)
            self._step(placed)
        return self.problems

    def _add(self, path: str, code: str, detail: object = "") -> None:
        self.problems.append(Problem.of(path, code, detail))

    # ------------------------------------------------------- ids and shape --

    def _place(self, placed: IRStep) -> None:
        step = placed.step
        if step.id in self.placed:
            self._add(join_path(placed.path, "id"), "wf.duplicate_step_id", step.id)
        else:
            self.placed[step.id] = placed
        if step.id.startswith(_RESERVED_PREFIXES):
            self._add(
                join_path(placed.path, "id"),
                "wf.schema_invalid",
                f"a step id may not begin with {' or '.join(_RESERVED_PREFIXES)}",
            )

    def _trigger(self, placed: IRStep) -> None:
        trigger, path = placed.step, placed.path
        self._place(placed)
        for key in sorted(STEP_POLICY_KEYS & trigger.model_fields_set):
            self._add(join_path(path, key), "wf.schema_invalid", f"a trigger has no {key}")
        spec = placed.spec
        if spec is None:
            self._add(join_path(path, "type"), "wf.unknown_type", trigger.type)
        elif not spec.is_trigger:
            self._add(join_path(path, "type"), "wf.config_invalid", "not a trigger")
        else:
            self._config(trigger, spec, path)

    def _shape(self, placed: IRStep) -> None:
        """This path's rules, the error lane's consistency (R1.8), and a lane
        for every port (R2.2) when the path asks for one."""
        step, path = placed.step, placed.path
        for key in sorted(self.rules.refused_step_keys & step.model_fields_set):
            self._add(join_path(path, key), "wf.schema_invalid", f"{key} is not allowed here")
        for key in sorted(self.rules.required_step_keys):
            if getattr(step, key) is None:
                self._add(join_path(path, key), "wf.schema_invalid", f"{key} is required")
        has_error_lane = any(lane.is_error for lane, _ in placed.lanes)
        if has_error_lane and step.on_error != "route":
            self._add(
                join_path(path, ERROR_LANE),
                "wf.schema_invalid",
                "an error lane is taken only with on_error: route",
            )
        if step.on_error == "route" and not has_error_lane:
            self._add(
                join_path(path, "on_error"), "wf.schema_invalid", "on_error: route needs a lane"
            )
        if self.rules.every_port_lane and placed.spec is not None:
            for lane, _ in placed.lanes:
                if lane.is_error or lane.port in _OPTIONAL_PORTS:
                    continue
                if not _present(step.config, lane.at[1:]):
                    self._add(join_path(path, "config"), "wf.router_not_total", lane.port)
        if placed.index not in self.reach:
            self._add(path, "wf.unreachable_node", step.id)

    # ------------------------------------------------------------ the step --

    def _gates(self, placed: IRStep) -> tuple[_Gate, ...]:
        """The approvals whose approved lane holds `placed`, outermost first."""
        inward = [
            _Gate(above.step.id, str(above.step.config.get("decision_class")))
            for above, port in self.ir.ancestors(placed.index)
            if above.step.type == "human.approval@1" and port == "approved"
        ]
        return tuple(reversed(inward))

    def _step(self, placed: IRStep) -> None:
        step, path, spec = placed.step, placed.path, placed.spec
        if spec is None:
            self._add(join_path(path, "type"), "wf.unknown_type", step.type)
            return
        if spec.is_trigger:
            self._add(join_path(path, "type"), "wf.config_invalid", "a trigger among the steps")
            return
        if not self._config(step, spec, path):
            return
        config = step.config
        if step.type == "logic.switch@1" and not isinstance(config.get("default"), list):
            self._add(join_path(path, "config"), "wf.router_not_total", "default")
        if step.type in ("tool.call@1", "human.approval@1"):
            cls = str(config.get("decision_class"))
            if cls not in self.classes:
                self._add(
                    join_path(path, "config", "decision_class"),
                    "wf.decision_class_undeclared",
                    cls,
                )
        if step.type == "tool.call@1":
            self._tool_call(step, path, self._gates(placed))
        if step.type == "ai.llm@1" and "min_confidence" in config:
            self._confidence(config, path)
        if step.type == "time.wait@1" and "seconds_param" in config:
            name = str(config["seconds_param"])
            if name not in self.variables:
                self._add(join_path(path, "config", "seconds_param"), "wf.param_undeclared", name)
        skipped = _SCHEMA_KEYS | {lane.at[1] for lane, _ in placed.lanes if not lane.is_error}
        for key, value in config.items():
            if key not in skipped:
                self._references(value, join_path(path, "config", segment(key)), placed)

    def _config(self, step: Step, spec: NodeTypeSpec, path: str) -> bool:
        found = schema_problems(spec.config_schema, step.config)
        for problem in found:
            self._add(join_path(path, "config"), "wf.config_invalid", problem)
        return not found

    def _tool_fields(self, step: Step) -> set[str]:
        """The output fields a `tool.call` step's tool declares (`output_fields`)."""
        if step.type != "tool.call@1":
            return set()
        name, _, version = str(step.config.get("tool", "")).partition("@")
        try:
            return set(getattr(self.tools.resolve(name, version), "output_fields", ()) or ())
        except NotFoundError:
            return set()

    # ------------------------------------------------------- the HITL floor --

    def _tool_call(self, step: Step, path: str, gates: tuple[_Gate, ...]) -> None:
        name, _, version = str(step.config["tool"]).partition("@")
        try:
            tool = self.tools.resolve(name, version)
        except NotFoundError:
            self._add(join_path(path, "config", "tool"), "wf.tool_unknown", step.config["tool"])
            return
        cls = self.classes.get(str(step.config["decision_class"]))
        if (
            cls is not None
            and _EFFECT_RANK[tool.side_effect_level] > _EFFECT_RANK[cls.effect_level]
        ):
            self._add(
                join_path(path, "config", "tool"), "wf.effect_above_class", step.config["tool"]
            )
        if tool.side_effect_level not in _GATED:
            return
        gate = next(
            (g for g in reversed(gates) if g.decision_class == step.config["decision_class"]), None
        )
        if gate is None:
            self._add(path, "wf.hitl_gate_missing", step.id)
            return
        approved = f"{{{{ steps.{gate.step_id}.proposal }}}}"
        given = step.config["input"]
        if not (isinstance(given, str) and _normalised(given) == _normalised(approved)):
            self._add(join_path(path, "config", "input"), "wf.unapproved_input", step.id)

    def _confidence(self, config: Mapping[str, Any], path: str) -> None:
        schema = config.get("output_schema") or {}
        confidence = (schema.get("properties") or {}).get("confidence") or {}
        ok = (
            "confidence" in (schema.get("required") or [])
            and confidence.get("type") == "number"
            and confidence.get("minimum") == 0
            and confidence.get("maximum") == 1
        )
        if not ok:
            self._add(
                join_path(path, "config", "min_confidence"),
                "wf.config_invalid",
                "min_confidence needs a required number `confidence` between 0 and 1",
            )

    # -------------------------------------------------------- references --

    def _references(self, value: Any, path: str, at: IRStep) -> None:
        if isinstance(value, Mapping):
            for key, inner in value.items():
                self._references(inner, join_path(path, segment(key)), at)
        elif isinstance(value, list):
            for i, inner in enumerate(value):
                self._references(inner, join_path(path, i), at)
        elif isinstance(value, str) and ("{{" in value or "}}" in value):
            match = _REFERENCE.fullmatch(value.strip())
            if match is None:
                self._add(path, "wf.config_invalid", "a reference replaces a whole value")
                return
            self._reference(match, path, at)

    def _dominates(self, target: IRStep, at: IRStep) -> bool:
        """`target` has run on every path to `at` (R2.5). Where no path
        reaches `at`, its own problem says so and no reference is judged."""
        if target.depth == 0:  # a trigger: no node of the graph
            return False
        if at.index not in self.reach:
            return True
        return target.index != at.index and self.doms.dominates(target.index, at.index)

    def _reference(self, match: re.Match[str], path: str, at: IRStep) -> None:
        root, name, field = match.group(1), match.group(2), match.group(3)
        text = match.group(0)
        if root == "params":
            if field is not None or name not in self.variables:
                self._add(path, "wf.param_undeclared", text)
        elif root == "work":
            if field is not None or name not in self.work_fields:
                self._add(path, "wf.ref_unknown", text)
        else:
            placed = self.placed.get(name)
            if placed is None or field is None:
                self._add(path, "wf.ref_unknown", text)
            elif not self._dominates(placed, at):
                self._add(path, "wf.ref_not_dominating", name)
            else:
                spec = placed.spec
                output = spec.output_schema(placed.step.config) if spec is not None else {}
                known = set(output.get("properties") or {}) | self._tool_fields(placed.step)
                if field not in known:
                    self._add(path, "wf.ref_unknown", text)


def _normalised(reference: str) -> str:
    return re.sub(r"\s+", "", reference)


__all__ = [
    "MESSAGES",
    "PACK_RULES",
    "STEP_POLICY_KEYS",
    "PathRules",
    "Problem",
    "ToolSpecLookup",
    "validate",
]
