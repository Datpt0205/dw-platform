"""egress allowed hosts

Revision ID: 20bb9a2210cf
Revises: 70d8a4564454
Create Date: 2026-11-04 02:22:16.056442+00:00

connections-and-vault ticket 03 (spec R3.7-R3.12, R3.18, R3.19, R3.21; CV19,
CV22, CV30; ADR-0115 decision 6). The company's Allowed hosts: where every
tenant-directed call that is not a catalogue connector's may go.

- `platform.egress_allowed_hosts`: one row per host pattern a second person
  approved. Its `id` is the id of the `egress.allowed_host` approval that added
  it, so the decision's handler inserts with `ON CONFLICT DO NOTHING` and a
  replayed decision adds nothing, not even after the row was removed. A removal
  stamps `removed_at` and `removed_by` (both or neither) and the row stays;
  one live row per (pattern, purpose) by the partial UNIQUE
  `uq_egress_allowed_hosts_live`. The pattern is held by CHECK even against a
  direct write: lower-case letters, digits, dots and hyphens after an optional
  `*.`, at most 253 characters, never an IPv4 literal (an IPv6 one has a
  colon). The public suffix rule is the API's (the pinned list is code).
  Tenant-wide on purpose: one row opens a destination for every workspace of
  the company (D1); the owning workspace is the approval's, held by the
  RESTRICT composite key. `created_by` is who asked; who approved is in the
  `egress.allowlist.added` audit row.
- `dw_app`: SELECT, INSERT, UPDATE of `removed_at` and `removed_by`, and
  DELETE, which only the offboarding lane uses; no route deletes a row.
- `integrations.admin` joins the permission catalogue: a tenant-depth key,
  `elevated`, grantable by the tenant (tenant-rbac/01, /02).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20bb9a2210cf"
down_revision = "70d8a4564454"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"

_TABLE = r"""
    CREATE TABLE platform.egress_allowed_hosts (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        owning_workspace_id uuid NOT NULL,
        host_pattern text NOT NULL,
        ports integer[] DEFAULT '{443}' NOT NULL,
        purpose text NOT NULL,
        note text,
        created_by uuid NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        removed_at timestamp with time zone,
        removed_by uuid,
        CONSTRAINT pk_egress_allowed_hosts PRIMARY KEY (id),
        CONSTRAINT fk_egress_allowed_hosts_tenant_id_tenants
            FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id) ON DELETE CASCADE,
        CONSTRAINT fk_egress_allowed_hosts_owning_workspace_id_workspaces
            FOREIGN KEY (owning_workspace_id, tenant_id)
            REFERENCES platform.workspaces (id, tenant_id) ON DELETE RESTRICT,
        CONSTRAINT ck_egress_allowed_hosts_host_pattern CHECK (
            host_pattern ~ '^(\*\.)?[a-z0-9.-]+$'
            AND char_length(host_pattern) <= 253
            AND host_pattern !~ '^(\*\.)?[0-9.]+$'
        ),
        CONSTRAINT ck_egress_allowed_hosts_ports CHECK (
            cardinality(ports) BETWEEN 1 AND 16
            AND array_position(ports, NULL) IS NULL
            AND 0 < ALL (ports)
            AND 65536 > ALL (ports)
        ),
        CONSTRAINT ck_egress_allowed_hosts_purpose
            CHECK (purpose IN ('http_tool', 'mcp', 'webhook', 'model', 'any')),
        CONSTRAINT ck_egress_allowed_hosts_note CHECK (char_length(note) <= 500),
        CONSTRAINT ck_egress_allowed_hosts_removed
            CHECK ((removed_at IS NULL) = (removed_by IS NULL))
    )
"""

_INDEXES = (
    # The composite key's own index.
    "CREATE INDEX ix_egress_allowed_hosts_tenant_id_owning_workspace_id"
    " ON platform.egress_allowed_hosts (tenant_id, owning_workspace_id)",
    # The order `GET /api/v1/egress/allowed-hosts` pages in, led by the column
    # RLS supplies; also the index of the key to the tenant.
    "CREATE INDEX ix_egress_allowed_hosts_tenant_id_created_at_id"
    " ON platform.egress_allowed_hosts (tenant_id, created_at DESC, id DESC)",
    # One live row per pattern and purpose: a second approval of the same
    # pattern adds nothing (the handler's ON CONFLICT DO NOTHING).
    "CREATE UNIQUE INDEX uq_egress_allowed_hosts_live"
    " ON platform.egress_allowed_hosts (tenant_id, host_pattern, purpose)"
    " WHERE removed_at IS NULL",
)

_RLS = (
    "ALTER TABLE platform.egress_allowed_hosts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.egress_allowed_hosts FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_egress_allowed_hosts ON platform.egress_allowed_hosts"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# `0001_platform_grants.sql`'s default privileges hand `dw_app` SELECT, INSERT,
# UPDATE and DELETE on every new table of `platform`; these narrow UPDATE.
_APP_GRANTS = (
    "REVOKE UPDATE ON platform.egress_allowed_hosts FROM dw_app;",
    "GRANT SELECT, INSERT, DELETE ON platform.egress_allowed_hosts TO dw_app;",
    "GRANT UPDATE (removed_at, removed_by) ON platform.egress_allowed_hosts TO dw_app;",
)

_AGENT_RO_REVOKES = ("REVOKE ALL ON platform.egress_allowed_hosts FROM dw_agent_ro;",)

INTEGRATIONS_ADMIN = "integrations.admin"


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
    op.execute(_TABLE)
    for statement in (*_INDEXES, *_RLS):
        op.execute(statement)
    for statement in _APP_GRANTS:
        op.execute(_for_role("dw_app", statement))
    for statement in _AGENT_RO_REVOKES:
        op.execute(_for_role("dw_agent_ro", statement))
    # A tenant-depth key: one row opens a destination for every workspace.
    op.execute(
        sa.text(
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'integrations', :l, 'tenant', 'elevated', 'active', NULL,"
            " 'dw_platform', true)"
            " ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=INTEGRATIONS_ADMIN, l="Quản trị máy chủ được phép gọi ra")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
        ).bindparams(k=INTEGRATIONS_ADMIN)
    )
    op.execute(
        sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=INTEGRATIONS_ADMIN)
    )
    op.execute("DROP TABLE IF EXISTS platform.egress_allowed_hosts")
