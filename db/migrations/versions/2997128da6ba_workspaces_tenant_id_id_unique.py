"""workspaces tenant id id unique

Revision ID: 2997128da6ba
Revises: cfae5f2d4a13
Create Date: 2026-10-29

org-and-principals ticket 01 (R1.1, OP1). A table whose rows belong to one
workspace points at it with a composite foreign key `(tenant_id, workspace_id)`
so a row of tenant B can never name a workspace of tenant A; the target of that
key is this constraint. It changes no data. Its name follows
`dw_kernel.naming.NAMING_CONVENTION` (`uq_%(table_name)s_%(column_0_N_name)s`), and
no other revision creates it.
"""

from __future__ import annotations

from alembic import op

revision = "2997128da6ba"
down_revision = "cfae5f2d4a13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platform.workspaces"
        " ADD CONSTRAINT uq_workspaces_tenant_id_id UNIQUE (tenant_id, id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE platform.workspaces DROP CONSTRAINT uq_workspaces_tenant_id_id")
