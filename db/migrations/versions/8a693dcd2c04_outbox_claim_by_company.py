"""outbox claim by company

Revision ID: 8a693dcd2c04
Revises: 25e271c4c20a
Create Date: 2026-11-06 06:45:00.000000+00:00

runtime-hardening ticket 04 (R10.6, G9, RH37). The outbox claim takes turns
between companies: it finds the companies with an undelivered row by a skip
scan, keeps those with a due row of a type the process delivers, and takes
each one's oldest due rows. `ix_outbox_events_due_by_tenant` serves all three:
`(tenant_id, available_at)` with `event_type`, `occurred_at` and `attempts`
carried, partial on `processed_at IS NULL AND dead_at IS NULL`, the claim's
own predicate word for word (the planner uses a partial index only when the
query states its predicate). `ix_outbox_events_claimable` stays: `backlog()`
reads `min(occurred_at)` across companies through it.

No table, column, policy or grant changes, so the RLS, privilege and
offboarding coverage hold unchanged; offboarding deletes outbox rows as before
and the index follows them. Not `CONCURRENTLY` (the revision runs in a
transaction): the table is small today, and a deployment with a large backlog
locks outbox writes while the index builds during the upgrade.
"""

from __future__ import annotations

from alembic import op

revision = "8a693dcd2c04"
down_revision = "25e271c4c20a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_outbox_events_due_by_tenant ON platform.outbox_events"
        " (tenant_id, available_at) INCLUDE (event_type, occurred_at, attempts)"
        " WHERE processed_at IS NULL AND dead_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX platform.ix_outbox_events_due_by_tenant")
