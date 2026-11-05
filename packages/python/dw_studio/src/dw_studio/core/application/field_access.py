"""`FieldAccessService`: the one place that reads what `resolve_field_access`
decides from, in the caller's own transaction (field-security ticket 01,
step 3; R2.8-R2.10).

Every path that emits a record value asks this service, never the function's
inputs itself: custom-objects/03 (the records adapter and describe),
tools-and-skills/03 (object tools), workflow-nodes/03 and /06 (templates and
approvals) and telemetry-and-audit/03 (run history).

Nothing here caches. A `FieldAccess` lives as long as the transaction it was
read in, so a field secured or a grant revoked after a run began is in force
from the run's next call (R2.9), and the first statement of a request after a
publish reads the new `access_mode` (R1.6). The principal's keys come from
`platform.effective_grants` in that transaction, every assignment at every
anchor and depth together, never from the acting workspace's projection or an
access context's cache: which records the principal reaches is the record
policies' question, not this one (R2.4).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from dw_studio.core.domain.field_access import (
    BoundaryLink,
    FieldAccess,
    FieldAction,
    ObjectSecurity,
    resolve_field_access,
)

ActorKind = Literal["user", "agent", "workflow"]


class ActorUnboundError(Exception):
    """The transaction carries no actor this service can decide for: no
    `app.actor_kind`, no principal, or a boundary list it cannot read. The
    caller refuses; the run is never read as a `user`."""


@dataclass(frozen=True, slots=True)
class BoundActor:
    """Who the transaction acts as, as `bind_actor` bound it.

    ``boundary_ids`` is `app.boundary_id`, the run's `studio.boundary_chain`
    root first; empty for `user` and for a run whose chain is empty."""

    kind: ActorKind
    principal_id: uuid.UUID
    boundary_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class PrincipalGrants:
    """What one principal holds in the bound company."""

    keys: frozenset[str]
    service_account: bool


class FieldSecurityInputsPort(Protocol):
    """The inputs of `resolve_field_access`, each read in the session the
    caller hands in, under the company that session is bound to."""

    async def actor(self, tx: Any) -> BoundActor:
        """`app.actor_kind`, `app.user_id` and `app.boundary_id` of the open
        transaction; `ActorUnboundError` when any is missing or unreadable."""
        ...

    async def object_security(self, tx: Any, object_id: uuid.UUID) -> ObjectSecurity:
        """The object's live definition rows; `NotFoundError` when the bound
        company has no such object."""
        ...

    async def principal(self, tx: Any, principal_id: uuid.UUID) -> PrincipalGrants:
        """The keys `platform.effective_grants` gives ``principal_id`` in the
        bound company, every anchor and depth together, and whether it is a
        service account (True when that cannot be read)."""
        ...

    async def boundary(
        self, tx: Any, boundary_ids: Sequence[uuid.UUID], object_id: uuid.UUID
    ) -> tuple[BoundaryLink, ...]:
        """One mapping per boundary, in order: the object's fields that
        boundary lists, to its `read` or `edit`. A boundary the bound company
        does not hold is an empty mapping."""
        ...


class FieldAccessService:
    def __init__(self, inputs: FieldSecurityInputsPort) -> None:
        self.inputs = inputs

    async def for_object(
        self, tx: Any, object_id: uuid.UUID, action: FieldAction = "update"
    ) -> FieldAccess:
        """The transaction's own actor on ``object_id``: the person of a `user`
        request, or the principal of an `agent` or `workflow` run within every
        boundary of its chain."""
        actor = await self.inputs.actor(tx)
        security = await self.inputs.object_security(tx, object_id)
        principal = await self.inputs.principal(tx, actor.principal_id)
        boundary = None
        if actor.kind != "user":
            boundary = await self.inputs.boundary(tx, actor.boundary_ids, object_id)
        return resolve_field_access(
            principal.keys,
            security,
            boundary,
            action,
            service_account=principal.service_account,
        )

    async def for_person(self, tx: Any, user_id: uuid.UUID, object_id: uuid.UUID) -> FieldAccess:
        """What ``user_id``, someone other than the caller (an approver
        candidate, a viewer of run history), reads of ``object_id`` in the
        bound company: their own grants, no boundary."""
        security = await self.inputs.object_security(tx, object_id)
        principal = await self.inputs.principal(tx, user_id)
        return resolve_field_access(
            principal.keys, security, None, "read", service_account=principal.service_account
        )
