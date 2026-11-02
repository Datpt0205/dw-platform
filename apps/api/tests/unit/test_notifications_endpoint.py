"""The inbox routes over the real service with a fake inbox: the shapes, and
that someone else's notification answers as one that never existed.

Who can read which row is the database's decision, covered against a real
one by `dw_platform`'s `test_notifications.py`.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.notifications import Inbox, Notification, NotificationService

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()
MINE = uuid.uuid4()


class FakeMembershipLookup:
    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if tenant_id != TENANT or workspace_id != WORKSPACE:
            return None
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=PRINCIPAL,
            roles=frozenset({"member"}),
            scopes=frozenset(),
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


class FakeInbox:
    def __init__(self) -> None:
        self.read: list[uuid.UUID] = []
        self.all_read_by: list[uuid.UUID] = []

    async def latest(self, context: AccessContext, *, limit: int) -> Inbox:
        return Inbox(
            items=(
                Notification(
                    id=MINE,
                    title="Nhắc NCC cập nhật: PO-2026-007",
                    body="",
                    link="/approvals",
                    created_at=datetime.now(UTC),
                    read_at=None,
                ),
            ),
            unread=1,
        )

    async def mark_read(self, context: AccessContext, notification_id: uuid.UUID) -> bool:
        if notification_id != MINE:
            return False
        self.read.append(notification_id)
        return True

    async def mark_all_read(self, context: AccessContext) -> None:
        self.all_read_by.append(context.principal_id)


def make_container(inbox: FakeInbox) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup()),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=ScopeAuthorizationService(),
        notifications=NotificationService(inbox),
    )


async def _call(container: ApiContainer, method: str, path: str) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue("dev|member", email="member@fpt.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, f"/api/v1/notifications{path}", headers=headers)


async def test_a_member_reads_their_inbox_with_no_scope_at_all() -> None:
    response = await _call(make_container(FakeInbox()), "GET", "")

    assert response.status_code == 200
    body = response.json()
    assert body["unread"] == 1
    assert body["items"][0]["link"] == "/approvals"


async def test_marking_ones_own_read() -> None:
    inbox = FakeInbox()
    response = await _call(make_container(inbox), "POST", f"/{MINE}/read")

    assert response.status_code == 204
    assert inbox.read == [MINE]


async def test_someone_elses_notification_is_not_found() -> None:
    inbox = FakeInbox()
    response = await _call(make_container(inbox), "POST", f"/{uuid.uuid4()}/read")

    assert response.status_code == 404
    assert inbox.read == []


async def test_marking_all_read_is_the_callers_own() -> None:
    inbox = FakeInbox()
    response = await _call(make_container(inbox), "POST", "/read-all")

    assert response.status_code == 204
    assert inbox.all_read_by == [PRINCIPAL]
