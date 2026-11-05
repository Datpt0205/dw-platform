"""offboarding request claims

Revision ID: 4fb92ed062dc
Revises: 2611a825560d
Create Date: 2026-11-05 10:42:12.706272+00:00

foundations-hardening ticket 09 (R11.15, R11.20; FH42).

`platform.tenant_offboarding_requests.claims integer NOT NULL DEFAULT 0`: how
many times the offboarding lane has claimed the request, the first claim from
`requested` counting as one. A request that kills its worker on every export
(discovery/09 measured one OOM) was claimed again every `_STALE_CLAIM_MINUTES`
for ever, taking the worker's other lanes down with it each time; the lane now
stops a stale `exporting` request claimed three times instead of claiming it a
fourth. The count is a column, like `attempts` of `platform.channel_deliveries`,
because it is control state: the audit log is not, and after the SQL purge no
workspace is left to write an audit row against.

`CHECK (claims >= 0)`. A request filed before this revision starts at 0, so it
gets three claims from here. `dw_app` already holds UPDATE on the table and no
INSERT or DELETE (5d9d89ffc716); `dw_provisioner` files a request without
naming the column. No grant changes; `test_privileges.py` asserts the set.
"""

from __future__ import annotations

from alembic import op

revision = "4fb92ed062dc"
down_revision = "2611a825560d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platform.tenant_offboarding_requests"
        " ADD COLUMN claims integer DEFAULT 0 NOT NULL,"
        " ADD CONSTRAINT ck_tenant_offboarding_requests_claims CHECK (claims >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE platform.tenant_offboarding_requests"
        " DROP CONSTRAINT ck_tenant_offboarding_requests_claims,"
        " DROP COLUMN claims"
    )
