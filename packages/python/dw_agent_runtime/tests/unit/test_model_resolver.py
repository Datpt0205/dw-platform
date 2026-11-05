"""`ModelResolver`: one answer for every model door (model-connections ticket 02:
R1.1, R1.2, R1.4-R1.6, R2.1, R2.2, R2.6; MR1, MR3, MR4, MR6).

The four doors are driven for real (the structured gateway, the budget
middleware and compaction inside an agent, the meter around a chat model), for
a company that has its own profile under the id the platform also ships. Each
door's route is read from what it priced, so a door that stops asking with the
run's context reads the platform's model and its assertion turns red. Which
company may see whose profile is `test_tenant_overlay.py` (MR2); what a Studio
run pins at admission is `dw_studio`'s `test_run_request.py`.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fakes import NOW, FakeAuditRepo, FakeUoWFactory
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from test_agent_factory import THREAD
from test_context_compaction import COPY, _history
from test_prompts_profiles_gateway import SummaryOutput, make_prompt

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.context_compaction import PlatformSummarizationMiddleware
from dw_agent_runtime.adapters.langchain_usage import LangchainUsageMeter
from dw_agent_runtime.adapters.run_budget import RunBudgetMiddleware
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, ModelUsage, RoutingModelGateway
from dw_agent_runtime.model.profiles import (
    ModelBudgets,
    ModelProfile,
    ModelProfileRegistry,
    ModelRoute,
)
from dw_agent_runtime.model.prompts import PromptRegistry, RenderedPrompt
from dw_agent_runtime.model.resolver import (
    ModelResolver,
    ResolvedRoute,
    StaticPlanModelProfiles,
    pin_entry,
    profile_hash,
)
from dw_agent_runtime.ports import ModelRequest
from dw_agent_runtime.registry import ConfigError
from dw_agent_runtime.testing.models import AnyManifest, route
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.errors import EntitlementDeniedError, PermissionDeniedError
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_platform.testing.residency import run_gate

pytestmark = pytest.mark.unit

ACME = uuid.UUID("11111111-1111-5111-8111-111111111111")
OTHER = uuid.UUID("22222222-2222-5222-8222-222222222222")
PLAN = "basic"
SHARED = "shared"
REPO_ROOT = Path(__file__).resolve().parents[5]


def _profile(prefix: str, *, budget_tokens: int = 1_000_000) -> ModelProfile:
    def r(name: str) -> ModelRoute:
        return route(model=f"{prefix}-{name}", capabilities={"max_input_tokens": 8000})

    return ModelProfile(
        schema_version="2.0",
        profile_id=SHARED,
        routing_policy_version="1.0.0",
        structured_extraction=r("extract"),
        reasoning=r("reason"),
        chat=r("chat"),
        fallback=r("fallback"),
        budgets=ModelBudgets(max_input_tokens_per_run=budget_tokens),
    )


def _registry() -> ModelProfileRegistry:
    registry = ModelProfileRegistry()
    registry.register(_profile("platform"))
    registry.register(_profile("acme"), tenant_id=ACME)
    return registry


def _models(
    registry: ModelProfileRegistry | None = None,
    *,
    plans: Any = None,
    pinned: Any = None,
) -> ModelResolver:
    return ModelResolver(
        _registry() if registry is None else registry,
        StaticPlanModelProfiles({PLAN: frozenset({SHARED})}) if plans is None else plans,
        SHARED,
        pinned,
    )


def _run(tenant: uuid.UUID = ACME, *, plan: str = PLAN, manifest: str | None = None) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=tenant,
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="test",
        worker_version="1.0.0",
        channel="web",
        plan_id=plan,
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
        run_manifest_hash=manifest,
    )


def _spy(models: ModelResolver) -> list[ResolvedRoute]:
    """Every answer `models` gives, in order."""
    answers: list[ResolvedRoute] = []
    inner: Callable[..., Awaitable[ResolvedRoute]] = models.resolve

    async def resolve(*args: Any, **kwargs: Any) -> ResolvedRoute:
        answer = await inner(*args, **kwargs)
        answers.append(answer)
        return answer

    models.resolve = resolve  # type: ignore[method-assign]
    return answers


class _Seen:
    """A provider adapter that keeps the route of every call it was sent."""

    provider_name = "mock"

    def __init__(self) -> None:
        self.routes: list[ModelRoute] = []

    async def complete_json(
        self, prompt: RenderedPrompt, json_schema: Any, route: ModelRoute, **kwargs: Any
    ) -> Any:
        self.routes.append(route)
        usage = ModelUsage(provider="mock", model=route.model, input_tokens=3, output_tokens=2)
        return {"summary": "x", "language": "vi"}, usage, None


def _gateway(models: ModelResolver, adapter: _Seen, pricing: FlatPricing) -> RoutingModelGateway:
    prompts = PromptRegistry()
    prompts.register(make_prompt())
    return RoutingModelGateway(
        residency=run_gate(),
        models=models,
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=InMemoryUsageRecorder(),
        pricing=pricing,
        run_control=OpenRunControl(),
    )


_ASK = ModelRequest(
    task="structured_extraction",
    prompt_id="demo.summarize",
    prompt_version="1.0.0",
    variables={"content": "x"},
    model_profile=SHARED,
)


# ---- the four doors (R1.1, R1.2; MR1) ---------------------------------------


async def _through_the_gateway(models: ModelResolver, run: RunContext) -> list[str]:
    adapter, book = _Seen(), FlatPricing()
    await _gateway(models, adapter, book).generate_structured(_ASK, SummaryOutput, run_context=run)
    return [r.model for r in adapter.routes] + [model for _t, _p, model, _a in book.calls]


async def _through_the_budget(models: ModelResolver, run: RunContext) -> list[str]:
    book = FlatPricing()
    agent: Any = create_agent(
        model=MockChatModel(responses=[AIMessage(content="ok")], mock_reply="ok"),
        tools=[],
        middleware=[RunBudgetMiddleware(RunBudgetLedger(), models, SHARED, book)],
        context_schema=RunContext,
    )
    await agent.ainvoke({"messages": [HumanMessage("x")]}, context=run)
    return [model for _t, _p, model, _a in book.calls]


async def _through_the_meter(models: ModelResolver, run: RunContext) -> list[str]:
    book = FlatPricing()
    meter = LangchainUsageMeter(models=models, recorder=InMemoryUsageRecorder(), pricing=book)
    chat = MockChatModel(responses=[AIMessage(content="ok")], mock_reply="ok")
    async with meter.track(
        run, profile_id=SHARED, task="t", prompt_id="p", prompt_version="1.0.0"
    ) as callbacks:
        await chat.ainvoke([HumanMessage("x")], config=RunnableConfig(callbacks=list(callbacks)))
    return [model for _t, _p, model, _a in book.calls]


async def _through_compaction(models: ModelResolver, run: RunContext) -> list[str]:
    book = FlatPricing()
    summary = MockChatModel(responses=[AIMessage(content="tóm tắt")], mock_reply="tóm tắt")
    compaction = PlatformSummarizationMiddleware(
        summary,
        residency=run_gate(),
        copy=COPY,
        uow_factory=FakeUoWFactory(audit_repo=FakeAuditRepo()),
        clock=FixedClock(NOW),
        ids=SequentialIdGenerator(),
        budget=RunBudgetLedger(),
        pricing=book,
        models=models,
        profile_id=SHARED,
        summary_profile_id=SHARED,
        trigger=("messages", 10),
        keep=("messages", 4),
        run_control=OpenRunControl(),
    )
    agent: Any = create_agent(
        model=MockChatModel(responses=[AIMessage(content="xong")], mock_reply="xong"),
        tools=[],
        middleware=[compaction],
        context_schema=RunContext,
        checkpointer=InMemorySaver(),
    )
    history: list[BaseMessage] = _history(8)
    await agent.ainvoke({"messages": history}, THREAD, context=run)
    return [model for _t, _p, model, _a in book.calls]


DOORS = {
    "gateway": _through_the_gateway,
    "budget": _through_the_budget,
    "meter": _through_the_meter,
    "compaction": _through_compaction,
}


@pytest.mark.parametrize("door", sorted(DOORS))
async def test_every_door_takes_the_companys_own_route(door: str) -> None:
    """R1.1: a door that reads the platform layer instead (drops the run's
    context) prices `platform-*`, and this is red."""
    models = _models()
    priced = await DOORS[door](models, _run(ACME))
    assert priced and all(model.startswith("acme-") for model in priced), priced


async def test_the_four_doors_answer_one_route_for_one_company() -> None:
    """R1.2: one profile, one content hash, one chat route at every door that
    asks for the chat purpose; the gateway's structured route is the same
    profile's."""
    models = _models()
    answers = _spy(models)
    for door in DOORS.values():
        await door(models, _run(ACME))
    assert {(a.profile_id, a.layer, a.content_hash) for a in answers} == {
        (SHARED, "tenant", profile_hash(_profile("acme")))
    }
    chat = {(a.route.provider, a.route.model) for a in answers if a.purpose == "chat"}
    assert chat == {("mock", "acme-chat")}


