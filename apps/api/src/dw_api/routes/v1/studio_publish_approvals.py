"""`GET /api/v1/studio/publish-approvals/{approval_id}/candidate`: the
candidate a pending publish request asks about, for the person who may decide
it (agent-lifecycle R5.11, R5.12; ADR-0120 decision 2; V4.23).

The sealed document of the version, the version it was compared with at its
submit and what changed against it, each change a JSON pointer with its
`op`, `before` and `after`; an array is one value at its pointer. Anyone who
may not decide the request (its requester, an author, someone without the
stamp, `platform_admin` without it), a request already decided, another kind
of request or another company's is a 404, as if it did not exist, with
nothing audited. Ticket 07 adds what the review screen reads (R5.13-R5.15).
Mounted inside the Studio group (`dw_api.main.mount_studio`).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from dw_api.dependencies.auth import RequireStudioAccess
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_studio.lifecycle.application.review import Candidate, CandidateReader

router = APIRouter(prefix="/publish-approvals")


class ChangeView(BaseModel):
    path: str = Field(description="JSON pointer (RFC 6901) of the value that changed.")
    op: Literal["add", "remove", "replace"]
    before: Any = Field(default=None, description="The compared version's value; null on `add`.")
    after: Any = Field(default=None, description="The candidate's value; null on `remove`.")


class CandidateView(BaseModel):
    approval_id: uuid.UUID
    version_id: uuid.UUID
    artifact_id: uuid.UUID
    kind: str
    version_no: int
    definition_hash: str | None
    document: dict[str, Any]
    live_version_id: uuid.UUID | None = Field(
        description=(
            "The version the candidate was compared with when it was submitted;"
            " null when there was none."
        )
    )
    changes: list[ChangeView] = Field(
        description=(
            "What the candidate changes against that version; every field an `add`"
            " when there is none."
        )
    )


def _view(found: Candidate) -> CandidateView:
    return CandidateView(
        approval_id=found.approval_id,
        version_id=found.version_id,
        artifact_id=found.artifact_id,
        kind=found.kind,
        version_no=found.version_no or 0,
        definition_hash=found.definition_hash,
        document=dict(found.document),
        live_version_id=found.live_version_id,
        changes=[
            ChangeView(path=c.path, op=c.op, before=c.before, after=c.after) for c in found.changes
        ],
    )


@router.get(
    "/{approval_id}/candidate",
    response_model=CandidateView,
    name="read_publish_candidate",
    summary="The candidate of a pending publish request, for the person who may decide it",
)
async def read_candidate(
    approval_id: uuid.UUID,
    context: RequireStudioAccess,
    container: RequireContainer,
) -> CandidateView:
    if container.studio is None:
        raise InfrastructureError("Studio is not configured")
    reader: CandidateReader = container.studio.candidates
    return _view(await reader.read(context, container.authorization, approval_id))
