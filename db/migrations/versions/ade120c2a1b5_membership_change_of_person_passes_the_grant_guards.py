"""a membership's change of person passes the guards an assignment and a
revocation pass

Revision ID: ade120c2a1b5
Revises: 5a68710cf15a
Create Date: 2026-11-06 03:17:35.336624+00:00

tenant-rbac ticket 12 (R3.11, R3.12, R6.7; RB20, RB39, RB40, RB50). Moving a
membership to another person (`memberships.user_id`, `dw_migrator` only, RB50)
moves every assignment of it: a revocation from the old person plus an
assignment to the new one, judged here by the four rules that hold for every
writer, besides ticket 11's separation of duties.

- `platform.guard_operator_tenant_grants()` (R3.11): a `memberships` branch
  refuses moving owner authority to a platform operator or support staff
  member (the advisory lock per person, then the membership's role rows); the
  `role_assignments` branch reads the membership's person FOR KEY SHARE (the
  lock the assignment's foreign key takes later anyway, so an assignment beside
  an uncommitted move waits and reads the new person) and, for a listed
  person, locks the role row before it reads; an owner key added to a role
  locks the role row before it reads the holders; a person added to a list
  locks the role rows of all their assignments before it reads.
- `platform.guard_service_principal_grants()` (org-and-principals R6.4): a
  `memberships` branch refuses moving a critical role to a service account;
  the `role_assignments` branch reads the membership FOR KEY SHARE first.
- `platform.service_principal_grants_changed()` (R6.6): a move to a service
  account with any assignment announces it once.
- `platform.refuse_losing_the_last_owner()` (R6.7): a move of a membership
  carrying `tenant_owner` is judged as the old person's revocation.
- `trg_memberships_owner_coverage` (R3.12): ticket 08's deferred coverage
  check on a move.

One lock order for every path: the membership row, role rows, the advisory
lock, the tenant row, the access-version row. Each body is the latest one,
patched once per anchor; the way down restores those bodies and drops the five
triggers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "ade120c2a1b5"
down_revision = "5a68710cf15a"
branch_labels = None
depends_on = None


def _earlier(filename: str) -> ModuleType:
    """An earlier revision's module, for the function bodies this one patches
    (and restores on the way down) without a second copy of them."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(f"dw_rev_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ROLES_02 = _earlier("b5677d345bc1_tenant_roles.py")
