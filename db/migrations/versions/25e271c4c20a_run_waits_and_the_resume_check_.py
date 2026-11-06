"""run waits and the resume check permission

Revision ID: 25e271c4c20a
Revises: cae9cc86159c
Create Date: 2026-11-06 04:59:54.622124+00:00

workflow-engine ticket 05 (R6.1, R6.6, R6.13, R6.15, R6.39, R6.40; WE11, WE22,
WE53, WE54; ADR-0113 decisions 3, 4).

- `platform.run_waits`: one row per point a Studio run waits at, written by
  `RunWaitPort.open` (`dw_agent_runtime.adapters.run_waits`), the one owner of
  the row and of its id, `wait:<node_id>:<iteration_path>:<n>`. Every W1 kind
  is in `ck_run_waits_kind` from here, and `detail` (written once, at open) is
  this table's, so tickets 07, 08 and 09 each write their kind without one of
  them making the constraint again. The run's key is composite, `(tenant_id,
  run_id)` to `uq_worker_runs_tenant_id_id`, so a row of tenant A never names
  a run of tenant B (R6.15), and CASCADEs, so the offboarding lane's delete of
  `platform.worker_runs` takes the waits with it; `uq_run_waits_tenant_id_run_
  id_interrupt_id` leads with the key's two columns and is its index, and is
  what workflow-nodes/06's `studio.step_approvals` points to. At most one
  `open` row per `(run, node, iteration)` (`uq_run_waits_tenant_id_run_id_node_
  id_iteration_path_open`), so a step run again after a crash meets its own
  row instead of opening a second. Tenant-wide (DO-01): its workspace is the
  run's.
- `platform.guard_run_wait_transition()`: a row is born `open`, moves `open`
  -> `resolved` or `cancelled` and `resolved` -> `consumed`, and its
  `resolution` and `resolved_at`, once written, and everything it was opened
  with never change (R6.40); `ck_run_waits_resolved` holds a resolution on
  exactly the `resolved` and `consumed` rows.
- `platform.cancel_run_waits()`: AFTER UPDATE OF `status` on
  `platform.worker_runs`, a run that ends (`completed`, `failed`, `cancelled`,
  `dead_lettered`), by whatever path, has every `open` wait `cancelled` in the
  same transaction (R6.13). SECURITY DEFINER of the migrator, touching only
  the rows of `NEW.tenant_id` and `NEW.id`, so a cross-tenant lane with no
  `app.tenant_id` does not cancel zero rows under FORCE RLS.
- `dw_app` holds SELECT, INSERT and UPDATE of `status`, `resolved_at` and
  `resolution`, no DELETE; `dw_agent_ro` nothing.
- The permission `studio.workflows.resume_check`, the key of
  `POST /api/v1/runs/{run_id}/resume-check` (R6.39): workspace depth (a run
  belongs to its workspace), `standard` risk, `active`, owned by `dw_studio`,
  `tenant_grantable` (tenant-rbac/01, /02's classes).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "25e271c4c20a"
down_revision = "cae9cc86159c"
branch_labels = None
depends_on = None

PERMISSION = "studio.workflows.resume_check"
PERMISSION_LABEL = "Kiểm lại một lượt chạy bị chặn khi tiếp tục và xếp lại nó"

_FINISHED = "'completed', 'failed', 'cancelled', 'dead_lettered'"

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"

_TABLE = """
    CREATE TABLE platform.run_waits (
        tenant_id uuid NOT NULL,
        id uuid NOT NULL,
        run_id uuid NOT NULL,
        interrupt_id text NOT NULL,
        node_id text NOT NULL,
        iteration_path text NOT NULL,
        kind text NOT NULL,
        status text NOT NULL,
        detail jsonb,
        resolution jsonb,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        resolved_at timestamp with time zone,
        CONSTRAINT pk_run_waits PRIMARY KEY (tenant_id, id),
        CONSTRAINT fk_run_waits_run_id_worker_runs
            FOREIGN KEY (tenant_id, run_id)
            REFERENCES platform.worker_runs (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT uq_run_waits_tenant_id_run_id_interrupt_id
            UNIQUE (tenant_id, run_id, interrupt_id),
        CONSTRAINT ck_run_waits_kind
            CHECK (kind IN ('approval', 'incident', 'outcome_review', 'child_run')),
        CONSTRAINT ck_run_waits_status
            CHECK (status IN ('open', 'resolved', 'consumed', 'cancelled')),
        CONSTRAINT ck_run_waits_resolved CHECK (
            (status IN ('resolved', 'consumed')) = (resolution IS NOT NULL)
            AND (resolution IS NULL) = (resolved_at IS NULL)
        ),
        CONSTRAINT ck_run_waits_resolution_object
            CHECK (resolution IS NULL OR jsonb_typeof(resolution) = 'object'),
        CONSTRAINT ck_run_waits_detail_object
            CHECK (detail IS NULL OR jsonb_typeof(detail) = 'object'),
        CONSTRAINT ck_run_waits_interrupt_id CHECK (
            starts_with(interrupt_id, 'wait:' || node_id || ':' || iteration_path || ':')
        ),
        CONSTRAINT ck_run_waits_node_id CHECK (char_length(node_id) BETWEEN 1 AND 200)
    )
"""

_STATEMENTS = (
    "CREATE UNIQUE INDEX uq_run_waits_tenant_id_run_id_node_id_iteration_path_open"
    " ON platform.run_waits (tenant_id, run_id, node_id, iteration_path)"
    " WHERE status = 'open'",
    # Written out, not looped: `scripts/verify_invariants.py` reads this text.
    # Tenant-only: the wait's workspace is its run's (DO-01).
    "ALTER TABLE platform.run_waits ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.run_waits FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_run_waits ON platform.run_waits"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# R6.40 (WE54): the wait's state machine, held by PostgreSQL for every writer.
_GUARD = """
    CREATE FUNCTION platform.guard_run_wait_transition() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'open' THEN
                RAISE EXCEPTION 'a wait is opened, never written resolved'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_run_waits_transition';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
            (OLD.status = 'open' AND NEW.status IN ('resolved', 'cancelled'))
            OR (OLD.status = 'resolved' AND NEW.status = 'consumed')
        ) THEN
            RAISE EXCEPTION 'a wait moves open -> resolved or cancelled, resolved -> consumed'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_run_waits_transition';
        END IF;
        IF (OLD.resolution IS NOT NULL AND NEW.resolution IS DISTINCT FROM OLD.resolution)
           OR (OLD.resolved_at IS NOT NULL AND NEW.resolved_at IS DISTINCT FROM OLD.resolved_at)
        THEN
            RAISE EXCEPTION 'a wait''s resolution is written once'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_run_waits_transition';
        END IF;
        IF (NEW.tenant_id, NEW.id, NEW.run_id, NEW.interrupt_id, NEW.node_id,
            NEW.iteration_path, NEW.kind, NEW.detail, NEW.created_at)
           IS DISTINCT FROM
           (OLD.tenant_id, OLD.id, OLD.run_id, OLD.interrupt_id, OLD.node_id,
            OLD.iteration_path, OLD.kind, OLD.detail, OLD.created_at) THEN
            RAISE EXCEPTION 'a wait keeps what it was opened with'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_run_waits_transition';
        END IF;
        RETURN NEW;
    END
    $$
