"""`/api/v1/studio/artifacts`: the versioned envelope every Studio kind shares
(tenant-config R2, R3; the spec's "API").

Mounted only inside the Studio group (`dw_api.main.mount_studio`), behind its
gate and its dependency, so every route here has a verified identity and a
body of at most 1 MiB before it runs. The artifact and its draft are R3
resources of app-standards (ADR-0108 decision 3): each carries `version`, its
`ETag` is that version, and every write requires `If-Match`. The two creates
take an optional `Idempotency-Key` (ADR-0108 decision 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.conditions import MergePatch, RequireIfMatch
from dw_api.dependencies.idempotency import CheckInput, IdempotentOperation, idempotent
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.http_conditions import etag_of
from dw_kernel.pagination import Page
from dw_studio.core.application.ports import ArtifactRow, VersionRow
from dw_studio.core.application.service import ArtifactService, DependentGroup, Dependents

router = APIRouter(prefix="/artifacts")

_BASE = "/api/v1/studio/artifacts"


def _service(container: Any) -> ArtifactService:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    service: ArtifactService = container.studio.artifacts
    return service


class ArtifactView(BaseModel):
    id: uuid.UUID
    kind: str
    api_name: str
    owning_workspace_id: uuid.UUID
    labels: list[str]
    last_version_no: int
    version: int = Field(description="The artifact's ETag; `If-Match` of its writes.")
    created_at: datetime
    updated_at: datetime
    display_stage: str | None = Field(
        description=(
            "The stage shown for the artifact, computed by `studio.artifact_display_stage`:"
            " `killed`, `live`, `awaiting_approval`, `evaluating`, `draft` or `retired`,"
            " first that holds."
        )
    )


class ArtifactDraftView(BaseModel):
    artifact_id: uuid.UUID
    id: uuid.UUID
    document_schema: str
    document: dict[str, Any]
    version: int = Field(description="The draft's ETag; `If-Match` of a save and a submit.")
    based_on_version_id: uuid.UUID | None


class DraftWarning(BaseModel):
    pointer: str = Field(description="Where in the document, a JSON pointer (RFC 6901).")
    code: str
    detail: str


class SavedDraftView(ArtifactDraftView):
    warnings: list[DraftWarning] = Field(
        description=(
            "What the kind's check finds in the saved draft. A warning never blocks a save;"
            " the same problems refuse a submit."
        )
    )


class VersionView(BaseModel):
    id: uuid.UUID
    version_no: int
    stage: str
    document_schema: str
    document: dict[str, Any]
    content_hash: str | None
    definition_hash: str | None
    based_on_version_id: uuid.UUID | None
    change_note: str | None


class VersionList(BaseModel):
    items: list[VersionView]


class DependentView(BaseModel):
    artifact_id: uuid.UUID
    kind: str
    api_name: str


class DependentGroupView(BaseModel):
    items: list[DependentView]
    hidden: int = Field(description="Dependents the caller may not read, counted only.")


class DependentsView(BaseModel):
    live: DependentGroupView
    candidate: DependentGroupView


class ReferenceView(BaseModel):
    to_kind: str
    to_key: str
    usage: str
    path: str


class ReferenceList(BaseModel):
    items: list[ReferenceView]


class NewArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    api_name: str
    labels: list[str] = []
    document: dict[str, Any] = {}


class ArtifactDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: dict[str, Any]


def _artifact(row: ArtifactRow) -> ArtifactView:
    return ArtifactView(
        id=row.id,
        kind=row.kind,
        api_name=row.api_name,
        owning_workspace_id=row.owning_workspace_id,
        labels=list(row.labels),
        last_version_no=row.last_version_no,
        version=row.row_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        display_stage=row.display_stage,
    )


def _draft(row: VersionRow) -> ArtifactDraftView:
    return ArtifactDraftView(
        artifact_id=row.artifact_id,
        id=row.id,
        document_schema=row.document_schema,
        document=dict(row.document),
        version=row.row_version,
        based_on_version_id=row.based_on_version_id,
    )


def version_view(row: VersionRow) -> VersionView:
    return VersionView(
        id=row.id,
        version_no=row.version_no or 0,
        stage=row.stage.value,
        document_schema=row.document_schema,
        document=dict(row.document),
        content_hash=row.content_hash,
        definition_hash=row.definition_hash,
        based_on_version_id=row.based_on_version_id,
        change_note=row.change_note,
    )


def _group(group: DependentGroup) -> DependentGroupView:
    return DependentGroupView(
        items=[
            DependentView(artifact_id=d.artifact_id, kind=d.kind, api_name=d.api_name)
            for d in group.items
        ],
        hidden=group.hidden,
    )


async def _may_create(check: CheckInput) -> None:
    """The create's own check, before a key row is read (app-standards R2.30)."""
    try:
        kind = (await check.request.json()).get("kind")
    except (ValueError, AttributeError):
        return  # the route refuses the body itself
    if isinstance(kind, str):
        await _service(check.container).check_create(check.context, kind)


async def _may_write(check: CheckInput) -> None:
    try:
        artifact_id = uuid.UUID(check.request.path_params["artifact_id"])
    except (KeyError, ValueError):
        return
    await _service(check.container).check_write(check.context, artifact_id)


CreateIdempotency = Annotated[
    IdempotentOperation, idempotent(_may_create, operation="POST /studio/artifacts")
]
DraftIdempotency = Annotated[
    IdempotentOperation,
    idempotent(_may_write, operation="POST /studio/artifacts/{artifact_id}/draft"),
]