async def test_another_company_on_the_same_doors_gets_the_platforms() -> None:
    priced = await _through_the_gateway(_models(), _run(OTHER))
    assert priced and all(model.startswith("platform-") for model in priced)


async def test_the_fallbacks_are_the_resolvers_and_the_gateway_tries_only_them() -> None:
    answer = await _models().resolve(_run(ACME), SHARED, "reasoning")
    assert answer.route.model == "acme-reason"
    assert [r.model for r in answer.fallbacks] == ["acme-fallback"]
    assert answer.attempts == (answer.route, *answer.fallbacks)
    # A fallback that is the route's own model is not a second attempt.
    same = _profile("x").model_copy(update={"fallback": route(model="x-reason")})
    registry = ModelProfileRegistry()
    registry.register(same)
    assert (await _models(registry).resolve(_run(), SHARED, "reasoning")).fallbacks == ()


async def test_deep_reasoning_falls_back_to_reasoning_and_chat_needs_a_chat_route() -> None:
    models = _models()
    deep = await models.resolve(_run(), SHARED, "deep_reasoning")
    assert deep.route.model == "acme-reason"
    registry = ModelProfileRegistry()
    registry.register(_profile("p").model_copy(update={"chat": None}))
    with pytest.raises(ConfigError, match="no chat route"):
        await _models(registry).resolve(_run(), SHARED, "chat")


