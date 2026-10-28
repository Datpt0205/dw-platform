"""idempotency keys bound to the caller

Revision ID: 3c54129c940c
Revises: 82e168f6d189
Create Date: 2026-10-28

app-standards ticket 02 (R2, ADR-0108 point 4). A replay is the first answer,
and only for the caller who asked the first question.

- `platform.idempotency_keys` gains `caller_ref` (`user:<principal_id>`, or
  `support:<grant_id>` under a support grant; `''` on a row written before this
  revision, which equals no real caller, so such a row is a conflict for
  everyone and never replays), `reservation_token` (the fence a take-over
  replaces, so a request that lost its reservation can neither complete nor
  release it), `response_headers` (only `ETag` and `Location`, by CHECK) and
  `request_preconditions` (the `If-Match` and `If-None-Match` sent, part of the
  fingerprint).
- `platform.effect_keys`: one row per effect an idempotent operation committed,
  written in the effect's own transaction. The HTTP key above is released when
  a handler fails after its effect committed; this row is what stops the retry
  from doing the effect again. Tenant-wide: "same workspace" is already inside
  `request_hash`, and a key follows its caller across the tenant's workspaces.
  `dw_app` reads, inserts and deletes (offboarding, and replacing an expired
  row, R2.37), never updates.
- `platform.effect_key_cutoff()`: the one owner of "has an effect key expired",
  a cutoff read from `platform.retention_terms`, so the purge and the route
  compare `created_at < cutoff` against the same number and the `(created_at)`
  index serves both. A missing term raises P0002 (R2.40).
- `platform.purge_expired_effect_keys()`: no argument, deletes only expired rows
  whose HTTP key row is gone (R2.31), returns the count.
"""

from __future__ import annotations

from alembic import op

revision = "3c54129c940c"
down_revision = "82e168f6d189"
branch_labels = None
depends_on = None

_TENANT = "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
_CALLER_REF = (
    "'^(user|support):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
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
    op.execute(
        f"""
        ALTER TABLE platform.idempotency_keys
            ADD COLUMN caller_ref text NOT NULL DEFAULT '',
            ADD COLUMN reservation_token uuid NOT NULL DEFAULT gen_random_uuid(),
            ADD COLUMN response_headers jsonb,
            ADD COLUMN request_preconditions text NOT NULL DEFAULT '',
            ADD CONSTRAINT ck_idempotency_keys_caller_ref
                CHECK (caller_ref = '' OR caller_ref ~ {_CALLER_REF}),
            ADD CONSTRAINT ck_idempotency_keys_response_headers_allowed
                CHECK (response_headers IS NULL OR (
                    jsonb_typeof(response_headers) = 'object'
                    AND response_headers - ARRAY['ETag', 'Location'] = '{{}}'::jsonb
                ))
        """
    )
    op.execute(
        f"""
        CREATE TABLE platform.effect_keys (
            tenant_id uuid NOT NULL,
            operation text NOT NULL,
            idempotency_key text NOT NULL,
            caller_ref text NOT NULL,
            request_hash text NOT NULL,
            result jsonb NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_effect_keys PRIMARY KEY (tenant_id, operation, idempotency_key),
            CONSTRAINT fk_effect_keys_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE CASCADE,
            CONSTRAINT ck_effect_keys_idempotency_key_length
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 255),
            CONSTRAINT ck_effect_keys_caller_ref CHECK (caller_ref ~ {_CALLER_REF}),
            CONSTRAINT ck_effect_keys_request_hash CHECK (request_hash ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_effect_keys_result CHECK (
                jsonb_typeof(result) = 'object' AND result - ARRAY['status', 'id'] = '{{}}'::jsonb
            )
        )
        """
    )
    # `tenant_id` leads the primary key, so the foreign key needs no index of
    # its own; the purge reads by age.
    op.execute("CREATE INDEX ix_effect_keys_created_at ON platform.effect_keys (created_at)")
    op.execute("ALTER TABLE platform.effect_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.effect_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_effect_keys ON platform.effect_keys "
        f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    # The schema's default privileges hand `dw_app` UPDATE as well; an effect
    # key is written once and never rewritten.
    op.execute(
        _for_role("dw_app", "REVOKE UPDATE, TRUNCATE ON platform.effect_keys FROM dw_app;")
    )
    for table in ("platform.effect_keys", "platform.idempotency_keys"):
        op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON {table} FROM dw_agent_ro;"))

    op.execute(
        """
        CREATE FUNCTION platform.effect_key_cutoff()
        RETURNS timestamp with time zone
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT now() - make_interval(
                days => platform.retention_term_days('platform.effect_keys')
            )
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.effect_key_cutoff() FROM PUBLIC")
    op.execute(
        _for_role("dw_app", "GRANT EXECUTE ON FUNCTION platform.effect_key_cutoff() TO dw_app;")
    )
    op.execute(
        """
        CREATE FUNCTION platform.purge_expired_effect_keys()
        RETURNS bigint
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            cutoff timestamp with time zone := platform.effect_key_cutoff();
            removed bigint;
        BEGIN
            -- An expired effect key stays while its HTTP key row lives: a
            -- reservation taken over late and abandoned must still find the
            -- effect it would otherwise do again (R2.31).
            DELETE FROM platform.effect_keys e
            WHERE e.created_at < cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM platform.idempotency_keys k
                  WHERE k.tenant_id = e.tenant_id
                    AND k.idempotency_key = e.idempotency_key
              );
            GET DIAGNOSTICS removed = ROW_COUNT;
            RETURN removed;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.purge_expired_effect_keys() FROM PUBLIC")
    op.execute(
        _for_role(
            "dw_app",
            "GRANT EXECUTE ON FUNCTION platform.purge_expired_effect_keys() TO dw_app;",
        )
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.purge_expired_effect_keys()")
    op.execute("DROP FUNCTION platform.effect_key_cutoff()")
    op.execute("DROP TABLE platform.effect_keys")
    op.execute(
        """
        ALTER TABLE platform.idempotency_keys
            DROP CONSTRAINT ck_idempotency_keys_response_headers_allowed,
            DROP CONSTRAINT ck_idempotency_keys_caller_ref,
            DROP COLUMN request_preconditions,
            DROP COLUMN response_headers,
            DROP COLUMN reservation_token,
            DROP COLUMN caller_ref
        """
    )
