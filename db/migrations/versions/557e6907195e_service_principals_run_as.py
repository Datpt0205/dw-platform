"""service principals run as

Revision ID: 557e6907195e
Revises: 67071483caa6
Create Date: 2026-11-03 04:11:32.868684+00:00

org-and-principals ticket 03 (R6.1-R6.6, R6.8-R6.20, R7; ADR-0103 decisions 2-4,
ADR-0104 decision 6). A company's service account is a `platform.users` row of
kind `service` that never signs in, never holds a critical privilege, has an
accountable owner who is an `active` human member, and is bound as a run's
principal only by someone who holds every privilege it holds. This extends the
objects digital-worker/01 made in be93e0c26a4c; it rebuilds none of them.

- `platform.service_principals` gains `description`, `created_by`, `updated_at`
  (touched by the trigger), a name that is not blank (`ck_service_principals_name`
  replaced under the same name) and unique per tenant
  (`uq_service_principals_tenant_id_name`, earlier duplicates renamed and
  counted), and its accountable owner as a composite key to
  `platform.tenant_members` `ON DELETE SET NULL (owner_user_id)` (rows whose owner
  has no company row are set NULL first, and counted).
- `platform.guard_accountable_owner()` asks for an owner on INSERT and, whenever
  the owner is set or changes, an `active` human member of the tenant;
  `platform.accountable_owner_present()` is the one answer to "is the owner
  present", read by the binding guard, `platform.dw_work_scopes_due` and the
  `dw_work` lane's claim.
- `platform.guard_service_user_tenant()`: a service user is a company member of
  its own tenant only (`ck_tenant_members_service_own_tenant`).
- `platform.role_is_critical()`: the one owner of "critical role" (`tenant_owner`
  or a key of risk `critical`). `platform.guard_service_principal_grants()`
  refuses such a role reaching a service user by assignment, by a critical key
  added to a role it holds, or by restoring one (`ck_role_assignments_service_not_critical`),
  for every writer; `platform.service_principal_grants_changed()` writes one
  `platform.service_principal.grants_changed` outbox row per service account
  whose assigned grants grow. Both lock the role row `FOR NO KEY UPDATE`, and
  sort before `trg_z_bump_access_version`: one lock order, the role row before
  the tenant's access-version row.
- `platform.holder_covers_grant()` (the cover rule, from `grants_cover`),
  `platform.uncovered_grants()` and `platform.grants_cover()` rewritten over it.
- `platform.is_digital_worker_principal()`: SECURITY DEFINER, because a DW of
  another workspace is invisible under the caller's RLS.
- `platform.purge_tenant_service_users()`: the offboarding lane's step for the
  service users `dw_app` may not delete itself.
- Two keys, `platform.service_principals.manage` and `.use`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "557e6907195e"
down_revision = "67071483caa6"
branch_labels = None
depends_on = None

_DEPTHS = "ARRAY['own', 'workspace', 'tenant']"

# -- data checked or repaired before the constraints ---------------------------

# Refused, never repaired: a name someone gave is not renamed by a guess.
_NAMES_INVALID = """
    DO $$
    DECLARE
        v_count integer;
    BEGIN
        SELECT count(*) INTO v_count FROM platform.service_principals
        WHERE NOT (btrim(name) <> '' AND char_length(name) <= 120);
        IF v_count > 0 THEN
            RAISE EXCEPTION 'org-and-principals/03: % service principal name(s) are blank or'
                ' longer than 120 characters; fix them before this migration', v_count;
        END IF;
    END
    $$
"""

# Every name equal to an earlier one of its tenant (by `created_at`, then
# `user_id`) takes the first eight characters of its id: at most 119 characters.
RENAME_DUPLICATES = """
    UPDATE platform.service_principals p
    SET name = left(p.name, 108) || ' (' || left(p.user_id::text, 8) || ')'
    WHERE EXISTS (
        SELECT 1 FROM platform.service_principals q
        WHERE q.tenant_id = p.tenant_id AND q.name = p.name
          AND (q.created_at, q.user_id) < (p.created_at, p.user_id)
    )
