"""run status checks and outbox backoff

Revision ID: 65443fe9fd9a
Revises: c478ca7b6ed1
Create Date: 2026-11-02

runtime-hardening ticket 03 (R9.3, R10.1-R10.3; RH26-RH28):

- PostgreSQL refuses a status no code knows: `ck_worker_runs_status` (the
  statuses written today, `waiting_timer` of wf-lite among them, and the four
  Studio's queue will write, ADR-0113), `ck_approval_requests_status`
  (`expired` included, ADR-0112) and `ck_approval_decisions_outcome`. Each
  set is its enum's (`RunStatus`, `ApprovalStatus`, `DecisionOutcome`), held
  to it by a catalog test. Existing rows are checked first: a value outside
  a set stops the migration and names it, nothing is rewritten to fit.
- `platform.outbox_events.available_at`: when a failed event may be tried
  again (an exponential backoff with jitter, set by PostgreSQL's clock), and
  `dead_at`: the one owner of "this event will not be delivered", so the
  backlog and the dead-letter gauge count disjoint rows. The claim's partial
  index covers the rows it can still take, in `occurred_at` order with
  `available_at` beside it; a second one counts the dead.
"""

from __future__ import annotations

from alembic import op

revision = "65443fe9fd9a"
down_revision = "c478ca7b6ed1"
branch_labels = None
depends_on = None

_RUN_STATUSES = (
    "pending",
    "running",
    "waiting_approval",
    "waiting_timer",
    "completed",
    "failed",
    "cancelled",
    "queued",
    "waiting",
    "blocked",
    "dead_lettered",
)
_APPROVAL_STATUSES = ("pending", "approved", "rejected", "cancelled", "expired")
_OUTCOMES = ("approved", "rejected")

_CHECKS = (
    ("platform.worker_runs", "ck_worker_runs_status", "status", _RUN_STATUSES),
    ("platform.approval_requests", "ck_approval_requests_status", "status", _APPROVAL_STATUSES),
    ("platform.approval_decisions", "ck_approval_decisions_outcome", "outcome", _OUTCOMES),
)


def _set(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    for table, name, column, values in _CHECKS:
        # Names any value outside the set before the CHECK would only say
        # that one row fails.
        op.execute(
            f"""
            DO $$
            DECLARE stray text;
            BEGIN
                SELECT string_agg(DISTINCT {column}, ', ') INTO stray
                FROM {table} WHERE {column} NOT IN ({_set(values)});
                IF stray IS NOT NULL THEN
                    RAISE EXCEPTION '{table}.{column} holds values outside the set: %', stray;
                END IF;
            END
            $$
            """
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({column} IN ({_set(values)}))"
        )

    op.execute(
        "ALTER TABLE platform.outbox_events"
        " ADD COLUMN available_at timestamp with time zone DEFAULT now() NOT NULL,"
        " ADD COLUMN dead_at timestamp with time zone"
    )
    op.execute("DROP INDEX platform.ix_outbox_events_unprocessed")
    op.execute(
        "CREATE INDEX ix_outbox_events_claimable ON platform.outbox_events"
        " (occurred_at, available_at) WHERE processed_at IS NULL AND dead_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_outbox_events_dead ON platform.outbox_events (dead_at)"
        " WHERE processed_at IS NULL AND dead_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX platform.ix_outbox_events_dead")
    op.execute("DROP INDEX platform.ix_outbox_events_claimable")
    op.execute(
        "CREATE INDEX ix_outbox_events_unprocessed ON platform.outbox_events (occurred_at)"
        " WHERE processed_at IS NULL"
    )
    op.execute("ALTER TABLE platform.outbox_events DROP COLUMN dead_at, DROP COLUMN available_at")
    for table, name, _, _ in reversed(_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
