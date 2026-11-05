"""The one owner of every span name, attribute key and metric name we emit.

OpenTelemetry's GenAI conventions live in their own repository and are still
`development`, so names move between commits. A name read off a moving branch
is a contract nobody pinned: the day upstream renames `gen_ai.system` (it did,
to `gen_ai.provider.name`), every dashboard built on the old name goes quiet
without an error. So the conventions are pinned to one commit,
`GENAI_SEMCONV_COMMIT`, and `scripts/genai_semconv_snapshot.py` turns that
commit's YAML into `contracts/telemetry/genai-semconv@<sha12>.json`. The
contract test holds what the code emits to that snapshot (ADR-0122 decision 1).

The snapshot is generated from upstream's YAML, never from this module: a name
this module claims is upstream's and upstream does not have fails the test even
after the snapshot is regenerated. What this module adds to the snapshot is only
what is ours by prefix — `dw.*` span names and attribute keys, `dw_*` metrics —
and the metric label keys, which are the operator's contract, not upstream's.

`ALLOWED_KEYS` is the identifier allowlist. The span processor, the JSON log
formatter and the contract test read this one set, so an identifier is allowed
in one place or nowhere (spec R1.4, R1.5). It is an allowlist on purpose: a
content key upstream adds in a later commit (`gen_ai.system_instructions` was
one) is dropped because nobody listed it, not kept because nobody banned it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dw_observability.metrics import ALL_METRICS
from dw_observability.telemetry import RecordingTelemetry

__all__ = [
    "ALLOWED_KEYS",
    "DW_ATTRIBUTES",
    "DW_EGRESS_REQUEST",
    "DW_KNOWLEDGE_RERANK",
    "DW_RESIDENCY_CHECK",
    "DW_SPAN_NAMES",
    "GENAI_ATTRIBUTES",
    "GENAI_OPERATIONS",
    "GENAI_SEMCONV_COMMIT",
    "GENAI_SEMCONV_REPOSITORY",
    "LOG_FIELDS",
    "METRIC_LABELS",
    "OP_CHAT",
    "OP_EXECUTE_TOOL",
    "OP_INVOKE_WORKFLOW",
    "OTEL_CORE_ATTRIBUTES",
    "chat_span_name",
    "contract_violations",
    "dw_names",
    "execute_tool_span_name",
    "invoke_workflow_span_name",
    "load_snapshot",
    "snapshot_path",
    "span_operation",
]

GENAI_SEMCONV_REPOSITORY: Final = "open-telemetry/semantic-conventions-genai"
# `main` on 2026-10-27; upstream publishes no tags. Moving it is a change to
# this line plus a regenerated snapshot, reviewed together.
GENAI_SEMCONV_COMMIT: Final = "e19717d65f890955777b044bca2a3cd71ae8b498"

# ------------------------------------------------------------------ spans --
# A GenAI span is named `{gen_ai.operation.name} {target}`; the operation is
# the part upstream defines. These are the operations we claim are upstream's.
OP_CHAT: Final = "chat"
OP_EXECUTE_TOOL: Final = "execute_tool"
OP_INVOKE_WORKFLOW: Final = "invoke_workflow"
GENAI_OPERATIONS: Final = frozenset({OP_CHAT, OP_EXECUTE_TOOL, OP_INVOKE_WORKFLOW})

# Spans that are ours alone. A name here must start with `dw.`.
DW_KNOWLEDGE_RERANK: Final = "dw.knowledge.rerank"
# One call of the egress client (connections-and-vault R3).
DW_EGRESS_REQUEST: Final = "dw.egress.request"
# One attempt of a Studio step, inside the node wrapper (workflow-engine R4.9).
DW_NODE: Final = "dw.node"
# One check of `ResidencyGate` (compliance-pdpl R2.1; ADR-0123 decision 6). The
# kernel names it as `dw_kernel.residency.RESIDENCY_SPAN`, which cannot import
# this module; `test_residency_gate.py` holds the two to one value.
DW_RESIDENCY_CHECK: Final = "dw.residency.check"
DW_SPAN_NAMES: Final = frozenset(
    {DW_KNOWLEDGE_RERANK, DW_EGRESS_REQUEST, DW_NODE, DW_RESIDENCY_CHECK}
)


def chat_span_name(model: str) -> str:
    return f"{OP_CHAT} {model}"


def execute_tool_span_name(tool: str) -> str:
    return f"{OP_EXECUTE_TOOL} {tool}"


def invoke_workflow_span_name(worker_id: str) -> str:
    return f"{OP_INVOKE_WORKFLOW} {worker_id}"


def span_operation(name: str) -> str:
    """The part of a span name the contract governs: the operation, or the name."""
    return name.split(" ", 1)[0]


# ------------------------------------------------------------- attributes --
# Upstream identifier keys we emit. Content keys (`gen_ai.input.messages`,
# `gen_ai.output.messages`, `gen_ai.system_instructions`,
# `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`) are never listed.
GENAI_ATTRIBUTES: Final = frozenset(
    {
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.tool.name",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "error.type",
    }
)

# Set by the OTel SDK itself when a span records an exception. The type is an
# identifier; `exception.message` and `exception.stacktrace` carry whatever the
# exception was built from, and are dropped (spec R1.4).
OTEL_CORE_ATTRIBUTES: Final = frozenset({"exception.type"})

DW_ATTRIBUTES: Final = frozenset(
    {
        "dw.channel",
        # Where a model call was processed and who processed it (ADR-0123
        # decisions 5, 6): `vn`/`foreign` and a processor's short name, set by
        # configuration, never by a run.
        "dw.data_location",
        # Why an egress call leaves: a value from a set (connections-and-vault R3).
        "dw.egress.purpose",
        "dw.graph_version",
        "dw.input_tokens",
        "dw.latency_ms",
        "dw.model",
        "dw.model_profile",
        "dw.output_tokens",
        "dw.policy_version",
        "dw.processor",
        "dw.prompt_bundle_version",
        "dw.prompt_id",
        "dw.prompt_version",
        "dw.provider",
        "dw.release_manifest_ref",
        "dw.rerank.candidates",
        "dw.rerank.top_k",
        # Whether the gate admitted the destination: a boolean.
        "dw.residency.admitted",
        # The run's data route class: one of three values (ADR-0123 decision 3).
        "dw.route_class",
        "dw.run_id",
        # live, test or simulate (tenant-config R4.3): a value from a set.
        "dw.run_mode",
        # A Studio step's id and its `type@major` (the `dw.node` span): ids
        # the document gives, never a value a step read or wrote.
        "dw.step_id",
        "dw.step_type",
        "dw.subject_ref",
        "dw.tenant_id",
        "dw.tool_name",
        "dw.tool_version",
        "dw.toolset_version",
        "dw.trace_id",
        "dw.worker_id",
        "dw.worker_version",
        "dw.workspace_id",
    }
)

# Label keys of the `dw_*` metrics. Prometheus alert rules read them
# (`infra/prometheus/alerts.yml`), so they are a contract like the names.
METRIC_LABELS: Final = frozenset(
    {
        "approval_type",
        "direction",
        "error",
        # `dw_node_failure_total`: `error_type_label(code)`, a closed set.
        "error_type",
        "model",
        # The egress counters (connections-and-vault R3): each a value from a set.
        "outcome",
        "provider",
        "purpose",
        "queue",
        "reason",
        "status",
        "tool",
        "worker",
    }
)

# `extra=` keys a log line may carry. Identifiers, counts and type names; free
# text (an exception's message, a fact the model wrote) has no key here.
LOG_FIELDS: Final = frozenset(
    {
        "attempt",
        "deleted",
        "error_type",
        "held_by_citations",
        "memory_id",
        "memory_ids",
        "months_ahead",
        "of",
        "partitions",
        "policy_version",
        "rerank_skipped",
        "retention_class",
        "run_id",
        "status",
        "superseded",
        "vectors_left",
        "worker_id",
    }
)

ALLOWED_KEYS: Final = (
    GENAI_ATTRIBUTES | OTEL_CORE_ATTRIBUTES | DW_ATTRIBUTES | METRIC_LABELS | LOG_FIELDS
)


def snapshot_path(repo_root: Path) -> Path:
    """Where the snapshot for the pinned commit lives, under `repo_root`."""
    name = f"genai-semconv@{GENAI_SEMCONV_COMMIT[:12]}.json"
    return repo_root / "contracts" / "telemetry" / name


def dw_names() -> dict[str, list[str]]:
    """What this module adds to the snapshot: only names that are ours by prefix."""
    return {
        "span_names": sorted(DW_SPAN_NAMES),
        "attributes": sorted(DW_ATTRIBUTES),
        "metrics": sorted(ALL_METRICS),
        "metric_labels": sorted(METRIC_LABELS),
    }


# --------------------------------------------------------------- contract --
def load_snapshot(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def contract_violations(snapshot: Mapping[str, Any], recording: RecordingTelemetry) -> list[str]:
    """Every name `recording` captured that the pinned snapshot does not allow.

    A span is judged by its operation (`chat` of `chat gpt-x`); an attribute key
    must be in the snapshot AND in `ALLOWED_KEYS`, because upstream's content
    keys are in the snapshot too; a metric name must be upstream's or ours, and
    its label keys ours.
    """
    upstream, ours = snapshot["upstream"], snapshot["dw"]
    operations = set(upstream["operations"]) | set(ours["span_names"])
    attributes = (set(upstream["attributes"]) | set(ours["attributes"])) & ALLOWED_KEYS
    metric_names = set(upstream["metrics"]) | set(ours["metrics"])
    labels = set(ours["metric_labels"])
    found: list[str] = []
    for name, span_attributes in recording.spans:
        if span_operation(name) not in operations:
            found.append(f"span {name!r}")
        found.extend(
            f"attribute {key!r} on span {name!r}"
            for key in span_attributes
            if key not in attributes
        )
    for name, _, metric_attributes in recording.metrics + recording.gauges + recording.histograms:
        if name not in metric_names:
            found.append(f"metric {name!r}")
        found.extend(
            f"label {key!r} on metric {name!r}" for key in metric_attributes if key not in labels
        )
    return sorted(set(found))
