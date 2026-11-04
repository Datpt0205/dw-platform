"""role administration and anti-escalation

Revision ID: d2b57239ef50
Revises: 703be798341f
Create Date: 2026-11-04 14:50:47.319339+00:00

tenant-rbac ticket 03 (R6, R7, R8.5, R8.7; RB15-RB26, RB32, RB36, RB43,
RB48-RB50; ADR-0104 decisions 6 and 10 with their amendments of 2026-11-03 and
2026-11-04). Nobody grants what they do not hold, nobody grants to themselves,
a tenant keeps an owner, and every change that does not only narrow takes two
people, held by the database for every writer.

- Two catalogue keys, `platform.roles.write` and `platform.roles.bind` (tenant,
  critical); `bind` joins the `org_admin` template and every tenant's
  `org_admin` clone, but for a clone assigned to a service account (counted and
  printed: its `tenant_owner` holds `bind` through the computed grants).
- `platform.role_privileges(tenant, role)`: what a role carries, `tenant_owner`'s
  computed keys included. `platform.rbac_refusals(tenant, actor, change)`: the one
  answer to "may this person make this change", read by the services before a
  write and by the triggers below for every writer: the hold rule through
  `platform.holder_covers_grant`, `platform.roles.bind` over a role
  `platform.role_is_critical` calls not critical, no self-assignment, no system
  role touched, no key a tenant may not hold and no role keyed `platform_admin`.
- `platform.role_change_requests`: a proposal enters `proposed` from its own
  proposer and leaves it once, to `confirmed` by another holder of its
  permission before it expires, or to `withdrawn`; deleted only while its tenant
  is `offboarding` (`platform.guard_role_change_request`).
- `rbac_refusals_<table>` on `platform.tenant_roles`,
  `platform.tenant_role_permissions` and `platform.role_assignments`
  (`platform.rbac_guard`): a write that only narrows needs `app.user_id` and the
  hold rule, and passes unasked in a tenant `offboarding` or `offboarded`; a write
  that widens also needs the proposal of `app.role_change_id`, confirmed by
  `app.user_id` in this very transaction, of the kind and with the values the
  write carries, but for a Digital Worker principal's first roles in the
  transaction its creator makes the DW. `dw_migrator` is exempt; `dw_provisioner`
  only installs the system roles and assigns `tenant_owner` (Q1, Đạt's
  delegation 31/10/2026). No exemption for the legacy copy trigger (RB48).
- `version` of a role grows in the database: a BEFORE UPDATE trigger on the role
  and an AFTER trigger on its privileges.
- `ck_role_assignments_last_owner`: an `active` or `locked` tenant keeps an active
  owner, cascades included (the owner's assignments are removed first, while the
  person is still visible); a `tenant_owner` assignment never expires.
- A Digital Worker principal's roles are fixed once it leaves `draft`, on
  `platform.role_assignments` now (`trg_role_assignments_dw_principal_roles_fixed`).
- `guard_legacy_role_columns` (only `dw_migrator` adds `platform_admin`, only
  `dw_app` and `dw_migrator` add any key, RB49), `guard_membership_identity`
  (RB50) and `guard_user_created_at` (the DW exception's clock).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2b57239ef50"
down_revision = "703be798341f"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires since cfae5f2d4a13.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_DEPTHS = "ARRAY['own', 'workspace', 'tenant']"
_ACTOR = "NULLIF(current_setting('app.user_id', true), '')::uuid"

# (key, label_vi): both `tenant` keys of risk `critical` (spec, 23/10/2026).
KEYS = (
    ("platform.roles.write", "Tạo và sửa vai trò của công ty"),
    ("platform.roles.bind", "Gán vai trò không trọng yếu cho thành viên"),
)

# -- the proposals ------------------------------------------------------------

_TABLE = (
    """
    CREATE TABLE platform.role_change_requests (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        kind text NOT NULL,
        payload jsonb NOT NULL,
        role_id uuid,
        base_version integer,
        required_permission text NOT NULL,
        proposed_by uuid NOT NULL,
        proposed_at timestamp with time zone DEFAULT now() NOT NULL,
        expires_at timestamp with time zone NOT NULL,
        status text NOT NULL,
        confirmed_by uuid,
        decided_at timestamp with time zone,
        CONSTRAINT pk_role_change_requests PRIMARY KEY (id),
        CONSTRAINT fk_role_change_requests_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE CASCADE,
        CONSTRAINT fk_role_change_requests_tenant_id_tenant_roles FOREIGN KEY (tenant_id, role_id)
            REFERENCES platform.tenant_roles (tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT ck_role_change_requests_kind
            CHECK (kind IN ('role_create', 'role_update', 'role_permissions', 'assignment_grant')),
        CONSTRAINT ck_role_change_requests_status
            CHECK (status IN ('proposed', 'confirmed', 'withdrawn')),
        CONSTRAINT ck_role_change_requests_required_permission
            CHECK (required_permission = CASE WHEN kind = 'assignment_grant'
                   THEN 'platform.roles.bind' ELSE 'platform.roles.write' END),
        CONSTRAINT ck_role_change_requests_role CHECK ((kind = 'role_create') = (role_id IS NULL)),
        CONSTRAINT ck_role_change_requests_payload CHECK (jsonb_typeof(payload) = 'object'),
        CONSTRAINT ck_role_change_requests_expiry
            CHECK (expires_at = proposed_at + interval '7 days'),
        CONSTRAINT ck_role_change_requests_second_person
            CHECK (confirmed_by IS NULL OR confirmed_by <> proposed_by),
        CONSTRAINT ck_role_change_requests_decision CHECK (
            (status = 'proposed' AND confirmed_by IS NULL AND decided_at IS NULL)
            OR (status = 'confirmed' AND confirmed_by IS NOT NULL AND decided_at IS NOT NULL)
            OR (status = 'withdrawn' AND confirmed_by IS NULL AND decided_at IS NOT NULL)
        )
    )
    """,
    # The list pages on (proposed_at, id) within a status, RLS supplying the tenant.
    "CREATE INDEX ix_role_change_requests_tenant_id_status_proposed_at_id"
    " ON platform.role_change_requests (tenant_id, status, proposed_at, id)",
    "CREATE INDEX ix_role_change_requests_tenant_id_role_id"
    " ON platform.role_change_requests (tenant_id, role_id)",
    "ALTER TABLE platform.role_change_requests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ONLY platform.role_change_requests FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_role_change_requests ON platform.role_change_requests"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

# ADR-0012's state machine, as the waivers keep it: in `proposed` from its own
# proposer only; out of it once, to `confirmed` by another holder of its
# permission before it expires, or to `withdrawn`; any UPDATE of a closed row
# refused, even one that changes nothing, because it would renew the `xmin` the
# guard below reads (R7.8). DELETE only while the tenant is `offboarding`, the
# shape of `platform.guard_control_switch()` (R7.7). The migrator ages a row in
# a test; it never deletes one outside offboarding either.
_GUARD_REQUEST = f"""
    CREATE FUNCTION platform.guard_role_change_request() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_actor uuid := {_ACTOR};
        v_status text;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            SELECT t.status INTO v_status FROM platform.tenants t WHERE t.id = OLD.tenant_id;
            IF FOUND AND v_status IS DISTINCT FROM 'offboarding' THEN
                RAISE EXCEPTION 'a role change request is deleted only by the offboarding lane'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_role_change_requests_delete';
            END IF;
            RETURN OLD;
        END IF;
        IF session_user = 'dw_migrator' THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'proposed' OR NEW.confirmed_by IS NOT NULL
               OR NEW.decided_at IS NOT NULL
               OR (session_user = 'dw_app'
                   AND (NEW.proposed_by IS DISTINCT FROM v_actor
                        OR NEW.proposed_at IS DISTINCT FROM now())) THEN
                RAISE EXCEPTION 'a role change request is proposed by its own proposer, open'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_role_change_requests_insert';
            END IF;
            RETURN NEW;
        END IF;
        IF OLD.status <> 'proposed' THEN
            RAISE EXCEPTION 'role change request % is closed', OLD.id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_role_change_requests_closed';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['status', 'confirmed_by', 'decided_at'])
               IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'confirmed_by', 'decided_at'])
           OR NEW.decided_at IS DISTINCT FROM now()
           OR NEW.status NOT IN ('confirmed', 'withdrawn')
           OR (NEW.status = 'withdrawn' AND NEW.confirmed_by IS NOT NULL)
           OR (NEW.status = 'confirmed'
               AND (v_actor IS NULL
                    OR NEW.confirmed_by IS DISTINCT FROM v_actor
                    OR now() >= NEW.expires_at
                    OR NOT EXISTS (
                        SELECT 1 FROM platform.effective_grants(NEW.tenant_id, v_actor) g
                        WHERE g.permission_key = NEW.required_permission
                    ))) THEN
            RAISE EXCEPTION 'role change request % leaves proposed only once, by a holder'
                ' of its permission before it expires', OLD.id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_role_change_requests_transition';
        END IF;
        RETURN NEW;
    END
    $$
