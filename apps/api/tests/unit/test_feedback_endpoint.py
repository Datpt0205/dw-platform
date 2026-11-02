"""The feedback routes (spec 003 US5): anyone may POST, only the inbox scope may GET.

The UoW/repository and the screenshot storage are faked; the route's own rules
run for real - the limits on screenshots, objects-before-rows with cleanup on
failure, the open submit, the gated inbox and the gated screenshot read.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.errors import status_for
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.errors import ErrorCode, InfrastructureError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.feedback_dto import MAX_FEEDBACK_IMAGE_BYTES, MAX_FEEDBACK_IMAGES
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.domain.feedback import Feedback, FeedbackAttachment

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()
INBOX_SCOPE = "platform.members.read"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeMembershipLookup:
    def __init__(self, scopes: frozenset[str]) -> None:
        self._scopes = scopes

    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if tenant_id != TENANT or workspace_id != WORKSPACE:
            return None
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=PRINCIPAL,
            roles=frozenset({"sales"}),
            scopes=self._scopes,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


class FakeFeedbackRepo:
    def __init__(self, items: list[Feedback] | None = None) -> None:
        self.added: list[dict[str, object]] = []
        self.attachments: list[dict[str, object]] = []
        self.items = items or []

    async def add(self, **kw: object) -> None:
        self.added.append(kw)

    async def add_attachment(self, **kw: object) -> None:
        self.attachments.append(kw)

    async def list_page(self, request: PageRequest) -> Page[Feedback]:
        return build_page(
            self.items,
            request=request,
            position_of=lambda item: CursorPosition(sort_value=item.created_at, tiebreaker=item.id),
        )

    async def get_attachment(
        self, feedback_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> FeedbackAttachment | None:
        for item in self.items:
            for attachment in item.attachments:
                if item.id == feedback_id and attachment.id == attachment_id:
                    return attachment
        return None


class FakeStorage:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []
        self._fail_after = fail_after

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self._fail_after is not None and len(self.objects) >= self._fail_after:
            raise InfrastructureError("bucket is unreachable")
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


class FakeUow:
    def __init__(self, repo: FakeFeedbackRepo) -> None:
        self.feedback = repo
        self.committed = False

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class FakeUowFactory:
    def __init__(self, repo: FakeFeedbackRepo) -> None:
        self._repo = repo

    def __call__(self, context: object) -> FakeUow:
        return FakeUow(self._repo)


def make_container(
    repo: FakeFeedbackRepo, scopes: frozenset[str], storage: FakeStorage | None = None
) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup(scopes)),
        identity_bootstrap=None,
        uow_factory=FakeUowFactory(repo),
        authorization=ScopeAuthorizationService(),
        grant_membership=None,
        revoke_membership=None,
        feedback_storage=storage,
    )


def headers() -> dict[str, str]:
    token = DevTokenVerifier(SECRET).issue("dev|member", email="member@fpt.com")
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }


async def _request(container: ApiContainer, method: str, path: str, **kw: object) -> httpx.Response:
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers(), **kw)


def _images(
    count: int, *, size: int = len(PNG), mime: str = "image/png"
) -> list[tuple[str, tuple[str, bytes, str]]]:
    data = PNG[:size] if size <= len(PNG) else PNG + b"0" * (size - len(PNG))
    return [("images", (f"shot-{index}.png", data, mime)) for index in range(count)]


FORM = {"module": "Leads", "message": "Nút Convert biến mất.", "page_path": "/sales/leads/1"}
VALIDATION = status_for(ErrorCode.VALIDATION_FAILED)


async def test_a_member_submits_text_and_two_screenshots() -> None:
    repo, storage = FakeFeedbackRepo(), FakeStorage()
    response = await _request(
        make_container(repo, frozenset(), storage),
        "POST",
        "/api/v1/feedback",
        data={**FORM, "suggestion": "Giữ nút lại."},
        files=_images(2),
    )

    assert response.status_code == 201
    assert len(repo.added) == 1
    assert repo.added[0]["author_id"] == PRINCIPAL
    assert repo.added[0]["tenant_id"] == TENANT
    assert repo.added[0]["module"] == "Leads"
    assert repo.added[0]["suggestion"] == "Giữ nút lại."
    assert repo.added[0]["page_path"] == "/sales/leads/1"
    assert len(repo.attachments) == 2 == len(storage.objects)
    # Every object key names the tenant and workspace (cache-key law).
    for key in storage.objects:
        assert str(TENANT) in key and str(WORKSPACE) in key


async def test_text_only_needs_no_storage() -> None:
    repo = FakeFeedbackRepo()
    response = await _request(
        make_container(repo, frozenset(), storage=None), "POST", "/api/v1/feedback", data=FORM
    )
    assert response.status_code == 201
    assert repo.attachments == []


async def test_a_missing_description_is_refused() -> None:
    repo = FakeFeedbackRepo()
    response = await _request(
        make_container(repo, frozenset(), FakeStorage()),
        "POST",
        "/api/v1/feedback",
        data={"module": "Leads"},
    )
    assert response.status_code == 422
    assert repo.added == []


async def test_too_many_screenshots_are_refused_before_anything_is_stored() -> None:
    repo, storage = FakeFeedbackRepo(), FakeStorage()
    response = await _request(
        make_container(repo, frozenset(), storage),
        "POST",
        "/api/v1/feedback",
        data=FORM,
        files=_images(MAX_FEEDBACK_IMAGES + 1),
    )
    assert response.status_code == VALIDATION
    assert str(MAX_FEEDBACK_IMAGES) in response.json()["message"]
    assert storage.objects == {} and repo.added == []


async def test_an_oversized_screenshot_is_refused_and_names_the_limit() -> None:
    repo, storage = FakeFeedbackRepo(), FakeStorage()
    response = await _request(
        make_container(repo, frozenset(), storage),
        "POST",
        "/api/v1/feedback",
        data=FORM,
        files=_images(1, size=MAX_FEEDBACK_IMAGE_BYTES + 1),
    )
    assert response.status_code == VALIDATION
    assert "10 MB" in response.json()["message"]
    assert storage.objects == {} and repo.added == []


async def test_a_non_image_is_refused() -> None:
    repo, storage = FakeFeedbackRepo(), FakeStorage()
    response = await _request(
        make_container(repo, frozenset(), storage),
        "POST",
        "/api/v1/feedback",
        data=FORM,
        files=[("images", ("log.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    assert response.status_code == VALIDATION
    assert storage.objects == {} and repo.added == []


async def test_a_storage_failure_stores_no_row_and_cleans_up() -> None:
    repo, storage = FakeFeedbackRepo(), FakeStorage(fail_after=1)
    response = await _request(
        make_container(repo, frozenset(), storage),
        "POST",
        "/api/v1/feedback",
        data=FORM,
        files=_images(2),
    )
    assert response.status_code == status_for(InfrastructureError.code)
    assert repo.added == [] and repo.attachments == []
    # The one object that did land was removed again.
    assert len(storage.deleted) == 1 and storage.objects == {}


async def test_inbox_is_denied_without_the_scope() -> None:
    repo = FakeFeedbackRepo()
    response = await _request(make_container(repo, frozenset()), "GET", "/api/v1/feedback")
    assert response.status_code == 403


def _item(attachments: tuple[FeedbackAttachment, ...] = ()) -> Feedback:
    return Feedback(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        author_id=UserId(PRINCIPAL),
        author_name="Voice Of Customer",
        category="bug",
        message="Nút Convert biến mất.",
        created_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
        module="Leads",
        page_path="/sales/leads/1",
        suggestion="Giữ nút lại.",
        attachments=attachments,
    )


async def test_admin_reads_the_inbox_with_screenshots_listed() -> None:
    attachment = FeedbackAttachment(
        id=uuid.uuid4(),
        feedback_id=uuid.uuid4(),
        object_key="feedback/x",
        content_type="image/png",
        size_bytes=len(PNG),
        created_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
    )
    repo = FakeFeedbackRepo([_item((attachment,))])
    response = await _request(
        make_container(repo, frozenset({INBOX_SCOPE})), "GET", "/api/v1/feedback"
    )
    assert response.status_code == 200
    body = response.json()["items"]
    assert body[0]["module"] == "Leads"
    assert body[0]["suggestion"] == "Giữ nút lại."
    assert body[0]["attachments"] == [
        {"id": str(attachment.id), "content_type": "image/png", "size_bytes": len(PNG)}
    ]


async def test_a_screenshot_is_read_with_the_inbox_scope_and_hidden_without() -> None:
    item = _item()
    attachment = FeedbackAttachment(
        id=uuid.uuid4(),
        feedback_id=item.id,
        object_key="feedback/one",
        content_type="image/png",
        size_bytes=len(PNG),
        created_at=item.created_at,
    )
    item = replace(item, attachments=(attachment,))
    storage = FakeStorage()
    storage.objects["feedback/one"] = (PNG, "image/png")
    repo = FakeFeedbackRepo([item])
    path = f"/api/v1/feedback/{item.id}/attachments/{attachment.id}"

    denied = await _request(make_container(repo, frozenset(), storage), "GET", path)
    assert denied.status_code == 403

    allowed = await _request(make_container(repo, frozenset({INBOX_SCOPE}), storage), "GET", path)
    assert allowed.status_code == 200
    assert allowed.headers["content-type"].startswith("image/png")
    assert allowed.content == PNG

    # An id from another tenant (RLS hides it) reads as not found, not as 403.
    missing = await _request(
        make_container(repo, frozenset({INBOX_SCOPE}), storage),
        "GET",
        f"/api/v1/feedback/{uuid.uuid4()}/attachments/{uuid.uuid4()}",
    )
    assert missing.status_code == 404
