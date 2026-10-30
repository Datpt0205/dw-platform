"""tool executions refused

Revision ID: f051d26f0610
Revises: cfbd906be98b
Create Date: 2026-10-30

digital-worker ticket 02 (R6.1, R6.2): a call the tool executor refuses at a
Digital Worker's boundary (the DW is not operating, its state cannot be read,
the tool is outside its `allowed_tools`, a scope its principal has lost) is a
row of `platform.tool_executions`, status `refused`, with the reason in
`error`. It carries no idempotency key and no dispatch id: it was refused
before any claim, so it can be neither a success to replay nor a dispatch to
resolve. Any other status, as before, fails the CHECK.
"""

from __future__ import annotations

from alembic import op

revision = "f051d26f0610"
down_revision = "cfbd906be98b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform.tool_executions
            DROP CONSTRAINT ck_tool_executions_status,
            ADD CONSTRAINT ck_tool_executions_status CHECK (
                status IN ('succeeded', 'failed', 'dispatched', 'outcome_unknown', 'refused')
            ),
            ADD CONSTRAINT ck_tool_executions_refused_unkeyed CHECK (
                status <> 'refused' OR (idempotency_key IS NULL AND dispatch_id IS NULL)
            )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform.tool_executions WHERE status = 'refused'")
    op.execute(
        """
        ALTER TABLE platform.tool_executions
            DROP CONSTRAINT IF EXISTS ck_tool_executions_refused_unkeyed,
            DROP CONSTRAINT ck_tool_executions_status,
            ADD CONSTRAINT ck_tool_executions_status CHECK (
                status IN ('succeeded', 'failed', 'dispatched', 'outcome_unknown')
            )
        """
    )
