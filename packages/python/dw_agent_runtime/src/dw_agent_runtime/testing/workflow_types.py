"""A step-type registry for tests of the `dw.workflow/v1` core and of Studio's
`workflow` kind (workflow-engine ticket 01, step 9).

The six wf-lite types, and one fixture type for each shape the lowering and
the validator must handle before the Studio types that have them exist:

- `fixture.effect@1`: a step with an effect of its own, no lane;
- `fixture.choice@1`: a `choice` block over `yes` and `no`;
- `fixture.wait@1`: a step that waits, no lane;
- `fixture.parallel@1`: a `parallel` block over `branches.<name>`;
- `fixture.loop@1`: a `loop` over `body`, leaving by `max_reached`;
- `fixture.stop@1`: `ends_run`;
- `fixture.break@1`: `exits_loop`;
- `fixture.trigger@1`: a trigger that uses a data source (an `endpoint`
  artifact) by its id in `source`;
- `fixture.object@1`: a step that reads an object by its id in `object`.

None of them is registered by any composition root: a test passes
`fixture_node_registry()` where the root would pass `build_node_registry()`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from dw_agent_runtime.wflite.registry import (
    Block,
    JsonSchema,
    NodeTypeSpec,
    StepDependency,
    build_node_registry,
    no_dependencies,
)

_LANE: JsonSchema = {"type": "array", "items": {"type": "object"}}
_EMPTY: JsonSchema = {"type": "object", "properties": {}}
_ID: JsonSchema = {"type": "string", "minLength": 1}


def _fixed(schema: JsonSchema) -> Callable[[Mapping[str, Any]], JsonSchema]:
    return lambda config: schema


def _ports(*ports: str) -> Callable[[Mapping[str, Any]], Mapping[str, list[Any]]]:
    """Each port always, `[]` when the config leaves it out."""

    def lanes(config: Mapping[str, Any]) -> Mapping[str, list[Any]]:
        found: dict[str, list[Any]] = {}
        for port in ports:
            items = config.get(port)
            found[port] = list(items) if isinstance(items, list) else []
        return found

    return lanes


def _branches(config: Mapping[str, Any]) -> Mapping[str, list[Any]]:
    branches = config.get("branches")
    if not isinstance(branches, Mapping):
        return {}
    return {
        f"branches.{name}": list(items) if isinstance(items, list) else []
        for name, items in branches.items()
    }


def _uses(field: str) -> Callable[[Mapping[str, Any]], tuple[StepDependency, ...]]:
    def dependencies(config: Mapping[str, Any]) -> tuple[StepDependency, ...]:
        target = config.get(field)
        if not isinstance(target, str):
            return ()
        return (StepDependency("artifact", target, "read", f"/{field}"),)

    return dependencies


def _type(
    name: str,
    *,
    properties: Mapping[str, JsonSchema] | None = None,
    required: tuple[str, ...] = (),
    block: Block = "none",
    lanes: Callable[[Mapping[str, Any]], Mapping[str, list[Any]]] | None = None,
    ends_run: bool = False,
    exits_loop: bool = False,
    dependencies: Callable[[Mapping[str, Any]], tuple[StepDependency, ...]] = no_dependencies,
    is_trigger: bool = False,
    output: JsonSchema = _EMPTY,
) -> NodeTypeSpec:
    return NodeTypeSpec(
        type=name,
        config_schema={
            "type": "object",
            "required": list(required),
            "properties": dict(properties or {}),
            "additionalProperties": False,
        },
        output_schema=_fixed(output),
        block=block,
        ends_run=ends_run,
        exits_loop=exits_loop,
        dependencies=dependencies,
        lanes=lanes or (lambda config: {}),
        side_effect_level="internal" if name == "fixture.effect@1" else "none",
        is_trigger=is_trigger,
    )


def fixture_node_types() -> tuple[NodeTypeSpec, ...]:
    return (
        _type(
            "fixture.effect@1",
            properties={"note": {"type": "string"}},
            output={"type": "object", "properties": {"done": {"type": "boolean"}}},
        ),
        _type(
            "fixture.choice@1",
            properties={"on": _ID, "yes": _LANE, "no": _LANE},
            required=("on",),
            block="choice",
            lanes=_ports("yes", "no"),
            output={"type": "object", "properties": {"case": {"type": "string"}}},
        ),
        _type("fixture.wait@1", properties={"seconds": {"type": "integer", "minimum": 1}}),
        _type(
            "fixture.parallel@1",
            properties={"branches": {"type": "object", "additionalProperties": _LANE}},
            required=("branches",),
            block="parallel",
            lanes=_branches,
        ),
        _type(
            "fixture.loop@1",
            properties={
                "max_iterations": {"type": "integer", "minimum": 1},
                "body": _LANE,
                "max_reached": _LANE,
            },
            required=("max_iterations",),
            block="loop",
            lanes=_ports("body", "max_reached"),
        ),
        _type("fixture.stop@1", ends_run=True),
        _type("fixture.break@1", exits_loop=True),
        _type(
            "fixture.trigger@1",
            properties={"source": _ID},
            required=("source",),
            dependencies=_uses("source"),
            is_trigger=True,
        ),
        _type(
            "fixture.object@1",
            properties={"object": _ID},
            required=("object",),
            dependencies=_uses("object"),
            output={"type": "object", "properties": {"record": {"type": "object"}}},
        ),
    )


def fixture_node_registry() -> Mapping[str, NodeTypeSpec]:
    """The six wf-lite types and the fixture types, one registry."""
    return MappingProxyType(
        {**build_node_registry(), **{spec.type: spec for spec in fixture_node_types()}}
    )