"""

# The composite key below needs a company row for every owner it names.
CLEAR_OWNERS_WITHOUT_MEMBER = """
    UPDATE platform.service_principals p SET owner_user_id = NULL
    WHERE p.owner_user_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM platform.tenant_members tm
          WHERE tm.tenant_id = p.tenant_id AND tm.user_id = p.owner_user_id
      )
"""

# Refused, never repaired: removing a role someone gave is a decision.
_CRITICAL_HELD = """
    DO $$
    DECLARE
        v_count integer;
    BEGIN
        SELECT count(*) INTO v_count
        FROM platform.role_assignments a
        JOIN platform.memberships m ON m.id = a.membership_id
        JOIN platform.users u ON u.id = m.user_id AND u.kind = 'service'
        WHERE platform.role_is_critical(a.tenant_id, a.role_id);
        IF v_count > 0 THEN
            RAISE EXCEPTION 'org-and-principals/03: % assignment(s) give a service user'
                ' tenant_owner or a critical key; remove them before this migration', v_count;
        END IF;
    END
    $$
"""

# -- the table ---------------------------------------------------------------

_TABLE = (
    """
    ALTER TABLE platform.service_principals
        ADD COLUMN description text,
        ADD COLUMN created_by uuid,
        ADD COLUMN updated_at timestamp with time zone DEFAULT now() NOT NULL,
        ADD CONSTRAINT ck_service_principals_description
            CHECK (description IS NULL OR char_length(description) <= 1000),
        ADD CONSTRAINT fk_service_principals_created_by_users
            FOREIGN KEY (created_by) REFERENCES platform.users (id) ON DELETE SET NULL
    """,
    "CREATE INDEX ix_service_principals_created_by ON platform.service_principals (created_by)",
    "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON platform.service_principals"
    " FOR EACH ROW EXECUTE FUNCTION platform.touch_updated_at()",
    """
    ALTER TABLE platform.service_principals
        DROP CONSTRAINT ck_service_principals_name,
        ADD CONSTRAINT ck_service_principals_name
            CHECK (btrim(name) <> '' AND char_length(name) <= 120)
    """,
    "ALTER TABLE platform.service_principals"
    " ADD CONSTRAINT uq_service_principals_tenant_id_name UNIQUE (tenant_id, name)",
    "ALTER TABLE platform.service_principals"
    " DROP CONSTRAINT fk_service_principals_owner_user_id_users",
    "DROP INDEX platform.ix_service_principals_owner_user_id",
    # Removing the owner's company row empties the column and keeps the
    # account (R6.16); its own company row is no key of it (H8).
    """
    ALTER TABLE platform.service_principals
        ADD CONSTRAINT fk_service_principals_tenant_id_tenant_members
            FOREIGN KEY (tenant_id, owner_user_id)
            REFERENCES platform.tenant_members (tenant_id, user_id)
            ON DELETE SET NULL (owner_user_id)
    """,
    "CREATE INDEX ix_service_principals_tenant_id_owner_user_id"
    " ON platform.service_principals (tenant_id, owner_user_id)",
)

# -- functions ----------------------------------------------------------------

# R6.16: the principal is a service user of its own tenant (unchanged), and its
# accountable owner, given on INSERT and whenever it is set or changed, an
# `active` human member of the tenant. Back to NULL is the composite key's SET
# NULL; the API refuses it at the request.
_GUARD_OWNER = """
    CREATE OR REPLACE FUNCTION platform.guard_accountable_owner() RETURNS trigger
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
        IF TG_OP = 'INSERT' AND NEW.owner_user_id IS NULL THEN
            RAISE EXCEPTION 'a service principal has an accountable owner'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_service_principals_accountable_owner';
        END IF;
        IF NEW.owner_user_id IS NOT NULL
           AND (TG_OP = 'INSERT'
                OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id)
           AND NOT EXISTS (
               SELECT 1 FROM platform.users u
               JOIN platform.tenant_members tm ON tm.user_id = u.id
               WHERE u.id = NEW.owner_user_id AND u.kind = 'human'
                 AND tm.tenant_id = NEW.tenant_id AND tm.status = 'active'
           ) THEN
            RAISE EXCEPTION 'the accountable owner is an active human member of the tenant'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_service_principals_accountable_owner';
        END IF;
        RETURN NEW;
    END
    $$
