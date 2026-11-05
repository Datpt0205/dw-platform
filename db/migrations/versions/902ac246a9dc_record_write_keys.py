"""record write keys

Revision ID: 902ac246a9dc
Revises: 2f177d264a27
Create Date: 2026-11-05 01:56:40.030244+00:00

custom-objects ticket 03 (R5.9-R5.11, CO26; V4.30; ADR-0108 decision 6): the
`wf:` key of each record write a workflow step sends through `RecordsPort`
(`update`, the update branch of `upsert`, and record-access/05's `assign`),
written in the transaction of the write and replayed when the step runs again.

- `studio.record_write_keys`: PK `(tenant_id, write_key)`, the key starting
  `wf:` and at most 255 bytes; the record by the composite key to
  `studio.records (tenant_id, id)` ON DELETE CASCADE, indexed on its side; the
  result the first write gave (`version`, `created`); the three owner columns
  an `assign` records, all set exactly for `assign`; `actor_id`, the run
  principal who used the key. The assign workspace is `owner_workspace_id`,
  not `workspace_id`: a row is one principal's key and the table is
  tenant-wide (`test_rls_coverage.py`), which a column named `workspace_id`
  would contradict.
- Row security: the tenant policy, and the RESTRICTIVE
  `tenant AND (actor_id = app.user_id OR scope)` of a table private to one
  person (ADR-0117), so another principal's key is not even seen: its PK
  conflict is the only trace, which RecordService answers 409.
- `dw_app` reads, inserts and deletes (the offboarding lane and the retention
  purge), never updates: a stored result is never rewritten.
- `studio.purge_expired_record_write_keys()`: SECURITY DEFINER of the
  migrator, as `platform.purge_expired_effect_keys()` is, because the
  retention lane sees no other principal's row through the RESTRICTIVE policy
  (gate (p)). It deletes, in every tenant, rows older than the term of
  `studio.record_write_keys` in `platform.retention_terms`, and raises without
  deleting anything when that term is missing.
"""

from __future__ import annotations

from alembic import op

revision = "902ac246a9dc"
down_revision = "2f177d264a27"
branch_labels = None
depends_on = None

_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_USER = "(SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"

_TABLE = """
    CREATE TABLE studio.record_write_keys (
        tenant_id uuid NOT NULL,
        write_key text NOT NULL,
        record_id uuid NOT NULL,
        op text NOT NULL,
        version integer NOT NULL,
        created boolean NOT NULL DEFAULT false,
        owner_kind text,
        owner_id uuid,
        owner_workspace_id uuid,
        actor_id uuid NOT NULL,
        created_at timestamp with time zone NOT NULL DEFAULT now(),
        CONSTRAINT pk_record_write_keys PRIMARY KEY (tenant_id, write_key),
        CONSTRAINT ck_record_write_keys_write_key
            CHECK (write_key LIKE 'wf:%' AND octet_length(write_key) <= 255),
        CONSTRAINT ck_record_write_keys_op CHECK (op IN ('update', 'upsert', 'assign')),
        CONSTRAINT ck_record_write_keys_version CHECK (version >= 1),
        CONSTRAINT ck_record_write_keys_assign_owner CHECK (
            (op = 'assign') = (
                owner_kind IS NOT NULL AND owner_id IS NOT NULL
                AND owner_workspace_id IS NOT NULL
            )
            AND (owner_kind IS NULL) = (owner_id IS NULL)
            AND (owner_id IS NULL) = (owner_workspace_id IS NULL)
        ),
        CONSTRAINT ck_record_write_keys_owner_kind
            CHECK (owner_kind IS NULL OR owner_kind IN ('user', 'team')),
        CONSTRAINT fk_record_write_keys_tenant_id_records FOREIGN KEY (tenant_id, record_id)
            REFERENCES studio.records (tenant_id, id) ON DELETE CASCADE
    )
"""

_INDEXES = (
    "CREATE INDEX ix_record_write_keys_tenant_id_record_id"
    " ON studio.record_write_keys (tenant_id, record_id)",
    # The purge's scan across every tenant, oldest first.
    "CREATE INDEX ix_record_write_keys_created_at ON studio.record_write_keys (created_at)",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
_RLS = (
    "ALTER TABLE studio.record_write_keys ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.record_write_keys FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_record_write_keys ON studio.record_write_keys"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    # A row private to one principal (CLAUDE.md, Tenancy; ADR-0117): RESTRICTIVE,
    # so no PERMISSIVE policy added later reopens another principal's key.
    "CREATE POLICY actor_or_scope_record_write_keys ON studio.record_write_keys AS RESTRICTIVE"
    f" USING ({_TENANT} AND (actor_id = {_USER} OR {_SCOPE}))",
)

_PURGE = """
    CREATE FUNCTION studio.purge_expired_record_write_keys()
    RETURNS bigint
    LANGUAGE plpgsql
    VOLATILE
    SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        -- Raises P0002 when the term is missing: nothing is deleted then.
        cutoff timestamp with time zone := now() - make_interval(
            days => platform.retention_term_days('studio.record_write_keys')
        );
        removed bigint;
    BEGIN
        DELETE FROM studio.record_write_keys WHERE created_at < cutoff;
        GET DIAGNOSTICS removed = ROW_COUNT;
        RETURN removed;
    END
    $$
"""


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
    for statement in (*_INDEXES, *_RLS):
        op.execute(statement)
    op.execute("REVOKE ALL ON studio.record_write_keys FROM PUBLIC")
    # The schema's defaults hand `dw_app` SELECT; written out so the grant does
    # not rest on them. No UPDATE: a stored result is never rewritten.
    op.execute(_for_role("dw_app", "REVOKE ALL ON studio.record_write_keys FROM dw_app;"))
    op.execute(
        _for_role("dw_app", "GRANT SELECT, INSERT, DELETE ON studio.record_write_keys TO dw_app;")
    )
    for role in ("dw_provisioner", "dw_agent_ro"):
        op.execute(_for_role(role, f"REVOKE ALL ON studio.record_write_keys FROM {role};"))

    op.execute(_PURGE)
    op.execute("REVOKE ALL ON FUNCTION studio.purge_expired_record_write_keys() FROM PUBLIC")
    op.execute(
        _for_role(
            "dw_app",
            "GRANT EXECUTE ON FUNCTION studio.purge_expired_record_write_keys() TO dw_app;",
        )
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION studio.purge_expired_record_write_keys()")
    op.execute("DROP TABLE studio.record_write_keys")
