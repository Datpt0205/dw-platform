"""usage ledger, its daily roll-up and the append-only purge

Revision ID: 2354ad4d2e3c
Revises: 388a31c46bdf
Create Date: 2026-11-04 04:35:03.602394+00:00

usage-and-limits ticket 02 (spec R3.1-R3.12, UL7, UL16, UL18; ADR-0121
decisions 1, 2, 9; DO-21.1, DO-02.2). The per-call usage ledger comes back by
a new revision, never by a downgrade of `aefe7c1f5d9b`, with its readers from
the first day.

- `platform.usage_events`: one row per model call, range-partitioned by month
  on `occurred_at` with a DEFAULT partition, `PRIMARY KEY (id, occurred_at)`.
  NOT NULL: `id`, `occurred_at`, `tenant_id`, `operation`, `purpose`,
  `payer`, `actor_kind`, `provider`, `model`, the token columns, `units`,
  `cost_source`, `price_book_version`, `price_entry_ids`. NULL where W1 has no
  writer or a call has no value: `workspace_id` (company-level work),
  `run_id`, `root_run_id`, `node_id`, the artifact columns, `lease_id`
  (ticket 03), `user_id`, `trigger_kind` and the three route columns
  (compliance-pdpl/03 writes them from `ResidencyGate`; NULL means the call
  did not pass the gate, never `vn_only`). `cost_usd` is NULL exactly when
  `cost_source = 'unpriced'`. RLS enabled and forced on the parent and on the
  DEFAULT partition with the tenant policy; `worker_drain_usage_events` lets
  the `usage_rollup` lane SELECT across tenants, nothing else. `dw_app`
  holds SELECT and INSERT on the parent, never UPDATE or DELETE, and nothing
  on any partition, DEFAULT included (DO-02.2); `dw_agent_ro` nothing.
  Registered in `platform.time_partitioned_tables` (`append_only`), so the
  `partitions` lane makes its months.
- `platform.usage_daily`: the roll-up the usage screen reads, one row per
  (company, workspace, day, artifact, user, provider, model, operation,
  purpose, payer), `UNIQUE NULLS NOT DISTINCT`; tenant policy; `dw_app`
  SELECT, INSERT, UPDATE, DELETE (the lane recomputes a day; offboarding
  deletes it as an ordinary table, R3.8).
- `platform.drop_expired_partitions(cutoffs jsonb)` replaces the one-cutoff
  version of 0013: one cutoff per registered parent, keyed `schema.table`;
  a parent with no key, or a NULL, loses nothing.
- `platform.append_only_tables()` and
  `platform.purge_tenant_append_only(p_tenant, p_tables)`: SECURITY DEFINER on
  a fixed `search_path`, revoked from PUBLIC, executable by `dw_app`. The
  purge refuses with 23514, deleting nothing, a tenant that is not the
  transaction's own, one that is not `offboarding`, and a table outside the
  first function's answer (every `append_only` registered table but
  `platform.audit_events`).
- `platform.usage.read` becomes `active` (tenant-rbac/01's convention);
  `tenant_owner` holds it by computation (ADR-0104 decision 2).
"""

from __future__ import annotations

from alembic import op

revision = "2354ad4d2e3c"
down_revision = "388a31c46bdf"
branch_labels = None
depends_on = None

# Each setting read once per statement, in a sub-SELECT (foundations-hardening R5.3).
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_DRAIN = "((SELECT current_setting('app.worker_drain', true)) = 'on')"


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