"""

# The proposal `app.role_change_id` names, when it opens writes here: of the
# bound tenant, proposed by someone else, confirmed by `app.user_id` in this
# very transaction (the row's `xmin`; a savepoint's write would carry the
# subtransaction's id and open nothing). The `tenant_id` filter is the only
# layer that keeps another tenant's proposal out of the guard, which runs as
# the definer (R3.3).
_IN_FORCE = f"""
    CREATE FUNCTION platform.role_change_in_force()
    RETURNS TABLE (kind text, role_id uuid, payload jsonb)
    LANGUAGE plpgsql
    VOLATILE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_id uuid;
    BEGIN
        BEGIN
            v_id := NULLIF(current_setting('app.role_change_id', true), '')::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            RETURN;
        END;
        RETURN QUERY
        SELECT r.kind, r.role_id, r.payload
        FROM platform.role_change_requests r
        WHERE r.id = v_id
          AND r.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          AND r.status = 'confirmed'
          AND r.confirmed_by = {_ACTOR}
          AND r.proposed_by <> {_ACTOR}
          AND r.xmin = pg_current_xact_id()::xid;
    END
    $$
"""

# -- what a change may be -------------------------------------------------------

# What a role carries: its rows, and for `tenant_owner` every active key a tenant
# may hold, at `tenant` depth, as `platform.assigned_grants` computes them (the
# test `test_role_privileges_of_the_owner_match_its_effective_grants` holds the
# two equal).
_ROLE_PRIVILEGES = """
    CREATE FUNCTION platform.role_privileges(p_tenant_id uuid, p_role_id uuid)
    RETURNS TABLE (permission_key text, depth text)
    LANGUAGE sql STABLE
    AS $$
        SELECT p.permission_key, p.depth
        FROM platform.tenant_role_permissions p
        WHERE p.tenant_id = p_tenant_id AND p.role_id = p_role_id
        UNION ALL
        SELECT k.key, 'tenant'
        FROM platform.tenant_roles r
        CROSS JOIN platform.permissions k
        WHERE r.tenant_id = p_tenant_id AND r.id = p_role_id AND r.key = 'tenant_owner'
          AND k.status = 'active' AND k.tenant_grantable
    $$
"""

# What a role template carries, at the depth a clone gets: `tenant` for a
# tenant key, `workspace` otherwise (an uncatalogued key too, which its foreign
# key then refuses). One owner, read by `install_role_template` and by
# `GET /api/v1/admin/role-templates`, which snapshots it into a proposal.
# SECURITY DEFINER over the two global template tables only: the provisioner,
# which installs `member`, holds no SELECT on `platform.permission_sets`.
_TEMPLATE_PRIVILEGES = """
    CREATE FUNCTION platform.role_template_privileges(p_template_key text)
    RETURNS TABLE (permission_key text, depth text)
    LANGUAGE sql STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
        SELECT DISTINCT s.key,
               CASE WHEN p.scope_kind = 'tenant' THEN 'tenant' ELSE 'workspace' END
        FROM (
            SELECT scopes FROM platform.roles WHERE key = p_template_key
            UNION ALL
            SELECT scopes FROM platform.permission_sets WHERE key = p_template_key
              AND NOT EXISTS (SELECT 1 FROM platform.roles WHERE key = p_template_key)
        ) t
        CROSS JOIN LATERAL jsonb_array_elements_text(t.scopes) s(key)
        LEFT JOIN platform.permissions p ON p.key = s.key
    $$
"""

_INSTALL = """
    CREATE OR REPLACE FUNCTION platform.install_role_template(
        p_tenant_id uuid, p_template_key text
    )
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
        INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key, depth)
        SELECT p_tenant_id, v_id, g.permission_key, g.depth
        FROM platform.role_template_privileges(p_template_key) g;
        RETURN v_id;
    END
    $$
