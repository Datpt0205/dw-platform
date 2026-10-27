"""retention terms table

Revision ID: 82e168f6d189
Revises: a77c5408a1f4
Create Date: 2026-10-27

The runtime copy of the terms in the pinned retention fragment set
(telemetry-and-audit R5.9-R5.12; V4.21). A narrow purge function takes no
argument, so no caller can widen it; it reads its own term here instead, and a
lawyer's new number reaches it as an edited fragment, not as code or a
migration.

- `platform.retention_terms (store_key, term_days)`: one row per fragment with a
  term in days that is `enforced`. Platform-wide, so no `tenant_id` and no RLS:
  a term is the deployment's, never one tenant's.
- `dw_app` keeps SELECT and loses INSERT, UPDATE, DELETE and TRUNCATE, which the
  schema's default privileges handed it (`0001_platform_grants.sql`), as in
  648e2f7c3edb: the terms change only through the loader.
- `dw_provisioner` gets SELECT, INSERT, UPDATE and DELETE, guarded on the role
  existing as in 5d9d89ffc716: the loader runs as it, in the `migrate` job.
  A cluster that gains the role later receives the same grants from
  `scripts/create_provisioner_role.py`.
- `platform.retention_term_days(text)`: the term of one key, or SQLSTATE P0002
  naming the key when there is no row, so a purge function asking for a term
  nobody loaded stops instead of purging on a default. No role is granted
  EXECUTE: only the narrow SECURITY DEFINER purge functions, owned by the
  migrator, call it.
"""

from __future__ import annotations

from alembic import op

revision = "82e168f6d189"
down_revision = "a77c5408a1f4"
branch_labels = None
depends_on = None


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
        CREATE TABLE platform.retention_terms (
            store_key text NOT NULL,
            term_days integer NOT NULL,
            CONSTRAINT pk_retention_terms PRIMARY KEY (store_key),
            CONSTRAINT ck_retention_terms_term_days_positive CHECK (term_days > 0)
        )
        """
    )
    op.execute(
        _for_role(
            "dw_app",
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform.retention_terms FROM dw_app;",
        )
    )
    op.execute(_for_role("dw_app", "GRANT SELECT ON platform.retention_terms TO dw_app;"))
    op.execute(
        _for_role(
            "dw_provisioner",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.retention_terms TO dw_provisioner;",
        )
    )
    op.execute(
        """
        CREATE FUNCTION platform.retention_term_days(p_store_key text)
        RETURNS integer
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            -- Not `found`: PL/pgSQL names its row-found flag FOUND, and a
            -- local of that name shadows it in the IF below.
            term integer;
        BEGIN
            SELECT term_days INTO term
            FROM platform.retention_terms
            WHERE store_key = p_store_key;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'no retention term is loaded for %', p_store_key
                    USING ERRCODE = 'P0002';
            END IF;
            RETURN term;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.retention_term_days(text) FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.retention_term_days(text)")
    op.execute("DROP TABLE platform.retention_terms")
