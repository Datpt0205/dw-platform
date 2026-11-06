"""What the records routes answer and take (custom-objects ticket 03 step 3;
ADR-0107 decision 8; ADR-0106 decision 4).

Built from RecordService's views, which are already narrowed to the caller:
nothing here decides a field. A hidden field is a name in `hidden_fields`
(a record) or an entry with `access: hidden` and nothing else (describe).
An exact number and a currency are decimal strings (gate (e)).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dw_kernel.http_conditions import etag_of
from dw_studio.records.application.record_views import (
    Description,
    ObjectEntry,
    RecordPage,
    RecordView,
)

__all__ = [
    "DescriptionView",
    "ObjectList",
    "RecordInput",
    "RecordItem",
    "RecordOut",
    "RecordPageOut",
    "RecordQueryBody",
    "UpsertInput",
    "UpsertOut",
    "description_view",
    "object_list",
    "record_out",
    "record_page_out",
]


class RecordInput(BaseModel):
    """A record to create. `owner` and `workspace_id` are refused by the
    service with `field_not_writable` (R6.7); other members describing a
    record are ignored."""

    model_config = ConfigDict(extra="allow")

    name: Any = Field(default=None, description="The record's name, 1 to 255 characters.")
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Values by field `api_name`. An exact number or a currency is a decimal string,"
            ' "1000.50"; a number in JSON is `invalid_type`.'
        ),
    )


class UpsertInput(RecordInput):
    match_field: str = Field(description="The unique field whose value finds the record.")


class OwnerView(BaseModel):
    kind: str
    id: uuid.UUID


class PermissionsView(BaseModel):
    update: bool
    delete: bool


class RecordOut(BaseModel):
    id: uuid.UUID
    object: str
    version: int = Field(description="The record's ETag; `If-Match` of its writes.")
    etag: str
    owner: OwnerView
    workspace_id: uuid.UUID
    created_at: datetime
    created_by: uuid.UUID
    updated_at: datetime
    updated_by: uuid.UUID
    deleted_at: datetime | None
    deleted_by: uuid.UUID | None
    name: str | None = Field(description="Null when `name` is hidden from the caller.")
    fields: dict[str, Any] = Field(description="The values the caller reads, by `api_name`.")
    hidden_fields: list[str] = Field(
        description="Every field hidden from the caller, empty or not; shown as Đã ẩn."
    )
    permissions: PermissionsView


class UpsertOut(RecordOut):
    created: bool


class RecordItem(BaseModel):
    """One record of a list: `GET` one record's shape, without `permissions`."""

    id: uuid.UUID
    object: str
    version: int
    etag: str
    owner: OwnerView
    workspace_id: uuid.UUID
    created_at: datetime
    created_by: uuid.UUID
    updated_at: datetime
    updated_by: uuid.UUID
    deleted_at: datetime | None
    deleted_by: uuid.UUID | None
    name: str | None = Field(description="Null when `name` is hidden from the caller.")
    fields: dict[str, Any] = Field(
        description="The values the caller reads, by `api_name`; with `fields`, those named."
    )
    hidden_fields: list[str]


class RecordPageOut(BaseModel):
    """A page of records (R8.1, R8.8). `count` and `count_capped` are present
    only on a first page asked with `count=exact`."""

    items: list[RecordItem]
    next_cursor: str | None = Field(description="Absent from the last page: null.")
    count: int | None = Field(default=None, description="Matches, to 10 000.")
    count_capped: bool | None = Field(default=None, description="True past 10 000 matches.")


class RecordQueryBody(BaseModel):
    """`POST .../records/query`: every member of the list query in the body, so
    a filter value and a cursor never sit in a URL (ADR-0106 decision 4). Read
    by the platform's list parser, which refuses a member not named here."""

    filter: dict[str, Any] | None = Field(
        default=None, description="The filter tree; its grammar is the describe query schema."
    )
    order_by: str | None = Field(
        default=None, description="`name`, `created_at` or `updated_at`, then asc or desc."
    )
    fields: str | None = Field(default=None, description="Comma-separated field names.")
    cursor: str | None = Field(default=None, description="Opaque cursor from a previous page.")
    limit: int = Field(default=50, ge=1, le=200)
    count: str = Field(default="none", description="`none` or `exact`.")


