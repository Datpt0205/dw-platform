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
from typing import Any

from dw_agent_runtime.wflite.registry import (
    NO_PORTS,
    Block,
    FixedOutput,
    FixedPorts,
    JsonSchema,
    KeyedPorts,
    NodeTypeSpec,
    Port,
    Ports,
    StepDependency,
    build_node_registry,
    no_dependencies,
    registry_of,
)

_LANE: JsonSchema = {"type": "array", "items": {"type": "object"}}
_EMPTY: JsonSchema = {"type": "object", "properties": {}}
_ID: JsonSchema = {"type": "string", "minLength": 1}


def _ports(*names: str) -> FixedPorts:
    """Each port always, `[]` when the config leaves it out."""
    return FixedPorts(tuple(Port(name, name) for name in names))


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
    ports: Ports = NO_PORTS,
    ends_run: bool = False,
    exits_loop: bool = False,
    dependencies: Callable[[Mapping[str, Any]], tuple[StepDependency, ...]] = no_dependencies,
    is_trigger: bool = False,
    output: JsonSchema = _EMPTY,
) -> NodeTypeSpec:
    return NodeTypeSpec(
        type=name,
        label_vi=name,
        config_schema={
            "type": "object",
            "required": list(required),
            "properties": dict(properties or {}),
            "additionalProperties": False,
        },
        output=FixedOutput(output),
        block=block,
        ends_run=ends_run,
        exits_loop=exits_loop,
        dependencies=dependencies,
        ports=ports,
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
            ports=_ports("yes", "no"),
            output={"type": "object", "properties": {"case": {"type": "string"}}},
        ),
        _type("fixture.wait@1", properties={"seconds": {"type": "integer", "minimum": 1}}),
        _type(
            "fixture.parallel@1",
            properties={"branches": {"type": "object", "additionalProperties": _LANE}},
            required=("branches",),
            block="parallel",
            ports=KeyedPorts("branches"),
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
            ports=_ports("body", "max_reached"),
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
    return registry_of((*build_node_registry().values(), *fixture_node_types()))
