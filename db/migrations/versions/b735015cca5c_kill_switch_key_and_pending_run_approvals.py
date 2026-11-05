"""kill switch key and pending run approvals

Revision ID: b735015cca5c
Revises: 66777ec67d16
Create Date: 2026-11-05 09:00:00.000000+00:00

agent-lifecycle ticket 05 (R8.1, R8.2, R8.6; AL13, AL14, AL16). Data and one
index, no table: `platform.control_switches`, its guard (which already lifts a
kill only with an approved, second-person `studio.lifecycle.revive` request
naming the row) and the one-pending-lift index are ticket 01's (8efd60e59d32).

- The permission `studio.lifecycle.kill`, by tenant-rbac/01's classes and
  tenant-rbac/02's columns: `workspace` depth (a kill is of one component,
  checked at its `owning_workspace_id`), `standard` risk (not a `platform.*`
  key), `active`, owned by `dw_platform`, `tenant_grantable`. It is the key of
  both routes and the stamp of the revive request's decider; the revive is an
  approval type, not a key, as `studio.lifecycle.unfreeze` is.
- The `org_admin` template carries it, as 8efd60e59d32 did for
  `studio.lifecycle.freeze` (tenant-rbac R3.2), so a company cloned from it
  later has more than one holder of the revive stamp; a role already cloned is
  not touched.
- `ix_approval_requests_tenant_id_run_id_pending`: the `control_switch` lane
  cancels the pending requests of each run it cancels, by `run_id`; without
  it that read scans every pending request of the company once per run.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b735015cca5c"
down_revision = "66777ec67d16"
branch_labels = None
depends_on = None

KILL = "studio.lifecycle.kill"


def upgrade() -> None:
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    op.execute(
        sa.text(
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
            " 'dw_platform', true)"
            " ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=KILL, l="Tắt khẩn cấp và xin bật lại agent, quy trình")
    )
    # The template a company cloned later starts from; cloned roles keep theirs.
    op.execute(
        sa.text(
            "UPDATE platform.roles SET scopes = scopes || jsonb_build_array(CAST(:k AS text))"
            " WHERE key = 'org_admin' AND NOT scopes @> jsonb_build_array(CAST(:k AS text))"
        ).bindparams(k=KILL)
    )
    op.execute(
        "CREATE INDEX ix_approval_requests_tenant_id_run_id_pending"
        " ON platform.approval_requests (tenant_id, run_id)"
        " WHERE status = 'pending' AND run_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX platform.ix_approval_requests_tenant_id_run_id_pending")
    op.execute(
        sa.text(
            "UPDATE platform.roles SET scopes = scopes - :k WHERE key = 'org_admin'"
        ).bindparams(k=KILL)
    )
    op.execute(
        sa.text(
            "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
        ).bindparams(k=KILL)
    )
    op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=KILL))
