import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import route_cost
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, RoutingModelGateway
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry
from dw_agent_runtime.ports import ModelOutputInvalidError, ModelRequest
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import DomainError, NotFoundError

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


def make_run_context() -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="demo_approval",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset({"demo.read"}),
        trace_id="trace-1",
    )


def make_prompt(**overrides: object) -> PromptArtifact:
    defaults: dict[str, object] = {
        "schema_version": "1.0",
        "prompt_id": "demo.summarize",
        "version": "1.0.0",
        "system": "Bạn là trợ lý tóm tắt.",
        "template": "Tóm tắt nội dung: {content}",
        "variables": frozenset({"content"}),
    }
    defaults.update(overrides)
    return PromptArtifact.model_validate(defaults)


class SummaryOutput(BaseModel):
    summary: str
    language: str


def test_prompt_render_strict_variables() -> None:
    registry = PromptRegistry()
    registry.register(make_prompt())
    rendered = registry.render("demo.summarize", "1.0.0", {"content": "cuộc họp tuần"})
    assert "cuộc họp tuần" in rendered.user
    with pytest.raises(DomainError, match="variables mismatch"):
        registry.render("demo.summarize", "1.0.0", {})
    with pytest.raises(DomainError, match="variables mismatch"):
        registry.render("demo.summarize", "1.0.0", {"content": "x", "extra": "y"})
    with pytest.raises(NotFoundError):
        registry.render("demo.summarize", "2.0.0", {"content": "x"})


def test_prompt_duplicate_rejected() -> None:
    registry = PromptRegistry()
    registry.register(make_prompt())
    with pytest.raises(ConfigError, match="already registered"):
        registry.register(make_prompt())


def test_model_profiles_load_from_repo_configs() -> None:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    balanced = profiles.resolve("balanced")
    assert balanced.structured_extraction.provider == "mock"
    assert balanced.budgets.max_cost_usd_per_run == 2.0
    with pytest.raises(NotFoundError):
        profiles.resolve("premium")


def make_gateway(adapter: MockModelAdapter) -> RoutingModelGateway:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    return RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=InMemoryUsageRecorder(),
        default_profile="balanced",
    )


async def test_gateway_returns_validated_output_and_records_usage() -> None:
    adapter = MockModelAdapter()
    adapter.register_builder(
        "demo.summarize",
        "1.0.0",
        lambda prompt: {"summary": "Ba quyết định chính.", "language": "vi"},
    )
    gateway = make_gateway(adapter)
    recorder = gateway.usage_recorder
    assert isinstance(recorder, InMemoryUsageRecorder)

    request = ModelRequest(
        task="structured_extraction",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "họp giao ban"},
        model_profile="balanced",
    )
    output = await gateway.generate_structured(
        request, SummaryOutput, run_context=make_run_context()
    )
    assert output.language == "vi"
    assert len(adapter.calls) == 1
    assert recorder.records[0][1].provider == "mock"


async def test_recorded_usage_carries_the_route_price() -> None:
    """What the ledger stores has to be what the budget ceiling counted.

    The two were computed apart: the ceiling priced the call from the route and
    the recorder was handed the provider's own figure, which behind this gateway
    is always zero - so every priced call landed in the ledger with a NULL cost
    and the bill could not be read back from the database.
    """
    adapter = MockModelAdapter()
    adapter.register_builder(
        "demo.summarize",
        "1.0.0",
        lambda prompt: {"summary": "Ba quyết định chính.", "language": "vi"},
    )
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    recorder = InMemoryUsageRecorder()
    gateway = RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"openai_responses": adapter},
        usage_recorder=recorder,
        default_profile="balanced",
    )
    run_context = make_run_context()

    await gateway.generate_structured(
        ModelRequest(
            task="structured_extraction",
            prompt_id="demo.summarize",
            prompt_version="1.0.0",
            variables={"content": "họp giao ban"},
            model_profile="gateway",
        ),
        SummaryOutput,
        run_context=run_context,
    )

    recorded = recorder.records[0][1]
    route = profiles.resolve("gateway").structured_extraction
    expected = route_cost(route, recorded.input_tokens, recorded.output_tokens)
    assert expected > 0.0
    assert recorded.cost_usd == expected
    spend = gateway.budget.spend[run_context.run_id]
    assert spend.cost_usd == expected


async def test_an_unpriced_route_records_no_cost() -> None:
    """Zero is not a price. `balanced` declares none, so nothing is charged."""
    adapter = MockModelAdapter()
    adapter.register_builder(
        "demo.summarize",
        "1.0.0",
        lambda prompt: {"summary": "Ba quyết định chính.", "language": "vi"},
    )
    gateway = make_gateway(adapter)
    recorder = gateway.usage_recorder
    assert isinstance(recorder, InMemoryUsageRecorder)

    await gateway.generate_structured(
        ModelRequest(
            task="structured_extraction",
            prompt_id="demo.summarize",
            prompt_version="1.0.0",
            variables={"content": "x"},
            model_profile="balanced",
        ),
        SummaryOutput,
        run_context=make_run_context(),
    )

    assert recorder.records[0][1].cost_usd == 0.0


