"""platform digital workers

Revision ID: be93e0c26a4c
Revises: 3f1cb1d4cece
Create Date: 2026-10-30 03:37:16.868702+00:00

digital-worker ticket 01 (R1.1-R1.3, R1.5-R1.11, R1.13, R1.15-R1.18, R2.1-R2.4;
ADR-0103 decisions 2-4, ADR-0128 decisions 1-4). A Digital Worker is company
data with a service principal of its own.

- `platform.users` gains `kind` (`human` or `service`) and `owner_tenant_id`,
  set exactly when the user is a service principal (ADR-0103 decision 2).
- `platform.service_principals`: one row per service user, tenant-wide (its
  `owning_workspace_id` is held by the composite RESTRICT key R9.4 asks for).
  `owner_user_id` is the Business Owner of the DW and the only place that fact
  is kept; `platform.guard_accountable_owner()` refuses an owner who is not a
  human member of the principal's tenant (R1.16), and the principal's own
  `platform.users` row must be a service user of that same tenant.
- `platform.digital_workers` and `platform.dw_decision_classes`, under the one
  workspace policy shape of `CLAUDE.md`. Each reaches its parent through a
  composite key carrying `tenant_id`, because a foreign key check does not pass
  through RLS and a one-column key would let tenant A's row name tenant B's
  workspace or DW (the shape of `uq_workspaces_tenant_id_id` in 3f1cb1d4cece).
  `earned_level <= ceiling` is a CHECK, by the order of the five levels.
- A login identity is never linked to a service user
  (`ck_external_identities_human_only`, R1.11).
- A DW principal's memberships take no new role or permission set and no new
  workspace once its DW exists (`ck_memberships_dw_principal_roles_fixed`,
  R1.17); narrowing and removing stay possible. SECURITY DEFINER, because the
  DW row may sit in a workspace the caller's RLS does not reach.
- `dw.read` joins every membership role and `dw.manage` joins `org_admin`.
- `dw_app` reads, inserts, updates and deletes the three new tables. The spec
  grants no DELETE ("offboarding deletes with its own role"), but offboarding
  in this repository runs as `dw_app` and purges exactly the tenant tables
  `dw_app` may DELETE from (`offboarding.py`, `_CATALOG_PURGEABLE`); without it
  `platform.digital_workers` would hold its workspace by RESTRICT and no tenant
  with a DW could ever be offboarded. No application path deletes a row.
"""

from __future__ import annotations

from alembic import op

revision = "be93e0c26a4c"
down_revision = "3f1cb1d4cece"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires since cfae5f2d4a13: every setting is
# read inside a sub-SELECT, once per statement.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_WORKSPACE = "(workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid))"
_SCOPE = "((SELECT current_setting('app.workspace_scope', true)) = 'tenant')"
_NARROWED = f"({_TENANT} AND ({_WORKSPACE} OR {_SCOPE}))"

_LEVELS = "ARRAY['A0', 'A1', 'A2', 'A3', 'A4']"

# Every membership role reads DWs; only the organisation admin creates one.
_MEMBER_ROLES = ("member", "approver", "manager", "director", "executive", "org_admin")

