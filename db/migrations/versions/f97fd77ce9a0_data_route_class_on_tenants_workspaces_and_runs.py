"""data route class on tenants, workspaces and runs

Revision ID: f97fd77ce9a0
Revises: b735015cca5c
Create Date: 2026-11-05 12:00:00.000000+00:00

compliance-pdpl ticket 03 (R2.1, R2.4, R2.7, R2.8; ADR-0123 decisions 3, 6).
Columns only, no table and no trigger (OPS-b): the decision is
`dw_kernel.residency`'s, and the migration only holds the three values.

- `platform.tenants.data_route_class`: NOT NULL DEFAULT `vn_only`, the class
  every tenant starts at and keeps in W1, where no loosening path exists.
- `platform.workspaces.data_route_class`: NULL inherits the tenant's; a value
  only tightens it, which the admin route checks (422 otherwise).
- `platform.worker_runs.data_route_class`: the effective class pinned when the
  run is admitted; a resume reads it back. NULL is a run admitted before this
  revision, which the runtime reads as `vn_only`.

Each CHECK writes the three classes as literals, strictest first, the order of
`dw_kernel.residency.ROUTE_CLASSES`; `test_residency_catalog.py` reads them back
from `pg_constraint`. The run table's CHECK is added NOT VALID and validated
after, so the scan of existing rows does not hold the table's write lock.
No grant changes: the table grants already cover a new column, and the RLS
policies of the three tables are unchanged.
"""

from __future__ import annotations

from alembic import op

revision = "f97fd77ce9a0"
down_revision = "b735015cca5c"
branch_labels = None
depends_on = None

_CLASSES = "('vn_only', 'cross_border_minimised', 'cross_border_full')"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platform.tenants"
        " ADD COLUMN data_route_class text NOT NULL DEFAULT 'vn_only',"
        f" ADD CONSTRAINT ck_tenants_data_route_class CHECK (data_route_class IN {_CLASSES})"
    )
    op.execute(
        "ALTER TABLE platform.workspaces"
        " ADD COLUMN data_route_class text,"
        f" ADD CONSTRAINT ck_workspaces_data_route_class CHECK (data_route_class IN {_CLASSES})"
    )
    op.execute("ALTER TABLE platform.worker_runs ADD COLUMN data_route_class text")
    op.execute(
        "ALTER TABLE platform.worker_runs ADD CONSTRAINT ck_worker_runs_data_route_class"
        f" CHECK (data_route_class IN {_CLASSES}) NOT VALID"
    )
    op.execute(
        "ALTER TABLE platform.worker_runs VALIDATE CONSTRAINT ck_worker_runs_data_route_class"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE platform.worker_runs DROP COLUMN data_route_class")
    op.execute("ALTER TABLE platform.workspaces DROP COLUMN data_route_class")
    op.execute("ALTER TABLE platform.tenants DROP COLUMN data_route_class")
