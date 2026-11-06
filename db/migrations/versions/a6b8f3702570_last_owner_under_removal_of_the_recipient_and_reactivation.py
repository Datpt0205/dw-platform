"""the last owner under a removal of the recipient and a reactivation

Revision ID: a6b8f3702570
Revises: 596062dfa2d0
Create Date: 2026-11-06 04:18:41.694255+00:00

tenant-rbac ticket 14 (R6.7, RB20; ADR-0104 decision 6, "cascades
included"). Two more ways a side read an old snapshot and returned early with
no lock, so both transactions passed and the tenant kept no active owner.

- (a) `platform.remove_owner_assignments_first()`: deleting P's company row
  beside a handover to P (`tenant_owner` given to P, the last other owner's
  removed) removed P's owner assignments by a snapshot that did not see the
  handover yet; the cascade to P's memberships then waited for it, but by then
  P's company row was gone in this very transaction and the assignment branch
  returned early. On a company row it now locks P's memberships FOR UPDATE, in
  id order, before its DELETE: the rows the cascade locks at the end of the
  same statement anyway, taken earlier, so every open handover (which holds
  FOR KEY SHARE on P's membership) is waited for and the DELETE reads after it.
- (b) `platform.refuse_losing_the_last_owner()` (ticket 13's body): removing
  the `tenant_owner` assignment of a person not yet active (suspended,
  invited) beside a transaction reactivating them and suspending the last
  active owner returned early. Such a holder, with a company row, now takes the
  tenant row FOR KEY SHARE and reads again, the membership's person included
  for an assignment (a move of the membership may be open beside it); an
  active holder goes straight to FOR UPDATE as before.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "a6b8f3702570"
down_revision = "596062dfa2d0"
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


_ROLES_03 = _earlier("d2b57239ef50_role_administration_and_anti_escalation.py")
_SUSPENSION_13 = _earlier("596062dfa2d0_a_suspension_waits_for_open_last_owner_checks.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/14: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


def _replace(body: str) -> str:
    return body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


# -- (a) a company row removed: its memberships first --------------------------------

_OWNERS_FIRST_BEFORE = _replace(_ROLES_03._OWNERS_FIRST)

_OWNERS_FIRST = _patched(
    _OWNERS_FIRST_BEFORE,
    (
        """    BEGIN
        DELETE FROM platform.role_assignments a""",
        """    BEGIN
        -- The rows the cascade locks at the end of this statement, taken now:
        -- an open handover to this person holds FOR KEY SHARE on one of them.
        IF TG_TABLE_NAME = 'tenant_members' THEN
            PERFORM 1 FROM platform.memberships m
            WHERE m.tenant_id = (v_old->>'tenant_id')::uuid
              AND m.user_id = (v_old->>'user_id')::uuid
            ORDER BY m.id
            FOR UPDATE;
        END IF;
        DELETE FROM platform.role_assignments a""",
    ),
)

# -- (b) a holder not yet active ------------------------------------------------------

_LAST_OWNER_BEFORE: str = _SUSPENSION_13._LAST_OWNER

# The common part's three early returns, as ticket 13 left them.
_ACTIVE_HOLDER = """SELECT 1 FROM platform.tenant_members tm
            WHERE tm.tenant_id = v_tenant AND tm.user_id = v_user
              AND (tm.status = 'active' OR TG_TABLE_NAME = 'tenant_members')"""
_RETURNS = f"""        IF v_user IS NULL OR NOT EXISTS (
            {_ACTIVE_HOLDER}
        ) OR NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('active', 'locked')
        ) THEN
            RETURN NULL;
        END IF;"""

# The assignment branch's read of the holder, used again after the lock.
_HOLDER_READ = """SELECT m.user_id INTO v_user FROM platform.memberships m
            WHERE m.tenant_id = OLD.tenant_id AND m.id = OLD.membership_id;"""
assert _LAST_OWNER_BEFORE.count(_HOLDER_READ) == 1, "tenant-rbac/14: the holder read moved"

_LAST_OWNER = _patched(
    _LAST_OWNER_BEFORE,
    (
        _RETURNS,
        f"""        IF v_user IS NULL OR NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('active', 'locked')
        ) THEN
            RETURN NULL;
        END IF;
        IF NOT EXISTS (
            {_ACTIVE_HOLDER}
        ) THEN
            -- No company row (removed in this transaction: (a) closes that
            -- way): as before.
            IF NOT EXISTS (
                SELECT 1 FROM platform.tenant_members tm
                WHERE tm.tenant_id = v_tenant AND tm.user_id = v_user
            ) THEN
                RETURN NULL;
            END IF;
            -- Not active yet: a transaction reactivating them and removing the
            -- last active owner holds the tenant row FOR UPDATE; wait, then
            -- read again, the membership's person included.
            PERFORM 1 FROM platform.tenants
            WHERE id = v_tenant AND status IN ('active', 'locked')
            FOR KEY SHARE;
            IF TG_TABLE_NAME = 'role_assignments' THEN
                {_HOLDER_READ}
            END IF;
            IF v_user IS NULL OR NOT EXISTS (
                {_ACTIVE_HOLDER}
            ) THEN
                RETURN NULL;
            END IF;
        END IF;""",
    ),
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    op.execute(_OWNERS_FIRST)
    op.execute(_LAST_OWNER)


def downgrade() -> None:
    op.execute(_LAST_OWNER_BEFORE)
    op.execute(_OWNERS_FIRST_BEFORE)
