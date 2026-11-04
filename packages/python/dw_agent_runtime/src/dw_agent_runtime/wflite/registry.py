"""The step-type registry of `dw.workflow/v1`: ADR-0112 decision 2's one
`NodeTypeRegistry` (workflow-nodes R1; wf-lite R2).

One registry, built by one function, read by the validator, the compiler and
Studio's step-type catalogue, so none of them can disagree about what a type
is. workflow-nodes owns it (ticket 02); it sits in the platform core because
the core's validator and compiler read it and the core may not import
`dw_studio`. A type is its Vietnamese label, its config schema, its output
(fixed, or taken from the step's config) and its ports, both declared as data
so the catalogue can publish them; the ports whose lanes a step of it holds;
and the side effect it has by itself (`tool.call`'s comes from the tool it
calls).

A lane is a list of steps in the step's `config` under the port's name; a
config schema says only that it is an array, and the validator walks it.
A port named `a.b` sits at `config[a][b]` (a switch's `cases.<value>`).

What the lowering to `WorkflowIR` needs of a type is declared here, never read
from its name (workflow-engine R2.1; ADR-0112 Amendments 2026-11-03): `block`
(does a step of it run one lane, every lane, or loop over `body`), `ends_run`
and `exits_loop`; `dependencies` is what a step of it uses that Studio's
where-used index records (workflow-engine R1.3). The four have no default, so
a type that forgot one cannot be built.

Every field has a named reader (workflow-nodes R1.4, WN15):
`dw_studio/tests/workflows/test_node_registry.py` holds the table, and a field
joins this class only with its first reader, in the same change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, TypedDict, get_args

from dw_agent_runtime.contracts import SideEffectLevel
from dw_agent_runtime.wflite.document import OnError
from dw_kernel.canonical import content_hash

JsonSchema = Mapping[str, Any]

_LANE: JsonSchema = {"type": "array", "items": {"type": "object"}}
_PROMPT_ID = r"^[a-z][a-z0-9_.]*@(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_TOOL_ID = _PROMPT_ID
_REFERENCE_OR_TEXT: JsonSchema = {"type": "string", "minLength": 1}
_EMPTY_OUTPUT: JsonSchema = {"type": "object", "properties": {}}


Block = Literal["none", "choice", "parallel", "loop"]


@dataclass(frozen=True, slots=True)
class StepDependency:
    """One use a step makes of something Studio records (`studio.dependencies`):
    `to_kind` and `usage` are that table's words, `path` a JSON pointer inside
    the step's `config`. The Studio extractor turns it into its `Reference`."""

    to_kind: str
    to_key: str
    usage: str
    path: str


Dependencies = Callable[[Mapping[str, Any]], tuple[StepDependency, ...]]


def no_dependencies(config: Mapping[str, Any]) -> tuple[StepDependency, ...]:
    """A type whose tools and prompts are the platform's, not Studio artifacts."""
    return ()


# ---------------------------------------------------------------------------
# What a step of a type outputs, and the lanes it holds: data, not functions
# (workflow-nodes R1.2, R1.5), so the catalogue publishes exactly what the
# validator and the compiler compute from.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixedOutput:
    """The output every step of the type has."""

    schema: JsonSchema


@dataclass(frozen=True, slots=True)
class OutputFromConfig:
    """The output a step declares in its own config under `key` (an
    `ai.llm@1`'s `output_schema`); an empty object when it declares none."""

    key: str


Output = FixedOutput | OutputFromConfig


@dataclass(frozen=True, slots=True)
class Port:
    """One outcome a step leaves by ("Nhánh ra"): its lane sits in the
    step's config under `name`, and a person reads it as `label_vi`."""

    name: str
    label_vi: str


@dataclass(frozen=True, slots=True)
class FixedPorts:
    """The same ports on every step of the type, each lane `[]` when the
    config leaves it out (`human.approval@1`'s `approved` and `rejected`)."""

    ports: tuple[Port, ...] = ()


@dataclass(frozen=True, slots=True)
class KeyedPorts:
    """One port per key of the object under `key`, named `<key>.<k>` and read
    as `k` (`logic.switch@1`'s `cases`), and `default` when the config holds a
    list under its name."""

    key: str
    default: Port | None = None


Ports = FixedPorts | KeyedPorts

NO_PORTS = FixedPorts()


