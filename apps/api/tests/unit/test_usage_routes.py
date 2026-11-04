"""`GET /runs/{id}/usage` and `GET /usage/summary` (usage-and-limits R3.6,
R3.12; UL7, UL18).

The run's usage reads the run first in the caller's workspace, so another
workspace's run and one that does not exist are the same 404 and nothing of the
ledger is asked; a visible run that called no model is a 200 with zero. The
summary is a 403 without `platform.usage.read`, before any read. The stores
honour the SQL ones' contract; the SQL ones run against Postgres in
`dw_usage`'s integration suite.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from asgi_lifespan import LifespanManager

from dw_agent_runtime.adapters.run_store import RunRecord, RunStatus
from dw_agent_runtime.contracts import RunContext
from dw_api.bootstrap import ApiContainer
from dw_api.health import CheckState, HealthService
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_kernel.errors import NotFoundError
from dw_kernel.ports import FixedClock
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.identity import DbAccessContextFactory, MembershipAccess
from dw_usage.application.calendar import UsageCalendar
from dw_usage.application.ports import RunUsageRow, SummaryFilter, SummaryRow
from dw_usage.application.reads import UsageReads

pytestmark = pytest.mark.unit

SECRET = "unit-test-secret-0123456789abcdef"
TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
OTHER_WORKSPACE = uuid.uuid4()
PRINCIPAL = uuid.uuid4()
NOW = datetime(2026, 11, 4, 9, tzinfo=UTC)


@dataclass
class FakeMembershipLookup:
    scopes: frozenset[str]

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
            scopes=self.scopes,
            groups=frozenset(),
            clearance="internal",
            plan_id="professional",
            feature_flags=frozenset(),
        )


def _record(run_id: uuid.UUID, workspace: uuid.UUID) -> RunRecord:
    return RunRecord(
        id=run_id,
        thread_id=run_id,
        workspace_id=workspace,
        status=RunStatus.COMPLETED,
        worker_id="demo",
        worker_version="1.0.0",
        graph_version="1.0.0",
        prompt_bundle_version=None,
        toolset_version=None,
        policy_version=None,
        memory_policy_version=None,
        autonomy_level=None,
        approval_policy_version=None,
        input={},
        result=None,
        error=None,
        approval_request_id=None,
        release_manifest_ref=None,
        requested_by=PRINCIPAL,
        actor_roles=frozenset(),
        actor_scopes=frozenset(),
        actor_plan_id="professional",
        actor_clearance="internal",
        actor_record_visibility="open",
        actor_visible_owners=None,
    )


@dataclass
class FakeRunStore:
    """Honours `SqlWorkerRunStore.get`: a run is found in its own workspace only."""

    runs: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    async def get(self, run_context: RunContext, run_id: uuid.UUID) -> RunRecord:
        if self.runs.get(run_id) != run_context.workspace_id:
            raise NotFoundError("run not found", details={"run_id": str(run_id)})
        return _record(run_id, run_context.workspace_id)


@dataclass
class FakeUsageStore:
    """Honours `SqlUsageReads`: rows of the asked company and run only."""

    rows: dict[uuid.UUID, list[RunUsageRow]] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    async def run_usage(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[RunUsageRow]:
        self.asked.append(f"run:{tenant_id}")
        return self.rows.get(run_id, [])

    async def summary(self, tenant_id: uuid.UUID, query: SummaryFilter) -> list[SummaryRow]:
        self.asked.append(f"summary:{tenant_id}")
        return [
            SummaryRow(
                key=None,
                artifact_kind=None,
                label=None,
                calls=3,
                input_tokens=30,
                output_tokens=9,
                cost_usd=Decimal("0.012345"),
                unpriced_calls=0,
                estimated_calls=1,
            )
        ]


@dataclass
class NoZone:
    async def timezone_of(self, tenant_id: uuid.UUID) -> str | None:
        return None


def _container(
    scopes: frozenset[str], *, runs: FakeRunStore | None = None, usage: FakeUsageStore
) -> ApiContainer:
    async def ok_probe() -> CheckState:
        return "ok"

    authorization = ScopeAuthorizationService()
    return ApiContainer(
        settings=ApiSettings(profile="test", dev_secret=SECRET),
        engine=None,
        health_service=HealthService(probes={"database": ok_probe}),
        token_verifier=DevTokenVerifier(SECRET),
        access_context_factory=DbAccessContextFactory(FakeMembershipLookup(scopes)),
        identity_bootstrap=None,
        uow_factory=None,
        authorization=authorization,
        run_store=runs or FakeRunStore(),  # type: ignore[arg-type]
        usage=UsageReads(
            store=usage,
            calendar=UsageCalendar(NoZone()),
            authz=authorization,
            clock=FixedClock(NOW),
        ),
    )


async def _get(container: ApiContainer, path: str) -> httpx.Response:
    token = DevTokenVerifier(SECRET).issue("dev|reader", email="reader@fpt.com")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": str(TENANT),
        "X-Workspace-Id": str(WORKSPACE),
    }
    app = create_app(container)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(f"/api/v1{path}", headers=headers)


# ---- R3.12 (UL18) -----------------------------------------------------------


async def test_the_summary_without_the_key_is_403_and_reads_nothing() -> None:
    usage = FakeUsageStore()
    response = await _get(_container(frozenset({"runs.read"}), usage=usage), "/usage/summary")
    assert response.status_code == 403
    assert usage.asked == []


async def test_the_holder_reads_the_company_level_group() -> None:
    usage = FakeUsageStore()
    response = await _get(
        _container(frozenset({"platform.usage.read"}), usage=usage), "/usage/summary"
    )
    assert response.status_code == 200
    body = response.json()
    assert usage.asked == [f"summary:{TENANT}"]
    assert body["groups"][0]["key"] is None  # the company-level group
    assert (body["cost_usd"], body["calls"], body["estimated_calls"]) == ("0.01234500", 3, 1)
    assert (body["first_day"], body["last_day"]) == ("2026-11-01", "2026-11-30")


async def test_a_summary_range_too_long_is_422() -> None:
    usage = FakeUsageStore()
    response = await _get(
        _container(frozenset({"platform.usage.read"}), usage=usage),
        "/usage/summary?from=2025-01-01&to=2026-11-01",
    )
    assert response.status_code == 422
    assert usage.asked == []


# ---- R3.6 (UL7) ------------------------------------------------------------


async def test_another_workspaces_run_is_the_same_404_as_no_run() -> None:
    theirs = uuid.uuid4()
    usage = FakeUsageStore()
    container = _container(
        frozenset({"runs.read"}), runs=FakeRunStore({theirs: OTHER_WORKSPACE}), usage=usage
    )

    other = await _get(container, f"/runs/{theirs}/usage")
    unknown = await _get(container, f"/runs/{uuid.uuid4()}/usage")

    assert other.status_code == unknown.status_code == 404
    assert usage.asked == [], "the ledger is not asked about a run the caller cannot see"


async def test_reading_a_run_s_usage_needs_runs_read() -> None:
    mine = uuid.uuid4()
    usage = FakeUsageStore()
    response = await _get(
        _container(
            frozenset({"approvals.read"}), runs=FakeRunStore({mine: WORKSPACE}), usage=usage
        ),
        f"/runs/{mine}/usage",
    )
    assert response.status_code == 403
    assert usage.asked == []


async def test_a_visible_run_with_no_model_call_is_zero_not_404() -> None:
    mine = uuid.uuid4()
    usage = FakeUsageStore()
    response = await _get(
        _container(frozenset({"runs.read"}), runs=FakeRunStore({mine: WORKSPACE}), usage=usage),
        f"/runs/{mine}/usage",
    )
    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(mine),
        "calls": 0,
        "cost_usd": "0.00000000",
        "rows": [],
    }
    assert usage.asked == [f"run:{TENANT}"]


async def test_a_run_s_usage_sums_its_rows() -> None:
    mine = uuid.uuid4()
    usage = FakeUsageStore(
        rows={
            mine: [
                RunUsageRow("chat", "mock", "m", "computed", 2, 20, 4, Decimal("0.5")),
                RunUsageRow("chat", "mock", "m", "unpriced", 1, 10, 2, Decimal(0)),
            ]
        }
    )
    response = await _get(
        _container(frozenset({"runs.read"}), runs=FakeRunStore({mine: WORKSPACE}), usage=usage),
        f"/runs/{mine}/usage",
    )
    body = response.json()
    assert (body["calls"], body["cost_usd"]) == (3, "0.50000000")
    assert [row["cost_source"] for row in body["rows"]] == ["computed", "unpriced"]
