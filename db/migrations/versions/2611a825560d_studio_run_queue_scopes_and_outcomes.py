"""studio run queue scopes and outcomes

Revision ID: 2611a825560d
Revises: cbf2ba4fb6e9
Create Date: 2026-11-05 15:00:00.000000+00:00

workflow-engine ticket 04 (R5.2, R5.3, R5.6, R5.7, R5.23, R5.24; WE3, WE4,
WE23; ADR-0113 decisions 2, 3; H-14).

- `platform.worker_runs.outcomes text[] NOT NULL DEFAULT '{}'`: the names of
  the document's `outcomes[]` a Studio run reached, written in the
  transaction that ends it. No CHECK on the names: they come only from the
  pinned document, whose validator checked them (H-14). The column is the
  table's, which `dw_app` already writes: no grant changes.
- Three SECURITY DEFINER reads, the only ones that cross tenants for the
  `studio_runs` and `studio_run_reaper` lanes, each returning tenant ids and
  nothing else, `search_path` fixed, EXECUTE revoked from PUBLIC and granted
  to `dw_app` (the pattern of `platform.channel_delivery_scopes_due`); every
  claim, requeue and cancel runs outside them, under the tenant's RLS:
  - `studio_run_scopes_due(p_limit)`: tenants with a due `queued` Studio run,
    the earliest due first, then by id, so no tenant starves when more have
    work than the lane takes (R5.2);
  - `studio_run_orphans_due(p_limit)`: tenants with a `running` Studio run
    whose claim lapsed (R5.6);
  - `studio_run_deadlines_due(p_limit, p_unclaimed_after)`: tenants with an
    unfinished Studio run past `deadline_at` that no live claim holds, or a
    `queued` one never admitted (`deadline_at` NULL) older than
    `p_unclaimed_after` (R5.23). The age is the lane's one constant
    (`RUN_DEADLINE`), passed in, so the database holds no second copy of it.
- Indexes for the three reads: due `queued` runs by `available_at`, running
  Studio runs by `lease_until`, and never-admitted `queued` runs by
  `(tenant_id, created_at)`; the deadline index of `703be798341f` serves the
  rest.
"""

from __future__ import annotations

from alembic import op

revision = "2611a825560d"
down_revision = "cbf2ba4fb6e9"
branch_labels = None
depends_on = None

_STUDIO = "r.artifact_kind IS NOT NULL"
_FUNCTIONS = (
    "platform.studio_run_scopes_due(integer)",
    "platform.studio_run_orphans_due(integer)",
    "platform.studio_run_deadlines_due(integer, interval)",
)


def _for_role(role: str, statement: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                {statement}
            END IF;
        END
        $$
        """


def upgrade() -> None:
    op.execute("ALTER TABLE platform.worker_runs ADD COLUMN outcomes text[] DEFAULT '{}' NOT NULL")
    op.execute(
        "CREATE INDEX ix_worker_runs_available_at_queued ON platform.worker_runs"
        " (available_at, tenant_id) WHERE status = 'queued' AND artifact_kind IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_worker_runs_lease_until_running ON platform.worker_runs"
        " (lease_until, tenant_id) WHERE status = 'running' AND artifact_kind IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_worker_runs_tenant_id_created_at_unadmitted ON platform.worker_runs"
        " (tenant_id, created_at) WHERE status = 'queued' AND deadline_at IS NULL"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.studio_run_scopes_due(p_limit integer)
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
            SELECT r.tenant_id
            FROM platform.worker_runs r
            WHERE r.status = 'queued' AND {_STUDIO} AND r.available_at <= now()
            GROUP BY r.tenant_id
            ORDER BY min(r.available_at), r.tenant_id
            LIMIT greatest(p_limit, 0)
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.studio_run_orphans_due(p_limit integer)
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
            SELECT r.tenant_id
            FROM platform.worker_runs r
            WHERE r.status = 'running' AND {_STUDIO} AND r.lease_until < now()
            GROUP BY r.tenant_id
            ORDER BY min(r.lease_until), r.tenant_id
            LIMIT greatest(p_limit, 0)
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.studio_run_deadlines_due(
            p_limit integer, p_unclaimed_after interval
        )
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
            SELECT DISTINCT r.tenant_id
            FROM platform.worker_runs r
            WHERE {_STUDIO}
              AND (
                (r.status IN ('queued', 'running', 'waiting', 'blocked')
                 AND r.deadline_at <= now()
                 AND (r.lease_until IS NULL OR r.lease_until < now()))
                OR (r.status = 'queued' AND r.deadline_at IS NULL
                    AND r.created_at <= now() - p_unclaimed_after)
              )
            ORDER BY r.tenant_id
            LIMIT greatest(p_limit, 0)
        $$
        """
    )
    for function in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))


def downgrade() -> None:
    for function in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP INDEX IF EXISTS platform.ix_worker_runs_tenant_id_created_at_unadmitted")
    op.execute("DROP INDEX IF EXISTS platform.ix_worker_runs_lease_until_running")
    op.execute("DROP INDEX IF EXISTS platform.ix_worker_runs_available_at_queued")
    op.execute("ALTER TABLE platform.worker_runs DROP COLUMN IF EXISTS outcomes")
