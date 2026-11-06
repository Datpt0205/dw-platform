"""Run status + timeline API, and the resume check of a blocked Studio run.

`POST /runs/{run_id}/resume-check` (workflow-engine R6.39, R6.22, R6.23,
R6.25; WE53): `Idempotency-Key` required. A Studio run `blocked`
`incompatible_resume` is checked again (`ResumeCheckService`): 404 for a run
of another company or out of the caller's `runs.read` reach, 403 without
`studio.workflows.resume_check` at its workspace, 409 `run_not_resumable` for
any other run, 409 with the switch's reason under a freeze or a kill, 409
`incompatible_resume` while a check still fails; 200 `queued` with one audit
`run.unblocked`, or 200 `cancelled` past its deadline. Nothing is pinned
again.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError, NotFoundError
from dw_studio.core.application.resume_check import ResumeCheckService
from dw_usage.presentation.views import RunUsageView, run_usage_view


class RunView(BaseModel):
    id: uuid.UUID
    status: str
    worker_id: str
    worker_version: str
    graph_version: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    approval_request_id: uuid.UUID | None
    release_manifest_ref: str | None


class TimelineEvent(BaseModel):
    action: str
    resource_type: str
    resource_id: str
    policy_decision: str | None
    occurred_at: datetime
    details: dict[str, Any]


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunView)
async def get_run(
    run_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> RunView:
    if container.run_store is None:
        raise InfrastructureError("runtime is not configured")
    await container.authorization.require(
        context=context,
        action="runs.read",
        resource_type="worker_run",
        resource_id=str(run_id),
    )
    # Read in the caller's workspace: another workspace's run is a 404.
    record = await container.run_store.get(container.run_context_for(context, run_id), run_id)
    return RunView(
        id=record.id,
        status=record.status.value,
        worker_id=record.worker_id,
        worker_version=record.worker_version,
        graph_version=record.graph_version,
        result=record.result,
        error=record.error,
        approval_request_id=record.approval_request_id,
        release_manifest_ref=record.release_manifest_ref,
    )


@router.get("/{run_id}/usage", response_model=RunUsageView)
async def get_run_usage(
    run_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> RunUsageView:
    """The run's usage records summed by operation, model and cost source
    (usage-and-limits R3.6). The run is read first, in the caller's workspace,
    as `GET /runs/{run_id}` does: another company's run, another workspace's
    and one that does not exist are all a 404; a run that has called no model
    yet is a 200 with a total of zero."""
    if container.run_store is None or container.usage is None:
        raise InfrastructureError("runtime is not configured")
    await container.authorization.require(
        context=context,
        action="runs.read",
        resource_type="worker_run",
        resource_id=str(run_id),
    )
    record = await container.run_store.get(container.run_context_for(context, run_id), run_id)
    return run_usage_view(await container.usage.run_usage(context.tenant_id, record.id))


@router.get("/{run_id}/timeline", response_model=list[TimelineEvent])
async def get_timeline(
    run_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> list[TimelineEvent]:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context,
        action="runs.read",
        resource_type="worker_run",
        resource_id=str(run_id),
    )
    async with container.uow_factory(context) as uow:
        events = await uow.audit.list_for_run(run_id, workspace_id=context.workspace_id)
    return [
        TimelineEvent(
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            policy_decision=e.policy_decision,
            occurred_at=e.occurred_at,
            details=dict(e.details),
        )
        for e in events
    ]


class CancelResult(BaseModel):
    """Whether a run was actually stopped, not whether the request was understood.

    `False` is an ordinary answer: the turn had already finished, or another
    process holds it. A caller pressing Stop twice should get 200 both times —
    the second one describes a thread that is already not running, which is what
    they asked for.
    """

    cancelled: bool


@router.post("/threads/{thread_id}/cancel", response_model=CancelResult)
async def cancel_thread(
    thread_id: uuid.UUID, context: RequireAccessContext, container: RequireContainer
) -> CancelResult:
    """Stop the run in flight on this thread.

    The runner's own `cancel_thread` takes a thread id and nothing else: it
    looks the task up in an in-process dict, which is safe while the only caller
    is a run that started it. Over HTTP the id is whatever the caller typed, so
    ownership is established HERE, against the database under the caller's
    tenant, before the runner is asked to do anything.

    A thread this tenant has never run on is a 404 rather than a 403. "Not
    yours" and "never existed" are the same answer to someone probing ids, and
    the difference between them is exactly what a prober is trying to learn.
    """
    if container.run_store is None or container.runner is None:
        raise InfrastructureError("runtime is not configured")
    await container.authorization.require(
        context=context,
        action="runs.cancel",
        resource_type="worker_run",
        resource_id=str(thread_id),
    )
    if not await container.run_store.thread_belongs_to(
        context.tenant_id, context.workspace_id, thread_id
    ):
        raise NotFoundError("thread not found", details={"thread_id": str(thread_id)})
    return CancelResult(cancelled=await container.runner.cancel_thread(thread_id))


# ---- workflow-engine R6.39: the resume check of a blocked Studio run ------------------


class ResumeCheckView(BaseModel):
    """What the check did: the run queued, or cancelled past its deadline."""

    run_id: uuid.UUID
    status: Literal["queued", "cancelled"]


def _resume_checks(container: Any) -> ResumeCheckService:
    studio = container.studio
    if studio is None or studio.resume_checks is None:
        raise InfrastructureError("Studio runs are not configured")
    checks: ResumeCheckService = studio.resume_checks
    return checks


async def _may_check(check: CheckInput) -> None:
    """The service's own check, on the run the path names, before any key row."""
    run_id = uuid.UUID(check.request.path_params["run_id"])
    await _resume_checks(check.container).authorize(check.context, run_id)


ResumeCheckIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_check, operation="POST /runs/{run_id}/resume-check", required=True),
]


@router.post("/{run_id}/resume-check", response_model=ResumeCheckView)
async def resume_check(
    run_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: ResumeCheckIdempotency,
) -> ResumeCheckView:
    service = _resume_checks(container)

    async def run(effect: Any) -> ResumeCheckView:
        result = await service.check(context, run_id, effect=effect)
        return ResumeCheckView(run_id=result.run_id, status=result.status)

    async def reread(found: str) -> ResumeCheckView:
        record = await service.authorize(context, uuid.UUID(found))
        status: Literal["queued", "cancelled"] = (
            "cancelled" if record.status == "cancelled" else "queued"
        )
        return ResumeCheckView(run_id=record.run_id, status=status)

    view = await idempotency.once(status=200, run=run, reread=reread)
    return await idempotency.record(view)
