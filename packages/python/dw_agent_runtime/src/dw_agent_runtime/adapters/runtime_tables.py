"""SQLAlchemy Core tables for runtime persistence (migrations 0002, 0024 and 3f1cb1d4cece)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID

from dw_kernel.naming import NAMING_CONVENTION

metadata = sa.MetaData(schema="platform", naming_convention=NAMING_CONVENTION)

worker_runs = sa.Table(
    "worker_runs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("worker_id", sa.Text, nullable=False),
    sa.Column("worker_version", sa.Text, nullable=False),
    sa.Column("graph_version", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="pending"),
    sa.Column("input", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("result", JSONB, nullable=True),
    sa.Column("error", JSONB, nullable=True),
    sa.Column("approval_request_id", UUID(as_uuid=True), nullable=True),
    sa.Column("release_manifest_ref", sa.Text, nullable=True),
    # Migration 0005. Nullable only because runs started before it have no
    # record of these; every run since carries all four.
    sa.Column("prompt_bundle_version", sa.String(16), nullable=True),
    sa.Column("toolset_version", sa.String(16), nullable=True),
    sa.Column("policy_version", sa.String(16), nullable=True),
    sa.Column("memory_policy_version", sa.String(16), nullable=True),
    # Migration 0006. The level the run ran at and the policy that decided with
    # it. Nullable only for runs started before it.
    sa.Column("autonomy_level", sa.Text, nullable=True),
    sa.Column("approval_policy_version", sa.String(16), nullable=True),
    sa.Column("requested_by", UUID(as_uuid=True), nullable=False),
    sa.Column("actor_roles", sa.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("actor_scopes", sa.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("actor_plan_id", sa.Text, nullable=False, server_default=""),
    sa.Column("actor_clearance", sa.Text, nullable=False, server_default="internal"),
    # The ADR-003 roll-up the run started with; see migration 0145. NULL on
    # actor_visible_owners means "never recorded", not "may see nobody".
    sa.Column("actor_record_visibility", sa.Text, nullable=False, server_default="open"),
    sa.Column("actor_visible_owners", sa.ARRAY(UUID(as_uuid=True)), nullable=True),
    sa.Column("trace_id", sa.Text, nullable=True),
    # The record this run is about; see migration 0059.
    sa.Column("subject_ref", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
)

run_checkpoints = sa.Table(
    "run_checkpoints",
    metadata,
    sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
    sa.Column("checkpoint_ns", sa.Text, nullable=False),
    sa.Column("checkpoint_id", sa.Text, nullable=False),
    sa.Column("parent_checkpoint_id", sa.Text, nullable=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("checkpoint", BYTEA, nullable=False),
    sa.Column("metadata", BYTEA, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
)

run_checkpoint_writes = sa.Table(
    "run_checkpoint_writes",
    metadata,
    sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
    sa.Column("checkpoint_ns", sa.Text, nullable=False),
    sa.Column("checkpoint_id", sa.Text, nullable=False),
    sa.Column("task_id", sa.Text, nullable=False),
    sa.Column("idx", sa.Integer, nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("channel", sa.Text, nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("value", BYTEA, nullable=False),
    sa.Column("task_path", sa.Text, nullable=False),
    sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
)

agent_store = sa.Table(
    "agent_store",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("namespace", sa.ARRAY(sa.Text), nullable=False),
    sa.Column("key", sa.Text, nullable=False),
    sa.Column("value", JSONB, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("tenant_id", "namespace", "key"),
)


tenant_daily_spend_guard = sa.Table(
    "tenant_daily_spend_guard",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("spend_date", sa.Date, nullable=False),
    sa.Column("spend_usd", sa.Numeric(12, 4), nullable=False, server_default="0"),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("tenant_id", "spend_date"),
)


tool_executions = sa.Table(
    "tool_executions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("tool_name", sa.Text, nullable=False),
    sa.Column("tool_version", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=True),
    sa.Column("input_hash", sa.Text, nullable=False),
    sa.Column("output_hash", sa.Text, nullable=True),
    sa.Column("output", JSONB, nullable=True),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    # Migration 3f1cb1d4cece. On a terminal row, the `dispatched` row it closes;
    # NULL on every other row.
    sa.Column("dispatch_id", UUID(as_uuid=True), nullable=True),
)


# Migration 3f1cb1d4cece (ADR-0108 decision 5): one live claim per key.
tool_execution_claims = sa.Table(
    "tool_execution_claims",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("tool_name", sa.Text, primary_key=True),
    sa.Column("idempotency_key", sa.Text, primary_key=True),
    sa.Column("run_id", UUID(as_uuid=True), nullable=False),
    sa.Column("claim_token", UUID(as_uuid=True), nullable=False),
    sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
)
