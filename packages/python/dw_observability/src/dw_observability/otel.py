"""OpenTelemetry implementation of ``TelemetryPort``.

``configure_tracing`` builds a real SDK pipeline when an OTLP endpoint is
configured (plain collector or Langfuse — see ``dw_observability.langfuse``).
Without an endpoint the API-level no-op tracer applies, so instrumented code
never pays for unconfigured telemetry.

Metrics are a separate decision from tracing, on purpose. Before Ops
hardening Phase 5, ``metrics.get_meter(...)`` was called with no
``MeterProvider`` ever installed — every ``add_metric`` call in this
codebase (``dw_run_total``, ``dw_tool_call_total``, ...) was silently a
no-op against OTel's proxy meter, Langfuse configured or not. Measured, not
assumed: ``metrics.get_meter_provider()`` returns a ``_ProxyMeterProvider``
until something calls ``set_meter_provider``, and nothing here ever did.
Metrics now always get a real `MeterProvider` backed by
``PrometheusMetricReader`` — Prometheus is pull-based, so unlike the OTLP
trace exporter above it needs no destination configured to be worth turning
on, only something to scrape the process's own `/metrics`.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace

# `create_gauge`'s return type is exported as `_Gauge` in this pinned SDK
# version (the synchronous Gauge instrument was still stabilising its public
# name) — this is that same class, not a private implementation detail.
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.metrics import _Gauge as Gauge
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.trace import Status, StatusCode, Tracer

from dw_observability.metrics import HISTOGRAM_BUCKETS
from dw_observability.span_filter import IdentifierOnlySpanProcessor
from dw_observability.telemetry import TelemetryPort, safe_attributes

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter

_meter_provider_lock = threading.Lock()
_meter_provider_installed = False


def build_telemetry(
    *,
    service_name: str,
    langfuse_enabled: bool = False,
    langfuse_host: str | None = None,
    langfuse_public_key: str | None = None,
    langfuse_secret_key: str | None = None,
    otel_endpoint: str | None = None,
) -> TelemetryPort:
    """Turn Langfuse/OTLP settings into a ``TelemetryPort`` — one builder every app
    shares, so tracing is wired the same way in api, chat and worker.

    Langfuse is just an OTLP endpoint (§21.4) for TRACES. With no endpoint
    (neither Langfuse nor a plain collector), spans are a no-op — OTel's own
    default tracer, not ``NullTelemetry``: this always returns a real
    ``OtelTelemetry`` now, because metrics are wired regardless of whether
    tracing is.
    """
    endpoint = otel_endpoint
    headers: dict[str, str] | None = None
    if langfuse_enabled:
        from dw_observability.langfuse import langfuse_otlp_config

        if not (langfuse_host and langfuse_public_key and langfuse_secret_key):
            raise ValueError("Langfuse enabled but host/public_key/secret_key missing")
        endpoint, headers = langfuse_otlp_config(
            langfuse_host, langfuse_public_key, langfuse_secret_key
        )
    tracer, meter = configure_tracing(service_name, otlp_endpoint=endpoint, otlp_headers=headers)
    return OtelTelemetry(tracer=tracer, meter=meter)


def current_trace_id() -> str | None:
    """The running span's trace id as 32 lowercase hex digits, or None.

    None, not the all-zero id, when no span is recording: unconfigured tracing
    still hands out OTel's invalid span, and an id that names no trace would
    send whoever pastes it into a trace search looking for nothing.
    """
    context = trace.get_current_span().get_span_context()
    return trace.format_trace_id(context.trace_id) if context.is_valid else None


def configure_tracing(
    service_name: str,
    *,
    otlp_endpoint: str | None = None,
    otlp_headers: Mapping[str, str] | None = None,
) -> tuple[Tracer, Meter]:
    """Install a tracer (only if an OTLP endpoint is set) and a meter
    (always). Exported spans go to `otlp_endpoint`; exported metrics go to
    this process's own `/metrics` — a Prometheus scraper is the composition
    root's job to expose (`apps/api`'s route, `apps/worker`'s metrics
    server), not this function's.

    Langfuse and a plain collector are both this one OTLP path, so the
    identifier filter that wraps it covers both (spec R1.4).
    """
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider = build_tracer_provider(
            service_name,
            OTLPSpanExporter(
                endpoint=otlp_endpoint,
                headers=dict(otlp_headers) if otlp_headers else None,
            ),
        )
        trace.set_tracer_provider(provider)
    _ensure_meter_provider(service_name)
    return trace.get_tracer(service_name), metrics.get_meter(service_name)


def build_tracer_provider(service_name: str, *exporters: SpanExporter) -> TracerProvider:
    """A provider exporting to each of `exporters`, every one behind the identifier filter.

    The one place an exporter is attached: an exporter added beside this
    function rather than through it would ship spans unfiltered.
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    for exporter in exporters:
        provider.add_span_processor(IdentifierOnlySpanProcessor(BatchSpanProcessor(exporter)))
    return provider


