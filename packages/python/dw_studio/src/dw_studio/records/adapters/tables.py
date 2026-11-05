"""SQLAlchemy Core description of the four tables of custom objects (revision
16357d3dbff8), on the one `metadata` of `dw_studio.core.adapters.tables`.

Mirrors the migration; `test_metadata_matches_catalog.py` holds the two equal
after `alembic upgrade head`. The slot columns come from `SLOTS`, the one
owner of the slot set in code, and the partitions of `studio.records` are the
migration's alone: rows are reached only through the parent.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from dw_platform.adapters.persistence import tables as platform
from dw_studio.core.adapters.tables import artifact_versions, artifacts, metadata
from dw_studio.records.domain.field_types import SLOTS

_TS = sa.TIMESTAMP(timezone=True)
_VI = "vi-VN-x-icu"

_SLOT_TYPES: dict[str, sa.types.TypeEngine[Any]] = {
    "t": sa.Text(collation=_VI),
    "u": sa.Text(),
    "i": sa.BigInteger(),
    "f": sa.Float(precision=53),
    "d": sa.Date(),
    "z": _TS,
    "b": sa.Boolean(),
}


def _composite(column: str, target: sa.Table, *, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "tenant_id"], [target.c.id, target.c.tenant_id], ondelete=ondelete
    )


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", UUID(as_uuid=True), nullable=False),
    ]


object_defs = sa.Table(
    "object_defs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("api_name", sa.Text, nullable=False),
    sa.Column("labels", JSONB, nullable=False),
    sa.Column("default_access", sa.Text, nullable=False, server_default=sa.text("'private'")),
    sa.Column("ai_description", sa.Text, nullable=True),
    sa.Column("applied_version_id", UUID(as_uuid=True), nullable=False),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.Column("next_field_no", sa.Integer, nullable=False, server_default=sa.text("1")),
    *_stamps(),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
    sa.UniqueConstraint("tenant_id", "api_name"),
    _composite("id", artifacts, ondelete="RESTRICT"),
    _composite("applied_version_id", artifact_versions, ondelete="RESTRICT"),
    sa.Index(None, "tenant_id", "applied_version_id"),
)

field_defs = sa.Table(
    "field_defs",
    metadata,
    sa.Column("id", UUID(as_uuid=True), nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("object_id", UUID(as_uuid=True), nullable=False),
    sa.Column("api_name", sa.Text, nullable=False),
    sa.Column("labels", JSONB, nullable=False),
    sa.Column("ai_description", sa.Text, nullable=True),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("number_mode", sa.Text, nullable=True),
    sa.Column("scale", sa.Integer, nullable=True),
    sa.Column("currency_code", sa.Text, nullable=True),
    sa.Column("max_length", sa.Integer, nullable=True),
    sa.Column("required", sa.Boolean, nullable=False),
    sa.Column("is_unique", sa.Boolean, nullable=False),
    sa.Column("indexed", sa.Boolean, nullable=False),
    sa.Column("pd_category", sa.Text, nullable=False),
    sa.Column("sensitive_type", sa.Text, nullable=True),
    sa.Column("subject_identifier", sa.Text, nullable=True),
    sa.Column("storage_kind", sa.Text, nullable=False),
    sa.Column("slot", sa.Text, nullable=True),
    sa.Column("field_no", sa.Integer, nullable=True),
    *_stamps(),
    # field-security/01 (revision 2f177d264a27): `open` or `secured`, added
    # last, so it sits after the stamps in the catalog too.
    sa.Column("access_mode", sa.Text, nullable=False, server_default=sa.text("'open'")),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
    sa.UniqueConstraint("tenant_id", "object_id", "api_name"),
    sa.UniqueConstraint("tenant_id", "object_id", "field_no"),
    sa.Index(
        "uq_field_defs_tenant_id_object_id_slot",
        "tenant_id",
        "object_id",
        "slot",
        unique=True,
        postgresql_where=sa.text("slot IS NOT NULL"),
    ),
)
field_defs.append_constraint(_composite("object_id", object_defs, ondelete="CASCADE"))

picklist_options = sa.Table(
    "picklist_options",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("field_id", UUID(as_uuid=True), nullable=False),
    sa.Column("key", sa.Text, nullable=False),
    sa.Column("labels", JSONB, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("active", sa.Boolean, nullable=False),
    *_stamps(),
    sa.PrimaryKeyConstraint("tenant_id", "field_id", "key"),
    _composite("field_id", field_defs, ondelete="CASCADE"),
)

# A role's read or edit on one field (revision ef68083f2905, tenant-rbac ticket
# 04): tenant-wide, judged by `platform.rbac_guard`, written by the role service
# in raw SQL. Described here so the catalog comparison covers it like the rest.
field_permissions = sa.Table(
    "field_permissions",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("role_id", UUID(as_uuid=True), nullable=False),
    sa.Column("field_id", UUID(as_uuid=True), nullable=False),
    sa.Column("access", sa.Text, nullable=False),
    sa.Column("granted_by", UUID(as_uuid=True), nullable=True),
    sa.Column("granted_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.PrimaryKeyConstraint("tenant_id", "role_id", "field_id"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "role_id"],
        [platform.tenant_roles.c.tenant_id, platform.tenant_roles.c.id],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["tenant_id", "field_id"],
        [field_defs.c.tenant_id, field_defs.c.id],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(["granted_by"], [platform.users.c.id], ondelete="SET NULL"),
    sa.Index(None, "tenant_id", "field_id"),
    sa.Index(None, "granted_by"),
)

# The record reach ledger (revision f6ea6e818d0c, record-access ticket 02): read
# and written only in SQL, by `studio.ensure_principal_scope()` and the
# `studio.acl_*` readers; described here so the catalog comparison covers it.
_UUIDS = ARRAY(UUID(as_uuid=True))
_REACH = (
    *(
        f"{action}_{arm}"
        for action in ("read", "create", "update", "delete", "assign")
        for arm in ("own", "keys", "tenant")
    ),
    "create_own_keys",
)

access_epochs = sa.Table(
    "access_epochs",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("epoch", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("changed_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.PrimaryKeyConstraint("tenant_id"),
    sa.ForeignKeyConstraint(["tenant_id"], [platform.tenants.c.id], ondelete="CASCADE"),
)

principal_scopes = sa.Table(
    "principal_scopes",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("principal_id", UUID(as_uuid=True), nullable=False),
    sa.Column("epoch", sa.BigInteger, nullable=False),
    sa.Column("version", sa.BigInteger, nullable=False),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("computed_at", _TS, nullable=False),
    sa.Column("valid_until", _TS, nullable=True),
    sa.Column("workspace_ids", _UUIDS, nullable=False),
    *(
        sa.Column(column, _UUIDS, nullable=False, server_default=sa.text("'{}'::uuid[]"))
        for column in _REACH
    ),
    sa.PrimaryKeyConstraint("tenant_id", "principal_id"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "principal_id"],
        [platform.tenant_members.c.tenant_id, platform.tenant_members.c.user_id],
        ondelete="CASCADE",
    ),
)

# One row per trigger since record-access/03 (revision 2c2095fbb4c7), which
# declared `trg_studio_default_access` beside `studio.object_defs`'s first.
access_input_tables = sa.Table(
    "access_input_tables",
    metadata,
    sa.Column("table_name", sa.Text, nullable=False),
    sa.Column("trigger_function", sa.Text, nullable=False),
    sa.Column("events", sa.Text, nullable=True),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("trigger_name", sa.Text, nullable=False),
    sa.Column("condition", sa.Text, nullable=True),
    sa.PrimaryKeyConstraint("table_name", "trigger_name"),
)

# The data boundaries of agents and workflows (revision 996c234cfde3,
# record-access ticket 04): written only by `studio.record_actor_boundary`,
# read by `studio.boundary_chain` and `studio.acl_boundary_objects`.
actor_boundaries = sa.Table(
    "actor_boundaries",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("source_id", UUID(as_uuid=True), nullable=False),
    sa.Column("source_version", sa.Text, nullable=False),
    sa.Column("run_id", UUID(as_uuid=True), nullable=True),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
    sa.ForeignKeyConstraint(["tenant_id"], [platform.tenants.c.id], ondelete="CASCADE"),
    sa.Index(
        "uq_actor_boundaries_tenant_id_kind_source_id_source_version",
        "tenant_id",
        "kind",
        "source_id",
        "source_version",
        unique=True,
        postgresql_where=sa.text("run_id IS NULL"),
    ),
    sa.Index(
        "uq_actor_boundaries_tenant_id_run_id",
        "tenant_id",
        "run_id",
        unique=True,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    ),
)


def _boundary_key() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "boundary_id"],
        [actor_boundaries.c.tenant_id, actor_boundaries.c.id],
        ondelete="CASCADE",
    )


actor_boundary_objects = sa.Table(
    "actor_boundary_objects",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("boundary_id", UUID(as_uuid=True), nullable=False),
    sa.Column("object_id", UUID(as_uuid=True), nullable=False),
    *(
        sa.Column(flag, sa.Boolean, nullable=False)
        for flag in ("can_read", "can_create", "can_update", "can_delete", "can_assign")
    ),
    sa.PrimaryKeyConstraint("tenant_id", "boundary_id", "object_id"),
    _boundary_key(),
    sa.ForeignKeyConstraint(
        ["tenant_id", "object_id"],
        [object_defs.c.tenant_id, object_defs.c.id],
        ondelete="RESTRICT",
    ),
    sa.Index("ix_actor_boundary_objects_tenant_id_object_id", "tenant_id", "object_id"),
)

actor_boundary_fields = sa.Table(
    "actor_boundary_fields",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("boundary_id", UUID(as_uuid=True), nullable=False),
    sa.Column("field_id", UUID(as_uuid=True), nullable=False),
    sa.Column("access", sa.Text, nullable=False),
    sa.PrimaryKeyConstraint("tenant_id", "boundary_id", "field_id"),
    _boundary_key(),
    sa.ForeignKeyConstraint(
        ["tenant_id", "field_id"],
        [field_defs.c.tenant_id, field_defs.c.id],
        ondelete="RESTRICT",
    ),
    sa.Index("ix_actor_boundary_fields_tenant_id_field_id", "tenant_id", "field_id"),
)

SLOT_COLUMNS: tuple[str, ...] = tuple(slot for slots in SLOTS.values() for slot in slots)

records = sa.Table(
    "records",
    metadata,
    sa.Column("id", UUID(as_uuid=True), nullable=False),
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("object_id", UUID(as_uuid=True), nullable=False),
    sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
    sa.Column("owner_kind", sa.Text, nullable=False),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("name", sa.Text(collation=_VI), nullable=False),
    sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
    sa.Column("create_key", sa.Text, nullable=True),
    sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    *(
        sa.Column(slot, _SLOT_TYPES[family], nullable=True)
        for family, slots in SLOTS.items()
        for slot in slots
    ),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.Column("created_by", UUID(as_uuid=True), nullable=False),
    sa.Column("updated_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_by", UUID(as_uuid=True), nullable=False),
    sa.Column("deleted_at", _TS, nullable=True),
    sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
    # record-access/03 (revision 2c2095fbb4c7): the (object, owning workspace)
    # key the record policies match, from `studio.access_key()`, its one owner.
    sa.Column(
        "access_key",
        UUID(as_uuid=True),
        sa.Computed("studio.access_key(object_id, workspace_id)", persisted=True),
        nullable=True,
    ),
    sa.PrimaryKeyConstraint("tenant_id", "id"),
    _composite("object_id", object_defs, ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(
        ["workspace_id", "tenant_id"],
        [platform.workspaces.c.id, platform.workspaces.c.tenant_id],
        ondelete="RESTRICT",
    ),
    sa.Index(
        "uq_records_tenant_id_object_id_create_key",
        "tenant_id",
        "object_id",
        "create_key",
        unique=True,
        postgresql_where=sa.text("create_key IS NOT NULL"),
    ),
    sa.Index(
        "ix_records_tenant_id_object_id_created_at_id",
        "tenant_id",
        "object_id",
        sa.text("created_at DESC"),
        sa.text("id DESC"),
    ),
    sa.Index(
        "ix_records_tenant_id_object_id_updated_at_id",
        "tenant_id",
        "object_id",
        sa.text("updated_at DESC"),
        sa.text("id DESC"),
    ),
    sa.Index(None, "tenant_id", "object_id", "name", "id"),
    sa.Index(None, "tenant_id", "workspace_id"),
    sa.Index(
        "ix_records_tenant_id_access_key_created_at_id",
        "tenant_id",
        "access_key",
        sa.text("created_at DESC"),
        sa.text("id DESC"),
    ),
    sa.Index(
        "ix_records_tenant_id_owner_id_object_id_created_at_id",
        "tenant_id",
        "owner_id",
        "object_id",
        sa.text("created_at DESC"),
        sa.text("id DESC"),
    ),
    *(
        sa.Index(
            None,
            "tenant_id",
            "object_id",
            slot,
            "id",
            postgresql_where=sa.text(f"{slot} IS NOT NULL AND deleted_at IS NULL"),
        )
        for slot in SLOT_COLUMNS
    ),
    *(
        sa.Index(
            f"uq_records_tenant_id_object_id_{slot}",
            "tenant_id",
            "object_id",
            slot,
            unique=True,
            postgresql_where=sa.text(f"{slot} IS NOT NULL AND deleted_at IS NULL"),
        )
        for slot in SLOTS["u"]
    ),
    postgresql_partition_by="HASH (tenant_id)",
)

# The `wf:` key of each record write a workflow step sends (revision
# 902ac246a9dc, custom-objects ticket 03): one principal's row, written in the
# transaction of the write and read back on a replay.
record_write_keys = sa.Table(
    "record_write_keys",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
    sa.Column("write_key", sa.Text, nullable=False),
    sa.Column("record_id", UUID(as_uuid=True), nullable=False),
    sa.Column("op", sa.Text, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("owner_kind", sa.Text, nullable=True),
    sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
    sa.Column("owner_workspace_id", UUID(as_uuid=True), nullable=True),
    sa.Column("actor_id", UUID(as_uuid=True), nullable=False),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.PrimaryKeyConstraint("tenant_id", "write_key"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "record_id"], [records.c.tenant_id, records.c.id], ondelete="CASCADE"
    ),
    sa.Index(None, "tenant_id", "record_id"),
    sa.Index(None, "created_at"),
)
