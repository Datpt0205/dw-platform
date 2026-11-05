"""offboarding purges sod waivers

Revision ID: 9cc87820a05f
Revises: 4fb92ed062dc
Create Date: 2026-11-05 11:30:00.000000+00:00

foundations-hardening ticket 10 (R11.16, R11.21; FH43).

`platform.purge_tenant_sod_waivers(p_tenant uuid) RETURNS integer`, the
offboarding lane's step for `platform.sod_waivers`, in the shape of
`platform.purge_tenant_service_users` (557e6907195e): SECURITY DEFINER with a
fixed `search_path`, refusing with SQLSTATE 23514 (`ck_sod_waivers_purge`)
unless `p_tenant` is the transaction's own `app.tenant_id` (`IS DISTINCT FROM`,
so an unset or empty setting is refused too) and that tenant is
`offboarding`, then deleting the tenant's rows. The checks are the function's
own: it runs as its owner and so past the table's RLS, and
`trg_sod_waivers_not_in_use` fires on UPDATE only, so a call for a live
company would lift the waivers its members still rely on. EXECUTE is revoked
from PUBLIC and granted to `dw_app` alone; `dw_app` still holds no DELETE on
the table.

This reverses "offboarding keeps them with the audit log" of 6b26771e549d,
which is left as it was written. Every grant, confirmation and revocation of a
waiver already has its `platform.audit_events` row carrying the reason, kept
for the audit log's term; the waiver table has no term at all, so it kept the
grantor, the revoker and their reasons of a company that has left for ever
(failure-modes #6). The export bundle carries the table before the purge.
"""

from __future__ import annotations

from alembic import op

revision = "9cc87820a05f"
down_revision = "4fb92ed062dc"
branch_labels = None
depends_on = None

_FUNCTION = "platform.purge_tenant_sod_waivers(uuid)"

_PURGE_SOD_WAIVERS = """
    CREATE FUNCTION platform.purge_tenant_sod_waivers(p_tenant uuid) RETURNS integer
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_removed integer;
    BEGIN
        IF p_tenant IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
            RAISE EXCEPTION 'purge_tenant_sod_waivers runs for the transaction''s own tenant'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_sod_waivers_purge';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = p_tenant AND status = 'offboarding'
        ) THEN
            RAISE EXCEPTION 'purge_tenant_sod_waivers runs only for a tenant offboarding'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_sod_waivers_purge';
        END IF;
        DELETE FROM platform.sod_waivers WHERE tenant_id = p_tenant;
        GET DIAGNOSTICS v_removed = ROW_COUNT;
        RETURN v_removed;
    END
    $$
"""


# Guarded on the role existing, as in 557e6907195e.
_GRANT_TO_APP = f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dw_app') THEN
            GRANT EXECUTE ON FUNCTION {_FUNCTION} TO dw_app;
        END IF;
    END
    $$
"""


def upgrade() -> None:
    op.execute(_PURGE_SOD_WAIVERS)
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(_GRANT_TO_APP)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
