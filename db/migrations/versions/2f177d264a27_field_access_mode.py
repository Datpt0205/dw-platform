"""field access mode

Revision ID: 2f177d264a27
Revises: 996c234cfde3
Create Date: 2026-11-05 01:05:30.338481+00:00

field-security ticket 01 (R1.1-R1.3, R1.6, R1.7; FS1, FS11, FS12, FS15;
ADR-0106 decision 2). Every field of a company object is `open` or `secured`:

- `studio.field_defs.access_mode text NOT NULL DEFAULT 'open'`, held to the
  two values by `ck_field_defs_access_mode`.
- The rows custom-objects/02 already made are filled in before any new CHECK
  (R1.7): `ADD COLUMN ... DEFAULT` passes no INSERT trigger, so without it every
  personal-data field defined so far would read `open`. Their `updated_at`
  stays: the touch trigger is off for that one statement, as the backfill
  states no change a person made.
- `ck_field_defs_sensitive_is_secured`: a sensitive field is never open (R1.3).
- `trg_field_defs_secure_personal_data`, BEFORE INSERT: a field holding personal
  data (`pd_category <> 'none'`) is created `secured`, whatever the statement
  says (R1.2). Only at creation: opening a `basic` field later is a version a
  second person publishes (D11), and the CHECK keeps a sensitive one shut.
- `trg_z_bump_access_version_access_mode`, a constraint trigger deferred to
  commit, AFTER UPDATE OF `access_mode` and only when it changed: the tenant's
  access version moves, so an access context cached under the old version is
  not read again (R1.6). Deferred, so the version row is locked after every
  role row the publish's guards lock, the one lock order of tenant-rbac/04;
  named `trg_z_` to sort last like every trigger calling the same function, and
  apart from tenant-rbac/04's `trg_z_bump_access_version` (INSERT OR DELETE).
- `dw_app` may UPDATE `access_mode`, the one writer being the `object` kind's
  publish hook (`MetadataService.apply`, R1.8); the provisioner and
  `dw_agent_ro` gain nothing.
"""

from __future__ import annotations

from alembic import op

revision = "2f177d264a27"
down_revision = "996c234cfde3"
branch_labels = None
depends_on = None

_COLUMN = (
    "ALTER TABLE studio.field_defs ADD COLUMN access_mode text NOT NULL DEFAULT 'open'"
    " CONSTRAINT ck_field_defs_access_mode CHECK (access_mode IN ('open', 'secured'))"
)

# R1.7, before the CHECK below is added: the personal-data rows already defined.
_BACKFILL = (
    "ALTER TABLE studio.field_defs DISABLE TRIGGER touch_updated_at",
    "UPDATE studio.field_defs SET access_mode = 'secured' WHERE pd_category <> 'none'",
    "ALTER TABLE studio.field_defs ENABLE TRIGGER touch_updated_at",
)

_SENSITIVE_IS_SECURED = (
    "ALTER TABLE studio.field_defs ADD CONSTRAINT ck_field_defs_sensitive_is_secured"
    " CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')"
)

_SECURE_PERSONAL_FIELD = """
    CREATE FUNCTION studio.secure_personal_field() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
    AS $$
    BEGIN
        IF NEW.pd_category <> 'none' THEN
            NEW.access_mode := 'secured';
        END IF;
        RETURN NEW;
    END
    $$
"""

_TRIGGERS = (
    "CREATE TRIGGER trg_field_defs_secure_personal_data BEFORE INSERT ON studio.field_defs"
    " FOR EACH ROW EXECUTE FUNCTION studio.secure_personal_field()",
    "CREATE CONSTRAINT TRIGGER trg_z_bump_access_version_access_mode"
    " AFTER UPDATE OF access_mode ON studio.field_defs DEFERRABLE INITIALLY DEFERRED"
    " FOR EACH ROW WHEN (OLD.access_mode IS DISTINCT FROM NEW.access_mode)"
    " EXECUTE FUNCTION platform.bump_access_version()",
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
    op.execute(_COLUMN)
    for statement in _BACKFILL:
        op.execute(statement)
    op.execute(_SENSITIVE_IS_SECURED)
    op.execute(_SECURE_PERSONAL_FIELD)
    # A trigger function: no role calls it.
    op.execute("REVOKE ALL ON FUNCTION studio.secure_personal_field() FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    op.execute(_for_role("dw_app", "GRANT UPDATE (access_mode) ON studio.field_defs TO dw_app;"))


def downgrade() -> None:
    op.execute(_for_role("dw_app", "REVOKE UPDATE (access_mode) ON studio.field_defs FROM dw_app;"))
    op.execute("DROP TRIGGER trg_z_bump_access_version_access_mode ON studio.field_defs")
    op.execute("DROP TRIGGER trg_field_defs_secure_personal_data ON studio.field_defs")
    op.execute("DROP FUNCTION studio.secure_personal_field()")
    op.execute("ALTER TABLE studio.field_defs DROP CONSTRAINT ck_field_defs_sensitive_is_secured")
    op.execute("ALTER TABLE studio.field_defs DROP COLUMN access_mode")
