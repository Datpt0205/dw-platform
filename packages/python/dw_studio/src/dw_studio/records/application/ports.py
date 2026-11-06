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
from datetime import datetime
from typing import Any, Protocol

from dw_kernel.filters import ListQuery
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent
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

    @property
    def lane(self) -> str | None:
        """The lane carrying out the actor's recorded decision (`outbox` at a
        publish request's `.decided` handler), for `details.lane`; None on the
        actor's own request (custom-objects ticket 06)."""
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


# ---- the records (custom-objects ticket 03) -----------------------------------


@dataclass(frozen=True, slots=True)
class Binding:
    """What the door bound the transaction to, read back from it: the
    company, the working workspace a new record belongs to, and the mode
    `bind_actor` read from a run's row (empty for a person)."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None
    run_mode: str


@dataclass(frozen=True, slots=True)
class ObjectSummary:
    object_id: uuid.UUID
    api_name: str
    labels: Mapping[str, str]
    ai_description: str | None


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """A record as the caller's transaction reads it under the record
    policies, its values by `api_name` in their kept form, and whether the
    same policies' arms admit an update or a soft delete by this actor."""

    id: uuid.UUID
    object_id: uuid.UUID
    workspace_id: uuid.UUID
    owner_kind: str
    owner_id: uuid.UUID
    name: str
    version: int
    created_at: datetime
    created_by: uuid.UUID
    updated_at: datetime
    updated_by: uuid.UUID
    deleted_at: datetime | None
    deleted_by: uuid.UUID | None
    values: Mapping[str, Any]
    may_update: bool
    may_delete: bool


@dataclass(frozen=True, slots=True)
class NewRecord:
    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    values: Mapping[str, Any]
    create_key: str | None


@dataclass(frozen=True, slots=True)
class KeyedRecord:
    """A record a `wf:` key already wrote: its id, who wrote it, and the
    result the first write gave (`version`, `created`)."""

    record_id: uuid.UUID
    actor_id: uuid.UUID
    version: int
    created: bool


class DuplicateSlotError(Exception):
    """A unique field's value is another live record's: the `u` slot's partial
    UNIQUE refused the write. The transaction is lost."""

    def __init__(self, api_name: str) -> None:
        super().__init__(api_name)
        self.api_name = api_name


class CreateKeyTakenError(Exception):
    """`create_key` is another record's of the object (its UNIQUE refused the
    insert). The transaction is lost."""


class WriteRefusedError(Exception):
    """The record policies (WITH CHECK) or the owner check refused the row.
    The transaction is lost."""


class RecordTx(Protocol):
    """One transaction of a record operation, bound by its door. Every
    statement names the bound company's `tenant_id`; the record policies
    decide which rows it sees and changes."""

    @property
    def binding(self) -> Binding: ...

    async def object_id(self, api_name: str) -> uuid.UUID | None: ...

    async def objects(self) -> Sequence[ObjectSummary]: ...

    async def lock_shared(self, object_id: uuid.UUID) -> None:
        """`pg_advisory_xact_lock_shared` on `object_lock_key(tenant, object)`."""
        ...

    async def definition(self, object_id: uuid.UUID) -> AppliedObject | None: ...

    async def read(self, obj: AppliedObject, record_id: uuid.UUID) -> StoredRecord | None: ...

    async def page(self, obj: AppliedObject, query: ListQuery) -> Sequence[StoredRecord]:
        """Up to ``query.page.fetch_limit`` live records of ``obj`` the caller
        reads, matching its filter, in its order past its cursor (custom-objects
        ticket 04). ``may_update`` and ``may_delete`` are not read: False."""
        ...

    async def count(self, obj: AppliedObject, query: ListQuery, cap: int) -> int:
        """How many live records the caller reads match ``query``'s filter,
        counted up to ``cap + 1`` and no further (R8.8)."""
        ...

    async def match(self, obj: AppliedObject, api_name: str, value: Any) -> StoredRecord | None:
        """The live record whose unique field ``api_name`` holds ``value``,
        if the caller reads it."""
        ...

    async def by_create_key(self, object_id: uuid.UUID, key: str) -> KeyedRecord | None: ...

    async def written(self, write_key: str) -> KeyedRecord | None:
        """The caller's own `studio.record_write_keys` row of ``write_key``."""
        ...

    async def insert(self, obj: AppliedObject, record: NewRecord, *, arbiter: str | None) -> bool:
        """False when ``arbiter``'s value is another live record's
        (`ON CONFLICT ... DO NOTHING` on its `u` slot); raises
        `DuplicateSlotError`, `CreateKeyTakenError` or `WriteRefusedError`."""
        ...

    async def update(
        self,
        obj: AppliedObject,
        record_id: uuid.UUID,
        version: int,
        changes: Mapping[str, Any],
        by: uuid.UUID,
    ) -> int | None:
        """The new version, or None when no live row at ``version`` let the
        caller change it."""
        ...

    async def soft_delete(self, record_id: uuid.UUID, version: int, by: uuid.UUID) -> int | None:
        """As `update`; `WriteRefusedError` when the new row is outside the
        caller's `delete` reach (WITH CHECK)."""
        ...

    async def keep_write_key(
        self, write_key: str, record_id: uuid.UUID, op: str, version: int, by: uuid.UUID
    ) -> bool:
        """False when the key is already a row (anyone's)."""
        ...

    async def outbox(self, event: OutboxEvent) -> None: ...

    async def audit(self, event: AuditEvent) -> None: ...

    async def claim(self, claim: EffectClaim) -> None: ...


class RecordStore(Protocol):
    async def bind(self, tx: Any) -> RecordTx:
        """The record operations of the door's open transaction;
        `ActorUnboundError` when it is bound to no company."""
        ...