@dataclass(frozen=True, kw_only=True)
class NodeTypeSpec:
    type: str
    # How a person reads the type in the catalogue.
    label_vi: str
    config_schema: JsonSchema
    # The fields a later step may reference: `output_schema(config)`.
    output: Output
    # The lanes a step of this type holds: `lanes(config)`.
    ports: Ports
    # How the lowering wires a step of this type (`wflite.ir`): `choice` runs
    # one lane, `parallel` every lane, `loop` its `body` lane again and again.
    block: Block
    # No edge leaves a step that ends the run; one that exits its loop goes
    # to the loop's join. A step after either in its lane is unreachable.
    ends_run: bool
    exits_loop: bool
    dependencies: Dependencies
    side_effect_level: SideEffectLevel = "none"
    is_trigger: bool = False

    def output_schema(self, config: Mapping[str, Any]) -> JsonSchema:
        """The output of a step of this type with `config`, from `output`."""
        match self.output:
            case FixedOutput(schema):
                return schema
            case OutputFromConfig(key):
                found = config.get(key)
                return found if isinstance(found, Mapping) else _EMPTY_OUTPUT

    def lanes(self, config: Mapping[str, Any]) -> Mapping[str, list[Any]]:
        """The ports whose lanes a step of this type holds, from `ports`.
        Called by `wflite.ir.iter_lanes` and nothing else."""
        match self.ports:
            case FixedPorts(ports):
                return {port.name: _lane(config.get(port.name)) for port in ports}
            case KeyedPorts(key, default):
                found: dict[str, list[Any]] = {}
                keyed = config.get(key)
                if isinstance(keyed, Mapping):
                    for name, items in keyed.items():
                        found[f"{key}.{name}"] = _lane(items)
                if default is not None and isinstance(config.get(default.name), list):
                    found[default.name] = list(config[default.name])
                return found


def _lane(items: object) -> list[Any]:
    return list(items) if isinstance(items, list) else []


# ---------------------------------------------------------------------------
# A step's output with its error policy (workflow-nodes R1.5)
# ---------------------------------------------------------------------------

# What a step that failed under `continue` or `route` publishes beside its
# output: the code and its Vietnamese label (spec Quyết định 26/10/2026 H-21),
# never a provider's or a binding's text.
ERROR_OUTPUT: JsonSchema = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
    "additionalProperties": False,
}
_PUBLISHES_ERROR: frozenset[str] = frozenset({"continue", "route"})


def step_output_schema(
    spec: NodeTypeSpec, config: Mapping[str, Any], on_error: OnError | None
) -> JsonSchema:
    """The output of one step: its type's, plus `error` when its error policy
    lets a later step read why it failed (`continue`: the next step; `route`:
    the steps of its error lane). No `on_error` is `fail` (R2.3), and a step
    that fails under `fail` ends the run, so nothing reads an `error`."""
    output = spec.output_schema(config)
    if (on_error or "fail") not in _PUBLISHES_ERROR:
        return output
    properties = output.get("properties")
    return {
        **output,
        "properties": {
            **(properties if isinstance(properties, Mapping) else {}),
            "error": ERROR_OUTPUT,
        },
    }


# ---------------------------------------------------------------------------
# The six types of wf-lite
# ---------------------------------------------------------------------------


class _Shape(TypedDict):
    block: Block
    ends_run: bool
    exits_loop: bool
    dependencies: Dependencies


# The six types of wf-lite: two run one of their lanes, none ends the run or
# leaves a loop, and none uses a Studio artifact.
_PLAIN: _Shape = {
    "block": "none",
    "ends_run": False,
    "exits_loop": False,
    "dependencies": no_dependencies,
}
_CHOICE: _Shape = {**_PLAIN, "block": "choice"}