"""

# The one answer to "is this account's accountable owner present" (R6.17,
# R6.18): an owner, and their company row `active`. SECURITY INVOKER: the
# binding guard reads it under the caller's RLS, the lane's scan as its owner.
_OWNER_PRESENT = """
    CREATE FUNCTION platform.accountable_owner_present(p_tenant_id uuid, p_principal_id uuid)
    RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT EXISTS (
            SELECT 1
            FROM platform.service_principals p
            JOIN platform.tenant_members tm
              ON tm.tenant_id = p.tenant_id AND tm.user_id = p.owner_user_id
            WHERE p.tenant_id = p_tenant_id AND p.user_id = p_principal_id
              AND tm.status = 'active'
        )
    $$
"""

# R6.18: no new work for a DW whose owner is not present; the reclaim of work
# stuck `in_progress` is unchanged.
_SCOPES_DUE = """
    CREATE OR REPLACE FUNCTION platform.dw_work_scopes_due(p_limit integer)
    RETURNS TABLE (tenant_id uuid, workspace_id uuid)
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
        SELECT DISTINCT w.tenant_id, w.workspace_id
        FROM platform.work_items w
        JOIN platform.digital_workers d ON d.id = w.dw_id
        JOIN platform.service_principals p ON p.user_id = d.principal_user_id
        WHERE (
                w.status = 'open' AND w.available_at <= now()
                AND d.state = 'operating'
                AND platform.accountable_owner_present(p.tenant_id, p.user_id)
              )
           OR (w.status = 'in_progress' AND w.updated_at <= now() - interval '15 minutes')
        ORDER BY w.tenant_id, w.workspace_id
        LIMIT greatest(p_limit, 0)
    $$
"""

# The DW lane's scan as it was (cfbd906be98b), for the downgrade.
_SCOPES_DUE_BEFORE = _SCOPES_DUE.replace(
    "platform.accountable_owner_present(p.tenant_id, p.user_id)", "p.owner_user_id IS NOT NULL"
)

# R6.11: a service user is a company member of its own tenant only.
_GUARD_TENANT = """
    CREATE FUNCTION platform.guard_service_user_tenant() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM platform.users u
            WHERE u.id = NEW.user_id AND u.kind = 'service'
              AND u.owner_tenant_id IS DISTINCT FROM NEW.tenant_id
        ) THEN
            RAISE EXCEPTION 'a service user is a member of its own tenant only'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_tenant_members_service_own_tenant';
        END IF;
        RETURN NEW;
    END
    $$
"""

# ADR-0104 decision 6: the one owner of "critical role". tenant-rbac/03 and
# /04 read and extend this function, never a copy of it.
_ROLE_IS_CRITICAL = """
    CREATE FUNCTION platform.role_is_critical(p_tenant_id uuid, p_role_id uuid)
    RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM platform.tenant_roles r
            WHERE r.tenant_id = p_tenant_id AND r.id = p_role_id
              AND (r.key = 'tenant_owner' OR EXISTS (
                  SELECT 1 FROM platform.tenant_role_permissions p
                  JOIN platform.permissions k ON k.key = p.permission_key
                  WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id
                    AND k.risk = 'critical'))
        )
    $$
"""

# The service users a role is assigned to, whatever their status: the guard
# and the event read the same set.
_SERVICE_HOLDERS = """
    CREATE FUNCTION platform.service_holders_of_role(p_tenant_id uuid, p_role_id uuid)
    RETURNS SETOF uuid
    LANGUAGE sql STABLE
    AS $$
        SELECT DISTINCT m.user_id
        FROM platform.role_assignments a
        JOIN platform.memberships m ON m.id = a.membership_id
        JOIN platform.users u ON u.id = m.user_id AND u.kind = 'service'
        WHERE a.tenant_id = p_tenant_id AND a.role_id = p_role_id
    $$
