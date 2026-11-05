"""`/api/v1/studio/objects`: a company's objects and their records
(custom-objects ticket 03; R3, R5-R7; ADR-0107 decision 8).

Mounted only inside the Studio group (`dw_api.main.mount_studio`), behind its
gate and its dependency, so every route has a verified identity, and a
support grant header is refused before the route runs (R4.5): no route here is
in `SUPPORT_ALLOWED_ROUTES`. Every route calls the one `RecordService` through
the door the composition root builds (`record_door`): each transaction is the
caller's request, bound by `user_session`, so the record policies decide.

Errors are the platform's problem+json (ADR-0108 decision 1): a record that
does not exist, belongs to another company or is not readable is one 404
(R5.7); a missing object key is 403 before any record is read (R3.4). A record
is an R3 resource of app-standards: its `ETag` is its version, `PATCH` and
`DELETE` require `If-Match` (412 when stale, 428 when absent). The create
takes an optional `Idempotency-Key` and the upsert requires one, both bound to
the caller (app-standards/02); a step's `wf:` key never comes from here
(gate (a)).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.conditions import MergePatch, RequireIfMatch
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.http_conditions import ExpectedVersion, etag_of
from dw_platform.application.access_context import AccessContext
from dw_studio.records.application.record_service import RecordDoor, RecordService
from dw_studio.records.application.record_views import RecordView
from dw_studio.records.presentation.views import (
    DescriptionView,
    ObjectList,
    RecordInput,
    RecordOut,
    UpsertInput,
    UpsertOut,
    description_view,
    object_list,
    record_out,
)

router = APIRouter(prefix="/objects")

_BASE = "/api/v1/studio/objects"
_NO_STORE = "private, no-store"


def _records(container: Any) -> RecordService:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    service: RecordService = container.studio.records
    return service


def _door(container: Any, context: AccessContext) -> RecordDoor:
    door: RecordDoor = container.studio.record_door(context)
    return door


def _expected(if_match: ExpectedVersion) -> int:
    # A tag that names no version this platform minted never matches: 412.
    return 0 if if_match.version is None else if_match.version


def _headers(api_name: str, view: RecordView) -> dict[str, str]:
    return {"ETag": etag_of(view.version), "Location": f"{_BASE}/{api_name}/records/{view.id}"}


async def _may_create(check: CheckInput) -> None:
    """The route's own check before a key row is read (app-standards R2.30):
    the object, then `obj.<api_name>.create`."""
    api_name = check.request.path_params.get("api_name", "")
    await _records(check.container).require(
        _door(check.container, check.context), api_name, "create"
    )


CreateIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_create, operation="POST /studio/objects/{api_name}/records"),
]
UpsertIdempotency = Annotated[
    IdempotentOperation,
    idempotent(
        _may_create, operation="POST /studio/objects/{api_name}/records/upsert", required=True
    ),
]


@router.get("", response_model=ObjectList)
async def list_objects(
    context: RequireStudioAccess, container: RequireContainer, response: Response
) -> ObjectList:
    """R3.5: the objects whose read key the caller holds, with its actions."""
    response.headers["Cache-Control"] = _NO_STORE
    service = _records(container)
    return object_list(await service.objects(_door(container, context)))


@router.get(
    "/{api_name}/describe", response_model=DescriptionView, response_model_exclude_none=True
)
async def describe_object(
    api_name: str,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    action: Literal["read", "create"] = Query(
        default="read",
        description="`create` describes the creation form, with the create key (R3.1).",
    ),
) -> DescriptionView:
    response.headers["Cache-Control"] = _NO_STORE
    service = _records(container)
    return description_view(await service.describe(_door(container, context), api_name, action))


@router.post("/{api_name}/records", response_model=RecordOut, status_code=201)
async def create_record(
    api_name: str,
    body: RecordInput,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    idempotency: CreateIdempotency,
) -> RecordOut:
    service, door = _records(container), _door(container, context)
    sent = body.model_dump(exclude_unset=True)

    async def run(effect: Any) -> RecordView:
        return (await service.create(door, api_name, sent, effect=effect)).record

    async def reread(id_: str) -> RecordView:
        return await service.get(door, api_name, uuid.UUID(id_))

    view = await idempotency.once(status=201, run=run, reread=reread)
    headers = _headers(api_name, view)
    response.headers.update(headers)
    result: RecordOut = await idempotency.record(record_out(view), status_code=201, headers=headers)
    return result


@router.post(
    "/{api_name}/records/upsert",
    response_model=UpsertOut,
    responses={201: {"model": UpsertOut, "description": "Created"}},
)
async def upsert_record(
    api_name: str,
    body: UpsertInput,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    idempotency: UpsertIdempotency,
) -> UpsertOut:
    """R7.2: 201 `created: true` or 200 `created: false`. A retry after the
    first attempt committed and died before answering reads the record back
    and answers 200 (gate (t)); a stored answer keeps its first status."""
    service, door = _records(container), _door(container, context)
    sent = body.model_dump(exclude_unset=True)

    async def run(effect: Any) -> tuple[RecordView, bool]:
        result = await service.upsert(door, api_name, sent, effect=effect)
        return result.record, result.created

    async def reread(id_: str) -> tuple[RecordView, bool]:
        return await service.get(door, api_name, uuid.UUID(id_)), False

    view, created = await idempotency.once(status=200, run=run, reread=reread)
    status = 201 if created else 200
    headers = _headers(api_name, view)
    response.headers.update(headers)
    response.status_code = status
    out = UpsertOut(**record_out(view).model_dump(), created=created)
    result: UpsertOut = await idempotency.record(out, status_code=status, headers=headers)
    return result


@router.get("/{api_name}/records/{record_id}", response_model=RecordOut)
async def read_record(
    api_name: str,
    record_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
) -> RecordOut:
    view = await _records(container).get(_door(container, context), api_name, record_id)
    response.headers["ETag"] = etag_of(view.version)
    response.headers["Cache-Control"] = _NO_STORE
    return record_out(view)


@router.patch("/{api_name}/records/{record_id}", response_model=RecordOut)
async def update_record(
    api_name: str,
    record_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    expected: RequireIfMatch,
    patch: MergePatch,
) -> RecordOut:
    """A JSON Merge Patch on `name` and `fields`; `owner` and
    `workspace_id` are `field_not_writable` (R6.7)."""
    result = await _records(container).update(
        _door(container, context), api_name, record_id, patch, expected=_expected(expected)
    )
    response.headers["ETag"] = etag_of(result.record.version)
    return record_out(result.record)


@router.delete("/{api_name}/records/{record_id}", response_model=RecordOut)
async def delete_record(
    api_name: str,
    record_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    expected: RequireIfMatch,
) -> RecordOut:
    """R5.5: a soft delete; the record comes back with `deleted_at`."""
    result = await _records(container).delete(
        _door(container, context), api_name, record_id, expected=_expected(expected)
    )
    response.headers["ETag"] = etag_of(result.record.version)
    return record_out(result.record)
