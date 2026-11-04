"""object and field privileges in roles

Revision ID: ef68083f2905
Revises: 045712d63ec7
Create Date: 2026-11-04 19:59:05.262820+00:00

tenant-rbac ticket 04 (R6.8, R9.1-R9.15; RB28-RB31, RB33, RB35, RB44-RB47;
ADR-0104 decisions 2, 4, 6, 10; ADR-0106 decision 3). A tenant role carries
privileges on the company's own objects, `obj.<object>.<action>` at a depth,
and field privileges `fld.<object>.<field>.read|edit`, additive over every role
a person holds. No key is stored: each is generated from a live definition, in
one place each, and read by every function that asks what a role carries.

- `platform.object_actions`: the seven actions, five `enforced`; `share` and
  `export` wait for the migration that ships their reader. Read-only to every
  application role.
- `platform.tenant_role_object_privileges` and `studio.field_permissions`:
  tenant-wide (the anchor is the assignment's), RLS forced, composite keys to
  the role and the definition `ON DELETE CASCADE`, so no row names another
  tenant's role, object or field, and deleting a definition removes its
  privileges in the same transaction (R9.3, R9.8).
- `platform.object_permission_keys(tenant)`: the one owner of an object key and
  its attributes (label, `record`, `risk`, grantable), read by the catalogue
  route and by `platform.rbac_refusals`. `platform.field_permission_keys(tenant)`:
  the one owner of a field key and of "edit gives read too" (R9.15).
  `platform.record_privilege_keys(table, row)`: the keys one row gives.
- `platform.role_privileges` (what a role carries) adds both, and
  `tenant_owner`'s computed keys of every live object and field (R9.7);
  `platform.assigned_grants` reads it, so the owner's computation and a role's
  rows have one owner. `platform.scopes_in` keeps an `obj.*` key at every depth.
- `platform.role_is_critical` adds a role with `fld.*` on a `sensitive` field
  (R6.8, R9.9); `platform.rbac_refusals` refuses a record key that names no
  live definition as not grantable; `platform.rbac_guard` judges the two new
  tables as the other three: the hold rule, two people for a widening write
  matched against the proposal's `object_privileges` and `field_permissions`;
  `platform.guard_service_principal_grants` refuses `fld.*` on a sensitive field
  reaching a service account, and a field made sensitive while one holds it.
- The role's `version` and the tenant's access version move with every write of
  the new tables; a definition added or removed moves the access version at
  commit (a deferred constraint trigger: the role rows the guard locks in the
  same transaction are taken first, R9.11, R9.12).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op

revision = "ef68083f2905"
down_revision = "045712d63ec7"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"

# (action, label_vi, enforced, sort_order)
ACTIONS = (
    ("read", "Xem", True, 10),
    ("create", "Tạo", True, 20),
    ("update", "Sửa", True, 30),
    ("delete", "Xóa", True, 40),
    ("assign", "Giao người phụ trách", True, 50),
    ("share", "Chia sẻ", False, 60),
    ("export", "Xuất", False, 70),
)


def _earlier(filename: str) -> ModuleType:
    """An earlier revision's module, for the function bodies this one extends
    (and restores on the way down) without a second copy of them."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(f"dw_rev_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ROLES_03 = _earlier("d2b57239ef50_role_administration_and_anti_escalation.py")
