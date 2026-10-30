"""platform work items

Revision ID: cfbd906be98b
Revises: be93e0c26a4c
Create Date: 2026-10-30

digital-worker ticket 02 (R1.12, R1.14, R3, R4, R5.5; ADR-0128 decisions 6-7).
People and Digital Workers work one queue; each item has exactly one holder.

- `platform.work_items`, under the one workspace policy shape. It reaches its
  DW through the composite key carrying `tenant_id` (a foreign key does not
  pass through RLS). `payload` is fixed once written: a trigger refuses a
  change to `payload`, `payload_hash`, `kind`, `source_key` or `dw_id` by
  `dw_app`, so the subject-erasure pass of compliance-pdpl/06 can run under a
  role of its own. The status pairs live in the application's one table
  (`dw_platform.domain.work_item.TRANSITIONS`); the database holds what a row
  must look like in each status: a timer only while `waiting_timer`, a packet
  while `handed_off`, `closed_at` exactly at the end, a DW holder that is the
  DW itself.
- `platform.dw_work_scopes_due(limit)`, SECURITY DEFINER, the one read across
  tenants: which `(tenant_id, workspace_id)` hold an `open` item due for an
  `operating` DW that still has a Business Owner, or an `in_progress` item
  untouched for 15 minutes (R3.6, R3.14). Ids only; every read after it runs
  under that scope's RLS. EXECUTE for `dw_app` alone.
- `platform.retire_dw_principal(dw_id)`, SECURITY DEFINER: removes the
  memberships of a retired DW's principal in the bound tenant, and nothing
  else (R1.14). Refuses a DW that is not `retired`.
- `platform.worker_runs.run_as_principal_id` (ADR-0113 decision 1).
- `platform.approval_decisions.edited` and `edited_payload` (R5.5, D18).
- `dw_app` reads, inserts and updates work items, and deletes them for
  offboarding, which purges what `dw_app` may delete (as in be93e0c26a4c).
"""

from __future__ import annotations

from alembic import op

revision = "cfbd906be98b"
down_revision = "be93e0c26a4c"
branch_labels = None
depends_on = None