"""

# R6.4: no critical role reaches a service user, by any writer. Each branch
# locks the role row before it reads (the row the confirm of tenant-rbac/03
# locks too), so an assignment and a critical key added to the same role in two
# transactions do not both pass; a human recipient takes no lock. The row is
# taken before the tenant's access-version row on every path: this trigger is
# BEFORE, and DW creation locks its roles first.
_GUARD_GRANTS = """
    CREATE FUNCTION platform.guard_service_principal_grants() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_refused boolean := false;
    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN
            IF EXISTS (
                SELECT 1 FROM platform.memberships m
                JOIN platform.users u ON u.id = m.user_id
                WHERE m.id = NEW.membership_id AND u.kind = 'service'
            ) THEN
                PERFORM 1 FROM platform.tenant_roles
                WHERE tenant_id = NEW.tenant_id AND id = NEW.role_id
                FOR NO KEY UPDATE;
                v_refused := platform.role_is_critical(NEW.tenant_id, NEW.role_id);
            END IF;
        ELSIF TG_TABLE_NAME = 'tenant_role_permissions' THEN
            -- The new row is not visible to `role_is_critical` before it is
            -- written: its own key is the part of the rule still to be judged.
            IF EXISTS (
                SELECT 1 FROM platform.permissions k
                WHERE k.key = NEW.permission_key AND k.risk = 'critical'
            ) THEN
                PERFORM 1 FROM platform.tenant_roles
                WHERE tenant_id = NEW.tenant_id AND id = NEW.role_id
                FOR NO KEY UPDATE;
                v_refused := EXISTS (
                    SELECT 1 FROM platform.service_holders_of_role(NEW.tenant_id, NEW.role_id)
                );
            END IF;
        ELSIF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN
            -- The UPDATE holds the role row already.
            v_refused := platform.role_is_critical(NEW.tenant_id, NEW.id)
                AND EXISTS (SELECT 1 FROM platform.service_holders_of_role(NEW.tenant_id, NEW.id));
        END IF;
        IF v_refused THEN
            RAISE EXCEPTION 'a service account holds no critical role'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_role_assignments_service_not_critical';
        END IF;
        RETURN NEW;
    END
    $$
"""

# R6.6: one outbox row per service account whose assigned grants grow. The
# cases below ARE the definition of "grow": a key already held through another
# role still announces, and the reader only sends the binding back to review.
_GRANTS_CHANGED = f"""
    CREATE FUNCTION platform.service_principal_grants_changed() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_role uuid;
        v_principals uuid[];
    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN
            IF TG_OP = 'UPDATE' AND NOT (
                NEW.role_id IS DISTINCT FROM OLD.role_id
                OR NEW.membership_id IS DISTINCT FROM OLD.membership_id
                OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
                OR (OLD.expires_at IS NOT NULL
                    AND (NEW.expires_at IS NULL OR NEW.expires_at > OLD.expires_at))
            ) THEN
                RETURN NULL;
            END IF;
            v_role := NEW.role_id;
            v_principals := ARRAY(
                SELECT m.user_id FROM platform.memberships m
                JOIN platform.users u ON u.id = m.user_id AND u.kind = 'service'
                WHERE m.id = NEW.membership_id
            );
            IF cardinality(v_principals) = 0 THEN
                RETURN NULL;
            END IF;
            PERFORM 1 FROM platform.tenant_roles
            WHERE tenant_id = NEW.tenant_id AND id = v_role FOR NO KEY UPDATE;
        ELSE
            IF TG_TABLE_NAME = 'tenant_role_permissions' THEN
                IF TG_OP = 'UPDATE' AND NOT (
                    NEW.permission_key IS DISTINCT FROM OLD.permission_key
                    OR NEW.role_id IS DISTINCT FROM OLD.role_id
                    OR array_position({_DEPTHS}, NEW.depth) > array_position({_DEPTHS}, OLD.depth)
                ) THEN
                    RETURN NULL;
                END IF;
                v_role := NEW.role_id;
                -- Before the holders are read: an assignment committed by a
                -- transaction this one waited for is seen, and one still to
                -- come waits for this one and announces itself.
                PERFORM 1 FROM platform.tenant_roles
                WHERE tenant_id = NEW.tenant_id AND id = v_role FOR NO KEY UPDATE;
            ELSE
                IF NOT (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL) THEN
                    RETURN NULL;
                END IF;
                v_role := NEW.id;
            END IF;
            v_principals := ARRAY(SELECT platform.service_holders_of_role(NEW.tenant_id, v_role));
        END IF;
        INSERT INTO platform.outbox_events (
            id, tenant_id, workspace_id, event_type, schema_version, aggregate_id,
            payload, occurred_at
        )
        SELECT gen_random_uuid(), p.tenant_id, p.owning_workspace_id,
               'platform.service_principal.grants_changed', '1', p.user_id,
               jsonb_build_object('tenant_id', p.tenant_id, 'service_principal_id', p.user_id),
               now()
        FROM platform.service_principals p
        WHERE p.tenant_id = NEW.tenant_id AND p.user_id = ANY (v_principals);
        RETURN NULL;
    END
    $$
