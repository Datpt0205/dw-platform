"""a `setup` tenant opens only after an owner loss beside it commits

Revision ID: cae9cc86159c
Revises: a6b8f3702570
Create Date: 2026-11-06 04:34:25.101327+00:00

tenant-rbac ticket 15 (R3.10, R6.7; RB20, RB38). In a `setup` tenant
`platform.refuse_losing_the_last_owner()` returned before locking anything,
and the conditional FOR KEY SHARE of tickets 13 and 14 was taken in `active`
and `locked` tenants only, so an activation counted an owner that an
uncommitted suspension or removal was about to lose and opened the tenant
with one owner (or none, with three sides).

- `platform.refuse_losing_the_last_owner()` (ticket 14's body): the two
  conditional FOR KEY SHARE (V1 of ticket 13, V2 of ticket 14) and the common
  part's first early return (V3) now include `setup`, so every owner loss in a
  `setup` tenant holds the tenant row (FOR UPDATE, or FOR KEY SHARE for a
  person not yet an owner or not yet active) until it commits, which an
  activation's lock waits for. After the common FOR UPDATE the tenant's status
  is read again: a loss that waited for an activation is counted under R6.7
  in the tenant now `active`; one in a tenant still `setup` is not counted
  (R3.10 judges at activation; a `setup` tenant may lose its last owner).
- `platform.guard_tenant_setup()`: the `setup` to `active` UPDATE takes its
  own row FOR UPDATE (it holds FOR NO KEY UPDATE already) before it counts, so
  the second way to open conflicts with FOR KEY SHARE as
  `complete_tenant_setup` does.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "cae9cc86159c"
down_revision = "a6b8f3702570"
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
_REMOVAL_14 = _earlier("a6b8f3702570_last_owner_under_removal_of_the_recipient_and_reactivation.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/15: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


def _replace(body: str) -> str:
    return body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


# -- the owner losses ------------------------------------------------------------------

_LAST_OWNER_BEFORE: str = _REMOVAL_14._LAST_OWNER

_LAST_OWNER = _patched(
    _LAST_OWNER_BEFORE,
    # V1, ticket 13: a person not yet an owner.
    (
        """                -- UPDATE until it commits: wait for it, then read again.
                PERFORM 1 FROM platform.tenants
                WHERE id = v_tenant AND status IN ('active', 'locked')""",
        """                -- UPDATE until it commits: wait for it, then read again.
                PERFORM 1 FROM platform.tenants
                WHERE id = v_tenant AND status IN ('setup', 'active', 'locked')""",
    ),
    # V2, ticket 14: a holder not yet active.
    (
        """            -- read again, the membership's person included.
            PERFORM 1 FROM platform.tenants
            WHERE id = v_tenant AND status IN ('active', 'locked')""",
        """            -- read again, the membership's person included.
            PERFORM 1 FROM platform.tenants
            WHERE id = v_tenant AND status IN ('setup', 'active', 'locked')""",
    ),
    # V3: the common part's first early return, then the read after the lock.
    (
        """        IF v_user IS NULL OR NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('active', 'locked')""",
        """        IF v_user IS NULL OR NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('setup', 'active', 'locked')""",
    ),
    (
        """        PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;
""",
        """        PERFORM 1 FROM platform.tenants WHERE id = v_tenant FOR UPDATE;
        -- Read after the lock: a loss that waited for an activation is judged
        -- in the tenant now `active`; a `setup` tenant may lose its last owner.
        IF NOT EXISTS (
            SELECT 1 FROM platform.tenants t
            WHERE t.id = v_tenant AND t.status IN ('active', 'locked')
        ) THEN
            RETURN NULL;
        END IF;
""",
    ),
)

# -- the second way to open --------------------------------------------------------------

(_GUARD_SETUP_RAW,) = [s for s in _ROLES_02._SETUP if "guard_tenant_setup()" in s]
_GUARD_SETUP_BEFORE = _replace(_GUARD_SETUP_RAW)

_GUARD_SETUP = _patched(
    _GUARD_SETUP_BEFORE,
    (
        """        IF NEW.status IS DISTINCT FROM OLD.status THEN
""",
        """        IF NEW.status IS DISTINCT FROM OLD.status THEN
            -- FOR UPDATE, as `complete_tenant_setup` takes: an owner loss in
            -- this `setup` tenant holding FOR KEY SHARE is waited for.
            IF OLD.status = 'setup' AND NEW.status = 'active' THEN
                PERFORM 1 FROM platform.tenants WHERE id = NEW.id FOR UPDATE;
            END IF;
""",
    ),
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    op.execute(_LAST_OWNER)
    op.execute(_GUARD_SETUP)


def downgrade() -> None:
    op.execute(_GUARD_SETUP_BEFORE)
    op.execute(_LAST_OWNER_BEFORE)
