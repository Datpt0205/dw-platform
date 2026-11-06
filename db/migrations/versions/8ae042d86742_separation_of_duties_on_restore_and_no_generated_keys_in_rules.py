"""separation of duties on a role's restore, and no rule names a generated key

Revision ID: 8ae042d86742
Revises: a7ca12c36ec7
Create Date: 2026-11-06 02:19:52.145740+00:00

tenant-rbac ticket 09 (R5.1, RB14; ADR-0104 decision 9). No change may leave a
holder in breach of a rule without a confirmed open waiver; two ways around the
two separation-of-duties triggers are closed.

- Restoring a soft-deleted role (`tenant_roles.deleted_at` back to NULL) hands
  its keys back to every holder at once, and `platform.assigned_grants` did not
  count them while it was deleted, so a holder could take the other side of a
  rule meanwhile. `trg_tenant_roles_separation_of_duties`, AFTER UPDATE OF
  `deleted_at` FOR EACH ROW, on a restore only, runs
  `platform.enforce_role_separation_of_duties()`, which gains a `tenant_roles`
  branch: the people are everyone with an assignment of the role (expired ones
  included, as for a role's privilege), with no early return of ticket 08 (a
  restore hands back every key of the role), judged in `NEW.tenant_id` only.
  Same refusal, constraint, hint and detail as R5.1, for every writer,
  `dw_migrator` included. A soft delete only narrows and is not judged.
- `ck_sod_rules_no_generated_keys`: no element of `left_scopes` or
  `right_scopes` starts with `obj.` or `fld.` (ADR-0104 decision 4). Generated
  keys come from `platform.tenant_role_object_privileges` and
  `studio.field_permissions`, which carry no separation-of-duties trigger, so a
  rule naming one would be enforced by nothing. The revision stops, naming the
  rules, if one already does.

The function body is ticket 08's (a7ca12c36ec7), patched once; the way down
restores exactly that body and drops what this adds.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "8ae042d86742"
down_revision = "a7ca12c36ec7"
branch_labels = None
depends_on = None


def _earlier(filename: str) -> ModuleType:
    """An earlier revision's module, for the function body this one patches
    (and restores on the way down) without a second copy of it."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(f"dw_rev_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TRIGGERS_08 = _earlier("a7ca12c36ec7_owner_coverage_per_transaction_and_hold_rule_per_anchor.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/09: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


# -- 1. a restore passes the separation-of-duties function -----------------------

_SOD_BEFORE: str = _TRIGGERS_08._SOD

# The branch reads only columns `tenant_roles` has: plpgsql resolves `NEW.x`
# when the line runs, so the other branches' `NEW.role_id` never runs here.
_SOD = _patched(
    _SOD_BEFORE,
    (
        """        ELSE
            v_people := ARRAY(""",
        """        ELSIF TG_TABLE_NAME = 'tenant_roles' THEN
            -- A restore hands back every key of the role: no early return.
            v_people := ARRAY(
                SELECT DISTINCT m.user_id
                FROM platform.role_assignments a
                JOIN platform.memberships m ON m.id = a.membership_id
                WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.id
            );
        ELSE
            v_people := ARRAY(""",
    ),
)

_RESTORE_TRIGGER = (
    "CREATE TRIGGER trg_tenant_roles_separation_of_duties"
    " AFTER UPDATE OF deleted_at ON platform.tenant_roles FOR EACH ROW"
    " WHEN (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL)"
    " EXECUTE FUNCTION platform.enforce_role_separation_of_duties()"
)

# -- 2. no rule names a generated key ---------------------------------------------

_GENERATED = """'$[*] ? (@ starts with "obj." || @ starts with "fld.")'"""

_PRECHECK = f"""
    DO $$
    DECLARE
        v_rules text;
    BEGIN
        SELECT string_agg(key, ', ' ORDER BY key) INTO v_rules
        FROM platform.sod_rules
        WHERE left_scopes @? {_GENERATED} OR right_scopes @? {_GENERATED};
        IF v_rules IS NOT NULL THEN
            RAISE EXCEPTION 'separation-of-duties rules name a generated obj./fld. key: %',
                v_rules;
        END IF;
    END
    $$
"""

_NO_GENERATED_KEYS = (
    "ALTER TABLE platform.sod_rules ADD CONSTRAINT ck_sod_rules_no_generated_keys CHECK ("
    f"NOT (left_scopes @? {_GENERATED}) AND NOT (right_scopes @? {_GENERATED}))"
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    op.execute(_SOD)
    op.execute(_RESTORE_TRIGGER)
    op.execute(_PRECHECK)
    op.execute(_NO_GENERATED_KEYS)


def downgrade() -> None:
    op.execute("ALTER TABLE platform.sod_rules DROP CONSTRAINT ck_sod_rules_no_generated_keys")
    op.execute("DROP TRIGGER trg_tenant_roles_separation_of_duties ON platform.tenant_roles")
    op.execute(_SOD_BEFORE)
