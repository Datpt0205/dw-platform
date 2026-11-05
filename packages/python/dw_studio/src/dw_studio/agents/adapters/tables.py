"""`studio.agent_settings` in the core's `metadata` (studio-skeleton R6.7), as
revision fece6611d786 creates it; `test_metadata_matches_catalog.py` holds the
two equal. Policies, column grants and the trigger are the migration's alone.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from dw_platform.adapters.persistence import tables as platform
from dw_studio.core.adapters.tables import artifacts, metadata

_TS = sa.TIMESTAMP(timezone=True)

agent_settings = sa.Table(
    "agent_settings",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("artifact_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("audience", JSONB, nullable=False),
    sa.Column("owner_user_id", UUID(as_uuid=True), nullable=True),
    # No server default, on purpose (AB10).
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("row_version", sa.Integer, nullable=False),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", _TS, nullable=False, server_default=sa.text("now()")),
    sa.ForeignKeyConstraint(
        ["artifact_id", "tenant_id"],
        [artifacts.c.id, artifacts.c.tenant_id],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["owner_user_id", "tenant_id"],
        [platform.tenant_members.c.user_id, platform.tenant_members.c.tenant_id],
        ondelete="SET NULL (owner_user_id)",
    ),
    sa.Index(None, "tenant_id", "owner_user_id"),
)