def _ensure_meter_provider(service_name: str) -> None:
    """Install the process-wide Prometheus-backed ``MeterProvider`` exactly
    once. ``metrics.set_meter_provider`` is itself idempotent-safe (a second
    call is refused with a log warning, not an exception) but guarded here
    too so a second call in the same process — a second app/worker
    composition root import path, a test — never even attempts it or logs
    that warning.
    """
    global _meter_provider_installed
    with _meter_provider_lock:
        if _meter_provider_installed:
            return
        from opentelemetry.exporter.prometheus import PrometheusMetricReader
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource

        reader = PrometheusMetricReader()
        provider = MeterProvider(
            resource=Resource.create({"service.name": service_name}),
            metric_readers=[reader],
            views=histogram_views(),
        )
        metrics.set_meter_provider(provider)
        _meter_provider_installed = True


def histogram_views() -> list[View]:
    """One View per histogram, carrying the buckets `HISTOGRAM_BUCKETS` owns."""
    return [
        View(
            instrument_name=name,
            aggregation=ExplicitBucketHistogramAggregation(boundaries=boundaries),
        )
        for name, boundaries in HISTOGRAM_BUCKETS.items()
    ]


@dataclass
class OtelTelemetry:
    """``TelemetryPort`` on an OpenTelemetry tracer + meter."""

    tracer: Tracer
    meter: Meter
    _counters: dict[str, Counter] = field(default_factory=dict)
    _gauges: dict[str, Gauge] = field(default_factory=dict)
    _histograms: dict[str, Histogram] = field(default_factory=dict)

    @contextmanager
    def _span(self, name: str, attributes: Mapping[str, object]) -> Iterator[None]:
        with self.tracer.start_as_current_span(name) as span:
            for key, value in safe_attributes(attributes).items():
                span.set_attribute(key, value)
            try:
                yield
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                raise

    def span(self, name: str, attributes: Mapping[str, object]) -> AbstractContextManager[None]:
        return self._span(name, attributes)

    def add_metric(self, name: str, value: int | float, attributes: Mapping[str, object]) -> None:
        counter = self._counters.get(name)
        if counter is None:
            counter = self.meter.create_counter(name)
            self._counters[name] = counter
        counter.add(value, safe_attributes(attributes))

    def set_gauge(self, name: str, value: int | float, attributes: Mapping[str, object]) -> None:
        gauge = self._gauges.get(name)
        if gauge is None:
            gauge = self.meter.create_gauge(name)
            self._gauges[name] = gauge
        gauge.set(value, safe_attributes(attributes))

    def record_histogram(
        self, name: str, value: int | float, attributes: Mapping[str, object]
    ) -> None:
        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = self.meter.create_histogram(name, unit="s")
            self._histograms[name] = histogram
        histogram.record(value, safe_attributes(attributes))
