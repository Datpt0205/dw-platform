"""Spans leave the process carrying identifiers only, on every exporter (spec R1.4, TA9).

These go through `configure_tracing` itself, with the OTLP exporter replaced by
an in-memory one, rather than through a provider built by hand: what is under
test is that the path every deployment takes (a collector, or Langfuse, which
is the same OTLP path) has the filter on it.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from dw_observability.metrics import DW_APPROVAL_WAIT_SECONDS, DW_RUN_DURATION_SECONDS
from dw_observability.otel import OtelTelemetry, build_telemetry, histogram_views
from dw_observability.semconv import ALLOWED_KEYS

pytestmark = pytest.mark.unit

PHONE = "0912 345 678"


def _pipeline(
    monkeypatch: pytest.MonkeyPatch, **settings: Any
) -> tuple[OtelTelemetry, InMemorySpanExporter, TracerProvider]:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
        lambda **_: exporter,
    )
    installed: list[TracerProvider] = []
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    built = build_telemetry(service_name="test-span-filter", **settings)
    assert isinstance(built, OtelTelemetry)
    (provider,) = installed
    # The tracer of the provider the pipeline installed, not the global one.
    return OtelTelemetry(tracer=provider.get_tracer("t"), meter=built.meter), exporter, provider


@pytest.mark.parametrize(
    "settings",
    [
        {"otel_endpoint": "http://collector:4318/v1/traces"},
        {
            "langfuse_enabled": True,
            "langfuse_host": "https://langfuse.example",
            "langfuse_public_key": "pk",
            "langfuse_secret_key": "sk",
        },
    ],
    ids=["otlp", "langfuse"],
)
def test_an_exported_span_carries_only_allowed_keys(
    monkeypatch: pytest.MonkeyPatch, settings: dict[str, Any]
) -> None:
    telemetry, exporter, provider = _pipeline(monkeypatch, **settings)

    with pytest.raises(ValueError):
        with telemetry.span(
            "chat gpt-x",
            {
                "dw.run_id": "r1",
                "gen_ai.request.model": "gpt-x",
                "user.id": "u-42",
                "gen_ai.input.messages": f"[{PHONE}]",
                # Added by a later semconv commit and listed nowhere: an
                # allowlist drops it, a list of banned keys would not.
                "gen_ai.system_instructions": "Bạn là trợ lý",
                "gen_ai.future_content": "x",
            },
        ):
            raise ValueError(f"refused {PHONE}")
    provider.force_flush()

    (span,) = exporter.get_finished_spans()
    assert set(span.attributes or {}) == {"dw.run_id", "gen_ai.request.model"}
    # Two: `OtelTelemetry` records the exception, and so does the SDK's own
    # `start_as_current_span`. Both arrive with the type and nothing else.
    assert span.events
    for event in span.events:
        assert event.name == "exception"
        assert set(event.attributes or {}) == {"exception.type"}
    assert not span.status.is_ok
    assert span.status.description is None
    assert "345" not in repr(span.to_json())


def test_every_kept_key_is_allowed() -> None:
    """The filter keeps a key only from `ALLOWED_KEYS`; a span of only those keeps all."""
    from dw_observability.span_filter import allowed_attributes

    sample = dict.fromkeys(ALLOWED_KEYS, "v")
    assert allowed_attributes({**sample, "exception.message": "x"}) == sample


def test_histograms_record_with_the_buckets_the_metric_owns() -> None:
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader], views=histogram_views()).get_meter("t")
    telemetry = OtelTelemetry(tracer=TracerProvider().get_tracer("t"), meter=meter)

    telemetry.record_histogram(DW_RUN_DURATION_SECONDS, 3.0, {"worker": "w", "status": "ok"})
    telemetry.record_histogram(
        DW_APPROVAL_WAIT_SECONDS, 120.0, {"worker": "w", "approval_type": "a"}
    )

    data = reader.get_metrics_data()
    assert data is not None
    bounds = {
        metric.name: tuple(metric.data.data_points[0].explicit_bounds)  # type: ignore[union-attr]
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    assert bounds[DW_RUN_DURATION_SECONDS] == (0.5, 1, 2, 5, 10, 30, 60, 120, 300, 900, 1800, 3600)
    assert bounds[DW_APPROVAL_WAIT_SECONDS] == (
        60,
        300,
        900,
        3600,
        14400,
        43200,
        86400,
        259200,
        604800,
    )