@router.post("", response_model=ArtifactView, status_code=201)
async def create_artifact(
    body: NewArtifact,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    idempotency: CreateIdempotency,
) -> ArtifactView:
    service = _service(container)

    async def run(effect: Any) -> ArtifactView:
        row, _draft_row = await service.create(
            context,
            kind=body.kind,
            api_name=body.api_name,
            labels=body.labels,
            document=body.document,
            effect=effect,
        )
        return _artifact(row)

    async def reread(id_: str) -> ArtifactView:
        return _artifact(await service.get(context, uuid.UUID(id_)))

    view = await idempotency.once(status=201, run=run, reread=reread)
    headers = {"ETag": etag_of(view.version), "Location": f"{_BASE}/{view.id}"}
    response.headers.update(headers)
    result: ArtifactView = await idempotency.record(view, status_code=201, headers=headers)
    return result


@router.get("", response_model=Page[ArtifactView])
async def list_artifacts(
    context: RequireStudioAccess,
    container: RequireContainer,
    page: RequireListPage,
    kind: str | None = Query(default=None, description="Only this kind."),
    label: str | None = Query(default=None, description="Only artifacts carrying this label."),
) -> Page[ArtifactView]:
    request = page.request(
        context,
        key="studio.artifacts",
        filters={"kind": kind, "label": label},
        params={"kind": kind, "label": label},
    )
    listed = await _service(container).page(context, request, kind=kind, label=label)
    return listed.map_items(_artifact)


@router.get("/{artifact_id}", response_model=ArtifactView)
async def read_artifact(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
) -> ArtifactView:
    view = _artifact(await _service(container).get(context, artifact_id))
    response.headers["ETag"] = etag_of(view.version)
    return view


@router.patch("/{artifact_id}", response_model=ArtifactView)
async def update_artifact(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    expected: RequireIfMatch,
    patch: MergePatch,
) -> ArtifactView:
    row = await _service(container).update(context, artifact_id, expected, patch)
    response.headers["ETag"] = etag_of(row.row_version)
    return _artifact(row)


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    expected: RequireIfMatch,
) -> Response:
    await _service(container).soft_delete(context, artifact_id, expected)
    return Response(status_code=204)


@router.get("/{artifact_id}/draft", response_model=ArtifactDraftView)
async def read_draft(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
) -> ArtifactDraftView:
    view = _draft(await _service(container).get_draft(context, artifact_id))
    response.headers["ETag"] = etag_of(view.version)
    return view


@router.put("/{artifact_id}/draft", response_model=SavedDraftView)
async def save_draft(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    expected: RequireIfMatch,
    body: Annotated[ArtifactDraftBody, Body()],
) -> SavedDraftView:
    saved = await _service(container).save_draft(context, artifact_id, expected, body.document)
    response.headers["ETag"] = etag_of(saved.version.row_version)
    return SavedDraftView(
        **_draft(saved.version).model_dump(),
        warnings=[
            DraftWarning(pointer=w.pointer, code=w.code, detail=w.detail) for w in saved.warnings
        ],
    )


@router.post("/{artifact_id}/draft", response_model=ArtifactDraftView, status_code=201)
async def create_draft(
    artifact_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
    response: Response,
    # The key first: a retry meets its effect before a version is compared.
    idempotency: DraftIdempotency,
    expected: RequireIfMatch,
) -> ArtifactDraftView:
    service = _service(container)

    async def run(effect: Any) -> ArtifactDraftView:
        return _draft(await service.create_draft(context, artifact_id, expected, effect))

    async def reread(_id: str) -> ArtifactDraftView:
        return _draft(await service.get_draft(context, artifact_id))

    view = await idempotency.once(status=201, run=run, reread=reread)
    headers = {"ETag": etag_of(view.version), "Location": f"{_BASE}/{artifact_id}/draft"}
    response.headers.update(headers)
    result: ArtifactDraftView = await idempotency.record(view, status_code=201, headers=headers)
    return result


@router.get("/{artifact_id}/draft/dependencies", response_model=ReferenceList)
async def draft_dependencies(
    artifact_id: uuid.UUID, context: RequireStudioAccess, container: RequireContainer
) -> ReferenceList:
    references = await _service(container).draft_dependencies(context, artifact_id)
    return ReferenceList(
        items=[
            ReferenceView(
                to_kind=r.to_kind.value, to_key=r.to_key, usage=r.usage.value, path=r.path
            )
            for r in references
        ]
    )


@router.get("/{artifact_id}/versions", response_model=VersionList)
async def list_versions(
    artifact_id: uuid.UUID, context: RequireStudioAccess, container: RequireContainer
) -> VersionList:
    versions = await _service(container).versions(context, artifact_id)
    return VersionList(items=[version_view(v) for v in versions])


@router.get("/{artifact_id}/versions/{version_no}", response_model=VersionView)
async def read_version(
    artifact_id: uuid.UUID,
    version_no: int,
    context: RequireStudioAccess,
    container: RequireContainer,
) -> VersionView:
    return version_view(await _service(container).version(context, artifact_id, version_no))


@router.get("/{artifact_id}/dependents", response_model=DependentsView)
async def list_dependents(
    artifact_id: uuid.UUID, context: RequireStudioAccess, container: RequireContainer
) -> DependentsView:
    found: Dependents = await _service(container).dependents(context, artifact_id)
    return DependentsView(live=_group(found.live), candidate=_group(found.candidate))