"""

# b5677d345bc1's body, for the downgrade.
_INSTALL_BEFORE = _INSTALL.replace(
    """        SELECT p_tenant_id, v_id, g.permission_key, g.depth
        FROM platform.role_template_privileges(p_template_key) g;""",
    """        SELECT DISTINCT p_tenant_id, v_id, s.key,
               CASE WHEN p.scope_kind = 'tenant' THEN 'tenant' ELSE 'workspace' END
        FROM jsonb_array_elements_text(v_scopes) s(key)
        LEFT JOIN platform.permissions p ON p.key = s.key;""",
)

# ADR-0104 decision 6, one function for both doors. `p_change` is one change:
#   {"op": "grant"|"revoke", "role_id", "workspace_id", "user_id"}  an assignment;
#   {"op": "add"|"raise"|"remove"|"lower", "role_id", "permission_key", "depth"}
#       a privilege of a role, `depth` the one at stake (the new one when it
#       widens, the old one when it narrows);
#   {"op": "role_create"|"role_delete"|"role_rekey"|"role_restore"|"role_update",
#    "role_id", "role_key"}  a role row.
# The hold rule's anchor is the assignment's workspace, or every workspace the
# role is assigned at; a role nobody holds takes the key held at the same or a
# broader depth at any anchor (M16), since its next assignment is judged again.
# `p_lock` takes the actor's own assignments FOR SHARE (f381f1694395's race);
# a read that only previews (`assignable_by_me`) passes false.
_REFUSALS = """
    CREATE FUNCTION platform.rbac_refusals(
        p_tenant_id uuid, p_actor_id uuid, p_change jsonb, p_lock boolean DEFAULT true
    )
    RETURNS TABLE (reason_code text, permission_key text, depth text)
    LANGUAGE plpgsql
    VOLATILE
    SET search_path = pg_catalog, platform
    AS $$
    #variable_conflict use_column
    DECLARE
        v_op text := p_change->>'op';
        v_role uuid := NULLIF(p_change->>'role_id', '')::uuid;
        v_workspace uuid := NULLIF(p_change->>'workspace_id', '')::uuid;
        v_grantee uuid := NULLIF(p_change->>'user_id', '')::uuid;
        v_role_key text;
        v_key text := p_change->>'permission_key';
        v_depth text := p_change->>'depth';
        v_binds boolean;
    BEGIN
        IF p_lock AND p_actor_id IS NOT NULL THEN
            PERFORM 1
            FROM platform.role_assignments a
            JOIN platform.memberships m ON m.tenant_id = a.tenant_id AND m.id = a.membership_id
            WHERE a.tenant_id = p_tenant_id AND m.user_id = p_actor_id
            FOR SHARE OF a;
        END IF;
        SELECT r.key INTO v_role_key FROM platform.tenant_roles r
        WHERE r.tenant_id = p_tenant_id AND r.id = v_role;
        v_role_key := coalesce(p_change->>'role_key', v_role_key);

        IF v_op IN ('grant', 'revoke') THEN
            IF v_op = 'grant' AND v_grantee IS NOT NULL AND v_grantee = p_actor_id THEN
                reason_code := 'rbac_self_assignment';
                RETURN NEXT;
            END IF;
            IF v_op = 'grant' AND (v_role_key = 'platform_admin' OR EXISTS (
                SELECT 1 FROM platform.role_privileges(p_tenant_id, v_role) g
                JOIN platform.permissions k ON k.key = g.permission_key
                WHERE NOT k.tenant_grantable
            )) THEN
                reason_code := 'rbac_not_grantable';
                RETURN NEXT;
            END IF;
            v_binds := EXISTS (
                SELECT 1 FROM platform.effective_grants(p_tenant_id, p_actor_id) h
                WHERE h.permission_key = 'platform.roles.bind'
            ) AND NOT platform.role_is_critical(p_tenant_id, v_role);
            IF NOT v_binds THEN
                RETURN QUERY
                SELECT DISTINCT 'rbac_escalation'::text, g.permission_key, g.depth
                FROM platform.role_privileges(p_tenant_id, v_role) g
                WHERE NOT platform.holder_covers_grant(
                    p_tenant_id, p_actor_id, g.permission_key, g.depth, v_workspace
                );
            END IF;
            RETURN;
        END IF;

        IF v_op IN ('add', 'raise', 'remove', 'lower') THEN
            IF v_role_key = 'tenant_owner' THEN
                reason_code := 'role_is_system';
                RETURN NEXT;
                RETURN;
            END IF;
            IF v_op IN ('add', 'raise') AND EXISTS (
                SELECT 1 FROM platform.permissions k WHERE k.key = v_key AND NOT k.tenant_grantable
            ) THEN
                reason_code := 'rbac_not_grantable';
                permission_key := v_key;
                depth := v_depth;
                RETURN NEXT;
                RETURN;
            END IF;
            RETURN QUERY
            SELECT 'rbac_escalation'::text, v_key, v_depth
            WHERE CASE
                WHEN EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    WHERE a.tenant_id = p_tenant_id AND a.role_id = v_role
                ) THEN EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    WHERE a.tenant_id = p_tenant_id AND a.role_id = v_role
                      AND NOT platform.holder_covers_grant(
                          p_tenant_id, p_actor_id, v_key, v_depth, a.workspace_id
                      )
                )
                ELSE NOT EXISTS (
                    SELECT 1 FROM platform.effective_grants(p_tenant_id, p_actor_id) h
                    WHERE platform.holder_covers_grant(
                        p_tenant_id, p_actor_id, v_key, v_depth, h.anchor_workspace_id
                    )
                )
            END;
            RETURN;
        END IF;

        IF v_op IN ('role_create', 'role_rekey', 'role_delete')
           AND (v_role_key IN ('tenant_owner', 'member')
                OR (v_op = 'role_rekey'
                    AND p_change->>'old_key' IN ('tenant_owner', 'member'))) THEN
            reason_code := 'role_is_system';
            RETURN NEXT;
            RETURN;
        END IF;
        IF v_op IN ('role_create', 'role_rekey') AND v_role_key = 'platform_admin' THEN
            reason_code := 'rbac_not_grantable';
            RETURN NEXT;
            RETURN;
        END IF;
        IF v_op IN ('role_delete', 'role_restore') THEN
            -- What the role's holders lose or regain, at each of their anchors.
            RETURN QUERY
            SELECT DISTINCT 'rbac_escalation'::text, g.permission_key, g.depth
            FROM platform.role_privileges(p_tenant_id, v_role) g
            CROSS JOIN (
                SELECT DISTINCT a.workspace_id FROM platform.role_assignments a
                WHERE a.tenant_id = p_tenant_id AND a.role_id = v_role
            ) w
            WHERE NOT platform.holder_covers_grant(
                p_tenant_id, p_actor_id, g.permission_key, g.depth, w.workspace_id
            );
        END IF;
        RETURN;
    END
    $$
