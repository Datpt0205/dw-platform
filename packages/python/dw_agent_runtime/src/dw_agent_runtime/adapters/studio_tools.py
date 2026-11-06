"""A Studio agent's pinned tools, as its model sees them (tools-and-skills
R4.1-R4.3, R5.3; ADR-0116 decisions 3, 5, 6 and the amendment of 2026-11-04).

The agent version's `toolset` (`dw.toolset/v1`, parsed by
`dw_studio.core.domain.toolset`, which this package never imports) names
each tool by what the version pinned: an object by its artifact, a connector
action by its connector's `<key>@<semver>`. `studio_tools` resolves every
entry through the run's `PinnedResolver` and nothing else, never the
`ToolRegistry` and never the platform layer at run time (DO-05); a kind's
`PinnedToolSource` compiles the pinned entry into what the `ToolAssembler`
builds, and the built tool is handed to the executor on every call
(`execute(..., pinned=...)`), never registered.

Closed on a gap: an entry the manifest does not pin, a kind with no source
or factory, a name past 64 characters, two tools of one name or more than 40
in all is a `ConfigError` for the whole set, and the run fails rather than
run with a tool missing.

Each tool answers `content_and_artifact`: the content is the output wrapped
and cut by `contain_tool_output`, the one place that does it; the artifact
(the execution row, the pinned version, whether it was cut) stays beside the
message and never reaches the model.

An object tool (ticket 03) is shown narrower than the executor checks it: its
behaviour's `args_schema` is the view as built (a field soft-deleted since the
pin left out, R6.5), and its `FieldNarrowing` travels in the tool's metadata
for `FieldSecurityToolSchemaMiddleware`, which narrows the view to what the
run's actor reads at every model call (R6.3). The executor still checks the
full pinned schema, so a call naming a hidden or soft-deleted field reaches
RecordService and is refused there.

Strict mode (R4.4, R4.6; ticket 04) is two things at once, decided once per
turn in `PinnedTools.strict`: every tool's args schema in its strict form, and
`strict=True` on the provider's tool definitions (`StrictToolsMiddleware`),
never one without the other. The model's route declares `strict_tools` and the
turn's tools do not outnumber its `max_strict_tools`, or every tool is plain.
The executor still checks every call against the original schema (R1.1): the
strict form only narrows what the model may send, and the nulls it must send
for an optional field are dropped before the executor sees them.
"""

from __future__ import annotations

import copy as copying
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.tools import StructuredTool
from langgraph.runtime import get_runtime

from dw_agent_runtime.adapters.langchain_tools import tool_call
from dw_agent_runtime.contracts import (
    MAX_MODEL_TOOLS,
    MAX_TOOL_NAME_CHARS,
    MODEL_TOOL_NAME,
    RunContext,
    ToolDefinition,
    model_facing_name,
)
from dw_agent_runtime.executor import ToolExecutor, ToolResult
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.model.profiles import ModelCapabilities
from dw_agent_runtime.model.prompts import ContainedOutput, contain_tool_output
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import ObjectFieldsPort
from dw_agent_runtime.tool_kinds import (
    CompiledTool,
    PinnedToolSource,
    ToolAssembler,
    ToolsetEntry,
)
from dw_agent_runtime.tools import FieldNarrowing, ModelView, RegisteredTool
from dw_kernel.errors import ConfigError, NotFoundError, PermissionDeniedError

__all__ = [
    "FIELD_NARROWING",
    "CompiledTool",
    "FieldSecurityToolSchemaMiddleware",
    "PinnedToolSource",
    "PinnedTools",
    "StrictToolsMiddleware",
    "ToolsetEntry",
    "drop_strict_nulls",
    "render_input_schema",
    "studio_tools",
    "turn_capabilities",
]

# The `StructuredTool.metadata` key a tool's `FieldNarrowing` travels under,
# already rendered for the turn's strict mode; the model never sees metadata.
FIELD_NARROWING = "field_narrowing"


@dataclass(frozen=True)
class PinnedTools:
    """A Studio agent's tools and their definitions, the one list its stack's
    middlewares are built from (`AgentSpec.pinned`)."""

    tools: tuple[StructuredTool, ...]
    definitions: tuple[ToolDefinition, ...]
    # Every tool's schema is in its strict form, so the provider is told
    # `strict=True` (`StrictToolsMiddleware`); the one owner of both halves.
    strict: bool = False


