"""A tool of a registered kind: one factory per kind, the kind's floor, and the
one assembler that makes a `RegisteredTool` of them (tools-and-skills R2.2-R2.4;
ADR-0116 decisions 1, 3).

A kind's factory returns behaviour only (`ToolBehaviour`), with no slot for
policy: what a tool may do without a person is the policy's, checked here
against the kind's floor, which a tenant may tighten and never loosen. The
table `kind -> factory` is the composition root's, passed to the assembler; a
factory takes what it needs in its constructor (`CLAUDE.md`: constructor
injection), so `build` takes the binding and the contract alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

from dw_agent_runtime.contracts import ApprovalPolicy, SideEffectLevel, ToolDefinition
from dw_agent_runtime.ports import PinnedEntry
from dw_agent_runtime.tool_schema import check_profile
from dw_agent_runtime.tools import RegisteredTool, ToolBehaviour, ToolRegistry
from dw_kernel.errors import ConfigError, DomainError
from dw_kernel.ids import TenantId

Operation = Literal["read", "write"]

_EFFECT_RANK: Final[Mapping[str, int]] = {"none": 0, "internal": 1, "external": 2, "critical": 3}
_APPROVAL_RANK: Final[Mapping[str, int]] = {"never": 0, "conditional": 1, "always": 2}
# An `http` call with any other method changes something where it lands.
_HTTP_READS: Final = frozenset({"GET", "HEAD"})


@dataclass(frozen=True)
class ToolPolicy:
    """What a tool's policy says about it without a person: how far its effect
    reaches and when it asks. A kind's floor is one too."""

    side_effect_level: SideEffectLevel
    approval_policy: ApprovalPolicy

    @classmethod
    def of(cls, definition: ToolDefinition) -> ToolPolicy:
        return cls(definition.side_effect_level, definition.approval_policy)


# The least each kind's tool may declare, by whether it reads or writes. A kind
# not named here has no floor yet, and the assembler refuses it.
KIND_FLOORS: Final[Mapping[tuple[str, Operation], ToolPolicy]] = {
    ("object_crud", "read"): ToolPolicy("none", "never"),
    ("object_crud", "write"): ToolPolicy("internal", "conditional"),
    ("connector_action", "read"): ToolPolicy("none", "never"),
    ("connector_action", "write"): ToolPolicy("external", "conditional"),
    ("http", "read"): ToolPolicy("none", "never"),
    ("http", "write"): ToolPolicy("external", "conditional"),
}


def check_policy_against_floor(policy: ToolPolicy, floor: ToolPolicy) -> None:
    """Refuse a policy below its floor on either axis (R2.3, R2.4): a kind's
    floor, or the platform tool a tenant's override stands over. Equal is
    allowed; only tightening is. `validation_failed` with `details.reason_code`
    `kind_floor_violation` (ADR-0108's 422)."""
    below = [
        axis
        for axis, ranks, mine, least in (
            ("side_effect_level", _EFFECT_RANK, policy.side_effect_level, floor.side_effect_level),
            ("approval_policy", _APPROVAL_RANK, policy.approval_policy, floor.approval_policy),
        )
        if ranks[mine] < ranks[least]
    ]
    if below:
        raise DomainError(
            "the tool's policy is below its floor",
            details={
                "reason_code": "kind_floor_violation",
                "fields": below,
                "floor": {
                    "side_effect_level": floor.side_effect_level,
                    "approval_policy": floor.approval_policy,
                },
            },
        )


@dataclass(frozen=True)
class ToolBinding:
    """A tool's implementation: its kind and that kind's configuration."""

    kind: str
    config: Mapping[str, Any] = field(default_factory=dict)
    # Whether it changes anything; an `http` binding's method decides for it.
    operation: Operation = "write"

    def effective_operation(self) -> Operation:
        if self.kind == "http":
            method = str(self.config.get("method", "POST")).upper()
            return "read" if method in _HTTP_READS else "write"
        return self.operation


def floor_for(binding: ToolBinding) -> ToolPolicy:
    found = KIND_FLOORS.get((binding.kind, binding.effective_operation()))
    if found is None:
        raise ConfigError(
            "no floor for this tool kind",
            details={"kind": binding.kind, "reason_code": "kind_unknown"},
        )
    return found


@dataclass(frozen=True)
class ToolContract:
    """What a tool says it takes and gives, and the definition its policy is in."""

    definition: ToolDefinition
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]


class ToolKindFactory(Protocol):
    """One kind's behaviour (`object_crud`, `connector_action` in W1)."""

    def build(self, binding: ToolBinding, contract: ToolContract) -> ToolBehaviour: ...


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
    composition root's, beside the assembler's `kind -> factory`. Here, beside
    the factory, and not with the LangChain wrapping in `adapters.studio_tools`,
    so a source in a package that never imports LangChain (Studio's) can name
    it."""

    def compile(self, entry: ToolsetEntry, pinned: PinnedEntry) -> Sequence[CompiledTool]: ...


@dataclass(frozen=True)
class ToolAssembler:
    """The one place a tool of a kind becomes a `RegisteredTool`: its kind's
    factory, its schemas within the profile, its policy at or above the floor
    (`build`), then registered for its layer (`assemble`). Any refusal is a
    `ConfigError` and nothing is registered. A Studio run's pinned tool is
    built and never registered: the run hands it to the executor itself
    (tools-and-skills R4.1, `adapters.studio_tools`)."""

    registry: ToolRegistry
    kinds: Mapping[str, ToolKindFactory]

    def assemble(
        self,
        binding: ToolBinding,
        contract: ToolContract,
        *,
        tenant_id: TenantId | None,
        over: ToolDefinition | None = None,
    ) -> RegisteredTool:
        """`build`, then registered for the layer `tenant_id` names."""
        tool = self.build(binding, contract, over=over)
        self.registry.register(tool, tenant_id=tenant_id)
        return tool

    def build(
        self,
        binding: ToolBinding,
        contract: ToolContract,
        *,
        over: ToolDefinition | None = None,
    ) -> RegisteredTool:
        """`over` is the platform tool a tenant's version overrides, whose
        policy is a floor too (R2.4)."""
        factory = self.kinds.get(binding.kind)
        if factory is None:
            raise ConfigError(
                "no factory for this tool kind",
                details={"kind": binding.kind, "reason_code": "kind_unknown"},
            )
        check_profile(contract.input_schema)
        check_profile(contract.output_schema)
        policy = ToolPolicy.of(contract.definition)
        floors = [floor_for(binding)] + ([] if over is None else [ToolPolicy.of(over)])
        try:
            for floor in floors:
                check_policy_against_floor(policy, floor)
        except DomainError as exc:
            raise ConfigError(
                f"tool {contract.definition.name}@{contract.definition.version} is below its floor",
                details={"tool": contract.definition.name, **exc.details},
            ) from exc
        return RegisteredTool(contract.definition, factory.build(binding, contract))
