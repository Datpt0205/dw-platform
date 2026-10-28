"""The nine operations that take `Idempotency-Key`, over HTTP, against Postgres.

app-standards ticket 02 (R2.16, R2.17, R2.22, R2.23, R2.29, R2.30, R2.33, R2.35,
R2.37, R2.42; APS17, APS20, APS23, APS24, APS32, APS33, APS35, APS37, APS39,
APS42, APS44). The real app, the real container and every SQL adapter; only the
HTTP key store is wrapped, to fail where a process can fail: after the effect
has committed, before the answer is stored.

"No second effect" is counted in `platform.audit_events`: every one of the nine
writes its audit row in the effect's own transaction, so a second effect is a
second row.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.errors import InfrastructureError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.idempotency_store import SqlIdempotencyStore
from dw_platform.adapters.persistence.scope_holders import SqlScopeHolders
from dw_platform.adapters.persistence.support_grants import SqlSupportGrantRepository
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectKey, ExistingEffect, PendingEffect
from dw_platform.application.idempotency import (
    HttpIdempotency,
    RequestFingerprint,
    ReservedKey,
    StoredResponse,
)
from dw_platform.application.membership_admin import GrantMembership, RevokeMembership
from dw_platform.application.support_access import (
    RequestSupportGrant,
    SupportGrantService,
    SupportScopeCatalog,
)
from dw_platform.application.tenant_members import InviteMember, SetMemberships, WorkspaceRoles
from dw_platform.domain.approval import ApprovalRequest

pytestmark = pytest.mark.integration

SECRET = "integration-secret-0123456789abcdef0123"
SET_KEY = "it.read"
SUPPORT_FLAG = "support_access"


# ---------------------------------------------------------------------------
# A world: one company with two workspaces, a second company, and the people.
# ---------------------------------------------------------------------------


@dataclass
class World:
    tenant: uuid.UUID
    ws1: uuid.UUID
    ws2: uuid.UUID
    other_tenant: uuid.UUID
    other_ws: uuid.UUID
    admin_role: str
    plain_role: str
    requester_role: str
    users: dict[str, uuid.UUID] = field(default_factory=dict)


ADMIN_SCOPES = (
    '["platform.members.read", "platform.members.write", "support.grant",'
    ' "approvals.read", "approvals.decide", "x.read"]'
)


async def _role(conn: Any, key: str, scopes: str) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO platform.roles (key, name, scopes) VALUES (:k, :k, CAST(:s AS jsonb))"
        ),
        {"k": key, "s": scopes},
    )


async def new_user(
    migrator: AsyncEngine,
    tenant: uuid.UUID,
    memberships: list[tuple[uuid.UUID, str]],
    *,
    name: str = "Người dùng",
) -> uuid.UUID:
    user = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.users (id, subject, email, display_name)"
                " VALUES (:id, :sub, :email, :name)"
            ),
            {"id": user, "sub": f"it-{user}", "email": f"{user.hex[:12]}@it.test", "name": name},
        )
        for workspace, role in memberships:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys) VALUES (:id, :t, :w, :u, CAST(:r AS jsonb))"
                ),
                {"id": uuid.uuid4(), "t": tenant, "w": workspace, "u": user, "r": f'["{role}"]'},
            )
    return user


async def build_world(migrator: AsyncEngine) -> World:
    tag = uuid.uuid4().hex[:10]
    world = World(
        tenant=uuid.uuid4(),
        ws1=uuid.uuid4(),
        ws2=uuid.uuid4(),
        other_tenant=uuid.uuid4(),
        other_ws=uuid.uuid4(),
        admin_role=f"it_admin_{tag}",
        plain_role=f"it_plain_{tag}",
        requester_role=f"it_requester_{tag}",
    )
    async with migrator.begin() as conn:
        await _role(conn, world.admin_role, ADMIN_SCOPES)
        await _role(conn, world.plain_role, '["x.read"]')
        await _role(conn, world.requester_role, '["support.request", "approvals.read"]')
        for tenant, workspaces in (
            (world.tenant, (world.ws1, world.ws2)),
            (world.other_tenant, (world.other_ws,)),
        ):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tenants (id, slug, name, status)"
                    " VALUES (:id, :slug, :slug, 'active')"
                ),
                {"id": tenant, "slug": f"it-{tenant.hex[:12]}"},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.entitlements (id, tenant_id, plan_id, feature_overrides)"
                    " VALUES (:id, :t, 'professional', CAST(:f AS jsonb))"
                ),
                {"id": uuid.uuid4(), "t": tenant, "f": f'["{SUPPORT_FLAG}"]'},
            )
            for n, workspace in enumerate(workspaces):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                        " VALUES (:id, :t, :slug, :slug)"
                    ),
                    {"id": workspace, "t": tenant, "slug": f"ws{n}"},
                )
    both = [(world.ws1, world.admin_role), (world.ws2, world.admin_role)]
    world.users["a"] = await new_user(migrator, world.tenant, both, name="Quản trị A")
    world.users["b"] = await new_user(migrator, world.tenant, both, name="Quản trị B")
    world.users["plain"] = await new_user(migrator, world.tenant, [(world.ws1, world.plain_role)])
    world.users["requester"] = await new_user(
        migrator, world.tenant, [(world.ws1, world.requester_role)], name="Người yêu cầu"
    )
    world.users["c"] = await new_user(
        migrator, world.other_tenant, [(world.other_ws, world.admin_role)], name="Quản trị C"
    )
    return world


def probe_catalog() -> SupportScopeCatalog:
    catalog = SupportScopeCatalog()
    catalog.register(SET_KEY, "Đọc", frozenset({"x.read"}), {"workspace"})
    catalog.freeze()
    return catalog


# ---------------------------------------------------------------------------
# The harness: the real app, with the HTTP key store wrapped.
# ---------------------------------------------------------------------------


class FlakyStore:
    """The SQL store, failing where a process can: after the effect, before
    the answer is stored (`fail_complete`), and dying before it releases the
    key (`drop_release`)."""

    def __init__(self, inner: SqlIdempotencyStore) -> None:
        self.inner = inner
        self.fail_complete = 0
        self.drop_release = False
        self.reserves = 0

    async def reserve(
        self, context: AccessContext, *, key: str, fingerprint: RequestFingerprint
    ) -> uuid.UUID | ReservedKey:
        self.reserves += 1
        return await self.inner.reserve(context, key=key, fingerprint=fingerprint)

    async def take_over(self, context: AccessContext, **kw: Any) -> uuid.UUID | None:
        return await self.inner.take_over(context, **kw)

    async def complete(
        self, context: AccessContext, *, key: str, token: uuid.UUID, response: StoredResponse
    ) -> None:
        if self.fail_complete:
            self.fail_complete -= 1
            raise InfrastructureError("the store went away after the effect committed")
        await self.inner.complete(context, key=key, token=token, response=response)

    async def release(self, context: AccessContext, *, key: str, token: uuid.UUID) -> None:
        if not self.drop_release:
            await self.inner.release(context, key=key, token=token)


class NoRunner:
    """Every approval here has no run, so nothing resumes."""

    def hosts(self, **_: object) -> bool:
        raise NotImplementedError("not exercised: no approval here has a run")

    async def resume(self, **_: object) -> None:
        raise NotImplementedError("not exercised: no approval here has a run")


@dataclass
class Harness:
    world: World
    container: ApiContainer
    client: httpx.AsyncClient
    migrator: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    store: FlakyStore

    async def send(
        self,
        who: str,
        call: Call,
        key: str | None,
        *,
        workspace: uuid.UUID | None = None,
        tenant: uuid.UUID | None = None,
    ) -> httpx.Response:
        subject = f"it-{self.world.users[who]}"
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(subject)}",
            "X-Tenant-Id": str(tenant or self.world.tenant),
            "X-Workspace-Id": str(workspace or self.world.ws1),
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        return await self.client.request(call.method, call.url, json=call.body, headers=headers)

    def context(self, *scopes: str, who: uuid.UUID | None = None) -> AccessContext:
        return AccessContext(
            tenant_id=self.world.tenant,
            workspace_id=self.world.ws1,
            principal_id=who or uuid.uuid4(),
            roles=frozenset(),
            scopes=frozenset(scopes),
            plan_id="professional",
            feature_flags=frozenset({SUPPORT_FLAG}),
        )

    async def audits(self) -> int:
        async with self.migrator.connect() as conn:
            count = await conn.scalar(
                sa.text("SELECT count(*) FROM platform.audit_events WHERE tenant_id = :t"),
                {"t": self.world.tenant},
            )
        return int(count or 0)

    async def key_rows(self, key: str) -> int:
        async with self.migrator.connect() as conn:
            count = await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.idempotency_keys WHERE idempotency_key = :k"
                ),
                {"k": key},
            )
        return int(count or 0)

    async def backdate(self, key: str) -> None:
        async with self.migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.idempotency_keys"
                    " SET created_at = now() - interval '10 minutes' WHERE idempotency_key = :k"
                ),
                {"k": key},
            )


@pytest.fixture
async def harness(api_db: DatabaseUrls) -> AsyncIterator[Harness]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    assert container.engine is not None and container.uow_factory is not None
    sessions = async_sessionmaker(container.engine, class_=AsyncSession, expire_on_commit=False)
    clock, ids = SystemClock(), Uuid4Generator()
    store = FlakyStore(SqlIdempotencyStore(sessions))
    container.idempotency = HttpIdempotency(store=store, clock=clock)
    container.support_grants = SupportGrantService(
        repo=SqlSupportGrantRepository(sessions),
        member_scopes=SqlScopeHolders(sessions),
        catalog=probe_catalog(),
        clock=clock,
        ids=ids,
    )
    container.approval_flow = ApproveAndResumeService(
        uow_factory=container.uow_factory,
        runner=cast(Any, NoRunner()),
        run_store=cast(Any, None),
        clock=clock,
        id_generator=ids,
    )
    app = create_app(container)
    world = await build_world(migrator)
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://it") as client:
                yield Harness(world, container, client, migrator, sessions, store)
    finally:
        await container.engine.dispose()
        await migrator.dispose()


# ---------------------------------------------------------------------------
# The nine operations, each prepared on resources of its own.
# ---------------------------------------------------------------------------


@dataclass
class Call:
    method: str
    url: str
    body: dict[str, Any] | None
    status: int
    resource: str | None
    # The same effect through its service, with no HTTP in between (R2.22).
    direct: Callable[[AccessContext], Awaitable[object]]
    # Who else in the tenant may perform it (R2.23).
    peer: str = "b"


async def grant(h: Harness) -> Call:
    hire = await new_user(h.migrator, h.world.tenant, [])
    email = f"{hire.hex[:12]}@it.test"
    service = h.container.grant_membership
    assert service is not None
    return Call(
        "POST",
        "/api/v1/admin/members",
        {"email": email, "workspace_id": str(h.world.ws1), "role_keys": [h.world.plain_role]},
        201,
        str(hire),
        lambda context: service.handle(
            context, GrantMembership(email, h.world.ws1, frozenset({h.world.plain_role}))
        ),
    )


async def revoke(h: Harness) -> Call:
    person = await new_user(h.migrator, h.world.tenant, [(h.world.ws1, h.world.plain_role)])
    service = h.container.revoke_membership
    assert service is not None
    return Call(
        "DELETE",
        f"/api/v1/admin/members/{person}?workspace_id={h.world.ws1}",
        None,
        204,
        None,
        lambda context: service.handle(context, RevokeMembership(person, h.world.ws1)),
    )


async def set_memberships(h: Harness) -> Call:
    person = await new_user(h.migrator, h.world.tenant, [(h.world.ws1, h.world.plain_role)])
    service = h.container.tenant_members
    assert service is not None
    rows = [{"workspace_id": str(h.world.ws2), "role_keys": [h.world.plain_role]}]
    return Call(
        "PUT",
        f"/api/v1/admin/members/{person}/memberships",
        {"memberships": rows},
        200,
        str(person),
        lambda context: service.set_memberships(
            context,
            SetMemberships(person, (WorkspaceRoles(h.world.ws2, frozenset({h.world.plain_role})),)),
        ),
    )


async def invite(h: Harness) -> Call:
    email = f"invite-{uuid.uuid4().hex[:10]}@it.test"
    service = h.container.tenant_members
    assert service is not None
    rows = [{"workspace_id": str(h.world.ws1), "role_keys": [h.world.plain_role]}]
    return Call(
        "POST",
        "/api/v1/admin/invitations",
        {"display_name": "Người được mời", "email": email, "memberships": rows},
        201,
        None,
        lambda context: service.invite(
            context,
            InviteMember(
                "Người được mời",
                email,
                (WorkspaceRoles(h.world.ws1, frozenset({h.world.plain_role})),),
            ),
        ),
    )


async def raise_approval(h: Harness) -> uuid.UUID:
    requester = h.context("approvals.read", who=h.world.users["requester"])
    request = ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(h.world.tenant),
        workspace_id=WorkspaceId(h.world.ws1),
        approval_type="it.check",
        requested_by=UserId(h.world.users["requester"]),
        reason="kiểm tra",
        payload={},
    )
    async with SqlPlatformUnitOfWorkFactory(h.sessions)(requester) as uow:
        await uow.approvals.add(request)
        await uow.commit()
    return request.id


async def decide(h: Harness) -> Call:
    approval = await raise_approval(h)
    flow = h.container.approval_flow
    assert flow is not None
    return Call(
        "POST",
        f"/api/v1/approvals/{approval}/decisions",
        {"approve": True, "comment": "đồng ý"},
        200,
        str(approval),
        lambda context: flow.decide(
            approval_id=approval,
            approve=True,
            comment="đồng ý",
            context=context,
            authorization=h.container.authorization,
        ),
    )


def _support() -> RequestSupportGrant:
    return RequestSupportGrant(
        scope_set_key=SET_KEY,
        resource_type="workspace",
        resource_id=None,
        reason="cần hỗ trợ",
        duration_hours=2,
    )


async def request_support(h: Harness) -> Call:
    service = h.container.support_grants
    assert service is not None
    return Call(
        "POST",
        "/api/v1/support/grants",
        {
            "scope_set_key": SET_KEY,
            "resource_type": "workspace",
            "reason": "cần hỗ trợ",
            "duration_hours": 2,
        },
        201,
        None,
        lambda context: service.request(context, _support()),
    )


async def _pending_grant(h: Harness, *, granted: bool) -> uuid.UUID:
    service = h.container.support_grants
    assert service is not None
    who = h.context(
        *(("support.grant", "x.read") if granted else ("support.request",)),
        who=h.world.users["a" if granted else "requester"],
    )
    return (await service.request(who, _support())).grant.id


async def approve_support(h: Harness) -> Call:
    grant_id = await _pending_grant(h, granted=False)
    service = h.container.support_grants
    assert service is not None
    return Call(
        "POST",
        f"/api/v1/support/grants/{grant_id}/approve",
        None,
        200,
        str(grant_id),
        lambda context: service.approve(context, grant_id),
    )


async def reject_support(h: Harness) -> Call:
    grant_id = await _pending_grant(h, granted=False)
    service = h.container.support_grants
    assert service is not None
    return Call(
        "POST",
        f"/api/v1/support/grants/{grant_id}/reject",
        {"reason": "không cần"},
        200,
        str(grant_id),
        lambda context: service.reject(context, grant_id, "không cần"),
    )


async def revoke_support(h: Harness) -> Call:
    grant_id = await _pending_grant(h, granted=True)
    service = h.container.support_grants
    assert service is not None
    return Call(
        "POST",
        f"/api/v1/support/grants/{grant_id}/revoke",
        None,
        200,
        str(grant_id),
        lambda context: service.revoke(context, grant_id),
    )


OPERATIONS: dict[str, Callable[[Harness], Awaitable[Call]]] = {
    "POST /admin/members": grant,
    "DELETE /admin/members/{user_id}": revoke,
    "PUT /admin/members/{user_id}/memberships": set_memberships,
    "POST /admin/invitations": invite,
    "POST /approvals/{approval_id}/decisions": decide,
    "POST /support/grants": request_support,
    "POST /support/grants/{grant_id}/approve": approve_support,
    "POST /support/grants/{grant_id}/reject": reject_support,
    "POST /support/grants/{grant_id}/revoke": revoke_support,
}
each_operation = pytest.mark.parametrize("operation", list(OPERATIONS))


def _resource(response: httpx.Response) -> str | None:
    if response.status_code == 204:
        return None
    body = response.json()
    return str(body.get("user_id") or body.get("id"))


async def _fail_after_the_effect(h: Harness, call: Call, key: str) -> tuple[int, str | None]:
    """The effect commits, the answer is never stored, the key is released (G6)."""
    h.store.fail_complete = 1
    failed = await h.send("a", call, key)
    assert failed.status_code >= 500, failed.text
    return await h.audits(), call.resource


# ---------------------------------------------------------------------------
# R2.16 (APS20): a retry never makes a second effect.
# ---------------------------------------------------------------------------


@each_operation
async def test_a_retry_after_the_key_was_released_answers_with_the_effect_that_exists(
    harness: Harness, operation: str
) -> None:
    call = await OPERATIONS[operation](harness)
    key = f"g6-{uuid.uuid4()}"
    effects, _ = await _fail_after_the_effect(harness, call, key)

    retried = await harness.send("a", call, key)

    assert retried.status_code == call.status, retried.text
    assert await harness.audits() == effects, "the retry made a second effect"
    if call.resource is not None:
        assert _resource(retried) == call.resource


@each_operation
async def test_a_take_over_of_an_abandoned_reservation_answers_with_the_effect(
    harness: Harness, operation: str
) -> None:
    call = await OPERATIONS[operation](harness)
    key = f"stale-{uuid.uuid4()}"
    harness.store.drop_release = True
    effects, _ = await _fail_after_the_effect(harness, call, key)
    harness.store.drop_release = False
    assert await harness.key_rows(key) == 1, "the dead request's reservation is still held"
    await harness.backdate(key)

    retried = await harness.send("a", call, key)

    assert retried.status_code == call.status, retried.text
    assert await harness.audits() == effects


# ---------------------------------------------------------------------------
# R2.23 (APS24): another caller's retry is a conflict, not their effect.
# ---------------------------------------------------------------------------


@each_operation
async def test_another_caller_sending_the_released_key_is_refused(
    harness: Harness, operation: str
) -> None:
    call = await OPERATIONS[operation](harness)
    key = f"peer-{uuid.uuid4()}"
    effects, _ = await _fail_after_the_effect(harness, call, key)

    theirs = await harness.send(call.peer, call, key)

    assert theirs.status_code == 409, theirs.text
    assert theirs.json()["code"] == "idempotency_conflict"
    if call.resource is not None:
        assert call.resource not in theirs.text
    assert await harness.audits() == effects


# ---------------------------------------------------------------------------
# R2.22 (APS23): the service refuses on its own, with no HTTP in front of it.
# ---------------------------------------------------------------------------


@each_operation
async def test_the_service_refuses_a_caller_without_the_right(
    harness: Harness, operation: str
) -> None:
    call = await OPERATIONS[operation](harness)
    before = await harness.audits()

    with pytest.raises((PermissionDeniedError, NotFoundError)) as refused:
        await call.direct(harness.context("x.read"))

    if operation != "POST /approvals/{approval_id}/decisions":
        # A request the caller may neither decide nor raised is one they cannot
        # see (ADR 0004), so `decide` answers 404 for it; every other service
        # says no.
        assert isinstance(refused.value, PermissionDeniedError)
    assert await harness.audits() == before


# ---------------------------------------------------------------------------
# R2.23 (APS35): another workspace is another request.
# ---------------------------------------------------------------------------


async def test_the_same_key_from_another_workspace_is_a_conflict(harness: Harness) -> None:
    call = await grant(harness)
    key = f"ws-{uuid.uuid4()}"
    effects, _ = await _fail_after_the_effect(harness, call, key)

    elsewhere = await harness.send("a", call, key, workspace=harness.world.ws2)

    assert elsewhere.status_code == 409
    assert elsewhere.json()["code"] == "idempotency_conflict"
    assert await harness.audits() == effects


# ---------------------------------------------------------------------------
# R2.17 (APS17): a replay re-checks the route's right.
# ---------------------------------------------------------------------------


async def test_a_caller_who_lost_the_right_gets_403_and_not_the_stored_body(
    harness: Harness,
) -> None:
    call = await grant(harness)
    key = f"lost-{uuid.uuid4()}"
    first = await harness.send("a", call, key)
    assert first.status_code == 201
    async with harness.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.memberships SET role_keys = CAST(:r AS jsonb) WHERE user_id = :u"
            ),
            {"r": f'["{harness.world.plain_role}"]', "u": harness.world.users["a"]},
        )

    again = await harness.send("a", call, key)

    assert again.status_code == 403
    assert again.json()["code"] == "permission_denied"
    assert str(call.resource) not in again.text


# ---------------------------------------------------------------------------
# R2.29 (APS32): the existing effect is read back under current authority.
# ---------------------------------------------------------------------------


async def test_an_effect_no_longer_visible_is_answered_as_absent(harness: Harness) -> None:
    call = await grant(harness)
    key = f"gone-{uuid.uuid4()}"
    await _fail_after_the_effect(harness, call, key)
    async with harness.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.memberships WHERE user_id = :u"),
            {"u": uuid.UUID(str(call.resource))},
        )

    retried = await harness.send("a", call, key)

    assert retried.status_code == 404
    assert str(call.resource) not in retried.text


# ---------------------------------------------------------------------------
# R2.30 (APS33): `decide` checks with the service's own rules first.
# ---------------------------------------------------------------------------


async def test_a_requester_withdraws_without_approvals_decide_and_the_retry_replays(
    harness: Harness,
) -> None:
    approval = await raise_approval(harness)
    withdraw = Call(
        "POST",
        f"/api/v1/approvals/{approval}/decisions",
        {"approve": False, "comment": "thôi"},
        200,
        str(approval),
        lambda _: asyncio.sleep(0),
    )
    key = f"withdraw-{uuid.uuid4()}"

    first = await harness.send("requester", withdraw, key)
    again = await harness.send("requester", withdraw, key)

    assert (first.status_code, again.status_code) == (200, 200), first.text
    assert again.json() == first.json()


async def test_someone_who_may_not_decide_is_refused_before_any_key_row(
    harness: Harness,
) -> None:
    call = await decide(harness)
    key = f"nobody-{uuid.uuid4()}"

    reserves = harness.store.reserves

    refused = await harness.send("plain", call, key)

    assert refused.status_code in {403, 404}
    # Counted at the store: a refused request releases what it reserved, so
    # the table alone would look the same either way.
    assert harness.store.reserves == reserves, "the check ran after the key row was read"
    assert await harness.key_rows(key) == 0


# ---------------------------------------------------------------------------
# R2.42 (APS44): the entitlement before the key row, and never for a close.
# ---------------------------------------------------------------------------


async def _flag(h: Harness, on: bool) -> None:
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.entitlements SET feature_overrides = CAST(:f AS jsonb)"
                " WHERE tenant_id = :t"
            ),
            {"f": f'["{SUPPORT_FLAG}"]' if on else "[]", "t": h.world.tenant},
        )


async def test_a_grant_replayed_after_support_is_switched_off_is_refused(harness: Harness) -> None:
    call = await request_support(harness)
    key = f"flag-{uuid.uuid4()}"
    first = await harness.send("a", call, key)
    assert first.status_code == 201
    await _flag(harness, False)

    again = await harness.send("a", call, key)

    assert again.status_code == 403
    assert again.json()["details"]["reason_code"] == "support_access_not_enabled"
    assert first.json()["id"] not in again.text


async def test_closing_works_and_replays_with_support_switched_off(harness: Harness) -> None:
    calls = [await reject_support(harness), await revoke_support(harness)]
    await _flag(harness, False)

    for call in calls:
        key = f"close-{uuid.uuid4()}"
        first = await harness.send("a", call, key)
        again = await harness.send("a", call, key)
        assert (first.status_code, again.status_code) == (200, 200), first.text
        assert again.json() == first.json()


# ---------------------------------------------------------------------------
# R2.24 (APS26): another tenant's key never meets this tenant's effect.
# ---------------------------------------------------------------------------


async def test_another_tenant_spending_the_same_key_gets_its_own_effect(harness: Harness) -> None:
    key = f"tenant-{uuid.uuid4()}"
    mine = await grant(harness)
    await _fail_after_the_effect(harness, mine, key)
    hire = await new_user(harness.migrator, harness.world.other_tenant, [])
    theirs = Call(
        "POST",
        "/api/v1/admin/members",
        {
            "email": f"{hire.hex[:12]}@it.test",
            "workspace_id": str(harness.world.other_ws),
            "role_keys": [harness.world.plain_role],
        },
        201,
        str(hire),
        lambda _: asyncio.sleep(0),
    )

    answered = await harness.send(
        "c", theirs, key, tenant=harness.world.other_tenant, workspace=harness.world.other_ws
    )

    assert answered.status_code == 201, answered.text
    assert answered.json()["user_id"] == str(hire)
    assert str(mine.resource) not in answered.text


# ---------------------------------------------------------------------------
# R2.33, R2.35 (APS37, APS39): two attempts of one key in one race.
# ---------------------------------------------------------------------------


def _pending(operation: str, key: str, caller: uuid.UUID, status: int) -> PendingEffect:
    return PendingEffect(
        key=EffectKey(
            operation=operation,
            idempotency_key=key,
            caller_ref=f"user:{caller}",
            request_hash="d" * 64,
            fresh=True,
        ),
        status=status,
    )


async def test_two_grants_racing_on_one_key_make_one_member_and_one_audit_row(
    harness: Harness,
) -> None:
    call = await grant(harness)
    admin = harness.context("platform.members.write", "x.read", who=harness.world.users["a"])
    effect = _pending("POST /admin/members", f"race-{uuid.uuid4()}", admin.principal_id, 201)
    service = harness.container.grant_membership
    assert service is not None
    before = await harness.audits()
    body = call.body or {}

    outcomes = await asyncio.gather(
        *(
            service.handle(
                admin,
                GrantMembership(body["email"], harness.world.ws1, frozenset(body["role_keys"])),
                effect=effect,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(o, ExistingEffect) for o in outcomes) == 1, outcomes
    assert await harness.audits() == before + 1
    async with harness.migrator.connect() as conn:
        members = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.memberships WHERE user_id = :u"),
            {"u": uuid.UUID(str(call.resource))},
        )
    assert members == 1


async def test_two_decisions_racing_on_one_key_leave_one_decided_event(harness: Harness) -> None:
    approval = await raise_approval(harness)
    decider = harness.context("approvals.read", "approvals.decide", who=harness.world.users["a"])
    effect = _pending(
        "POST /approvals/{approval_id}/decisions", f"race-{uuid.uuid4()}", decider.principal_id, 200
    )
    flow = harness.container.approval_flow
    assert flow is not None

    outcomes = await asyncio.gather(
        *(
            flow.decide(
                approval_id=approval,
                approve=True,
                comment="đồng ý",
                context=decider,
                authorization=harness.container.authorization,
                effect=effect,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(o, ExistingEffect) for o in outcomes) == 1, outcomes
    async with harness.migrator.connect() as conn:
        events = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.outbox_events"
                " WHERE aggregate_id = :a AND event_type LIKE '%.decided'"
            ),
            {"a": approval},
        )
    assert events == 1


async def test_two_invitations_racing_on_one_key_meet_one_effect(harness: Harness) -> None:
    """R2.38 (APS37): the effect key goes in before the person is created, so
    the second attempt waits there and meets the first effect; after the
    person's row instead, it would fail as "already a member"."""
    email = f"race-{uuid.uuid4().hex[:10]}@it.test"
    admin = harness.context("platform.members.write", "x.read", who=harness.world.users["a"])
    effect = _pending("POST /admin/invitations", f"race-{uuid.uuid4()}", admin.principal_id, 201)
    service = harness.container.tenant_members
    assert service is not None
    before = await harness.audits()
    command = InviteMember(
        "Người được mời",
        email,
        (WorkspaceRoles(harness.world.ws1, frozenset({harness.world.plain_role})),),
    )

    outcomes = await asyncio.gather(
        *(service.invite(admin, command, effect=effect) for _ in range(2)),
        return_exceptions=True,
    )

    assert sum(isinstance(o, ExistingEffect) for o in outcomes) == 1, outcomes
    assert await harness.audits() == before + 1
