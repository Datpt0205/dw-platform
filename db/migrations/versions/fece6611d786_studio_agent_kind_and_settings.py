"""studio agent kind and its settings

Revision ID: fece6611d786
Revises: 0353c313569f
Create Date: 2026-11-05 16:00:00.000000+00:00

agent-builder ticket 02 (R1.1, R1.4, R1.8, R1.11; AB10, AB12, AB15; ADR-0117
decision 3; OPS-b). The `agent` kind beside its registry entry
(`dw_studio.kinds.agent_kind`), and the settings that sit beside its versions:

- The `agent` row of `studio.artifact_kinds`, with a quality gate (ADR-0120
  decision 1).
- Two permissions, by tenant-rbac/01's classes (step 3) and tenant-rbac/02's
  (step 1): `studio.agents.author`, the kind's read and write key, and
  `studio.agents.manage_settings`, the settings routes' key. Each is
  workspace depth (an agent belongs to its owning workspace), `standard` risk
  (not a `platform.*` key), `active`, owned by `dw_studio` and
  `tenant_grantable`. The submit key, `studio.versions.submit`, is
  agent-lifecycle 03's; `studio.agents.read`, the `/chat` user's key, is
  agent-builder 04's, with the list that reads it.
- `studio.agent_settings`: who may invoke an agent, its accountable owner and
  whether it is enabled, one row per agent and no version of its own. A
  tenant-wide table like the envelope (DO-01): its workspace is the artifact's
  `owning_workspace_id`. The key to the artifact is composite and CASCADEs, so
  the offboarding lane's delete of `studio.artifacts` takes the row with it
  (`dw_app` holds no DELETE); the owner's composite key to
  `platform.tenant_members` sets the column alone to NULL when that person
  leaves (ADR-0103 decision 3's column contract; W2's `principal_ownership`
  lane acts on it). `enabled` has no DEFAULT: a row that does not say is
  refused (AB10).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "fece6611d786"
down_revision = "0353c313569f"
branch_labels = None
depends_on = None

# (key, label): workspace depth, standard risk (tenant-rbac/01's classes).
PERMISSIONS = (
    ("studio.agents.author", "Tạo và sửa định nghĩa agent"),
    ("studio.agents.manage_settings", "Quản lý cài đặt sử dụng của agent"),
)

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"

_TABLE = """
    CREATE TABLE studio.agent_settings (
        tenant_id uuid NOT NULL,
        artifact_id uuid NOT NULL,
        audience jsonb NOT NULL,
        owner_user_id uuid,
        enabled boolean NOT NULL,
        row_version integer NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_agent_settings PRIMARY KEY (tenant_id, artifact_id),
        CONSTRAINT fk_agent_settings_artifact_id_artifacts
            FOREIGN KEY (artifact_id, tenant_id)
            REFERENCES studio.artifacts (id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_agent_settings_owner_user_id_tenant_members
            FOREIGN KEY (owner_user_id, tenant_id)
            REFERENCES platform.tenant_members (user_id, tenant_id)
            ON DELETE SET NULL (owner_user_id),
        CONSTRAINT ck_agent_settings_audience CHECK (
            jsonb_typeof(audience) = 'object' AND audience ->> 'schema' = 'dw.audience/v1'
        ),
        CONSTRAINT ck_agent_settings_row_version CHECK (row_version >= 1)
    )
"""

_STATEMENTS = (
    # The owner's key, on its own side (the artifact's is the primary key).
    "CREATE INDEX ix_agent_settings_tenant_id_owner_user_id"
    " ON studio.agent_settings (tenant_id, owner_user_id)",
    # Written out, not looped: `scripts/verify_invariants.py` reads this text.
    # Tenant-only, like the envelope it sits beside (ADR-0117 decision 3).
    "ALTER TABLE studio.agent_settings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.agent_settings FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_agent_settings ON studio.agent_settings"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    # Yields to a value the statement states (`platform.touch_updated_at`).
    "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON studio.agent_settings"
    " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
)

# What `dw_app` holds beyond the schema's default SELECT (ADR 0100 point 4):
# a row is created and its three settings changed, never deleted by it.
_APP_GRANTS = (
    "GRANT INSERT ON studio.agent_settings TO dw_app;",
    "GRANT UPDATE (audience, owner_user_id, enabled, row_version, updated_at)"
    " ON studio.agent_settings TO dw_app;",
)


def _for_role(role: str, statement: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                {statement}
            END IF;
        END
        $$
        """


def upgrade() -> None:
    # OPS-b: the kind's row beside its registry entry, with a gate.
    op.execute("INSERT INTO studio.artifact_kinds (kind, has_quality_gate) VALUES ('agent', true)")
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    for key, label in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
                " 'dw_studio', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label)
        )
    op.execute(_TABLE)
    for statement in _STATEMENTS:
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))


def downgrade() -> None:
    op.execute("DROP TABLE studio.agent_settings")
    for key, _label in PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
            ).bindparams(k=key)
        )
        op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=key))
    op.execute("DELETE FROM studio.artifact_kinds WHERE kind = 'agent'")
