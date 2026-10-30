"""wf lite definition hash and timers

Revision ID: 16ac88642439
Revises: f051d26f0610
Create Date: 2026-10-30

wf-lite ticket 02 (R6.12, R6.14, R6.15).

- `platform.worker_runs.definition_hash`: the sha256 of the workflow document
  a wf-lite run was started from (the run manifest's column, ADR-0109), apart
  from `release_manifest_ref`, the platform release's. Lowercase hex or NULL
  for a run that is not a workflow's.
- `platform.dw_timer_scopes_due(limit)`, SECURITY DEFINER, the timer lane's one
  read across tenants: the `(tenant_id, workspace_id)` holding a work item in
  `waiting_timer` whose `wake_at` has passed, of an `operating` DW (a paused
  DW's timers stay where they are, R6.15). Ids only; EXECUTE for `dw_app`.
"""

from __future__ import annotations

from alembic import op

revision = "16ac88642439"
down_revision = "f051d26f0610"
branch_labels = None
depends_on = None


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
        ALTER TABLE platform.worker_runs
            ADD COLUMN definition_hash text,
            ADD CONSTRAINT ck_worker_runs_definition_hash
                CHECK (definition_hash IS NULL OR definition_hash ~ '^[0-9a-f]{64}$')
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.dw_timer_scopes_due(p_limit integer)
        RETURNS TABLE (tenant_id uuid, workspace_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
            SELECT DISTINCT w.tenant_id, w.workspace_id
            FROM platform.work_items w
            JOIN platform.digital_workers d ON d.id = w.dw_id
            WHERE w.status = 'waiting_timer' AND w.wake_at <= now()
              AND d.state = 'operating'
            ORDER BY w.tenant_id, w.workspace_id
            LIMIT greatest(p_limit, 0)
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.dw_timer_scopes_due(integer) FROM PUBLIC")
    op.execute(
        _for_role(
            "dw_app", "GRANT EXECUTE ON FUNCTION platform.dw_timer_scopes_due(integer) TO dw_app;"
        )
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform.dw_timer_scopes_due(integer)")
    op.execute(
        """
        ALTER TABLE platform.worker_runs
            DROP CONSTRAINT IF EXISTS ck_worker_runs_definition_hash,
            DROP COLUMN IF EXISTS definition_hash
        """
    )
