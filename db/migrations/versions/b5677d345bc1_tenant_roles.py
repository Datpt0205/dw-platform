"""tenant roles

Revision ID: b5677d345bc1
Revises: 764b0e239f95
Create Date: 2026-11-02 08:29:07.732491+00:00

tenant-rbac ticket 02 (R2-R5; RB5-RB14, RB34, RB37-RB41; ADR-0104 decisions
2, 3, 5, 7, 9, 10): roles become tenant data, assigned per membership, and one
PostgreSQL function answers "what does this person hold".

- `platform.permissions.tenant_grantable`, NOT NULL with no default: false
  for `platform.admin`, true for the rest. Read by `tenant_owner`'s computed
  grants and by ticket 03's anti-escalation.
- `platform.tenant_roles` (kind `role` or `permission_set`; `key` unique per
  tenant across soft-deleted rows; `is_system` follows the key: `tenant_owner`
  and `member` are system roles, every other key is not, by a BEFORE trigger),
  `platform.tenant_role_permissions` (one depth per key, held to the key's
  `scope_kind` by `ck_tenant_role_permissions_depth_kind`) and
  `platform.role_assignments` (membership, role, optional `expires_at`; its
  workspace is the membership's, one fact through the composite key). A role
  is not deleted while assigned in an `active` tenant; 200 live roles per
  tenant at most, serialised by an advisory lock (`role_limit_reached`).
- `platform.tenant_access_versions`: one row per tenant, born with the tenant
  (or here, for every tenant that exists), bumped by
  `platform.bump_access_version()` on every table that feeds authorization;
  `dw_app` reads it only. The AccessContext cache key carries it.
- Functions. `platform.assigned_grants(tenant)`: every privilege an assignment
  carries, `tenant_owner`'s computed ones included, whatever the status of the
  person or the tenant. `platform.effective_grants(tenant, user)`: the subset in
  force (an active member of an active tenant), the one answer every reader
  asks; `platform.scopes_in` (the projection for one workspace),
  `platform.workspace_reach`, `platform.grants_cover` and
  `platform.checker_candidates` read it. Separation of duties reads
  `assigned_grants` instead, so an invitation or a company in `setup` cannot
  carry both sides of a rule in while nothing is yet in force.
- Separation of duties moves to the role tables: AFTER triggers on
  `platform.role_assignments` and `platform.tenant_role_permissions`, across
  every workspace of the person (`ck_roles_sod_memberships`, the rule in HINT,
  up to 20 user ids in DETAIL). The membership trigger and the template
  triggers of `b9862fa13a80` and `f381f1694395` are dropped; the waiver in-use
  guard counts people.
- `memberships.role_keys` and `permission_set_keys` stay a write path until
  ticket 03 locks them: a one-way trigger copies what a write adds or removes
  to the membership's assignments, cloning a template the tenant lacks, and
  never touches an assignment the columns did not give (`tenant_owner`).
- Two owners (V4.38): `setup` joins `ck_tenants_status`; a tenant enters
  `setup` only at creation and leaves it only for `active` (with two active
  owners) or `offboarding`; the write that makes the second owner active turns
  the tenant `active` in its own transaction, audited. A platform operator or
  support staff member never holds `tenant_owner`, `studio.publish.approve` or
  `platform.roles.write` in a tenant (`ck_role_assignments_operator_not_owner`).
- Below two holders of either key: `platform.tenants.owner_coverage_low_since`
  and one `platform.tenant.owner_coverage_low` outbox event per fall.
- Backfill as the migrator: system roles for every tenant, a tenant role for
  every key a membership uses (`platform_admin` excepted: W1 keeps it in
  `role_keys`), the assignments, and `tenant_owner` for the `org_admin`
  holders of each tenant's `main` workspace, audited as
  `system:rbac_migration`; the tenants left below two owners or without an
  `org_admin` there are printed for the operators.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5677d345bc1"
down_revision = "764b0e239f95"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires since cfae5f2d4a13.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"

# What `dw_provisioner` holds here, beside the tuples of the same name in
# 0fdd32a39d87 and 349080a62e41; mirrored by scripts/create_provisioner_role.py,
# all held to the catalog by test_privileges.py.
PROVISIONER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("platform.tenant_roles", "SELECT, INSERT", ()),
    ("platform.tenant_role_permissions", "SELECT, INSERT", ()),
    ("platform.role_assignments", "SELECT, INSERT", ()),
    # An owner who never signed in is created as an `invite:` user.
    ("platform.users", "INSERT", ()),
    # The depth trigger and `install_system_roles` read `scope_kind`.
    ("platform.permissions", "SELECT", ()),
)

# `dw_platform.domain.audit.system_actor("rbac_migration")`, written out: a
# migration does not import the code it predates (uuid5 of SYSTEM_ACTOR_NAMESPACE
# and "system:rbac_migration"; `test_tenant_roles_migration.py` holds the two equal).
RBAC_MIGRATION_ACTOR = "2726fdd7-53e7-5a45-ad0f-e239e95f6a6b"

# -- the four tables ----------------------------------------------------------

_TABLES = (
    """
    CREATE TABLE platform.tenant_roles (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        key text NOT NULL,
        name text NOT NULL,
        description text,
        kind text NOT NULL,
        is_system boolean DEFAULT false NOT NULL,
        template_key text,
        version integer DEFAULT 1 NOT NULL,
        created_by uuid,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        deleted_at timestamp with time zone,
        CONSTRAINT pk_tenant_roles PRIMARY KEY (id),
        CONSTRAINT fk_tenant_roles_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE CASCADE,
        CONSTRAINT fk_tenant_roles_created_by_users FOREIGN KEY (created_by)
            REFERENCES platform.users (id) ON DELETE SET NULL,
        CONSTRAINT uq_tenant_roles_tenant_id_key UNIQUE (tenant_id, key),
        CONSTRAINT uq_tenant_roles_tenant_id_id UNIQUE (tenant_id, id),
        CONSTRAINT ck_tenant_roles_key CHECK (key ~ '^[a-z][a-z0-9_]{1,62}$'),
        CONSTRAINT ck_tenant_roles_name CHECK (btrim(name) <> ''),
        CONSTRAINT ck_tenant_roles_kind CHECK (kind IN ('role', 'permission_set'))
    )
    """,
    "CREATE INDEX ix_tenant_roles_created_by ON platform.tenant_roles (created_by)",
    """
    CREATE TABLE platform.tenant_role_permissions (
        tenant_id uuid NOT NULL,
        role_id uuid NOT NULL,
        permission_key text NOT NULL,
        depth text NOT NULL,
        CONSTRAINT pk_tenant_role_permissions PRIMARY KEY (role_id, permission_key),
        CONSTRAINT fk_tenant_role_permissions_tenant_id_tenant_roles
            FOREIGN KEY (tenant_id, role_id)
            REFERENCES platform.tenant_roles (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_tenant_role_permissions_permission_key_permissions
            FOREIGN KEY (permission_key)
            REFERENCES platform.permissions (key) ON DELETE RESTRICT,
        CONSTRAINT ck_tenant_role_permissions_depth
            CHECK (depth IN ('own', 'workspace', 'tenant'))
    )
    """,
    "CREATE INDEX ix_tenant_role_permissions_tenant_id_role_id"
    " ON platform.tenant_role_permissions (tenant_id, role_id)",
    "CREATE INDEX ix_tenant_role_permissions_permission_key_tenant_id"
    " ON platform.tenant_role_permissions (permission_key, tenant_id)",
    "ALTER TABLE platform.memberships ADD CONSTRAINT uq_memberships_tenant_id_workspace_id_id"
    " UNIQUE (tenant_id, workspace_id, id)",
    """
    CREATE TABLE platform.role_assignments (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        workspace_id uuid NOT NULL,
        membership_id uuid NOT NULL,
        role_id uuid NOT NULL,
        assigned_by uuid,
        assigned_at timestamp with time zone DEFAULT now() NOT NULL,
        expires_at timestamp with time zone,
        CONSTRAINT pk_role_assignments PRIMARY KEY (id),
        CONSTRAINT uq_role_assignments_membership_id_role_id UNIQUE (membership_id, role_id),
        CONSTRAINT fk_role_assignments_tenant_id_memberships
            FOREIGN KEY (tenant_id, workspace_id, membership_id)
            REFERENCES platform.memberships (tenant_id, workspace_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_role_assignments_tenant_id_tenant_roles
            FOREIGN KEY (tenant_id, role_id)
            REFERENCES platform.tenant_roles (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_role_assignments_assigned_by_users FOREIGN KEY (assigned_by)
            REFERENCES platform.users (id) ON DELETE SET NULL,
        CONSTRAINT ck_role_assignments_expires_at
            CHECK (expires_at IS NULL OR expires_at > assigned_at)
    )
    """,
    "CREATE INDEX ix_role_assignments_tenant_id_role_id"
    " ON platform.role_assignments (tenant_id, role_id)",
    "CREATE INDEX ix_role_assignments_tenant_id_workspace_id_membership_id"
    " ON platform.role_assignments (tenant_id, workspace_id, membership_id)",
    "CREATE INDEX ix_role_assignments_assigned_by ON platform.role_assignments (assigned_by)",
    """
    CREATE TABLE platform.tenant_access_versions (
        tenant_id uuid NOT NULL,
        version bigint DEFAULT 0 NOT NULL,
        changed_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_tenant_access_versions PRIMARY KEY (tenant_id),
        CONSTRAINT fk_tenant_access_versions_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE CASCADE
    )
    """,
)

# One literal per table and policy head: `verify_invariants.py` reads this text.
_RLS = (
    "ALTER TABLE platform.tenant_roles ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ONLY platform.tenant_roles FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_tenant_roles ON platform.tenant_roles"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE platform.tenant_role_permissions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ONLY platform.tenant_role_permissions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_tenant_role_permissions ON platform.tenant_role_permissions"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE platform.role_assignments ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ONLY platform.role_assignments FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_role_assignments ON platform.role_assignments"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE platform.tenant_access_versions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ONLY platform.tenant_access_versions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_tenant_access_versions ON platform.tenant_access_versions"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# -- functions ----------------------------------------------------------------

# The two keys whose holders are counted (R3.12) and that no operator or support
# staff member holds in a customer's tenant (R3.11), in one place.
_OWNER_KEYS = """
    CREATE FUNCTION platform.owner_permission_keys() RETURNS text[]
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT ARRAY['platform.roles.write', 'studio.publish.approve']::text[] $$
"""

_SHAPE_FUNCTIONS = (
    # `is_system` follows the key, so no writer can make a role system or unmake one.
    """
    CREATE FUNCTION platform.tenant_role_system_flag() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        NEW.is_system := NEW.key IN ('tenant_owner', 'member');
        RETURN NEW;
    END
    $$
    """,
    # R3.7: the 201st live role of a tenant is refused; the lock serialises two
    # inserts at the 200th, and each statement of plpgsql reads a fresh snapshot.
    """
    CREATE FUNCTION platform.limit_tenant_roles() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        PERFORM pg_advisory_xact_lock(hashtext('tenant_roles:' || NEW.tenant_id::text));
        IF (SELECT count(*) FROM platform.tenant_roles
            WHERE tenant_id = NEW.tenant_id AND deleted_at IS NULL) >= 200 THEN
            RAISE EXCEPTION 'a tenant holds at most 200 roles'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'role_limit_reached';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R3.4: a `tenant` key takes `tenant`; a `workspace` key `workspace` or
    # `tenant`; a `record` key all three. An unknown key is the FK's to refuse.
    """
    CREATE FUNCTION platform.check_role_permission_depth() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_kind text;
    BEGIN
        SELECT scope_kind INTO v_kind FROM platform.permissions WHERE key = NEW.permission_key;
        IF (v_kind = 'tenant' AND NEW.depth <> 'tenant')
           OR (v_kind = 'workspace' AND NEW.depth NOT IN ('workspace', 'tenant')) THEN
            RAISE EXCEPTION 'key % is a % key and cannot be held at depth %',
                NEW.permission_key, v_kind, NEW.depth
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_tenant_role_permissions_depth_kind';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # Step 4: an assigned role of an active tenant stays; offboarding (and a
    # tenant deleted outright) removes roles in any order.
    """
    CREATE FUNCTION platform.refuse_deleting_an_assigned_role() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM platform.role_assignments
            WHERE tenant_id = OLD.tenant_id AND role_id = OLD.id
        ) AND EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = OLD.tenant_id AND status = 'active'
        ) THEN
            RAISE EXCEPTION 'role % is still assigned', OLD.key
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_tenant_roles_in_use';
        END IF;
        RETURN OLD;
    END
    $$
    """,
)

# A tenant role cloned from a template (`platform.roles`, or `platform.permission_sets`
# for kind `permission_set`), at today's depth: `tenant` for a tenant key,
# `workspace` otherwise. A copy, never a link: a template edited later changes no
# clone, and nothing reads through to a template (R3.2). SECURITY INVOKER, so the
# writer's RLS binds the tenant.
_INSTALL = (
    """
    CREATE FUNCTION platform.install_role_template(p_tenant_id uuid, p_template_key text)
    RETURNS uuid
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_id uuid := gen_random_uuid();
        v_name text;
        v_scopes jsonb;
        v_kind text := 'role';
    BEGIN
        SELECT name, scopes INTO v_name, v_scopes FROM platform.roles WHERE key = p_template_key;
        IF NOT FOUND THEN
            SELECT name, scopes INTO v_name, v_scopes
            FROM platform.permission_sets WHERE key = p_template_key;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'no role template %', p_template_key
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_tenant_roles_template_known';
            END IF;
            v_kind := 'permission_set';
        END IF;
        IF EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(v_scopes) s(key)
            JOIN platform.permissions p ON p.key = s.key
            WHERE NOT p.tenant_grantable
        ) THEN
            RAISE EXCEPTION 'template % carries a key no tenant may hold', p_template_key
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_tenant_role_permissions_grantable';
        END IF;
        INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind, template_key)
        VALUES (v_id, p_tenant_id, p_template_key, v_name, v_kind, p_template_key);
        -- An uncatalogued key arrives with no kind and fails its foreign key.
        INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key, depth)
        SELECT DISTINCT p_tenant_id, v_id, s.key,
               CASE WHEN p.scope_kind = 'tenant' THEN 'tenant' ELSE 'workspace' END
        FROM jsonb_array_elements_text(v_scopes) s(key)
        LEFT JOIN platform.permissions p ON p.key = s.key;
        RETURN v_id;
    END
    $$
    """,
    # `tenant_owner` has no privilege rows: its grants are computed (ADR-0104
    # decision 2). `member` is the template's clone, editable by the tenant.
    """
    CREATE FUNCTION platform.install_system_roles(p_tenant_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)
        VALUES (gen_random_uuid(), p_tenant_id, 'tenant_owner', 'Chủ sở hữu công ty', 'role')
        ON CONFLICT (tenant_id, key) DO NOTHING;
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenant_roles WHERE tenant_id = p_tenant_id AND key = 'member'
        ) THEN
            PERFORM platform.install_role_template(p_tenant_id, 'member');
        END IF;
    END
    $$
    """,
)

# Inlinable SQL: no SET clause, STABLE, one statement, every name qualified.
_GRANT_FUNCTIONS = (
    """
    CREATE FUNCTION platform.assigned_grants(p_tenant_id uuid)
    RETURNS TABLE (
        user_id uuid, permission_key text, depth text, anchor_workspace_id uuid,
        role_id uuid, role_key text
    )
    LANGUAGE sql STABLE
    AS $$
        SELECT m.user_id, p.permission_key, p.depth, a.workspace_id, r.id, r.key
        FROM platform.role_assignments a
        JOIN platform.memberships m
          ON m.tenant_id = a.tenant_id AND m.workspace_id = a.workspace_id
         AND m.id = a.membership_id
        JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
        JOIN platform.tenant_role_permissions p
          ON p.tenant_id = a.tenant_id AND p.role_id = r.id
        WHERE a.tenant_id = p_tenant_id
          AND r.deleted_at IS NULL
          AND (a.expires_at IS NULL OR a.expires_at > now())
        UNION ALL
        SELECT m.user_id, k.key, 'tenant', a.workspace_id, r.id, r.key
        FROM platform.role_assignments a
        JOIN platform.memberships m
          ON m.tenant_id = a.tenant_id AND m.workspace_id = a.workspace_id
         AND m.id = a.membership_id
        JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
        CROSS JOIN platform.permissions k
        WHERE a.tenant_id = p_tenant_id
          AND r.key = 'tenant_owner'
          AND r.deleted_at IS NULL
          AND (a.expires_at IS NULL OR a.expires_at > now())
          AND k.status = 'active'
          AND k.tenant_grantable
    $$
    """,
    """
    CREATE FUNCTION platform.effective_grants(p_tenant_id uuid, p_user_id uuid)
    RETURNS TABLE (permission_key text, depth text, anchor_workspace_id uuid, role_id uuid)
    LANGUAGE sql STABLE
    AS $$
        SELECT g.permission_key, g.depth, g.anchor_workspace_id, g.role_id
        FROM platform.assigned_grants(p_tenant_id) g
        JOIN platform.tenant_members tm
          ON tm.tenant_id = p_tenant_id AND tm.user_id = g.user_id
        JOIN platform.tenants t ON t.id = p_tenant_id
        WHERE g.user_id = p_user_id
          AND tm.status = 'active'
          AND t.status = 'active'
    $$
    """,
    # The projection for the acting workspace: tenant depth from every anchor,
    # workspace depth where it is anchored, a record key at every depth (its
    # records are narrowed by `workspace_reach`, not here).
    """
    CREATE FUNCTION platform.scopes_in(p_tenant_id uuid, p_user_id uuid, p_workspace_id uuid)
    RETURNS SETOF text
    LANGUAGE sql STABLE
    AS $$
        SELECT DISTINCT g.permission_key
        FROM platform.effective_grants(p_tenant_id, p_user_id) g
        JOIN platform.permissions k ON k.key = g.permission_key
        WHERE g.depth = 'tenant'
           OR g.anchor_workspace_id = p_workspace_id
           OR k.scope_kind = 'record'
    $$
    """,
    """
    CREATE FUNCTION platform.workspace_reach(
        p_tenant_id uuid, p_user_id uuid, p_permission_key text
    )
    RETURNS SETOF uuid
    LANGUAGE sql STABLE
    AS $$
        SELECT w.id
        FROM platform.workspaces w
        WHERE w.tenant_id = p_tenant_id
          AND w.archived_at IS NULL
          AND EXISTS (
              SELECT 1 FROM platform.effective_grants(p_tenant_id, p_user_id) g
              WHERE g.permission_key = p_permission_key
                AND (g.depth = 'tenant'
                     OR (g.depth = 'workspace' AND g.anchor_workspace_id = w.id))
          )
    $$
    """,
    # Whether the holder has every key of the subject at the same or a broader
    # depth, at the same anchor below `tenant`.
    """
    CREATE FUNCTION platform.grants_cover(p_tenant_id uuid, p_holder_id uuid, p_subject_id uuid)
    RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT NOT EXISTS (
            SELECT 1 FROM platform.effective_grants(p_tenant_id, p_subject_id) s
            WHERE NOT EXISTS (
                SELECT 1 FROM platform.effective_grants(p_tenant_id, p_holder_id) h
                WHERE h.permission_key = s.permission_key
                  AND (h.depth = 'tenant'
                       OR (h.anchor_workspace_id = s.anchor_workspace_id
                           AND array_position(ARRAY['own', 'workspace', 'tenant'], h.depth)
                               >= array_position(ARRAY['own', 'workspace', 'tenant'], s.depth)))
            )
        )
    $$
    """,
    # The people who could confirm what `p_proposer_id` proposes: active people
    # (never a Digital Worker's principal) holding the key, the proposer
    # excepted; with a workspace, only those whose holding reaches it.
    """
    CREATE FUNCTION platform.checker_candidates(
        p_tenant_id uuid, p_permission_key text, p_proposer_id uuid,
        p_workspace_id uuid DEFAULT NULL
    )
    RETURNS SETOF uuid
    LANGUAGE sql STABLE
    AS $$
        SELECT DISTINCT tm.user_id
        FROM platform.tenant_members tm
        JOIN platform.users u ON u.id = tm.user_id AND u.kind = 'human'
        CROSS JOIN LATERAL platform.effective_grants(p_tenant_id, tm.user_id) g
        WHERE tm.tenant_id = p_tenant_id
          AND tm.status = 'active'
          AND tm.user_id IS DISTINCT FROM p_proposer_id
          AND g.permission_key = p_permission_key
          AND (p_workspace_id IS NULL
               OR g.depth = 'tenant'
               OR (g.depth = 'workspace' AND g.anchor_workspace_id = p_workspace_id))
    $$
    """,
    # The active members holding an assignment of `tenant_owner` (R3.10): read on
    # the tables, not through `effective_grants`, which counts an active tenant only.
    """
    CREATE FUNCTION platform.active_tenant_owners(p_tenant_id uuid) RETURNS SETOF uuid
    LANGUAGE sql STABLE
    AS $$
        SELECT DISTINCT m.user_id
        FROM platform.role_assignments a
        JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
        JOIN platform.memberships m ON m.tenant_id = a.tenant_id AND m.id = a.membership_id
        JOIN platform.tenant_members tm ON tm.tenant_id = m.tenant_id AND tm.user_id = m.user_id
        WHERE a.tenant_id = p_tenant_id
          AND r.key = 'tenant_owner'
          AND r.deleted_at IS NULL
          AND (a.expires_at IS NULL OR a.expires_at > now())
          AND tm.status = 'active'
    $$
    """,
)

# -- separation of duties -----------------------------------------------------

_SOD = (
    # What one person holds for the rules: every assigned key at any depth and
    # anchor, `tenant_owner`'s excepted (the emergency role; ADR-0104 decision 9).
    """
    CREATE FUNCTION platform.sod_held_keys(p_tenant_id uuid, p_user_id uuid) RETURNS text[]
    LANGUAGE sql STABLE
    AS $$
        SELECT coalesce(array_agg(DISTINCT g.permission_key), '{}'::text[])
        FROM platform.assigned_grants(p_tenant_id) g
        WHERE g.user_id = p_user_id AND g.role_key <> 'tenant_owner'
    $$
    """,
    """
    CREATE FUNCTION platform.sod_rule_broken(p_rule_key text, p_keys text[]) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM platform.sod_rules s
            WHERE s.key = p_rule_key
              AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(s.left_scopes) l(key)
                          WHERE l.key = ANY (p_keys))
              AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(s.right_scopes) r(key)
                          WHERE r.key = ANY (p_keys))
        )
    $$
    """,
    # The first rule the person breaks without a confirmed open waiver, which
    # is taken FOR SHARE (f381f1694395's race, unchanged).
    """
    CREATE FUNCTION platform.sod_violation(p_tenant_id uuid, p_user_id uuid)
    RETURNS TABLE (rule_key text, rule_description text)
    LANGUAGE plpgsql
    VOLATILE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    #variable_conflict use_column
    DECLARE
        candidate record;
        v_keys text[] := platform.sod_held_keys(p_tenant_id, p_user_id);
    BEGIN
        FOR candidate IN
            SELECT s.key, s.description, s.waivable FROM platform.sod_rules s ORDER BY s.key
        LOOP
            CONTINUE WHEN NOT platform.sod_rule_broken(candidate.key, v_keys);
            IF candidate.waivable THEN
                PERFORM 1
                FROM platform.sod_waivers w
                WHERE w.tenant_id = p_tenant_id
                  AND w.rule_key = candidate.key
                  AND w.revoked_at IS NULL
                  AND w.confirmed_at IS NOT NULL
                FOR SHARE;
                CONTINUE WHEN FOUND;
            END IF;
            rule_key := candidate.key;
            rule_description := candidate.description;
            RETURN NEXT;
            RETURN;
        END LOOP;
    END
    $$
    """,
    # AFTER a role assignment or a role's privilege is written: every person it
    # reaches is judged across all their assignments in the tenant.
    """
    CREATE FUNCTION platform.enforce_role_separation_of_duties() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_people uuid[];
        v_rule text;
        v_reason text;
        v_count integer;
        v_listed text;
    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN
            v_people := ARRAY(
                SELECT m.user_id FROM platform.memberships m WHERE m.id = NEW.membership_id
            );
        ELSE
            v_people := ARRAY(
                SELECT DISTINCT m.user_id
                FROM platform.role_assignments a
                JOIN platform.memberships m ON m.id = a.membership_id
                WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.role_id
            );
        END IF;
        WITH broken AS (
            SELECT p.user_id, v.rule_key, v.rule_description,
                   row_number() OVER (ORDER BY p.user_id) AS rn
            FROM unnest(v_people) AS p(user_id)
            CROSS JOIN LATERAL platform.sod_violation(NEW.tenant_id, p.user_id) v
        )
        SELECT min(rule_key), count(*),
               string_agg(user_id::text, ', ' ORDER BY user_id) FILTER (WHERE rn <= 20)
        INTO v_rule, v_count, v_listed
        FROM broken;
        IF v_count > 0 THEN
            SELECT description INTO v_reason FROM platform.sod_rules WHERE key = v_rule;
            RAISE EXCEPTION '%', v_reason
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_roles_sod_memberships',
                      HINT = v_rule,
                      DETAIL = v_listed;
        END IF;
        RETURN NULL;
    END
    $$
    """,
    # Revoking a waiver someone relies on is refused, counting people by what
    # they hold across the tenant (not memberships by `role_keys`).
    """
    CREATE OR REPLACE FUNCTION platform.refuse_revoking_a_waiver_in_use()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        relying integer;
    BEGIN
        -- The waiver row is locked before a row trigger runs, so a write
        -- holding it FOR SHARE has committed by now, and this query (plpgsql,
        -- so a fresh snapshot) sees that write.
        SELECT count(*) INTO relying
        FROM platform.tenant_members tm
        WHERE tm.tenant_id = NEW.tenant_id
          AND platform.sod_rule_broken(
              NEW.rule_key, platform.sod_held_keys(NEW.tenant_id, tm.user_id)
          );
        IF relying > 0 THEN
            RAISE EXCEPTION 'waiver of % is relied on by % person(s)', NEW.rule_key, relying
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_sod_waivers_not_in_use',
                      DETAIL = relying::text;
        END IF;
        RETURN NULL;
    END
    $$
    """,
)

# The legacy write path, until ticket 03 locks the two columns: what a write
# adds to `role_keys` or `permission_set_keys` is assigned, what it removes is
# revoked, in the same statement. A key the tenant has no role for is cloned
# from its template first; one that is neither is refused. `platform_admin`
# stays in `role_keys` only (W1, G2). Never touches an assignment the columns
# did not give, and refuses `tenant_owner` there for that reason.
_LEGACY_SYNC = """
    CREATE FUNCTION platform.sync_legacy_role_columns() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_new text[];
        v_old text[] := '{}';
        v_key text;
        v_role uuid;
    BEGIN
        v_new := ARRAY(
            SELECT jsonb_array_elements_text(NEW.role_keys)
            UNION SELECT jsonb_array_elements_text(NEW.permission_set_keys)
        );
        IF TG_OP = 'UPDATE' THEN
            v_old := ARRAY(
                SELECT jsonb_array_elements_text(OLD.role_keys)
                UNION SELECT jsonb_array_elements_text(OLD.permission_set_keys)
            );
        END IF;
        IF 'tenant_owner' = ANY (v_new) AND NOT 'tenant_owner' = ANY (v_old) THEN
            RAISE EXCEPTION 'tenant_owner is assigned as a role, never through role_keys'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_memberships_role_keys_known';
        END IF;
        -- Only a write that removes a key revokes, so a writer that never
        -- removes one (the provisioner, which holds no DELETE) needs no DELETE.
        IF EXISTS (SELECT 1 FROM unnest(v_old) k WHERE NOT k = ANY (v_new)) THEN
            DELETE FROM platform.role_assignments a
            USING platform.tenant_roles r
            WHERE a.membership_id = NEW.id
              AND r.tenant_id = a.tenant_id AND r.id = a.role_id
              AND r.key = ANY (v_old) AND NOT r.key = ANY (v_new)
              AND r.key NOT IN ('platform_admin', 'tenant_owner');
        END IF;
        FOREACH v_key IN ARRAY v_new LOOP
            CONTINUE WHEN v_key = ANY (v_old) OR v_key IN ('platform_admin', 'tenant_owner');
            SELECT id INTO v_role FROM platform.tenant_roles
            WHERE tenant_id = NEW.tenant_id AND key = v_key AND deleted_at IS NULL;
            IF NOT FOUND THEN
                IF NOT EXISTS (SELECT 1 FROM platform.roles WHERE key = v_key)
                   AND NOT EXISTS (SELECT 1 FROM platform.permission_sets WHERE key = v_key) THEN
                    RAISE EXCEPTION 'no role or role template %', v_key
                        USING ERRCODE = 'check_violation',
                              CONSTRAINT = 'ck_memberships_role_keys_known';
                END IF;
                v_role := platform.install_role_template(NEW.tenant_id, v_key);
            END IF;
            INSERT INTO platform.role_assignments (
                id, tenant_id, workspace_id, membership_id, role_id
            ) VALUES (gen_random_uuid(), NEW.tenant_id, NEW.workspace_id, NEW.id, v_role)
            ON CONFLICT (membership_id, role_id) DO NOTHING;
        END LOOP;
        RETURN NULL;
    END
    $$
