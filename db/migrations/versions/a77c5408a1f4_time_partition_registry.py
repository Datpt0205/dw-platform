"""time partition registry

Revision ID: a77c5408a1f4
Revises: 121e470ec23c
Create Date: 2026-10-27

One registry drives partition creation (ADR 0100 point 7; studio-skeleton R3).
Until now `platform.ensure_time_partitions` looped over an array literal with
one element and `platform._ensure_one_partition` wrote `platform.` into every
statement, so a Studio table could not be partitioned at all and each new
partitioned table meant rewriting both functions (0013). A table now joins with
one row in the revision that creates it.

- `platform.time_partitioned_tables (schema_name, table_name, append_only,
  registered_by)`: written only by migrations; `dw_app` holds nothing on it and
  no role but the owner may write it, because it is the input of a SECURITY
  DEFINER function. `registered_by` is read by the red lines of the catalog
  tests (R3.4, R3.7). The first row is `platform.audit_events`.
- `_ensure_one_partition(schema_name, parent, month)` replaces the two-argument
  version. A partition it creates gets ENABLE and FORCE row security and the
  tenant policy as before, and then loses every privilege of every role but its
  owner, in every schema, instead of only `dw_app`'s UPDATE and DELETE on
  `audit_events` partitions (DO-02.2). Rows are read and written through the
  parent; a partition addressed by its own name answers "permission denied",
  so a table whose policies are narrower than the tenant one may join too.
- `ensure_time_partitions(months_ahead)` loops over the registry under a
  transaction-scoped advisory lock, so two maintenance passes at once run one
  after the other and the second creates nothing (R3.9).
- The partitions that already exist lose the same privileges here, the DEFAULT
  one included.

`drop_expired_partitions` is untouched: its rewrite belongs to usage-and-limits/02.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision = "a77c5408a1f4"
down_revision = "121e470ec23c"
branch_labels = None
depends_on = None

_TAG = re.compile(r"\$[A-Za-z_]*\$")
_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _statements(text: str) -> list[str]:
    """One command per string: asyncpg prepares what it is given, and a prepared
    statement may hold exactly one command."""
    out: list[str] = []
    buf: list[str] = []
    tag: str | None = None
    for line in text.split("\n"):
        if tag is None:
            found = _TAG.search(line)
            if found and line.count(found.group(0)) == 1:
                tag = found.group(0)
        elif tag in line:
            tag = None
        buf.append(line)
        if tag is None and line.rstrip().endswith(";"):
            statement = "\n".join(buf).strip()
            if statement:
                out.append(statement)
            buf = []
    leftover = "\n".join(buf).strip()
    if leftover:  # pragma: no cover - a file ending mid-statement is a typo
        raise ValueError(f"unterminated statement: {leftover[:120]}")
    return out


# Every privilege of every role but the owner, PUBLIC included, on one relation.
# Shared by the function (a partition it makes) and this migration (the ones
# that exist), so the two cannot disagree about what "every" means.
_REVOKE_FROM_ALL_BUT_OWNER = """
CREATE OR REPLACE FUNCTION platform._revoke_all_but_owner(target regclass)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    holder oid;
BEGIN
    FOR holder IN
        SELECT DISTINCT a.grantee
        FROM pg_class c, aclexplode(c.relacl) a
        WHERE c.oid = target AND a.grantee <> c.relowner
    LOOP
        IF holder = 0 THEN
            EXECUTE format('REVOKE ALL ON %s FROM PUBLIC', target);
        ELSE
            EXECUTE format('REVOKE ALL ON %s FROM %s', target, holder::regrole);
        END IF;
    END LOOP;
END;
$fn$
"""

_ENSURE_ONE = """
CREATE FUNCTION platform._ensure_one_partition(schema_name text, parent text, month date)
RETURNS text
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    part text := parent || '_' || to_char(month, 'YYYY_MM');
    fallback text := parent || '_default';
    stamp text;
    next_month date := (month + interval '1 month')::date;
    predicate constant text :=
        'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid';
    stranded boolean := false;