_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_WORKSPACE = "(workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid))"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"
_NARROWED = f"({_TENANT} AND ({_WORKSPACE} OR {_SCOPE}))"


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
    op.execute(
        """
        CREATE TABLE platform.work_items (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            dw_id uuid NOT NULL,
            kind text NOT NULL,
            source_key text NOT NULL,
            payload jsonb NOT NULL,
            payload_hash text NOT NULL,
            holder_kind text NOT NULL,
            holder_id uuid NOT NULL,
            status text DEFAULT 'open' NOT NULL,
            available_at timestamp with time zone DEFAULT now() NOT NULL,
            run_id uuid,
            wake_at timestamp with time zone,
            handoff jsonb,
            error text,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            closed_at timestamp with time zone,
            CONSTRAINT pk_work_items PRIMARY KEY (id),
            CONSTRAINT uq_work_items_source
                UNIQUE (tenant_id, dw_id, kind, source_key),
            CONSTRAINT fk_work_items_digital_worker
                FOREIGN KEY (tenant_id, workspace_id, dw_id)
                REFERENCES platform.digital_workers(tenant_id, workspace_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT ck_work_items_kind CHECK (char_length(kind) BETWEEN 1 AND 120),
            CONSTRAINT ck_work_items_source_key
                CHECK (char_length(source_key) BETWEEN 1 AND 255),
            CONSTRAINT ck_work_items_payload_hash CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_work_items_holder_kind
                CHECK (holder_kind IN ('digital_worker', 'person')),
            CONSTRAINT ck_work_items_dw_holds_itself
                CHECK (holder_kind <> 'digital_worker' OR holder_id = dw_id),
            CONSTRAINT ck_work_items_status CHECK (
                status IN ('open', 'in_progress', 'waiting_approval', 'waiting_timer',
                           'handed_off', 'done', 'failed', 'cancelled')
            ),
            CONSTRAINT ck_work_items_wake_at
                CHECK ((status = 'waiting_timer') = (wake_at IS NOT NULL)),
            CONSTRAINT ck_work_items_handoff
                CHECK (status <> 'handed_off' OR handoff IS NOT NULL),
            CONSTRAINT ck_work_items_closed_at
                CHECK ((status IN ('done', 'failed', 'cancelled')) = (closed_at IS NOT NULL))
        )
        """
    )
    # The list pages newest first in one workspace (R3.5), the lane reads what
    # is due (R3.6), the timer what wakes, and a run finds its item.
    op.execute(
        "CREATE INDEX ix_work_items_page"
        " ON platform.work_items (tenant_id, workspace_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_work_items_digital_worker"
        " ON platform.work_items (tenant_id, workspace_id, dw_id)"
    )
    op.execute(
        "CREATE INDEX ix_work_items_open_due"
        " ON platform.work_items (tenant_id, available_at) WHERE status = 'open'"
    )
    op.execute(
        "CREATE INDEX ix_work_items_in_progress"
        " ON platform.work_items (tenant_id, updated_at) WHERE status = 'in_progress'"
    )
    op.execute(
        "CREATE INDEX ix_work_items_wake_at"
        " ON platform.work_items (wake_at) WHERE status = 'waiting_timer'"
    )
    op.execute("CREATE INDEX ix_work_items_run_id ON platform.work_items (run_id)")
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.work_items"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )

    op.execute(
        """
        CREATE FUNCTION platform.work_item_payload_fixed() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF current_user = 'dw_app' AND (
                NEW.payload IS DISTINCT FROM OLD.payload
                OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
                OR NEW.kind IS DISTINCT FROM OLD.kind
                OR NEW.source_key IS DISTINCT FROM OLD.source_key
                OR NEW.dw_id IS DISTINCT FROM OLD.dw_id
            ) THEN
                RAISE EXCEPTION 'a work item keeps what it was given'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_work_items_payload_fixed';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER work_item_payload_fixed BEFORE UPDATE ON platform.work_items"
        " FOR EACH ROW EXECUTE FUNCTION platform.work_item_payload_fixed()"
    )

    op.execute("ALTER TABLE platform.work_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.work_items FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_work_items ON platform.work_items"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )
    op.execute(_for_role("dw_app", "REVOKE TRUNCATE ON platform.work_items FROM dw_app;"))
    op.execute(
        _for_role(
            "dw_app", "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.work_items TO dw_app;"
        )
    )
    op.execute(_for_role("dw_agent_ro", "REVOKE ALL ON platform.work_items FROM dw_agent_ro;"))

    op.execute(
        """
        CREATE FUNCTION platform.dw_work_scopes_due(p_limit integer)
        RETURNS TABLE (tenant_id uuid, workspace_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
            SELECT DISTINCT w.tenant_id, w.workspace_id
            FROM platform.work_items w
            JOIN platform.digital_workers d ON d.id = w.dw_id
            JOIN platform.service_principals p ON p.user_id = d.principal_user_id
            WHERE (
                    w.status = 'open' AND w.available_at <= now()
                    AND d.state = 'operating' AND p.owner_user_id IS NOT NULL
                  )
               OR (w.status = 'in_progress' AND w.updated_at <= now() - interval '15 minutes')
            ORDER BY w.tenant_id, w.workspace_id
            LIMIT greatest(p_limit, 0)
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform.retire_dw_principal(p_dw_id uuid)
        RETURNS integer
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        DECLARE
            v_tenant uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
            v_principal uuid;
            v_removed integer;
        BEGIN
            SELECT d.principal_user_id INTO v_principal
            FROM platform.digital_workers d
            WHERE d.id = p_dw_id AND d.tenant_id = v_tenant AND d.state = 'retired';
            IF v_tenant IS NULL OR v_principal IS NULL THEN
                RAISE EXCEPTION 'only a retired digital worker of the bound tenant is retired here'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            DELETE FROM platform.memberships m
            WHERE m.tenant_id = v_tenant AND m.user_id = v_principal;
            GET DIAGNOSTICS v_removed = ROW_COUNT;
            RETURN v_removed;
        END
        $$
        """
    )
    for function in (
        "platform.dw_work_scopes_due(integer)",
        "platform.retire_dw_principal(uuid)",
        "platform.work_item_payload_fixed()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in ("platform.dw_work_scopes_due(integer)", "platform.retire_dw_principal(uuid)"):
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))

    op.execute("ALTER TABLE platform.worker_runs ADD COLUMN run_as_principal_id uuid")
    op.execute(
        "CREATE INDEX ix_worker_runs_run_as_principal_id"
        " ON platform.worker_runs (tenant_id, run_as_principal_id)"
    )
    op.execute(
        """
        ALTER TABLE platform.approval_decisions
            ADD COLUMN edited boolean DEFAULT false NOT NULL,
            ADD COLUMN edited_payload jsonb,
            ADD CONSTRAINT ck_approval_decisions_edited
                CHECK (edited = (edited_payload IS NOT NULL))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform.approval_decisions
            DROP CONSTRAINT IF EXISTS ck_approval_decisions_edited,
            DROP COLUMN IF EXISTS edited_payload,
            DROP COLUMN IF EXISTS edited
        """
    )
    op.execute("DROP INDEX IF EXISTS platform.ix_worker_runs_run_as_principal_id")
    op.execute("ALTER TABLE platform.worker_runs DROP COLUMN IF EXISTS run_as_principal_id")
    op.execute("DROP FUNCTION IF EXISTS platform.retire_dw_principal(uuid)")
    op.execute("DROP FUNCTION IF EXISTS platform.dw_work_scopes_due(integer)")
    op.execute("DROP TABLE IF EXISTS platform.work_items")
    op.execute("DROP FUNCTION IF EXISTS platform.work_item_payload_fixed()")