"""

# -- the access version -------------------------------------------------------

# The row is born only here (AFTER INSERT on tenants) and in the backfill; every
# other firing updates it, so the deletes after offboarding purged it do not
# bring it back (R4.2). Fires last among its table's row triggers (`trg_z_`), so
# a write that also locks the tenant row takes it before the version row.
_BUMP = """
    CREATE FUNCTION platform.bump_access_version() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid;
    BEGIN
        IF TG_TABLE_NAME = 'tenants' THEN
            IF TG_OP = 'INSERT' THEN
                INSERT INTO platform.tenant_access_versions (tenant_id) VALUES (NEW.id)
                ON CONFLICT (tenant_id) DO NOTHING;
                RETURN NULL;
            END IF;
            v_tenant := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
        ELSE
            v_tenant := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
        END IF;
        UPDATE platform.tenant_access_versions
        SET version = version + 1, changed_at = now()
        WHERE tenant_id = v_tenant;
        RETURN NULL;
    END
    $$
"""
_BUMPED_TABLES = (
    "tenant_roles",
    "tenant_role_permissions",
    "role_assignments",
    "memberships",
    "tenants",
    "entitlements",
    "tenant_members",
)

# Offboarding's step for the version row, which `dw_app` may not delete (R4.2).
_PURGE_VERSION = """
    CREATE FUNCTION platform.purge_tenant_access_version(p_tenant_id uuid) RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF p_tenant_id IS DISTINCT FROM
            NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
            RAISE EXCEPTION 'purge_tenant_access_version runs for the transaction''s own tenant'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_tenant_access_versions_purge';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = p_tenant_id AND status = 'offboarding'
        ) THEN
            RAISE EXCEPTION 'purge_tenant_access_version runs only for a tenant offboarding'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_tenant_access_versions_purge';
        END IF;
        DELETE FROM platform.tenant_access_versions WHERE tenant_id = p_tenant_id;
    END
    $$
