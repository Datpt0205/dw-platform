"""`/api/v1/studio/{segment}/{artifact_id}/versions/{version_id}/...`: submit,
withdraw and retire a version (agent-lifecycle R2.1, R2.4-R2.6, R2.12, R2.13,
R7.9; the spec's "API").

One route per segment of `SUBMIT_SEGMENTS`, each naming one kind: an artifact
of another kind under that segment is a 404, as one that does not exist.
`agents` and `workflows`, and from ticket 04 `objects` and `data-sources`,
the branch of a kind without a quality gate; retire only under
`RETIRE_SEGMENTS`. Mounted inside the Studio group (`dw_api.main.mount_studio`).
Each takes an optional `Idempotency-Key` (ADR-0108 decision 4); a submit
requires `If-Match`, the draft's ETag (428 without it, before any write), and
answers 202 with the required bindings that have no approved value yet
(`binding_unset`, R2.11).

No `from __future__ import annotations`: the routes are defined inside
`_mount`, and FastAPI resolves a string annotation against the module's
globals, where each segment's idempotency dependency is not.
"""

import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import Field

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.conditions import RequireIfMatch
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_api.routes.v1.studio_artifacts import VersionView, version_view
from dw_kernel.errors import InfrastructureError
from dw_studio.lifecycle.application.service import (
    RETIRE_SEGMENTS,
    LifecycleService,
    Submitted,
)


class SubmitView(VersionView):
    """A submitted version (R2.8-R2.11): `live` on the tighten-only branch,
    otherwise `evaluating` or `awaiting_approval`."""

    binding_unset: list[str] = Field(
        description=(
            "Required bindings with no approved value yet, by name; empty when"
            " every one has one. Publishing waits for them (R2.11, R5.10)."
        )
    )


def submit_view(submitted: Submitted) -> SubmitView:
    return SubmitView(
        **version_view(submitted.version).model_dump(),
        binding_unset=list(submitted.binding_unset),
    )


def _service(container: Any) -> LifecycleService:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    service: LifecycleService = container.studio.lifecycle
    return service


def _artifact_id(check: CheckInput) -> uuid.UUID | None:
    try:
        return uuid.UUID(check.request.path_params["artifact_id"])
    except (KeyError, ValueError):
        return None


def _kind_of(check: CheckInput) -> str | None:
    """The kind the request's segment names, from the composition root's map."""
    studio = check.container.studio
    segment = check.request.url.path.partition("/studio/")[2].split("/", 1)[0]
    return None if studio is None else studio.segments.get(segment)


async def _may_submit(check: CheckInput) -> None:
    """The service's own question, before a key row is read (app-standards R2.30)."""
    artifact_id, kind = _artifact_id(check), _kind_of(check)
    if artifact_id is not None and kind is not None:
        await _service(check.container).check(check.context, kind, artifact_id)


async def _may_retire(check: CheckInput) -> None:
    artifact_id, kind = _artifact_id(check), _kind_of(check)
    if artifact_id is not None and kind is not None:
        await _service(check.container).check(check.context, kind, artifact_id, retire=True)


def _mount(router: APIRouter, segment: str, kind: str) -> None:
    base = f"/{segment}/{{artifact_id}}/versions/{{version_id}}"

    submit_idempotency = Annotated[
        IdempotentOperation,
        idempotent(_may_submit, operation=f"POST /studio{base}/submit"),
    ]
    withdraw_idempotency = Annotated[
        IdempotentOperation,
        idempotent(_may_submit, operation=f"POST /studio{base}/withdraw"),
    ]
    retire_idempotency = Annotated[
        IdempotentOperation,
        idempotent(_may_retire, operation=f"POST /studio{base}/retire"),
    ]

    async def submit(
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        context: RequireStudioAccess,
        container: RequireContainer,
        # The key first: a retry meets its effect before a version is compared.
        idempotency: submit_idempotency,
        expected: RequireIfMatch,
    ) -> SubmitView:
        service = _service(container)

        async def run(effect: Any) -> SubmitView:
            return submit_view(
                await service.submit(context, kind, artifact_id, version_id, expected, effect)
            )

        async def reread(_id: str) -> SubmitView:
            return submit_view(await service.submitted(context, kind, artifact_id, version_id))

        view = await idempotency.once(status=202, run=run, reread=reread)
        result: SubmitView = await idempotency.record(view, status_code=202)
        return result

    async def withdraw(
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        context: RequireStudioAccess,
        container: RequireContainer,
        idempotency: withdraw_idempotency,
    ) -> VersionView:
        service = _service(container)

        async def run(effect: Any) -> VersionView:
            return version_view(
                await service.withdraw(context, kind, artifact_id, version_id, effect)
            )

        async def reread(_id: str) -> VersionView:
            return version_view(await service.version(context, kind, artifact_id, version_id))

        view = await idempotency.once(status=200, run=run, reread=reread)
        result: VersionView = await idempotency.record(view, status_code=200)
        return result

    async def retire(
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        context: RequireStudioAccess,
        container: RequireContainer,
        idempotency: retire_idempotency,
    ) -> VersionView:
        service = _service(container)

        async def run(effect: Any) -> VersionView:
            return version_view(
                await service.retire(context, kind, artifact_id, version_id, effect)
            )

        async def reread(_id: str) -> VersionView:
            return version_view(await service.version(context, kind, artifact_id, version_id))

        view = await idempotency.once(status=200, run=run, reread=reread)
        result: VersionView = await idempotency.record(view, status_code=200)
        return result

    name = segment.replace("-", "_")
    router.add_api_route(
        f"{base}/submit",
        submit,
        methods=["POST"],
        response_model=SubmitView,
        status_code=202,
        name=f"submit_{name}_version",
        summary=f"Submit a {kind} draft: sealed, checked, on to its gate or its approval",
    )
    router.add_api_route(
        f"{base}/withdraw",
        withdraw,
        methods=["POST"],
        response_model=VersionView,
        name=f"withdraw_{name}_version",
        summary=f"Withdraw a {kind} candidate back to its draft",
    )
    if segment not in RETIRE_SEGMENTS:
        return
    router.add_api_route(
        f"{base}/retire",
        retire,
        methods=["POST"],
        response_model=VersionView,
        name=f"retire_{name}_version",
        summary=f"Retire a live {kind} version",
    )


def lifecycle_router(segments: Mapping[str, str]) -> APIRouter:
    """The routes of each segment the composition root names, in its order."""
    router = APIRouter()
    for segment, kind in segments.items():
        _mount(router, segment, kind)
    return router
