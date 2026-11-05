"""The residency gate at every model door of the runtime (compliance-pdpl R2.2,
R2.3; ADR-0123 decision 4; CP2, CP3).

Each door is tested on its own, never only through the layer above it
(failure-modes #5): the structured gateway (a run's own resolution and a Studio
run's pinned routes), the agent loop's middleware, a sub-agent's stack and
context compaction. A refusal sends nothing, records no usage and charges
nothing, and a `vn` route that fails never falls through to a `foreign` one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from test_agent_factory import ABROAD_TENANT, _spec
from test_executor import make_run_context

from dw_agent_runtime.adapters.agent_factory import platform_middleware
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.model_retry import ModelRetryMiddleware
from dw_agent_runtime.adapters.residency_middleware import ResidencyGateMiddleware
from dw_agent_runtime.adapters.run_budget import RunBudgetMiddleware
from dw_agent_runtime.adapters.run_control_middleware import RunControlMiddleware
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec, sub_agent_spec
from dw_agent_runtime.adapters.telemetry_usage import TelemetryUsageRecorder
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.model.gateway import (
    InMemoryUsageRecorder,
    ModelUsage,
    RoutingModelGateway,
)
from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry, RenderedPrompt
from dw_agent_runtime.model.resolver import pin_entry
from dw_agent_runtime.ports import ModelRequest
from dw_agent_runtime.testing.models import AnyManifest
from dw_agent_runtime.testing.models import resolver as model_resolver
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.errors import InfrastructureError
from dw_kernel.residency import RESIDENCY_SPAN, ResidencyRefusedError, RouteClass
from dw_observability.semconv import DW_RESIDENCY_CHECK, contract_violations, load_snapshot
from dw_observability.semconv import snapshot_path as semconv_snapshot
from dw_observability.telemetry import RecordingTelemetry
from dw_platform.testing.residency import run_gate

pytestmark = pytest.mark.unit

PROFILE = "residency_test"
REPO_ROOT = Path(__file__).resolve().parents[5]


def _route(provider: str, location: str, processor: str, model: str) -> dict[str, object]:
    return {
        "provider": provider,
        "model": model,
        "data_location": location,
        "processor": processor,
        "retention_days": 0,
        "no_training": True,
        "capabilities": {"max_input_tokens": 8000},
    }


VN = _route("vn_provider", "vn", "viettel_ai", "vn-model")
ABROAD = _route("abroad_provider", "foreign", "openai", "abroad-model")


def _profile(primary: dict[str, object], fallback: dict[str, object] | None) -> ModelProfile:
    body: dict[str, object] = {
        "schema_version": "2.0",
        "profile_id": PROFILE,
        "routing_policy_version": "1.0.0",
        "structured_extraction": primary,
        "reasoning": primary,
        "chat": primary,
        "budgets": {"max_input_tokens_per_run": 100_000, "max_cost_usd_per_run": 100.0},
    }
    if fallback is not None:
        body["fallback"] = fallback
    return ModelProfile.model_validate(body)


def _registry(primary: dict[str, object], fallback: dict[str, object] | None = None) -> Any:
    profiles = ModelProfileRegistry()
    profiles.register(_profile(primary, fallback))
    return profiles


@dataclass
class _Provider:
    """One provider's adapter: counts what reached it, fails when told to."""

    name: str
    fail: bool = False
    calls: int = 0

    @property
    def provider_name(self) -> str:
        return self.name

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        self.calls += 1
        if self.fail:
            raise InfrastructureError("503 from the provider", details={"status": 503})
        usage = ModelUsage(provider=self.name, model=route.model, input_tokens=5, output_tokens=3)
        return {"answer": "xong"}, usage, None


class _Answer(BaseModel):
    answer: str


@dataclass
class _World:
    vn: _Provider = field(default_factory=lambda: _Provider("vn_provider"))
    abroad: _Provider = field(default_factory=lambda: _Provider("abroad_provider"))
    recorder: InMemoryUsageRecorder = field(default_factory=InMemoryUsageRecorder)
    budget: RunBudgetLedger = field(default_factory=RunBudgetLedger)

    def gateway(self, profiles: Any, *, pinned: Any = None) -> RoutingModelGateway:
        prompts = PromptRegistry()
        prompts.register(
            PromptArtifact(
                schema_version="1.0",
                prompt_id="demo.ask",
                version="1.0.0",
                system="Trả lời.",
                template="{question}",
                variables=frozenset({"question"}),
            )
        )
        return RoutingModelGateway(
            models=model_resolver(profiles, PROFILE, pinned=pinned),
            prompts=prompts,
            adapters={"vn_provider": self.vn, "abroad_provider": self.abroad},
            usage_recorder=self.recorder,
            pricing=FlatPricing(prices={"vn-model": (Decimal("0"), Decimal("0"))}),
            run_control=OpenRunControl(),
            residency=run_gate(),
            budget=self.budget,
        )


