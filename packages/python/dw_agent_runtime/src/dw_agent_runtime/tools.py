"""Tool registry: versioned tool definitions bound to typed handlers (§7.6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import NotFoundError

ToolHandler = Callable[[BaseModel, RunContext], Awaitable[BaseModel]]
# What the approver has to read before deciding, for a tool whose arguments
# cannot say it. Field name -> value, rendered next to the arguments.
ApprovalPreview = Callable[[BaseModel, RunContext], Awaitable[dict[str, str]]]


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    # Set only where the arguments are references. `email.save_to_record` takes
    # an artifact id and nothing else - deliberately, so the body cannot drift
    # between the card and the record - which left the approver authorizing a
    # write to a customer record with a UUID as the only thing on screen.
    approval_preview: ApprovalPreview | None = None


@dataclass
class ToolRegistry:
    """Fail-fast registry keyed by (name, version)."""

    _tools: dict[tuple[str, str], RegisteredTool] = field(default_factory=dict)

    def register(self, tool: RegisteredTool) -> None:
        key = (tool.definition.name, tool.definition.version)
        if key in self._tools:
            raise ConfigError(f"tool already registered: {key[0]}@{key[1]}")
        self._tools[key] = tool

    def resolve(self, name: str, version: str) -> RegisteredTool:
        tool = self._tools.get((name, version))
        if tool is None:
            raise NotFoundError(
                "tool version not registered",
                details={"tool": name, "version": version},
            )
        return tool

    def has_tool(self, name: str) -> bool:
        """Whether any version of a tool of this name is registered: what a
        Digital Worker's `allowed_tools` is checked against (digital-worker
        R1.3, `ToolCatalogPort`). Read at the time of asking, so a tool a
        context registers after wiring counts."""
        return any(tool_name == name for tool_name, _ in self._tools)

    def all_definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def definitions_for(self, pins: Iterable[tuple[str, str]]) -> list[ToolDefinition]:
        """The definitions a toolset pins, in the order the toolset lists them.

        A pin naming a tool nobody registered raises here — at agent build time,
        which is startup — rather than when a model first reaches for it.
        """
        return [self.resolve(name, version).definition for name, version in pins]