async def test_a_call_naming_no_profile_runs_on_the_deployments_default() -> None:
    answer = await _models().resolve(_run(OTHER), None, "structured_extraction")
    assert (answer.profile_id, answer.layer) == (SHARED, "platform")


# ---- the plan (R2.1, R2.2, R2.6; MR3) ----------------------------------------


@pytest.mark.parametrize(
    "plans",
    [
        pytest.param({PLAN: frozenset({"luna"})}, id="outside-the-plan"),
        pytest.param({}, id="a-plan-with-no-rows"),
    ],
)
async def test_a_platform_profile_the_plan_does_not_list_is_refused_and_nothing_is_sent(
    plans: dict[str, frozenset[str]],
) -> None:
    adapter = _Seen()
    gateway = _gateway(_models(plans=StaticPlanModelProfiles(plans)), adapter, FlatPricing())
    with pytest.raises(EntitlementDeniedError) as refused:
        await gateway.generate_structured(_ASK, SummaryOutput, run_context=_run(OTHER))
    assert refused.value.details == {
        "reason_code": "model_profile_unavailable",
        "reason": "plan",
        "profile_id": SHARED,
    }
    assert adapter.routes == []


async def test_the_background_plan_reaches_no_model() -> None:
    """`background` is a context's plan, not a row of `platform.plans`."""
    with pytest.raises(EntitlementDeniedError):
        await _models().resolve(_run(OTHER, plan="background"), SHARED, "chat")


