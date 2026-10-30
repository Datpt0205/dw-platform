"""The Digital Worker routes over the real service with fakes behind its ports:
what the route adds (the body shape, the context-derived tenant, the problem
the web branches on). What the database decides is covered by `dw_platform`'s
`test_digital_workers_db.py`; the service's rules by its unit test.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
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
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.digital_workers import DigitalWorkerService, Standing
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
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


def make_container(repo: FakeRepo, scopes: frozenset[str] = SCOPES) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    authz = ScopeAuthorizationService()
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
        digital_workers=DigitalWorkerService(
            repo=repo,
            authz=authz,
            tools=Tools(),
            members=Members(),
            roles=Roles(),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
        ),
    )


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