_USAGE_EVENTS = """
    CREATE TABLE platform.usage_events (
        id uuid NOT NULL,
        occurred_at timestamptz NOT NULL,
        tenant_id uuid NOT NULL,
        workspace_id uuid,
        run_id uuid,
        root_run_id uuid,
        lease_id uuid,
        node_id text,
        artifact_kind text,
        artifact_id uuid,
        artifact_version text,
        user_id uuid,
        actor_kind text NOT NULL,
        trigger_kind text,
        operation text NOT NULL,
        purpose text NOT NULL,
        payer text NOT NULL,
        provider text NOT NULL,
        model text NOT NULL,
        input_tokens bigint NOT NULL,
        output_tokens bigint NOT NULL,
        cache_read_tokens bigint NOT NULL,
        cache_write_tokens bigint NOT NULL,
        reasoning_tokens bigint NOT NULL,
        units jsonb NOT NULL,
        cost_usd numeric(18, 8),
        cost_source text NOT NULL,
        price_book_version text NOT NULL,
        price_entry_ids text[] NOT NULL,
        data_route_class text,
        data_location text,
        processor text,
        CONSTRAINT pk_usage_events PRIMARY KEY (id, occurred_at),
        CONSTRAINT ck_usage_events_operation CHECK (operation IN (
            'chat', 'embeddings', 'rerank', 'extraction', 'transcription',
            'sandbox_exec', 'server_tool', 'unsettled_estimate')),
        CONSTRAINT ck_usage_events_purpose CHECK (purpose IN (
            'run', 'test_run', 'builder_assist', 'eval_offline', 'eval_online',
            'ingestion', 'retrieval', 'compaction', 'memory')),
        CONSTRAINT ck_usage_events_payer CHECK (payer IN ('platform', 'tenant')),
        CONSTRAINT ck_usage_events_actor_kind
            CHECK (actor_kind IN ('user', 'service', 'system')),
        CONSTRAINT ck_usage_events_artifact_kind
            CHECK (artifact_kind IS NULL OR artifact_kind IN ('agent', 'workflow')),
        CONSTRAINT ck_usage_events_cost_source CHECK (cost_source IN (
            'computed', 'provider_reported', 'estimated', 'unpriced')),
        CONSTRAINT ck_usage_events_cost_when_priced
            CHECK ((cost_usd IS NULL) = (cost_source = 'unpriced')),
        CONSTRAINT ck_usage_events_cost_usd CHECK (cost_usd >= 0),
        CONSTRAINT ck_usage_events_tokens CHECK (
            input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0
            AND cache_write_tokens >= 0 AND reasoning_tokens >= 0),
        CONSTRAINT ck_usage_events_cache_within_input
            CHECK (cache_read_tokens + cache_write_tokens <= input_tokens),
        CONSTRAINT ck_usage_events_reasoning_within_output
            CHECK (reasoning_tokens <= output_tokens),
        CONSTRAINT ck_usage_events_units CHECK (jsonb_typeof(units) = 'object'),
        CONSTRAINT ck_usage_events_price_book_version CHECK (btrim(price_book_version) <> ''),
        CONSTRAINT ck_usage_events_data_route_class CHECK (data_route_class IN (
            'vn_only', 'cross_border_minimised', 'cross_border_full')),
        CONSTRAINT ck_usage_events_data_location CHECK (data_location IN ('vn', 'foreign'))
    ) PARTITION BY RANGE (occurred_at)
"""

_USAGE_DAILY = """
    CREATE TABLE platform.usage_daily (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL,
        workspace_id uuid,
        day date NOT NULL,
        artifact_kind text,
        artifact_id uuid,
        user_id uuid,
        provider text NOT NULL,
        model text NOT NULL,
        operation text NOT NULL,
        purpose text NOT NULL,
        payer text NOT NULL,
        calls bigint NOT NULL,
        input_tokens bigint NOT NULL,
        output_tokens bigint NOT NULL,
        cache_read_tokens bigint NOT NULL,
        cache_write_tokens bigint NOT NULL,
        reasoning_tokens bigint NOT NULL,
        cost_usd numeric(20, 8) NOT NULL,
        unpriced_calls bigint NOT NULL,
        estimated_calls bigint NOT NULL,
        rolled_up_at timestamptz NOT NULL,
        CONSTRAINT pk_usage_daily PRIMARY KEY (id),
        CONSTRAINT uq_usage_daily_group UNIQUE NULLS NOT DISTINCT (
            tenant_id, workspace_id, day, artifact_kind, artifact_id, user_id,
            provider, model, operation, purpose, payer),
        CONSTRAINT ck_usage_daily_counts CHECK (
            calls >= 0 AND input_tokens >= 0 AND output_tokens >= 0
            AND cache_read_tokens >= 0 AND cache_write_tokens >= 0
            AND reasoning_tokens >= 0 AND cost_usd >= 0
            AND unpriced_calls >= 0 AND estimated_calls >= 0
            AND unpriced_calls + estimated_calls <= calls),
        CONSTRAINT ck_usage_daily_artifact_kind
            CHECK (artifact_kind IS NULL OR artifact_kind IN ('agent', 'workflow'))
    )
"""