"""

# -- the triggers that judge every writer ---------------------------------------


def _refuse(reason: str, detail: str) -> str:
    return (
        f"RAISE EXCEPTION '{reason}' USING ERRCODE = '23514',"
        f" CONSTRAINT = 'rbac_refusals_' || TG_TABLE_NAME, DETAIL = {detail};"
    )


_PROVISIONER_REFUSED = _refuse(
    "the provisioner installs system roles and assigns tenant_owner only",
    "'rbac_provisioner_scope'",
)
_TWO_PEOPLE_REFUSED = _refuse(
    "a change that widens is applied only by its confirmed proposal", "'rbac_two_people'"
)
_ACTOR_REFUSED = _refuse("a role change names its actor in app.user_id", "'rbac_actor_missing'")

# One function, three tables (`rbac_refusals_<table>`). Each write is neutral
# (the version bump, a user's deletion emptying `created_by` or `assigned_by`),
# narrowing (an assignment removed or shortened, a privilege removed or made
# shallower, a role deleted) or widening (everything else). Every writer but
# the two exempt roles is judged; the legacy copy trigger's writes, nested or
# not, are judged as their writer's (R7.5, RB48).
_GUARD = f"""
    CREATE FUNCTION platform.rbac_guard() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_new jsonb := CASE WHEN TG_OP = 'DELETE' THEN NULL ELSE to_jsonb(NEW) END;
        v_old jsonb := CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE to_jsonb(OLD) END;
        v_tenant uuid := coalesce(v_new->>'tenant_id', v_old->>'tenant_id')::uuid;
        v_actor uuid := {_ACTOR};
        v_class text;
        v_kind text;
        v_changes jsonb[] := '{{}}';
        v_status text;
        v_open record;
        v_matched boolean := false;
        v_refusal record;
        v_grantee uuid;
    BEGIN
        IF session_user = 'dw_migrator' THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END IF;

        IF TG_TABLE_NAME = 'tenant_roles' THEN
            IF TG_OP = 'INSERT' THEN
                v_class := 'widen';
                v_kind := 'role_create';
                v_changes := ARRAY[jsonb_build_object(
                    'op', 'role_create', 'role_id', NEW.id, 'role_key', NEW.key)];
            ELSIF TG_OP = 'DELETE' THEN
                v_class := 'narrow';
                v_changes := ARRAY[jsonb_build_object(
                    'op', 'role_delete', 'role_id', OLD.id, 'role_key', OLD.key)];
            ELSIF (v_new - ARRAY['version', 'updated_at', 'created_by'])
                      = (v_old - ARRAY['version', 'updated_at', 'created_by'])
                  AND (NEW.created_by IS NULL OR NEW.created_by = OLD.created_by) THEN
                v_class := 'neutral';
            ELSIF (v_new - ARRAY['version', 'updated_at', 'deleted_at'])
                      = (v_old - ARRAY['version', 'updated_at', 'deleted_at'])
                  AND OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
                v_class := 'narrow';
                v_changes := ARRAY[jsonb_build_object(
                    'op', 'role_delete', 'role_id', OLD.id, 'role_key', OLD.key)];
            ELSE
                v_class := 'widen';
                IF (v_new - ARRAY['version', 'updated_at', 'name', 'description'])
                       = (v_old - ARRAY['version', 'updated_at', 'name', 'description']) THEN
                    v_kind := 'role_update';
                    v_changes := ARRAY[jsonb_build_object(
                        'op', 'role_update', 'role_id', NEW.id, 'role_key', NEW.key)];
                ELSIF NEW.key IS DISTINCT FROM OLD.key THEN
                    v_changes := ARRAY[jsonb_build_object(
                        'op', 'role_rekey', 'role_id', NEW.id, 'role_key', NEW.key,
                        'old_key', OLD.key)];
                ELSIF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN
                    v_changes := ARRAY[jsonb_build_object(
                        'op', 'role_restore', 'role_id', NEW.id, 'role_key', NEW.key)];
                END IF;
            END IF;
        ELSIF TG_TABLE_NAME = 'tenant_role_permissions' THEN
            IF TG_OP = 'INSERT' THEN
                v_class := 'widen';
                v_kind := 'privilege';
                v_changes := ARRAY[jsonb_build_object('op', 'add', 'role_id', NEW.role_id,
                    'permission_key', NEW.permission_key, 'depth', NEW.depth)];
            ELSIF TG_OP = 'DELETE' THEN
                v_class := 'narrow';
                v_changes := ARRAY[jsonb_build_object('op', 'remove', 'role_id', OLD.role_id,
                    'permission_key', OLD.permission_key, 'depth', OLD.depth)];
            ELSIF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                  OR NEW.role_id IS DISTINCT FROM OLD.role_id
                  OR NEW.permission_key IS DISTINCT FROM OLD.permission_key THEN
                v_class := 'widen';
                v_changes := ARRAY[
                    jsonb_build_object('op', 'remove', 'role_id', OLD.role_id,
                        'permission_key', OLD.permission_key, 'depth', OLD.depth),
                    jsonb_build_object('op', 'add', 'role_id', NEW.role_id,
                        'permission_key', NEW.permission_key, 'depth', NEW.depth)];
            ELSIF array_position({_DEPTHS}, NEW.depth) > array_position({_DEPTHS}, OLD.depth) THEN
                v_class := 'widen';
                v_kind := 'privilege';
                v_changes := ARRAY[jsonb_build_object('op', 'raise', 'role_id', NEW.role_id,
                    'permission_key', NEW.permission_key, 'depth', NEW.depth)];
            ELSIF array_position({_DEPTHS}, NEW.depth) < array_position({_DEPTHS}, OLD.depth) THEN
                v_class := 'narrow';
                v_changes := ARRAY[jsonb_build_object('op', 'lower', 'role_id', OLD.role_id,
                    'permission_key', OLD.permission_key, 'depth', OLD.depth)];
            ELSE
                v_class := 'neutral';
            END IF;
        ELSE
            IF TG_OP = 'INSERT' THEN
                SELECT m.user_id INTO v_grantee FROM platform.memberships m
                WHERE m.tenant_id = NEW.tenant_id AND m.id = NEW.membership_id;
                v_class := 'widen';
                v_kind := 'assignment';
                v_changes := ARRAY[jsonb_build_object('op', 'grant', 'role_id', NEW.role_id,
                    'workspace_id', NEW.workspace_id, 'user_id', v_grantee)];
            ELSIF TG_OP = 'DELETE' THEN
                v_class := 'narrow';
                v_changes := ARRAY[jsonb_build_object('op', 'revoke', 'role_id', OLD.role_id,
                    'workspace_id', OLD.workspace_id)];
            ELSIF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                  OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
                  OR NEW.membership_id IS DISTINCT FROM OLD.membership_id
                  OR NEW.role_id IS DISTINCT FROM OLD.role_id
                  OR (OLD.expires_at IS NOT NULL
                      AND (NEW.expires_at IS NULL OR NEW.expires_at > OLD.expires_at)) THEN
                SELECT m.user_id INTO v_grantee FROM platform.memberships m
                WHERE m.tenant_id = NEW.tenant_id AND m.id = NEW.membership_id;
                v_class := 'widen';
                v_changes := ARRAY[
                    jsonb_build_object('op', 'revoke', 'role_id', OLD.role_id,
                        'workspace_id', OLD.workspace_id),
                    jsonb_build_object('op', 'grant', 'role_id', NEW.role_id,
                        'workspace_id', NEW.workspace_id, 'user_id', v_grantee)];
            ELSIF NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                v_class := 'narrow';
                v_changes := ARRAY[jsonb_build_object('op', 'revoke', 'role_id', OLD.role_id,
                    'workspace_id', OLD.workspace_id)];
            ELSIF (NEW.assigned_by IS NULL OR NEW.assigned_by = OLD.assigned_by)
                  AND NEW.assigned_at = OLD.assigned_at THEN
                v_class := 'neutral';
            ELSE
                v_class := 'widen';
            END IF;
        END IF;

        IF v_class = 'neutral' THEN
            RETURN NEW;
        END IF;
        -- Q1: the provisioner installs the system roles and assigns `tenant_owner`.
        -- (`v_new`, never `NEW.<column>`, where one expression serves the three
        -- tables: a column one of them lacks fails the expression's preparation.)
        IF session_user = 'dw_provisioner' THEN
            IF TG_OP = 'INSERT' AND (
                (TG_TABLE_NAME = 'tenant_roles' AND v_new->>'key' IN ('tenant_owner', 'member'))
                OR (TG_TABLE_NAME = 'tenant_role_permissions' AND EXISTS (
                    SELECT 1 FROM platform.tenant_roles r
                    WHERE r.tenant_id = v_tenant AND r.id = (v_new->>'role_id')::uuid
                      AND r.key = 'member' AND r.xmin = pg_current_xact_id()::xid))
                OR (TG_TABLE_NAME = 'role_assignments' AND EXISTS (
                    SELECT 1 FROM platform.tenant_roles r
                    WHERE r.tenant_id = v_tenant AND r.id = (v_new->>'role_id')::uuid
                      AND r.key = 'tenant_owner'))
            ) THEN
                RETURN NEW;
            END IF;
            {_PROVISIONER_REFUSED}
        END IF;

        -- Offboarding's purge only narrows; it needs neither actor nor rule.
        SELECT t.status INTO v_status FROM platform.tenants t WHERE t.id = v_tenant;
        IF v_class = 'narrow' AND (NOT FOUND OR v_status IN ('offboarding', 'offboarded')) THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END IF;
        IF v_actor IS NULL THEN
            {_ACTOR_REFUSED}
        END IF;

        IF v_class = 'widen' THEN
            IF v_kind = 'assignment' AND platform.dw_principal_first_role(
                v_tenant, (v_new->>'membership_id')::uuid, v_actor
            ) THEN
                v_matched := true;
            ELSE
                -- Exactly the write the proposal's kind allows, on the role (and
                -- membership) it names, with its payload's values (R7.5).
                SELECT * INTO v_open FROM platform.role_change_in_force();
                IF FOUND THEN
                    v_matched := CASE
                        WHEN v_open.kind = 'role_create' THEN
                            (v_kind = 'role_create'
                             AND v_new->>'id' = v_open.payload->>'role_id'
                             AND v_new->>'key' = v_open.payload->>'key'
                             AND v_new->>'name' = v_open.payload->>'name'
                             AND v_new->'description' IS NOT DISTINCT FROM
                                 coalesce(v_open.payload->'description', 'null'::jsonb)
                             AND v_new->>'kind' = v_open.payload->>'kind'
                             AND (v_new->'template_key' = 'null'::jsonb
                                  OR v_new->>'template_key' = v_open.payload->>'template_key')
                             AND v_new->'deleted_at' = 'null'::jsonb)
                            OR (v_kind = 'privilege' AND TG_OP = 'INSERT'
                                AND v_new->>'role_id' = v_open.payload->>'role_id'
                                AND v_open.payload->'permissions' @> jsonb_build_array(
                                    jsonb_build_object('key', v_new->>'permission_key',
                                                       'depth', v_new->>'depth')))
                        WHEN v_open.kind = 'role_update' THEN
                            v_kind = 'role_update'
                            AND (v_new->>'id')::uuid = v_open.role_id
                            AND v_new->>'name' = v_open.payload->>'name'
                            AND v_new->'description' IS NOT DISTINCT FROM
                                coalesce(v_open.payload->'description', 'null'::jsonb)
                        WHEN v_open.kind = 'role_permissions' THEN
                            v_kind = 'privilege'
                            AND (v_new->>'role_id')::uuid = v_open.role_id
                            AND v_open.payload->'permissions' @> jsonb_build_array(
                                jsonb_build_object('key', v_new->>'permission_key',
                                                   'depth', v_new->>'depth'))
                        WHEN v_open.kind = 'assignment_grant' THEN
                            v_kind = 'assignment'
                            AND (v_new->>'role_id')::uuid = v_open.role_id
                            AND v_new->>'membership_id' = v_open.payload->>'membership_id'
                        ELSE false
                    END;
                END IF;
            END IF;
            IF NOT coalesce(v_matched, false) THEN
                {_TWO_PEOPLE_REFUSED}
            END IF;
        END IF;

        FOR v_refusal IN
            SELECT r.reason_code,
                   string_agg(r.permission_key || ':' || r.depth, ',' ORDER BY r.permission_key)
                       AS keys
            FROM unnest(v_changes) c(change)
            CROSS JOIN LATERAL platform.rbac_refusals(v_tenant, v_actor, c.change) r
            GROUP BY r.reason_code
            ORDER BY r.reason_code
            LIMIT 1
        LOOP
            RAISE EXCEPTION 'refused: %', v_refusal.reason_code
                USING ERRCODE = '23514', CONSTRAINT = 'rbac_refusals_' || TG_TABLE_NAME,
                      DETAIL = v_refusal.reason_code, HINT = coalesce(v_refusal.keys, '');
        END LOOP;
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END
    $$
