"""The permission `studio.publish.approve` (agent-lifecycle ticket 04, step 1).

The stamp of every `studio.publish.<kind>` request (R5.1, R5.4; ADR-0004,
amendment 2026-10-07): a decider holds it, besides `approvals.decide`, at a
depth reaching the component's owning workspace, the request's own. One row of
the code-owned catalogue, with every NOT NULL column of `platform.permissions`
as tenant-rbac/01 and /02 left it (`risk` `standard`, `tenant_grantable`).
It is already one of `platform.owner_permission_keys()` (revision
b5677d345bc1): no operator or support staff member holds it in a customer's
tenant, and the owners holding it are counted. Which roles grant it is the
company's own data; no template is changed.

Revision ID: 0353c313569f
Revises: 9cc87820a05f
Create Date: 2026-11-05 12:00:17.336737+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0353c313569f"
down_revision = "9cc87820a05f"
branch_labels = None
depends_on = None

KEY = "studio.publish.approve"
LABEL = "Duyệt phát hành phiên bản agent, quy trình, đối tượng và nguồn dữ liệu"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
            " 'dw_studio', true)"
            " ON CONFLICT (key) DO NOTHING"
        ).bindparams(k=KEY, l=LABEL)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
        ).bindparams(k=KEY)
    )
    op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=KEY))
