"""The work-item routes over the real queue with fakes behind its ports: what
the route adds (status codes, the problem's reason, what a list and an item
carry). The rules against a real database are `dw_platform`'s
`test_work_queue_db.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.work_queue import (
    Claimed,
    InMemoryWorkKindSchemas,
    WorkListFilter,
    WorkQueue,
    WorkScope,
)
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import (
    DigitalWorker,
    DwConfiguration,
    DwPeople,
)
from dw_platform.domain.work_item import HandoffPacket, WorkItem, WorkStatus

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()
CALLER = uuid.uuid4()
OTHER = uuid.uuid4()
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SCHEMA = {"type": "object", "required": ["email"]}


class Lookup:
    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=CALLER,
            roles=frozenset({"member"}),
            scopes=frozenset({"dw.read"}),
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


def worker(*, assigner: uuid.UUID) -> DigitalWorker:
    return DigitalWorker(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_user_id=uuid.uuid4(),
        configuration=DwConfiguration(
            key="lead_care",
            name="Chăm sóc lead",
            mandate="Gửi thư.",
            work_kinds=("lead.new",),
            allowed_tools=(),
            workflow_key="leadcare",
            workflow_version="1.0.0",
            parameters={},
            role_keys=frozenset({"member"}),
            decision_classes=(),
        ),
        people=DwPeople(
            business_owner_id=OTHER,
            technical_owner_id=OTHER,
            work_assigner_id=assigner,
            validator_id=OTHER,
        ),
        state="operating",
        created_by=OTHER,
        created_at=NOW,
        updated_at=NOW,
    )


class Repo:
    """Keeps items by id, refuses a move from a state outside `sources`."""

    def __init__(self) -> None:
        self.items: dict[uuid.UUID, WorkItem] = {}

    async def insert(
        self,
        scope: WorkScope,
        item: WorkItem,
        *,
        audit: AuditEvent | None,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        for existing in self.items.values():
            if (existing.dw_id, existing.kind, existing.source_key) == (
                item.dw_id,
                item.kind,
                item.source_key,
            ):
                return existing
        self.items[item.id] = item
        return item

    async def get(self, scope: WorkScope, item_id: uuid.UUID) -> WorkItem | None:
        return self.items.get(item_id)

    async def page(
        self, scope: WorkScope, request: PageRequest, where: WorkListFilter
    ) -> Page[WorkItem]:
        rows = [i for i in self.items.values() if where.status in (None, i.status)]
        return build_page(
            rows[: request.fetch_limit],
            request=request,
            position_of=lambda i: CursorPosition(sort_value=i.created_at, tiebreaker=i.id),
        )

    async def move(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        sources: frozenset[WorkStatus],
        target: WorkStatus,
        values: Any,
        audit: AuditEvent | None,
        effect: PendingEffect | None = None,
    ) -> WorkItem | None:
        item = self.items.get(item_id)
        if item is None or item.status not in sources:
            return None
        self.items[item_id] = replace(item, status=target, **dict(values))
        return self.items[item_id]

    async def claim_due(self, scope: WorkScope, *, limit: int) -> list[Claimed]:
        raise NotImplementedError("not exercised by the route tests")

    async def release_stuck(self, scope: WorkScope, *, older_than: Any) -> int:
        raise NotImplementedError("not exercised by the route tests")


class Workers:
    def __init__(self, found: DigitalWorker) -> None:
        self.found = found

    async def digital_worker(self, scope: WorkScope, dw_id: uuid.UUID) -> DigitalWorker | None:
        return self.found if dw_id == self.found.id else None


class People:
    async def is_person_in(self, scope: WorkScope, user_id: uuid.UUID) -> bool:
        return True


def make(repo: Repo, dw: DigitalWorker) -> ApiContainer:
    async def ok() -> CheckState:
        return "ok"

    authz = ScopeAuthorizationService()
    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(Lookup()),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=authz,
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
        work_queue=WorkQueue(
            repo=repo,
            workers=Workers(dw),
            people=People(),
            schemas=InMemoryWorkKindSchemas({("leadcare", "lead.new"): SCHEMA}),
            authz=authz,
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        ),
    )


async def call(
    container: ApiContainer, method: str, path: str, body: object = None
) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue("dev|caller", email="caller@fpt.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, f"/api/v1{path}", json=body, headers=headers)


def new_work(source: str = "form-1") -> dict[str, Any]:
    return {"kind": "lead.new", "source_key": source, "payload": {"email": "an@khach.vn"}}


async def test_only_the_work_assigner_gives_work_by_hand() -> None:
    """DWK30."""
    repo = Repo()
    not_mine = worker(assigner=OTHER)
    refused = await call(
        make(repo, not_mine), "POST", f"/digital-workers/{not_mine.id}/work-items", new_work()
    )
    assert refused.status_code == 403
    assert refused.json()["details"]["reason_code"] == "not_work_assigner"
    assert repo.items == {}

    mine = worker(assigner=CALLER)
    given = await call(
        make(repo, mine), "POST", f"/digital-workers/{mine.id}/work-items", new_work()
    )
    assert given.status_code == 201, given.text
    assert given.json()["status"] == "open"


async def test_a_payload_outside_its_schema_is_a_422_with_its_reason() -> None:
    repo = Repo()
    mine = worker(assigner=CALLER)
    response = await call(
        make(repo, mine),
        "POST",
        f"/digital-workers/{mine.id}/work-items",
        {**new_work(), "payload": {"name": "Anh"}},
    )
    assert response.status_code == 422
    assert response.json()["details"]["reason_code"] == "payload_invalid"


async def test_a_list_carries_no_payload_and_only_the_holder_closes_handed_work() -> None:
    """R3.5, DWK12, R3.13."""
    repo = Repo()
    mine = worker(assigner=CALLER)
    created = await call(
        make(repo, mine), "POST", f"/digital-workers/{mine.id}/work-items", new_work()
    )
    item_id = uuid.UUID(created.json()["id"])

    listed = await call(make(repo, mine), "GET", "/work-items")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["payload"] is None

    packet = HandoffPacket("p", "c", "t", "r")
    repo.items[item_id] = replace(
        repo.items[item_id],
        status="handed_off",
        holder_kind="person",
        holder_id=OTHER,
        handoff=packet,
    )
    refused = await call(make(repo, mine), "POST", f"/work-items/{item_id}/complete")
    assert refused.status_code == 403
    assert refused.json()["details"]["reason_code"] == "not_holder"

    repo.items[item_id] = replace(repo.items[item_id], holder_id=CALLER)
    done = await call(make(repo, mine), "POST", f"/work-items/{item_id}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["handoff"]["recommendation"] == "r"


async def test_an_unknown_item_is_404() -> None:
    repo = Repo()
    response = await call(make(repo, worker(assigner=CALLER)), "GET", f"/work-items/{uuid.uuid4()}")
    assert response.status_code == 404


class Trails:
    """`RunTrailReader`'s answer for one run; records the scope it was asked in."""

    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.asked: list[dict[str, Any]] = []

    async def trail(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, run_id: uuid.UUID, live: bool
    ) -> list[dict[str, Any]]:
        self.asked.append(
            {"tenant_id": tenant_id, "workspace_id": workspace_id, "run_id": run_id, "live": live}
        )
        if run_id != self.run_id:
            return []
        return [{"step_id": "draft", "type": "ai.llm@1", "status": "done", "at": NOW.isoformat()}]


