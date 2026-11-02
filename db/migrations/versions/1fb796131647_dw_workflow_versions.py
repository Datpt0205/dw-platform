"""dw workflow versions

Revision ID: 1fb796131647
Revises: 100d1de08d37
Create Date: 2026-11-02

wf-ai ticket 03 (R6.4-R6.6, R6.8, R6.10, R6.11, R6.14, R6.16; WAI10-WAI12,
WAI14, WAI16, WAI17).

- `platform.dw_workflow_versions`: a tenant's published version of one DW's
  workflow, append-only. `version` is `<pack semver>+t<seq>`, `seq` counting
  per DW; the content is the draft's as approved, with the hashes the approval
  carried, who wrote it and who approved it. `approval_id` is unique, so a
  decision delivered twice publishes once (R6.14). `dw_app` reads and inserts;
  it updates nothing, and deletes only for the offboarding purge.
- `platform.dw_workflow_drafts.approval_id`: the publish approval a submitted
  draft waits on, so a settlement or a withdrawal acts only on its own.
- `ck_digital_workers_workflow_version` takes a tenant version's pin
  (`1.0.0+t3`) besides a pack's semver.

One workspace policy shape, RESTRICT to the DW like every edge to
`digital_workers`.
"""

from __future__ import annotations

from alembic import op

revision = "1fb796131647"
down_revision = "100d1de08d37"
branch_labels = None
depends_on = None

_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_WORKSPACE = "(workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid))"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"
_NARROWED = f"({_TENANT} AND ({_WORKSPACE} OR {_SCOPE}))"
_SEMVER = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"


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
    op.execute(
        f"""
        CREATE TABLE platform.dw_workflow_versions (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            dw_id uuid NOT NULL,
            key text NOT NULL,
            seq integer NOT NULL,
            version text NOT NULL,
            content jsonb NOT NULL,
            content_sha256 text NOT NULL,
            base_sha256 text NOT NULL,
            author_ids uuid[] NOT NULL,
            approved_by uuid NOT NULL,
            approval_id uuid NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_dw_workflow_versions PRIMARY KEY (id),
            CONSTRAINT uq_dw_workflow_versions_approval_id UNIQUE (approval_id),
            CONSTRAINT uq_dw_workflow_versions_dw_seq UNIQUE (tenant_id, dw_id, seq),
            CONSTRAINT uq_dw_workflow_versions_dw_version UNIQUE (tenant_id, dw_id, version),
            CONSTRAINT fk_dw_workflow_versions_digital_worker
                FOREIGN KEY (tenant_id, workspace_id, dw_id)
                REFERENCES platform.digital_workers(tenant_id, workspace_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_dw_workflow_versions_seq CHECK (seq >= 1),
            CONSTRAINT ck_dw_workflow_versions_version
                CHECK (version ~ '^{_SEMVER}\\+t[1-9][0-9]*$'
                       AND split_part(version, '+t', 2) = seq::text),
            CONSTRAINT ck_dw_workflow_versions_content_sha256
                CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_dw_workflow_versions_base_sha256
                CHECK (base_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_dw_workflow_versions_author_ids CHECK (cardinality(author_ids) >= 1)
        )
        """
    )
    # The foreign key's own side, as every edge (CLAUDE.md, Data model); a
    # resume finds its graph by key, version and content hash under RLS.
    op.execute(
        "CREATE INDEX ix_dw_workflow_versions_digital_worker"
        " ON platform.dw_workflow_versions (tenant_id, workspace_id, dw_id)"
    )
    op.execute(
        "CREATE INDEX ix_dw_workflow_versions_content"
        " ON platform.dw_workflow_versions (tenant_id, key, version, content_sha256)"
    )
    op.execute("ALTER TABLE platform.dw_workflow_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.dw_workflow_versions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_dw_workflow_versions ON platform.dw_workflow_versions"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )
    op.execute(_for_role("dw_app", "REVOKE ALL ON platform.dw_workflow_versions FROM dw_app;"))
    op.execute(
        _for_role(
            "dw_app", "GRANT SELECT, INSERT, DELETE ON platform.dw_workflow_versions TO dw_app;"
        )
    )
    op.execute(
        _for_role("dw_agent_ro", "REVOKE ALL ON platform.dw_workflow_versions FROM dw_agent_ro;")
    )

    op.execute("ALTER TABLE platform.dw_workflow_drafts ADD COLUMN approval_id uuid")
    op.execute(
        "ALTER TABLE platform.dw_workflow_drafts ADD CONSTRAINT ck_dw_workflow_drafts_approval_id"
        " CHECK ((state = 'submitted') = (approval_id IS NOT NULL))"
    )

    op.execute(
        "ALTER TABLE platform.digital_workers DROP CONSTRAINT ck_digital_workers_workflow_version"
    )
    op.execute(
        "ALTER TABLE platform.digital_workers ADD CONSTRAINT ck_digital_workers_workflow_version"
        f" CHECK (workflow_version ~ '^{_SEMVER}(\\+t[1-9][0-9]*)?$')"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE platform.digital_workers DROP CONSTRAINT ck_digital_workers_workflow_version"
    )
    op.execute(
        "ALTER TABLE platform.digital_workers ADD CONSTRAINT ck_digital_workers_workflow_version"
        f" CHECK (workflow_version ~ '^{_SEMVER}$')"
    )
    op.execute(
        "ALTER TABLE platform.dw_workflow_drafts DROP CONSTRAINT ck_dw_workflow_drafts_approval_id"
    )
    op.execute("ALTER TABLE platform.dw_workflow_drafts DROP COLUMN approval_id")
    op.execute("DROP TABLE platform.dw_workflow_versions")