"""

# Named to sort before `trg_z_bump_access_version` (and the `rbac_refusals_*`
# of tenant-rbac/03): the role row is taken before the access-version row.
_GRANT_TRIGGERS = (
    "CREATE TRIGGER guard_service_principal_grants"
    " BEFORE INSERT OR UPDATE ON platform.role_assignments"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_service_principal_grants()",
    "CREATE TRIGGER guard_service_principal_grants"
    " BEFORE INSERT OR UPDATE ON platform.tenant_role_permissions"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_service_principal_grants()",
    "CREATE TRIGGER guard_service_principal_grants"
    " BEFORE UPDATE OF deleted_at ON platform.tenant_roles"
    " FOR EACH ROW EXECUTE FUNCTION platform.guard_service_principal_grants()",
    "CREATE TRIGGER service_principal_grants_changed"
    " AFTER INSERT OR UPDATE ON platform.role_assignments"
    " FOR EACH ROW EXECUTE FUNCTION platform.service_principal_grants_changed()",
    "CREATE TRIGGER service_principal_grants_changed"
    " AFTER INSERT OR UPDATE ON platform.tenant_role_permissions"
    " FOR EACH ROW EXECUTE FUNCTION platform.service_principal_grants_changed()",
    "CREATE TRIGGER service_principal_grants_changed"
    " AFTER UPDATE OF deleted_at ON platform.tenant_roles"
    " FOR EACH ROW EXECUTE FUNCTION platform.service_principal_grants_changed()",
)
_GRANT_TRIGGER_TABLES = ("role_assignments", "tenant_role_permissions", "tenant_roles")

# One owner of the cover rule: the holder has the key at `tenant` depth, or at
# the same anchor with the same or a broader depth (b5677d345bc1's
# `grants_cover`, moved here unchanged). tenant-rbac/03 reads it per privilege.
_COVER = (
    f"""
    CREATE FUNCTION platform.holder_covers_grant(
        p_tenant_id uuid, p_holder_id uuid, p_permission_key text, p_depth text,
        p_anchor_workspace_id uuid
    )
    RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM platform.effective_grants(p_tenant_id, p_holder_id) h
            WHERE h.permission_key = p_permission_key
              AND (h.depth = 'tenant'
                   OR (h.anchor_workspace_id = p_anchor_workspace_id
                       AND array_position({_DEPTHS}, h.depth)
                           >= array_position({_DEPTHS}, p_depth)))
        )
    $$
    """,
    """
    CREATE FUNCTION platform.uncovered_grants(
        p_tenant_id uuid, p_holder_id uuid, p_subject_id uuid
    )
    RETURNS TABLE (permission_key text, depth text, anchor_workspace_id uuid)
    LANGUAGE sql STABLE
    AS $$
        SELECT DISTINCT s.permission_key, s.depth, s.anchor_workspace_id
        FROM platform.effective_grants(p_tenant_id, p_subject_id) s
        WHERE NOT platform.holder_covers_grant(
            p_tenant_id, p_holder_id, s.permission_key, s.depth, s.anchor_workspace_id
        )
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION platform.grants_cover(
        p_tenant_id uuid, p_holder_id uuid, p_subject_id uuid
    )
    RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
        SELECT NOT EXISTS (
            SELECT 1 FROM platform.uncovered_grants(p_tenant_id, p_holder_id, p_subject_id)
        )
    $$
    """,
)

_GRANTS_COVER_BEFORE = f"""
    CREATE OR REPLACE FUNCTION platform.grants_cover(
        p_tenant_id uuid, p_holder_id uuid, p_subject_id uuid
    )
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
                           AND array_position({_DEPTHS}, h.depth)
                               >= array_position({_DEPTHS}, s.depth)))
            )
        )
    $$
