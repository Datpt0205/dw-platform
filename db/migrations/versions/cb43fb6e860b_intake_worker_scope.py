"""intake worker scope

Revision ID: cb43fb6e860b
Revises: 0c3e9392cc06
Create Date: 2026-10-30

`platform.intake_worker_scope(dw_id)` (leadcare R2.6): the one read the signed
lead intake makes before it has a tenant context. It answers a DW's tenant,
workspace and state, nothing else; SECURITY DEFINER because `dw_app` with no
context reads no row of `platform.digital_workers`. EXECUTE for `dw_app` only.
The intake then verifies the signature with the DW's derived key and works
under that tenant and workspace.
"""

from __future__ import annotations

from alembic import op

revision = "cb43fb6e860b"
down_revision = "0c3e9392cc06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION platform.intake_worker_scope(p_dw_id uuid)
        RETURNS TABLE (tenant_id uuid, workspace_id uuid, state text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
            SELECT d.tenant_id, d.workspace_id, d.state
            FROM platform.digital_workers d
            WHERE d.id = p_dw_id
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION platform.intake_worker_scope(uuid) FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dw_app') THEN
                GRANT EXECUTE ON FUNCTION platform.intake_worker_scope(uuid) TO dw_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION platform.intake_worker_scope(uuid)")
