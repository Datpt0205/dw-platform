"""run mode and simulated tool calls

Revision ID: c478ca7b6ed1
Revises: ebb17244abc6
Create Date: 2026-11-02

tenant-config ticket 03 (R4.1, R5.1; TC9, TC11; ADR-0111 decisions 1-3), its
steps 3 and 7 in one revision:

- `platform.worker_runs.run_mode`: the mode a run runs in, set by the server
  where it starts and read back where it resumes. Every run before this one
  acted on the world, so the backfill is `live`; then NOT NULL and a CHECK,
  and no DEFAULT: a run started without a mode is a bug to refuse, not one
  to run as some value.
- `platform.tool_executions.status` takes `simulated`, a call the executor
  answered with a sample outside `live`; the set keeps every value written
  today (`dispatched` and `outcome_unknown` of the dispatch log, `refused` of
  the DW boundary) and `ck_tool_executions_refused_unkeyed` stays.
"""

from __future__ import annotations

from alembic import op

revision = "c478ca7b6ed1"
down_revision = "ebb17244abc6"
branch_labels = None
depends_on = None

_STATUSES = "'succeeded', 'failed', 'dispatched', 'outcome_unknown', 'refused'"


def upgrade() -> None:
    op.execute("ALTER TABLE platform.worker_runs ADD COLUMN run_mode text")
    op.execute("UPDATE platform.worker_runs SET run_mode = 'live' WHERE run_mode IS NULL")
    op.execute("ALTER TABLE platform.worker_runs ALTER COLUMN run_mode SET NOT NULL")
    op.execute(
        "ALTER TABLE platform.worker_runs ADD CONSTRAINT ck_worker_runs_run_mode"
        " CHECK (run_mode IN ('live', 'test', 'simulate'))"
    )
    # Stops with the CHECK's own error if any row holds a value outside the
    # new set: nothing is rewritten to make it fit.
    op.execute(
        f"""
        ALTER TABLE platform.tool_executions
            DROP CONSTRAINT ck_tool_executions_status,
            ADD CONSTRAINT ck_tool_executions_status CHECK (
                status IN ({_STATUSES}, 'simulated')
            )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform.tool_executions WHERE status = 'simulated'")
    op.execute(
        f"""
        ALTER TABLE platform.tool_executions
            DROP CONSTRAINT ck_tool_executions_status,
            ADD CONSTRAINT ck_tool_executions_status CHECK (status IN ({_STATUSES}))
        """
    )
    op.execute("ALTER TABLE platform.worker_runs DROP CONSTRAINT ck_worker_runs_run_mode")
    op.execute("ALTER TABLE platform.worker_runs DROP COLUMN run_mode")