def _run(route_class: RouteClass = "vn_only", **fields: Any) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="residency_test",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
        route_class=route_class,
        **fields,
    )


_ASK = ModelRequest(
    task="structured_extraction",
    prompt_id="demo.ask",
    prompt_version="1.0.0",
    variables={"question": "Khách hỏi gì?"},
)


# ---- the structured gateway ---------------------------------------------------


async def test_a_vn_only_run_never_reaches_a_foreign_route() -> None:
    """CP2: refused before the send; no provider call, no usage, no spend."""
    world = _World()
    gateway = world.gateway(_registry(ABROAD))
    run = _run("vn_only")

    with pytest.raises(ResidencyRefusedError) as refused:
        await gateway.generate_structured(_ASK, _Answer, run_context=run)

    assert refused.value.details["reason_code"] == "residency_refused"
    assert world.abroad.calls == 0
    assert world.recorder.records == []
    assert run.run_id not in world.budget.spend


async def test_a_failing_vn_route_does_not_fall_through_to_a_foreign_fallback() -> None:
    """CP2: the `vn` route answers 503 twice, the `foreign` fallback is never
    tried, and the run ends refused (R2.2)."""
    world = _World(vn=_Provider("vn_provider", fail=True))
    gateway = world.gateway(_registry(VN, ABROAD))

    with pytest.raises(ResidencyRefusedError) as refused:
        await gateway.generate_structured(_ASK, _Answer, run_context=_run("vn_only"))

    assert refused.value.details["reason"] == "fallback_refused"
    assert isinstance(refused.value.__cause__, InfrastructureError)
    assert world.vn.calls == 2
    assert world.abroad.calls == 0


async def test_a_full_cross_border_run_does_fall_back() -> None:
    world = _World(vn=_Provider("vn_provider", fail=True))
    gateway = world.gateway(_registry(VN, ABROAD))

    await gateway.generate_structured(_ASK, _Answer, run_context=_run("cross_border_full"))

    assert (world.vn.calls, world.abroad.calls) == (2, 1)


async def test_a_refused_primary_leaves_an_admitted_fallback() -> None:
    world = _World()
    gateway = world.gateway(_registry(ABROAD, VN))

    await gateway.generate_structured(_ASK, _Answer, run_context=_run("vn_only"))

    assert (world.abroad.calls, world.vn.calls) == (0, 1)


@pytest.mark.parametrize(
    ("primary", "sent"), [(VN, True), (ABROAD, False)], ids=["vn route", "foreign route"]
)
async def test_minimised_sends_to_vn_and_refuses_abroad(
    primary: dict[str, object], sent: bool
) -> None:
    world = _World()
    gateway = world.gateway(_registry(primary))
    run = _run("cross_border_minimised")

    if sent:
        await gateway.generate_structured(_ASK, _Answer, run_context=run)
    else:
        with pytest.raises(ResidencyRefusedError):
            await gateway.generate_structured(_ASK, _Answer, run_context=run)

    assert world.vn.calls + world.abroad.calls == (1 if sent else 0)


async def test_a_studio_run_s_pinned_foreign_route_is_refused() -> None:
    """The door reads a Studio run's pinned routes (`PinnedEnginePort`), and
    the gate checks what was pinned, not what the platform holds now."""
    world = _World()
    abroad = _profile(ABROAD, None)
    pinned = AnyManifest(
        {
            "durability": "sync",
            "model_routes": {PROFILE: pin_entry(abroad, "platform")},
            "default_model_profile": PROFILE,
        }
    )
    # The current platform profile must match what was pinned, or the
    # resolver refuses first: pin and register the same foreign profile.
    profiles = ModelProfileRegistry()
    profiles.register(abroad)
    gateway = world.gateway(profiles, pinned=pinned)
    run = _run("vn_only", run_manifest_hash="sha256:" + "a" * 64)

    with pytest.raises(ResidencyRefusedError):
        await gateway.generate_structured(_ASK, _Answer, run_context=run)

    assert world.abroad.calls == 0


async def test_the_ledger_and_the_span_carry_the_class_location_and_processor() -> None:
    """R2.1: the call's usage names the run's class and the route's location
    and processor; the chat span carries them as identifiers."""
    telemetry = RecordingTelemetry()
    world = _World()
    gateway = world.gateway(_registry(VN))
    gateway.usage_recorder = TelemetryUsageRecorder(telemetry)
    gateway.residency = run_gate(telemetry)

    await gateway.generate_structured(_ASK, _Answer, run_context=_run("vn_only"))

    chat = [attrs for name, attrs in telemetry.spans if name.startswith("chat ")]
    assert chat and chat[0]["dw.route_class"] == "vn_only"
    assert (chat[0]["dw.data_location"], chat[0]["dw.processor"]) == ("vn", "viettel_ai")
    checks = [attrs for name, attrs in telemetry.spans if name == DW_RESIDENCY_CHECK]
    assert (
        checks
        == [
            {
                "dw.route_class": "vn_only",
                "dw.data_location": "vn",
                "dw.processor": "viettel_ai",
                "dw.residency.admitted": True,
            }
        ]
        * 2
    )
    assert contract_violations(load_snapshot(semconv_snapshot(REPO_ROOT)), telemetry) == []