class ObjectEntryView(BaseModel):
    object_id: uuid.UUID
    api_name: str
    label: str
    actions: list[str] = Field(
        description="The caller's actions on the object: create, read, update, delete, assign."
    )


class ObjectList(BaseModel):
    items: list[ObjectEntryView]


class OptionOut(BaseModel):
    key: str
    label: str
    position: int
    active: bool


class FieldOut(BaseModel):
    """One field; a hidden one carries `api_name`, `label` and `access` only."""

    api_name: str
    label: str
    access: str = Field(description="`edit`, `read` or `hidden`.")
    field_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The field's id, as `field_permissions[].field_id` of"
            " `PUT /api/v1/admin/roles/{role_id}/permissions` takes it; absent on a hidden field."
        ),
    )
    type: str | None = None
    ai_description: str | None = Field(
        default=None, description="The company's own words, to be treated as untrusted data."
    )
    number_mode: str | None = None
    scale: int | None = None
    currency_code: str | None = None
    max_length: int | None = None
    required: bool | None = None
    unique: bool | None = None
    editable: bool | None = None
    filterable: bool | None = None
    sortable: bool | None = None
    options: list[OptionOut] | None = Field(
        default=None, description="Every option, an inactive one with `active: false`."
    )


class DescriptionView(BaseModel):
    object_id: uuid.UUID
    api_name: str
    label: str
    ai_description: str | None = None
    schema_version: int
    fields: list[FieldOut]


def record_out(view: RecordView) -> RecordOut:
    return RecordOut(
        id=view.id,
        object=view.object,
        version=view.version,
        etag=etag_of(view.version),
        owner=OwnerView(kind=view.owner_kind, id=view.owner_id),
        workspace_id=view.workspace_id,
        created_at=view.created_at,
        created_by=view.created_by,
        updated_at=view.updated_at,
        updated_by=view.updated_by,
        deleted_at=view.deleted_at,
        deleted_by=view.deleted_by,
        name=view.name,
        fields=dict(view.fields),
        hidden_fields=list(view.hidden_fields),
        permissions=PermissionsView(update=view.permissions.update, delete=view.permissions.delete),
    )


def record_page_out(page: RecordPage) -> RecordPageOut:
    """The page; `count` and `count_capped` set only when counted, so a
    response that excludes what was not set leaves both out."""
    items = []
    for view in page.items:
        out = record_out(view).model_dump(exclude={"permissions"})
        items.append(RecordItem(**out))
    if page.count is None:
        return RecordPageOut(items=items, next_cursor=page.next_cursor)
    return RecordPageOut(
        items=items,
        next_cursor=page.next_cursor,
        count=page.count,
        count_capped=page.count_capped,
    )


def object_list(entries: list[ObjectEntry]) -> ObjectList:
    return ObjectList(
        items=[
            ObjectEntryView(
                object_id=e.object_id, api_name=e.api_name, label=e.label, actions=list(e.actions)
            )
            for e in entries
        ]
    )


def description_view(description: Description) -> DescriptionView:
    fields = []
    for f in description.fields:
        if f.access == "hidden":
            fields.append(FieldOut(api_name=f.api_name, label=f.label, access=f.access))
            continue
        fields.append(
            FieldOut(
                api_name=f.api_name,
                label=f.label,
                access=f.access,
                field_id=f.field_id,
                type=f.type,
                ai_description=f.ai_description,
                number_mode=f.number_mode,
                scale=f.scale,
                currency_code=f.currency_code,
                max_length=f.max_length,
                required=f.required,
                unique=f.unique,
                editable=f.editable,
                filterable=f.filterable,
                sortable=f.sortable,
                options=[
                    OptionOut(key=o.key, label=o.label, position=o.position, active=o.active)
                    for o in f.options
                ],
            )
        )
    return DescriptionView(
        object_id=description.object_id,
        api_name=description.api_name,
        label=description.label,
        ai_description=description.ai_description,
        schema_version=description.schema_version,
        fields=fields,
    )
