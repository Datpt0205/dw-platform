"""The tool registry's two layers, through the executor (tools-and-skills
ticket 01: R2.1; `CLAUDE.md` "Per-tenant artifacts").

A tenant's tool is resolved for that tenant's run, then the platform's; never
another tenant's, and an inventory answer reads the platform layer only.
"""

from __future__ import annotations

import uuid

import pytest
from fakes import NOW, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from pydantic import BaseModel
from test_executor import EchoInput, EchoOutput, make_definition, make_run_context

from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_kernel.errors import ConfigError, NotFoundError
from dw_kernel.ids import TenantId
from dw_kernel.ports import FixedClock, SequentialIdGenerator

pytestmark = pytest.mark.unit

A = uuid.uuid4()
B = uuid.uuid4()
OWN = make_definition(name="acme.quote", side_effect_level="internal")


class Answer:
    def __init__(self, who: str) -> None:
        self.who = who
        self.calls = 0

    async def __call__(self, payload: BaseModel, run_context: RunContext) -> EchoOutput:
        self.calls += 1
        return EchoOutput(echoed=self.who)


def tool(definition: object, answer: Answer) -> RegisteredTool:
    return RegisteredTool(
        definition,  # type: ignore[arg-type]
        pydantic_behaviour(EchoInput, EchoOutput, answer),
    )


def executor(registry: ToolRegistry) -> ToolExecutor:
    store = FakeExecutionStore()
    return ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=FakeUoWFactory(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
        steps=build_tool_executor_steps(),
    )


def run_of(tenant: uuid.UUID) -> RunContext:
    return make_run_context().model_copy(update={"tenant_id": tenant})


async def _call(ex: ToolExecutor, name: str, tenant: uuid.UUID) -> BaseModel:
    return await ex.execute(
        name=name,
        version="1.0.0",
        raw_input={"message": "x"},
        run_context=run_of(tenant),
        # A key per call: the fake store, unlike the SQL one, is not per tenant.
        idempotency_key=str(uuid.uuid4()),
    )


async def test_a_tenants_tool_is_not_found_for_another_tenant() -> None:
    """R2.1: B's run naming A's tool is `not_found`, and A's handler does not
    run; A's run reaches it."""
    registry = ToolRegistry()
    answer = Answer("a")
    registry.register(tool(OWN, answer), tenant_id=TenantId(A))
    ex = executor(registry)
    with pytest.raises(NotFoundError):
        await _call(ex, "acme.quote", B)
    assert answer.calls == 0
    output = await _call(ex, "acme.quote", A)
    assert isinstance(output, EchoOutput) and output.echoed == "a" and answer.calls == 1


async def test_without_its_own_a_tenant_gets_the_platforms_never_another_tenants() -> None:
    """R2.1: one name in three layers; B has none of its own."""
    registry = ToolRegistry()
    platform, own_a = Answer("platform"), Answer("a")
    registry.register(tool(OWN, platform))
    registry.register(tool(OWN, own_a), tenant_id=TenantId(A))
    ex = executor(registry)
    for _ in range(2):
        output = await _call(ex, "acme.quote", B)
        assert isinstance(output, EchoOutput) and output.echoed == "platform"
    output = await _call(ex, "acme.quote", A)
    assert isinstance(output, EchoOutput) and output.echoed == "a"
    assert own_a.calls == 1


def test_inventory_answers_read_the_platform_layer_only() -> None:
    """R2.1: `has_tool`, `all_definitions` and `definitions_for` do not see
    a tenant's tool."""
    registry = ToolRegistry()
    registry.register(tool(OWN, Answer("a")), tenant_id=TenantId(A))
    assert not registry.has_tool("acme.quote")
    assert registry.all_definitions() == []
    with pytest.raises(NotFoundError):
        registry.definitions_for([("acme.quote", "1.0.0")])


def test_one_version_twice_in_one_layer_is_refused_and_an_override_is_not() -> None:
    registry = ToolRegistry()
    registry.register(tool(OWN, Answer("platform")))
    registry.register(tool(OWN, Answer("a")), tenant_id=TenantId(A))
    with pytest.raises(ConfigError):
        registry.register(tool(OWN, Answer("again")), tenant_id=TenantId(A))
    with pytest.raises(ConfigError):
        registry.register(tool(OWN, Answer("again")))
