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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import StructuredTool

from dw_agent_runtime.adapters.langchain_tools import tool_call
from dw_agent_runtime.contracts import (
    MAX_MODEL_TOOLS,
    MAX_TOOL_NAME_CHARS,
    MODEL_TOOL_NAME,
    ToolDefinition,
    model_facing_name,
)
from dw_agent_runtime.executor import ToolExecutor, ToolResult
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.model.prompts import ContainedOutput, contain_tool_output
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import PinnedEntry
from dw_agent_runtime.tool_kinds import ToolAssembler, ToolBinding, ToolContract
from dw_agent_runtime.tools import RegisteredTool
from dw_kernel.errors import ConfigError


class ToolsetEntry(Protocol):
    """One entry of a pinned agent's `toolset`, as the runtime reads it: its
    tool kind and the `(kind, key)` the run manifest pinned it under."""

    @property
    def kind(self) -> str: ...

    def pin(self) -> tuple[str, str]: ...


@dataclass(frozen=True)
class CompiledTool:
    """One tool a toolset entry offers: what the kind's factory builds from."""

    binding: ToolBinding
    contract: ToolContract


class PinnedToolSource(Protocol):
    """One tool kind's way from a toolset entry and what the run pinned for it
    to the tools it offers: tools-and-skills/03's object generator
    (`object_crud`, a tool per enabled operation) and connections-and-vault/05's
    action compiler (`connector_action`). The table `kind -> source` is the
    composition root's, beside the assembler's `kind -> factory`."""

    def compile(self, entry: ToolsetEntry, pinned: PinnedEntry) -> Sequence[CompiledTool]: ...


@dataclass(frozen=True)
class PinnedTools:
    """A Studio agent's tools and their definitions, the one list its stack's
    middlewares are built from (`AgentSpec.pinned`)."""

    tools: tuple[StructuredTool, ...]
    definitions: tuple[ToolDefinition, ...]


def _refuse(message: str, reason: str, **details: object) -> ConfigError:
    return ConfigError(message, details={"reason": reason, **details})


def studio_tools(
    toolset: Sequence[ToolsetEntry],
    resolver: PinnedResolver,
    assembler: ToolAssembler,
    sources: Mapping[str, PinnedToolSource],
    executor: ToolExecutor,
    *,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> PinnedTools:
    """Every tool of a pinned `toolset`, or `ConfigError` and none at all."""
    tools: list[StructuredTool] = []
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
            tools.append(
                _pinned_tool(
                    registered,
                    compiled.binding.kind,
                    version_id,
                    pinned.content_hash,
                    executor,
                    approval_type_prefix,
                    copy,
                )
            )
            definitions.append(registered.definition)
    if len(tools) > MAX_MODEL_TOOLS:
        raise _refuse(
            "more tools than reach a model",
            "too_many_tools",
            count=len(tools),
            most=MAX_MODEL_TOOLS,
        )
    return PinnedTools(tuple(tools), tuple(definitions))


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
    registered: RegisteredTool,
    kind: str,
    version_id: str,
    content_hash: str | None,
    executor: ToolExecutor,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> StructuredTool:
    definition = registered.definition

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
        args_schema=registered.behaviour.args_schema,
        coroutine=tool_call(
            registered,
            executor,
            approval_type_prefix,
            copy,
            pinned=True,
            present=present,
            rejected=rejected,
        ),
        response_format="content_and_artifact",
        metadata={"tool_version_id": version_id, "content_hash": content_hash, "kind": kind},
    )
