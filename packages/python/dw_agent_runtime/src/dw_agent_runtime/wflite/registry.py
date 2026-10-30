"""The six step types of wf-lite (wf-lite R2; ADR-0112 decision 2).

One registry, built by one function, read by the validator and (wf-lite/02)
the compiler, so the two cannot disagree about what a type is. A type is its
config schema, its output schema (fixed, or taken from the step's config), the
ports whose lanes a step of it holds, and the side effect it has by itself
(`tool.call`'s comes from the tool it calls).

A lane is a list of steps in the step's `config` under the port's name; a
config schema says only that it is an array, and the validator walks it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from dw_agent_runtime.contracts import SideEffectLevel

JsonSchema = Mapping[str, Any]

_LANE: JsonSchema = {"type": "array", "items": {"type": "object"}}
_PROMPT_ID = r"^[a-z][a-z0-9_.]*@(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_TOOL_ID = _PROMPT_ID
_REFERENCE_OR_TEXT: JsonSchema = {"type": "string", "minLength": 1}


@dataclass(frozen=True)
class NodeTypeSpec:
    type: str
    config_schema: JsonSchema
    # The fields a later step may reference, from the step's own config.
    output_schema: Callable[[Mapping[str, Any]], JsonSchema]
    # The ports whose lanes a step of this type holds, from its config.
    lanes: Callable[[Mapping[str, Any]], Mapping[str, list[Any]]] = field(default=lambda config: {})
    side_effect_level: SideEffectLevel = "none"
    is_trigger: bool = False


def _fixed(schema: JsonSchema) -> Callable[[Mapping[str, Any]], JsonSchema]:
    return lambda config: schema


def _of_config(name: str) -> Callable[[Mapping[str, Any]], JsonSchema]:
    def output(config: Mapping[str, Any]) -> JsonSchema:
        found = config.get(name)
        return found if isinstance(found, Mapping) else {"type": "object", "properties": {}}

    return output


def _approval_lanes(config: Mapping[str, Any]) -> Mapping[str, list[Any]]:
    return {
        port: list(config.get(port) or []) if isinstance(config.get(port) or [], list) else []
        for port in ("approved", "rejected")
    }


def _switch_lanes(config: Mapping[str, Any]) -> Mapping[str, list[Any]]:
    lanes: dict[str, list[Any]] = {}
    cases = config.get("cases")
    if isinstance(cases, Mapping):
        for value, steps in cases.items():
            lanes[f"cases.{value}"] = list(steps) if isinstance(steps, list) else []
    default = config.get("default")
    if isinstance(default, list):
        lanes["default"] = list(default)
    return lanes


def build_node_registry() -> Mapping[str, NodeTypeSpec]:
    """Exactly the six types of the first slice; no more (R2.1)."""
    specs = (
        NodeTypeSpec(
            type="trigger.work_item@1",
            config_schema={
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            output_schema=_fixed({"type": "object", "properties": {}}),
            is_trigger=True,
        ),
        NodeTypeSpec(
            type="ai.llm@1",
            config_schema={
                "type": "object",
                "required": ["prompt", "inputs", "output_schema"],
                "properties": {
                    "prompt": {"type": "string", "pattern": _PROMPT_ID},
                    "inputs": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "min_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "additionalProperties": False,
            },
            output_schema=_of_config("output_schema"),
        ),
        NodeTypeSpec(
            type="tool.call@1",
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
            output_schema=_fixed({"type": "object", "properties": {"result": {}}}),
        ),
        NodeTypeSpec(
            type="human.approval@1",
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
            output_schema=_fixed(
                {
                    "type": "object",
                    "properties": {
                        "proposal": {"type": "object"},
                        "approved": {"type": "boolean"},
                        "comment": {"type": "string"},
                    },
                }
            ),
            lanes=_approval_lanes,
        ),
        NodeTypeSpec(
            type="time.wait@1",
            config_schema={
                "type": "object",
                "oneOf": [{"required": ["seconds"]}, {"required": ["seconds_param"]}],
                "properties": {
                    "seconds": {"type": "integer", "minimum": 1, "maximum": 2_592_000},
                    "seconds_param": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            output_schema=_fixed({"type": "object", "properties": {"woke_at": {"type": "string"}}}),
        ),
        NodeTypeSpec(
            type="logic.switch@1",
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
            output_schema=_fixed({"type": "object", "properties": {"case": {"type": "string"}}}),
            lanes=_switch_lanes,
        ),
    )
    return MappingProxyType({spec.type: spec for spec in specs})