async def test_the_companys_own_layer_is_not_filtered_by_the_plan() -> None:
    """ADR-0118 decision 1: the plan lists platform profiles only."""
    models = _models(plans=StaticPlanModelProfiles({}))
    assert (await models.resolve(_run(ACME), SHARED, "chat")).layer == "tenant"


class _Unreadable:
    async def allowed(self, plan_id: str) -> frozenset[str]:
        raise RuntimeError("the catalogue is down")


async def test_a_catalogue_that_cannot_be_read_refuses_and_is_never_every_profile() -> None:
    """R2.6: the read error reaches the caller; the model is not called."""
    adapter = _Seen()
    gateway = _gateway(_models(plans=_Unreadable()), adapter, FlatPricing())
    with pytest.raises(RuntimeError, match="catalogue is down"):
        await gateway.generate_structured(_ASK, SummaryOutput, run_context=_run(OTHER))
    assert adapter.routes == []


async def test_the_budget_door_refuses_a_profile_outside_the_plan_before_the_model() -> None:
    model = MockChatModel(responses=[AIMessage(content="ok")], mock_reply="ok")
    agent: Any = create_agent(
        model=model,
        tools=[],
        middleware=[
            RunBudgetMiddleware(
                RunBudgetLedger(),
                _models(plans=StaticPlanModelProfiles({})),
                SHARED,
                FlatPricing(),
            )
        ],
        context_schema=RunContext,
    )
    with pytest.raises(EntitlementDeniedError):
        await agent.ainvoke({"messages": [HumanMessage("x")]}, context=_run(OTHER))
    assert model.calls == []


# ---- no run, no answer (R1.6; MR6) ---------------------------------------------


async def test_there_is_no_answer_without_a_run() -> None:
    with pytest.raises(PermissionDeniedError) as refused:
        await _models().resolve(None, SHARED, "chat")  # type: ignore[arg-type]
    assert refused.value.details["reason_code"] == "run_context_required"


def test_the_platform_layer_unfiltered_is_a_separate_door() -> None:
    assert _models().platform_profile(SHARED).chat.model == "platform-chat"  # type: ignore[union-attr]


def test_a_default_nobody_registered_fails_at_startup() -> None:
    with pytest.raises(Exception, match="not registered"):
        ModelResolver(ModelProfileRegistry(), StaticPlanModelProfiles({}), "nowhere")


# ---- a Studio run reads what it pinned (R1.4, R1.5; MR4) ------------------------

MANIFEST = "sha256:" + "c" * 64


async def _pinned(models: ModelResolver, *declared: str, tenant: uuid.UUID = ACME) -> AnyManifest:
    return AnyManifest(
        {"durability": "sync", **await models.pin(tenant, PLAN, frozenset(declared))}
    )


async def test_pin_holds_the_profiles_by_value_and_no_secret() -> None:
    models = _models()
    engine = await models.pin(OTHER, PLAN, frozenset())
    assert engine["default_model_profile"] == SHARED
    entry = engine["model_routes"][SHARED]
    assert entry == pin_entry(_profile("platform"), "platform")
    assert set(entry["routes"]) == {"structured_extraction", "reasoning", "chat", "fallback"}
    assert "secret" not in repr(engine)
    assert not any("secret" in name for name in ResolvedRoute.__dataclass_fields__)
    assert not any("secret" in name for name in ModelRoute.model_fields)


