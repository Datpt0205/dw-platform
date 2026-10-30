"""dw autonomy raise pending unique

Revision ID: 92abd4932780
Revises: d55d55e34e7f
Create Date: 2026-10-30

One pending `dw.autonomy.raise` per Digital Worker decision class
(digital-worker R8.4): a partial unique index on the two payload fields the
raise names, over pending rows of that type only. Two owners raising at once
both pass the service's own look, and the index lets one approval in; the
repository reads the other's refusal by this name as 409 `raise_pending`.
A decided raise leaves the index, so the next one may open.
"""

from __future__ import annotations

from alembic import op

revision = "92abd4932780"
down_revision = "d55d55e34e7f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_approval_requests_dw_autonomy_raise_pending"
        " ON platform.approval_requests ((payload->>'dw_id'), (payload->>'decision_class'))"
        " WHERE approval_type = 'dw.autonomy.raise' AND status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX platform.uq_approval_requests_dw_autonomy_raise_pending")
