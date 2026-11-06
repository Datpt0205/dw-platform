"""Unit: a one-call run takes its lease before the call and gives it back
after, whatever the outcome; the gateway asks the run's lease before every
attempt, after the residency gate (usage-and-limits R5.2, R5.5, R6.5).

Against the real `RoutingModelGateway` with the open limits port that keeps
every question, so a test sees what was asked, in what order, and what was not.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, ModelUsage
from dw_agent_runtime.model.profiles import ModelProfileRegistry, ModelRoute
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry, RenderedPrompt
from dw_agent_runtime.model.routing import RoutingModelGateway
from dw_agent_runtime.model.single_call import SingleCallModelGateway
from dw_agent_runtime.ports import ModelOutputInvalidError, ModelRequest
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.models import resolver as model_resolver
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.limits import LimitExceededError
from dw_platform.testing.residency import run_gate

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


class Answer(BaseModel):
    answer: str


@dataclass
class _Spy:
    """The mock adapter, keeping the `max_output_tokens` of every call."""

    inner: MockModelAdapter
    asked: list[int | None] = field(default_factory=list)

    @property
    def provider_name(self) -> str:
        return self.inner.provider_name

    async def complete_json(
        self,
        prompt: RenderedPrompt,
        json_schema: dict[str, object],
        route: ModelRoute,
        *,
        max_output_tokens: int | None,
    ) -> tuple[dict[str, object], ModelUsage, str | None]:
        self.asked.append(max_output_tokens)
        return await self.inner.complete_json(
            prompt, json_schema, route, max_output_tokens=max_output_tokens
        )


def _run_context(**overrides: object) -> RunContext:
    fields: dict[str, object] = {
        "run_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "actor_id": uuid.uuid4(),
        "worker_id": "demo.one_call",
        "worker_version": "1.0.0",
        "channel": "web",
        "plan_id": "professional",
        "roles": frozenset({"member"}),
        "scopes": frozenset(),
        "trace_id": "trace-1",
    }
    fields.update(overrides)
    return RunContext.model_validate(fields)


def _answering(answer: dict[str, object]) -> _Spy:
    adapter = MockModelAdapter()
    adapter.register_builder("demo.answer", "1.0.0", lambda prompt: answer)
    return _Spy(adapter)


def _gateway(
    adapter: _Spy, limits: OpenLimits
) -> tuple[RoutingModelGateway, InMemoryUsageRecorder]:
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(
        PromptArtifact.model_validate(
            {
                "schema_version": "1.0",
                "prompt_id": "demo.answer",
                "version": "1.0.0",
                "system": "Trả lời ngắn.",
                "template": "Câu hỏi: {question}",
                "variables": frozenset({"question"}),
            }
        )
    )
    recorder = InMemoryUsageRecorder()
    gateway = RoutingModelGateway(
        residency=run_gate(),
        models=model_resolver(profiles, "balanced"),
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=recorder,
        pricing=FlatPricing(),
        limits=limits,
        run_control=OpenRunControl(),
    )
    return gateway, recorder


_REQUEST = ModelRequest(
    task="structured_extraction",
    prompt_id="demo.answer",
    prompt_version="1.0.0",
    variables={"question": "x"},
)


async def test_a_one_call_run_takes_a_lease_that_counts_no_run_and_gives_it_back() -> None:
    """R6.2 (usage-and-limits/04): a call outside any run takes a
    `builder_assist` operation lease, never a run's, and the call spends it."""
    limits = OpenLimits()
    gateway, recorder = _gateway(_answering({"answer": "ok"}), limits)
    single = SingleCallModelGateway(inner=gateway, limits=limits)
    context = _run_context()

    result = await single.generate_structured(_REQUEST, Answer, run_context=context)

    assert result.answer == "ok"
    assert limits.admitted == []
    assert limits.operations == [(context.run_id, "builder_assist")]
    assert limits.released == [(context.run_id, "completed")]
    ((_, usage),) = recorder.records
    assert usage.permit is not None and usage.permit.purpose == "builder_assist"


async def test_a_one_call_run_gives_its_lease_back_when_the_call_fails() -> None:
    """Every attempt spent before the schema refused it; the lease still goes,
    or a failing prompt would hold money until the reaper (failure-modes #6)."""
    limits = OpenLimits()
    gateway, _ = _gateway(_answering({"wrong": True}), limits)
    single = SingleCallModelGateway(inner=gateway, limits=limits)
    context = _run_context()

    with pytest.raises(ModelOutputInvalidError):
        await single.generate_structured(_REQUEST, Answer, run_context=context)

    assert limits.released == [(context.run_id, "failed")]


async def test_a_one_call_run_over_its_limits_never_reaches_the_model() -> None:
    adapter = _answering({"answer": "ok"})
    limits = OpenLimits(
        refuse=LimitExceededError("spent", metric="cost_usd", scope_type="tenant", window="day")
    )
    gateway, recorder = _gateway(adapter, limits)
    single = SingleCallModelGateway(inner=gateway, limits=limits)

    with pytest.raises(LimitExceededError):
        await single.generate_structured(_REQUEST, Answer, run_context=_run_context())

    assert adapter.asked == []
    assert recorder.records == []
    assert limits.released == []


async def test_every_attempt_is_sent_with_the_permits_max_tokens_and_settled_by_it() -> None:
    """R5.2 (UL3): the call carries no more output than the lease permits, and
    its usage carries the permit, which is what settles it into the lease."""
    adapter = _answering({"answer": "ok"})
    limits = OpenLimits(max_output_tokens=100)
    gateway, recorder = _gateway(adapter, limits)

    await gateway.generate_structured(_REQUEST, Answer, run_context=_run_context())

    assert adapter.asked == [100]
    ((_, usage),) = recorder.records
    assert usage.permit == limits.permits[0]


async def test_a_refused_call_falls_through_to_no_cheaper_route() -> None:
    """R5.5 (UL13): the lease refused, nothing was sent, no fallback was tried."""
    adapter = _answering({"answer": "ok"})
    limits = OpenLimits(
        refuse_calls=LimitExceededError("ceiling", metric="cost_usd", scope_type="run")
    )
    gateway, recorder = _gateway(adapter, limits)

    with pytest.raises(LimitExceededError):
        await gateway.generate_structured(_REQUEST, Answer, run_context=_run_context())

    assert adapter.asked == []
    assert len(limits.calls) == 1
    assert recorder.records == []