async def test_gateway_rejects_schema_invalid_mock_response() -> None:
    adapter = MockModelAdapter()
    adapter.register_builder("demo.summarize", "1.0.0", lambda prompt: {"wrong_field": True})
    gateway = make_gateway(adapter)
    request = ModelRequest(
        task="structured_extraction",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "x"},
    )
    # The specific type, so a caller degrading to "not understood" can catch
    # exactly this; still a DomainError for every caller that does not care.
    with pytest.raises(ModelOutputInvalidError, match="schema validation") as raised:
        await gateway.generate_structured(request, SummaryOutput, run_context=make_run_context())
    assert isinstance(raised.value, DomainError)


async def test_gateway_unknown_provider_fails_fast() -> None:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    gateway = RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={},
        usage_recorder=InMemoryUsageRecorder(),
        default_profile="balanced",
    )
    request = ModelRequest(
        task="reasoning",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "x"},
    )
    with pytest.raises(NotFoundError, match="provider"):
        await gateway.generate_structured(request, SummaryOutput, run_context=make_run_context())


def test_extract_json_object_tolerates_fences_and_preamble() -> None:
    from dw_agent_runtime.adapters.openai_compatible import _extract_json_object

    assert _extract_json_object('{"a": 1}') == {"a": 1}
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_object('Kết quả:\n{"a": {"b": 2}} xong') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        _extract_json_object("no json here")
    with pytest.raises(ValueError):
        _extract_json_object("[1, 2]")


async def test_gateway_retries_once_on_schema_invalid_output() -> None:
    attempts: list[int] = []

    def flaky_builder(prompt: object) -> dict[str, object]:
        attempts.append(1)
        if len(attempts) == 1:
            return {"wrong_field": True}
        return {"summary": "Lần hai chuẩn.", "language": "vi"}

    adapter = MockModelAdapter()
    adapter.register_builder("demo.summarize", "1.0.0", flaky_builder)
    gateway = make_gateway(adapter)
    request = ModelRequest(
        task="structured_extraction",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "x"},
    )
    output = await gateway.generate_structured(
        request, SummaryOutput, run_context=make_run_context()
    )
    assert output.summary == "Lần hai chuẩn."
    assert len(attempts) == 2


async def test_gateway_uses_fallback_route_when_primary_provider_errors() -> None:
    from dw_agent_runtime.model.profiles import ModelBudgets, ModelProfile, ModelRoute
    from dw_kernel.errors import InfrastructureError

    class FailingAdapter:
        provider_name = "flaky"

        async def complete_json(
            self, prompt: Any, json_schema: Any, route: Any, *, max_output_tokens: Any
        ) -> Any:
            raise InfrastructureError("provider down")

    mock = MockModelAdapter()
    mock.register_builder(
        "demo.summarize", "1.0.0", lambda prompt: {"summary": "từ fallback", "language": "vi"}
    )
    profiles = ModelProfileRegistry()
    profiles.register(
        ModelProfile(
            schema_version="1.0",
            profile_id="with_fallback",
            routing_policy_version="1.0.0",
            structured_extraction=ModelRoute(provider="flaky", model="primary-1"),
            reasoning=ModelRoute(provider="flaky", model="primary-1"),
            fallback=ModelRoute(provider="mock", model="fallback-1"),
            budgets=ModelBudgets(),
        )
    )
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    gateway = RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"flaky": FailingAdapter(), "mock": mock},
        usage_recorder=InMemoryUsageRecorder(),
        default_profile="with_fallback",
    )
    request = ModelRequest(
        task="structured_extraction",
        prompt_id="demo.summarize",
        prompt_version="1.0.0",
        variables={"content": "x"},
        model_profile="with_fallback",
    )
    output = await gateway.generate_structured(
        request, SummaryOutput, run_context=make_run_context()
    )
    assert output.summary == "từ fallback"


class _SchemaSeen:
    """Keeps the schema each call asks the provider to answer in."""

    provider_name = "mock"

    def __init__(self) -> None:
        self.asked: list[Any] = []

    async def complete_json(
        self, prompt: Any, json_schema: Any, route: Any, *, max_output_tokens: Any
    ) -> Any:
        from dw_agent_runtime.model.gateway import ModelUsage

        self.asked.append(json_schema)
        usage = ModelUsage(provider="mock", model=route.model, input_tokens=1, output_tokens=1)
        return {"summary": "x", "language": "vi"}, usage, None


def _asking_gateway(adapter: _SchemaSeen) -> RoutingModelGateway:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    return RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=InMemoryUsageRecorder(),
        default_profile="balanced",
    )


async def test_a_request_with_its_own_schema_asks_the_provider_in_it() -> None:
    """A caller whose contract is a JSON Schema (a workflow step) has the
    provider asked in that schema; the output type only parses the answer."""
    adapter = _SchemaSeen()
    schema: dict[str, object] = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }
    request = _UNNAMED.model_copy(update={"output_schema": schema})
    await _asking_gateway(adapter).generate_structured(
        request, SummaryOutput, run_context=make_run_context()
    )
    assert adapter.asked == [schema]