"""

# The one exception to "every assignment is a proposal" (ADR-0104, Amendments
# 2026-11-03, 2026-11-04): the membership is a Digital Worker principal's, in the
# DW's workspace, the DW is `draft`, made by `p_actor` in this very transaction,
# and the principal is a `service` user with its `platform.service_principals`
# row, made in this transaction too (`created_at` is the transaction's `now()`
# and `guard_user_created_at` keeps it), so an existing run-as account pointed
# at by a new DW gets no role alone.
_DW_FIRST_ROLE = """
    CREATE FUNCTION platform.dw_principal_first_role(
        p_tenant_id uuid, p_membership_id uuid, p_actor_id uuid
    )
    RETURNS boolean
    LANGUAGE sql
    VOLATILE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
        SELECT EXISTS (
            SELECT 1
            FROM platform.memberships m
            JOIN platform.digital_workers d
              ON d.tenant_id = m.tenant_id AND d.principal_user_id = m.user_id
             AND d.workspace_id = m.workspace_id
            JOIN platform.users u ON u.id = m.user_id
            JOIN platform.service_principals p
              ON p.tenant_id = m.tenant_id AND p.user_id = m.user_id
            WHERE m.tenant_id = p_tenant_id AND m.id = p_membership_id
              AND d.state = 'draft'
              AND d.created_by = p_actor_id
              AND d.xmin = pg_current_xact_id()::xid
              AND u.kind = 'service'
              AND u.created_at = now()
        )
    $$