_PRINCIPALS_03 = _earlier("557e6907195e_service_principals_run_as.py")
_ROLES_02 = _earlier("b5677d345bc1_tenant_roles.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/04: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


def _replace(body: str) -> str:
    return _patched(body, ("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"))


# -- the tables -----------------------------------------------------------------

_TABLES = (
    """
    CREATE TABLE platform.object_actions (
        action text NOT NULL,
        label_vi text NOT NULL,
        enforced boolean NOT NULL,
        sort_order integer NOT NULL,
        CONSTRAINT pk_object_actions PRIMARY KEY (action),
        CONSTRAINT ck_object_actions_action CHECK (action IN
            ('read', 'create', 'update', 'delete', 'assign', 'share', 'export')),
        CONSTRAINT ck_object_actions_label_vi CHECK (btrim(label_vi) <> '')
    )
    """,
    """
    CREATE TABLE platform.tenant_role_object_privileges (
        tenant_id uuid NOT NULL,
        role_id uuid NOT NULL,
        object_id uuid NOT NULL,
        action text NOT NULL,
        depth text NOT NULL,
        CONSTRAINT pk_tenant_role_object_privileges PRIMARY KEY (role_id, object_id, action),
        CONSTRAINT fk_tenant_role_object_privileges_tenant_id_tenant_roles
            FOREIGN KEY (tenant_id, role_id)
            REFERENCES platform.tenant_roles (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_tenant_role_object_privileges_tenant_id_object_defs
            FOREIGN KEY (tenant_id, object_id)
            REFERENCES studio.object_defs (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_tenant_role_object_privileges_action_object_actions
            FOREIGN KEY (action)
            REFERENCES platform.object_actions (action) ON DELETE RESTRICT,
        CONSTRAINT ck_tenant_role_object_privileges_depth
            CHECK (depth IN ('own', 'workspace', 'tenant'))
    )
    """,
    "CREATE INDEX ix_tenant_role_object_privileges_tenant_id_role_id"
    " ON platform.tenant_role_object_privileges (tenant_id, role_id)",
    "CREATE INDEX ix_tenant_role_object_privileges_tenant_id_object_id"
    " ON platform.tenant_role_object_privileges (tenant_id, object_id)",
    "CREATE INDEX ix_tenant_role_object_privileges_action"
    " ON platform.tenant_role_object_privileges (action)",
    """
    CREATE TABLE studio.field_permissions (
        tenant_id uuid NOT NULL,
        role_id uuid NOT NULL,
        field_id uuid NOT NULL,
        access text NOT NULL,
        granted_by uuid,
        granted_at timestamp with time zone DEFAULT now() NOT NULL,
        CONSTRAINT pk_field_permissions PRIMARY KEY (tenant_id, role_id, field_id),
        CONSTRAINT fk_field_permissions_tenant_id_tenant_roles
            FOREIGN KEY (tenant_id, role_id)
            REFERENCES platform.tenant_roles (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_field_permissions_tenant_id_field_defs
            FOREIGN KEY (tenant_id, field_id)
            REFERENCES studio.field_defs (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT fk_field_permissions_granted_by_users
            FOREIGN KEY (granted_by) REFERENCES platform.users (id) ON DELETE SET NULL,
        CONSTRAINT ck_field_permissions_access CHECK (access IN ('read', 'edit'))
    )
    """,
    # The key leads with (tenant_id, role_id), the role's foreign key.
    "CREATE INDEX ix_field_permissions_tenant_id_field_id"
    " ON studio.field_permissions (tenant_id, field_id)",
    "CREATE INDEX ix_field_permissions_granted_by ON studio.field_permissions (granted_by)",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
_RLS = (
    "ALTER TABLE platform.tenant_role_object_privileges ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ONLY platform.tenant_role_object_privileges FORCE ROW LEVEL SECURITY",
    # One literal up to the table's name: the invariant check reads this text.
    "CREATE POLICY tenant_isolation_tenant_role_object_privileges ON platform.tenant_role_object_privileges"  # noqa: E501
    f" USING {_TENANT} WITH CHECK {_TENANT}",
    "ALTER TABLE studio.field_permissions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE studio.field_permissions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_field_permissions ON studio.field_permissions"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# -- the keys, one owner each ----------------------------------------------------

# An object key exists for every live definition (a `studio.object_defs` row, so
# past its first publish) and every enforced action, with the attributes the
# catalogue shows and `platform.rbac_refusals` reads (step 6): grantable in a
# tenant, `record`, `standard` for read and `elevated` otherwise, never critical
# in W1. SQL, STABLE, SECURITY INVOKER: inlined into its callers, under their RLS.
_OBJECT_KEYS = """
    CREATE FUNCTION platform.object_permission_keys(p_tenant_id uuid)
    RETURNS TABLE (
        key text, object_id uuid, action text, label_vi text, area text, scope_kind text,
        risk text, tenant_grantable boolean, sort_order integer
    )
    LANGUAGE sql STABLE
    AS $$
        SELECT 'obj.' || o.api_name || '.' || a.action, o.id, a.action,
               coalesce(o.labels ->> 'vi', o.api_name) || ' — ' || a.label_vi,
               'records', 'record',
               CASE WHEN a.action = 'read' THEN 'standard' ELSE 'elevated' END,
               true, a.sort_order
        FROM studio.object_defs o
        CROSS JOIN platform.object_actions a
        WHERE o.tenant_id = p_tenant_id AND a.enforced
    $$
"""

# A field key exists for every live field, `read` and `edit`. `from_access` is
# the access a `studio.field_permissions` row needs to give the key: `edit`
# gives both (R9.15), so field-security never derives "edit, so read" itself.
_FIELD_KEYS = """
    CREATE FUNCTION platform.field_permission_keys(p_tenant_id uuid)
    RETURNS TABLE (key text, field_id uuid, from_access text, pd_category text)
    LANGUAGE sql STABLE
    AS $$
        SELECT 'fld.' || o.api_name || '.' || f.api_name || '.' || g.access, f.id,
               g.from_access, f.pd_category
        FROM studio.field_defs f
        JOIN studio.object_defs o ON o.tenant_id = f.tenant_id AND o.id = f.object_id
        CROSS JOIN (VALUES ('read', 'read'), ('read', 'edit'), ('edit', 'edit'))
            AS g(access, from_access)
        WHERE f.tenant_id = p_tenant_id
    $$
"""

# The keys one row of either table gives, `{key, depth}` each, in the row's own
# tenant; none when its definition is not live (or not of that tenant). The
# triggers judge a write by these; the role service previews with them.
_ROW_KEYS = """
    CREATE FUNCTION platform.record_privilege_keys(p_table text, p_row jsonb)
    RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
        SELECT coalesce(jsonb_agg(jsonb_build_object('key', k.key, 'depth', k.depth)
                                  ORDER BY k.key), '[]'::jsonb)
        FROM (
            SELECT o.key, p_row ->> 'depth' AS depth
            FROM platform.object_permission_keys((p_row ->> 'tenant_id')::uuid) o
            WHERE p_table = 'tenant_role_object_privileges'
              AND o.object_id = (p_row ->> 'object_id')::uuid
              AND o.action = p_row ->> 'action'
            UNION ALL
            SELECT f.key, 'tenant'
            FROM platform.field_permission_keys((p_row ->> 'tenant_id')::uuid) f
            WHERE p_table = 'field_permissions'
              AND f.field_id = (p_row ->> 'field_id')::uuid
              AND f.from_access = p_row ->> 'access'
        ) k
    $$
"""

# What a role carries: its catalogue rows, its object and field rows as their
# keys, and for `tenant_owner` every active key a tenant may hold, every key of
# every live object and every key of every live field, all at `tenant` (R9.7,
# ADR-0104 decision 2), computed, never stored. The one owner: `assigned_grants`
# reads it per assignment.
_ROLE_PRIVILEGES = """
    CREATE OR REPLACE FUNCTION platform.role_privileges(p_tenant_id uuid, p_role_id uuid)
    RETURNS TABLE (permission_key text, depth text)
    LANGUAGE sql STABLE
    AS $$
        SELECT p.permission_key, p.depth
        FROM platform.tenant_role_permissions p
        WHERE p.tenant_id = p_tenant_id AND p.role_id = p_role_id
        UNION ALL
        SELECT k.key, o.depth
        FROM platform.tenant_role_object_privileges o
        JOIN platform.object_permission_keys(p_tenant_id) k
          ON k.object_id = o.object_id AND k.action = o.action
        WHERE o.tenant_id = p_tenant_id AND o.role_id = p_role_id
        UNION ALL
        SELECT k.key, 'tenant'
        FROM studio.field_permissions f
        JOIN platform.field_permission_keys(p_tenant_id) k
          ON k.field_id = f.field_id AND k.from_access = f.access
        WHERE f.tenant_id = p_tenant_id AND f.role_id = p_role_id
        UNION ALL
        SELECT k.key, 'tenant'
        FROM platform.tenant_roles r
        CROSS JOIN platform.permissions k
        WHERE r.tenant_id = p_tenant_id AND r.id = p_role_id AND r.key = 'tenant_owner'
          AND k.status = 'active' AND k.tenant_grantable
        UNION ALL
        SELECT k.key, 'tenant'
        FROM platform.tenant_roles r
        CROSS JOIN platform.object_permission_keys(p_tenant_id) k
        WHERE r.tenant_id = p_tenant_id AND r.id = p_role_id AND r.key = 'tenant_owner'
        UNION ALL
        SELECT k.key, 'tenant'
        FROM platform.tenant_roles r
        CROSS JOIN platform.field_permission_keys(p_tenant_id) k
        WHERE r.tenant_id = p_tenant_id AND r.id = p_role_id AND r.key = 'tenant_owner'
          AND k.from_access = 'edit'
    $$
"""

# Inlinable SQL still: no SET clause, STABLE, one statement.
_ASSIGNED_GRANTS = """
    CREATE OR REPLACE FUNCTION platform.assigned_grants(p_tenant_id uuid)
    RETURNS TABLE (
        user_id uuid, permission_key text, depth text, anchor_workspace_id uuid,
        role_id uuid, role_key text
    )
    LANGUAGE sql STABLE
    AS $$
        SELECT m.user_id, g.permission_key, g.depth, a.workspace_id, r.id, r.key
        FROM platform.role_assignments a
        JOIN platform.memberships m
          ON m.tenant_id = a.tenant_id AND m.workspace_id = a.workspace_id
         AND m.id = a.membership_id
        JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
        CROSS JOIN LATERAL platform.role_privileges(p_tenant_id, r.id) g
        WHERE a.tenant_id = p_tenant_id
          AND r.deleted_at IS NULL
          AND (a.expires_at IS NULL OR a.expires_at > now())
    $$
"""

# The projection for the acting workspace: a key the catalogue does not hold is
# a generated record key, kept at every depth like a `record` key (its records
# are narrowed by `workspace_reach` and record-access, not here).
_SCOPES_IN = """
    CREATE OR REPLACE FUNCTION platform.scopes_in(
        p_tenant_id uuid, p_user_id uuid, p_workspace_id uuid
    )
    RETURNS SETOF text
    LANGUAGE sql STABLE
    AS $$
        SELECT DISTINCT g.permission_key
        FROM platform.effective_grants(p_tenant_id, p_user_id) g
        LEFT JOIN platform.permissions k ON k.key = g.permission_key
        WHERE g.depth = 'tenant'
           OR g.anchor_workspace_id = p_workspace_id
           OR coalesce(k.scope_kind, 'record') = 'record'
    $$
"""

# ADR-0104 decision 6, amended 2026-11-03: the one owner of "critical role" adds
# a role with `fld.*` on a live sensitive field (R6.8, R9.9, DO-32.1).
_ROLE_IS_CRITICAL = """
    CREATE OR REPLACE FUNCTION platform.role_is_critical(p_tenant_id uuid, p_role_id uuid)
    RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM platform.tenant_roles r
            WHERE r.tenant_id = p_tenant_id AND r.id = p_role_id
              AND (r.key = 'tenant_owner'
                   OR EXISTS (
                       SELECT 1 FROM platform.tenant_role_permissions p
                       JOIN platform.permissions k ON k.key = p.permission_key
                       WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id
                         AND k.risk = 'critical')
                   OR EXISTS (
                       SELECT 1 FROM studio.field_permissions f
                       JOIN studio.field_defs d ON d.tenant_id = f.tenant_id AND d.id = f.field_id
                       WHERE f.tenant_id = r.tenant_id AND f.role_id = r.id
                         AND d.pd_category = 'sensitive'))
        )
    $$
"""

# R9.2 (RB28): an action no reader enforces yet is held by no role, whoever writes.
_ACTION_ENFORCED = """
    CREATE FUNCTION platform.refuse_unenforced_object_action() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM platform.object_actions a WHERE a.action = NEW.action AND a.enforced
        ) THEN
            RAISE EXCEPTION 'action % is not enforced yet', NEW.action
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_role_object_privileges_action_enforced';
        END IF;
        RETURN NEW;
    END
    $$
"""

# `platform.rbac_refusals`: a record key is grantable only while it names a live
# definition of the tenant (`object_permission_keys`' own `tenant_grantable`); a
# key that resolved to nothing is refused, never read as "no catalogue row".
_REFUSALS = _patched(
    _replace(_ROLES_03._REFUSALS),
    (
        """            IF v_op IN ('add', 'raise') AND EXISTS (
                SELECT 1 FROM platform.permissions k WHERE k.key = v_key AND NOT k.tenant_grantable
            ) THEN""",
        """            IF v_op IN ('add', 'raise') AND (
                v_key IS NULL
                OR EXISTS (
                    SELECT 1 FROM platform.permissions k
                    WHERE k.key = v_key AND NOT k.tenant_grantable
                )
                OR (v_key LIKE 'obj.%' AND NOT EXISTS (
                    SELECT 1 FROM platform.object_permission_keys(p_tenant_id) o
                    WHERE o.key = v_key AND o.tenant_grantable
                ))
                OR (v_key LIKE 'fld.%' AND NOT EXISTS (
                    SELECT 1 FROM platform.field_permission_keys(p_tenant_id) f
                    WHERE f.key = v_key
                ))
            ) THEN""",
    ),
)

# `platform.rbac_guard`: the two new tables, judged by the keys a row gives.
# A widening write (a row added, a depth raised, `read` to `edit`) is applied only
# by a confirmed `role_create` or `role_permissions` proposal whose payload holds
# the row; one that only narrows needs `app.user_id` and the hold rule (R9.10,
# R7.6). A row deleted after its definition is the definition's cascade (R9.3):
# nothing to judge, the keys it gave are gone already.
_GUARD = _patched(
    _replace(_ROLES_03._GUARD),
    (
        "        v_grantee uuid;\n",
        "        v_grantee uuid;\n"
        "        v_old_keys jsonb;\n"
        "        v_new_keys jsonb;\n"
        "        v_added jsonb;\n"
        "        v_removed jsonb;\n",
    ),
    (
        """        ELSE
            IF TG_OP = 'INSERT' THEN
                SELECT m.user_id INTO v_grantee FROM platform.memberships m""",
        """        ELSIF TG_TABLE_NAME IN ('tenant_role_object_privileges',
                                'field_permissions') THEN
            v_old_keys := platform.record_privilege_keys(TG_TABLE_NAME, v_old);
            v_new_keys := platform.record_privilege_keys(TG_TABLE_NAME, v_new);
            IF TG_OP = 'DELETE' AND jsonb_array_length(v_old_keys) = 0 THEN
                RETURN OLD;
            END IF;
            -- What the write adds (a key, or a key at a broader depth) and removes.
            v_added := coalesce((
                SELECT jsonb_agg(n.k) FROM jsonb_array_elements(v_new_keys) n(k)
                WHERE NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(v_old_keys) o(k)
                    WHERE o.k->>'key' = n.k->>'key'
                      AND array_position({_DEPTHS}, o.k->>'depth')
                          >= array_position({_DEPTHS}, n.k->>'depth'))
            ), '[]'::jsonb);
            v_removed := coalesce((
                SELECT jsonb_agg(o.k) FROM jsonb_array_elements(v_old_keys) o(k)
                WHERE NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(v_new_keys) n(k)
                    WHERE n.k->>'key' = o.k->>'key'
                      AND array_position({_DEPTHS}, n.k->>'depth')
                          >= array_position({_DEPTHS}, o.k->>'depth'))
            ), '[]'::jsonb);
            IF TG_OP = 'INSERT' AND jsonb_array_length(v_new_keys) = 0 THEN
                -- No live definition: refused as not grantable, never passed.
                v_added := jsonb_build_array(
                    jsonb_build_object('key', NULL, 'depth', v_new->>'depth'));
            END IF;
            v_changes := ARRAY(
                SELECT jsonb_build_object('op', 'add', 'role_id', v_new->>'role_id',
                                          'permission_key', a.k->>'key', 'depth', a.k->>'depth')
                FROM jsonb_array_elements(v_added) a(k)
                UNION ALL
                SELECT jsonb_build_object('op', 'remove', 'role_id', v_old->>'role_id',
                                          'permission_key', r.k->>'key', 'depth', r.k->>'depth')
                FROM jsonb_array_elements(v_removed) r(k)
            );
            IF jsonb_array_length(v_added) > 0 THEN
                v_class := 'widen';
                -- Only a row that stays itself can be what a proposal names.
                IF TG_OP = 'INSERT' OR (
                    (v_new - ARRAY['depth', 'access', 'granted_by', 'granted_at'])
                    = (v_old - ARRAY['depth', 'access', 'granted_by', 'granted_at'])) THEN
                    v_kind := 'record_privilege';
                END IF;
            ELSIF jsonb_array_length(v_removed) > 0 THEN
                v_class := 'narrow';
            ELSE
                v_class := 'neutral';
            END IF;
        ELSE
            IF TG_OP = 'INSERT' THEN
                SELECT m.user_id INTO v_grantee FROM platform.memberships m""".replace(
            "{_DEPTHS}", _ROLES_03._DEPTHS
        ),
    ),
    (
        """                            OR (v_kind = 'privilege' AND TG_OP = 'INSERT'
                                AND v_new->>'role_id' = v_open.payload->>'role_id'
                                AND v_open.payload->'permissions' @> jsonb_build_array(
                                    jsonb_build_object('key', v_new->>'permission_key',
                                                       'depth', v_new->>'depth')))""",
        """                            OR (v_kind = 'privilege' AND TG_OP = 'INSERT'
                                AND v_new->>'role_id' = v_open.payload->>'role_id'
                                AND v_open.payload->'permissions' @> jsonb_build_array(
                                    jsonb_build_object('key', v_new->>'permission_key',
                                                       'depth', v_new->>'depth')))
                            OR (v_kind = 'record_privilege' AND TG_OP = 'INSERT'
                                AND v_new->>'role_id' = v_open.payload->>'role_id'
                                AND platform.proposal_holds_record_row(
                                    v_open.payload, TG_TABLE_NAME, v_new))""",
    ),
    (
        """                        WHEN v_open.kind = 'role_permissions' THEN
                            v_kind = 'privilege'
                            AND (v_new->>'role_id')::uuid = v_open.role_id
                            AND v_open.payload->'permissions' @> jsonb_build_array(
                                jsonb_build_object('key', v_new->>'permission_key',
                                                   'depth', v_new->>'depth'))""",
        """                        WHEN v_open.kind = 'role_permissions' THEN
                            (v_new->>'role_id')::uuid = v_open.role_id
                            AND ((v_kind = 'privilege'
                                  AND v_open.payload->'permissions' @> jsonb_build_array(
                                      jsonb_build_object('key', v_new->>'permission_key',
                                                         'depth', v_new->>'depth')))
                                 OR (v_kind = 'record_privilege'
                                     AND platform.proposal_holds_record_row(
                                         v_open.payload, TG_TABLE_NAME, v_new)))""",
    ),
)

# The row exactly as the proposal's payload carries it (R7.5): an object
# privilege `{object_id, action, depth}`, a field permission `{field_id, access}`.
_PROPOSAL_HOLDS = """
    CREATE FUNCTION platform.proposal_holds_record_row(
        p_payload jsonb, p_table text, p_row jsonb
    )
    RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$
        SELECT CASE p_table
            WHEN 'tenant_role_object_privileges' THEN
                coalesce(p_payload->'object_privileges', '[]'::jsonb) @> jsonb_build_array(
                    jsonb_build_object('object_id', p_row->>'object_id',
                                       'action', p_row->>'action',
                                       'depth', p_row->>'depth'))
            WHEN 'field_permissions' THEN
                coalesce(p_payload->'field_permissions', '[]'::jsonb) @> jsonb_build_array(
                    jsonb_build_object('field_id', p_row->>'field_id',
                                       'access', p_row->>'access'))
            ELSE false
        END
    $$
"""

# `platform.guard_service_principal_grants`: `fld.*` on a sensitive field makes a
# role critical, so it reaches no service account (R9.9): a field permission on
# a sensitive field for a role a service account holds, and a field made
# sensitive while a role holding it is held by one. Each locks the role rows
# `FOR NO KEY UPDATE` before it reads, as the branches beside it.
_GUARD_GRANTS = _patched(
    _replace(_PRINCIPALS_03._GUARD_GRANTS),
    (
        """        ELSIF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN""",
        """        ELSIF TG_TABLE_NAME = 'field_permissions' THEN
            IF EXISTS (
                SELECT 1 FROM studio.field_defs f
                WHERE f.tenant_id = NEW.tenant_id AND f.id = NEW.field_id
                  AND f.pd_category = 'sensitive'
            ) THEN
                PERFORM 1 FROM platform.tenant_roles
                WHERE tenant_id = NEW.tenant_id AND id = NEW.role_id
                FOR NO KEY UPDATE;
                v_refused := EXISTS (
                    SELECT 1 FROM platform.service_holders_of_role(NEW.tenant_id, NEW.role_id)
                );
            END IF;
        ELSIF TG_TABLE_NAME = 'field_defs' THEN
            IF NEW.pd_category = 'sensitive' AND OLD.pd_category IS DISTINCT FROM 'sensitive' THEN
                PERFORM 1 FROM platform.tenant_roles r
                WHERE r.tenant_id = NEW.tenant_id AND r.id IN (
                    SELECT p.role_id FROM studio.field_permissions p
                    WHERE p.tenant_id = NEW.tenant_id AND p.field_id = NEW.id
                )
                ORDER BY r.id
                FOR NO KEY UPDATE;
                v_refused := EXISTS (
                    SELECT 1 FROM studio.field_permissions p
                    WHERE p.tenant_id = NEW.tenant_id AND p.field_id = NEW.id
                      AND EXISTS (
                          SELECT 1 FROM platform.service_holders_of_role(NEW.tenant_id, p.role_id)
                      )
                );
            END IF;
        ELSIF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN""",
    ),
)

_NEW_TABLES = (
    ("platform", "tenant_role_object_privileges"),
    ("studio", "field_permissions"),
)

_TRIGGERS = (
    # BEFORE, by name: the action, then the service-account guard, then the rules.
    "CREATE TRIGGER ck_role_object_privileges_action_enforced"
    " BEFORE INSERT OR UPDATE OF action ON platform.tenant_role_object_privileges"
    " FOR EACH ROW EXECUTE FUNCTION platform.refuse_unenforced_object_action()",
    *(
        f"CREATE TRIGGER rbac_refusals_{table} BEFORE INSERT OR UPDATE OR DELETE"
        f" ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION platform.rbac_guard()"
        for schema, table in _NEW_TABLES
    ),
    "CREATE TRIGGER guard_service_principal_grants"
    " BEFORE INSERT OR UPDATE ON studio.field_permissions"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_service_principal_grants()",
    "CREATE TRIGGER guard_service_principal_grants"
    " BEFORE UPDATE OF pd_category ON studio.field_defs"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_service_principal_grants()",
    # AFTER, by name: the role's version (`trg_t…`, `trg_f…`) before the tenant's
    # access version (`trg_z_…`), the role row before the version row.
    *(
        f"CREATE TRIGGER trg_{table}_role_version AFTER INSERT OR UPDATE OR DELETE"
        f" ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION platform.bump_parent_role_version()"
        for schema, table in _NEW_TABLES
    ),
    *(
        f"CREATE TRIGGER trg_z_bump_access_version AFTER INSERT OR UPDATE OR DELETE"
        f" ON {schema}.{table} FOR EACH ROW EXECUTE FUNCTION platform.bump_access_version()"
        for schema, table in _NEW_TABLES
    ),
    # The owner's computed keys follow the definitions (R9.12). At commit, so the
    # version row is taken after every role row a publish locks (one lock order).
    *(
        f"CREATE CONSTRAINT TRIGGER trg_z_bump_access_version AFTER INSERT OR DELETE"
        f" ON studio.{table} DEFERRABLE INITIALLY DEFERRED"
        " FOR EACH ROW EXECUTE FUNCTION platform.bump_access_version()"
        for table in ("object_defs", "field_defs")
    ),
)

_TRIGGER_TABLES = (
    ("ck_role_object_privileges_action_enforced", "platform.tenant_role_object_privileges"),
    *((f"rbac_refusals_{t}", f"{s}.{t}") for s, t in _NEW_TABLES),
    ("guard_service_principal_grants", "studio.field_permissions"),
    ("guard_service_principal_grants", "studio.field_defs"),
    *((f"trg_{t}_role_version", f"{s}.{t}") for s, t in _NEW_TABLES),
    *(("trg_z_bump_access_version", f"{s}.{t}") for s, t in _NEW_TABLES),
    ("trg_z_bump_access_version", "studio.object_defs"),
    ("trg_z_bump_access_version", "studio.field_defs"),
)

# `dw_app` reads the keys (the catalogue, the role service's preview, and through
# `role_privileges` every grant); the trigger functions are no one's to call.
_APP_FUNCTIONS = (
    "platform.object_permission_keys(uuid)",
    "platform.field_permission_keys(uuid)",
    "platform.record_privilege_keys(text, jsonb)",
)
_PRIVATE_FUNCTIONS = (
    "platform.refuse_unenforced_object_action()",
    "platform.proposal_holds_record_row(jsonb, text, jsonb)",
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
    # 1. The tables, their row security and privileges.
    for statement in _TABLES:
        op.execute(statement)
    for statement in _RLS:
        op.execute(statement)
    for action, label, enforced, order in ACTIONS:
        op.execute(
            sa.text(
                "INSERT INTO platform.object_actions (action, label_vi, enforced, sort_order)"
                " VALUES (:a, :l, :e, :o)"
            ).bindparams(a=action, l=label, e=enforced, o=order)
        )
    # The schema's defaults hand `dw_app` writes on a platform table and SELECT
    # on a studio one: the actions are migration-only, read by every role; the
    # privileges are `dw_app`'s, as `platform.tenant_role_permissions`; a field
    # permission changes only its access (studio-skeleton R2.7).
    op.execute(
        _for_role(
            "dw_app",
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform.object_actions FROM dw_app;"
            " GRANT INSERT, DELETE ON studio.field_permissions TO dw_app;"
            " GRANT UPDATE (access, granted_by, granted_at) ON studio.field_permissions TO dw_app;",
        )
    )
    # Not the provisioner: it holds exactly what its code runs (foundations R5.2),
    # and nothing it runs reads the actions.
    op.execute(_for_role("dw_agent_ro", "GRANT SELECT ON platform.object_actions TO dw_agent_ro;"))
    op.execute(
        _for_role(
            "dw_agent_ro",
            "REVOKE ALL ON platform.tenant_role_object_privileges FROM dw_agent_ro;",
        )
    )

    # 2. The keys, what a role carries, and the rules that read them.
    for statement in (
        _OBJECT_KEYS,
        _FIELD_KEYS,
        _ROW_KEYS,
        _ROLE_PRIVILEGES,
        _ASSIGNED_GRANTS,
        _SCOPES_IN,
        _ROLE_IS_CRITICAL,
        _ACTION_ENFORCED,
        _PROPOSAL_HOLDS,
        _REFUSALS,
        _GUARD,
        _GUARD_GRANTS,
    ):
        op.execute(statement)
    for function in (*_APP_FUNCTIONS, *_PRIVATE_FUNCTIONS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in _APP_FUNCTIONS:
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))

    # 3. The triggers.
    for statement in _TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    for trigger, table in _TRIGGER_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    op.execute(_replace(_PRINCIPALS_03._GUARD_GRANTS))
    op.execute(_replace(_ROLES_03._GUARD))
    op.execute(_replace(_ROLES_03._REFUSALS))
    op.execute(_replace(_PRINCIPALS_03._ROLE_IS_CRITICAL))
    op.execute(_replace(_ROLES_03._ROLE_PRIVILEGES))
    for statement in _ROLES_02._GRANT_FUNCTIONS:
        if "platform.assigned_grants(" in statement or "platform.scopes_in(" in statement:
            op.execute(_replace(statement))
    for function in (
        *_PRIVATE_FUNCTIONS,
        "platform.record_privilege_keys(text, jsonb)",
        "platform.field_permission_keys(uuid)",
        "platform.object_permission_keys(uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TABLE IF EXISTS studio.field_permissions")
    op.execute("DROP TABLE IF EXISTS platform.tenant_role_object_privileges")
    op.execute("DROP TABLE IF EXISTS platform.object_actions")
