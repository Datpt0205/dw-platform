"""TelemetryUsageRecorder emits §21.3 token metrics with safe labels only, under the
pinned GenAI names."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.adapters.telemetry_usage import TelemetryUsageRecorder
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import ModelUsage, RoutingModelGateway
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry
from dw_agent_runtime.ports import ModelRequest
from dw_observability.metrics import DW_MODEL_TOKENS_TOTAL
from dw_observability.semconv import contract_violations, load_snapshot, snapshot_path
from dw_observability.telemetry import RecordingTelemetry

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


def _run_context() -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="demo",
        worker_version="1.0.0",
        channel="web",
        plan_id="starter",
        roles=frozenset({"member"}),
        scopes=frozenset(),
        trace_id="test-trace",
    )


async def test_records_token_metrics_and_model_span() -> None:
    telemetry = RecordingTelemetry()
    recorder = TelemetryUsageRecorder(telemetry)
    request = ModelRequest(
        prompt_id="demo.extract",
        prompt_version="1.0.0",
        model_profile="balanced",
        task="structured_extraction",
        variables={"rfq": "salary data and other secrets"},
    )
    usage = ModelUsage(
        provider="mock",
        model="mock-structured",
        input_tokens=120,
        output_tokens=45,
        response_model="mock-structured-2026-10",
    )

    await recorder.record(_run_context(), request, usage)

    directions = {
        (m[2]["direction"], m[1]) for m in telemetry.metrics if m[0] == DW_MODEL_TOKENS_TOTAL
    }
    assert directions == {("input", 120), ("output", 45)}
    (span_name, attributes) = telemetry.spans[0]
    assert span_name == "chat mock-structured"
    # `gen_ai.system` left the conventions; the provider is `gen_ai.provider.name`,
    # and the response model is what answered, not a copy of the request.
    assert "gen_ai.system" not in attributes
    assert attributes["gen_ai.provider.name"] == "mock"
    assert attributes["gen_ai.request.model"] == "mock-structured"
    assert attributes["gen_ai.response.model"] == "mock-structured-2026-10"
    assert attributes["dw.prompt_id"] == "demo.extract"
    # prompt content must never appear in telemetry attributes
    assert all("salary" not in str(v) for v in attributes.values())


class _Summary(BaseModel):
    summary: str


async def test_a_gateway_call_emits_only_pinned_names_and_no_input_value() -> None:
    """The gateway end to end, through the recorder the processes wire: every
    span, attribute and metric name is in the pinned snapshot (spec R1.1), and
    a phone number in the prompt's input reaches none of them (spec R1.2)."""
    telemetry = RecordingTelemetry()
    adapter = MockModelAdapter()
    adapter.register_builder("demo.summarize", "1.0.0", lambda prompt: {"summary": "ok"})
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.register(
        PromptArtifact.model_validate(
            {
                "schema_version": "1.0",
                "prompt_id": "demo.summarize",
                "version": "1.0.0",
                "system": "Tóm tắt.",
                "template": "Tóm tắt: {content}",
                "variables": frozenset({"content"}),
            }
        )
    )
    gateway = RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=TelemetryUsageRecorder(telemetry),
        default_profile="balanced",
    )

    await gateway.generate_structured(
        ModelRequest(
            task="structured_extraction",
            prompt_id="demo.summarize",
            prompt_version="1.0.0",
            variables={"content": "khách gọi lại số 0912 345 678"},
        ),
        _Summary,
        run_context=_run_context(),
    )

    assert [name.split(" ", 1)[0] for name, _ in telemetry.spans] == ["chat"]
    assert contract_violations(load_snapshot(snapshot_path(REPO_ROOT)), telemetry) == []
    assert "345" not in repr(telemetry.spans) + repr(telemetry.metrics)
