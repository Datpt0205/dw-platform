"""The last door before a span leaves the process: identifiers only.

`safe_attributes` cleans what our code hands the telemetry port, but the port is
not the only writer of a span. The OTel SDK attaches an exception event with
`exception.message` and `exception.stacktrace` when a span ends in an error, and
puts the message in the status description, below anything a test on
`RecordingTelemetry` can see (`failure-modes.md` #0). An exception built from a
value — a validation error quoting the phone number it refused — leaves that way.

So every exporter is wrapped in `IdentifierOnlySpanProcessor`, which rebuilds the
span keeping only the keys in `dw_observability.semconv.ALLOWED_KEYS`, on the
span, its events and its links, and drops the status description. It is an
allowlist: a key nobody listed is dropped, including content keys a later
semconv commit adds (spec R1.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry.context import Context
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import Link, Status

from dw_observability.semconv import ALLOWED_KEYS

__all__ = ["IdentifierOnlySpanProcessor", "allowed_attributes"]


def allowed_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (attributes or {}).items() if key in ALLOWED_KEYS}


class IdentifierOnlySpanProcessor(SpanProcessor):
    """Hands `inner` (the exporting processor) a copy of each span with only allowed keys."""

    def __init__(self, inner: SpanProcessor) -> None:
        self._inner = inner

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._inner.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._inner.on_end(
            ReadableSpan(
                name=span.name,
                context=span.context,
                parent=span.parent,
                resource=span.resource,
                attributes=allowed_attributes(span.attributes),
                events=[
                    Event(event.name, allowed_attributes(event.attributes), event.timestamp)
                    for event in span.events
                ],
                links=[
                    Link(link.context, allowed_attributes(link.attributes)) for link in span.links
                ],
                kind=span.kind,
                # The description is the exception's text; the code is enough
                # to say the span failed, and `exception.type` says how.
                status=Status(span.status.status_code),
                start_time=span.start_time,
                end_time=span.end_time,
                instrumentation_scope=span.instrumentation_scope,
            )
        )

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)