async def test_pin_refuses_a_declared_profile_and_leaves_out_a_default_the_plan_does_not_list() -> (
    None
):
    narrow = _models(plans=StaticPlanModelProfiles({PLAN: frozenset()}))
    assert await narrow.pin(OTHER, PLAN, frozenset()) == {
        "model_routes": {},
        "default_model_profile": None,
    }
    with pytest.raises(EntitlementDeniedError):
        await narrow.pin(OTHER, PLAN, frozenset({SHARED}))
    # The company's own profile is pinned whatever the plan lists.
    own = await narrow.pin(ACME, PLAN, frozenset({SHARED}))
    assert own["model_routes"][SHARED]["layer"] == "tenant"


async def test_a_studio_run_reads_its_pinned_route_and_not_the_registry() -> None:
    models = _models()
    engines = await _pinned(models)
    adapter = _Seen()
    # A later deployment's resolver: another registry, another default.
    later = ModelResolver(
        _registry(), StaticPlanModelProfiles({PLAN: frozenset({SHARED})}), SHARED, engines
    )
    run = _run(ACME, manifest=MANIFEST)
    await _gateway(later, adapter, FlatPricing()).generate_structured(
        _ASK.model_copy(update={"model_profile": None}), SummaryOutput, run_context=run
    )
    assert [r.model for r in adapter.routes] == ["acme-extract"]


async def test_a_pinned_profile_whose_content_changed_is_refused_before_a_send() -> None:
    """R1.5: the alias was re-declared `foreign` after admission. The run does
    not follow the new declaration and does not send under the old one."""
    engines = await _pinned(_models())
    changed = ModelProfileRegistry()
    acme = _profile("acme")
    changed.register(_profile("platform"))
    changed.register(
        acme.model_copy(
            update={"chat": acme.chat.model_copy(update={"data_location": "foreign"})}  # type: ignore[union-attr]
        ),
        tenant_id=ACME,
    )
    adapter = _Seen()
    gateway = _gateway(_models(changed, pinned=engines), adapter, FlatPricing())
    with pytest.raises(EntitlementDeniedError) as refused:
        await gateway.generate_structured(
            _ASK, SummaryOutput, run_context=_run(ACME, manifest=MANIFEST)
        )
    assert refused.value.details["reason"] == "pinned_profile_changed"
    assert adapter.routes == []


async def test_a_pinned_platform_profile_the_plan_dropped_is_refused() -> None:
    engines = await _pinned(_models(), tenant=OTHER)
    dropped = _models(plans=StaticPlanModelProfiles({PLAN: frozenset()}), pinned=engines)
    with pytest.raises(EntitlementDeniedError) as refused:
        await dropped.resolve(_run(OTHER, manifest=MANIFEST), SHARED, "chat")
    assert refused.value.details["reason"] == "plan"


@pytest.mark.parametrize(
    "engine",
    [
        pytest.param({"durability": "sync"}, id="a-manifest-from-before-model-routes"),
        pytest.param(
            {"durability": "sync", "model_routes": {}, "default_model_profile": None},
            id="a-default-that-was-not-pinned",
        ),
    ],
)
async def test_an_unpinned_profile_is_key_not_pinned(engine: dict[str, Any]) -> None:
    models = _models(pinned=AnyManifest(engine))
    with pytest.raises(ConfigError) as refused:
        await models.resolve(_run(ACME, manifest=MANIFEST), None, "chat")
    assert refused.value.details["reason"] == "key_not_pinned"


async def test_a_profile_the_run_did_not_pin_is_key_not_pinned() -> None:
    models = _models(pinned=await _pinned(_models()))
    with pytest.raises(ConfigError) as refused:
        await models.resolve(_run(ACME, manifest=MANIFEST), "luna", "chat")
    assert refused.value.details == {
        "reason": "key_not_pinned",
        "kind": "model_profile",
        "key": "luna",
    }


async def test_a_studio_run_without_a_manifest_reader_is_refused() -> None:
    with pytest.raises(ConfigError) as refused:
        await _models().resolve(_run(ACME, manifest=MANIFEST), None, "chat")
    assert refused.value.details["reason"] == "manifest_not_found"


