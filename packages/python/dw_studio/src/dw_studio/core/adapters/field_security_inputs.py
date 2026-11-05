"""`SqlFieldSecurityInputs`: `FieldSecurityInputsPort` over the caller's
session (field-security ticket 01, step 3).

Every read runs in the session handed in, as `dw_app` under the record and
tenant policies of the company that session is bound to: the company is
`app.tenant_id`, never an argument, so a person who belongs to two companies
is read in the bound one only (R2.10). Raw SQL, because the core describes no
capability's tables.

The principal of every actor kind is `app.user_id`: for `agent` and
`workflow` it is the run's `coalesce(run_as_principal_id, requested_by)`,
which `bind_actor` refuses to bind otherwise (record-access/04), so this
module reads no run row and checks nothing `bind_actor` already holds.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import text

from dw_kernel.errors import NotFoundError
from dw_kernel.personal_data import PdCategory
from dw_studio.core.application.field_access import (
    ActorKind,
    ActorUnboundError,
    BoundActor,
    PrincipalGrants,
)
from dw_studio.core.domain.field_access import (
    BoundaryLevel,
    BoundaryLink,
    FieldSecurity,
    ObjectSecurity,
)

_ACTOR_KINDS: Final[frozenset[str]] = frozenset({"user", "agent", "workflow"})
_UUID: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_BOUNDARY_LIST: Final = re.compile(rf"^(?:{_UUID}(?:,{_UUID})*)?$", re.IGNORECASE)

_SETTINGS = text(
    "SELECT current_setting('app.actor_kind', true) AS kind,"
    " NULLIF(current_setting('app.user_id', true), '') AS user_id,"
    " coalesce(current_setting('app.boundary_id', true), '') AS boundary"
)

# The live fields of the object, `owner` and `workspace` aside (system columns
# every reader of the record sees, ADR-0105).
_OBJECT = text(
    "SELECT o.api_name AS object_name, o.schema_version, f.id, f.api_name, f.access_mode,"
    " f.pd_category, f.is_unique"
    " FROM studio.object_defs o"
    " LEFT JOIN studio.field_defs f ON f.tenant_id = o.tenant_id AND f.object_id = o.id"
    "  AND f.api_name NOT IN ('owner', 'workspace')"
    " WHERE o.id = :o"
    " ORDER BY f.api_name"
)

# Every key, every anchor and depth, of the bound company only.
_PRINCIPAL = text(
    "SELECT ARRAY(SELECT DISTINCT g.permission_key FROM platform.effective_grants("
    "  NULLIF(current_setting('app.tenant_id', true), '')::uuid, :u) g) AS keys,"
    " coalesce((SELECT u.kind = 'service' FROM platform.users u WHERE u.id = :u), true)"
    " AS service_account,"
    " NULLIF(current_setting('app.tenant_id', true), '') IS NULL AS unbound"
)

_BOUNDARY = text(
    "SELECT b.boundary_id, b.field_id, b.access FROM studio.actor_boundary_fields b"
    " JOIN studio.field_defs f ON f.tenant_id = b.tenant_id AND f.id = b.field_id"
    " WHERE b.boundary_id = ANY(:b) AND f.object_id = :o"
)


class SqlFieldSecurityInputs:
    """Stateless: every call runs on the session its caller hands in."""

    async def actor(self, tx: Any) -> BoundActor:
        row = (await tx.execute(_SETTINGS)).one()
        if row.kind not in _ACTOR_KINDS:
            raise ActorUnboundError("the transaction has no actor kind")
        if row.user_id is None:
            raise ActorUnboundError("the transaction has no principal")
        if not _BOUNDARY_LIST.fullmatch(row.boundary):
            raise ActorUnboundError("the transaction's boundary list is not readable")
        kind: ActorKind = row.kind
        boundary = tuple(uuid.UUID(part) for part in row.boundary.split(",") if part)
        if kind == "user" and boundary:
            raise ActorUnboundError("a user's transaction carries a boundary")
        return BoundActor(kind, uuid.UUID(row.user_id), boundary)

    async def object_security(self, tx: Any, object_id: uuid.UUID) -> ObjectSecurity:
        rows = (await tx.execute(_OBJECT, {"o": object_id})).all()
        if not rows:
            raise NotFoundError("object not found")
        return ObjectSecurity(
            api_name=rows[0].object_name,
            schema_version=int(rows[0].schema_version),
            fields=tuple(
                FieldSecurity(
                    field_id=r.id,
                    api_name=r.api_name,
                    access_mode="open" if r.access_mode == "open" else "secured",
                    pd_category=PdCategory(r.pd_category),
                    is_unique=bool(r.is_unique),
                )
                for r in rows
                if r.id is not None
            ),
        )

    async def principal(self, tx: Any, principal_id: uuid.UUID) -> PrincipalGrants:
        row = (await tx.execute(_PRINCIPAL, {"u": principal_id})).one()
        if row.unbound:
            raise ActorUnboundError("the transaction is bound to no company")
        return PrincipalGrants(frozenset(row.keys), bool(row.service_account))

    async def boundary(
        self, tx: Any, boundary_ids: Sequence[uuid.UUID], object_id: uuid.UUID
    ) -> tuple[BoundaryLink, ...]:
        links: dict[uuid.UUID, dict[uuid.UUID, BoundaryLevel]] = {b: {} for b in boundary_ids}
        if boundary_ids:
            rows = await tx.execute(_BOUNDARY, {"b": list(boundary_ids), "o": object_id})
            for r in rows:
                links[r.boundary_id][r.field_id] = "edit" if r.access == "edit" else "read"
        return tuple(links[b] for b in boundary_ids)