# One cutoff per registered parent (spec "Trong phạm vi"; usage-and-limits/02 is
# its one owner in W1). The partitions a parent owns are the names
# `_ensure_one_partition` makes; the DEFAULT and anything made by hand fall
# through, because a sweep that guessed an unfamiliar range would be guessing
# which rows to destroy.
_DROP_EXPIRED = """
CREATE FUNCTION platform.drop_expired_partitions(cutoffs jsonb)
RETURNS SETOF text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    registered record;
    found record;
    cutoff timestamptz;
    range_end timestamptz;
BEGIN
    IF cutoffs IS NULL OR jsonb_typeof(cutoffs) <> 'object' THEN
        RAISE EXCEPTION 'cutoffs is a json object keyed schema.table';
    END IF;
    FOR registered IN
        SELECT r.schema_name, r.table_name
        FROM platform.time_partitioned_tables r
        ORDER BY r.schema_name, r.table_name
    LOOP
        -- A missing key and a JSON null alike: nothing is dropped, which is
        -- what a table with no enforced term must get.
        cutoff := (
            cutoffs ->> (registered.schema_name || '.' || registered.table_name)
        )::timestamptz;
        CONTINUE WHEN cutoff IS NULL;
        FOR found IN
            SELECT child.relname AS part
            FROM pg_inherits i
            JOIN pg_class parent ON parent.oid = i.inhparent
            JOIN pg_class child ON child.oid = i.inhrelid
            JOIN pg_namespace n ON n.oid = parent.relnamespace
            WHERE n.nspname = registered.schema_name
              AND parent.relname = registered.table_name
            ORDER BY child.relname
        LOOP
            CONTINUE WHEN found.part !~ ('^' || registered.table_name || '_\\d{4}_\\d{2}$');
            range_end := to_date(right(found.part, 7), 'YYYY_MM') + interval '1 month';
            IF range_end <= cutoff THEN
                EXECUTE format('DROP TABLE %I.%I', registered.schema_name, found.part);
                RETURN NEXT format('%I.%I', registered.schema_name, found.part);
            END IF;
        END LOOP;
    END LOOP;
END;
$fn$
"""

# 0013's one-cutoff version, restored by the downgrade as it was.
_DROP_EXPIRED_0013 = """
CREATE FUNCTION platform.drop_expired_partitions(audit_cutoff timestamptz)
RETURNS SETOF text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    found record;
    range_end timestamptz;
BEGIN
    IF audit_cutoff IS NULL THEN
        RETURN;
    END IF;
    FOR found IN
        SELECT child.relname AS part
        FROM pg_inherits i
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_class child ON child.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = parent.relnamespace
        WHERE n.nspname = 'platform' AND parent.relname = 'audit_events'
        ORDER BY child.relname
    LOOP
        CONTINUE WHEN found.part !~ '^audit_events_\\d{4}_\\d{2}$';
        range_end := to_date(right(found.part, 7), 'YYYY_MM') + interval '1 month';
        IF range_end <= audit_cutoff THEN
            EXECUTE format('DROP TABLE platform.%I', found.part);
            RETURN NEXT found.part;
        END IF;
    END LOOP;
END;
$fn$
"""

# Every append-only registered table but the audit log, whose term is its own
# retention fragment's and which offboarding never shortens.
_APPEND_ONLY_TABLES = """
CREATE FUNCTION platform.append_only_tables()
RETURNS SETOF text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
    SELECT r.schema_name || '.' || r.table_name
    FROM platform.time_partitioned_tables r
    WHERE r.append_only
      AND NOT (r.schema_name = 'platform' AND r.table_name = 'audit_events')
    ORDER BY 1
$fn$
"""

# The offboarding lane's step for the append-only tables (spec R3.8-R3.10).
# Each refusal is 23514 before any delete, so a refused call deletes nothing.
_PURGE_APPEND_ONLY = """
CREATE FUNCTION platform.purge_tenant_append_only(p_tenant uuid, p_tables text[])
RETURNS TABLE (table_name text, deleted bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    v_table text;
    v_schema text;
    v_name text;
    v_count bigint;
BEGIN
    IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM
        NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
        RAISE EXCEPTION 'purge_tenant_append_only runs for the transaction''s own tenant'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM platform.tenants t WHERE t.id = p_tenant AND t.status = 'offboarding'
    ) THEN
        RAISE EXCEPTION 'purge_tenant_append_only runs only for a tenant offboarding'
            USING ERRCODE = '23514';
    END IF;
    IF p_tables IS NULL OR EXISTS (
        SELECT 1 FROM unnest(p_tables) AS asked(name)
        WHERE asked.name IS NULL
           OR asked.name NOT IN (SELECT a FROM platform.append_only_tables() AS a)
    ) THEN
        RAISE EXCEPTION 'purge_tenant_append_only deletes only registered append-only tables'
            USING ERRCODE = '23514';
    END IF;
    FOREACH v_table IN ARRAY p_tables LOOP
        v_schema := split_part(v_table, '.', 1);
        v_name := split_part(v_table, '.', 2);
        EXECUTE format('DELETE FROM %I.%I WHERE tenant_id = $1', v_schema, v_name)
            USING p_tenant;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        table_name := v_table;
        deleted := v_count;
        RETURN NEXT;
    END LOOP;
END;
$fn$
"""

