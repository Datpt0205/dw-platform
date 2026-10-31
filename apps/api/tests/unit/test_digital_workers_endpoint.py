"""The Digital Worker routes over the real service with fakes behind its ports:
what the route adds (the body shape, the context-derived tenant, the problem
the web branches on). What the database decides is covered by `dw_platform`'s
`test_digital_workers_db.py`; the service's rules by its unit test.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_agent_runtime.wflite.catalog import load_shipped_packs
from dw_agent_runtime.wflite.outline import WorkflowOutlineReader
from dw_agent_runtime.wflite.registry import build_node_registry
from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.paths import CONFIGS
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.digital_workers import (
    ClassAutonomy,
    DigitalWorkerService,
    Standing,
)
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_platform.application.work_queue import InMemoryWorkKindSchemas, WorkQueue, WorkScope
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import DigitalWorker, DwPeople, DwState

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()
CALLER, TECH, ASSIGNER, VALIDATOR = (uuid.uuid4() for _ in range(4))
SCOPES = frozenset({"dw.manage", "dw.read", "approvals.read", "email.send"})


class FakeLookup:
    def __init__(self, scopes: frozenset[str]) -> None:
        self._scopes = scopes

    async def find_access(
        self, subject: str, issuer: str, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> MembershipAccess | None:
        if (tenant_id, workspace_id) != (TENANT, WORKSPACE):
            return None
        return MembershipAccess(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=CALLER,
            roles=frozenset({"member"}),
            scopes=self._scopes,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


class FakeRepo:
    """Keeps DWs by id and answers only inside the caller's tenant and workspace."""

    def __init__(self) -> None:
        self.workers: dict[uuid.UUID, DigitalWorker] = {}

    async def create(
        self,
        context: AccessContext,
        worker: DigitalWorker,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        self.workers[worker.id] = worker

    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker | None:
        found = self.workers.get(dw_id)
        if found is None or (found.tenant_id, found.workspace_id) != (
            context.tenant_id,
            context.workspace_id,
        ):
            return None
        return found

    async def list(self, context: AccessContext, request: PageRequest) -> Page[DigitalWorker]:
        mine = sorted(
            (w for w in self.workers.values() if w.workspace_id == context.workspace_id),
            key=lambda w: (w.created_at, w.id),
            reverse=True,
        )
        return build_page(
            mine[: request.fetch_limit],
            request=request,
            position_of=lambda w: CursorPosition(sort_value=w.created_at, tiebreaker=w.id),
        )

    async def change_state(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        *,
        current: DwState,
        target: DwState,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        found = await self.get(context, dw_id)
        if found is None or found.state != current:
            return False
        self.workers[dw_id] = replace(found, state=target)
        return True

    async def replace_people(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        people: DwPeople,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        raise NotImplementedError("not exercised by the route tests")


class Members:
    async def standing(self, context: AccessContext, user_id: uuid.UUID) -> Standing | None:
        if user_id == VALIDATOR:
            return Standing("human", frozenset({"approvals.decide"}))
        if user_id in {CALLER, TECH, ASSIGNER}:
            return Standing("human", frozenset({"approvals.read"}))
        return None


class Tools:
    def has_tool(self, name: str) -> bool:
        return name == "email.send"


class Roles:
    async def role_catalog(self) -> dict[str, frozenset[str]]:
        return {"member": frozenset({"approvals.read", "dw.read"})}


class QueueRepo:
    """Answers the one question the list asks of the queue: open items per DW,
    only inside the scope asked."""

    def __init__(self) -> None:
        self.open: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        self.asked: list[WorkScope] = []

    async def open_counts(self, scope: WorkScope, dw_ids: Any) -> dict[uuid.UUID, int]:
        self.asked.append(scope)
        wanted = set(dw_ids)
        return {
            dw: n
            for (workspace, dw), n in self.open.items()
            if workspace == scope.workspace_id and dw in wanted
        }

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(f"{name} is not exercised by the route tests")


class Autonomy:
    """The gate's answer per class key, as `DecisionAutonomy` gives it."""

    def __init__(self, answers: dict[str, ClassAutonomy]) -> None:
        self.answers = answers

    async def class_autonomy(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> ClassAutonomy:
        return self.answers.get(key, ClassAutonomy(effective_level="A0", requires_person=True))


def make_container(
    repo: FakeRepo,
    scopes: frozenset[str] = SCOPES,
    *,
    queue: QueueRepo | None = None,
    autonomy: Autonomy | None = None,
) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    authz = ScopeAuthorizationService()
    service = DigitalWorkerService(
        repo=repo,
        authz=authz,
        tools=Tools(),
        members=Members(),
        roles=Roles(),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )
    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeLookup(scopes)),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=authz,
        entitlement=PlanEntitlementService(DEFAULT_PLANS),
        digital_workers=service,
        work_queue=WorkQueue(
            repo=cast(Any, queue or QueueRepo()),
            workers=cast(Any, None),
            people=cast(Any, None),
            schemas=InMemoryWorkKindSchemas({}),
            authz=authz,
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        ),
        dw_workflows=WorkflowOutlineReader(
            workers=service,
            workflows=PACKS,
            autonomy=autonomy or Autonomy({}),
            registry=build_node_registry(),
        ),
    )


PACKS = load_shipped_packs(CONFIGS)


def body(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": "lead_care",
        "name": "Chăm sóc lead",
        "mandate": "Gửi thư chào lead mới.",
        "work_kinds": ["lead.new"],
        "allowed_tools": ["email.send"],
        "workflow_key": "leadcare",
        "workflow_version": "1.0.0",
        "role_keys": ["member"],
        "people": {
            "business_owner_id": str(CALLER),
            "technical_owner_id": str(TECH),
            "work_assigner_id": str(ASSIGNER),
            "validator_id": str(VALIDATOR),
        },
        "decision_classes": [
            {
                "key": "email.first_touch",
                "effect_level": "external",
                "reversible": True,
                "ceiling": "A3",
                "earned_level": "A2",
            }
        ],
    }
    base.update(changes)
    return base


async def call(
    container: ApiContainer, method: str, path: str = "", payload: object = None
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
            return await client.request(
                method, f"/api/v1/digital-workers{path}", json=payload, headers=headers
            )


async def test_a_tenant_in_the_body_changes_nothing() -> None:
    """R1.1: the DW lands in the caller's tenant and workspace."""
    repo = FakeRepo()
    response = await call(
        make_container(repo),
        "POST",
        payload=body(tenant_id=str(uuid.uuid4()), workspace_id=str(uuid.uuid4())),
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["state"] == "draft"
    assert view["people"]["validator_id"] == str(VALIDATOR)
    [worker] = repo.workers.values()
    assert (worker.tenant_id, worker.workspace_id) == (TENANT, WORKSPACE)


@pytest.mark.parametrize(
    ("changes", "status", "code"),
    [
        ({"work_kinds": []}, 422, "work_kinds_empty"),
        ({"allowed_tools": ["sms.send"]}, 422, "tool_unknown"),
        (
            {
                "decision_classes": [
                    {
                        "key": "email.first_touch",
                        "effect_level": "external",
                        "reversible": True,
                        "ceiling": "A2",
                        "earned_level": "A3",
                    }
                ]
            },
            422,
            "above_ceiling",
        ),
        (
            {
                "people": {
                    "business_owner_id": str(CALLER),
                    "technical_owner_id": str(TECH),
                    "work_assigner_id": str(ASSIGNER),
                    "validator_id": str(uuid.uuid4()),
                }
            },
            422,
            "owner_not_member",
        ),
    ],
)
async def test_a_refusal_names_its_reason(changes: dict[str, Any], status: int, code: str) -> None:
    repo = FakeRepo()
    response = await call(make_container(repo), "POST", payload=body(**changes))
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["details"]["reason_code"] == code
    assert repo.workers == {}


async def test_an_unknown_or_unreadable_dw_is_404_and_a_non_owner_is_403() -> None:
    repo = FakeRepo()
    created = await call(make_container(repo), "POST", payload=body())
    dw_id = created.json()["id"]

    assert (await call(make_container(repo), "GET", f"/{uuid.uuid4()}")).status_code == 404
    unreadable = await call(make_container(repo, frozenset({"approvals.read"})), "GET", f"/{dw_id}")
    assert unreadable.status_code == 404
    assert unreadable.json()["code"] == "not_found"

    # The caller is the Business Owner here: TECH's DW, not theirs, would be
    # 403. Make the caller no owner by replacing the stored people.
    worker = repo.workers[uuid.UUID(dw_id)]
    repo.workers[worker.id] = replace(worker, people=replace(worker.people, business_owner_id=TECH))
    refused = await call(make_container(repo), "POST", f"/{dw_id}/state", {"state": "retired"})
    assert refused.status_code == 403
    assert refused.json()["details"]["reason_code"] == "not_dw_owner"
    assert repo.workers[worker.id].state == "draft"


async def test_the_creator_cannot_start_their_own_dw_and_the_list_shows_it() -> None:
    repo = FakeRepo()
    created = await call(make_container(repo), "POST", payload=body())
    dw_id = created.json()["id"]
    refused = await call(make_container(repo), "POST", f"/{dw_id}/state", {"state": "operating"})
    assert refused.status_code == 409
    assert refused.json()["details"]["reason_code"] == "second_person_required"

    listed = await call(make_container(repo), "GET")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [dw_id]


async def test_the_list_counts_each_dws_open_items_in_the_callers_workspace() -> None:
    """R9.1: the list carries the open items of each DW; one with none reads 0."""
    repo, queue = FakeRepo(), QueueRepo()
    first = (await call(make_container(repo), "POST", payload=body())).json()["id"]
    second = (await call(make_container(repo), "POST", payload=body(key="other"))).json()["id"]
    queue.open[(WORKSPACE, uuid.UUID(first))] = 3
    queue.open[(uuid.uuid4(), uuid.UUID(second))] = 9

    listed = await call(make_container(repo, queue=queue), "GET")
    assert listed.status_code == 200, listed.text
    counts = {item["id"]: item["open_items"] for item in listed.json()["items"]}
    assert counts == {first: 3, second: 0}
    assert queue.asked == [WorkScope(tenant_id=TENANT, workspace_id=WORKSPACE)]


def lead_care(**changes: Any) -> dict[str, Any]:
    return body(
        workflow_key="lead_care",
        decision_classes=[
            {
                "key": "email.send",
                "effect_level": "external",
                "reversible": False,
                "ceiling": "A2",
                "earned_level": "A1",
            },
            {
                "key": "work.handoff",
                "effect_level": "internal",
                "reversible": True,
                "ceiling": "A3",
                "earned_level": "A3",
            },
        ],
        **changes,
    )


async def test_the_workflow_route_draws_the_pinned_tree_and_each_class_mode() -> None:
    """R9.2: every step of the pinned document with its lanes; a class whose
    every tool is outside `allowed_tools` is `blocked` whatever its level."""
    repo = FakeRepo()
    autonomy = Autonomy(
        {
            "email.send": ClassAutonomy(effective_level="A1", requires_person=True),
            "work.handoff": ClassAutonomy(effective_level="A3", requires_person=False),
        }
    )
    dw_id = (await call(make_container(repo), "POST", payload=lead_care())).json()["id"]

    response = await call(make_container(repo, autonomy=autonomy), "GET", f"/{dw_id}/workflow")
    assert response.status_code == 200, response.text
    view = response.json()
    assert (view["key"], view["version"]) == ("lead_care", "1.0.0")
    assert [s["id"] for s in view["steps"]] == ["score", "draft", "approve_send"]
    gate = view["steps"][2]
    assert gate["decision_class"] == "email.send"
    assert [lane["port"] for lane in gate["lanes"]] == ["approved", "rejected"]
    switch = next(s for s in gate["lanes"][0]["steps"] if s["id"] == "replied")
    assert {lane["port"] for lane in switch["lanes"]} == {"cases.true", "default"}
    # Only email.send is allowed: work.handoff's tools are all refused.
    assert view["decision_classes"] == [
        {"key": "email.send", "effective_level": "A1", "mode": "ask"},
        {"key": "work.handoff", "effective_level": "A3", "mode": "blocked"},
    ]


async def test_the_workflow_of_an_unreadable_or_unshipped_dw_is_404() -> None:
    repo = FakeRepo()
    dw_id = (await call(make_container(repo), "POST", payload=lead_care())).json()["id"]
    unreadable = await call(
        make_container(repo, frozenset({"approvals.read"})), "GET", f"/{dw_id}/workflow"
    )
    assert unreadable.status_code == 404
    assert "steps" not in unreadable.json()

    other = (await call(make_container(repo), "POST", payload=body(key="unshipped"))).json()["id"]
    unshipped = await call(make_container(repo), "GET", f"/{other}/workflow")
    assert unshipped.status_code == 404
    assert unshipped.json()["details"]["reason_code"] == "workflow_not_shipped"