"""

# digital-worker R1.17, moved to the assignments: a principal's roles do not
# grow once its DW leaves `draft`, for every writer but the migrator. Named to
# fire after `rbac_refusals_role_assignments`.
_DW_ROLES_FIXED = """
    CREATE OR REPLACE FUNCTION platform.dw_principal_roles_fixed() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF session_user = 'dw_migrator' THEN
            RETURN NEW;
        END IF;
        IF EXISTS (
            SELECT 1 FROM platform.memberships m
            JOIN platform.digital_workers d
              ON d.tenant_id = m.tenant_id AND d.principal_user_id = m.user_id
            WHERE m.tenant_id = NEW.tenant_id AND m.id = NEW.membership_id
              AND d.state <> 'draft'
        ) THEN
            RAISE EXCEPTION 'the roles of a digital worker principal are fixed'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_memberships_dw_principal_roles_fixed';
        END IF;
        RETURN NEW;
    END
    $$
"""

# be93e0c26a4c's version, for the downgrade.
_DW_ROLES_FIXED_BEFORE = """
    CREATE OR REPLACE FUNCTION platform.dw_principal_roles_fixed() RETURNS trigger
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

# -- version (R8.5, R8.7) -------------------------------------------------------

# A role's ETag moves on every change to it that the statement did not number
# itself; a merge patch that changes nothing moves nothing (app-standards R3.16).
_ROLE_VERSION = """
    CREATE FUNCTION platform.bump_tenant_role_version() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF NEW.version = OLD.version
           AND (to_jsonb(NEW) - ARRAY['version', 'updated_at'])
               IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['version', 'updated_at']) THEN
            NEW.version := OLD.version + 1;
        END IF;
        RETURN NEW;
    END
    $$
"""

# Every write to a role's privileges moves the role's version, so a proposal
# read before it goes stale. Named to sort before `trg_z_bump_access_version`:
# the role row is taken before the tenant's access-version row.
_PARENT_VERSION = """
    CREATE FUNCTION platform.bump_parent_role_version() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            UPDATE platform.tenant_roles SET version = version + 1
            WHERE tenant_id = OLD.tenant_id AND id = OLD.role_id;
        END IF;
        IF TG_OP <> 'DELETE' AND (TG_OP = 'INSERT' OR NEW.role_id IS DISTINCT FROM OLD.role_id) THEN
            UPDATE platform.tenant_roles SET version = version + 1
            WHERE tenant_id = NEW.tenant_id AND id = NEW.role_id;
        END IF;
        RETURN NULL;
    END
    $$
"""

# -- the last owner (R6.7) -----------------------------------------------------

# AFTER a `tenant_owner` assignment goes, or its holder stops being `active`: an
# `active` or `locked` tenant that had the holder as an active owner must still
# count one (`platform.active_tenant_owners`, ticket 02), counted after the
# tenant row is locked so two removals of the last two queue. A tenant with no
# owner at all is left alone; `setup` keeps R3.10's rule; offboarding is not
# judged. A `tenant_owner` assignment never expires.
_LAST_OWNER = """
    CREATE FUNCTION platform.refuse_losing_the_last_owner() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid;
        v_user uuid;
    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN
            IF TG_OP <> 'DELETE' AND NEW.expires_at IS NOT NULL AND EXISTS (
                SELECT 1 FROM platform.tenant_roles r
                WHERE r.tenant_id = NEW.tenant_id AND r.id = NEW.role_id AND r.key = 'tenant_owner'
            ) THEN
                RAISE EXCEPTION 'a tenant_owner assignment does not expire'
                    USING ERRCODE = 'check_violation',
                          CONSTRAINT = 'ck_role_assignments_last_owner';
            END IF;
            IF TG_OP = 'INSERT' OR NOT EXISTS (
                SELECT 1 FROM platform.tenant_roles r
                WHERE r.tenant_id = OLD.tenant_id AND r.id = OLD.role_id AND r.key = 'tenant_owner'
            ) THEN
                RETURN NULL;
            END IF;
            v_tenant := OLD.tenant_id;
            SELECT m.user_id INTO v_user FROM platform.memberships m
            WHERE m.tenant_id = OLD.tenant_id AND m.id = OLD.membership_id;
        ELSE
            IF OLD.status <> 'active' OR NEW.status = 'active' THEN
                RETURN NULL;
            END IF;
            v_tenant := OLD.tenant_id;
            v_user := OLD.user_id;
            IF NOT EXISTS (
                SELECT 1 FROM platform.role_assignments a
                JOIN platform.memberships m ON m.tenant_id = a.tenant_id AND m.id = a.membership_id
                JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
                WHERE a.tenant_id = v_tenant AND m.user_id = v_user AND r.key = 'tenant_owner'
            ) THEN
                RETURN NULL;
            END IF;
        END IF;
        IF v_user IS NULL OR NOT EXISTS (
            SELECT 1 FROM platform.tenant_members tm
            WHERE tm.tenant_id = v_tenant AND tm.user_id = v_user
              AND (tm.status = 'active' OR TG_TABLE_NAME = 'tenant_members')
        ) OR NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('active', 'locked')
        ) THEN
            RETURN NULL;
        END IF;
        PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;
        IF NOT EXISTS (SELECT 1 FROM platform.active_tenant_owners(v_tenant)) THEN
            RAISE EXCEPTION 'tenant % keeps at least one active owner', v_tenant
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_role_assignments_last_owner';
        END IF;
        RETURN NULL;
    END
    $$
"""

# BEFORE a membership, a company row or (through them) a user goes: the
# `tenant_owner` assignments it carries go first, as their own statement, while
# the person and their company row are still there to be read by the check
# above. The cascade would remove them anyway, after the person was gone.
_OWNERS_FIRST = """
    CREATE FUNCTION platform.remove_owner_assignments_first() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_old jsonb := to_jsonb(OLD);
    BEGIN
        DELETE FROM platform.role_assignments a
        USING platform.memberships m, platform.tenant_roles r
        WHERE m.tenant_id = a.tenant_id AND m.id = a.membership_id
          AND r.tenant_id = a.tenant_id AND r.id = a.role_id AND r.key = 'tenant_owner'
          AND a.tenant_id = (v_old->>'tenant_id')::uuid
          AND CASE WHEN TG_TABLE_NAME = 'memberships' THEN m.id = (v_old->>'id')::uuid
                   ELSE m.user_id = (v_old->>'user_id')::uuid END;
        RETURN OLD;
    END
    $$
"""

# -- the legacy columns and the membership's identity (RB49, RB50) ---------------

# A key added to `role_keys` or `permission_set_keys` (present in NEW, absent in
# OLD; every key on INSERT): `platform_admin` only by the migrator (ADR-0104
# decision 8), any key only by `dw_app` (judged by the copy trigger's writes)
# and the migrator. Keeping or removing a key is not judged.
_LEGACY = """
    CREATE FUNCTION platform.guard_legacy_role_columns() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_added text[];
    BEGIN
        v_added := ARRAY(
            SELECT k FROM (
                SELECT jsonb_array_elements_text(NEW.role_keys)
                UNION SELECT jsonb_array_elements_text(NEW.permission_set_keys)
            ) n(k)
            EXCEPT
            SELECT k FROM (
                SELECT jsonb_array_elements_text(OLD.role_keys) WHERE TG_OP = 'UPDATE'
                UNION SELECT jsonb_array_elements_text(OLD.permission_set_keys)
                WHERE TG_OP = 'UPDATE'
            ) o(k)
        );
        IF cardinality(v_added) > 0
           AND (('platform_admin' = ANY (v_added) AND session_user <> 'dw_migrator')
                OR session_user NOT IN ('dw_app', 'dw_migrator')) THEN
            RAISE EXCEPTION 'this writer may not add % to the legacy role columns', v_added
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_memberships_legacy_role_writer';
        END IF;
        RETURN NEW;
    END
    $$
"""

