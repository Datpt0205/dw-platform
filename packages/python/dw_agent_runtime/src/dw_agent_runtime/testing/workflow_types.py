"""A step-type registry for tests of the `dw.workflow/v1` core and of Studio's
`workflow` kind (workflow-engine ticket 01, step 9).

The six wf-lite types, and one fixture type for each shape the lowering and
the validator must handle before the Studio types that have them exist:

- `fixture.effect@1`: a step with an effect of its own, no lane;
- `fixture.choice@1`: a `choice` block over `yes` and `no`;
- `fixture.wait@1`: a step that waits, no lane; in a Studio run it opens an
  `approval` wait and goes on with the resolution as its output, until
  workflow-nodes/06's `human.approval@2` (workflow-engine/05);
- `fixture.parallel@1`: a `parallel` block over `branches.<name>`;
- `fixture.loop@1`: a `loop` over `body`, leaving by `max_reached`;
- `fixture.stop@1`: `ends_run`;
- `fixture.break@1`: `exits_loop`;
- `fixture.trigger@1`: a trigger that uses a data source (an `endpoint`
  artifact) by its id in `source`;
- `fixture.object@1`: a step that reads an object by its id in `object`;
- `fixture.records@1`: a step that runs one record command on an object (by
  its `api_name`) through the `records` door, naming the fields it reads and
  writes (`record_uses`), until workflow-nodes/04's `data.object.*`;
- `fixture.assign@1`: a step that assigns a record through the `assign` door.

The types a Studio run can run (workflow-engine/03) carry a body over
`EffectDoors`: `fixture.effect@1` through the `tool` door, `fixture.records@1`
and `fixture.assign@1` through theirs, `fixture.choice@1` answering the port
its `on` names, `fixture.stop@1` ending the run.

None of them is registered by any composition root: a test passes
`fixture_node_registry()` where the root would pass `build_node_registry()`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from dw_agent_runtime.wflite.doors import BodyResult, EffectDoor, EffectDoors, Routed, StepBody
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
    RecordUse,
    RecordUses,
    StepDependency,
    WaitSpec,
    build_node_registry,
    no_dependencies,
    no_record_uses,
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
    effect_door: EffectDoor | None = None,
    body: StepBody | None = None,
    record_uses: RecordUses = no_record_uses,
    wait: WaitSpec | None = None,
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
        effect_door=effect_door,
        body=body,
        record_uses=record_uses,
        wait=wait,
    )


# ---- the bodies a Studio run runs -------------------------------------------------


async def _send(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    raw = inputs.get("input")
    return await doors.call("tool", "fixture.send@1", dict(raw) if isinstance(raw, Mapping) else {})


async def _records(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    values = inputs.get("values")
    return await doors.call(
        "records",
        str(config["command"]),
        {
            "object": config["object"],
            "record_id": inputs.get("record"),
            "values": dict(values) if isinstance(values, Mapping) else {},
        },
    )


async def _assign(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    return await doors.call(
        "assign", "assign", {"object": config["object"], "record_id": inputs.get("record")}
    )


async def _choose(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    case = str(inputs.get("on"))
    return Routed({"case": case}, case if case in ("yes", "no") else None)


async def _stop(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    return {}


def waited(config: Mapping[str, Any], resolution: Mapping[str, Any]) -> Routed:
    """A waiting fixture's output: what its wait was resolved with."""
    return Routed(
        {k: resolution[k] for k in ("decision", "decided_by", "comment") if k in resolution},
        None,
    )


FIXTURE_WAIT = WaitSpec(kind="approval", resume=waited)


def _record_uses(config: Mapping[str, Any]) -> tuple[RecordUse, ...]:
    fields = config.get("fields")
    writes = config.get("writes")
    return (
        RecordUse(
            str(config["object"]),
            config["command"],
            tuple(fields) if isinstance(fields, list) else (),
            tuple(writes) if isinstance(writes, list) else (),
        ),
    )


def _assign_uses(config: Mapping[str, Any]) -> tuple[RecordUse, ...]:
    return (RecordUse(str(config["object"]), "assign"),)


def fixture_node_types() -> tuple[NodeTypeSpec, ...]:
    return (
        _type(
            "fixture.effect@1",
            properties={"note": {"type": "string"}, "input": {"type": ["object", "string"]}},
            output={"type": "object", "properties": {"done": {"type": "boolean"}}},
            effect_door="tool",
            body=_send,
        ),
        _type(
            "fixture.choice@1",
            properties={"on": _ID, "yes": _LANE, "no": _LANE},
            required=("on",),
            block="choice",
            ports=_ports("yes", "no"),
            output={"type": "object", "properties": {"case": {"type": "string"}}},
            body=_choose,
        ),
        _type(
            "fixture.wait@1",
            properties={"seconds": {"type": "integer", "minimum": 1}},
            output={
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "decided_by": {"type": "string"},
                    "comment": {"type": "string"},
                },
            },
            wait=FIXTURE_WAIT,
        ),
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
        _type("fixture.stop@1", ends_run=True, body=_stop),
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
        _type(
            "fixture.records@1",
            properties={
                "object": _ID,
                "command": {"enum": ["read", "create", "update", "delete"]},
                "record": {"type": "string"},
                "fields": {"type": "array", "items": _ID},
                "writes": {"type": "array", "items": _ID},
                "values": {"type": "object"},
            },
            required=("object", "command"),
            output={
                "type": "object",
                "properties": {"record": {"type": "object"}, "replayed": {"type": "boolean"}},
            },
            effect_door="records",
            body=_records,
            record_uses=_record_uses,
        ),
        _type(
            "fixture.assign@1",
            properties={"object": _ID, "record": {"type": "string"}},
            required=("object",),
            output={
                "type": "object",
                "properties": {"assignee": {"type": "string"}, "replayed": {"type": "boolean"}},
            },
            effect_door="assign",
            body=_assign,
            record_uses=_assign_uses,
        ),
    )


def fixture_node_registry() -> Mapping[str, NodeTypeSpec]:
    """The six wf-lite types and the fixture types, one registry."""
    return registry_of((*build_node_registry().values(), *fixture_node_types()))
