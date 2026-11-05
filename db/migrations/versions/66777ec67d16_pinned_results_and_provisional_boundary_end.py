"""pinned results and the provisional boundary's end

Revision ID: 66777ec67d16
Revises: 902ac246a9dc
Create Date: 2026-11-05 09:00:00.000000+00:00

workflow-engine ticket 03 (R3.14, R3.16, R3.23, R4.27-R4.29; V4.22, V4.37;
H-18):

- `platform.worker_runs.pinned_results jsonb`, NULL: what a `simulate` run's
  steps answer instead of their doors, by step id, written by the run door
  (`RunRequestService`) and nothing else; `ck_worker_runs_pinned_results_simulate`
  refuses it on a run of any other mode, for `dw_app` writing SQL too.
- `worker_runs_pinned_results_immutable`: a BEFORE UPDATE trigger refusing any
  change of the column once inserted, so a run taken again after a crash reads
  what it was accepted with (CLAUDE.md: a run resolves only from what it
  pinned, on resume too); `ck_worker_runs_pinned_results_immutable` names it.
- `worker_runs_end_provisional_boundary`: AFTER UPDATE OF `status`, the
  provisional boundary of a run (record-access, revision 996c234cfde3) is
  deleted in the transaction that ends the run (`completed`, `failed`,
  `cancelled`, `dead_lettered`), whatever wrote the status: the runner, the
  reaper, the kill lane's UPDATE. Its function is SECURITY DEFINER of the
  migrator and deletes only the boundary of `NEW.id` under `NEW.tenant_id`,
  stated, so a cross-tenant lane with no `app.tenant_id` does not delete zero
  rows under FORCE RLS (gate of workflow-engine/05, 4/11/2026); a published
  boundary has no `run_id` and is never touched.

No grant changes: `dw_app` already inserts and updates `platform.worker_runs`
(`test_privileges.py`), and nobody may call the two trigger functions.
"""

from __future__ import annotations

from alembic import op

revision = "66777ec67d16"
down_revision = "902ac246a9dc"
branch_labels = None
depends_on = None

_FINISHED = "'completed', 'failed', 'cancelled', 'dead_lettered'"

_COLUMN = """
    ALTER TABLE platform.worker_runs
        ADD COLUMN pinned_results jsonb,
        ADD CONSTRAINT ck_worker_runs_pinned_results_simulate
            CHECK (pinned_results IS NULL OR run_mode = 'simulate')
    """

_IMMUTABLE = """
    CREATE FUNCTION platform.refuse_pinned_results_change() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        IF NEW.pinned_results IS DISTINCT FROM OLD.pinned_results THEN
            RAISE EXCEPTION 'a run''s pinned results never change once it is accepted'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_worker_runs_pinned_results_immutable';
        END IF;
        RETURN NEW;
    END
    $$
    """

_END_PROVISIONAL = """
    CREATE FUNCTION platform.end_provisional_boundary() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
        DELETE FROM studio.actor_boundaries b
        WHERE b.tenant_id = NEW.tenant_id AND b.run_id = NEW.id;
        RETURN NULL;
    END
    $$
    """

_FUNCTIONS = (
    "platform.refuse_pinned_results_change()",
    "platform.end_provisional_boundary()",
)


def upgrade() -> None:
    op.execute(_COLUMN)
    op.execute(_IMMUTABLE)
    op.execute(_END_PROVISIONAL)
    for function in _FUNCTIONS:
        # Called by their triggers and by no role.
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER worker_runs_pinned_results_immutable"
        " BEFORE UPDATE OF pinned_results ON platform.worker_runs"
        " FOR EACH ROW EXECUTE FUNCTION platform.refuse_pinned_results_change()"
    )
    op.execute(
        "CREATE TRIGGER worker_runs_end_provisional_boundary"
        " AFTER UPDATE OF status ON platform.worker_runs FOR EACH ROW"
        f" WHEN (NEW.status IN ({_FINISHED}) AND OLD.status IS DISTINCT FROM NEW.status)"
        " EXECUTE FUNCTION platform.end_provisional_boundary()"
    )


def downgrade() -> None:
    for statement in (
        "DROP TRIGGER worker_runs_end_provisional_boundary ON platform.worker_runs",
        "DROP TRIGGER worker_runs_pinned_results_immutable ON platform.worker_runs",
        "DROP FUNCTION platform.end_provisional_boundary()",
        "DROP FUNCTION platform.refuse_pinned_results_change()",
        # The column takes its CHECK with it.
        "ALTER TABLE platform.worker_runs DROP COLUMN pinned_results",
    ):
        op.execute(statement)
