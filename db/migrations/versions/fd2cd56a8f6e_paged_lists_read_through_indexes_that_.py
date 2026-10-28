"""paged lists read through indexes that carry them

Revision ID: fd2cd56a8f6e
Revises: 3c54129c940c
Create Date: 2026-10-28 07:30:32.368611+00:00

app-standards ticket 03 (R6.1, R6.2; ADR-0122 decision 6). The plan-shape check
(`tests/support/plan_shape.py`) planned every paged statement under `dw_app`
with sequential scans off, and these are the indexes it found missing:

- `ix_feedback_page (tenant_id, created_at DESC, id DESC)` replaces
  `ix_feedback_tenant_created (tenant_id, created_at)`: the inbox orders by
  `created_at DESC, id DESC`, and without `id` in the index every page sorted
  the tenant's whole inbox.
- `ix_audit_events_by_run (tenant_id, run_id, workspace_id, occurred_at)` on
  the partitioned parent: the run's audit list filters by run and workspace,
  and no audit index carried `run_id`. The one run index of the platform;
  ADR-0122 decision 6 replaced the `ix_audit_events_run` telemetry had planned.
- `ix_documents_workspace_page` and `ix_documents_global_page`: the document
  listing reads its two disjoint arms (the workspace's own documents, and the
  global ones every tenant may read) each in page order. RLS on
  `knowledge.documents` is `tenant OR global`, which narrows no index by
  tenant, so the own arm names `tenant_id` and its index leads with it. The
  global arm's rows belong to whichever tenant published them, so its index
  holds only `scope = 'global'` rows and cannot lead with a tenant; the check
  lists it as the one exempt index, with that reason.

Locking. The audit index is built without blocking audited writes: an invalid
index `ON ONLY` the parent, then `CREATE INDEX CONCURRENTLY` on each partition
outside alembic's transaction, attached one by one; the parent's index becomes
valid when the last partition is attached, and `ensure_time_partitions` gives
it to every partition made after. The feedback and document indexes are plain
`CREATE INDEX`, each a SHARE lock on a table no deployed environment has
populated yet (`6d4aed20ccf2`'s note applies).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "fd2cd56a8f6e"
down_revision = "3c54129c940c"
branch_labels = None
depends_on = None

_RUN_INDEX = "ix_audit_events_by_run"
_RUN_COLUMNS = "(tenant_id, run_id, workspace_id, occurred_at)"


def _audit_partitions() -> list[str]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
            " WHERE i.inhparent = 'platform.audit_events'::regclass ORDER BY c.relname"
        )
    )
    return [row[0] for row in rows]


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_feedback_page ON platform.feedback (tenant_id, created_at DESC, id DESC)"
    )
    op.execute("DROP INDEX platform.ix_feedback_tenant_created")

    op.execute(
        "CREATE INDEX ix_documents_workspace_page ON knowledge.documents"
        " (tenant_id, workspace_id, status, created_at DESC, id DESC) WHERE scope <> 'global'"
    )
    op.execute(
        "CREATE INDEX ix_documents_global_page ON knowledge.documents"
        " (status, created_at DESC, id DESC) WHERE scope = 'global'"
    )

    op.execute(f"CREATE INDEX {_RUN_INDEX} ON ONLY platform.audit_events {_RUN_COLUMNS}")
    partitions = _audit_partitions()
    with op.get_context().autocommit_block():
        for partition in partitions:
            index = f"{partition}_by_run_idx"
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index}"
                f" ON platform.{partition} {_RUN_COLUMNS}"
            )
            op.execute(f"ALTER INDEX platform.{_RUN_INDEX} ATTACH PARTITION platform.{index}")


def downgrade() -> None:
    # Dropping the parent's index drops every partition's attached one.
    op.execute(f"DROP INDEX platform.{_RUN_INDEX}")
    op.execute("DROP INDEX knowledge.ix_documents_global_page")
    op.execute("DROP INDEX knowledge.ix_documents_workspace_page")
    op.execute(
        "CREATE INDEX ix_feedback_tenant_created ON platform.feedback (tenant_id, created_at)"
    )
    op.execute("DROP INDEX platform.ix_feedback_page")