"""

# -- two owners (R3.1, R3.9-R3.15) ---------------------------------------------

_SETUP = (
    # A tenant enters `setup` only when it is created, and leaves it for
    # `active` (with two active owners) or `offboarding` alone (R3.15).
    """
    CREATE FUNCTION platform.guard_tenant_setup() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            IF NEW.status = 'setup'
               OR (OLD.status = 'setup' AND NEW.status NOT IN ('active', 'offboarding'))
               OR (OLD.status = 'setup' AND NEW.status = 'active'
                   AND (SELECT count(*) FROM platform.active_tenant_owners(NEW.id)) < 2)
            THEN
                RAISE EXCEPTION 'tenant status cannot go from % to %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_tenants_status_transition';
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    # R3.10: the write that brings a `setup` tenant's active owners to two turns
    # it `active` in its own transaction. The tenant row is locked before the
    # count, so two activations at once queue and the second counts both.
    """
    CREATE FUNCTION platform.complete_tenant_setup() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid := NEW.tenant_id;
        v_actor uuid;
        v_owners uuid[];
        v_workspace uuid;
    BEGIN
        IF TG_TABLE_NAME = 'tenant_members' THEN
            v_actor := NEW.user_id;
        ELSE
            IF NOT EXISTS (
                SELECT 1 FROM platform.tenant_roles
                WHERE id = NEW.role_id AND key = 'tenant_owner'
            ) THEN
                RETURN NULL;
            END IF;
            SELECT user_id INTO v_actor FROM platform.memberships WHERE id = NEW.membership_id;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = v_tenant AND status = 'setup'
        ) THEN
            RETURN NULL;
        END IF;
        PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;
        SELECT array_agg(o ORDER BY o) INTO v_owners FROM platform.active_tenant_owners(v_tenant) o;
        IF coalesce(cardinality(v_owners), 0) < 2 THEN
            RETURN NULL;
        END IF;
        UPDATE platform.tenants SET status = 'active' WHERE id = v_tenant AND status = 'setup';
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
        SELECT id INTO v_workspace FROM platform.workspaces
        WHERE tenant_id = v_tenant ORDER BY (slug = 'main') DESC, created_at, id LIMIT 1;
        INSERT INTO platform.audit_events (
            id, tenant_id, workspace_id, actor_id, action, resource_type, resource_id,
            details, occurred_at
        ) VALUES (
            gen_random_uuid(), v_tenant, v_workspace, v_actor, 'platform.tenant.setup_completed',
            'tenant', v_tenant::text,
            jsonb_build_object('owner_ids', to_jsonb(v_owners)), now()
        );
        RETURN NULL;
    END
    $$
    """,
    # R3.11: one function holds the role and the two keys no platform operator
    # or support staff member may hold in a tenant, for every writer. The
    # advisory lock per person closes the race between listing someone and
    # assigning them at once (gate M4).
    """
    CREATE FUNCTION platform.guard_operator_tenant_grants() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_user uuid;
        v_refused boolean := false;
    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN
            SELECT user_id INTO v_user FROM platform.memberships WHERE id = NEW.membership_id;
            PERFORM pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text));
            v_refused := (
                EXISTS (SELECT 1 FROM platform.platform_operators WHERE user_id = v_user)
                OR EXISTS (SELECT 1 FROM platform.support_staff WHERE user_id = v_user)
            ) AND EXISTS (
                SELECT 1 FROM platform.tenant_roles r
                WHERE r.tenant_id = NEW.tenant_id AND r.id = NEW.role_id
                  AND (r.key = 'tenant_owner' OR EXISTS (
                      SELECT 1 FROM platform.tenant_role_permissions p
                      WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id
                        AND p.permission_key = ANY (platform.owner_permission_keys())))
            );
        ELSIF TG_TABLE_NAME = 'tenant_role_permissions' THEN
            v_refused := NEW.permission_key = ANY (platform.owner_permission_keys())
                AND EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    JOIN platform.memberships m ON m.id = a.membership_id
                    WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.role_id
                      AND (EXISTS (SELECT 1 FROM platform.platform_operators o
                                   WHERE o.user_id = m.user_id)
                           OR EXISTS (SELECT 1 FROM platform.support_staff s
                                      WHERE s.user_id = m.user_id))
                );
        ELSE
            v_user := NEW.user_id;
            PERFORM pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text));
            v_refused := EXISTS (
                SELECT 1 FROM platform.role_assignments a
                JOIN platform.memberships m ON m.id = a.membership_id
                JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
                WHERE m.user_id = v_user
                  AND (r.key = 'tenant_owner' OR EXISTS (
                      SELECT 1 FROM platform.tenant_role_permissions p
                      WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id
                        AND p.permission_key = ANY (platform.owner_permission_keys())))
            );
        END IF;
        IF v_refused THEN
            RAISE EXCEPTION 'a platform operator or support staff member holds no owner'
                ' authority in a tenant'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_role_assignments_operator_not_owner';
        END IF;
        RETURN NEW;
    END
    $$
    """,
)

