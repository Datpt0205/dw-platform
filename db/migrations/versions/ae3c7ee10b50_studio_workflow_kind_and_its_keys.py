"""studio workflow kind and its keys

Revision ID: ae3c7ee10b50
Revises: d2b57239ef50
Create Date: 2026-11-04 17:51:19.398985+00:00

workflow-engine ticket 01 (R1.4, R1.5; OPS-b, H-19; tenant-config R2.14,
R2.15). Data only, no table:

- The `workflow` row of `studio.artifact_kinds`, beside its registry entry
  (`dw_studio.kinds.workflow_kind`), with a quality gate (R1.5): a gated kind
  stays at `evaluating` until agent-lifecycle 06 builds the gate.
- Three permissions, by tenant-rbac/01's classes (step 3) and tenant-rbac/02's
  (step 1): `studio.workflows.read` and `studio.workflows.edit`, the kind's
  read and write keys, and `studio.workflows.test`, the key a test run asks
  (H-19), which the run door's table names for `(workflow, test)`
  (`dw_api.bootstrap.studio._RUN_KEYS`, workflow-engine 02). Each is
  workspace depth (a workflow belongs to a workspace), `standard` risk (not a
  `platform.*` key), `active`, owned by `dw_studio`, and `tenant_grantable`
  (only `platform.admin` is not). The submit key, `studio.versions.submit`,
  is agent-lifecycle 03's (revision 6503c6f309b1).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ae3c7ee10b50"
down_revision = "d2b57239ef50"
branch_labels = None
depends_on = None

# (key, label): workspace depth, standard risk (tenant-rbac/01's classes).
PERMISSIONS = (
    ("studio.workflows.read", "Xem quy trình của công ty"),
    ("studio.workflows.edit", "Tạo và sửa bản nháp quy trình"),
    ("studio.workflows.test", "Chạy thử quy trình"),
)


def upgrade() -> None:
    # OPS-b: the kind's row beside its registry entry, with a gate (R1.5).
    op.execute(
        "INSERT INTO studio.artifact_kinds (kind, has_quality_gate) VALUES ('workflow', true)"
    )
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    for key, label in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
                " 'dw_studio', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label)
        )


def downgrade() -> None:
    for key, _label in PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
            ).bindparams(k=key)
        )
        op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=key))
    op.execute("DELETE FROM studio.artifact_kinds WHERE kind = 'workflow'")
