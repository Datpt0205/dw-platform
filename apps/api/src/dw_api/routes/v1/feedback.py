"""Member feedback: /api/v1/feedback.

Anyone signed in with a workspace may POST a bug report - which module, what
went wrong, what they would do about it, and up to five screenshots (spec 003
US5) - as one multipart request, so a feedback either lands whole or not at
all. Only admins (the ``platform.members.read`` scope - the people who run the
org) may GET the inbox or a screenshot. Everything runs inside the tenant-scoped
UoW, so RLS keeps feedback within its tenant; the screenshot bytes are read
back through the API on purpose (no presigned URL): object storage is not
reachable from the browser here, and the scope check then runs on every read.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from pydantic import BaseModel

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.listing import RequireListPage
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import DomainError, InfrastructureError, NotFoundError
from dw_kernel.pagination import Page
from dw_platform.application.access_context import AccessContext
from dw_platform.application.feedback_dto import (
    FEEDBACK_IMAGE_MIMES,
    MAX_FEEDBACK_IMAGE_BYTES,
    MAX_FEEDBACK_IMAGES,
    attachment_key,
)
from dw_platform.application.ports import FeedbackAttachmentStoragePort

# The admin inbox is for the org's admins - the same people who manage members.
# Reusing that scope avoids a second roles catalog to keep in sync.
_INBOX_SCOPE = "platform.members.read"

# The new form is a bug report; the column predates the form and stays.
_CATEGORY = "bug"

_MODULE_MAX = 128
_TEXT_MAX = 4000
_PATH_MAX = 512

router = APIRouter(prefix="/feedback", tags=["feedback"])

ModuleForm = Annotated[str, Form(min_length=1, max_length=_MODULE_MAX)]
MessageForm = Annotated[str, Form(min_length=1, max_length=_TEXT_MAX)]
SuggestionForm = Annotated[str | None, Form(max_length=_TEXT_MAX)]
PagePathForm = Annotated[str | None, Form(max_length=_PATH_MAX)]
ImagesUpload = Annotated[list[UploadFile], File()]


class FeedbackAttachmentView(BaseModel):
    id: str
    content_type: str
    size_bytes: int


class FeedbackView(BaseModel):
    id: str
    author_name: str
    category: str
    message: str
    created_at: datetime
    module: str | None = None
    suggestion: str | None = None
    page_path: str | None = None
    attachments: list[FeedbackAttachmentView] = []


async def _read_images(images: list[UploadFile]) -> list[tuple[bytes, str]]:
    """Validate every screenshot before anything is stored."""
    if len(images) > MAX_FEEDBACK_IMAGES:
        raise DomainError(
            f"tối đa {MAX_FEEDBACK_IMAGES} ảnh cho một phản hồi",
            details={"max_images": MAX_FEEDBACK_IMAGES, "got": len(images)},
        )
    read: list[tuple[bytes, str]] = []
    for image in images:
        mime = image.content_type or ""
        if mime not in FEEDBACK_IMAGE_MIMES:
            raise DomainError(
                "chỉ nhận ảnh PNG, JPEG, GIF hoặc WebP",
                details={"filename": image.filename, "mime": mime},
            )
        # limit+1: enough to prove the file is too big without buffering more.
        data = await image.read(MAX_FEEDBACK_IMAGE_BYTES + 1)
        if len(data) > MAX_FEEDBACK_IMAGE_BYTES:
            raise DomainError(
                f"mỗi ảnh tối đa {MAX_FEEDBACK_IMAGE_BYTES // (1024 * 1024)} MB",
                details={"filename": image.filename, "max_bytes": MAX_FEEDBACK_IMAGE_BYTES},
            )
        if not data:
            raise DomainError("ảnh rỗng", details={"filename": image.filename})
        read.append((data, mime))
    return read


@dataclass(frozen=True)
class _Stored:
    attachment_id: uuid.UUID
    key: str
    content_type: str
    size_bytes: int


async def _store_all(
    storage: FeedbackAttachmentStoragePort,
    files: list[tuple[bytes, str]],
    *,
    context: AccessContext,
    feedback_id: uuid.UUID,
) -> list[_Stored]:
    """Objects first, rows second: a row without its bytes is not
    reconcilable, a leftover object is. On any failure what was already stored
    is removed best-effort and nothing reaches the database."""
    stored: list[_Stored] = []
    try:
        for data, mime in files:
            attachment_id = uuid.uuid4()
            key = attachment_key(
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                feedback_id=feedback_id,
                attachment_id=attachment_id,
            )
            await storage.put(key, data, mime)
            stored.append(_Stored(attachment_id, key, mime, len(data)))
    except InfrastructureError:
        for item in stored:
            with contextlib.suppress(InfrastructureError):
                await storage.delete(item.key)
        raise
    return stored


@router.post("", status_code=201)
async def submit_feedback(
    context: RequireAccessContext,
    container: RequireContainer,
    module: ModuleForm,
    message: MessageForm,
    suggestion: SuggestionForm = None,
    page_path: PagePathForm = None,
    images: ImagesUpload = [],  # noqa: B006 - FastAPI reads the default as "no files"
) -> None:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    files = await _read_images(images)

    feedback_id = uuid.uuid4()
    stored: list[_Stored] = []
    if files:
        if container.feedback_storage is None:
            raise InfrastructureError("attachment storage is not configured")
        stored = await _store_all(
            container.feedback_storage, files, context=context, feedback_id=feedback_id
        )

    async with container.uow_factory(context) as uow:
        await uow.feedback.add(
            feedback_id=feedback_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            author_id=context.principal_id,
            category=_CATEGORY,
            message=message,
            module=module,
            page_path=page_path,
            suggestion=suggestion or None,
        )
        for item in stored:
            await uow.feedback.add_attachment(
                attachment_id=item.attachment_id,
                feedback_id=feedback_id,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                object_key=item.key,
                content_type=item.content_type,
                size_bytes=item.size_bytes,
            )
        await uow.commit()


@router.get("", response_model=Page[FeedbackView])
async def list_feedback(
    context: RequireAccessContext,
    container: RequireContainer,
    page: RequireListPage,
) -> Page[FeedbackView]:
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context, action=_INBOX_SCOPE, resource_type="feedback"
    )
    request = page.request(context, key="feedback.inbox", filters={"tenant": context.tenant_id})
    async with container.uow_factory(context) as uow:
        inbox = await uow.feedback.list_page(request)
    return inbox.map_items(
        lambda item: FeedbackView(
            id=str(item.id),
            author_name=item.author_name,
            category=item.category,
            message=item.message,
            created_at=item.created_at,
            module=item.module,
            suggestion=item.suggestion,
            page_path=item.page_path,
            attachments=[
                FeedbackAttachmentView(
                    id=str(attachment.id),
                    content_type=attachment.content_type,
                    size_bytes=attachment.size_bytes,
                )
                for attachment in item.attachments
            ],
        )
    )


@router.get("/{feedback_id}/attachments/{attachment_id}")
async def read_attachment(
    feedback_id: uuid.UUID,
    attachment_id: uuid.UUID,
    context: RequireAccessContext,
    container: RequireContainer,
) -> Response:
    """The screenshot bytes, for the inbox. Same scope as the inbox itself."""
    if container.uow_factory is None:
        raise InfrastructureError("database is not configured")
    await container.authorization.require(
        context=context, action=_INBOX_SCOPE, resource_type="feedback"
    )
    async with container.uow_factory(context) as uow:
        attachment = await uow.feedback.get_attachment(feedback_id, attachment_id)
    # RLS already hid another tenant's row; an unknown id reads the same way.
    if attachment is None:
        raise NotFoundError("attachment not found", details={"attachment_id": str(attachment_id)})
    if container.feedback_storage is None:
        raise InfrastructureError("attachment storage is not configured")
    data = await container.feedback_storage.get(attachment.object_key)
    return Response(content=data, media_type=attachment.content_type)
