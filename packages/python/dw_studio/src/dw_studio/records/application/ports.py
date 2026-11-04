"""What the object kind asks of storage (custom-objects ticket 02).

Two ports, each the narrowest its consumer calls:

- `ObjectDefinitionStore`: the publish hook's reads and writes, inside the
  transaction of the `ArtifactTx` the hook is handed. The composition root
  makes one from that transaction (`Callable[[ArtifactTx], ObjectDefinitionStore]`),
  so the hook's writes commit or roll back with the publish.
- `ObjectDefinitionReader`: the schema projector's one read, under the tenant
  the caller's access context or run names, never the request.

The store decides nothing: the hook decides, the database refuses (CHECKs,
the slot UNIQUE, the composite keys).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from dw_platform.application.access_context import AccessContext
from dw_studio.records.domain.document import DocumentDefinition, FieldDefinition, OptionDefinition


@dataclass(frozen=True, slots=True)
class ObjectVersion:
    """A version of an `object` artifact, as the hook reads it."""

    artifact_id: uuid.UUID
    version_no: int | None
    document: Any


@dataclass(frozen=True, slots=True)
class FieldStorage:
    """Where one field of an object lives: a system column, a slot or `data`."""

    field_id: uuid.UUID
    storage_kind: str
    slot: str | None
    field_no: int | None


@dataclass(frozen=True, slots=True)
class AppliedObject:
    """An object's definition as stored: the version it was applied from, what
    that document decided (`definition`, in `definition_of`'s shape, so the two
    compare by equality) and where each field lives, `owner` and `workspace`
    included in `storage` though no document decides them."""

    object_id: uuid.UUID
    api_name: str
    applied_version_id: uuid.UUID
    schema_version: int
    definition: DocumentDefinition
    storage: Mapping[str, FieldStorage]


class ObjectDefinitionStore(Protocol):
    """One publish transaction, bound to the tenant and the actor of its
    `ArtifactTx`."""

    @property
    def context(self) -> AccessContext:
        """Who the transaction acts as: the hook's audit actor."""
        ...

    async def lock_object(self, object_id: uuid.UUID) -> None:
        """`pg_advisory_xact_lock` on `object_lock_key(tenant, object)`."""
        ...

    async def version(self, version_id: uuid.UUID) -> ObjectVersion | None: ...

    async def applied(self, object_id: uuid.UUID) -> AppliedObject | None: ...

    async def insert_object(
        self,
        *,
        object_id: uuid.UUID,
        api_name: str,
        labels: Mapping[str, str],
        ai_description: str | None,
        default_access: str,
        version_id: uuid.UUID,
        version_no: int,
    ) -> None: ...

    async def update_object(self, object_id: uuid.UUID, **values: Any) -> None: ...

    async def used_slots(self, object_id: uuid.UUID) -> frozenset[str]:
        """Every slot a field of the object holds, read now, not from a snapshot."""
        ...

    async def take_field_no(self, object_id: uuid.UUID) -> int:
        """The object's next `field_no`, and the counter moved past it."""
        ...

    async def insert_field(
        self,
        *,
        object_id: uuid.UUID,
        field_id: uuid.UUID,
        field: FieldDefinition,
        storage_kind: str,
        slot: str | None,
        field_no: int | None,
    ) -> None: ...

    async def update_field(self, field_id: uuid.UUID, **values: Any) -> None: ...

    async def put_options(self, field_id: uuid.UUID, options: Sequence[OptionDefinition]) -> None:
        """Insert each option, or update its labels, position and active flag."""
        ...


class ObjectDefinitionReader(Protocol):
    async def read(self, tenant_id: uuid.UUID, object_id: uuid.UUID) -> AppliedObject | None:
        """The object of that tenant only, as the store holds it under RLS."""
        ...
