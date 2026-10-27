"""studio schema and grants

Revision ID: 121e470ec23c
Revises: f1576bf82a5a
Create Date: 2026-10-27

The schema Studio's tables live in (ADR 0100 point 4; studio-skeleton R2).
Unlike `platform`, `knowledge` and `memory`, whose default privileges hand
`dw_app` full DML on every new table (`0001_platform_grants.sql`), `studio`
defaults to SELECT only: a Studio table states its writes in the migration
that creates it, so a table whose author forgot them fails on its first write
instead of opening the table to every write the application could make.

Nothing is granted to `dw_provisioner`, `dw_agent_ro` or PUBLIC. A service on
`dw_agent_ro` reads Studio record values through the platform API, where field
security applies (CLAUDE.md "A second language", condition 5; DO-13.3).
`test_privileges.py` asserts the schema from the catalog, by effective
privilege rather than by ACL entry.

The default privileges are those of `dw_migrator`, the role that runs these
migrations and owns what they create (`infra/compose/init/init-databases.sh`).
"""

from __future__ import annotations

from alembic import op

revision = "121e470ec23c"
down_revision = "f1576bf82a5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA studio")
    op.execute("REVOKE ALL ON SCHEMA studio FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dw_app') THEN
                RAISE WARNING USING
                    MESSAGE = 'role dw_app does not exist; it will have no access to studio',
                    HINT = 'CREATE ROLE dw_app LOGIN PASSWORD ''...''; then re-run this migration';
                RETURN;
            END IF;
            GRANT USAGE ON SCHEMA studio TO dw_app;
            -- SELECT, and only SELECT, by default: writes are granted per table.
            ALTER DEFAULT PRIVILEGES IN SCHEMA studio GRANT SELECT ON TABLES TO dw_app;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dw_app') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA studio REVOKE SELECT ON TABLES FROM dw_app;
            END IF;
        END
        $$
        """
    )
    op.execute("DROP SCHEMA studio")
