"""The one place a process builds its model gateway and usage recorders.

The API calls models in its requests and runs; the worker calls them in lanes no
request ever touched (the Zalo poll lane reads a chat message with one). Both
must ask the same limits before every call and record into the same ledger. Two
builders agree only until one of them is edited, so there is one — the same
reason `dw_knowledge.adapters.embedding_factory` exists for embedders.

It takes a `ModelProviderConfig`, not a settings object: each process has its
own settings class, and mapping it is the composition root's business.

What it builds:

- the model resolver (`build_model_resolver`): the platform profiles under
  `configs/models`, the plan catalogue and, where Studio runs are taken, the
  manifests they pinned, with the deployment's profile as the default every
  door asks for (model-connections R1.1);
- the provider adapters (`build_model_adapters`), with the SSRF guard on the
  endpoint and the mock refused in a deployed profile;
- the usage recorders: the usage ledger the composition root hands in (a
  `dw_usage` recorder, whose write of a permitted call settles it into its
  lease; usage-and-limits R3.1, R5.11), the run's cost and telemetry, behind
  the composite that lets no recorder take a call down;
- the gateway priced by the price book the composition root hands in
  (`PricingPort`, R2.1);
- the gateway asking the `LimitsPort` the composition root hands in before
  every call (R5.2);
- `ModelStack.one_call()`: the gateway for a caller whose run is one call,
  which takes the call's lease first and gives it back after
  (`SingleCallModelGateway`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.adapters.openai_compatible import OpenAICompatibleAdapter
from dw_agent_runtime.adapters.openai_responses import OpenAIResponsesAdapter
from dw_agent_runtime.adapters.run_cost_recorder import RunCostRecorder
from dw_agent_runtime.adapters.telemetry_usage import TelemetryUsageRecorder
from dw_agent_runtime.adapters.usage_recorders import CompositeUsageRecorder
from dw_agent_runtime.model.gateway import ModelProviderAdapter, UsageRecorderPort
from dw_agent_runtime.model.pricing import PricingPort
from dw_agent_runtime.model.profiles import ModelProfileRegistry, Provider
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.model.routing import RoutingModelGateway
from dw_agent_runtime.model.single_call import SingleCallModelGateway
from dw_agent_runtime.ports import (
    LimitsPort,
    PinnedEnginePort,
    PlanModelProfilesPort,
    RunControlPort,
)
from dw_kernel.net_guard import ensure_allowed_outbound_url
from dw_kernel.ports import SystemClock, UtcClock
from dw_kernel.residency import ResidencyGate
from dw_kernel.resilience import CircuitBreaker
from dw_observability.telemetry import TelemetryPort


class MockModelForbiddenError(RuntimeError):
    """A deployed profile asked for the fixture model."""


@dataclass(frozen=True)
class ModelProviderConfig:
    """What a process's settings say about its model provider."""

    # "mock" (fixtures, local/test only) or anything else for a real gateway.
    provider: str
    # Which profile a request naming none runs on.
    model_profile: str
    profile: str
    is_deployed: bool
    openai_api_key: str | None
    openai_base_url: str | None
    openai_structured_mode: str = "json_schema"
    openai_strict_schema: bool = True
    outbound_allowed_hosts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allow_private_endpoints(self) -> bool:
        """Local/test may call a localhost provider; a deployed profile never does."""
        return not self.is_deployed


def build_model_resolver(
    config: ModelProviderConfig,
    *,
    profiles_dir: Path,
    plans: PlanModelProfilesPort,
    pinned: PinnedEnginePort | None = None,
) -> ModelResolver:
    """The process's one `ModelResolver`: the platform layer from `profiles_dir`
    (no production code loads a tenant layer in W1), the plan catalogue the
    composition root built, and `config.model_profile` as the default, checked
    against the platform layer here so a profile nobody registered fails at
    startup, not on the first call."""
    profiles = ModelProfileRegistry()
    profiles.load_directory(profiles_dir)
    return ModelResolver(profiles, plans, config.model_profile, pinned)