_NEW_TABLES = (
    "platform.service_principals",
    "platform.digital_workers",
    "platform.dw_decision_classes",
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
    op.execute(
        """
        ALTER TABLE platform.users
            ADD COLUMN kind text DEFAULT 'human' NOT NULL,
            ADD COLUMN owner_tenant_id uuid,
            ADD CONSTRAINT ck_users_kind CHECK (kind IN ('human', 'service')),
            ADD CONSTRAINT ck_users_service_has_owner_tenant
                CHECK ((kind = 'service') = (owner_tenant_id IS NOT NULL)),
            ADD CONSTRAINT fk_users_owner_tenant_id_tenants
                FOREIGN KEY (owner_tenant_id) REFERENCES platform.tenants(id) ON DELETE CASCADE
        """
    )
    op.execute("CREATE INDEX ix_users_owner_tenant_id ON platform.users (owner_tenant_id)")

    op.execute(
        """
        CREATE TABLE platform.service_principals (
            user_id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            owning_workspace_id uuid NOT NULL,
            name text NOT NULL,
            owner_user_id uuid,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_service_principals PRIMARY KEY (user_id),
            CONSTRAINT uq_service_principals_tenant_id_user_id UNIQUE (tenant_id, user_id),
            CONSTRAINT fk_service_principals_user_id_users
                FOREIGN KEY (user_id) REFERENCES platform.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_service_principals_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE CASCADE,
            CONSTRAINT fk_service_principals_owning_workspace
                FOREIGN KEY (tenant_id, owning_workspace_id)
                REFERENCES platform.workspaces(tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_service_principals_owner_user_id_users
                FOREIGN KEY (owner_user_id) REFERENCES platform.users(id) ON DELETE SET NULL,
            CONSTRAINT ck_service_principals_name CHECK (char_length(name) BETWEEN 1 AND 120)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_service_principals_owning_workspace"
        " ON platform.service_principals (tenant_id, owning_workspace_id)"
    )
    op.execute(
        "CREATE INDEX ix_service_principals_owner_user_id"
        " ON platform.service_principals (owner_user_id)"
    )

    op.execute(
        f"""
        CREATE TABLE platform.digital_workers (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            principal_user_id uuid NOT NULL,
            key text NOT NULL,
            name text NOT NULL,
            mandate text NOT NULL,
            work_kinds text[] NOT NULL,
            allowed_tools text[] NOT NULL,
            workflow_key text NOT NULL,
            workflow_version text NOT NULL,
            parameters jsonb DEFAULT '{{}}'::jsonb NOT NULL,
            state text DEFAULT 'draft' NOT NULL,
            technical_owner_id uuid NOT NULL,
            work_assigner_id uuid NOT NULL,
            validator_id uuid NOT NULL,
            created_by uuid NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_digital_workers PRIMARY KEY (id),
            CONSTRAINT uq_digital_workers_tenant_id_workspace_id_id
                UNIQUE (tenant_id, workspace_id, id),
            CONSTRAINT uq_digital_workers_tenant_id_key UNIQUE (tenant_id, key),
            CONSTRAINT uq_digital_workers_principal_user_id UNIQUE (principal_user_id),
            CONSTRAINT fk_digital_workers_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants(id) ON DELETE RESTRICT,
            CONSTRAINT fk_digital_workers_workspace
                FOREIGN KEY (tenant_id, workspace_id)
                REFERENCES platform.workspaces(tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_digital_workers_principal
                FOREIGN KEY (tenant_id, principal_user_id)
                REFERENCES platform.service_principals(tenant_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT fk_digital_workers_technical_owner_id_users
                FOREIGN KEY (technical_owner_id) REFERENCES platform.users(id) ON DELETE RESTRICT,
            CONSTRAINT fk_digital_workers_work_assigner_id_users
                FOREIGN KEY (work_assigner_id) REFERENCES platform.users(id) ON DELETE RESTRICT,
            CONSTRAINT fk_digital_workers_validator_id_users
                FOREIGN KEY (validator_id) REFERENCES platform.users(id) ON DELETE RESTRICT,
            CONSTRAINT ck_digital_workers_key CHECK (key ~ '^[a-z][a-z0-9_]{{1,39}}$'),
            CONSTRAINT ck_digital_workers_name CHECK (char_length(name) BETWEEN 1 AND 120),
            CONSTRAINT ck_digital_workers_mandate
                CHECK (char_length(mandate) BETWEEN 1 AND 2000),
            CONSTRAINT ck_digital_workers_work_kinds CHECK (cardinality(work_kinds) >= 1),
            CONSTRAINT ck_digital_workers_workflow_version
                CHECK (workflow_version ~ '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$'),
            CONSTRAINT ck_digital_workers_parameters CHECK (jsonb_typeof(parameters) = 'object'),
            CONSTRAINT ck_digital_workers_state
                CHECK (state IN ('draft', 'operating', 'paused', 'retired'))
        )
        """
    )
    # The list pages newest first inside one workspace (R1.5 keyset); the index
    # leads with what RLS supplies and also carries the workspace foreign key.
    op.execute(
        "CREATE INDEX ix_digital_workers_tenant_id_workspace_id_created_at"
        " ON platform.digital_workers (tenant_id, workspace_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_digital_workers_tenant_id_principal_user_id"
        " ON platform.digital_workers (tenant_id, principal_user_id)"
    )
    for column in ("technical_owner_id", "work_assigner_id", "validator_id"):
        op.execute(
            f"CREATE INDEX ix_digital_workers_{column} ON platform.digital_workers ({column})"
        )
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.digital_workers"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )

    op.execute(
        f"""
        CREATE TABLE platform.dw_decision_classes (
            dw_id uuid NOT NULL,
            key text NOT NULL,
            tenant_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            effect_level text NOT NULL,
            reversible boolean NOT NULL,
            ceiling text NOT NULL,
            earned_level text NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_dw_decision_classes PRIMARY KEY (dw_id, key),
            CONSTRAINT fk_dw_decision_classes_digital_worker
                FOREIGN KEY (tenant_id, workspace_id, dw_id)
                REFERENCES platform.digital_workers(tenant_id, workspace_id, id)
                ON DELETE CASCADE,
            CONSTRAINT ck_dw_decision_classes_key CHECK (key ~ '^[a-z][a-z0-9_.]{{1,63}}$'),
            CONSTRAINT ck_dw_decision_classes_effect_level
                CHECK (effect_level IN ('none', 'internal', 'external', 'critical')),
            CONSTRAINT ck_dw_decision_classes_ceiling CHECK (ceiling = ANY ({_LEVELS})),
            CONSTRAINT ck_dw_decision_classes_earned_level CHECK (earned_level = ANY ({_LEVELS})),
            CONSTRAINT ck_dw_decision_classes_earned_within_ceiling CHECK (
                array_position({_LEVELS}, earned_level) <= array_position({_LEVELS}, ceiling)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_dw_decision_classes_digital_worker"
        " ON platform.dw_decision_classes (tenant_id, workspace_id, dw_id)"
    )
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.dw_decision_classes"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()"
    )

    # RLS. One literal per policy head: `verify_invariants.py` reads this text.
    op.execute("ALTER TABLE platform.service_principals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.service_principals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_service_principals ON platform.service_principals"
        f" USING ({_TENANT}) WITH CHECK ({_TENANT})"
    )
    op.execute("ALTER TABLE platform.digital_workers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.digital_workers FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_digital_workers ON platform.digital_workers"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )
    op.execute("ALTER TABLE platform.dw_decision_classes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ONLY platform.dw_decision_classes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_dw_decision_classes ON platform.dw_decision_classes"
        f" USING {_NARROWED} WITH CHECK {_NARROWED}"
    )

    # R1.16 and ADR-0103 decision 2: the principal is a service user of this
    # tenant, and its accountable owner a human member of it. SECURITY DEFINER
    # so a membership in a workspace the caller's RLS does not reach still
    # counts; NEW.tenant_id is the caller's own, held by the policy above.
    op.execute(
        """
        CREATE FUNCTION platform.guard_accountable_owner() RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM platform.users u
                WHERE u.id = NEW.user_id AND u.kind = 'service'
                  AND u.owner_tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'a service principal is a service user of its own tenant'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_service_principals_service_user';
            END IF;
            IF NEW.owner_user_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM platform.users u
                JOIN platform.memberships m ON m.user_id = u.id
                WHERE u.id = NEW.owner_user_id AND u.kind = 'human'
                  AND m.tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'the accountable owner is a human member of the tenant'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_service_principals_accountable_owner';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER guard_accountable_owner"
        " BEFORE INSERT OR UPDATE OF user_id, tenant_id, owner_user_id"
        " ON platform.service_principals"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_accountable_owner()"
    )

    # R1.11: a service user never signs in, nor links a chat.
    op.execute(
        """
        CREATE FUNCTION platform.external_identities_human_only() RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM platform.users WHERE id = NEW.user_id AND kind <> 'human'
            ) THEN
                RAISE EXCEPTION 'a service user has no login or chat identity'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_external_identities_human_only';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER external_identities_human_only"
        " BEFORE INSERT OR UPDATE OF user_id ON platform.external_identities"
        " FOR EACH ROW EXECUTE FUNCTION platform.external_identities_human_only()"
    )

    # R1.17: the roles a second person covered when the DW went into operation
    # do not grow afterwards. A new membership, a new role or permission set, or
    # a membership moved onto the principal is refused; narrowing and removing
    # are not. The DW's own creation inserts the membership before the DW row,
    # so it is not caught here.
    op.execute(
        """
        CREATE FUNCTION platform.dw_principal_roles_fixed() RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, platform
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM platform.digital_workers WHERE principal_user_id = NEW.user_id
            ) THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'INSERT'
               OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NOT (OLD.role_keys @> NEW.role_keys)
               OR NOT (OLD.permission_set_keys @> NEW.permission_set_keys)
            THEN
                RAISE EXCEPTION 'the roles of a digital worker principal are fixed'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_memberships_dw_principal_roles_fixed';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER dw_principal_roles_fixed"
        " BEFORE INSERT OR UPDATE ON platform.memberships"
        " FOR EACH ROW EXECUTE FUNCTION platform.dw_principal_roles_fixed()"
    )
    for function in (
        "platform.guard_accountable_owner()",
        "platform.external_identities_human_only()",
        "platform.dw_principal_roles_fixed()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")

    # Scopes, by migration only (`platform.roles` is read-only to every
    # application role, 648e2f7c3edb).
    for role in _MEMBER_ROLES:
        op.execute(
            "UPDATE platform.roles SET scopes = scopes || '[\"dw.read\"]'::jsonb"
            f" WHERE key = '{role}' AND NOT scopes ? 'dw.read'"
        )
    op.execute(
        "UPDATE platform.roles SET scopes = scopes || '[\"dw.manage\"]'::jsonb"
        " WHERE key = 'org_admin' AND NOT scopes ? 'dw.manage'"
    )

    for table in _NEW_TABLES:
        op.execute(_for_role("dw_app", f"REVOKE TRUNCATE ON {table} FROM dw_app;"))
        op.execute(
            _for_role("dw_app", f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dw_app;")
        )
        op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON {table} FROM dw_agent_ro;"))


def downgrade() -> None:
    op.execute("UPDATE platform.roles SET scopes = scopes - 'dw.manage' WHERE key = 'org_admin'")
    op.execute("UPDATE platform.roles SET scopes = scopes - 'dw.read'")
    op.execute("DROP TRIGGER IF EXISTS dw_principal_roles_fixed ON platform.memberships")
    op.execute("DROP FUNCTION IF EXISTS platform.dw_principal_roles_fixed()")
    op.execute(
        "DROP TRIGGER IF EXISTS external_identities_human_only ON platform.external_identities"
    )
    op.execute("DROP FUNCTION IF EXISTS platform.external_identities_human_only()")
    op.execute("DROP TABLE IF EXISTS platform.dw_decision_classes")
    op.execute("DROP TABLE IF EXISTS platform.digital_workers")
    op.execute("DROP TABLE IF EXISTS platform.service_principals")
    op.execute("DROP FUNCTION IF EXISTS platform.guard_accountable_owner()")
    op.execute("DELETE FROM platform.users WHERE kind = 'service'")
    op.execute("DROP INDEX IF EXISTS platform.ix_users_owner_tenant_id")
    op.execute(
        """
        ALTER TABLE platform.users
            DROP CONSTRAINT IF EXISTS fk_users_owner_tenant_id_tenants,
            DROP CONSTRAINT IF EXISTS ck_users_service_has_owner_tenant,
            DROP CONSTRAINT IF EXISTS ck_users_kind,
            DROP COLUMN IF EXISTS owner_tenant_id,
            DROP COLUMN IF EXISTS kind
        """
    )
