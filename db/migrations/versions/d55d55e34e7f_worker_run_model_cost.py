"""worker run model cost

Revision ID: d55d55e34e7f
Revises: cb43fb6e860b
Create Date: 2026-10-30

`platform.worker_runs.model_cost_usd` (digital-worker R7.3): what a run's model
calls cost, added by every call (`RunCostRecorder`), read by a DW's scorecard.
`numeric(12,6)`, never negative, 0 for a run that called no model. `dw_app`
holds UPDATE on the whole table, so the new column needs no grant of its own.
"""

from __future__ import annotations

from alembic import op

revision = "d55d55e34e7f"
down_revision = "cb43fb6e860b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platform.worker_runs"
        " ADD COLUMN model_cost_usd numeric(12, 6) DEFAULT 0 NOT NULL"
    )
    op.execute(
        "ALTER TABLE platform.worker_runs ADD CONSTRAINT ck_worker_runs_model_cost_usd"
        " CHECK (model_cost_usd >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE platform.worker_runs DROP CONSTRAINT ck_worker_runs_model_cost_usd")
    op.execute("ALTER TABLE platform.worker_runs DROP COLUMN model_cost_usd")