BEGIN
    IF to_regclass(format('%I.%I', schema_name, part)) IS NOT NULL THEN
        RETURN NULL;
    END IF;
    -- The partition key, from the table that declares it, and only of a RANGE
    -- partitioned table: a month is a range.
    SELECT a.attname INTO stamp
    FROM pg_partitioned_table p
    JOIN pg_attribute a ON a.attrelid = p.partrelid AND a.attnum = p.partattrs[0]
    WHERE p.partrelid = to_regclass(format('%I.%I', schema_name, parent))
      AND p.partstrat = 'r';
    IF stamp IS NULL THEN
        RAISE EXCEPTION '%.% is not range-partitioned', schema_name, parent;
    END IF;

    -- Asked before the expensive path is taken: detaching the default takes an
    -- ACCESS EXCLUSIVE lock, and this runs hourly on a table that is almost
    -- always already in order.
    IF to_regclass(format('%I.%I', schema_name, fallback)) IS NOT NULL THEN
        EXECUTE format(
            'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I >= %L AND %I < %L)',
            schema_name, fallback, stamp, month, stamp, next_month
        ) INTO stranded;
    END IF;
    IF stranded THEN
        EXECUTE format(
            'ALTER TABLE %I.%I DETACH PARTITION %I.%I',
            schema_name, parent, schema_name, fallback
        );
    END IF;

    EXECUTE format(
        'CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
        schema_name, part, schema_name, parent, month, next_month
    );
    -- Postgres does not inherit row security to a partition created later, and
    -- a partition addressed by name uses its own settings. FORCE as well:
    -- without it the owner reads straight past the policy, and the owner is
    -- exactly who runs this.
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', schema_name, part);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', schema_name, part);
    EXECUTE format(
        'CREATE POLICY %I ON %I.%I USING (%s) WITH CHECK (%s)',
        'tenant_isolation_' || part, schema_name, part, predicate, predicate
    );
    -- `ALTER DEFAULT PRIVILEGES` has already handed this partition what the
    -- schema hands every table. Rows are read and written through the parent,
    -- so nobody but the owner keeps anything on the partition itself.
    PERFORM platform._revoke_all_but_owner(format('%I.%I', schema_name, part)::regclass);

    IF stranded THEN
        -- Back in through the PARENT, so the rows route themselves into the
        -- partition just made. Only this month's: the default may legitimately
        -- be holding other months that nothing has asked for yet.
        EXECUTE format(
            'INSERT INTO %I.%I SELECT * FROM %I.%I WHERE %I >= %L AND %I < %L',
            schema_name, parent, schema_name, fallback, stamp, month, stamp, next_month
        );
        EXECUTE format(
            'DELETE FROM %I.%I WHERE %I >= %L AND %I < %L',
            schema_name, fallback, stamp, month, stamp, next_month
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ATTACH PARTITION %I.%I DEFAULT',
            schema_name, parent, schema_name, fallback
        );
    END IF;
    RETURN part;
END;
$fn$
"""

_ENSURE_ALL = """
CREATE OR REPLACE FUNCTION platform.ensure_time_partitions(months_ahead integer)
RETURNS SETOF text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    registered record;
    step integer;
    made text;
    first_month constant date := date_trunc('month', now())::date;
BEGIN
    -- Bounded rather than trusted: the argument crosses a privilege boundary,
    -- and 24 months of empty partitions is the most any schedule needs.
    IF months_ahead IS NULL OR months_ahead < 1 OR months_ahead > 24 THEN
        RAISE EXCEPTION 'months_ahead must be between 1 and 24, got %', months_ahead;
    END IF;
    -- Two passes at once (two worker replicas) take turns: the second finds
    -- every partition made and every stranded row already moved.
    PERFORM pg_advisory_xact_lock(hashtext('platform.ensure_time_partitions'));
    FOR registered IN
        SELECT r.schema_name, r.table_name
        FROM platform.time_partitioned_tables r
        ORDER BY r.schema_name, r.table_name
    LOOP
        FOR step IN 0..months_ahead LOOP
            made := platform._ensure_one_partition(
                registered.schema_name,
                registered.table_name,
                (first_month + (step || ' month')::interval)::date
            );
            IF made IS NOT NULL THEN
                RETURN NEXT format('%I.%I', registered.schema_name, made);
            END IF;
        END LOOP;
    END LOOP;
END;
$fn$
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform.time_partitioned_tables (
            schema_name text NOT NULL,
            table_name text NOT NULL,
            append_only boolean NOT NULL,
            registered_by text NOT NULL,
            CONSTRAINT pk_time_partitioned_tables PRIMARY KEY (schema_name, table_name)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE platform.time_partitioned_tables IS"
        " 'Range-partitioned tables whose monthly partitions ensure_time_partitions"
        " creates. Written only by migrations (ADR 0100 point 7).'"
    )
    op.execute(
        "INSERT INTO platform.time_partitioned_tables"
        " (schema_name, table_name, append_only, registered_by)"
        " VALUES ('platform', 'audit_events', true, 'platform')"
    )
    op.execute(_REVOKE_FROM_ALL_BUT_OWNER)
    op.execute("REVOKE ALL ON FUNCTION platform._revoke_all_but_owner(regclass) FROM PUBLIC")
    # The default privileges of `platform` gave `dw_app` DML on the new table.
    op.execute(
        "SELECT platform._revoke_all_but_owner('platform.time_partitioned_tables'::regclass)"
    )
    op.execute("DROP FUNCTION platform._ensure_one_partition(text, date)")
    op.execute(_ENSURE_ONE)
    op.execute(
        "REVOKE ALL ON FUNCTION platform._ensure_one_partition(text, text, date) FROM PUBLIC"
    )
    op.execute(_ENSURE_ALL)
    op.execute("REVOKE ALL ON FUNCTION platform.ensure_time_partitions(integer) FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT EXECUTE ON FUNCTION platform.ensure_time_partitions(integer) TO dw_app;
            END IF;
        END
        $$
        """
    )
    # The partitions that exist already, the DEFAULT one included.
    op.execute(
        """
        SELECT platform._revoke_all_but_owner(i.inhrelid::regclass)
        FROM platform.time_partitioned_tables r
        JOIN pg_namespace n ON n.nspname = r.schema_name
        JOIN pg_class parent ON parent.relnamespace = n.oid AND parent.relname = r.table_name
        JOIN pg_inherits i ON i.inhparent = parent.oid
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION platform._ensure_one_partition(text, text, date)")
    # 0013's two-argument helper and its array-driven loop, restored as written.
    sql = (_SQL_DIR / "0013_partition_maintenance.sql").read_text("utf-8")
    for statement in _statements(sql):
        op.execute(statement)
    op.execute("DROP FUNCTION platform._revoke_all_but_owner(regclass)")
    op.execute("DROP TABLE platform.time_partitioned_tables")