async def test_a_manifest_is_read_once_and_the_cache_is_bounded() -> None:
    reads: list[str] = []

    class Counting:
        async def engine(self, tenant_id: uuid.UUID, run_manifest_hash: str) -> Any:
            reads.append(run_manifest_hash)
            return {"durability": "sync", **await _models().pin(tenant_id, PLAN, frozenset())}

    models = _models(pinned=Counting())
    for _ in range(3):
        await models.resolve(_run(ACME, manifest=MANIFEST), None, "chat")
    assert reads == [MANIFEST]
    for n in range(300):
        await models.resolve(_run(ACME, manifest="sha256:" + f"{n:064x}"), None, "chat")
    assert len(models._engines) == 256


# ---- one reader of the registry (MR1, MR6): a scan of the production source ----

_SOURCES = ("apps", "packages/python", "scripts")
# Where the platform layer may be read unfiltered: composition roots and scripts
# (ticket 02 step 1), and compaction's build-time check of its summary route.
PLATFORM_READERS = frozenset(
    {
        "apps/api/src/dw_api/bootstrap/knowledge.py",
        "apps/worker/src/dw_worker/composition.py",
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/chat_model.py",
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/context_compaction.py",
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/model/resolver.py",
        "scripts/check_model_gateway.py",
        "scripts/eval_wf_ai.py",
    }
)
REGISTRY_READERS = frozenset(
    {"packages/python/dw_agent_runtime/src/dw_agent_runtime/model/resolver.py"}
)


def _production_files() -> list[Path]:
    files = []
    for top in _SOURCES:
        for path in (REPO_ROOT / top).rglob("*.py"):
            parts = set(path.relative_to(REPO_ROOT).parts)
            if parts & {"tests", ".venv", "__pycache__", "testing", "node_modules"}:
                continue
            files.append(path)
    return files


def _registry_reads(tree: ast.AST) -> list[str]:
    """Calls that read a model profile around the resolver: `X.resolve(...)` or
    `X.layer(...)` on a receiver named for profiles, and `chat_route(...)`."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "chat_route":
            found.append("chat_route")
        if isinstance(func, ast.Attribute):
            receiver = ast.unparse(func.value).lower()
            if func.attr in ("resolve", "layer") and "profile" in receiver:
                found.append(f"{ast.unparse(func.value)}.{func.attr}")
            if func.attr == "chat_route":
                found.append("chat_route")
    return found


def _platform_reads(tree: ast.AST) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "platform_profile"
    )


def _offenders() -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for path in _production_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reads = [] if relative in REGISTRY_READERS else _registry_reads(tree)
        if relative not in PLATFORM_READERS and _platform_reads(tree):
            reads.append("platform_profile")
        if reads:
            offenders[relative] = reads
    return offenders


def test_only_the_resolver_reads_the_registry_and_only_roots_read_the_platform_layer() -> None:
    """MR1, MR6: a door that resolves around `ModelResolver.resolve`, or reads
    the unfiltered platform layer, is named here. Blind to a registry held
    under a name with no `profile` in it; the doors take a `ModelResolver`, and
    no production module but the composition roots builds a registry."""
    assert _offenders() == {}


def test_the_scan_sees_each_shape_it_forbids() -> None:
    """The scan above can fail: each forbidden shape, as source, is found."""
    for source in (
        "profiles.resolve('x', tenant_id=t)",
        "self._profiles.layer('x', tenant_id=None)",
        "chat_route(profiles, 'x')",
        "adapters.chat_model.chat_route(p, 'x')",
    ):
        assert _registry_reads(ast.parse(source)), source
    assert _platform_reads(ast.parse("models.platform_profile('x')")) == 1
    assert not _registry_reads(ast.parse("models.resolve(run, 'x', 'chat')"))
