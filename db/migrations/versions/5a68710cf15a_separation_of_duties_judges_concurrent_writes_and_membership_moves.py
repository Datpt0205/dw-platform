"""separation of duties takes the tenant's access version row before it reads,
and judges a membership's change of person

Revision ID: 5a68710cf15a
Revises: 8ae042d86742
Create Date: 2026-11-06 02:47:01.576408+00:00

tenant-rbac ticket 11 (R5.1, RB14; ADR-0104 decisions 7, 9). Two
transactions each giving one person one side of a rule were judged each
before the other committed, so both passed and the person held both sides:
the separation-of-duties trigger fires before `trg_z_bump_access_version`
(row triggers fire in name order), so the second writer waited on the access
version row only after it had judged.

- `platform.enforce_role_separation_of_duties()` (ticket 09's body, patched
  once) first takes the tenant's `platform.tenant_access_versions` row FOR NO
  KEY UPDATE, the mode the version bump at the end of the same statement takes
  anyway: no lock the transaction did not already take, only taken earlier, so
  a second writer waits here and then reads with a fresh snapshot. A missing
  row refuses (23514 `ck_roles_sod_access_version`, fail closed), except in a
  tenant offboarding or offboarded, where the purge removed it and a user's
  deletion still nulls `assigned_by`.
- A new `memberships` branch judges the person a membership is moved to
  (`trg_memberships_separation_of_duties`, AFTER UPDATE OF user_id, when the
  person changes; only `dw_migrator` may move one), in that tenant only, with
  no early return: moving a membership to someone already in breach is
  refused too.

`platform.owner_coverage_after_write()` is unchanged: the below-two race was
measured without a leak (db/bench/rbac/RESULTS.md, tenant-rbac/11).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "5a68710cf15a"
down_revision = "8ae042d86742"
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


_RESTORE_09 = _earlier(
    "8ae042d86742_separation_of_duties_on_restore_and_no_generated_keys_in_rules.py"
)


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/11: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


_SOD_BEFORE: str = _RESTORE_09._SOD

_SOD = _patched(
    _SOD_BEFORE,
    (
        """    BEGIN
        IF TG_TABLE_NAME = 'role_assignments' THEN""",
        """    BEGIN
        -- The row the version bump of this very statement locks anyway, taken
        -- before reading: a concurrent writer of the tenant waits here, then
        -- reads what the first one committed.
        PERFORM 1 FROM platform.tenant_access_versions v
        WHERE v.tenant_id = NEW.tenant_id
        FOR NO KEY UPDATE;
        IF NOT FOUND AND NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = NEW.tenant_id AND t.status IN ('offboarding', 'offboarded')
        ) THEN
            RAISE EXCEPTION 'tenant % has no access version to judge separation of duties under',
                NEW.tenant_id
                USING ERRCODE = 'check_violation',
                      CONSTRAINT = 'ck_roles_sod_access_version';
        END IF;
        IF TG_TABLE_NAME = 'role_assignments' THEN""",
    ),
    (
        """        ELSIF TG_TABLE_NAME = 'tenant_roles' THEN""",
        """        ELSIF TG_TABLE_NAME = 'memberships' THEN
            -- Every assignment of the membership moves to this person.
            v_people := ARRAY[NEW.user_id];
        ELSIF TG_TABLE_NAME = 'tenant_roles' THEN""",
    ),
)

_MEMBERSHIP_TRIGGER = (
    "CREATE TRIGGER trg_memberships_separation_of_duties"
    " AFTER UPDATE OF user_id ON platform.memberships FOR EACH ROW"
    " WHEN (NEW.user_id IS DISTINCT FROM OLD.user_id)"
    " EXECUTE FUNCTION platform.enforce_role_separation_of_duties()"
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    op.execute(_SOD)
    op.execute(_MEMBERSHIP_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_memberships_separation_of_duties ON platform.memberships")
    op.execute(_SOD_BEFORE)