"""

# "Is this a Digital Worker's principal" in the bound tenant, whichever of its
# workspaces the DW sits in: a NOT EXISTS under the caller's RLS would miss a
# DW of another workspace. Answers a boolean only.
_IS_DW_PRINCIPAL = """
    CREATE FUNCTION platform.is_digital_worker_principal(p_user_id uuid) RETURNS boolean
    LANGUAGE sql STABLE
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM platform.digital_workers d
            WHERE d.principal_user_id = p_user_id
              AND d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    $$
"""

# R6.8, R6.9: the offboarding lane's step for the service users of the tenant
# it purges; `dw_app` holds no DELETE on `platform.users`.
_PURGE_SERVICE_USERS = """
    CREATE FUNCTION platform.purge_tenant_service_users(p_tenant uuid) RETURNS integer
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_removed integer;
    BEGIN
        IF p_tenant IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid THEN
            RAISE EXCEPTION 'purge_tenant_service_users runs for the transaction''s own tenant'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_users_service_purge';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants WHERE id = p_tenant AND status = 'offboarding'
        ) THEN
            RAISE EXCEPTION 'purge_tenant_service_users runs only for a tenant offboarding'
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_users_service_purge';
        END IF;
        DELETE FROM platform.users WHERE kind = 'service' AND owner_tenant_id = p_tenant;
        GET DIAGNOSTICS v_removed = ROW_COUNT;
        RETURN v_removed;
    END
    $$
