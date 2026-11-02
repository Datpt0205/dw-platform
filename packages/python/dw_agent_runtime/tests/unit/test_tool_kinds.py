"""Tool kinds, their floors and the one assembler (tools-and-skills ticket 01:
R2.2-R2.4; TS4). The kinds' real factories belong to ticket 03 and
connections-and-vault/05; the factories here are fakes that build what a real
one would, a `ToolBehaviour`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel
from test_executor import make_definition
from test_tool_schema import LEAD_INPUT, LEAD_OUTPUT

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.tool_kinds import (
    KIND_FLOORS,
    ToolAssembler,
    ToolBinding,
    ToolContract,
    ToolKindFactory,
    ToolPolicy,
    check_policy_against_floor,
)
from dw_agent_runtime.tool_schema import json_schema_behaviour
from dw_agent_runtime.tools import ToolBehaviour, ToolRegistry
from dw_kernel.errors import ConfigError, DomainError, NotFoundError
from dw_kernel.ids import TenantId

pytestmark = pytest.mark.unit


async def _handler(payload: BaseModel, run_context: RunContext) -> Any:
    return {"saved": True}


@dataclass
class FakeFactory:
    built: list[ToolBinding] = field(default_factory=list)

    def build(self, binding: ToolBinding, contract: ToolContract) -> ToolBehaviour:
        self.built.append(binding)
        return json_schema_behaviour(contract.input_schema, contract.output_schema, _handler)


def assembler(registry: ToolRegistry) -> tuple[ToolAssembler, dict[str, FakeFactory]]:
    # The composition root's table: one factory per W1 kind.
    factories = {"object_crud": FakeFactory(), "connector_action": FakeFactory()}
    kinds: dict[str, ToolKindFactory] = dict(factories)
    return ToolAssembler(registry=registry, kinds=kinds), factories


def contract(definition: ToolDefinition) -> ToolContract:
    return ToolContract(definition=definition, input_schema=LEAD_INPUT, output_schema=LEAD_OUTPUT)


# --------------------------------------------------------------------- R2.2 --


@pytest.mark.parametrize("kind", ["object_crud", "connector_action"])
def test_each_w1_kind_builds_a_registered_tool(kind: str) -> None:
    """R2.2: the kind's factory returns the behaviour; the assembler makes
    the `RegisteredTool` and registers it."""
    registry = ToolRegistry()
    tools, factories = assembler(registry)
    definition = make_definition(name=f"{kind}.save")
    tool = tools.assemble(
        ToolBinding(kind=kind, operation="write"), contract(definition), tenant_id=None
    )
    assert factories[kind].built == [ToolBinding(kind=kind, operation="write")]
    assert registry.resolve(definition.name, "1.0.0", tenant_id=None) is tool
    assert tool.definition == definition


def test_a_kind_with_no_factory_is_refused_and_nothing_is_registered() -> None:
    """R2.2."""
    registry = ToolRegistry()
    tools, _ = assembler(registry)
    with pytest.raises(ConfigError) as refused:
        tools.assemble(
            ToolBinding(kind="code"), contract(make_definition(name="x.run")), tenant_id=None
        )
    assert refused.value.details["kind"] == "code"
    with pytest.raises(NotFoundError):
        registry.resolve("x.run", "1.0.0", tenant_id=None)


def test_a_kind_with_a_factory_but_no_floor_is_refused() -> None:
    """A kind is not assembled before its floor is written down."""
    registry = ToolRegistry()
    tools = ToolAssembler(registry=registry, kinds={"workflow": FakeFactory()})
    with pytest.raises(ConfigError) as refused:
        tools.assemble(
            ToolBinding(kind="workflow"), contract(make_definition(name="x.run")), tenant_id=None
        )
    assert refused.value.details["reason_code"] == "kind_unknown"


# --------------------------------------------------------------- R2.3, R2.4 --


@pytest.mark.parametrize(
    ("policy", "floor", "refused"),
    [
        # R2.3: an `http` POST writes, and its floor is an external effect.
        (
            ToolPolicy("none", "never"),
            KIND_FLOORS[("http", "write")],
            ["side_effect_level", "approval_policy"],
        ),
        (ToolPolicy("none", "conditional"), KIND_FLOORS[("http", "write")], ["side_effect_level"]),
        (ToolPolicy("external", "never"), KIND_FLOORS[("http", "write")], ["approval_policy"]),
        # R2.4: over a platform tool that always asks, `conditional` loosens.
        (
            ToolPolicy("external", "conditional"),
            ToolPolicy("external", "always"),
            ["approval_policy"],
        ),
        (ToolPolicy("internal", "always"), ToolPolicy("external", "always"), ["side_effect_level"]),
        # Tightening, and standing exactly on the floor, are accepted.
        (ToolPolicy("external", "always"), ToolPolicy("external", "conditional"), []),
        (ToolPolicy("critical", "always"), KIND_FLOORS[("http", "write")], []),
        (ToolPolicy("external", "conditional"), KIND_FLOORS[("http", "write")], []),
        (ToolPolicy("none", "never"), KIND_FLOORS[("object_crud", "read")], []),
    ],
)
def test_a_policy_may_tighten_its_floor_and_never_loosen_it(
    policy: ToolPolicy, floor: ToolPolicy, refused: list[str]
) -> None:
    """R2.3, R2.4 (TS4): `kind_floor_violation`, naming the axis."""
    if not refused:
        check_policy_against_floor(policy, floor)
        return
    with pytest.raises(DomainError) as found:
        check_policy_against_floor(policy, floor)
    assert found.value.code == "validation_failed"
    assert found.value.details["reason_code"] == "kind_floor_violation"
    assert found.value.details["fields"] == refused


def test_an_http_binding_writes_unless_its_method_reads() -> None:
    assert ToolBinding("http", {"method": "post"}, operation="read").effective_operation() == (
        "write"
    )
    assert ToolBinding("http", {"method": "GET"}).effective_operation() == "read"
    assert ToolBinding("object_crud").effective_operation() == "write"


def test_a_tool_below_its_kinds_floor_is_never_registered() -> None:
    """R2.3 (TS4): an `object_crud` write declared `none` is refused at
    assembly with `ConfigError`, and nothing is registered."""
    registry = ToolRegistry()
    tools, factories = assembler(registry)
    definition = make_definition(
        name="obj_lead.update", side_effect_level="none", approval_policy="never"
    )
    with pytest.raises(ConfigError) as refused:
        tools.assemble(
            ToolBinding(kind="object_crud", operation="write"), contract(definition), tenant_id=None
        )
    assert refused.value.details["reason_code"] == "kind_floor_violation"
    assert factories["object_crud"].built == []
    with pytest.raises(NotFoundError):
        registry.resolve("obj_lead.update", "1.0.0", tenant_id=None)


def test_a_tenant_override_below_its_platform_tool_is_never_registered() -> None:
    """R2.4 (TS4): the platform tool always asks; the tenant's version may
    not ask only sometimes. Its equal is accepted."""
    registry = ToolRegistry()
    tools, _ = assembler(registry)
    tenant = TenantId(uuid.uuid4())
    platform = make_definition(name="connector_action.send", approval_policy="always")
    binding = ToolBinding(kind="connector_action", operation="write")
    looser = make_definition(name="connector_action.send", approval_policy="conditional")
    with pytest.raises(ConfigError) as refused:
        tools.assemble(binding, contract(looser), tenant_id=tenant, over=platform)
    assert refused.value.details["fields"] == ["approval_policy"]
    with pytest.raises(NotFoundError):
        registry.resolve("connector_action.send", "1.0.0", tenant_id=tenant)
    tools.assemble(binding, contract(platform), tenant_id=tenant, over=platform)
    assert registry.resolve("connector_action.send", "1.0.0", tenant_id=tenant)


def test_a_schema_outside_the_profile_is_never_assembled() -> None:
    registry = ToolRegistry()
    tools, factories = assembler(registry)
    open_schema = {"type": "object", "properties": {}}
    with pytest.raises(ConfigError):
        tools.assemble(
            ToolBinding(kind="object_crud", operation="read"),
            ToolContract(
                definition=make_definition(
                    name="obj_lead.search", side_effect_level="none", approval_policy="never"
                ),
                input_schema=open_schema,
                output_schema=LEAD_OUTPUT,
            ),
            tenant_id=None,
        )
    assert factories["object_crud"].built == []
