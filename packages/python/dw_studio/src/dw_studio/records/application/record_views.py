"""What RecordService answers, for every door alike (custom-objects ticket 03):
a record as the caller reads it, the result of a write, an object's
description and the object catalogue, each already narrowed to the caller.

A view never carries a value the caller's `FieldAccess` hides: a hidden field
is a name in `hidden_fields` and nothing else (ADR-0106 decision 4), `name`
included (gate (g)). Building one is a pure function of what the transaction
read, so the API, a workflow step and an agent's tool get the same shape.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dw_studio.core.domain.field_access import HIDDEN, FieldAccess
from dw_studio.records.application.ports import AppliedObject, StoredRecord
from dw_studio.records.domain.document import NAME
from dw_studio.records.domain.values import present


@dataclass(frozen=True, slots=True)
class Permissions:
    """What the caller may do to the record now: the object action key and
    the record policy's own arms (`may_sql`), together (gate (l))."""

    update: bool
    delete: bool


@dataclass(frozen=True, slots=True)
class RecordView:
    id: uuid.UUID
    object: str
    version: int
    owner_kind: str
    owner_id: uuid.UUID
    workspace_id: uuid.UUID
    created_at: datetime
    created_by: uuid.UUID
    updated_at: datetime
    updated_by: uuid.UUID
    deleted_at: datetime | None
    deleted_by: uuid.UUID | None
    name: str | None
    fields: Mapping[str, Any]
    hidden_fields: tuple[str, ...]
    permissions: Permissions


@dataclass(frozen=True, slots=True)
class WriteResult:
    """One write's answer: the record read back under the caller's current
    authority, whether this call created it, and, for a replayed `wf:` key,
    the version and `created` the first write gave (R5.10)."""

    record: RecordView
    created: bool
    version: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class RecordPage:
    """One page of a record list (custom-objects ticket 04, R8.1, R8.8): the
    records as `get` shows each, `permissions` not read (False), the cursor of
    the next page, and on a first page asked with `count=exact` how many match
    up to the cap, with ``count_capped`` past it."""

    items: tuple[RecordView, ...]
    next_cursor: str | None
    count: int | None = None
    count_capped: bool | None = None


@dataclass(frozen=True, slots=True)
class OptionView:
    key: str
    label: str
    position: int
    active: bool


@dataclass(frozen=True, slots=True)
class FieldView:
    """One field as the caller may know it. A hidden field carries its name,
    label and `access` only (R3.2): every other member stays None or empty,
    `field_id` too, which a readable field carries (R3.1; custom-objects/12)."""

    api_name: str
    label: str
    access: str
    # The `studio.field_defs` row's id, what a role's field permission names
    # (tenant-rbac R9.13); present exactly when `access` is not `hidden`.
    field_id: uuid.UUID | None = None
    type: str | None = None
    ai_description: str | None = None
    number_mode: str | None = None
    scale: int | None = None
    currency_code: str | None = None
    max_length: int | None = None
    required: bool | None = None
    unique: bool | None = None
    editable: bool | None = None
    filterable: bool | None = None
    sortable: bool | None = None
    options: tuple[OptionView, ...] = ()


@dataclass(frozen=True, slots=True)
class Description:
    object_id: uuid.UUID
    api_name: str
    label: str
    ai_description: str | None
    schema_version: int
    fields: tuple[FieldView, ...]


@dataclass(frozen=True, slots=True)
class ObjectEntry:
    """An object the caller reads, and every action it holds on it (gate (x))."""

    object_id: uuid.UUID
    api_name: str
    label: str
    actions: tuple[str, ...]


def readable(access: FieldAccess, api_name: str) -> bool:
    level = access.level_of(api_name)
    return level is not None and level != HIDDEN


def readable_names(access: FieldAccess) -> frozenset[str]:
    """Every field the caller reads, by `api_name`."""
    return frozenset(
        name for field, name in access.api_names.items() if access.levels[field] != HIDDEN
    )


def hidden_fields(access: FieldAccess) -> tuple[str, ...]:
    """Every field hidden from the caller, empty or not (ADR-0106 decision 4)."""
    return tuple(
        sorted(name for field, name in access.api_names.items() if access.levels[field] == HIDDEN)
    )


def record_view(
    obj: AppliedObject,
    stored: StoredRecord,
    access: FieldAccess,
    holds: Callable[[str], bool],
) -> RecordView:
    """``stored`` as the caller reads it: only readable values, each as a
    caller reads it (`present`), and the permissions both halves allow."""
    definitions = obj.definition.fields
    return RecordView(
        id=stored.id,
        object=obj.api_name,
        version=stored.version,
        owner_kind=stored.owner_kind,
        owner_id=stored.owner_id,
        workspace_id=stored.workspace_id,
        created_at=stored.created_at,
        created_by=stored.created_by,
        updated_at=stored.updated_at,
        updated_by=stored.updated_by,
        deleted_at=stored.deleted_at,
        deleted_by=stored.deleted_by,
        name=stored.name if readable(access, NAME) else None,
        fields={
            name: present(definitions[name], stored.values.get(name))
            for name in sorted(definitions)
            if name != NAME and readable(access, name)
        },
        hidden_fields=hidden_fields(access),
        permissions=Permissions(
            update=holds(f"obj.{obj.api_name}.update") and stored.may_update,
            delete=holds(f"obj.{obj.api_name}.delete") and stored.may_delete,
        ),
    )