"""

# (key, label_vi), both `workspace` keys of risk `elevated` (step 5).
_KEYS = (
    ("platform.service_principals.manage", "Quản lý tài khoản dịch vụ"),
    ("platform.service_principals.use", "Gắn tài khoản dịch vụ làm chủ thể chạy"),
)

_DEFINER_FUNCTIONS = (
    "platform.guard_service_user_tenant()",
    "platform.guard_service_principal_grants()",
    "platform.service_principal_grants_changed()",
    "platform.is_digital_worker_principal(uuid)",
    "platform.purge_tenant_service_users(uuid)",
)
_APP_FUNCTIONS = (
    "platform.is_digital_worker_principal(uuid)",
    "platform.purge_tenant_service_users(uuid)",
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


def _counted(title: str, statement: str) -> None:
    """Run a repair and print how many rows it touched, for the operators."""
    bind = op.get_bind()
    if bind is None:  # a recording stand-in for `op` (unit tests) has no connection
        op.execute(statement)
        return
    touched = bind.execute(sa.text(statement)).rowcount
    print(f"org-and-principals/03: {title}: {touched}")


def upgrade() -> None:
    # 1. What the new constraints would refuse: refused, renamed or emptied.
    op.execute(_NAMES_INVALID)
    _counted("service principals renamed after an earlier one of the same name", RENAME_DUPLICATES)
    _counted("service principals whose owner had no company row", CLEAR_OWNERS_WITHOUT_MEMBER)

    # 2. The table.
    for statement in _TABLE:
        op.execute(statement)

    # 3. Functions, then the triggers that judge writes.
    for statement in (
        _GUARD_OWNER,
        _OWNER_PRESENT,
        _SCOPES_DUE,
        _GUARD_TENANT,
        _ROLE_IS_CRITICAL,
        _SERVICE_HOLDERS,
        _GUARD_GRANTS,
        _GRANTS_CHANGED,
        *_COVER,
        _IS_DW_PRINCIPAL,
        _PURGE_SERVICE_USERS,
    ):
        op.execute(statement)
    op.execute(_CRITICAL_HELD)
    op.execute(
        "CREATE TRIGGER guard_service_user_tenant"
        " BEFORE INSERT OR UPDATE OF tenant_id, user_id ON platform.tenant_members"
        " FOR EACH ROW EXECUTE FUNCTION platform.guard_service_user_tenant()"
    )
    for statement in _GRANT_TRIGGERS:
        op.execute(statement)

    # 4. Privileges: no one calls a trigger function; `dw_app` the two it reads.
    for function in _DEFINER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    for function in _APP_FUNCTIONS:
        op.execute(_for_role("dw_app", f"GRANT EXECUTE ON FUNCTION {function} TO dw_app;"))

    # 5. The two keys.
    for key, label in _KEYS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'platform', :l, 'workspace', 'elevated', 'active', NULL,"
                " 'dw_platform', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label)
        )


def downgrade() -> None:
    for key, _ in _KEYS:
        op.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
            ).bindparams(k=key)
        )
        op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=key))
    for table in _GRANT_TRIGGER_TABLES:
        for trigger in ("guard_service_principal_grants", "service_principal_grants_changed"):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON platform.{table}")
    op.execute("DROP TRIGGER IF EXISTS guard_service_user_tenant ON platform.tenant_members")
    op.execute(_GRANTS_COVER_BEFORE)
    op.execute(_SCOPES_DUE_BEFORE)
    for function in (
        "platform.purge_tenant_service_users(uuid)",
        "platform.is_digital_worker_principal(uuid)",
        "platform.uncovered_grants(uuid, uuid, uuid)",
        "platform.holder_covers_grant(uuid, uuid, text, text, uuid)",
        "platform.service_principal_grants_changed()",
        "platform.guard_service_principal_grants()",
        "platform.service_holders_of_role(uuid, uuid)",
        "platform.role_is_critical(uuid, uuid)",
        "platform.guard_service_user_tenant()",
        "platform.accountable_owner_present(uuid, uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    # be93e0c26a4c's guard: an owner, when given, is a human member anywhere in the tenant.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform.guard_accountable_owner() RETURNS trigger
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
    op.execute("DROP INDEX IF EXISTS platform.ix_service_principals_tenant_id_owner_user_id")
    op.execute(
        "ALTER TABLE platform.service_principals"
        " DROP CONSTRAINT IF EXISTS fk_service_principals_tenant_id_tenant_members"
    )
    op.execute(
        "ALTER TABLE platform.service_principals"
        " ADD CONSTRAINT fk_service_principals_owner_user_id_users"
        " FOREIGN KEY (owner_user_id) REFERENCES platform.users (id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX ix_service_principals_owner_user_id"
        " ON platform.service_principals (owner_user_id)"
    )
    op.execute(
        "ALTER TABLE platform.service_principals"
        " DROP CONSTRAINT IF EXISTS uq_service_principals_tenant_id_name"
    )
    op.execute(
        "ALTER TABLE platform.service_principals"
        " DROP CONSTRAINT ck_service_principals_name,"
        " ADD CONSTRAINT ck_service_principals_name CHECK (char_length(name) BETWEEN 1 AND 120)"
    )
    op.execute("DROP TRIGGER IF EXISTS touch_updated_at ON platform.service_principals")
    op.execute("DROP INDEX IF EXISTS platform.ix_service_principals_created_by")
    op.execute(
        """
        ALTER TABLE platform.service_principals
            DROP CONSTRAINT IF EXISTS fk_service_principals_created_by_users,
            DROP CONSTRAINT IF EXISTS ck_service_principals_description,
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS created_by,
            DROP COLUMN IF EXISTS description
        """
    )