def _wf_lite_types() -> tuple[NodeTypeSpec, ...]:
    """Exactly the six types of the first slice; no more (wf-lite R2.1)."""
    return (
        NodeTypeSpec(
            type="trigger.work_item@1",
            label_vi="Khi có việc mới",
            config_schema={
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            output=FixedOutput({"type": "object", "properties": {}}),
            ports=NO_PORTS,
            is_trigger=True,
            **_PLAIN,
        ),
        NodeTypeSpec(
            type="ai.llm@1",
            label_vi="AI soạn",
            config_schema={
                "type": "object",
                "required": ["prompt", "inputs", "output_schema"],
                "properties": {
                    "prompt": {"type": "string", "pattern": _PROMPT_ID},
                    "inputs": {"type": "object"},
                    "output_schema": {"type": "object"},
                    # A number, or the DW's parameter that holds one (leadcare R1.1).
                    "min_confidence": {
                        "oneOf": [
                            {"type": "number", "minimum": 0, "maximum": 1},
                            {
                                "type": "string",
                                "pattern": r"^\{\{\s*params\.[a-z][a-z0-9_]*\s*\}\}$",
                            },
                        ]
                    },
                },
                "additionalProperties": False,
            },
            output=OutputFromConfig("output_schema"),
            ports=NO_PORTS,
            **_PLAIN,
        ),
        NodeTypeSpec(
            type="tool.call@1",
            label_vi="Công cụ",
            config_schema={
                "type": "object",
                "required": ["tool", "input", "decision_class"],
                "properties": {
                    "tool": {"type": "string", "pattern": _TOOL_ID},
                    "input": {"type": ["string", "object"]},
                    "decision_class": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            # The node writes the tool's typed output under `result`.
            output=FixedOutput({"type": "object", "properties": {"result": {}}}),
            ports=NO_PORTS,
            **_PLAIN,
        ),
        NodeTypeSpec(
            type="human.approval@1",
            label_vi="Người duyệt",
            config_schema={
                "type": "object",
                "required": ["decision_class", "proposal"],
                "properties": {
                    "decision_class": {"type": "string", "minLength": 1},
                    "proposal": {"type": ["string", "object"]},
                    "locked_fields": {"type": "array", "items": {"type": "string"}},
                    "approved": _LANE,
                    "rejected": _LANE,
                },
                "additionalProperties": False,
            },
            # What was approved, edited or not (D18), and the decision.
            output=FixedOutput(
                {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                        "approved": {"type": "boolean"},
                        "comment": {"type": "string"},
                    },
                }
            ),
            ports=FixedPorts((Port("approved", "Duyệt"), Port("rejected", "Từ chối"))),
            **_CHOICE,
        ),
        NodeTypeSpec(
            type="time.wait@1",
            label_vi="Chờ",
            config_schema={
                "type": "object",
                "oneOf": [{"required": ["seconds"]}, {"required": ["seconds_param"]}],
                "properties": {
                    "seconds": {"type": "integer", "minimum": 1, "maximum": 2_592_000},
                    "seconds_param": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            output=FixedOutput({"type": "object", "properties": {"woke_at": {"type": "string"}}}),
            ports=NO_PORTS,
            **_PLAIN,
        ),
        NodeTypeSpec(
            type="logic.switch@1",
            label_vi="Rẽ nhánh",
            config_schema={
                # `default` is not required here: its absence has its own code,
                # `wf.router_not_total` (R3.3).
                "type": "object",
                "required": ["on", "cases"],
                "properties": {
                    "on": _REFERENCE_OR_TEXT,
                    "cases": {"type": "object", "additionalProperties": _LANE},
                    "default": _LANE,
                },
                "additionalProperties": False,
            },
            output=FixedOutput({"type": "object", "properties": {"case": {"type": "string"}}}),
            ports=KeyedPorts("cases", default=Port("default", "Khác")),
            **_CHOICE,
        ),
    )


def registry_of(specs: Iterable[NodeTypeSpec]) -> Mapping[str, NodeTypeSpec]:
    """A read-only registry of `specs`, refusing a `type@major` registered
    twice: two entries of one type are two answers to what it is, and the
    later silently winning is how they would drift (ADR-0112 decision 2)."""
    found: dict[str, NodeTypeSpec] = {}
    for spec in specs:
        if spec.type in found:
            raise ValueError(f"step type {spec.type} is registered twice")
        found[spec.type] = spec
    return MappingProxyType(found)


def build_node_registry() -> Mapping[str, NodeTypeSpec]:
    """The one registry both composition roots build: the API's catalogue and
    validator, the worker's compiler (workflow-nodes R1.1). The pack path
    builds it as it is, six types (wf-lite R2.1); Studio's own types join
    through an `extra` argument with the first of them (ticket 03)."""
    return registry_of(_wf_lite_types())


# ---------------------------------------------------------------------------
# The catalogue (workflow-nodes R1.1, R1.2)
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """`value` as JSON data the canonical hash takes: dicts and lists only."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _output_entry(output: Output) -> dict[str, Any]:
    match output:
        case FixedOutput(schema):
            return {"kind": "fixed", "schema": _plain(schema)}
        case OutputFromConfig(key):
            return {"kind": "config", "key": key}


def _port_entry(port: Port) -> dict[str, str]:
    return {"name": port.name, "label_vi": port.label_vi}


def _ports_entry(ports: Ports) -> dict[str, Any]:
    match ports:
        case FixedPorts(fixed):
            return {"kind": "fixed", "ports": [_port_entry(port) for port in fixed]}
        case KeyedPorts(key, default):
            return {
                "kind": "keyed",
                "key": key,
                "default": None if default is None else _port_entry(default),
            }


def _catalogue_entry(spec: NodeTypeSpec) -> dict[str, Any]:
    # The error policies under which a step publishes `error`, as the one
    # function that adds it answers (R1.5), never a second list.
    publishes = [
        policy
        for policy in get_args(OnError)
        if "error" in (step_output_schema(spec, {}, policy).get("properties") or {})
    ]
    return {
        "type": spec.type,
        "label_vi": spec.label_vi,
        "config_schema": _plain(spec.config_schema),
        "output": _output_entry(spec.output),
        "error": {"on_error": publishes, "schema": _plain(ERROR_OUTPUT)},
        "ports": _ports_entry(spec.ports),
        "side_effect_level": spec.side_effect_level,
    }


def catalogue_document(registry: Mapping[str, NodeTypeSpec]) -> dict[str, Any]:
    """The step-type catalogue as data, unclamped and the same for every
    caller: what `GET /api/v1/studio/node-types` returns and `catalogue_hash`
    hashes. What depends on the caller (plan clamps, lock reasons) joins the
    route's answer beside it, never this document (R1.2)."""
    return {"types": [_catalogue_entry(registry[name]) for name in sorted(registry)]}


def catalogue_hash(registry: Mapping[str, NodeTypeSpec]) -> str:
    """The catalogue's canonical hash (`dw_kernel.canonical`): the API's and
    the worker's registries agree exactly when their hashes do (R1.1)."""
    return content_hash(catalogue_document(registry))
