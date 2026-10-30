"""Digital Workers: /api/v1/digital-workers (digital-worker R1, R2, R7, R8).

Create a DW with its principal, list and read the workspace's DWs, change a
DW's state, replace its four people, read its scorecard, and raise or lower a
decision class's earned level. The service owns every rule (scopes,
the four people, the second person, the roles a principal may hold); the route
shapes the request and lets a domain error map to its status.

Refusals the web branches on, in `details.reason_code`: 422 `owner_not_member`,
`validator_cannot_decide`, `tool_unknown`, `work_kinds_empty`, `above_ceiling`,
`role_not_allowed_for_service`; 403 `grants_not_covered`, `not_dw_owner`; 409
`invalid_transition`, `second_person_required`, `dw_key_taken`. A DW the caller
may not read is 404, the same as one that does not exist (R1.5). The scorecard:
422 `days_out_of_range`. Autonomy: 403 `not_dw_owner`; 404
`decision_class_not_found`; 422 `above_ceiling`, `level_invalid`,
`level_unchanged`; 409 `raise_pending`, `level_changed`; 202 when a raise
waits for its second person.
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.autonomy import AutonomyLevel
from dw_kernel.errors import InfrastructureError
from dw_kernel.pagination import Page
from dw_platform.application.access_context import AccessContext
from dw_platform.application.digital_workers import (
    DW_MANAGE,
    ChangeState,
    CreateDigitalWorker,
    DigitalWorkerService,
)
from dw_platform.application.dw_autonomy import AutonomyChange, DwAutonomyService
from dw_platform.application.scorecard import DEFAULT_DAYS, Scorecard, ScorecardService
from dw_platform.domain.digital_worker import (
    DecisionClass,
    DigitalWorker,
    DwConfiguration,
    DwPeople,
    DwState,
    EffectLevel,
)

router = APIRouter(prefix="/digital-workers", tags=["digital-workers"])


def _service(container: ApiContainer) -> DigitalWorkerService:
    if container.digital_workers is None:
        raise InfrastructureError("digital workers are not configured")
    return container.digital_workers


def _scorecards(container: ApiContainer) -> ScorecardService:
    if container.dw_scorecard is None:
        raise InfrastructureError("digital workers are not configured")
    return container.dw_scorecard


def _autonomy(container: ApiContainer) -> DwAutonomyService:
    if container.dw_autonomy is None:
        raise InfrastructureError("digital workers are not configured")
    return container.dw_autonomy


async def _owner_of_path(check: CheckInput) -> None:
    """The service's own who-may check, before any key row is read (app-standards
    R2.30): 404 for a DW the caller may not read, 403 for one they do not own."""
    try:
        dw_id = UUID(check.request.path_params["dw_id"])
    except (KeyError, ValueError):
        return
    await _service(check.container).require_owner(check.context, dw_id)


CreateIdempotency = Annotated[
    IdempotentOperation, idempotent(DW_MANAGE, operation="POST /digital-workers")
]
StateIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_owner_of_path, operation="POST /digital-workers/{dw_id}/state"),
]
PeopleIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_owner_of_path, operation="PUT /digital-workers/{dw_id}/people"),
]
AutonomyIdempotency = Annotated[
    IdempotentOperation,
    idempotent(
        _owner_of_path, operation="POST /digital-workers/{dw_id}/decision-classes/{key}/autonomy"
    ),
]


class DecisionClassBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    effect_level: str
    reversible: bool
    ceiling: str
    earned_level: str


class PeopleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_owner_id: UUID
    technical_owner_id: UUID
    work_assigner_id: UUID
    validator_id: UUID


class CreateDigitalWorkerRequest(BaseModel):
    """Unknown fields are ignored, not refused: a `tenant_id` or `workspace_id`
    in the body changes nothing, both come from the access context (R1.1)."""

    key: str
    name: str
    mandate: str
    work_kinds: list[str]
    allowed_tools: list[str] = Field(default_factory=list)
    workflow_key: str
    workflow_version: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    role_keys: list[str]
    people: PeopleBody
    decision_classes: list[DecisionClassBody] = Field(default_factory=list)


class ChangeStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str


class DecisionClassView(BaseModel):
    key: str
    effect_level: str
    reversible: bool
    ceiling: str
    earned_level: str


class PeopleView(BaseModel):
    # None once the Business Owner's user row is gone; such a DW takes no work.
    business_owner_id: UUID | None
    technical_owner_id: UUID
    work_assigner_id: UUID
    validator_id: UUID


class DigitalWorkerView(BaseModel):
    id: UUID
    key: str
    name: str
    mandate: str
    state: str
    work_kinds: list[str]
    allowed_tools: list[str]
    workflow_key: str
    workflow_version: str
    parameters: dict[str, Any]
    principal_user_id: UUID
    role_keys: list[str]
    people: PeopleView
    decision_classes: list[DecisionClassView]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


def _view(worker: DigitalWorker) -> DigitalWorkerView:
    config = worker.configuration
    people = worker.people
    return DigitalWorkerView(
        id=worker.id,
        key=config.key,
        name=config.name,
        mandate=config.mandate,
        state=worker.state,
        work_kinds=list(config.work_kinds),
        allowed_tools=list(config.allowed_tools),
        workflow_key=config.workflow_key,
        workflow_version=config.workflow_version,
        parameters=dict(config.parameters),
        principal_user_id=worker.principal_user_id,
        role_keys=sorted(config.role_keys),
        people=PeopleView(
            business_owner_id=people.business_owner_id,
            technical_owner_id=people.technical_owner_id,
            work_assigner_id=people.work_assigner_id,
            validator_id=people.validator_id,
        ),
        decision_classes=[
            DecisionClassView(
                key=c.key,
                effect_level=c.effect_level,
                reversible=c.reversible,
                ceiling=c.ceiling,
                earned_level=c.earned_level,
            )
            for c in config.decision_classes
        ],
        created_by=worker.created_by,
        created_at=worker.created_at,
        updated_at=worker.updated_at,
    )


def _people(body: PeopleBody) -> DwPeople:
    return DwPeople(
        business_owner_id=body.business_owner_id,
        technical_owner_id=body.technical_owner_id,
        work_assigner_id=body.work_assigner_id,
        validator_id=body.validator_id,
    )


def _command(body: CreateDigitalWorkerRequest) -> CreateDigitalWorker:
    # The domain refuses an unknown effect level or autonomy level with its
    # reason code; the casts only carry the strings to it.
    return CreateDigitalWorker(
        configuration=DwConfiguration(
            key=body.key,
            name=body.name,
            mandate=body.mandate,
            work_kinds=tuple(body.work_kinds),
            allowed_tools=tuple(body.allowed_tools),
            workflow_key=body.workflow_key,
            workflow_version=body.workflow_version,
            parameters=body.parameters,
            role_keys=frozenset(body.role_keys),
            decision_classes=tuple(
                DecisionClass(
                    key=c.key,
                    effect_level=cast(EffectLevel, c.effect_level),
                    reversible=c.reversible,
                    ceiling=cast(AutonomyLevel, c.ceiling),
                    earned_level=cast(AutonomyLevel, c.earned_level),
                )
                for c in body.decision_classes
            ),
        ),
        people=_people(body.people),
    )


async def _viewed(worker: Awaitable[DigitalWorker]) -> DigitalWorkerView:
    return _view(await worker)


async def _reread(
    service: DigitalWorkerService, context: AccessContext, dw_id: str
) -> DigitalWorkerView:
    """A retried write, read back as the caller may see the DW now (R2.29)."""
    return _view(await service.get(context, UUID(dw_id)))


@router.post("", response_model=DigitalWorkerView, status_code=201)
async def create_digital_worker(
    body: CreateDigitalWorkerRequest,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: CreateIdempotency,
) -> DigitalWorkerView:
    service = _service(container)
    view = await idempotency.once(
        status=201,
        run=lambda effect: _viewed(service.create(context, _command(body), effect=effect)),
        reread=lambda dw_id: _reread(service, context, dw_id),
    )
    return await idempotency.record(view, status_code=201)


@router.get("", response_model=Page[DigitalWorkerView])
async def list_digital_workers(
    context: RequireAccessContext, container: RequireContainer, page: RequireListPage
) -> Page[DigitalWorkerView]:
    request = page.request(
        context,
        key="digital_workers",
        filters={"tenant": context.tenant_id, "workspace": context.workspace_id},
    )
    listed = await _service(container).list(context, request)
    return listed.map_items(_view)


@router.get("/{dw_id}", response_model=DigitalWorkerView)
async def get_digital_worker(
    dw_id: UUID, context: RequireAccessContext, container: RequireContainer
) -> DigitalWorkerView:
    return _view(await _service(container).get(context, dw_id))


@router.post("/{dw_id}/state", response_model=DigitalWorkerView)
async def change_digital_worker_state(
    dw_id: UUID,
    body: ChangeStateRequest,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: StateIdempotency,
) -> DigitalWorkerView:
    service = _service(container)
    command = ChangeState(target=cast(DwState, body.state))
    view = await idempotency.once(
        status=200,
        run=lambda effect: _viewed(service.change_state(context, dw_id, command, effect=effect)),
        reread=lambda found: _reread(service, context, found),
    )
    return await idempotency.record(view)


@router.put("/{dw_id}/people", response_model=DigitalWorkerView)
async def replace_digital_worker_people(
    dw_id: UUID,
    body: PeopleBody,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: PeopleIdempotency,
) -> DigitalWorkerView:
    service = _service(container)
    view = await idempotency.once(
        status=200,
        run=lambda effect: _viewed(
            service.replace_people(context, dw_id, _people(body), effect=effect)
        ),
        reread=lambda found: _reread(service, context, found),
    )
    return await idempotency.record(view)


class ScorecardItemsView(BaseModel):
    by_status: dict[str, int]
    total: int
    # None with no item in the window: no rate, which is not a rate of 0.
    done_alone_rate: float | None
    handed_off_rate: float | None


class ScorecardDecisionsView(BaseModel):
    approved_as_is: int
    approved_edited: int
    rejected: int


class ScorecardView(BaseModel):
    dw_id: UUID
    days: int
    since: datetime
    items: ScorecardItemsView
    decisions: ScorecardDecisionsView
    # A decimal string, exact to the micro-dollar the column keeps.
    model_cost_usd: str


def _scorecard_view(card: Scorecard) -> ScorecardView:
    counts = card.counts
    return ScorecardView(
        dw_id=card.dw_id,
        days=card.days,
        since=card.since,
        items=ScorecardItemsView(
            by_status=card.items_by_status,
            total=card.items_total,
            done_alone_rate=card.done_alone_rate,
            handed_off_rate=card.handed_off_rate,
        ),
        decisions=ScorecardDecisionsView(
            approved_as_is=counts.approved_as_is,
            approved_edited=counts.approved_edited,
            rejected=counts.rejected,
        ),
        model_cost_usd=str(counts.model_cost_usd),
    )


@router.get("/{dw_id}/scorecard", response_model=ScorecardView)
async def get_digital_worker_scorecard(
    dw_id: UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    days: int = Query(DEFAULT_DAYS),
) -> ScorecardView:
    # The range is the service's: 422 `days_out_of_range` (R7.2).
    return _scorecard_view(await _scorecards(container).scorecard(context, dw_id, days=days))


class AutonomyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str


class AutonomyChangeView(BaseModel):
    outcome: Literal["lowered", "raise_requested"]
    dw_id: UUID
    decision_class: str
    # The level in force now: the new one when lowered, the old one while a
    # raise waits.
    earned_level: str
    requested_level: str
    approval_id: UUID | None


def _change_view(change: AutonomyChange) -> AutonomyChangeView:
    return AutonomyChangeView(
        outcome=change.kind,
        dw_id=change.dw_id,
        decision_class=change.decision_class,
        earned_level=change.earned_level,
        requested_level=change.requested_level,
        approval_id=change.approval_id,
    )


async def _changed(change: Awaitable[AutonomyChange]) -> AutonomyChangeView:
    return _change_view(await change)


async def _reread_change(
    service: DigitalWorkerService,
    context: AccessContext,
    dw_id: UUID,
    key: str,
    level: str,
    found: str,
) -> AutonomyChangeView:
    """A retried change whose answer was not stored, read back as it stands:
    the effect names `<dw>/<class>` for a lowering and the approval for a
    raise; the same key carries the same body, so `level` is what was asked."""
    worker = await service.get(context, dw_id)
    current = next(
        (c.earned_level for c in worker.configuration.decision_classes if c.key == key), level
    )
    raised = "/" not in found
    return AutonomyChangeView(
        outcome="raise_requested" if raised else "lowered",
        dw_id=dw_id,
        decision_class=key,
        earned_level=current,
        requested_level=level,
        approval_id=UUID(found) if raised else None,
    )


@router.post(
    "/{dw_id}/decision-classes/{key}/autonomy",
    response_model=AutonomyChangeView,
    responses={202: {"model": AutonomyChangeView, "description": "a raise waits for approval"}},
)
async def change_decision_class_autonomy(
    dw_id: UUID,
    key: str,
    body: AutonomyRequest,
    response: Response,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: AutonomyIdempotency,
) -> AutonomyChangeView:
    """Lower at once (R8.1), or open a raise for a second person (R8.2): 202."""
    service = _autonomy(container)
    view = await idempotency.once(
        status=200,
        run=lambda effect: _changed(service.change(context, dw_id, key, body.level, effect=effect)),
        reread=lambda found: _reread_change(
            _service(container), context, dw_id, key, body.level, found
        ),
    )
    response.status_code = 202 if view.outcome == "raise_requested" else 200
    return await idempotency.record(view, status_code=response.status_code)
