"""dw workflow drafts

Revision ID: 100d1de08d37
Revises: 92abd4932780
Create Date: 2026-11-02

wf-ai ticket 02 (R6.1, R6.2, R6.7, R6.9, R6.13; WAI9, WAI13, WAI15).

- `platform.dw_workflow_drafts`: one draft per Digital Worker, the document
  rebuilt by the server from the DW's pin and checked before it is stored,
  its hash, the hash of the base it was made from, who saved it last and
  everyone who saved it since the last publish (none of them may decide its
  publication, R6.4). `submitted` is ticket 03's.
- `platform.dw_workflow_simulations`: the last simulation of a DW's draft,
  keyed by the content hash it ran on; a new one replaces it.

Both under the one workspace policy shape, reaching their DW through the
composite key that carries `tenant_id` (a foreign key does not pass through
RLS), RESTRICT like every edge to `digital_workers`, so the offboarding purge
orders them from the catalog. `dw_app` reads, writes and (for offboarding)
deletes; `dw_agent_ro` nothing.
"""

from __future__ import annotations

from alembic import op

revision = "100d1de08d37"
down_revision = "92abd4932780"
branch_labels = None
depends_on = None

_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_WORKSPACE = "(workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid))"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"
_NARROWED = f"({_TENANT} AND ({_WORKSPACE} OR {_SCOPE}))"
_TABLES = ("dw_workflow_drafts", "dw_workflow_simulations")


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
        """
        CREATE TABLE platform.dw_workflow_drafts (
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            dw_id uuid NOT NULL,
            content jsonb NOT NULL,
            content_sha256 text NOT NULL,
            base_sha256 text NOT NULL,
            saved_by uuid NOT NULL,
            author_ids uuid[] NOT NULL,
            state text DEFAULT 'draft' NOT NULL,
            reason text,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_dw_workflow_drafts PRIMARY KEY (tenant_id, dw_id),
            CONSTRAINT fk_dw_workflow_drafts_digital_worker
                FOREIGN KEY (tenant_id, workspace_id, dw_id)
                REFERENCES platform.digital_workers(tenant_id, workspace_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_dw_workflow_drafts_content_sha256
                CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_dw_workflow_drafts_base_sha256
                CHECK (base_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_dw_workflow_drafts_author_ids
                CHECK (cardinality(author_ids) >= 1 AND saved_by = ANY (author_ids)),
            CONSTRAINT ck_dw_workflow_drafts_state CHECK (state IN ('draft', 'submitted')),
            CONSTRAINT ck_dw_workflow_drafts_reason
                CHECK (reason IS NULL OR reason IN ('base_changed', 'content_changed'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform.dw_workflow_simulations (
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            dw_id uuid NOT NULL,
            content_sha256 text NOT NULL,
            outcome text NOT NULL,
            trail jsonb NOT NULL,
            tool_calls jsonb NOT NULL,
            failed_step text,
            error text,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_dw_workflow_simulations PRIMARY KEY (tenant_id, dw_id),
            CONSTRAINT fk_dw_workflow_simulations_digital_worker
                FOREIGN KEY (tenant_id, workspace_id, dw_id)
                REFERENCES platform.digital_workers(tenant_id, workspace_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_dw_workflow_simulations_content_sha256
                CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_dw_workflow_simulations_outcome CHECK (outcome IN ('passed', 'failed')),
            CONSTRAINT ck_dw_workflow_simulations_failed
                CHECK ((outcome = 'failed') = (failed_step IS NOT NULL))
        )
        """
    )
    # The foreign key's own side, as every edge (CLAUDE.md, Data model). The
    # statements are written out per table: `verify_invariants.py` reads them.
    op.execute(
        "CREATE INDEX ix_dw_workflow_drafts_digital_worker"
        " ON platform.dw_workflow_drafts (tenant_id, workspace_id, dw_id)"
    )
    op.execute(
        "CREATE INDEX ix_dw_workflow_simulations_digital_worker"
        " ON platform.dw_workflow_simulations (tenant_id, workspace_id, dw_id)"
    )
    op.execute("ALTER TABLE platform.dw_workflow_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.dw_workflow_drafts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_dw_workflow_drafts ON platform.dw_workflow_drafts"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )
    op.execute("ALTER TABLE platform.dw_workflow_simulations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.dw_workflow_simulations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_dw_simulations ON platform.dw_workflow_simulations"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )
    for table in _TABLES:
        op.execute(_for_role("dw_app", f"REVOKE TRUNCATE ON platform.{table} FROM dw_app;"))
        op.execute(
            _for_role(
                "dw_app", f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.{table} TO dw_app;"
            )
        )
        op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON platform.{table} FROM dw_agent_ro;"))
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.dw_workflow_drafts"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE platform.{table}")