_ROLES_03 = _earlier("d2b57239ef50_role_administration_and_anti_escalation.py")
_PRINCIPALS = _earlier("557e6907195e_service_principals_run_as.py")
_OBJECTS_04 = _earlier("ef68083f2905_object_and_field_privileges_in_roles.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/12: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


def _replace(body: str) -> str:
    return body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


# The role rows of the membership's own assignments, in one order.
_LOCK_MEMBERSHIP_ROLES = """PERFORM 1 FROM platform.tenant_roles r
                WHERE r.tenant_id = NEW.tenant_id AND r.id IN (
                    SELECT a.role_id FROM platform.role_assignments a
                    WHERE a.tenant_id = NEW.tenant_id AND a.membership_id = NEW.id
                )
                ORDER BY r.id
                FOR NO KEY UPDATE;"""

# -- R3.11 ---------------------------------------------------------------------------

(_OPERATOR_BEFORE,) = [s for s in _ROLES_02._SETUP if "guard_operator_tenant_grants()" in s]

_OPERATOR = _patched(
    _replace(_OPERATOR_BEFORE),
    (
        """INTO v_user FROM platform.memberships WHERE id = NEW.membership_id;
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
            );""",
        """INTO v_user FROM platform.memberships WHERE id = NEW.membership_id
            -- An uncommitted change of the membership's person holds its row:
            -- this assignment waits, then reads the new person.
            FOR KEY SHARE;
            PERFORM pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text));
            IF EXISTS (SELECT 1 FROM platform.platform_operators WHERE user_id = v_user)
               OR EXISTS (SELECT 1 FROM platform.support_staff WHERE user_id = v_user) THEN
                PERFORM 1 FROM platform.tenant_roles
                WHERE tenant_id = NEW.tenant_id AND id = NEW.role_id
                FOR NO KEY UPDATE;
                v_refused := EXISTS (
                    SELECT 1 FROM platform.tenant_roles r
                    WHERE r.tenant_id = NEW.tenant_id AND r.id = NEW.role_id
                      AND (r.key = 'tenant_owner' OR EXISTS (
                          SELECT 1 FROM platform.tenant_role_permissions p
                          WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id
                            AND p.permission_key = ANY (platform.owner_permission_keys())))
                );
            END IF;""",
    ),
    (
        """            v_refused := NEW.permission_key = ANY (platform.owner_permission_keys())
                AND EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    JOIN platform.memberships m ON m.id = a.membership_id
                    WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.role_id
                      AND (EXISTS (SELECT 1 FROM platform.platform_operators o
                                   WHERE o.user_id = m.user_id)
                           OR EXISTS (SELECT 1 FROM platform.support_staff s
                                      WHERE s.user_id = m.user_id))
                );""",
        """            IF NEW.permission_key = ANY (platform.owner_permission_keys()) THEN
                -- The role row, before the holders are read: an assignment or a
                -- listing that locks it waits, or is waited for.
                PERFORM 1 FROM platform.tenant_roles
                WHERE tenant_id = NEW.tenant_id AND id = NEW.role_id
                FOR NO KEY UPDATE;
                v_refused := EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    JOIN platform.memberships m ON m.id = a.membership_id
                    WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.role_id
                      AND (EXISTS (SELECT 1 FROM platform.platform_operators o
                                   WHERE o.user_id = m.user_id)
                           OR EXISTS (SELECT 1 FROM platform.support_staff s
                                      WHERE s.user_id = m.user_id))
                );
            END IF;
        ELSIF TG_TABLE_NAME = 'memberships' THEN
            -- A change of person: every assignment of this membership reaches
            -- the new person, judged as assignments to them.
            v_user := NEW.user_id;
            PERFORM pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text));
            IF EXISTS (SELECT 1 FROM platform.platform_operators WHERE user_id = v_user)
               OR EXISTS (SELECT 1 FROM platform.support_staff WHERE user_id = v_user) THEN
                @LOCK_MEMBERSHIP_ROLES@
                v_refused := EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
                    WHERE a.tenant_id = NEW.tenant_id AND a.membership_id = NEW.id
                      AND (r.key = 'tenant_owner' OR EXISTS (
                          SELECT 1 FROM platform.tenant_role_permissions p
                          WHERE p.tenant_id = r.tenant_id AND p.role_id = r.id
                            AND p.permission_key = ANY (platform.owner_permission_keys())))
                );
            END IF;""".replace("@LOCK_MEMBERSHIP_ROLES@", _LOCK_MEMBERSHIP_ROLES),
    ),
    (
        """            v_user := NEW.user_id;
            PERFORM pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text));
            v_refused := EXISTS (""",
        """            v_user := NEW.user_id;
            PERFORM pg_advisory_xact_lock(hashtext('operator_grants:' || v_user::text));
            -- The role rows of every assignment the person holds, before reading:
            -- an owner key added to one of them meanwhile waits, or is waited for.
            PERFORM 1 FROM platform.tenant_roles r
            WHERE (r.tenant_id, r.id) IN (
                SELECT a.tenant_id, a.role_id FROM platform.role_assignments a
                JOIN platform.memberships m ON m.id = a.membership_id
                WHERE m.user_id = v_user
            )
            ORDER BY r.id
            FOR NO KEY UPDATE;
            v_refused := EXISTS (""",
    ),
)

# -- org-and-principals R6.4, R6.6 --------------------------------------------------

_SERVICE_BEFORE = _replace(_OBJECTS_04._GUARD_GRANTS)

_SERVICE = _patched(
    _SERVICE_BEFORE,
    (
        """        IF TG_TABLE_NAME = 'role_assignments' THEN
            IF EXISTS (""",
        """        IF TG_TABLE_NAME = 'role_assignments' THEN
            -- An uncommitted change of the membership's person holds its row.
            PERFORM 1 FROM platform.memberships WHERE id = NEW.membership_id FOR KEY SHARE;
            IF EXISTS (""",
    ),
    (
        """        ELSIF TG_TABLE_NAME = 'field_permissions' THEN""",
        """        ELSIF TG_TABLE_NAME = 'memberships' THEN
            IF EXISTS (
                SELECT 1 FROM platform.users u WHERE u.id = NEW.user_id AND u.kind = 'service'
            ) THEN
                @LOCK_MEMBERSHIP_ROLES@
                v_refused := EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    WHERE a.tenant_id = NEW.tenant_id AND a.membership_id = NEW.id
                      AND platform.role_is_critical(NEW.tenant_id, a.role_id)
                );
            END IF;
        ELSIF TG_TABLE_NAME = 'field_permissions' THEN""".replace(
            "@LOCK_MEMBERSHIP_ROLES@", _LOCK_MEMBERSHIP_ROLES
        ),
    ),
)

_CHANGED_BEFORE = _replace(_PRINCIPALS._GRANTS_CHANGED)

# Any assignment, expired or of a deleted role included, as the assignment
# branch: an extra notice only sends the binding back to review.
_CHANGED = _patched(
    _CHANGED_BEFORE,
    (
        """    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN""",
        """    BEGIN
        IF TG_TABLE_NAME = 'memberships' THEN
            v_principals := ARRAY(
                SELECT u.id FROM platform.users u
                WHERE u.id = NEW.user_id AND u.kind = 'service'
                  AND EXISTS (
                      SELECT 1 FROM platform.role_assignments a
                      WHERE a.tenant_id = NEW.tenant_id AND a.membership_id = NEW.id
                  )
            );
            IF cardinality(v_principals) = 0 THEN
                RETURN NULL;
            END IF;
        ELSIF TG_TABLE_NAME = 'role_assignments' THEN""",
    ),
)

# -- R6.7 ----------------------------------------------------------------------------

_LAST_OWNER_BEFORE = _replace(_ROLES_03._LAST_OWNER)

_LAST_OWNER = _patched(
    _LAST_OWNER_BEFORE,
    (
        """        ELSE
            IF OLD.status <> 'active' OR NEW.status = 'active' THEN""",
        """        ELSIF TG_TABLE_NAME = 'memberships' THEN
            -- The old person loses every assignment of the membership.
            IF NOT EXISTS (
                SELECT 1 FROM platform.role_assignments a
                JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
                WHERE a.tenant_id = NEW.tenant_id AND a.membership_id = NEW.id
                  AND r.key = 'tenant_owner'
            ) THEN
                RETURN NULL;
            END IF;
            v_tenant := NEW.tenant_id;
            v_user := OLD.user_id;
        ELSE
            IF OLD.status <> 'active' OR NEW.status = 'active' THEN""",
    ),
)

# -- the five triggers ----------------------------------------------------------------

_MOVED = "WHEN (NEW.user_id IS DISTINCT FROM OLD.user_id)"

_TRIGGERS = (
    (
        "trg_memberships_owner_coverage",
        "CREATE CONSTRAINT TRIGGER trg_memberships_owner_coverage"
        " AFTER UPDATE OF user_id ON platform.memberships"
        f" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW {_MOVED}"
        " EXECUTE FUNCTION platform.owner_coverage_after_write()",
    ),
    (
        "guard_service_principal_grants",
        "CREATE TRIGGER guard_service_principal_grants"
        f" BEFORE UPDATE OF user_id ON platform.memberships FOR EACH ROW {_MOVED}"
        " EXECUTE FUNCTION platform.guard_service_principal_grants()",
    ),
    (
        "trg_memberships_operator_not_owner",
        "CREATE TRIGGER trg_memberships_operator_not_owner"
        f" BEFORE UPDATE OF user_id ON platform.memberships FOR EACH ROW {_MOVED}"
        " EXECUTE FUNCTION platform.guard_operator_tenant_grants()",
    ),
    (
        "ck_role_assignments_last_owner",
        "CREATE TRIGGER ck_role_assignments_last_owner"
        f" AFTER UPDATE OF user_id ON platform.memberships FOR EACH ROW {_MOVED}"
        " EXECUTE FUNCTION platform.refuse_losing_the_last_owner()",
    ),
    (
        "service_principal_grants_changed",
        "CREATE TRIGGER service_principal_grants_changed"
        f" AFTER UPDATE OF user_id ON platform.memberships FOR EACH ROW {_MOVED}"
        " EXECUTE FUNCTION platform.service_principal_grants_changed()",
    ),
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    for body in (_OPERATOR, _SERVICE, _CHANGED, _LAST_OWNER):
        op.execute(body)
    for _, statement in _TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    for name, _ in _TRIGGERS:
        op.execute(f"DROP TRIGGER {name} ON platform.memberships")
    for body in (_replace(_OPERATOR_BEFORE), _SERVICE_BEFORE, _CHANGED_BEFORE, _LAST_OWNER_BEFORE):
        op.execute(body)