"""

# R6.13: every way a run ends cancels its open waits, in the same transaction.
_CANCEL = """
    CREATE FUNCTION platform.cancel_run_waits() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        UPDATE platform.run_waits w
        SET status = 'cancelled'
        WHERE w.tenant_id = NEW.tenant_id AND w.run_id = NEW.id AND w.status = 'open';
        RETURN NULL;
    END
    $$
"""

_FUNCTIONS = (
    "platform.guard_run_wait_transition()",
    "platform.cancel_run_waits()",
)

_TRIGGERS = (
    "CREATE TRIGGER guard_run_wait_transition BEFORE INSERT OR UPDATE ON platform.run_waits"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_run_wait_transition()",
    "CREATE TRIGGER worker_runs_cancel_run_waits"
    " AFTER UPDATE OF status ON platform.worker_runs FOR EACH ROW"
    f" WHEN (NEW.status IN ({_FINISHED}) AND OLD.status IS DISTINCT FROM NEW.status)"
    " EXECUTE FUNCTION platform.cancel_run_waits()",
)

# `ALTER DEFAULT PRIVILEGES` hands `dw_app` every verb and `dw_agent_ro`
# SELECT on a new platform table; these hold exactly what the wait path, the
# decision's handler and the runner run. No DELETE: the run's CASCADE does it.
_GRANTS = (
    ("dw_app", "REVOKE ALL ON platform.run_waits FROM dw_app;"),
    ("dw_app", "GRANT SELECT, INSERT ON platform.run_waits TO dw_app;"),
    ("dw_app", "GRANT UPDATE (status, resolved_at, resolution) ON platform.run_waits TO dw_app;"),
    ("dw_agent_ro", "REVOKE ALL ON platform.run_waits FROM dw_agent_ro;"),
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
    op.execute(_TABLE)
    for statement in _STATEMENTS:
        op.execute(statement)
    op.execute(_GUARD)
    op.execute(_CANCEL)
    for function in _FUNCTIONS:
        # Called by their triggers and by no role.
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for role, statement in _GRANTS:
        op.execute(_for_role(role, statement))
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    op.execute(
        sa.text(
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
            " 'dw_studio', true)"
            " ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=PERMISSION, l=PERMISSION_LABEL)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
        ).bindparams(k=PERMISSION)
    )
    op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=PERMISSION))
    op.execute("DROP TRIGGER worker_runs_cancel_run_waits ON platform.worker_runs")
    # The table takes its own trigger, index and policy with it.
    op.execute("DROP TABLE platform.run_waits")
    for function in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
