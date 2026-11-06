"""SQLAlchemy Core description of schema `studio` (studio-skeleton R6.7), and
of the two `platform` tables only Studio writes, the run manifest and its keys.

Mirrors the migrations, and `test_metadata_matches_catalog.py` holds the two
equal after `alembic upgrade head`: tables, columns, types, nullability, keys
and indexes. Policies, column grants and triggers are the migration's alone.

A composite key lists its own column first, `(<column>, tenant_id)`, so its
name from `NAMING_CONVENTION` says which column it holds; PostgreSQL matches
it to `UNIQUE (tenant_id, id)` as a set.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from dw_kernel.naming import NAMING_CONVENTION
from dw_platform.adapters.persistence import tables as platform

metadata = sa.MetaData(schema="studio", naming_convention=NAMING_CONVENTION)

_TS = sa.TIMESTAMP(timezone=True)


def _composite(column: str, target: sa.Table, *, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "tenant_id"], [target.c.id, target.c.tenant_id], ondelete=ondelete
    )


artifact_kinds = sa.Table(
    "artifact_kinds",
    metadata,
    sa.Column("kind", sa.Text, primary_key=True),
    # No server default, on purpose (tenant-config R2.14).
    sa.Column("has_quality_gate", sa.Boolean, nullable=False),
)

artifacts = sa.Table(
    "artifacts",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column(
        "kind",
        sa.Text,
        sa.ForeignKey(artifact_kinds.c.kind, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    ),
    sa.Column("api_name", sa.Text, nullable=False),
    sa.Column("owning_workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("labels", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("origin", JSONB, nullable=True),
    sa.Column("last_version_no", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("row_version", sa.Integer, nullable=False),
    sa.Column("deleted_at", _TS, nullable=True),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.UniqueConstraint("tenant_id", "id"),
    sa.ForeignKeyConstraint(
        ["owning_workspace_id", "tenant_id"],
        [platform.workspaces.c.id, platform.workspaces.c.tenant_id],
        ondelete="RESTRICT",
    ),
    sa.Index(None, "tenant_id", "owning_workspace_id"),
    sa.Index(
        "uq_artifacts_tenant_id_kind_api_name",
        "tenant_id",
        "kind",
        "api_name",
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    ),
    sa.Index(
        "ix_artifacts_tenant_id_kind_updated_at_id",
        "tenant_id",
        "kind",
        sa.text("updated_at DESC"),
        sa.text("id DESC"),
    ),
    sa.Index(
        "ix_artifacts_tenant_id_updated_at_id",
        "tenant_id",
        sa.text("updated_at DESC"),
        sa.text("id DESC"),
    ),
)

artifact_versions = sa.Table(
    "artifact_versions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("artifact_id", UUID(as_uuid=True), nullable=False),
    sa.Column("stage", sa.Text, nullable=False),
    sa.Column("version_no", sa.Integer, nullable=True),
    sa.Column("document_schema", sa.Text, nullable=False),
    sa.Column("document", JSONB, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=True),
    sa.Column("definition_hash", sa.Text, nullable=True),
    sa.Column("row_version", sa.Integer, nullable=False),
    sa.Column("based_on_version_id", UUID(as_uuid=True), nullable=True),
    sa.Column("change_note", sa.Text, nullable=True),
    # The lifecycle columns (agent-lifecycle ticket 03, revision 6503c6f309b1).
    # `gate_run_id` gets its composite key with `studio.gate_runs` (ticket 06).
    sa.Column("gate_run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("publish_approval_id", UUID(as_uuid=True), nullable=True),
    sa.Column("tighten_only", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("compared_live_hash", sa.Text, nullable=True),
    sa.Column("contributor_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
    sa.Column("submitted_by", UUID(as_uuid=True), nullable=True),
    sa.Column("submitted_at", _TS, nullable=True),
    sa.Column("published_by", UUID(as_uuid=True), nullable=True),
    sa.Column("published_at", _TS, nullable=True),
    sa.Column("retired_by", UUID(as_uuid=True), nullable=True),
    sa.Column("retired_at", _TS, nullable=True),
    sa.Column("retire_reason_code", sa.Text, nullable=True),
    sa.UniqueConstraint("tenant_id", "id"),
    sa.UniqueConstraint("artifact_id", "version_no"),
    _composite("artifact_id", artifacts, ondelete="CASCADE"),
    sa.ForeignKeyConstraint(
        ["publish_approval_id", "tenant_id"],
        [platform.approval_requests.c.id, platform.approval_requests.c.tenant_id],
        ondelete="RESTRICT",
    ),
    sa.Index(None, "tenant_id", "artifact_id"),
    sa.Index(None, "tenant_id", "based_on_version_id"),
    sa.Index(None, "tenant_id", "publish_approval_id"),
    sa.Index(
        "uq_artifact_versions_unreleased",
        "artifact_id",
        unique=True,
        postgresql_where=sa.text("stage IN ('draft', 'evaluating', 'awaiting_approval')"),
    ),
    sa.Index(
        "uq_artifact_versions_live",
        "artifact_id",
        unique=True,
        postgresql_where=sa.text("stage = 'live'"),
    ),
)

# A view (agent-lifecycle R1.5), so not in `metadata`: nothing creates it but
# its revision, and the catalog test compares tables.
artifact_display_stage = sa.table(
    "artifact_display_stage",
    sa.column("tenant_id", UUID(as_uuid=True)),
    sa.column("artifact_id", UUID(as_uuid=True)),
    sa.column("display_stage", sa.Text),
    schema="studio",
)
# Declared after the table exists, as a self-reference must be. `SET NULL` of
# the one column only: `tenant_id` is NOT NULL (measured 24/10/2026, PG 16).
artifact_versions.append_constraint(
    _composite("based_on_version_id", artifact_versions, ondelete="SET NULL (based_on_version_id)")
)

definition_manifests = sa.Table(
    "definition_manifests",
    metadata,
    sa.Column(
        "tenant_id",
        UUID(as_uuid=True),
        sa.ForeignKey(platform.tenants.c.id, ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column("hash", sa.Text, primary_key=True),
    sa.Column("body", JSONB, nullable=False),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
)

dependencies = sa.Table(
    "dependencies",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("from_artifact_id", UUID(as_uuid=True), nullable=False),
    sa.Column("from_version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("to_kind", sa.Text, nullable=False),
    sa.Column("to_key", sa.Text, nullable=False),
    sa.Column("to_version", sa.Integer, nullable=True),
    sa.Column("to_hash", sa.Text, nullable=True),
    sa.Column("to_artifact_id", UUID(as_uuid=True), nullable=True),
    sa.Column("to_version_id", UUID(as_uuid=True), nullable=True),
    sa.Column("usage", sa.Text, nullable=False),
    sa.Column("path", sa.Text, nullable=False),
    # custom-objects ticket 02 (ADR-0109 decision 5): a dependency on a field.
    sa.Column("to_field_id", UUID(as_uuid=True), nullable=True),
    _composite("from_artifact_id", artifacts, ondelete="CASCADE"),
    _composite("from_version_id", artifact_versions, ondelete="CASCADE"),
    _composite("to_artifact_id", artifacts, ondelete="RESTRICT"),
    _composite("to_version_id", artifact_versions, ondelete="RESTRICT"),
    # The target named as text: the core imports no capability ("Studio core
    # imports no capability"); `dw_studio.records.adapters.tables` describes it.
    sa.ForeignKeyConstraint(
        ["to_field_id", "tenant_id"],
        ["studio.field_defs.id", "studio.field_defs.tenant_id"],
        name="fk_dependencies_to_field_id_field_defs",
        ondelete="RESTRICT",
    ),
    sa.Index(None, "tenant_id", "from_artifact_id"),
    sa.Index(None, "tenant_id", "from_version_id"),
    sa.Index(None, "tenant_id", "to_artifact_id"),
    sa.Index(None, "tenant_id", "to_version_id"),
    sa.Index(None, "tenant_id", "to_kind", "to_key"),
    sa.Index(None, "tenant_id", "to_field_id"),
)

# What a Studio run pinned (tenant-config ticket 04, revision 28a94cda6fdf).
# In schema `platform`, beside the run row that names it; described here, by
# the one package that writes and reads it.
run_manifests = sa.Table(
    "run_manifests",
    metadata,
    sa.Column(
        "tenant_id",
        UUID(as_uuid=True),
        sa.ForeignKey(platform.tenants.c.id, ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column("hash", sa.Text, primary_key=True),
    sa.Column("body", JSONB, nullable=False),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    schema="platform",
)

# A tenant's configuration versions (tenant-config ticket 05): written by
# `dw_platform`'s `ConfigVersionService`, described here because the run
# manifest's keys point into it.
config_versions = sa.Table(
    "config_versions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("key", sa.Text, nullable=False),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("version_no", sa.Integer, nullable=False),
    sa.Column("base_version", sa.Integer, nullable=False),
    sa.Column("base_bindings_hash", sa.Text, nullable=False),
    sa.Column("base_approved_id", UUID(as_uuid=True), nullable=True),
    sa.Column("document", JSONB, nullable=False),
    sa.Column("document_hash", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("approval_id", UUID(as_uuid=True), nullable=False),
    sa.Column("proposed_by", UUID(as_uuid=True), nullable=False),
    sa.Column("proposed_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.Column("decided_by", UUID(as_uuid=True), nullable=True),
    sa.Column("decided_at", _TS, nullable=True),
    sa.Column("decision_comment", sa.Text, nullable=True),
    sa.Column("superseded_at", _TS, nullable=True),
    sa.ForeignKeyConstraint(["tenant_id"], [platform.tenants.c.id], ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(
        ["approval_id", "tenant_id", "workspace_id"],
        [
            platform.approval_requests.c.id,
            platform.approval_requests.c.tenant_id,
            platform.approval_requests.c.workspace_id,
        ],
        name="fk_config_versions_approval_id_approval_requests",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint("tenant_id", "id"),
    sa.UniqueConstraint("tenant_id", "kind", "key", "version_no"),
    sa.Index(None, "tenant_id", "workspace_id", "approval_id", unique=True),
    sa.Index(
        "uq_config_versions_tenant_id_kind_key_proposed",
        "tenant_id",
        "kind",
        "key",
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    ),
    sa.Index(
        "uq_config_versions_tenant_id_kind_key_approved",
        "tenant_id",
        "kind",
        "key",
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    ),
    schema="platform",
)

run_manifest_keys = sa.Table(
    "run_manifest_keys",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("manifest_hash", sa.Text, nullable=False),
    # Exactly one of the two (`ck_run_manifest_keys_one_target`, ticket 05).
    sa.Column("artifact_version_id", UUID(as_uuid=True), nullable=True),
    sa.Column("config_version_id", UUID(as_uuid=True), nullable=True),
    sa.ForeignKeyConstraint(
        ["manifest_hash", "tenant_id"],
        [run_manifests.c.hash, run_manifests.c.tenant_id],
        ondelete="CASCADE",
    ),
    _composite("artifact_version_id", artifact_versions, ondelete="RESTRICT"),
    _composite("config_version_id", config_versions, ondelete="RESTRICT"),
    sa.UniqueConstraint(
        "tenant_id",
        "manifest_hash",
        "config_version_id",
        name="uq_run_manifest_keys_tenant_id_manifest_hash_config_version_id",
    ),
    sa.Index(None, "tenant_id", "config_version_id"),
    # The convention's name is one character past PostgreSQL's 63.
    sa.UniqueConstraint(
        "tenant_id",
        "manifest_hash",
        "artifact_version_id",
        name="uq_run_manifest_keys_tenant_id_manifest_hash_artifact_version",
    ),
    sa.Index(None, "tenant_id", "artifact_version_id"),
    schema="platform",
)

# compliance-pdpl ticket 05 (revision c240f5261ec5): a version's capability
# analysis at its submit; written once, read by the gate and by a parent
# workflow's step on the version.
version_assessments = sa.Table(
    "version_assessments",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("definition_hash", sa.Text, nullable=False),
    sa.Column("analyser_version", sa.Text, nullable=False),
    sa.Column("signals", ARRAY(sa.Text), nullable=False),
    sa.Column("labels", JSONB, nullable=False),
    sa.Column("verdict", sa.Text, nullable=False),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    _composite("version_id", artifact_versions, ondelete="CASCADE"),
    sa.UniqueConstraint(
        "tenant_id",
        "version_id",
        "definition_hash",
        "analyser_version",
        name="uq_version_assessments_tenant_version_hash_analyser",
    ),
)
