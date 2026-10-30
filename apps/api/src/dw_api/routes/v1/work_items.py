"""The shared work queue: /api/v1/work-items (digital-worker R3.5, R3.8, R3.11,
R3.13), and the hand-given work of a DW, `POST /digital-workers/{id}/work-items`
(R3.10), mounted on the DW router's prefix.

The queue owns every rule; the route shapes the request. A list never carries a
payload or a hand-off packet; one item carries them for its holder and the DW's
four people only, and one item carries its run's `trail` (wf-lite R6.13): ids
and states only, for whoever may read the item. Refusals the web branches on,
in `details.reason_code`: 403 `not_holder`, `not_work_assigner`; 409
`invalid_transition`, `source_key_reused`; 422 `payload_invalid`,
`work_kind_outside_mandate`, `dw_not_accepting_work`.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.pagination import Page
from dw_platform.application.access_context import AccessContext
from dw_platform.application.work_queue import NewWork, WorkListFilter, WorkQueue
from dw_platform.domain.work_item import WorkItem, WorkStatus

router = APIRouter(prefix="/work-items", tags=["work"])
# An item whose run has not ended: its trail is in the run's checkpoint.
_LIVE: frozenset[WorkStatus] = frozenset({"in_progress", "waiting_approval", "waiting_timer"})
assign_router = APIRouter(prefix="/digital-workers", tags=["digital-workers"])


def _queue(container: ApiContainer) -> WorkQueue:
    if container.work_queue is None:
        raise InfrastructureError("the work queue is not configured")
    return container.work_queue


def _path_id(check: CheckInput, name: str) -> UUID | None:
    try:
        return UUID(check.request.path_params[name])
    except (KeyError, ValueError):
        return None


async def _holder_of_path(check: CheckInput) -> None:
    """The queue's own holder check, before any key row is read (R2.30)."""
    item_id = _path_id(check, "item_id")
    if item_id is not None:
        await _queue(check.container).require_holder(check.context, item_id)


async def _assigner_of_path(check: CheckInput) -> None:
    dw_id = _path_id(check, "dw_id")
    if dw_id is not None:
        await _queue(check.container).require_work_assigner(check.context, dw_id)


CompleteIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_holder_of_path, operation="POST /work-items/{item_id}/complete"),
]
AssignIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_assigner_of_path, operation="POST /digital-workers/{dw_id}/work-items"),
]


class HandoffView(BaseModel):
    problem: str
    context: str
    tried: str
    recommendation: str


class TrailEntryView(BaseModel):
    step_id: str
    type: str
    status: str
    at: str


class WorkItemView(BaseModel):
    id: UUID
    dw_id: UUID
    kind: str
    source_key: str
    status: str
    holder_kind: str
    holder_id: UUID
    available_at: datetime
    wake_at: datetime | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    # Present only for who may read them (R3.11); never in a list.
    payload: dict[str, Any] | None = None
    handoff: HandoffView | None = None
    # One item's run, step by step; never in a list or a write's answer.
    trail: list[TrailEntryView] | None = None


def _view(item: WorkItem, *, contents: bool) -> WorkItemView:
    return WorkItemView(
        id=item.id,
        dw_id=item.dw_id,
        kind=item.kind,
        source_key=item.source_key,
        status=item.status,
        holder_kind=item.holder_kind,
        holder_id=item.holder_id,
        available_at=item.available_at,
        wake_at=item.wake_at,
        error=item.error,
        created_at=item.created_at,
        updated_at=item.updated_at,
        closed_at=item.closed_at,
        payload=dict(item.payload) if contents and item.payload else None,
        handoff=HandoffView(**item.handoff.as_dict()) if contents and item.handoff else None,
    )


class NewWorkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=120)
    source_key: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any]


@router.get("", response_model=Page[WorkItemView])
async def list_work_items(
    context: RequireAccessContext,
    container: RequireContainer,
    page: RequireListPage,
    status: Annotated[WorkStatus | None, Query()] = None,
    holder_kind: Annotated[Literal["digital_worker", "person"] | None, Query()] = None,
) -> Page[WorkItemView]:
    request = page.request(
        context,
        key="work_items",
        filters={
            "tenant": context.tenant_id,
            "workspace": context.workspace_id,
            "status": status,
            "holder_kind": holder_kind,
        },
    )
    listed = await _queue(container).page(
        context, request, WorkListFilter(status=status, holder_kind=holder_kind)
    )
    return listed.map_items(lambda item: _view(item, contents=False))


@router.get("/{item_id}", response_model=WorkItemView)
async def get_work_item(
    item_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> WorkItemView:
    item = await _queue(container).get(context, item_id)
    view = _view(item, contents=True)
    if item.run_id is None or container.run_trails is None:
        return view.model_copy(update={"trail": []})
    # Under the caller's own tenant and workspace, as the item was read.
    trail = await container.run_trails.trail(
        tenant_id=context.tenant_id,
        workspace_id=context.workspace_id,
        run_id=item.run_id,
        live=item.status in _LIVE,
    )
    return view.model_copy(update={"trail": [TrailEntryView(**entry) for entry in trail]})


async def _viewed(item: Awaitable[WorkItem]) -> WorkItemView:
    return _view(await item, contents=True)


async def _reread(queue: WorkQueue, context: AccessContext, item_id: str) -> WorkItemView:
    return _view(await queue.get(context, UUID(item_id)), contents=True)


@router.post("/{item_id}/complete", response_model=WorkItemView)
async def complete_work_item(
    item_id: UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: CompleteIdempotency,
) -> WorkItemView:
    queue = _queue(container)
    view = await idempotency.once(
        status=200,
        run=lambda effect: _viewed(queue.complete(context, item_id, effect=effect)),
        reread=lambda found: _reread(queue, context, found),
    )
    return await idempotency.record(view)


@assign_router.post("/{dw_id}/work-items", response_model=WorkItemView, status_code=201)
async def give_work(
    dw_id: UUID,
    body: NewWorkRequest,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: AssignIdempotency,
) -> WorkItemView:
    queue = _queue(container)
    work = NewWork(kind=body.kind, source_key=body.source_key, payload=body.payload)
    view = await idempotency.once(
        status=201,
        run=lambda effect: _viewed(queue.enqueue_by_person(context, dw_id, work, effect=effect)),
        reread=lambda found: _reread(queue, context, found),
    )
    return await idempotency.record(view, status_code=201)
