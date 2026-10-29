"""narrow app role writes

Revision ID: 0fdd32a39d87
Revises: 6887b6020075
Create Date: 2026-10-29 12:16:04.099417+00:00

foundations-hardening ticket 03 (R5.1, R5.2, R5.4).

`ALTER DEFAULT PRIVILEGES` (0001_platform_grants.sql) handed `dw_app` every
verb on every platform table. No application path writes the operator list or
the plan catalogue, and none updates or deletes a user: only the first sign-in
and an invitation create one. Application credentials could therefore make
anyone a platform operator, or rewrite a plan's limits, and no application code
would have been the reason.

- `dw_app` loses INSERT, UPDATE, DELETE and TRUNCATE on `platform.platform_operators`
  and `platform.plans`, and UPDATE, DELETE and TRUNCATE on `platform.users`.
- `dw_provisioner` holds exactly what the code that connects as it runs, read
  from that code, table by table and, for `support_grants`, column by column:
  `SqlProvisioningRepository`, the `retention_terms` loader of the migrate job
  (82e168f6d189) and the operator login identity that only it may add (R4.4,
  6887b6020075). `scripts/create_provisioner_role.py` grants the same set and
  `test_privileges.py` compares the two with the catalog.

Each statement is guarded on the role existing, as in 648e2f7c3edb. Downgrade
gives back what the catalog held before.
"""

from __future__ import annotations

from alembic import op

revision = "0fdd32a39d87"
down_revision = "6887b6020075"
branch_labels = None
depends_on = None

# (table, table verbs, columns that may be updated). Mirrored by
# scripts/create_provisioner_role.py; test_privileges.py holds both to the catalog.
PROVISIONER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("platform.tenants", "SELECT, INSERT, UPDATE", ()),
    ("platform.workspaces", "SELECT, INSERT", ()),
    ("platform.entitlements", "SELECT, INSERT", ()),
    ("platform.memberships", "SELECT, INSERT, UPDATE", ()),
    ("platform.users", "SELECT", ()),
    ("platform.plans", "SELECT", ()),
    ("platform.roles", "SELECT", ()),
    ("platform.platform_operators", "SELECT, INSERT, DELETE", ()),
    ("platform.support_staff", "SELECT, INSERT, DELETE", ()),
    (
        "platform.support_grants",
        "SELECT",
        ("activated_at", "assigned_by", "expires_at", "staff_user_id", "status"),
    ),
    ("platform.audit_events", "INSERT", ()),
    ("platform.provisioning_audit", "SELECT, INSERT", ()),
    ("platform.tenant_offboarding_requests", "SELECT, INSERT", ()),
    ("platform.retention_terms", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.external_identities", "SELECT, INSERT", ()),
)

# What the catalog held before this revision, for downgrade.
_PROVISIONER_BEFORE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("platform.tenants", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.workspaces", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.entitlements", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.memberships", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.users", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.plans", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.roles", "SELECT", ()),
    ("platform.platform_operators", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.support_staff", "SELECT, INSERT, DELETE", ()),
    (
        "platform.support_grants",
        "SELECT",
        ("activated_at", "assigned_by", "expires_at", "staff_user_id", "status"),
    ),
    ("platform.audit_events", "INSERT", ()),
    ("platform.provisioning_audit", "SELECT, INSERT, UPDATE, DELETE", ()),
    ("platform.tenant_offboarding_requests", "SELECT, INSERT, UPDATE", ()),
    ("platform.retention_terms", "SELECT, INSERT, UPDATE, DELETE", ()),
)

_APP_NARROWED = (
    ("platform.platform_operators", "INSERT, UPDATE, DELETE, TRUNCATE"),
    ("platform.plans", "INSERT, UPDATE, DELETE, TRUNCATE"),
    ("platform.users", "UPDATE, DELETE, TRUNCATE"),
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


def _set_provisioner(grants: tuple[tuple[str, str, tuple[str, ...]], ...]) -> None:
    tables = sorted({table for table, _, _ in PROVISIONER + _PROVISIONER_BEFORE})
    for table in tables:
        op.execute(_for_role("dw_provisioner", f"REVOKE ALL ON {table} FROM dw_provisioner;"))
    op.execute(
        _for_role(
            "dw_provisioner",
            "REVOKE UPDATE (activated_at, assigned_by, expires_at, staff_user_id, status)"
            " ON platform.support_grants FROM dw_provisioner;",
        )
    )
    for table, verbs, columns in grants:
        op.execute(_for_role("dw_provisioner", f"GRANT {verbs} ON {table} TO dw_provisioner;"))
        if columns:
            op.execute(
                _for_role(
                    "dw_provisioner",
                    f"GRANT UPDATE ({', '.join(columns)}) ON {table} TO dw_provisioner;",
                )
            )


def upgrade() -> None:
    for table, verbs in _APP_NARROWED:
        op.execute(_for_role("dw_app", f"REVOKE {verbs} ON {table} FROM dw_app;"))
    _set_provisioner(PROVISIONER)


def downgrade() -> None:
    for table, verbs in _APP_NARROWED:
        op.execute(
            _for_role("dw_app", f"GRANT {verbs.replace(', TRUNCATE', '')} ON {table} TO dw_app;")
        )
    _set_provisioner(_PROVISIONER_BEFORE)
