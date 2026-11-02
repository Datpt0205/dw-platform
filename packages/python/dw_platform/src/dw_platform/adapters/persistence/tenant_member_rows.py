"""The company member row every membership hangs from (org-and-principals R4.1).

Each path that writes ``platform.memberships`` first runs this statement in the
same transaction, so ``fk_memberships_tenant_members`` always finds its row. A
row already there keeps its status, ``suspended`` included: reopening a person
takes two people (D11), never a second invitation or grant. A person written
``invited`` becomes ``active`` at their next sign-in, through
``platform.activate_invited_members`` (``identity_provisioning.py``).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dw_platform.adapters.persistence import tables

NewMemberStatus = Literal["invited", "active"]


def ensure_tenant_member(tenant_id: UUID, user_id: UUID, status: NewMemberStatus) -> Insert:
    """Insert the person's company row with ``status`` unless one exists."""
    return (
        pg_insert(tables.tenant_members)
        .values(tenant_id=tenant_id, user_id=user_id, status=status)
        .on_conflict_do_nothing(index_elements=["tenant_id", "user_id"])
    )
