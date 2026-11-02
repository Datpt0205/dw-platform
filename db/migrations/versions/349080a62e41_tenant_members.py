"""tenant members

Revision ID: 349080a62e41
Revises: 65443fe9fd9a
Create Date: 2026-11-02 06:40:25.891941+00:00

org-and-principals ticket 02 (R4.1-R4.5, R4.7, R4.8, R5.1; OP4-OP7). A
person's standing in a company is one row with a status, and every
membership hangs from it.

- `platform.tenant_members`: `(tenant_id, user_id)`, `status` one of
  `invited`, `active`, `suspended` with no default, and `status_changed_at`,
  moved by a trigger whenever `status` changes value (yielding to a value the
  statement states, as `touch_updated_at` does since 0004) so every path that
  changes a status moves it: its reader is the `principal_inactive` notice's
  `source_key` (workflow-engine R5.20). Tenant-wide on purpose: a person's
  standing belongs to the whole company, not to a workspace.
- RLS: the tenant policy, and `tenant_members_self_select`, SELECT only by
  `app.principal_id`, the shape of `memberships_self_select`, so sign-in reads
  the person's own standing in every company before a tenant is chosen. No
  write policy reads the principal: no connection changes its own status.
- Backfill: one row per `(tenant_id, user_id)` of `platform.memberships`,
  `active` for a service user (ADR-0103 decision 2: its status is this row) or
  a person who has signed in (a login identity, not a linked chat, the rule
  `member_status()` inferred until now), `invited` otherwise. Then
  `fk_memberships_tenant_members` ON DELETE CASCADE, carried by the existing
  `ix_memberships_tenant_user`.
- `platform.activate_invited_members(uuid)`: SECURITY DEFINER, because sign-in
  runs before any tenant is bound; it moves the person's rows from `invited`
  to `active` in every company and never from `suspended` (reopening takes two
  people, D11). EXECUTE for `dw_app` alone.
- `dw_app` reads and writes the table (DELETE for offboarding, which purges
  exactly what `dw_app` may delete); `dw_provisioner` SELECT, INSERT, for
  `grant_role`; `dw_agent_ro` nothing.
"""

from __future__ import annotations

from alembic import op

revision = "349080a62e41"
down_revision = "65443fe9fd9a"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires since cfae5f2d4a13: every setting is
# read inside a sub-SELECT, once per statement.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_PRINCIPAL = "(user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))"

# What `dw_provisioner` holds here, beside 0fdd32a39d87's `PROVISIONER`;
# mirrored by scripts/create_provisioner_role.py, both held to the catalog by
# test_privileges.py.
PROVISIONER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("platform.tenant_members", "SELECT, INSERT", ()),
)

# `tables.CHANNEL_LINK_PROVIDERS` when this revision was written: a linked chat
# is a delivery address, not a sign-in.
_CHANNEL_LINK_PROVIDERS = "('zalo')"


# One row per `(tenant_id, user_id)` of a membership (R4.1). Held to its rule by
# `test_tenant_member_status.py`, which runs it on planted people.
BACKFILL = f"""
    INSERT INTO platform.tenant_members (tenant_id, user_id, status)
    SELECT DISTINCT m.tenant_id, m.user_id,
           CASE WHEN u.kind = 'service' OR EXISTS (
                    SELECT 1 FROM platform.external_identities e
                    WHERE e.user_id = u.id AND e.provider NOT IN {_CHANNEL_LINK_PROVIDERS}
                ) THEN 'active' ELSE 'invited' END
    FROM platform.memberships m
    JOIN platform.users u ON u.id = m.user_id
    ON CONFLICT (tenant_id, user_id) DO NOTHING
"""


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
    op.execute(
        """
        CREATE TABLE platform.tenant_members (
            tenant_id uuid NOT NULL,
            user_id uuid NOT NULL,
            status text NOT NULL,
            status_changed_at timestamp with time zone DEFAULT now() NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_tenant_members PRIMARY KEY (tenant_id, user_id),
            CONSTRAINT fk_tenant_members_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE CASCADE,
            CONSTRAINT fk_tenant_members_user_id_users
                FOREIGN KEY (user_id) REFERENCES platform.users(id) ON DELETE CASCADE,
            CONSTRAINT ck_tenant_members_status
                CHECK (status IN ('invited', 'active', 'suspended'))
        )
        """
    )
    op.execute("CREATE INDEX ix_tenant_members_user_id ON platform.tenant_members (user_id)")
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.tenant_members"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )
    op.execute(
        """
        CREATE FUNCTION platform.touch_status_changed_at() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status
               AND NEW.status_changed_at IS NOT DISTINCT FROM OLD.status_changed_at THEN
                NEW.status_changed_at := now();
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER touch_status_changed_at BEFORE UPDATE OF status"
        " ON platform.tenant_members"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_status_changed_at()"
    )

    # RLS. One literal per policy head: `verify_invariants.py` reads this text.
    op.execute("ALTER TABLE platform.tenant_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.tenant_members FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_tenant_members ON platform.tenant_members"
        f" USING {_TENANT} WITH CHECK {_TENANT}"
    )
    op.execute(
        "CREATE POLICY tenant_members_self_select ON platform.tenant_members"
        f" FOR SELECT USING {_PRINCIPAL}"
    )

    # Backfill, as the migrator (no RLS in the way), then the key.
    op.execute(BACKFILL)
    op.execute(
        "ALTER TABLE platform.memberships ADD CONSTRAINT fk_memberships_tenant_members"
        " FOREIGN KEY (tenant_id, user_id)"
        " REFERENCES platform.tenant_members (tenant_id, user_id) ON DELETE CASCADE"
    )

    # R4.5: the one way an invitation becomes a member, at sign-in.
    op.execute(
        """
        CREATE FUNCTION platform.activate_invited_members(p_user_id uuid) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        DECLARE
            activated integer;
        BEGIN
            UPDATE platform.tenant_members SET status = 'active'
            WHERE user_id = p_user_id AND status = 'invited';
            GET DIAGNOSTICS activated = ROW_COUNT;
            RETURN activated;
        END
        $$
        """
    )
    for function in (
        "platform.touch_status_changed_at()",
        "platform.activate_invited_members(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(
        _for_role(
            "dw_app",
            "GRANT EXECUTE ON FUNCTION platform.activate_invited_members(uuid) TO dw_app;",
        )
    )

    table = "platform.tenant_members"
    op.execute(_for_role("dw_app", f"REVOKE TRUNCATE ON {table} FROM dw_app;"))
    op.execute(_for_role("dw_app", f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dw_app;"))
    op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON {table} FROM dw_agent_ro;"))
    for name, verbs, _ in PROVISIONER:
        op.execute(_for_role("dw_provisioner", f"GRANT {verbs} ON {name} TO dw_provisioner;"))


def downgrade() -> None:
    op.execute(
        "ALTER TABLE platform.memberships DROP CONSTRAINT IF EXISTS fk_memberships_tenant_members"
    )
    op.execute("DROP FUNCTION IF EXISTS platform.activate_invited_members(uuid)")
    op.execute("DROP TABLE IF EXISTS platform.tenant_members")
    op.execute("DROP FUNCTION IF EXISTS platform.touch_status_changed_at()")
