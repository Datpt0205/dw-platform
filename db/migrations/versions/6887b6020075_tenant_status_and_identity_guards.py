"""tenant status and identity guards

Revision ID: 6887b6020075
Revises: b248d0664f47
Create Date: 2026-10-29 05:24:28.358667+00:00

foundations-hardening ticket 02 (R3.2, R4.4; FH7, FH11; ADR-0103 decision 8).

- `platform.guard_tenant_status()`, BEFORE UPDATE OF status on
  `platform.tenants`, for every role: a tenant leaves `offboarding` only for
  `offboarded`, and `offboarded` only for `offboarding` (the flow run again).
  An allowlist, so a status added later (`setup`) opens no way back from a
  purge. `ck_tenants_status_transition`, SQLSTATE 23514.
- `platform.guard_privileged_login_identity()`, BEFORE INSERT on
  `platform.external_identities`: a login identity (any provider but a chat
  link) for a platform operator or a support staff member is added only by
  `dw_provisioner`, the one role ADR-0103 decision 8 names; every other role is
  refused, so an application role created later fails closed.
  `ck_external_identities_privileged_relink`.
- `platform.guard_login_identity_kept()`, BEFORE DELETE: a login identity is
  deleted only by a role holding BYPASSRLS. A chat link stays deletable by
  `dw_app` (re-linking replaces it), and a delete cascading from
  `platform.users` runs as the table owner, so it passes.
  `ck_external_identities_login_kept`.
- `dw_app` loses UPDATE and TRUNCATE on `platform.external_identities`: no path
  of it updates an identity, and TRUNCATE skips row triggers.

The chat providers are `tables.CHANNEL_LINK_PROVIDERS`; a test reads both
functions from the catalog and holds them to it.

Neither function is SECURITY DEFINER: `current_user` must be the caller.
"""

from __future__ import annotations

from alembic import op

revision = "6887b6020075"
down_revision = "b248d0664f47"
branch_labels = None
depends_on = None

_CHAT_PROVIDERS = "ARRAY['zalo']::text[]"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.guard_tenant_status()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF (OLD.status = 'offboarding' AND NEW.status NOT IN ('offboarding', 'offboarded'))
               OR (OLD.status = 'offboarded' AND NEW.status NOT IN ('offboarded', 'offboarding'))
            THEN
                RAISE EXCEPTION 'tenant status cannot go from % to %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_tenants_status_transition';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER tenants_status_transition BEFORE UPDATE OF status ON platform.tenants"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_tenant_status()"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.guard_privileged_login_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF current_user = 'dw_provisioner' OR NEW.provider = ANY ({_CHAT_PROVIDERS}) THEN
                RETURN NEW;
            END IF;
            IF EXISTS (SELECT 1 FROM platform.platform_operators WHERE user_id = NEW.user_id)
               OR EXISTS (SELECT 1 FROM platform.support_staff WHERE user_id = NEW.user_id)
            THEN
                RAISE EXCEPTION 'a login identity of an operator or support staff member is'
                    ' added only by dw_provisioner'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_external_identities_privileged_relink';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER external_identities_privileged_relink"
        " BEFORE INSERT ON platform.external_identities"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_privileged_login_identity()"
    )
    op.execute(
        f"""
        CREATE FUNCTION platform.guard_login_identity_kept()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF OLD.provider = ANY ({_CHAT_PROVIDERS})
               OR (SELECT rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = current_user)
            THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'a login identity is deleted only by a maintenance role'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_external_identities_login_kept';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER external_identities_login_kept"
        " BEFORE DELETE ON platform.external_identities"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_login_identity_kept()"
    )
    op.execute("REVOKE UPDATE, TRUNCATE ON platform.external_identities FROM dw_app")


def downgrade() -> None:
    op.execute("GRANT UPDATE, TRUNCATE ON platform.external_identities TO dw_app")
    op.execute(
        "DROP TRIGGER IF EXISTS external_identities_login_kept ON platform.external_identities"
    )
    op.execute("DROP FUNCTION IF EXISTS platform.guard_login_identity_kept()")
    op.execute(
        "DROP TRIGGER IF EXISTS external_identities_privileged_relink"
        " ON platform.external_identities"
    )
    op.execute("DROP FUNCTION IF EXISTS platform.guard_privileged_login_identity()")
    op.execute("DROP TRIGGER IF EXISTS tenants_status_transition ON platform.tenants")
    op.execute("DROP FUNCTION IF EXISTS platform.guard_tenant_status()")
