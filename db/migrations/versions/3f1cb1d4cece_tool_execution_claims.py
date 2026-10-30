"""tool execution claims

Revision ID: 3f1cb1d4cece
Revises: 2997128da6ba
Create Date: 2026-10-30

runtime-hardening ticket 01 (R6.1-R6.3, R6.7-R6.14; ADR-0108 decision 5). A tool
call with an idempotency key claims the key before it looks for a succeeded
call, and an outward call logs that it left before it leaves.

- `platform.tool_execution_claims`: one live claim per `(tenant_id, tool_name,
  idempotency_key)`. A duplicate while the first runs is refused, an expired one
  is taken over by its `claim_token`, and the holder releases only its own
  token. `workspace_id` points at its workspace through the composite key of
  `uq_workspaces_tenant_id_id`, because a foreign key check does not pass
  through RLS and a one-column key would let tenant A's claim name tenant B's
  workspace (R6.8). The policy narrows by tenant only, like
  `platform.tool_executions`: the primary key carries no workspace, so a claim
  must be visible to the same key from any workspace of its tenant.
  `worker_drain` lets the `tool_claims_retention` lane delete expired claims
  across tenants. `dw_app` reads, inserts and deletes, never updates.
- `platform.tool_executions` gains the dispatch log: `status` is CHECKed to
  `succeeded`, `failed`, `dispatched` and `outcome_unknown` (V4.30; an existing
  row with any other value makes the ADD fail, which is the check), and a
  terminal row names the `dispatched` row it closes in `dispatch_id`, so "a
  dispatch with no known outcome" needs no ordering column. At most one
  `succeeded` or `failed` row closes a dispatch; an `outcome_unknown` row before
  it is allowed. `dw_app` loses UPDATE: the table is append-only (DELETE stays
  for offboarding).
"""

from __future__ import annotations

from alembic import op

revision = "3f1cb1d4cece"
down_revision = "2997128da6ba"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires since cfae5f2d4a13: every setting is
# read inside a sub-SELECT, once per statement.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_DRAIN = "((SELECT current_setting('app.worker_drain', true)) = 'on')"


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
        CREATE TABLE platform.tool_execution_claims (
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            tool_name text NOT NULL,
            idempotency_key text NOT NULL,
            run_id uuid NOT NULL,
            claim_token uuid DEFAULT gen_random_uuid() NOT NULL,
            claimed_at timestamp with time zone DEFAULT now() NOT NULL,
            expires_at timestamp with time zone NOT NULL,
            CONSTRAINT pk_tool_execution_claims
                PRIMARY KEY (tenant_id, tool_name, idempotency_key),
            CONSTRAINT fk_tool_execution_claims_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE CASCADE,
            CONSTRAINT fk_tool_execution_claims_tenant_id_workspaces
                FOREIGN KEY (tenant_id, workspace_id)
                REFERENCES platform.workspaces(tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_tool_execution_claims_expires_after_claimed
                CHECK (expires_at > claimed_at)
        )
        """
    )
    # `tenant_id` leads the primary key, so the tenant foreign key needs no index
    # of its own; the composite one does, and the lane reads by age.
    op.execute(
        "CREATE INDEX ix_tool_execution_claims_tenant_id_workspace_id"
        " ON platform.tool_execution_claims (tenant_id, workspace_id)"
    )
    op.execute(
        "CREATE INDEX ix_tool_execution_claims_expires_at"
        " ON platform.tool_execution_claims (expires_at)"
    )
    op.execute("ALTER TABLE platform.tool_execution_claims ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.tool_execution_claims FORCE ROW LEVEL SECURITY")
    # One literal per policy head: `verify_invariants.py` reads this text.
    op.execute(
        "CREATE POLICY tenant_isolation_tool_execution_claims ON platform.tool_execution_claims"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute(
        "CREATE POLICY worker_drain_tool_execution_claims ON platform.tool_execution_claims"
        f" USING ({_DRAIN}) WITH CHECK ({_DRAIN})"
    )
    # The schema's default privileges hand `dw_app` UPDATE as well; a claim is
    # replaced by delete-then-insert under its token, never rewritten.
    op.execute(
        _for_role(
            "dw_app", "REVOKE UPDATE, TRUNCATE ON platform.tool_execution_claims FROM dw_app;"
        )
    )
    op.execute(
        _for_role("dw_agent_ro", "REVOKE ALL ON platform.tool_execution_claims FROM dw_agent_ro;")
    )

    op.execute(
        """
        ALTER TABLE platform.tool_executions
            ADD COLUMN dispatch_id uuid,
            ADD CONSTRAINT ck_tool_executions_status CHECK (
                status IN ('succeeded', 'failed', 'dispatched', 'outcome_unknown')
            ),
            ADD CONSTRAINT ck_tool_executions_dispatch_id
                CHECK (dispatch_id IS NULL OR status <> 'dispatched')
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_tool_executions_dispatch_resolved"
        " ON platform.tool_executions (tenant_id, dispatch_id)"
        " WHERE dispatch_id IS NOT NULL AND status IN ('succeeded', 'failed')"
    )
    # Every claimed call asks whether its key has a dispatch with no known
    # outcome; without this the question scans every row the tenant ever wrote.
    op.execute(
        "CREATE INDEX ix_tool_executions_dispatched"
        " ON platform.tool_executions (tenant_id, tool_name, idempotency_key)"
        " WHERE status = 'dispatched'"
    )
    op.execute(_for_role("dw_app", "REVOKE UPDATE ON platform.tool_executions FROM dw_app;"))


def downgrade() -> None:
    op.execute(_for_role("dw_app", "GRANT UPDATE ON platform.tool_executions TO dw_app;"))
    op.execute("DROP INDEX IF EXISTS platform.ix_tool_executions_dispatched")
    op.execute("DROP INDEX IF EXISTS platform.uq_tool_executions_dispatch_resolved")
    op.execute(
        """
        ALTER TABLE platform.tool_executions
            DROP CONSTRAINT IF EXISTS ck_tool_executions_dispatch_id,
            DROP CONSTRAINT IF EXISTS ck_tool_executions_status,
            DROP COLUMN IF EXISTS dispatch_id
        """
    )
    op.execute("DROP TABLE IF EXISTS platform.tool_execution_claims")
