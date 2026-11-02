"""Tool registry: versioned tool definitions bound to how each one behaves (§7.6).

A tool's behaviour is one shape whatever wrote it (`ToolBehaviour`,
tools-and-skills R1, R2.2): a tool defined in code is checked by its Pydantic
models (`pydantic_behaviour`, G1), a tool that is a tenant's data by its JSON
Schemas (`tool_schema.json_schema_behaviour`), and the executor reads only the
behaviour, so every kind passes the same door.

The registry is two layers (`CLAUDE.md` "Per-tenant artifacts"): the platform's
tools, and a tenant's own, resolved for that tenant first and then from the
platform, never from another tenant (R2.1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import NotFoundError
from dw_kernel.ids import TenantId
from dw_kernel.overlay import TenantOverlay

ToolHandler = Callable[[BaseModel, RunContext], Awaitable[BaseModel]]
# What the approver has to read before deciding, for a tool whose arguments
# cannot say it. Field name -> value, rendered next to the arguments.
ApprovalPreview = Callable[[BaseModel, RunContext], Awaitable[dict[str, str]]]

# At most this many problems are named, as the platform's validator does.
_PROBLEM_LIMIT = 10


class SchemaViolation(Exception):  # noqa: N818 - a refusal the executor translates
    """A value its tool's schema refuses: where, and which rule, never the
    value (ADR-0116 decision 3). The executor turns it into `validation_failed`."""

    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__(f"{len(problems)} schema problem(s)")
        self.problems = problems


class ToolPayload(BaseModel):
    """A JSON Schema tool's checked input or output, kept as given: the schema
    has already decided what may be in it."""

    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True)
class ToolBehaviour:
    """How one tool checks what it takes and gives, and what it runs.

    `validate_input` and `validate_output` raise `SchemaViolation`;
    `input_schema` and `output_schema` return a fresh copy of its JSON Schemas (a sample of the
    output answers a simulated call, the input is a proposal's schema), and
    `args_schema` is what the model is shown: the Pydantic model of a code
    tool, so LangChain coerces arguments as it always has, or the dict."""

    validate_input: Callable[[Mapping[str, object]], BaseModel]
    validate_output: Callable[[object], BaseModel]
    handler: ToolHandler
    input_schema: Callable[[], dict[str, Any]]
    output_schema: Callable[[], dict[str, Any]]
    args_schema: type[BaseModel] | dict[str, Any]
    # Set only where the arguments are references. `email.save_to_record` takes
    # an artifact id and nothing else - deliberately, so the body cannot drift
    # between the card and the record - which left the approver authorizing a
    # write to a customer record with a UUID as the only thing on screen.
    approval_preview: ApprovalPreview | None = None


def _pydantic_problems(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "path": "/".join(str(part) for part in error["loc"]) or "(root)",
            "keyword": error["type"],
        }
        for error in exc.errors(include_url=False, include_input=False)[:_PROBLEM_LIMIT]
    ]


def pydantic_behaviour(
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    handler: ToolHandler,
    approval_preview: ApprovalPreview | None = None,
) -> ToolBehaviour:
    """A tool defined in code, checked by its own models (G1)."""

    def validate_input(raw: Mapping[str, object]) -> BaseModel:
        try:
            return input_model.model_validate(raw)
        except ValidationError as exc:
            raise SchemaViolation(_pydantic_problems(exc)) from exc

    def validate_output(raw: object) -> BaseModel:
        try:
            return output_model.model_validate(
                raw.model_dump() if isinstance(raw, BaseModel) else raw
            )
        except ValidationError as exc:
            raise SchemaViolation(_pydantic_problems(exc)) from exc

    return ToolBehaviour(
        validate_input=validate_input,
        validate_output=validate_output,
        handler=handler,
        input_schema=input_model.model_json_schema,
        output_schema=output_model.model_json_schema,
        args_schema=input_model,
        approval_preview=approval_preview,
    )


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    behaviour: ToolBehaviour


@dataclass
class ToolRegistry:
    """Fail-fast registry keyed by (tenant, name, version); the platform layer
    is `tenant_id=None`."""

    _tools: TenantOverlay[tuple[str, str], RegisteredTool] = field(default_factory=TenantOverlay)

    def register(self, tool: RegisteredTool, *, tenant_id: TenantId | None = None) -> None:
        key = (tool.definition.name, tool.definition.version)
        layer = None if tenant_id is None else tenant_id.value
        # A tenant's own version of a platform tool is an override; two tools
        # claiming one version inside one layer is the mistake.
        if self._tools.existing(key, tenant_id=layer) is not None:
            raise ConfigError(f"tool already registered: {key[0]}@{key[1]}")
        self._tools.put(key, tool, tenant_id=layer)

    def resolve(self, name: str, version: str, *, tenant_id: TenantId | None) -> RegisteredTool:
        """The tenant's own tool, else the platform's; never another tenant's
        (R2.1). `tenant_id` has no default: the caller says whose run it is,
        or that it asks the platform layer."""
        tool = self._tools.get(
            (name, version), tenant_id=None if tenant_id is None else tenant_id.value
        )
        if tool is None:
            raise NotFoundError(
                "tool version not registered",
                details={"tool": name, "version": version},
            )
        return tool

    def has_tool(self, name: str) -> bool:
        """Whether any version of a platform tool of this name is registered:
        what a Digital Worker's `allowed_tools` is checked against
        (digital-worker R1.3, `ToolCatalogPort`). Read at the time of asking,
        so a tool a context registers after wiring counts. The platform layer
        only: an inventory answer does not depend on who asks."""
        return any(tool.definition.name == name for tool in self._tools.platform_values())

    def all_definitions(self) -> list[ToolDefinition]:
        """The platform layer's definitions."""
        return [tool.definition for tool in self._tools.platform_values()]

    def definitions_for(self, pins: Iterable[tuple[str, str]]) -> list[ToolDefinition]:
        """The platform definitions a toolset pins, in the order it lists them.

        A pin naming a tool nobody registered raises here — at agent build time,
        which is startup — rather than when a model first reaches for it.
        """
        return [self.resolve(name, version, tenant_id=None).definition for name, version in pins]
