"""Canonical metric names.

Central registry so emitters and dashboards never drift. Labels must stay
low-cardinality: never a user id or raw prompt.

Every name here has a call site in `src/` that emits it, and
`test_every_declared_metric_is_emitted` holds that: a name declared and emitted
by nothing reads like a signal on a dashboard and measures nothing
(`failure-modes.md` #1). `dw_node_failure_total` and three rates
(`dw_retrieval_hit_rate`, `dw_human_intervention_rate`, `dw_task_success_rate`)
left for that reason; the node wrapper of workflow-engine/03 declares the first
again together with its emitter.
"""

from __future__ import annotations

from typing import Final

DW_RUN_TOTAL: Final = "dw_run_total"  # labels: worker, status
DW_RUN_DURATION_SECONDS: Final = "dw_run_duration_seconds"  # histogram; labels: worker, status
DW_TOOL_CALL_TOTAL: Final = "dw_tool_call_total"  # labels: tool, status
DW_APPROVAL_WAIT_SECONDS: Final = (
    "dw_approval_wait_seconds"  # histogram; labels: worker, approval_type
)
DW_MODEL_TOKENS_TOTAL: Final = "dw_model_tokens_total"  # labels: provider, model, direction
DW_MODEL_COST_USD_TOTAL: Final = "dw_model_cost_usd_total"  # labels: worker, provider
# A search answered in vector order because the reranker failed.
DW_RETRIEVAL_RERANK_SKIPPED_TOTAL: Final = "dw_retrieval_rerank_skipped_total"  # labels: error

# Ops hardening Phase 5. Gauges (current value, not accumulated — see
# `TelemetryPort.set_gauge`): a Counter cannot represent "how many are
# pending right now" without lying about it on the next tick.
DW_OUTBOX_BACKLOG_SIZE: Final = "dw_outbox_backlog_size"  # no labels
DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS: Final = (
    "dw_outbox_oldest_pending_age_seconds"  # no labels; 0 when the backlog is empty
)
DW_REAPER_REAPED_TOTAL: Final = "dw_reaper_reaped_total"  # labels: queue

ALL_METRICS: Final = (
    DW_RUN_TOTAL,
    DW_RUN_DURATION_SECONDS,
    DW_TOOL_CALL_TOTAL,
    DW_APPROVAL_WAIT_SECONDS,
    DW_MODEL_TOKENS_TOTAL,
    DW_MODEL_COST_USD_TOTAL,
    DW_RETRIEVAL_RERANK_SKIPPED_TOTAL,
    DW_OUTBOX_BACKLOG_SIZE,
    DW_OUTBOX_OLDEST_PENDING_AGE_SECONDS,
    DW_REAPER_REAPED_TOTAL,
)

# Bucket boundaries, in seconds, of each histogram (telemetry-and-audit spec,
# "Trong phạm vi"). A run spans half a second to an hour; an approval waits a
# minute to a week, because a person answers it.
HISTOGRAM_BUCKETS: Final[dict[str, tuple[float, ...]]] = {
    DW_RUN_DURATION_SECONDS: (0.5, 1, 2, 5, 10, 30, 60, 120, 300, 900, 1800, 3600),
    DW_APPROVAL_WAIT_SECONDS: (60, 300, 900, 3600, 14400, 43200, 86400, 259200, 604800),
}