_FUNCTIONS = (
    "platform.drop_expired_partitions(jsonb)",
    "platform.append_only_tables()",
    "platform.purge_tenant_append_only(uuid, text[])",
)


def upgrade() -> None:
    # ---- the ledger ----------------------------------------------------------
    op.execute(_USAGE_EVENTS)
    op.execute(
        "CREATE TABLE platform.usage_events_default PARTITION OF platform.usage_events DEFAULT"
    )
    op.execute(
        "CREATE INDEX ix_usage_events_tenant_id_occurred_at"
        " ON platform.usage_events (tenant_id, occurred_at)"
    )
    op.execute(
        "CREATE INDEX ix_usage_events_tenant_id_run_id"
        " ON platform.usage_events (tenant_id, run_id) WHERE run_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_usage_events_lease_id"
        " ON platform.usage_events (lease_id) WHERE lease_id IS NOT NULL"
    )
    # Written out rather than looped: `scripts/verify_invariants.py` reads this
    # text, and a name built by an f-string is one it cannot see.
    op.execute("ALTER TABLE platform.usage_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.usage_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_usage_events ON platform.usage_events"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    # The DEFAULT partition carries its own: a partition addressed by name uses
    # its own settings, and the parent's do not reach it.
    op.execute("ALTER TABLE platform.usage_events_default ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.usage_events_default FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_usage_events_default ON platform.usage_events_default"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    # The roll-up lane finds the tenants with rows, and only reads.
    op.execute(
        "CREATE POLICY worker_drain_usage_events ON platform.usage_events"
        f" FOR SELECT USING ({_DRAIN})"
    )
    op.execute(
        _for_role("dw_app", "REVOKE UPDATE, DELETE, TRUNCATE ON platform.usage_events FROM dw_app;")
    )
    op.execute(_for_role("dw_app", "GRANT SELECT, INSERT ON platform.usage_events TO dw_app;"))
    op.execute(_for_role("dw_agent_ro", "REVOKE ALL ON platform.usage_events FROM dw_agent_ro;"))
    op.execute("SELECT platform._revoke_all_but_owner('platform.usage_events_default'::regclass)")
    op.execute(
        "INSERT INTO platform.time_partitioned_tables"
        " (schema_name, table_name, append_only, registered_by)"
        " VALUES ('platform', 'usage_events', true, 'usage-and-limits')"
    )

    # ---- the roll-up ---------------------------------------------------------
    op.execute(_USAGE_DAILY)
    op.execute("CREATE INDEX ix_usage_daily_tenant_id_day ON platform.usage_daily (tenant_id, day)")
    op.execute(
        "CREATE INDEX ix_usage_daily_tenant_id_workspace_id_day"
        " ON platform.usage_daily (tenant_id, workspace_id, day)"
    )
    op.execute("ALTER TABLE platform.usage_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.usage_daily FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_usage_daily ON platform.usage_daily"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute(
        _for_role(
            "dw_app",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.usage_daily TO dw_app;",
        )
    )
    op.execute(_for_role("dw_agent_ro", "REVOKE ALL ON platform.usage_daily FROM dw_agent_ro;"))

    # ---- the registry's functions --------------------------------------------
    op.execute("DROP FUNCTION platform.drop_expired_partitions(timestamptz)")
    op.execute(_DROP_EXPIRED)
    op.execute(_APPEND_ONLY_TABLES)
    op.execute(_PURGE_APPEND_ONLY)
    for function in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))

    # ---- the key -------------------------------------------------------------
    op.execute(
        "UPDATE platform.permissions SET status = 'active', status_reason = NULL"
        " WHERE key = 'platform.usage.read'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE platform.permissions SET status = 'unassigned',"
        " status_reason = 'usage-and-limits dùng lại và đưa về active trong migration của nó'"
        " WHERE key = 'platform.usage.read'"
    )
    op.execute("DROP FUNCTION platform.purge_tenant_append_only(uuid, text[])")
    op.execute("DROP FUNCTION platform.append_only_tables()")
    op.execute("DROP FUNCTION platform.drop_expired_partitions(jsonb)")
    op.execute(_DROP_EXPIRED_0013)
    op.execute("REVOKE ALL ON FUNCTION platform.drop_expired_partitions(timestamptz) FROM PUBLIC")
    op.execute(
        _for_role(
            "dw_app",
            "GRANT EXECUTE ON FUNCTION platform.drop_expired_partitions(timestamptz) TO dw_app;",
        )
    )
    op.execute("DROP TABLE platform.usage_daily")
    op.execute(
        "DELETE FROM platform.time_partitioned_tables"
        " WHERE schema_name = 'platform' AND table_name = 'usage_events'"
    )
    op.execute("DROP TABLE platform.usage_events")
