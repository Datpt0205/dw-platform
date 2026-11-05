"""`SqlActorBoundaries`: `ActorBoundaryPort` over `studio.record_actor_boundary`
(record-access ticket 04, step 2; revision 996c234cfde3).

`dw_app` writes no boundary row itself (gate (i)): the SECURITY DEFINER
function takes the company from `app.tenant_id`, checks the version, turns each
`api_name` into its id and writes the boundary with its object and field rows
in one call, so a published boundary is complete when its transaction commits
and nothing widens it afterwards. Its refusals reach the caller as the database
raised them and roll the caller's transaction back: a failed publish or run
door is a bug to see, not a condition to translate.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from dw_studio.core.application.boundaries import (
    BoundaryKind,
    FieldBoundary,
    ObjectBoundary,
)

_RECORD = text(
    "SELECT studio.record_actor_boundary(:kind, :source, :version, :run,"
    " CAST(:objects AS jsonb), CAST(:fields AS jsonb))"
)


def _objects(objects: Sequence[ObjectBoundary]) -> str:
    return json.dumps(
        [
            {
                "api_name": o.api_name,
                "can_read": o.can_read,
                "can_create": o.can_create,
                "can_update": o.can_update,
                "can_delete": o.can_delete,
                "can_assign": o.can_assign,
            }
            for o in objects
        ]
    )


def _fields(fields: Sequence[FieldBoundary]) -> str:
    return json.dumps(
        [
            {
                "object_api_name": f.object_api_name,
                "field_api_name": f.field_api_name,
                "access": f.access,
            }
            for f in fields
        ]
    )


class SqlActorBoundaries:
    """Stateless: every call runs on the session its caller hands in."""

    async def record(
        self,
        session: Any,
        kind: BoundaryKind,
        version_id: uuid.UUID,
        definition_hash: str,
        objects: Sequence[ObjectBoundary],
        fields: Sequence[FieldBoundary],
    ) -> uuid.UUID:
        return await self._write(session, kind, None, version_id, definition_hash, objects, fields)

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
        return await self._write(session, kind, run_id, version_id, pinned_hash, objects, fields)

    async def _write(
        self,
        session: Any,
        kind: BoundaryKind,
        run_id: uuid.UUID | None,
        version_id: uuid.UUID,
        source_version: str,
        objects: Sequence[ObjectBoundary],
        fields: Sequence[FieldBoundary],
    ) -> uuid.UUID:
        boundary = await session.scalar(
            _RECORD,
            {
                "kind": kind,
                "source": version_id,
                "version": source_version,
                "run": run_id,
                "objects": _objects(objects),
                "fields": _fields(fields),
            },
        )
        return uuid.UUID(str(boundary))
