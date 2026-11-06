"""a suspension waits for every open last-owner check, then reads again

Revision ID: 596062dfa2d0
Revises: ade120c2a1b5
Create Date: 2026-11-06 04:08:33.176797+00:00

tenant-rbac ticket 13 (R6.7, RB20). Suspending a person P who is not an owner
in its snapshot returned early without a lock, while another transaction made
P an owner and removed the last other one, counting P still active: both
passed and the tenant kept no active owner. The two ways in are a membership
moved to P (ticket 12) and an ownership handed over in one transaction
(ticket 03).

`platform.refuse_losing_the_last_owner()` (ticket 12's body, patched once): in
the `tenant_members` branch, a person who holds no `tenant_owner` assignment
in the first read takes the tenant row FOR KEY SHARE (only in a tenant
`active` or `locked`, the only ones the rule judges) and reads again. Every
write about to make P an owner and remove another holds the tenant row FOR
UPDATE until it commits, which FOR KEY SHARE waits for; the second read, a
fresh snapshot under READ COMMITTED, then sees P as an owner, and the common
part counts and refuses. FOR KEY SHARE, not a stronger mode: it does not
conflict with the FOR NO KEY UPDATE of ticket 08's deferred coverage check,
with a foreign key to the tenant, or with another suspension. A person who is
an owner already goes straight to the common FOR UPDATE, as before, so two
suspensions of the last two owners still queue rather than deadlock.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "596062dfa2d0"
down_revision = "ade120c2a1b5"
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


_MOVES_12 = _earlier("ade120c2a1b5_membership_change_of_person_passes_the_grant_guards.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/13: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


_LAST_OWNER_BEFORE: str = _MOVES_12._LAST_OWNER

# The `tenant_members` branch's question, read once and used twice.
_OWNS = """(
                SELECT 1 FROM platform.role_assignments a
                JOIN platform.memberships m ON m.tenant_id = a.tenant_id AND m.id = a.membership_id
                JOIN platform.tenant_roles r ON r.tenant_id = a.tenant_id AND r.id = a.role_id
                WHERE a.tenant_id = v_tenant AND m.user_id = v_user AND r.key = 'tenant_owner'
            )"""

_LAST_OWNER = _patched(
    _LAST_OWNER_BEFORE,
    (
        f"""            IF NOT EXISTS {_OWNS} THEN
                RETURN NULL;
            END IF;""",
        f"""            IF NOT EXISTS {_OWNS} THEN
                -- A write making this person an owner holds the tenant row FOR
                -- UPDATE until it commits: wait for it, then read again.
                PERFORM 1 FROM platform.tenants
                WHERE id = v_tenant AND status IN ('active', 'locked')
                FOR KEY SHARE;
                IF NOT EXISTS {_OWNS} THEN
                    RETURN NULL;
                END IF;
            END IF;""",
    ),
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    op.execute(_LAST_OWNER)


def downgrade() -> None:
    op.execute(_LAST_OWNER_BEFORE)