def build_model_adapters(
    config: ModelProviderConfig, *, mock_fixtures_dir: Path
) -> dict[str, ModelProviderAdapter]:
    adapters: dict[str, ModelProviderAdapter] = {}
    if config.provider == "mock":
        if config.is_deployed:
            raise MockModelForbiddenError(
                f"the mock model provider is forbidden in the {config.profile} profile"
            )
        adapters[Provider.MOCK] = MockModelAdapter(fixtures_dir=mock_fixtures_dir)
    if config.openai_api_key and config.openai_base_url:
        # SSRF guard: a provider endpoint must be public outside local development.
        base_url = ensure_allowed_outbound_url(
            config.openai_base_url,
            allow_private=config.allow_private_endpoints,
            allowed_hosts=config.outbound_allowed_hosts,
        )
        adapters[Provider.OPENAI_COMPATIBLE] = OpenAICompatibleAdapter(
            base_url=base_url,
            api_key=config.openai_api_key,
            structured_mode=config.openai_structured_mode,
            breaker=CircuitBreaker(clock=SystemClock(), name="model.openai_compatible"),
        )
        # Responses-dialect adapter (real OpenAI only): same credentials, but
        # /v1/responses returns the model's reasoning summary for visible
        # thinking. Profiles opt in with `provider: openai_responses`.
        adapters[Provider.OPENAI_RESPONSES] = OpenAIResponsesAdapter(
            base_url=base_url,
            api_key=config.openai_api_key,
            strict_schema=config.openai_strict_schema,
            breaker=CircuitBreaker(clock=SystemClock(), name="model.openai_responses"),
        )
    if config.is_deployed and Provider.OPENAI_COMPATIBLE not in adapters:
        raise RuntimeError(f"the {config.profile} profile requires a real model provider")
    return adapters


@dataclass(frozen=True)
class ModelStack:
    gateway: RoutingModelGateway
    usage_recorder: UsageRecorderPort
    # The process's one limits port, the gateway's and every agent's.
    limits: LimitsPort

    def one_call(self) -> SingleCallModelGateway:
        """The gateway for a caller whose run is this one call: its lease taken
        before it and given back after it."""
        return SingleCallModelGateway(inner=self.gateway, limits=self.limits)


def build_model_stack(
    config: ModelProviderConfig,
    *,
    models: ModelResolver,
    prompts: PromptRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    clock: UtcClock,
    telemetry: TelemetryPort,
    mock_fixtures_dir: Path,
    pricing: PricingPort,
    ledger: UsageRecorderPort,
    run_control: RunControlPort,
    residency: ResidencyGate,
    limits: LimitsPort,
) -> ModelStack:
    """`pricing`, `ledger` and `limits` come from `dw_usage`, which this package
    may not import: the composition root builds them and passes them, so both
    processes price by one book, write one ledger and hold one set of limits
    (usage-and-limits R2.1, R3.1, R5.1)."""
    # The composite stays because a recorder that raises must not take the call
    # down.
    recorder = CompositeUsageRecorder(
        [
            # One row per call, the source of the usage screen (R3.1), and the
            # settlement of a permitted call into its lease (R5.11).
            ledger,
            # A run's own spend, which a DW's scorecard reads (digital-worker R7.3).
            RunCostRecorder(session_factory=session_factory),
            TelemetryUsageRecorder(telemetry),
        ]
    )
    gateway = RoutingModelGateway(
        models=models,
        prompts=prompts,
        adapters=build_model_adapters(config, mock_fixtures_dir=mock_fixtures_dir),
        usage_recorder=recorder,
        pricing=pricing,
        # The process's one port, the gateway's first door (agent-lifecycle R7.1).
        run_control=run_control,
        # The process's one gate, after the freeze and before the limits
        # (compliance-pdpl R2.3).
        residency=residency,
        # Every call asks the run's lease first (R5.2).
        limits=limits,
        clock=clock,
    )
    return ModelStack(gateway=gateway, usage_recorder=recorder, limits=limits)
