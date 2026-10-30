"""One pass over a `dw.workflow/v1` document: every problem at once (wf-lite R3,
R4; ADR-0112 decision 3).

A problem is `{path, code, message_vi, message_en}`, the path into the
document as written (`steps/2/config/approved/0/config/input`). The codes are
stable; the words are for a person.

What "comes before on every path" means on a tree: the steps before a step in
its own list, the step whose lane holds it (and so on outwards), and the steps
before each of those in their lists. A step inside one lane of a switch is on
no path through another lane, nor after the switch. What "inside the approved
lane" of a gate means: in that lane's list, or in a block nested in it, at any
depth.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from dw_agent_runtime.tool_specs import ToolSpec
from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.registry import JsonSchema, NodeTypeSpec
from dw_kernel.errors import NotFoundError
from dw_platform.application.json_schema import problems as schema_problems

_EFFECT_RANK = {"none": 0, "internal": 1, "external": 2, "critical": 3}
_GATED = frozenset({"external", "critical"})
# A reference replaces a whole value and nothing else (R3.7, ADR-0114).
_REFERENCE = re.compile(
    r"^\{\{\s*(steps|work|params)\.([A-Za-z0-9_]+)(?:\.([A-Za-z0-9_]+))?\s*\}\}$"
)
# Config keys that hold a schema or lanes, not values that may reference.
_NOT_VALUES = frozenset({"output_schema", "approved", "rejected", "cases", "default"})

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
        "Rẽ nhánh thiếu lane mặc định",
        "The switch has no default lane",
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
class _Gate:
    step_id: str
    decision_class: str


@dataclass(frozen=True)
class _Placed:
    step: Step
    path: str


def _join(*parts: object) -> str:
    return "/".join(str(p) for p in parts if p != "")


def validate(
    raw: Mapping[str, Any],
    *,
    registry: Mapping[str, NodeTypeSpec],
    tools: ToolSpecLookup,
    work_schemas: Mapping[str, JsonSchema],
    file_key: tuple[str, str] | None = None,
) -> list[Problem]:
    """Every problem of `raw`, empty when it is valid. `work_schemas` is the
    JSON Schema of each declared kind; `file_key` the `(key, version)` the
    file's name states."""
    try:
        document = WorkflowDocument.model_validate(raw)
    except ValidationError as exc:
        return [
            Problem.of(_join(*error["loc"]), "wf.schema_invalid", error["msg"])
            for error in exc.errors()
        ]
    found: list[Problem] = []
    if file_key is not None and file_key != (document.key, document.version):
        found.append(
            Problem.of(
                "version",
                "wf.schema_invalid",
                f"{document.key}@{document.version} ≠ {file_key[0]}@{file_key[1]}",
            )
        )
    return found + _Check(document, registry, tools, work_schemas).run()