# -- below two holders (R3.12, R3.13) ------------------------------------------

_COVERAGE = (
    # Counts only the keys of the two that the catalogue has `active`: a key not
    # registered yet is held by nobody and must not warn every tenant.
    """
    CREATE FUNCTION platform.check_owner_coverage(p_tenant_id uuid) RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_low text[];
        v_since timestamptz;
        v_workspace uuid;
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = p_tenant_id AND status = 'active'
        ) THEN
            RETURN;
        END IF;
        v_low := ARRAY(
            SELECT k.key FROM platform.permissions k
            WHERE k.key = ANY (platform.owner_permission_keys()) AND k.status = 'active'
              AND (SELECT count(*) FROM platform.checker_candidates(p_tenant_id, k.key, NULL)) < 2
            ORDER BY k.key
        );
        IF cardinality(v_low) > 0 THEN
            -- Once per fall: only the write that finds the column empty sets it
            -- and announces; a concurrent one waits on the row and finds it set.
            UPDATE platform.tenants SET owner_coverage_low_since = now()
            WHERE id = p_tenant_id AND owner_coverage_low_since IS NULL
            RETURNING owner_coverage_low_since INTO v_since;
            IF FOUND THEN
                SELECT id INTO v_workspace FROM platform.workspaces
                WHERE tenant_id = p_tenant_id
                ORDER BY (slug = 'main') DESC, created_at, id LIMIT 1;
                INSERT INTO platform.outbox_events (
                    id, tenant_id, workspace_id, event_type, schema_version, aggregate_id,
                    payload, occurred_at
                ) VALUES (
                    gen_random_uuid(), p_tenant_id, v_workspace,
                    'platform.tenant.owner_coverage_low', '1', p_tenant_id,
                    jsonb_build_object(
                        'tenant_id', p_tenant_id,
                        'keys', to_jsonb(v_low),
                        'owner_coverage_low_since', v_since
                    ),
                    now()
                );
            END IF;
        ELSE
            UPDATE platform.tenants SET owner_coverage_low_since = NULL
            WHERE id = p_tenant_id AND owner_coverage_low_since IS NOT NULL;
        END IF;
    END
    $$
    """,
    # Once per tenant a statement touched. PostgreSQL refuses a transition table
    # on a trigger with more than one event (measured, gate M5), so each table
    # carries three triggers that share this function.
    """
    CREATE FUNCTION platform.owner_coverage_after_write() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            FOR v_tenant IN SELECT DISTINCT tenant_id FROM coverage_new LOOP
                PERFORM platform.check_owner_coverage(v_tenant);
            END LOOP;
        ELSIF TG_OP = 'DELETE' THEN
            FOR v_tenant IN SELECT DISTINCT tenant_id FROM coverage_old LOOP
                PERFORM platform.check_owner_coverage(v_tenant);
            END LOOP;
        ELSE
            FOR v_tenant IN
                SELECT tenant_id FROM coverage_new UNION SELECT tenant_id FROM coverage_old
            LOOP
                PERFORM platform.check_owner_coverage(v_tenant);
            END LOOP;
        END IF;
        RETURN NULL;
    END
    $$
    """,
)
_COVERED_TABLES = ("role_assignments", "tenant_role_permissions", "tenant_roles", "tenant_members")