@dataclass(frozen=True)
class _Built:
    registered: RegisteredTool
    kind: str
    version_id: str
    content_hash: str | None


def _refuse(message: str, reason: str, **details: object) -> ConfigError:
    return ConfigError(message, details={"reason": reason, **details})


def studio_tools(
    toolset: Sequence[ToolsetEntry],
    resolver: PinnedResolver,
    assembler: ToolAssembler,
    sources: Mapping[str, PinnedToolSource],
    executor: ToolExecutor,
    *,
    capabilities: ModelCapabilities,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> PinnedTools:
    """Every tool of a pinned `toolset`, or `ConfigError` and none at all.

    `capabilities` are those of the route the agent's model calls: strict
    when it declares `strict_tools` and the tools fit its `max_strict_tools`."""
    built: list[_Built] = []
    definitions: list[ToolDefinition] = []
    for entry in toolset:
        source = sources.get(entry.kind)
        if source is None:
            raise _refuse("no source for this tool kind", "kind_unknown", kind=entry.kind)
        pinned = resolver.resolve(*entry.pin())
        # The pinned object version, or the connector's `<key>@<semver>`.
        version_id = str(pinned.artifact.id) if pinned.artifact is not None else pinned.key
        for compiled in source.compile(entry, pinned):
            if compiled.binding.kind != entry.kind:
                raise _refuse(
                    "a source compiled a tool of another kind",
                    "kind_mismatch",
                    kind=entry.kind,
                    compiled=compiled.binding.kind,
                )
            registered = assembler.build(compiled.binding, compiled.contract)
            _check_name(registered.definition, definitions)
            built.append(_Built(registered, compiled.binding.kind, version_id, pinned.content_hash))
            definitions.append(registered.definition)
    if len(built) > MAX_MODEL_TOOLS:
        raise _refuse(
            "more tools than reach a model",
            "too_many_tools",
            count=len(built),
            most=MAX_MODEL_TOOLS,
        )
    turn = turn_capabilities(capabilities, len(built))
    tools = tuple(_pinned_tool(tool, turn, executor, approval_type_prefix, copy) for tool in built)
    return PinnedTools(tools, tuple(definitions), strict=turn.strict_tools)


def turn_capabilities(capabilities: ModelCapabilities, count: int) -> ModelCapabilities:
    """What one turn of `count` tools may use of its route's capabilities: no
    strict mode past `max_strict_tools` (unset is no ceiling), for every tool
    at once, never some strict and some plain (R4.4)."""
    ceiling = capabilities.max_strict_tools
    if capabilities.strict_tools and ceiling is not None and count > ceiling:
        return capabilities.model_copy(update={"strict_tools": False})
    return capabilities


def _check_name(definition: ToolDefinition, earlier: Sequence[ToolDefinition]) -> None:
    exposed = model_facing_name(definition.name)
    if len(exposed) > MAX_TOOL_NAME_CHARS:
        raise _refuse(
            "a tool's model-facing name is longer than 64 characters",
            "tool_name_too_long",
            tool=definition.name,
            length=len(exposed),
        )
    if MODEL_TOOL_NAME.fullmatch(exposed) is None:
        raise _refuse(
            "a tool's model-facing name is outside what a provider accepts",
            "tool_name_invalid",
            tool=definition.name,
        )
    if any(model_facing_name(other.name) == exposed for other in earlier):
        raise _refuse("two pinned tools share one name", "duplicate_tool", tool=exposed)


def _pinned_tool(
    built: _Built,
    capabilities: ModelCapabilities,
    executor: ToolExecutor,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> StructuredTool:
    registered, version_id = built.registered, built.version_id
    definition = registered.definition
    behaviour = registered.behaviour
    original = behaviour.input_schema()
    # What the model is shown, which may be narrower than what the executor
    # checks (`ToolBehaviour.narrowing`); a JSON Schema tool's is its input.
    shown = behaviour.args_schema if isinstance(behaviour.args_schema, dict) else original
    metadata: dict[str, Any] = {
        "tool_version_id": version_id,
        "content_hash": built.content_hash,
        "kind": built.kind,
    }
    if behaviour.narrowing is not None:
        metadata[FIELD_NARROWING] = _rendered(behaviour.narrowing, capabilities)

    def present(result: ToolResult) -> ContainedOutput:
        return contain_tool_output(
            result.output, definition, result.execution_id, tool_version_id=version_id
        )

    def rejected(text: str) -> ContainedOutput:
        # A person's refusal is the platform's words, not the tool's output.
        return ContainedOutput(
            text, {"execution_id": None, "tool_version_id": version_id, "truncated": False}
        )

    return StructuredTool(
        name=model_facing_name(definition.name),
        description=definition.description,
        args_schema=render_input_schema(shown, capabilities),
        coroutine=tool_call(
            registered,
            executor,
            approval_type_prefix,
            copy,
            pinned=True,
            present=present,
            rejected=rejected,
            admit=partial(drop_strict_nulls, original) if capabilities.strict_tools else None,
        ),
        response_format="content_and_artifact",
        metadata=metadata,
    )


def _rendered(narrowing: FieldNarrowing, capabilities: ModelCapabilities) -> FieldNarrowing:
    """``narrowing`` whose view comes out in the turn's form (R4.4): a strict
    turn's narrowed schema is strict too, never one tool plain among strict."""

    def view(readable: frozenset[str]) -> ModelView:
        seen = narrowing.view(readable)
        return ModelView(render_input_schema(seen.args_schema, capabilities), seen.description)

    return FieldNarrowing(narrowing.object, view)


# ------------------------------------------------------- strict (R4.4, R4.6) --

# What a strict schema keeps of `dw.tool-schema/v1`: the shape a provider
# constrains decoding to. Any other keyword (`maxLength`, `format`,
# `exclusiveMinimum`, `multipleOf`, ...) stays only in the schema the executor
# checks (R1.1), so a keyword a provider's strict mode refuses never reaches it.
_STRICT_KEYWORDS = frozenset({"type", "description", "enum", "const"})
# Kept only on a route that declares `numeric_bounds` (measured by `make check-model`).
_NUMERIC_BOUNDS = frozenset({"minimum", "maximum"})


def render_input_schema(
    schema: Mapping[str, Any], capabilities: ModelCapabilities
) -> dict[str, Any]:
    """The args schema the model is shown (R4.4, R4.6): the original, as it
    is, unless `capabilities` declare `strict_tools`; then its strict form.

    Strict: every object closed and every property in `required`, an optional
    one accepting `null` as well (its `type`, else its `enum`, else an `anyOf`
    branch), through nested objects, array items and `anyOf` branches;
    `minimum`/`maximum` only with `numeric_bounds`; nothing else."""
    if not capabilities.strict_tools:
        return copying.deepcopy(dict(schema))
    kept = _STRICT_KEYWORDS | (_NUMERIC_BOUNDS if capabilities.numeric_bounds else frozenset())
    return _strict(schema, kept)


def _strict(node: Mapping[str, Any], kept: frozenset[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for keyword, value in node.items():
        if keyword == "properties":
            required = set(node.get("required") or ())
            out["properties"] = {
                name: _strict(child, kept) if name in required else _nullable(_strict(child, kept))
                for name, child in value.items()
            }
        elif keyword == "items" and isinstance(value, Mapping):
            out["items"] = _strict(value, kept)
        elif keyword == "anyOf":
            out["anyOf"] = [_strict(branch, kept) for branch in value]
        elif keyword in kept:
            out[keyword] = copying.deepcopy(value)
    if "properties" in out or _is_type(node, "object"):
        out["required"] = list(out.get("properties") or ())
        out["additionalProperties"] = False
    return out


def _is_type(node: Mapping[str, Any], name: str) -> bool:
    kinds = node.get("type")
    return kinds == name or (isinstance(kinds, list) and name in kinds)


def _nullable(node: dict[str, Any]) -> dict[str, Any]:
    """`node`, accepting `null` as well: what a strict model sends for an
    optional property it has no value for."""
    if "const" in node and node["const"] is not None:
        node["enum"] = [node.pop("const")]
    if "type" in node and not _is_type(node, "null"):
        kinds = node["type"] if isinstance(node["type"], list) else [node["type"]]
        node["type"] = [*kinds, "null"]
    if "enum" in node and None not in node["enum"]:
        node["enum"] = [*node["enum"], None]
    if "type" in node or "enum" in node:
        return node
    if "anyOf" in node:
        node["anyOf"] = [*node["anyOf"], {"type": "null"}]
        return node
    return {"anyOf": [node, {"type": "null"}]}


def drop_strict_nulls(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    """`arguments` without the `null`s a strict model sent for an optional key
    the original `schema` does not let be `null` (step 3; R1.1, R1.3), through
    nested objects, array items and `anyOf` branches. A required key's `null`
    stays, and the executor refuses it with `validation_failed`."""
    return dict(_dropped([schema], arguments))


def _dropped(schemas: Sequence[Mapping[str, Any]], value: Any) -> Any:
    branches = [
        *schemas,
        *(b for s in schemas for b in s.get("anyOf") or () if isinstance(b, Mapping)),
    ]
    if isinstance(value, list):
        items = [b["items"] for b in branches if isinstance(b.get("items"), Mapping)]
        return [_dropped(items, element) for element in value]
    if not isinstance(value, Mapping):
        return value
    out: dict[str, Any] = {}
    for key, child in value.items():
        declaring = [b for b in branches if key in (b.get("properties") or {})]
        if (
            child is None
            and declaring
            and not any(
                key in (b.get("required") or ()) or _accepts_null(b["properties"][key])
                for b in declaring
            )
        ):
            continue
        out[key] = _dropped([b["properties"][key] for b in declaring], child)
    return out


def _accepts_null(schema: Mapping[str, Any]) -> bool:
    if "type" in schema and not _is_type(schema, "null"):
        return False
    if "enum" in schema and None not in schema["enum"]:
        return False
    if "const" in schema and schema["const"] is not None:
        return False
    branches = schema.get("anyOf")
    return branches is None or any(_accepts_null(b) for b in branches)


class StrictToolsMiddleware(AgentMiddleware):
    """`strict=True` on the provider's tool definitions, the other half of
    the strict schemas `PinnedTools.strict` says its tools carry: LangChain
    hands `model_settings` to `bind_tools`, whose OpenAI conversion marks
    every function `strict` (measured on langchain 1.4.1, langchain-openai
    1.6.2)."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        settings = {**request.model_settings, "strict": True}
        return await handler(request.override(model_settings=settings))


# ------------------------------------------------- field security (R6.3) --


class FieldSecurityToolSchemaMiddleware(AgentMiddleware):
    """Every object tool's model view narrowed to the fields the run's actor
    reads now (tools-and-skills R6.3; field-security R4.2, R4.8): at every
    model call, asked of `ObjectFieldsPort` once per object per call and never
    kept, so a read revoked between two calls of one run is out of the next
    one. It only narrows (`FieldNarrowing`); the executor still checks a call
    against the full pinned schema, and RecordService refuses a filter on a
    field the caller cannot read (`field_not_readable`). The one place a tool's
    view follows field security: field-security/02 adds its cases here.

    An object the actor may no longer read at all (`not_found`, `forbidden`)
    takes its tools out of the offer; any other failure fails the call."""

    def __init__(self, fields: ObjectFieldsPort) -> None:
        super().__init__()
        self._fields = fields

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        run = get_runtime(RunContext).context
        readable: dict[str, frozenset[str] | None] = {}
        offered: list[Any] = []
        for tool in request.tools:
            narrowing = _narrowing_of(tool) if isinstance(tool, StructuredTool) else None
            if narrowing is None or not isinstance(tool, StructuredTool):
                offered.append(tool)
                continue
            if narrowing.object not in readable:
                readable[narrowing.object] = await self._readable(run, narrowing.object)
            names = readable[narrowing.object]
            if names is None:
                continue
            view = narrowing.view(names)
            offered.append(
                tool.model_copy(
                    update={"args_schema": view.args_schema, "description": view.description}
                )
            )
        return await handler(request.override(tools=offered))

    async def _readable(self, run: RunContext, api_name: str) -> frozenset[str] | None:
        try:
            return await self._fields.readable(run, api_name)
        except (NotFoundError, PermissionDeniedError):
            return None


def _narrowing_of(tool: StructuredTool) -> FieldNarrowing | None:
    found = (tool.metadata or {}).get(FIELD_NARROWING)
    return found if isinstance(found, FieldNarrowing) else None
