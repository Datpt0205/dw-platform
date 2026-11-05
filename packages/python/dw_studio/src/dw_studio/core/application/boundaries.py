"""`ActorBoundaryPort`: where a version's data boundary, or a `simulate` run's
provisional one, is recorded (record-access ticket 04, step 2; ADR-0103
decision 5, ADR-0105 decision 6, ADR-0109 decision 6).

Declared once, here in Studio's core, because every caller is somewhere a
capability cannot import another: the `agent` kind's publish hook
(agent-builder/05), the `workflow` kind's (workflow-engine/03) and
`RunRequestService` (workflow-engine/03, R3.13 and R3.15). The two value types
are exactly what their derivations return, by `api_name`, never a second
shape (gate (c)).

Both methods run on the caller's open transaction, the session handed in
first, so a boundary is written in the transaction that publishes the version
or accepts the run, and rolls back with it. There is no delete: a provisional
boundary goes with its run (workflow-engine R3.14), a published one only with
its company (R6.8, R6.10).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

BoundaryKind = Literal["agent", "workflow"]
FieldAccess = Literal["read", "edit"]


@dataclass(frozen=True, slots=True)
class ObjectBoundary:
    """What the boundary lets the run do with one object's records."""

    api_name: str
    can_read: bool
    can_create: bool
    can_update: bool
    can_delete: bool
    can_assign: bool


@dataclass(frozen=True, slots=True)
class FieldBoundary:
    """One field the boundary lets the run read, or edit; field security reads it."""

    object_api_name: str
    field_api_name: str
    access: FieldAccess


class ActorBoundaryPort(Protocol):
    async def record(
        self,
        session: Any,
        kind: BoundaryKind,
        version_id: uuid.UUID,
        definition_hash: str,
        objects: Sequence[ObjectBoundary],
        fields: Sequence[FieldBoundary],
    ) -> uuid.UUID:
        """The one boundary of a published version (R6.7), in the publish
        transaction: ``version_id`` is a version of the session's company
        sealed under ``definition_hash``. An `api_name` the company has not
        applied, or a second boundary for the same version and hash, is a
        database error that rolls the publish back. Returns the boundary id."""
        ...

    async def record_provisional(
        self,
        session: Any,
        kind: BoundaryKind,
        run_id: uuid.UUID,
        version_id: uuid.UUID,
        pinned_hash: str,
        objects: Sequence[ObjectBoundary],
        fields: Sequence[FieldBoundary],
    ) -> uuid.UUID:
        """The provisional boundary of one `simulate` run whose root is not
        live (a draft under its pinned hash, a sealed candidate under its
        definition hash; R6.11), in the transaction that accepts the run,
        after its `platform.worker_runs` row. An object or field the draft has
        not applied yet is left out, so the run reads none of it. A run that
        is not `simulate` or not the company's, or a second boundary for it,
        is a database error. Returns the boundary id."""
        ...