# An assignment hangs off its membership: moving the membership to another
# person, workspace or tenant would move every assignment with it, past every
# rule above.
_IDENTITY = """
    CREATE FUNCTION platform.guard_membership_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF (NEW.tenant_id, NEW.workspace_id, NEW.user_id)
               IS DISTINCT FROM (OLD.tenant_id, OLD.workspace_id, OLD.user_id)
           AND session_user <> 'dw_migrator' THEN
            RAISE EXCEPTION 'a membership keeps its tenant, workspace and person'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_memberships_identity_fixed';
        END IF;
        RETURN NEW;
    END
    $$
"""

_USER_CREATED_AT = """
    CREATE FUNCTION platform.guard_user_created_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF NEW.created_at IS DISTINCT FROM OLD.created_at AND session_user <> 'dw_migrator' THEN
            RAISE EXCEPTION 'a user keeps the time it was created'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'ck_users_created_at_fixed';
        END IF;
        RETURN NEW;
    END
    $$
"""

# b5677d345bc1's coverage check, which this ticket's key wakes: once
# `platform.roles.write` is active, a tenant written before its first workspace
# (the seed installs the system roles first) counted below two and wrote an
# outbox row with no workspace, which the table refuses. With no workspace
# there is nobody to warn yet; the first write after one exists announces.
_COVERAGE = """
    CREATE OR REPLACE FUNCTION platform.check_owner_coverage(p_tenant_id uuid) RETURNS void
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
        SELECT id INTO v_workspace FROM platform.workspaces
        WHERE tenant_id = p_tenant_id
        ORDER BY (slug = 'main') DESC, created_at, id LIMIT 1;
        IF v_workspace IS NULL THEN
            RETURN;
        END IF;
        v_low := ARRAY(
            SELECT k.key FROM platform.permissions k
            WHERE k.key = ANY (platform.owner_permission_keys()) AND k.status = 'active'
              AND (SELECT count(*) FROM platform.checker_candidates(p_tenant_id, k.key, NULL)) < 2
            ORDER BY k.key
        );
        IF cardinality(v_low) > 0 THEN
            UPDATE platform.tenants SET owner_coverage_low_since = now()
            WHERE id = p_tenant_id AND owner_coverage_low_since IS NULL
            RETURNING owner_coverage_low_since INTO v_since;
            IF FOUND THEN
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
"""
_COVERAGE_BEFORE = _COVERAGE.replace(
    """        SELECT id INTO v_workspace FROM platform.workspaces
        WHERE tenant_id = p_tenant_id
        ORDER BY (slug = 'main') DESC, created_at, id LIMIT 1;
        IF v_workspace IS NULL THEN
            RETURN;
        END IF;
""",
    "",
).replace(
    """            IF FOUND THEN
                INSERT""",
    """            IF FOUND THEN
                SELECT id INTO v_workspace FROM platform.workspaces
                WHERE tenant_id = p_tenant_id
                ORDER BY (slug = 'main') DESC, created_at, id LIMIT 1;
                INSERT""",
)

_ROLE_TABLES = ("tenant_roles", "tenant_role_permissions", "role_assignments")

_TRIGGERS = (
    *(
        f"CREATE TRIGGER rbac_refusals_{table} BEFORE INSERT OR UPDATE OR DELETE"
        f" ON platform.{table} FOR EACH ROW EXECUTE FUNCTION platform.rbac_guard()"
        for table in _ROLE_TABLES
    ),
    "CREATE TRIGGER guard_role_change_request BEFORE INSERT OR UPDATE OR DELETE"
    " ON platform.role_change_requests"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_role_change_request()",
    "CREATE TRIGGER trg_tenant_roles_version BEFORE UPDATE ON platform.tenant_roles"
    " FOR EACH ROW EXECUTE FUNCTION platform.bump_tenant_role_version()",
    "CREATE TRIGGER trg_tenant_role_permissions_role_version"
    " AFTER INSERT OR UPDATE OR DELETE ON platform.tenant_role_permissions"
    " FOR EACH ROW EXECUTE FUNCTION platform.bump_parent_role_version()",
    "CREATE TRIGGER ck_role_assignments_last_owner AFTER INSERT OR UPDATE OR DELETE"
    " ON platform.role_assignments"
    " FOR EACH ROW EXECUTE FUNCTION platform.refuse_losing_the_last_owner()",
    "CREATE TRIGGER ck_role_assignments_last_owner AFTER UPDATE OF status"
    " ON platform.tenant_members"
    " FOR EACH ROW EXECUTE FUNCTION platform.refuse_losing_the_last_owner()",
    "CREATE TRIGGER trg_memberships_owner_assignments_first BEFORE DELETE"
    " ON platform.memberships"
    " FOR EACH ROW EXECUTE FUNCTION platform.remove_owner_assignments_first()",
    "CREATE TRIGGER trg_tenant_members_owner_assignments_first BEFORE DELETE"
    " ON platform.tenant_members"
    " FOR EACH ROW EXECUTE FUNCTION platform.remove_owner_assignments_first()",
    "CREATE TRIGGER trg_role_assignments_dw_principal_roles_fixed"
    " BEFORE INSERT OR UPDATE OF role_id, membership_id ON platform.role_assignments"
    " FOR EACH ROW EXECUTE FUNCTION platform.dw_principal_roles_fixed()",
    "CREATE TRIGGER guard_legacy_role_columns"
    " BEFORE INSERT OR UPDATE OF role_keys, permission_set_keys ON platform.memberships"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_legacy_role_columns()",
    "CREATE TRIGGER guard_membership_identity"
    " BEFORE UPDATE OF tenant_id, workspace_id, user_id ON platform.memberships"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_membership_identity()",
    "CREATE TRIGGER guard_user_created_at BEFORE UPDATE OF created_at ON platform.users"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_user_created_at()",
)

_TRIGGER_TABLES = (
    *((f"rbac_refusals_{table}", table) for table in _ROLE_TABLES),
    ("guard_role_change_request", "role_change_requests"),
    ("trg_tenant_roles_version", "tenant_roles"),
    ("trg_tenant_role_permissions_role_version", "tenant_role_permissions"),
    ("ck_role_assignments_last_owner", "role_assignments"),
    ("ck_role_assignments_last_owner", "tenant_members"),
    ("trg_memberships_owner_assignments_first", "memberships"),
    ("trg_tenant_members_owner_assignments_first", "tenant_members"),
    ("trg_role_assignments_dw_principal_roles_fixed", "role_assignments"),
    ("guard_legacy_role_columns", "memberships"),
    ("guard_membership_identity", "memberships"),
    ("guard_user_created_at", "users"),
)