# -- backfill, as the migrator ------------------------------------------------

# Held to their rules by `test_tenant_roles_migration.py`, which runs them on
# planted tenants. Each is idempotent, so running them again changes nothing.
BACKFILL = (
    "INSERT INTO platform.tenant_access_versions (tenant_id) SELECT id FROM platform.tenants"
    " ON CONFLICT (tenant_id) DO NOTHING",
    "SELECT platform.install_system_roles(t.id) FROM platform.tenants t",
    # A tenant role for every key a membership uses, cloned from its template.
    """
    SELECT platform.install_role_template(u.tenant_id, u.key)
    FROM (
        SELECT DISTINCT m.tenant_id, k.key
        FROM platform.memberships m
        CROSS JOIN LATERAL (
            SELECT jsonb_array_elements_text(m.role_keys)
            UNION SELECT jsonb_array_elements_text(m.permission_set_keys)
        ) k(key)
        WHERE k.key NOT IN ('platform_admin', 'tenant_owner')
    ) u
    WHERE NOT EXISTS (
        SELECT 1 FROM platform.tenant_roles r WHERE r.tenant_id = u.tenant_id AND r.key = u.key
    )
    """,
    # Each membership's roles and permission sets, as assignments where it is.
    """
    INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id, role_id)
    SELECT gen_random_uuid(), m.tenant_id, m.workspace_id, m.id, r.id
    FROM platform.memberships m
    CROSS JOIN LATERAL (
        SELECT jsonb_array_elements_text(m.role_keys)
        UNION SELECT jsonb_array_elements_text(m.permission_set_keys)
    ) k(key)
    JOIN platform.tenant_roles r ON r.tenant_id = m.tenant_id AND r.key = k.key
    WHERE k.key NOT IN ('platform_admin', 'tenant_owner')
    ON CONFLICT (membership_id, role_id) DO NOTHING
    """,
    # DO-32.2: `tenant_owner` for the `org_admin` holders of `main`, never for
    # a platform operator or support staff member (R3.11), one audit each.
    f"""
    WITH granted AS (
        INSERT INTO platform.role_assignments (id, tenant_id, workspace_id, membership_id, role_id)
        SELECT gen_random_uuid(), m.tenant_id, m.workspace_id, m.id, r.id
        FROM platform.memberships m
        JOIN platform.workspaces w ON w.id = m.workspace_id AND w.slug = 'main'
        JOIN platform.tenant_roles r ON r.tenant_id = m.tenant_id AND r.key = 'tenant_owner'
        WHERE m.role_keys ? 'org_admin'
          AND NOT EXISTS (SELECT 1 FROM platform.platform_operators o WHERE o.user_id = m.user_id)
          AND NOT EXISTS (SELECT 1 FROM platform.support_staff s WHERE s.user_id = m.user_id)
        ON CONFLICT (membership_id, role_id) DO NOTHING
        RETURNING id, tenant_id, workspace_id, membership_id, role_id
    )
    INSERT INTO platform.audit_events (
        id, tenant_id, workspace_id, actor_id, action, resource_type, resource_id,
        details, occurred_at
    )
    SELECT gen_random_uuid(), g.tenant_id, g.workspace_id, '{RBAC_MIGRATION_ACTOR}'::uuid,
           'platform.role_assignment.grant', 'role_assignment', g.id::text,
           jsonb_build_object(
               'membership_id', g.membership_id, 'role_id', g.role_id,
               'role_key', 'tenant_owner', 'actor', 'system:rbac_migration'
           ),
           now()
    FROM granted g
    """,
)