async def test_one_item_carries_its_runs_trail_read_in_the_callers_scope() -> None:
    """wf-lite R6.13 (WFL15): the trail is read under the caller's own tenant
    and workspace, after the item itself was; a list carries none."""
    repo = Repo()
    mine = worker(assigner=CALLER)
    container = make(repo, mine)
    created = await call(container, "POST", f"/digital-workers/{mine.id}/work-items", new_work())
    item_id = uuid.UUID(created.json()["id"])
    run_id = uuid.uuid4()
    repo.items[item_id] = replace(repo.items[item_id], status="in_progress", run_id=run_id)
    trails = Trails(run_id)
    container.run_trails = trails  # type: ignore[assignment]

    one = await call(container, "GET", f"/work-items/{item_id}")
    assert one.status_code == 200, one.text
    assert one.json()["trail"] == [
        {"step_id": "draft", "type": "ai.llm@1", "status": "done", "at": NOW.isoformat()}
    ]
    assert trails.asked == [
        {"tenant_id": TENANT, "workspace_id": WORKSPACE, "run_id": run_id, "live": True}
    ]

    listed = await call(container, "GET", "/work-items")
    assert listed.json()["items"][0]["trail"] is None

    # Another tenant's item is not found before any trail is read.
    trails.asked.clear()
    missing = await call(container, "GET", f"/work-items/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert trails.asked == []