class _Check:
    def __init__(
        self,
        document: WorkflowDocument,
        registry: Mapping[str, NodeTypeSpec],
        tools: ToolSpecLookup,
        work_schemas: Mapping[str, JsonSchema],
    ) -> None:
        self.document = document
        self.registry = registry
        self.tools = tools
        self.classes = {c.key: c for c in document.decision_classes}
        self.variables = {v.name for v in document.variables}
        self.problems: list[Problem] = []
        self.placed: dict[str, _Placed] = {}
        kinds = [
            str(t.config.get("kind"))
            for t in document.triggers
            if t.type == "trigger.work_item@1" and isinstance(t.config.get("kind"), str)
        ]
        schema = work_schemas.get(kinds[0]) if kinds else None
        properties = (schema or {}).get("properties") if schema else None
        self.work_fields = frozenset(properties) if isinstance(properties, Mapping) else frozenset()

    def run(self) -> list[Problem]:
        for i, trigger in enumerate(self.document.triggers):
            self._place(trigger, _join("triggers", i))
            spec = self.registry.get(trigger.type)
            if spec is None:
                self._add(_join("triggers", i, "type"), "wf.unknown_type", trigger.type)
            elif not spec.is_trigger:
                self._add(_join("triggers", i, "type"), "wf.config_invalid", "not a trigger")
            else:
                self._config(trigger, spec, _join("triggers", i))
        self._index(self.document.steps, "steps")
        self._walk(self.document.steps, "steps", frozenset(), ())
        return self.problems

    def _add(self, path: str, code: str, detail: object = "") -> None:
        self.problems.append(Problem.of(path, code, detail))

    # ---------------------------------------------------- the tree's index --

    def _steps_of(self, raw_list: Sequence[Any], path: str) -> Iterator[tuple[int, Step]]:
        for i, raw in enumerate(raw_list):
            if isinstance(raw, Step):
                yield i, raw
                continue
            try:
                yield i, Step.model_validate(raw)
            except ValidationError as exc:
                for error in exc.errors():
                    self._add(_join(path, i, *error["loc"]), "wf.schema_invalid", error["msg"])

    def _place(self, step: Step, path: str) -> None:
        if step.id in self.placed:
            self._add(_join(path, "id"), "wf.duplicate_step_id", step.id)
        else:
            self.placed[step.id] = _Placed(step, path)

    def _index(self, raw_list: Sequence[Any], path: str) -> None:
        """Every step of the tree by id, so a reference to one that exists
        but does not come first reads apart from one that does not exist."""
        for i, step in self._steps_of(raw_list, path):
            here = _join(path, i)
            self._place(step, here)
            spec = self.registry.get(step.type)
            if spec is not None:
                for port, lane in spec.lanes(step.config).items():
                    self._index(lane, _join(here, "config", port.replace(".", "/")))

    # ------------------------------------------------------------ the walk --

    def _walk(
        self,
        raw_list: Sequence[Any],
        path: str,
        visible: frozenset[str],
        gates: tuple[_Gate, ...],
    ) -> None:
        seen = set(visible)
        for i, step in self._steps_of_quiet(raw_list):
            here = _join(path, i)
            self._step(step, here, frozenset(seen), gates)
            spec = self.registry.get(step.type)
            if spec is not None:
                inner = frozenset(seen | {step.id})
                for port, lane in spec.lanes(step.config).items():
                    lane_gates = gates
                    if step.type == "human.approval@1" and port == "approved":
                        lane_gates = (
                            *gates,
                            _Gate(step.id, str(step.config.get("decision_class"))),
                        )
                    lane_path = _join(here, "config", port.replace(".", "/"))
                    self._walk(lane, lane_path, inner, lane_gates)
            seen.add(step.id)

    def _steps_of_quiet(self, raw_list: Sequence[Any]) -> Iterator[tuple[int, Step]]:
        # The index pass already reported what does not parse.
        for i, raw in enumerate(raw_list):
            if isinstance(raw, Step):
                yield i, raw
                continue
            try:
                yield i, Step.model_validate(raw)
            except ValidationError:
                continue

    def _step(
        self, step: Step, path: str, visible: frozenset[str], gates: tuple[_Gate, ...]
    ) -> None:
        spec = self.registry.get(step.type)
        if spec is None:
            self._add(_join(path, "type"), "wf.unknown_type", step.type)
            return
        if spec.is_trigger:
            self._add(_join(path, "type"), "wf.config_invalid", "a trigger among the steps")
            return
        if not self._config(step, spec, path):
            return
        config = step.config
        if step.type == "logic.switch@1" and not isinstance(config.get("default"), list):
            self._add(_join(path, "config"), "wf.router_not_total")
        if step.type in ("tool.call@1", "human.approval@1"):
            cls = str(config.get("decision_class"))
            if cls not in self.classes:
                self._add(
                    _join(path, "config", "decision_class"), "wf.decision_class_undeclared", cls
                )
        if step.type == "tool.call@1":
            self._tool_call(step, path, gates)
        if step.type == "ai.llm@1" and "min_confidence" in config:
            self._confidence(config, path)
        if step.type == "time.wait@1" and "seconds_param" in config:
            name = str(config["seconds_param"])
            if name not in self.variables:
                self._add(_join(path, "config", "seconds_param"), "wf.param_undeclared", name)
        self._references(config, _join(path, "config"), visible)

    def _config(self, step: Step, spec: NodeTypeSpec, path: str) -> bool:
        found = schema_problems(spec.config_schema, step.config)
        for problem in found:
            self._add(_join(path, "config"), "wf.config_invalid", problem)
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
            self._add(_join(path, "config", "tool"), "wf.tool_unknown", step.config["tool"])
            return
        cls = self.classes.get(str(step.config["decision_class"]))
        if (
            cls is not None
            and _EFFECT_RANK[tool.side_effect_level] > _EFFECT_RANK[cls.effect_level]
        ):
            self._add(_join(path, "config", "tool"), "wf.effect_above_class", step.config["tool"])
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
            self._add(_join(path, "config", "input"), "wf.unapproved_input", step.id)

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
                _join(path, "config", "min_confidence"),
                "wf.config_invalid",
                "min_confidence needs a required number `confidence` between 0 and 1",
            )

    # -------------------------------------------------------- references --

    def _references(self, value: Any, path: str, visible: frozenset[str]) -> None:
        if isinstance(value, Mapping):
            for key, inner in value.items():
                if key in _NOT_VALUES and path.endswith("config"):
                    continue
                self._references(inner, _join(path, key), visible)
        elif isinstance(value, list):
            for i, inner in enumerate(value):
                self._references(inner, _join(path, i), visible)
        elif isinstance(value, str) and ("{{" in value or "}}" in value):
            match = _REFERENCE.fullmatch(value.strip())
            if match is None:
                self._add(path, "wf.config_invalid", "a reference replaces a whole value")
                return
            self._reference(match, path, visible)

    def _reference(self, match: re.Match[str], path: str, visible: frozenset[str]) -> None:
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
            elif name not in visible:
                self._add(path, "wf.ref_not_dominating", name)
            else:
                spec = self.registry.get(placed.step.type)
                output = spec.output_schema(placed.step.config) if spec is not None else {}
                known = set(output.get("properties") or {}) | self._tool_fields(placed.step)
                if field not in known:
                    self._add(path, "wf.ref_unknown", text)


def _normalised(reference: str) -> str:
    return re.sub(r"\s+", "", reference)