async def test_a_request_without_one_asks_in_the_output_types_schema() -> None:
    adapter = _SchemaSeen()
    await _asking_gateway(adapter).generate_structured(
        _UNNAMED, SummaryOutput, run_context=make_run_context()
    )
    assert adapter.asked == [SummaryOutput.model_json_schema()]


class _Down:
    """A provider that is always unavailable, so only a fallback answers."""

    provider_name = "down"

    async def complete_json(
        self, prompt: Any, json_schema: Any, route: Any, *, max_output_tokens: Any
    ) -> Any:
        from dw_kernel.errors import InfrastructureError

        raise InfrastructureError("provider down")


class _ProfileRecorder:
    """Keeps the profile each recorded request names, next to its usage."""

    def __init__(self) -> None:
        self.records: list[tuple[str | None, str]] = []

    async def record(self, run_context: RunContext, request: ModelRequest, usage: Any) -> None:
        self.records.append((request.model_profile, usage.model))


def _profile(profile_id: str, model: str, *, fallback: str | None = None) -> Any:
    from dw_agent_runtime.model.profiles import ModelProfile, ModelRoute

    primary = ModelRoute(provider="down" if fallback else "mock", model=model)
    return ModelProfile(
        schema_version="1.0",
        profile_id=profile_id,
        routing_policy_version="1.0.0",
        structured_extraction=primary,
        reasoning=primary,
        fallback=ModelRoute(provider="mock", model=fallback) if fallback else None,
    )


def _summarizing_gateway(
    profiles: ModelProfileRegistry, recorder: _ProfileRecorder, *, default_profile: str
) -> RoutingModelGateway:
    adapter = MockModelAdapter()
    adapter.register_builder(
        "demo.summarize", "1.0.0", lambda prompt: {"summary": "x", "language": "vi"}
    )
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    return RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"mock": adapter, "down": _Down()},
        usage_recorder=recorder,
        default_profile=default_profile,
    )


_UNNAMED = ModelRequest(
    task="structured_extraction",
    prompt_id="demo.summarize",
    prompt_version="1.0.0",
    variables={"content": "x"},
)


async def test_a_request_naming_no_profile_runs_on_the_deployments_own() -> None:
    """A context's calls often name no profile. They ran on `balanced` whatever
    the deployment configured, so one set up for a real model sent every one
    of them to the mock profile, where each failed."""
    profiles = ModelProfileRegistry()
    profiles.register(_profile("balanced", "platform-default-1"))
    profiles.register(_profile("deployment", "deployment-1"))
    recorder = _ProfileRecorder()
    gateway = _summarizing_gateway(profiles, recorder, default_profile="deployment")

    await gateway.generate_structured(_UNNAMED, SummaryOutput, run_context=make_run_context())

    # The recorders (the trace among them) name the profile actually used.
    assert recorder.records == [("deployment", "deployment-1")]


async def test_a_request_naming_a_profile_keeps_it() -> None:
    profiles = ModelProfileRegistry()
    profiles.register(_profile("balanced", "platform-default-1"))
    profiles.register(_profile("deployment", "deployment-1"))
    recorder = _ProfileRecorder()
    gateway = _summarizing_gateway(profiles, recorder, default_profile="deployment")

    await gateway.generate_structured(
        _UNNAMED.model_copy(update={"model_profile": "balanced"}),
        SummaryOutput,
        run_context=make_run_context(),
    )

    assert recorder.records == [("balanced", "platform-default-1")]


async def test_a_tenants_own_profile_routes_its_calls_and_no_one_elses() -> None:
    """The route read the platform's profile while the budget read the
    tenant's, so a tenant on its own model contract was billed against its
    own ceiling on the platform's model."""
    tenant = uuid.uuid4()
    profiles = ModelProfileRegistry()
    profiles.register(_profile("deployment", "platform-1"))
    profiles.register(_profile("deployment", "tenant-own-1"), tenant_id=tenant)
    recorder = _ProfileRecorder()
    gateway = _summarizing_gateway(profiles, recorder, default_profile="deployment")

    own = make_run_context().model_copy(update={"tenant_id": tenant})
    await gateway.generate_structured(_UNNAMED, SummaryOutput, run_context=own)
    await gateway.generate_structured(_UNNAMED, SummaryOutput, run_context=make_run_context())

    assert [model for _, model in recorder.records] == ["tenant-own-1", "platform-1"]


async def test_a_tenants_own_profile_supplies_its_fallback() -> None:
    tenant = uuid.uuid4()
    profiles = ModelProfileRegistry()
    profiles.register(_profile("deployment", "primary-1", fallback="platform-fallback-1"))
    profiles.register(
        _profile("deployment", "primary-1", fallback="tenant-fallback-1"), tenant_id=tenant
    )
    recorder = _ProfileRecorder()
    gateway = _summarizing_gateway(profiles, recorder, default_profile="deployment")

    own = make_run_context().model_copy(update={"tenant_id": tenant})
    await gateway.generate_structured(_UNNAMED, SummaryOutput, run_context=own)

    assert [model for _, model in recorder.records] == ["tenant-fallback-1"]