# What the operators fix by hand (ADR-0104 Consequences): a tenant below two
# active owners changes no role and invites nobody until a second is installed
# (`POST /api/v1/platform/tenants/{tenant_id}/org-admins`).
REPORT_BELOW_TWO_OWNERS = """
    SELECT t.slug FROM platform.tenants t
    WHERE t.status <> 'offboarded'
      AND (SELECT count(*) FROM platform.active_tenant_owners(t.id)) < 2
    ORDER BY t.slug
"""
REPORT_NO_MAIN_ORG_ADMIN = """
    SELECT t.slug FROM platform.tenants t
    WHERE t.status <> 'offboarded'
      AND NOT EXISTS (
          SELECT 1 FROM platform.memberships m
          JOIN platform.workspaces w ON w.id = m.workspace_id AND w.slug = 'main'
          WHERE m.tenant_id = t.id AND m.role_keys ? 'org_admin'
      )
    ORDER BY t.slug
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


def _triggers() -> list[str]:
    statements = [
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.tenant_roles"
        " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
        "CREATE TRIGGER trg_tenant_roles_system_flag BEFORE INSERT OR UPDATE OF key, is_system"
        " ON platform.tenant_roles"
        " FOR EACH ROW EXECUTE FUNCTION platform.tenant_role_system_flag()",
        "CREATE TRIGGER trg_tenant_roles_limit BEFORE INSERT ON platform.tenant_roles"
        " FOR EACH ROW EXECUTE FUNCTION platform.limit_tenant_roles()",
        "CREATE TRIGGER trg_tenant_roles_in_use BEFORE DELETE ON platform.tenant_roles"
        " FOR EACH ROW EXECUTE FUNCTION platform.refuse_deleting_an_assigned_role()",
        "CREATE TRIGGER ck_tenant_role_permissions_depth_kind"
        " BEFORE INSERT OR UPDATE ON platform.tenant_role_permissions"
        " FOR EACH ROW EXECUTE FUNCTION platform.check_role_permission_depth()",
    ]
    return statements


def _behaviour_triggers() -> list[str]:
    statements = [
        f"CREATE TRIGGER trg_z_bump_access_version AFTER INSERT OR UPDATE OR DELETE"
        f" ON platform.{table} FOR EACH ROW EXECUTE FUNCTION platform.bump_access_version()"
        for table in _BUMPED_TABLES
    ]
    statements += [
        "CREATE TRIGGER trg_memberships_legacy_role_columns"
        " AFTER INSERT OR UPDATE OF role_keys, permission_set_keys ON platform.memberships"
        " FOR EACH ROW EXECUTE FUNCTION platform.sync_legacy_role_columns()",
        "CREATE TRIGGER trg_role_assignments_separation_of_duties"
        " AFTER INSERT OR UPDATE ON platform.role_assignments"
        " FOR EACH ROW EXECUTE FUNCTION platform.enforce_role_separation_of_duties()",
        "CREATE TRIGGER trg_tenant_role_permissions_separation_of_duties"
        " AFTER INSERT OR UPDATE ON platform.tenant_role_permissions"
        " FOR EACH ROW EXECUTE FUNCTION platform.enforce_role_separation_of_duties()",
        "CREATE TRIGGER trg_tenants_setup_transition BEFORE UPDATE OF status ON platform.tenants"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_tenant_setup()",
        "CREATE TRIGGER trg_tenant_members_complete_setup"
        " AFTER UPDATE OF status ON platform.tenant_members FOR EACH ROW"
        " WHEN (NEW.status = 'active' AND OLD.status <> 'active')"
        " EXECUTE FUNCTION platform.complete_tenant_setup()",
        "CREATE TRIGGER trg_role_assignments_complete_setup"
        " AFTER INSERT OR UPDATE OF role_id, membership_id ON platform.role_assignments"
        " FOR EACH ROW EXECUTE FUNCTION platform.complete_tenant_setup()",
        "CREATE TRIGGER trg_role_assignments_operator_not_owner"
        " BEFORE INSERT OR UPDATE ON platform.role_assignments"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_operator_tenant_grants()",
        "CREATE TRIGGER trg_tenant_role_permissions_operator_not_owner"
        " BEFORE INSERT OR UPDATE ON platform.tenant_role_permissions"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_operator_tenant_grants()",
        "CREATE TRIGGER trg_platform_operators_not_owner BEFORE INSERT"
        " ON platform.platform_operators"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_operator_tenant_grants()",
        "CREATE TRIGGER trg_support_staff_not_owner BEFORE INSERT ON platform.support_staff"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_operator_tenant_grants()",
    ]
    for table in _COVERED_TABLES:
        statements += [
            f"CREATE TRIGGER trg_{table}_owner_coverage_insert AFTER INSERT ON platform.{table}"
            " REFERENCING NEW TABLE AS coverage_new FOR EACH STATEMENT"
            " EXECUTE FUNCTION platform.owner_coverage_after_write()",
            f"CREATE TRIGGER trg_{table}_owner_coverage_update AFTER UPDATE ON platform.{table}"
            " REFERENCING OLD TABLE AS coverage_old NEW TABLE AS coverage_new FOR EACH STATEMENT"
            " EXECUTE FUNCTION platform.owner_coverage_after_write()",
            f"CREATE TRIGGER trg_{table}_owner_coverage_delete AFTER DELETE ON platform.{table}"
            " REFERENCING OLD TABLE AS coverage_old FOR EACH STATEMENT"
            " EXECUTE FUNCTION platform.owner_coverage_after_write()",
        ]
    return statements


_DEFINER_FUNCTIONS = (
    "platform.sod_violation(uuid, uuid)",
    "platform.enforce_role_separation_of_duties()",
    "platform.bump_access_version()",
    "platform.purge_tenant_access_version(uuid)",
    "platform.guard_tenant_setup()",
    "platform.complete_tenant_setup()",
    "platform.guard_operator_tenant_grants()",
    "platform.check_owner_coverage(uuid)",
    "platform.owner_coverage_after_write()",
)


def _report() -> None:
    bind = op.get_bind()
    if bind is None:  # a recording stand-in for `op` (unit tests) has no connection
        return
    for title, query in (
        ("tenants below two active owners", REPORT_BELOW_TWO_OWNERS),
        ("tenants with no org_admin in workspace main", REPORT_NO_MAIN_ORG_ADMIN),
    ):
        slugs = [row[0] for row in bind.execute(sa.text(query))]
        print(f"tenant-rbac/02: {title}: {', '.join(slugs) if slugs else '(none)'}")


def upgrade() -> None:
    # 1. The catalogue column, a value for every row, no default.
    op.execute("ALTER TABLE platform.permissions ADD COLUMN tenant_grantable boolean")
    op.execute("UPDATE platform.permissions SET tenant_grantable = (key <> 'platform.admin')")
    op.execute("ALTER TABLE platform.permissions ALTER COLUMN tenant_grantable SET NOT NULL")

    # 2. Tenants: `setup`, and the time the owners fell below two.
    op.execute("ALTER TABLE platform.tenants DROP CONSTRAINT ck_tenants_status")
    op.execute(
        "ALTER TABLE platform.tenants ADD CONSTRAINT ck_tenants_status"
        " CHECK (status IN ('setup', 'active', 'locked', 'offboarding', 'offboarded'))"
    )
    op.execute(
        "ALTER TABLE platform.tenants ADD COLUMN owner_coverage_low_since timestamp with time zone"
    )

    # 3. Tables, RLS, privileges.
    for statement in (*_TABLES, *_RLS):
        op.execute(statement)
    for table in ("tenant_roles", "tenant_role_permissions", "role_assignments"):
        op.execute(_for_role("dw_app", f"REVOKE TRUNCATE ON platform.{table} FROM dw_app;"))
        op.execute(
            _for_role(
                "dw_app", f"GRANT SELECT, INSERT, UPDATE, DELETE ON platform.{table} TO dw_app;"
            )
        )
        op.execute(_for_role("dw_agent_ro", f"REVOKE ALL ON platform.{table} FROM dw_agent_ro;"))
    op.execute(
        _for_role(
            "dw_app",
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform.tenant_access_versions"
            " FROM dw_app; GRANT SELECT ON platform.tenant_access_versions TO dw_app;",
        )
    )
    op.execute(
        _for_role("dw_agent_ro", "REVOKE ALL ON platform.tenant_access_versions FROM dw_agent_ro;")
    )
    for name, verbs, _ in PROVISIONER:
        op.execute(_for_role("dw_provisioner", f"GRANT {verbs} ON {name} TO dw_provisioner;"))

    # 4. Functions. The old separation of duties goes first: its functions
    # read the role catalogue per membership.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_memberships_separation_of_duties ON platform.memberships"
    )
    for table in ("roles", "permission_sets"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_sod_memberships ON platform.{table}")
    op.execute("DROP FUNCTION IF EXISTS platform.enforce_separation_of_duties()")
    op.execute("DROP FUNCTION IF EXISTS platform.refuse_scope_change_breaking_memberships()")
    op.execute("DROP FUNCTION IF EXISTS platform.sod_violation(uuid, jsonb, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS platform.sod_rule_broken(text, jsonb, jsonb)")
    for statement in (
        _OWNER_KEYS,
        *_SHAPE_FUNCTIONS,
        *_INSTALL,
        *_GRANT_FUNCTIONS,
        *_SOD,
        _LEGACY_SYNC,
        _BUMP,
        _PURGE_VERSION,
        *_SETUP,
        *_COVERAGE,
    ):
        op.execute(statement)
    for function in _DEFINER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(
        _for_role(
            "dw_app",
            "GRANT EXECUTE ON FUNCTION platform.purge_tenant_access_version(uuid) TO dw_app;",
        )
    )
    for function in (
        "platform.install_role_template(uuid, text)",
        "platform.install_system_roles(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(
            _for_role("dw_provisioner", f"GRANT EXECUTE ON FUNCTION {function} TO dw_provisioner;")
        )
    op.execute(
        _for_role(
            "dw_app",
            "GRANT EXECUTE ON FUNCTION platform.install_role_template(uuid, text) TO dw_app;",
        )
    )

    # 5. Shape triggers, then the data, then the triggers that judge writes:
    # what holds today is migrated as it is (a person holding a rule's two
    # sides in two workspaces stays, as f381f1694395 left memberships).
    for statement in _triggers():
        op.execute(statement)
    for statement in BACKFILL:
        op.execute(statement)
    for statement in _behaviour_triggers():
        op.execute(statement)
    _report()


def downgrade() -> None:
    # Forward only past the backfill: the old per-membership separation of
    # duties and its catalogue triggers are not restored (a downgrade is never
    # read, `test_tenant_status_vocabulary.py`); this removes what was added.
    for table in _COVERED_TABLES:
        for event in ("insert", "update", "delete"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table}_owner_coverage_{event} ON platform.{table}"
            )
    for table in _BUMPED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_z_bump_access_version ON platform.{table}")
    for trigger, table in (
        ("trg_memberships_legacy_role_columns", "memberships"),
        ("trg_tenants_setup_transition", "tenants"),
        ("trg_tenant_members_complete_setup", "tenant_members"),
        ("trg_platform_operators_not_owner", "platform_operators"),
        ("trg_support_staff_not_owner", "support_staff"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON platform.{table}")
    for table in (
        "role_assignments",
        "tenant_role_permissions",
        "tenant_roles",
        "tenant_access_versions",
    ):
        op.execute(f"DROP TABLE IF EXISTS platform.{table} CASCADE")
    for function in (
        *_DEFINER_FUNCTIONS,
        "platform.owner_permission_keys()",
        "platform.tenant_role_system_flag()",
        "platform.limit_tenant_roles()",
        "platform.check_role_permission_depth()",
        "platform.refuse_deleting_an_assigned_role()",
        "platform.install_system_roles(uuid)",
        "platform.install_role_template(uuid, text)",
        "platform.checker_candidates(uuid, text, uuid, uuid)",
        "platform.grants_cover(uuid, uuid, uuid)",
        "platform.workspace_reach(uuid, uuid, text)",
        "platform.scopes_in(uuid, uuid, uuid)",
        "platform.active_tenant_owners(uuid)",
        "platform.sod_held_keys(uuid, uuid)",
        "platform.sod_rule_broken(text, text[])",
        "platform.effective_grants(uuid, uuid)",
        "platform.assigned_grants(uuid)",
        "platform.sync_legacy_role_columns()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute(
        "ALTER TABLE platform.memberships"
        " DROP CONSTRAINT IF EXISTS uq_memberships_tenant_id_workspace_id_id"
    )
    op.execute("ALTER TABLE platform.tenants DROP COLUMN IF EXISTS owner_coverage_low_since")
    op.execute("ALTER TABLE platform.tenants DROP CONSTRAINT ck_tenants_status")
    op.execute(
        "ALTER TABLE platform.tenants ADD CONSTRAINT ck_tenants_status"
        " CHECK (status IN ('active', 'locked', 'offboarding', 'offboarded'))"
    )
    op.execute("ALTER TABLE platform.permissions DROP COLUMN IF EXISTS tenant_grantable")