# Nobody calls these but a trigger or the guard; `dw_app` calls the two below.
_PRIVATE_FUNCTIONS = (
    "platform.guard_role_change_request()",
    "platform.role_change_in_force()",
    "platform.rbac_guard()",
    "platform.dw_principal_first_role(uuid, uuid, uuid)",
    "platform.bump_tenant_role_version()",
    "platform.bump_parent_role_version()",
    "platform.refuse_losing_the_last_owner()",
    "platform.remove_owner_assignments_first()",
    "platform.guard_legacy_role_columns()",
    "platform.guard_membership_identity()",
    "platform.guard_user_created_at()",
)
_APP_FUNCTIONS = (
    "platform.rbac_refusals(uuid, uuid, jsonb, boolean)",
    "platform.role_privileges(uuid, uuid)",
    "platform.role_template_privileges(text)",
)

# Step 1: `bind` for every `org_admin` clone, but one assigned to a service
# account, which `guard_service_principal_grants` would refuse (`bind` is
# critical); those tenants are printed, their owners hold `bind` already.
SKIPPED_ORG_ADMINS = """
    SELECT t.slug FROM platform.tenant_roles r
    JOIN platform.tenants t ON t.id = r.tenant_id
    WHERE r.key = 'org_admin'
      AND EXISTS (SELECT 1 FROM platform.service_holders_of_role(r.tenant_id, r.id))
    ORDER BY t.slug
"""
BIND_ORG_ADMINS = """
    INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key, depth)
    SELECT r.tenant_id, r.id, 'platform.roles.bind', 'tenant'
    FROM platform.tenant_roles r
    WHERE r.key = 'org_admin'
      AND NOT EXISTS (SELECT 1 FROM platform.service_holders_of_role(r.tenant_id, r.id))
    ON CONFLICT (role_id, permission_key) DO NOTHING
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


def _bind_org_admins() -> None:
    bind = op.get_bind()
    if bind is None:  # a recording stand-in for `op` (unit tests) has no connection
        op.execute(BIND_ORG_ADMINS)
        return
    skipped = [row[0] for row in bind.execute(sa.text(SKIPPED_ORG_ADMINS))]
    print(
        "tenant-rbac/03: org_admin clones assigned to a service account, left without"
        f" platform.roles.bind: {', '.join(skipped) if skipped else '(none)'}"
    )
    bind.execute(sa.text(BIND_ORG_ADMINS))


def upgrade() -> None:
    # 1. The two keys, the `org_admin` template, then its clones (before the
    # triggers below exist, as the migrator). The coverage check first: the
    # write key it counts becomes active here.
    op.execute(_COVERAGE)
    for key, label in KEYS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'platform', :l, 'tenant', 'critical', 'active', NULL,"
                " 'dw_platform', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label)
        )
    op.execute(
        "UPDATE platform.roles SET scopes = scopes || '[\"platform.roles.bind\"]'::jsonb"
        " WHERE key = 'org_admin' AND NOT scopes ? 'platform.roles.bind'"
    )
    _bind_org_admins()

    # 2. The proposals, their privileges.
    for statement in _TABLE:
        op.execute(statement)
    op.execute(
        _for_role(
            "dw_app",
            "REVOKE ALL ON platform.role_change_requests FROM dw_app;"
            " GRANT SELECT, INSERT, DELETE ON platform.role_change_requests TO dw_app;"
            " GRANT UPDATE (status, confirmed_by, decided_at)"
            " ON platform.role_change_requests TO dw_app;",
        )
    )
    op.execute(
        _for_role("dw_agent_ro", "REVOKE ALL ON platform.role_change_requests FROM dw_agent_ro;")
    )

    # 3. Functions; the DW guard moves from the memberships to the assignments.
    op.execute("DROP TRIGGER IF EXISTS dw_principal_roles_fixed ON platform.memberships")
    for statement in (
        _GUARD_REQUEST,
        _IN_FORCE,
        _TEMPLATE_PRIVILEGES,
        _INSTALL,
        _ROLE_PRIVILEGES,
        _REFUSALS,
        _DW_FIRST_ROLE,
        _GUARD,
        _DW_ROLES_FIXED,
        _ROLE_VERSION,
        _PARENT_VERSION,
        _LAST_OWNER,
        _OWNERS_FIRST,
        _LEGACY,
        _IDENTITY,
        _USER_CREATED_AT,
    ):
        op.execute(statement)
    for function in (*_PRIVATE_FUNCTIONS, *_APP_FUNCTIONS):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in _APP_FUNCTIONS:
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))
    # The provisioner installs the `member` template through it.
    op.execute(
        _for_role(
            "dw_provisioner",
            "GRANT EXECUTE ON FUNCTION platform.role_template_privileges(text) TO dw_provisioner;",
        )
    )

    # 4. The triggers that judge writes.
    for statement in _TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    for trigger, table in _TRIGGER_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON platform.{table}")
    op.execute(_DW_ROLES_FIXED_BEFORE)
    op.execute(
        "CREATE TRIGGER dw_principal_roles_fixed"
        " BEFORE INSERT OR UPDATE ON platform.memberships"
        " FOR EACH ROW EXECUTE FUNCTION platform.dw_principal_roles_fixed()"
    )
    for function in (
        "platform.rbac_guard()",
        "platform.dw_principal_first_role(uuid, uuid, uuid)",
        "platform.rbac_refusals(uuid, uuid, jsonb, boolean)",
        "platform.role_privileges(uuid, uuid)",
        "platform.role_change_in_force()",
        "platform.guard_role_change_request()",
        "platform.bump_tenant_role_version()",
        "platform.bump_parent_role_version()",
        "platform.refuse_losing_the_last_owner()",
        "platform.remove_owner_assignments_first()",
        "platform.guard_legacy_role_columns()",
        "platform.guard_membership_identity()",
        "platform.guard_user_created_at()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute(_INSTALL_BEFORE)
    op.execute("DROP FUNCTION IF EXISTS platform.role_template_privileges(text)")
    op.execute("DROP TABLE IF EXISTS platform.role_change_requests")
    op.execute(
        "DELETE FROM platform.tenant_role_permissions"
        " WHERE permission_key IN ('platform.roles.write', 'platform.roles.bind')"
    )
    op.execute(
        "UPDATE platform.roles SET scopes = scopes - 'platform.roles.bind' WHERE key = 'org_admin'"
    )
    op.execute(
        "DELETE FROM platform.permissions"
        " WHERE key IN ('platform.roles.write', 'platform.roles.bind')"
    )
    op.execute(_COVERAGE_BEFORE)
