"""idempotency keys purge function

Revision ID: b248d0664f47
Revises: fd2cd56a8f6e
Create Date: 2026-10-28 09:32:15.596575+00:00

app-standards ticket 04 (R2.8, R2.13, R2.15; ADR-0122 decision 7). The replay
cache of `Idempotency-Key` gets a purge, so a key and its stored body do not
stay for ever (failure-modes #6).

- `platform.purge_expired_idempotency_keys()`: no argument, SECURITY DEFINER,
  deletes every tenant's rows older than the term of
  `configs/policies/retention.d/platform.idempotency_keys.yaml`, read through
  `platform.retention_term_days`, and returns only the count (R2.13): the one
  door across tenants reads no row back, as `platform.prune_notifications()`
  before it, so no drain policy opens the table (R2.12). A missing term raises
  P0002 before anything is deleted (R2.15); there is no default term.
- `dw_app` executes it; the retention lane's purger calls it
  (`SqlIdempotencyKeyRetention`).

`created_at` is when the reservation in force began, so a key taken over late
lives a full term from the take-over (R2.4). The `(created_at)` index of 0002
carries the delete.
"""

from __future__ import annotations

from alembic import op

revision = "b248d0664f47"
down_revision = "fd2cd56a8f6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.purge_expired_idempotency_keys()
        RETURNS integer
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            -- Read first, so a missing term fails even on an empty table.
            cutoff timestamp with time zone := now() - make_interval(
                days => platform.retention_term_days('platform.idempotency_keys')
            );
            removed integer;
        BEGIN
            DELETE FROM platform.idempotency_keys WHERE created_at < cutoff;
            GET DIAGNOSTICS removed = ROW_COUNT;
            RETURN removed;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.purge_expired_idempotency_keys() FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT EXECUTE ON FUNCTION platform.purge_expired_idempotency_keys() TO dw_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.purge_expired_idempotency_keys()")