def test_the_kernel_and_the_telemetry_contract_name_the_span_alike() -> None:
    assert RESIDENCY_SPAN == DW_RESIDENCY_CHECK


# ---- the agent loop -------------------------------------------------------------


class _Status503Error(Exception):
    status_code = 503


class _Failing(MockChatModel):
    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        self.calls.append(list(messages))
        raise _Status503Error("503")


def _loop(model: MockChatModel, profiles: Any, budget: RunBudgetLedger) -> Any:
    models = model_resolver(profiles, PROFILE)
    return create_agent(
        model=model,
        tools=[],
        middleware=[
            RunControlMiddleware(OpenRunControl()),
            ResidencyGateMiddleware(run_gate(), models, PROFILE),
            RunBudgetMiddleware(budget, models, PROFILE, FlatPricing()),
            ModelRetryMiddleware(backoff_seconds=0),
        ],
        context_schema=RunContext,
    )


async def test_the_agent_loop_refuses_a_foreign_chat_route_before_the_model() -> None:
    """CP2 at the loop's own door: the chat model is never called and the
    run's spend ledger is never charged (the gate sits before the limits)."""
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="x")
    budget = RunBudgetLedger()
    run = _run("vn_only")

    with pytest.raises(ResidencyRefusedError):
        await _loop(model, _registry(ABROAD), budget).ainvoke(
            {"messages": [HumanMessage("x")]}, context=run
        )

    assert model.calls == []
    assert run.run_id not in budget.spend


async def test_the_agent_loop_admits_a_vn_chat_route() -> None:
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="x")
    await _loop(model, _registry(VN), RunBudgetLedger()).ainvoke(
        {"messages": [HumanMessage("x")]}, context=_run("vn_only")
    )
    assert len(model.calls) == 1


async def test_the_agent_loop_retries_only_the_admitted_route() -> None:
    """CP2: `vn` first, `foreign` fallback, the `vn` route answers 503. The
    loop retries the route its chat model is bound to and never another; the
    foreign fallback is seen by the gate and not admitted."""
    model = _Failing(responses=[], mock_reply="x")
    telemetry = RecordingTelemetry()
    models = model_resolver(_registry(VN, ABROAD), PROFILE)
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[
            ResidencyGateMiddleware(run_gate(telemetry), models, PROFILE),
            ModelRetryMiddleware(backoff_seconds=0),
        ],
        context_schema=RunContext,
    )

    with pytest.raises(_Status503Error):
        await agent.ainvoke({"messages": [HumanMessage("x")]}, context=_run("vn_only"))

    assert len(model.calls) == 3
    admitted = [
        (attrs["dw.data_location"], attrs["dw.residency.admitted"])
        for name, attrs in telemetry.spans
        if name == DW_RESIDENCY_CHECK
    ]
    assert admitted == [("vn", True), ("foreign", False)]


# ---- where the middleware sits ---------------------------------------------------


def _order(stack: list[Any]) -> list[type]:
    kinds = (RunControlMiddleware, ResidencyGateMiddleware, RunBudgetMiddleware)
    return [type(m) for m in stack if isinstance(m, kinds)]


def test_the_platform_stack_puts_the_gate_after_the_freeze_and_before_the_limits() -> None:
    """usage-and-limits R6.5: a call the gate refuses reaches no limit."""
    spec = _spec(MockChatModel(responses=[AIMessage(content="xong")], mock_reply="x"))
    assert _order(platform_middleware(spec)) == [
        RunControlMiddleware,
        ResidencyGateMiddleware,
        RunBudgetMiddleware,
    ]


async def test_a_delegated_turn_asks_the_gate_at_its_own_model_call() -> None:
    """The parent's middleware does not run for a child turn, so the sub-agent
    stack carries its own gate, for the route the child's profile resolves to."""
    parent = _spec(MockChatModel(responses=[AIMessage(content="xong")], mock_reply="x"))
    child = SubAgentSpec(name="helper", description="d", offered=list(parent.offered)[:1])
    built = sub_agent_spec(parent, child)
    assert _order(built["middleware"]) == [
        RunControlMiddleware,
        ResidencyGateMiddleware,
        RunBudgetMiddleware,
    ]

    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="x")
    agent: Any = create_agent(
        model=model, tools=[], middleware=built["middleware"], context_schema=RunContext
    )
    # This tenant's own profile sends abroad (`test_agent_factory._models`).
    run = make_run_context().model_copy(update={"tenant_id": ABROAD_TENANT})
    with pytest.raises(ResidencyRefusedError):
        await agent.ainvoke({"messages": [HumanMessage("x")]}, context=run)
    assert model.calls == []
