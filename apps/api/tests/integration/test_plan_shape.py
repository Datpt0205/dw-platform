"""Every paged statement the API runs has an index that carries it.

app-standards R6.1, R6.2 (APS10): the five paged routes and the run's audit
list, through the real app on a migrated Postgres, each statement captured as
the repository sent it under `dw_app` and planned with sequential scans off,
on a first page and on a page with a cursor. `plan_shape.REGISTERED` is the
registry the app-build test holds against `app.openapi()` (R6.3); this file
plans exactly its entries.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from plan_shape import (
    REGISTERED,
    Captured,
    Expectation,
    Scope,
    bind,
    capture,
    explain,
    paged,
    plan_problems,
)
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
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_knowledge.gateway import KnowledgeGateway
from dw_memory.policy import MemoryWritePolicy
from dw_memory.service import MemoryService
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.tenant_members import SqlTenantMembersRepository
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.digital_workers import DigitalWorkerService

pytestmark = pytest.mark.integration

SECRET = "plan-shape-secret-0123456789abcdef01234"
SCOPES = (
    '["approvals.read", "audit.events", "platform.members.read", "knowledge.read", "memory.read",'
    ' "dw.read"]'
)

# What each registered page must get from its index: the statement's own
# predicate columns (RLS adds `tenant_id`, checked always) and its sort keys.
EXPECTED: dict[tuple[str, str], Expectation] = {
    ("GET", "/api/v1/approvals"): Expectation(
        "platform.approval_requests", ("workspace_id", "status"), ("created_at", "id")
    ),
    ("GET", "/api/v1/audit/events"): Expectation(
        "platform.audit_events", ("workspace_id",), ("occurred_at", "id")
    ),
    ("GET", "/api/v1/feedback"): Expectation("platform.feedback", (), ("created_at", "id")),
    ("GET", "/api/v1/digital-workers"): Expectation(
        "platform.digital_workers", ("workspace_id",), ("created_at", "id")
    ),
    ("GET", "/api/v1/work-items"): Expectation(
        "platform.work_items", ("workspace_id",), ("created_at", "id")
    ),
    ("GET", "/api/v1/knowledge/documents"): Expectation(
        "knowledge.documents",
        ("workspace_id", "status"),
        ("created_at", "id"),
        exempt_indexes={
            "ix_documents_global_page": (
                "the global arm: RLS lets every tenant read scope='global' documents, which"
                " belong to whichever tenant published them, so no index leads with a tenant"
            )
        },
    ),
    ("GET", "/api/v1/memory/items"): Expectation(
        "memory.items", ("workspace_id",), ("created_at", "memory_id")
    ),
}
RUN_AUDIT = Expectation("platform.audit_events", ("run_id", "workspace_id"), ("occurred_at",))


@dataclass
class World:
    tenant: uuid.UUID
    workspace: uuid.UUID
    user: uuid.UUID
    run: uuid.UUID

    @property
    def scope(self) -> Scope:
        return Scope(str(self.tenant), str(self.workspace), str(self.user))

    @property
    def context(self) -> AccessContext:
        return AccessContext(
            tenant_id=self.tenant,
            workspace_id=self.workspace,
            principal_id=self.user,
            roles=frozenset(),
            scopes=frozenset({"audit.events"}),
            plan_id="professional",
        )


async def seed(migrator: AsyncEngine) -> World:
    world = World(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    role = f"plan_{world.tenant.hex[:10]}"
    t, w, u, r = world.tenant, world.workspace, world.user, world.run
    now = datetime.now(UTC)
    async with migrator.begin() as conn:
        for statement, values in (
            (
                "INSERT INTO platform.roles (key, name, scopes) VALUES (:k, :k, CAST(:s AS jsonb))",
                {"k": role, "s": SCOPES},
            ),
            (
                "INSERT INTO platform.tenants (id, slug, name, status)"
                " VALUES (:t, :slug, :slug, 'active')",
                {"t": t, "slug": f"plan-{t.hex[:12]}"},
            ),
            (
                "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
                " VALUES (:id, :t, 'professional')",
                {"id": uuid.uuid4(), "t": t},
            ),
            (
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'plan', 'plan')",
                {"w": w, "t": t},
            ),
            (
                "INSERT INTO platform.users (id, subject, email, display_name)"
                " VALUES (:u, :sub, :email, 'Người xem')",
                {"u": u, "sub": f"plan-{u}", "email": f"{u.hex[:12]}@plan.test"},
            ),
            (
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
                " VALUES (:id, :t, :w, :u, CAST(:r AS jsonb))",
                {"id": uuid.uuid4(), "t": t, "w": w, "u": u, "r": f'["{role}"]'},
            ),
            (
                "INSERT INTO platform.worker_runs (id, tenant_id, workspace_id, worker_id,"
                " worker_version, graph_version, requested_by, thread_id)"
                " VALUES (:r, :t, :w, 'plan', '1', '1', :u, :r)",
                {"r": r, "t": t, "w": w, "u": u},
            ),
        ):
            await conn.execute(sa.text(statement), values)
        for n in range(3):
            at = now - timedelta(minutes=n)
            refs = json.dumps(
                [
                    {
                        "evidence_id": str(uuid.uuid4()),
                        "source_document_id": str(uuid.uuid4()),
                        "source_version": "1",
                        "relevance_score": 0.9,
                        "classification": "internal",
                        "provenance_hash": "0" * 64,
                    }
                ]
            )
            row = {"id": uuid.uuid4(), "t": t, "w": w, "u": u, "r": r, "at": at, "refs": refs}
            for statement in (
                "INSERT INTO platform.approval_requests (id, tenant_id, workspace_id,"
                " approval_type, requested_by, created_at)"
                " VALUES (:id, :t, :w, 'plan.check', :u, :at)",
                "INSERT INTO platform.audit_events (id, tenant_id, workspace_id, actor_id,"
                " action, resource_type, resource_id, run_id, occurred_at)"
                " VALUES (:id, :t, :w, :u, 'plan.check', 'plan', 'plan', :r, :at)",
                "INSERT INTO platform.feedback (id, tenant_id, workspace_id, author_id,"
                " category, message, created_at) VALUES (:id, :t, :w, :u, 'bug', 'plan', :at)",
                "INSERT INTO knowledge.documents (id, tenant_id, workspace_id, title,"
                " source_uri, created_by, created_at)"
                " VALUES (:id, :t, :w, 'plan', 'plan://x', :u, :at)",
                "INSERT INTO memory.items (memory_id, tenant_id, workspace_id, worker_id,"
                " memory_type, content, provenance_refs, confidence, valid_from,"
                " memory_schema_version, created_by_run_id, created_at)"
                " VALUES (:id, :t, :w, 'plan', 'semantic', 'plan', CAST(:refs AS jsonb), 0.9,"
                " :at,"
                " '1', :r, :at)",
            ):
                await conn.execute(sa.text(statement), {**row, "id": uuid.uuid4()})
            principal, dw = uuid.uuid4(), uuid.uuid4()
            for statement in (
                "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
                " VALUES (:p, :sub, 'plan', 'service', :t)",
                "INSERT INTO platform.service_principals (user_id, tenant_id,"
                " owning_workspace_id, name, owner_user_id) VALUES (:p, :t, :w, 'plan', :u)",
                "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
                " principal_user_id, key, name, mandate, work_kinds, allowed_tools, workflow_key,"
                " workflow_version, technical_owner_id, work_assigner_id, validator_id,"
                " created_by, created_at, updated_at)"
                " VALUES (:id, :t, :w, :p, :key, 'plan', 'plan', ARRAY['lead'], ARRAY[]::text[],"
                " 'plan', '1.0.0', :u, :u, :u, :u, :at, :at)",
                "INSERT INTO platform.work_items (id, tenant_id, workspace_id, dw_id, kind,"
                " source_key, payload, payload_hash, holder_kind, holder_id, created_at,"
                " updated_at) VALUES (:item, :t, :w, :dw, 'lead', :key, '{}'::jsonb,"
                " repeat('0', 64), 'digital_worker', :dw, :at, :at)",
            ):
                await conn.execute(
                    sa.text(statement),
                    {
                        **row,
                        "id": dw,
                        "dw": dw,
                        "item": uuid.uuid4(),
                        "p": principal,
                        "sub": f"service:{principal}",
                        "key": f"plan_{n}",
                    },
                )
    return world


@dataclass
class Bench:
    world: World
    container: ApiContainer
    client: httpx.AsyncClient
    app_engine: AsyncEngine
    admin_url: str

    async def get(self, path: str, **params: Any) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(f'plan-{self.world.user}')}",
            "X-Tenant-Id": str(self.world.tenant),
            "X-Workspace-Id": str(self.world.workspace),
        }
        response = await self.client.get(path, params=params, headers=headers)
        assert response.status_code == 200, response.text
        return response

    async def pages(self, path: str, table: str) -> list[Captured]:
        """The paged statements of a first page and of the page after it."""
        assert self.container.engine is not None
        with capture(self.container.engine) as seen:
            first = await self.get(path, limit=1)
            cursor = first.json()["next_cursor"]
            assert cursor, f"{path} has a second page to plan"
            await self.get(path, limit=1, cursor=cursor)
        statements = paged(seen, table)
        assert len(statements) >= 2, f"{path}: first and second page captured"
        return statements

    async def problems(
        self, statements: list[Captured], expected: Expectation, *, drop: str | None = None
    ) -> list[str]:
        found: list[str] = []
        # The admin role, so an index can be dropped in the same transaction,
        # then `dw_app` for the plan itself: RLS plans as it runs.
        engine = create_async_engine(self.admin_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn, conn.begin() as tx:
                if drop is not None:
                    await conn.execute(sa.text(f"DROP INDEX {drop}"))
                await conn.execute(sa.text("SET LOCAL ROLE dw_app"))
                await bind(conn, self.world.scope)
                for statement in statements:
                    plan = await explain(conn, statement)
                    found.extend(
                        f"{problem} :: {statement.statement}"
                        for problem in await plan_problems(conn, plan, expected)
                    )
                await tx.rollback()
        finally:
            await engine.dispose()
        return found


class Unused:
    """What a listing never touches: any use is a test that grew past it."""

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(f"not exercised by a listing: {name}")


@pytest.fixture
async def bench(api_db: DatabaseUrls) -> AsyncIterator[Bench]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    world = await seed(migrator)
    await migrator.dispose()
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    assert container.engine is not None and container.uow_factory is not None
    # The runtime is wired only with object storage, which this suite has not;
    # the two listings it would bring read only Postgres, so they are built
    # here on the app's own sessions, the rest of each left unusable.
    sessions = async_sessionmaker(container.engine, class_=AsyncSession, expire_on_commit=False)
    clock, ids = SystemClock(), Uuid4Generator()
    unused = cast(Any, Unused())
    container.knowledge_gateway = KnowledgeGateway(
        session_factory=sessions,
        vector_index=unused,
        embeddings=unused,
        object_storage=unused,
        clock=clock,
        id_generator=ids,
    )
    container.memory_service = MemoryService(
        session_factory=sessions,
        policy=MemoryWritePolicy(),
        clock=clock,
        id_generator=ids,
        evidence_store=unused,
    )
    # Digital Workers are wired with the runtime too; the listing reads only
    # Postgres, so no tool register is consulted.
    container.digital_workers = DigitalWorkerService(
        repo=SqlDigitalWorkerRepository(sessions),
        authz=ScopeAuthorizationService(),
        tools=unused,
        members=SqlDwMembershipCheck(sessions),
        roles=SqlTenantMembersRepository(sessions),
        clock=clock,
        id_generator=ids,
    )
    # The inbox lists through the approval flow; no approval here has a run.
    container.approval_flow = ApproveAndResumeService(
        uow_factory=container.uow_factory,
        runner=cast(Any, None),
        run_store=cast(Any, None),
        clock=clock,
        id_generator=ids,
    )
    app = create_app(container)
    admin_url = api_db.admin.rsplit("/", 1)[0] + "/" + api_db.app.rsplit("/", 1)[1]
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Bench(world, container, client, container.engine, admin_url)
    await container.engine.dispose()


def test_every_registered_page_has_its_expectation() -> None:
    assert set(EXPECTED) == set(REGISTERED)
    assert all(EXPECTED[op].table == table for op, table in REGISTERED.items())


@pytest.mark.parametrize("operation", sorted(REGISTERED))
async def test_a_paged_route_reads_through_an_index_that_carries_it(
    bench: Bench, operation: tuple[str, str]
) -> None:
    expected = EXPECTED[operation]
    statements = await bench.pages(operation[1], expected.table)

    assert await bench.problems(statements, expected) == []


async def test_the_run_audit_list_reads_through_the_run_index(bench: Bench) -> None:
    assert bench.container.uow_factory is not None
    with capture(bench.app_engine) as seen:
        async with bench.container.uow_factory(bench.world.context) as uow:
            events = await uow.audit.list_for_run(
                bench.world.run, workspace_id=bench.world.workspace
            )
    assert len(events) == 3
    statements = paged(seen, RUN_AUDIT.table)

    assert statements and await bench.problems(statements, RUN_AUDIT) == []


async def test_dropping_the_feedback_page_index_turns_the_check_red(bench: Bench) -> None:
    # APS10: the check is not passed by a table small enough to scan.
    expected = EXPECTED[("GET", "/api/v1/feedback")]
    statements = await bench.pages("/api/v1/feedback", expected.table)

    problems = await bench.problems(statements, expected, drop="platform.ix_feedback_page")

    assert problems, "the check passed without the index"
    assert any("FROM platform.feedback" in problem for problem in problems)
    assert any("created_at" in problem or "tenant_id" in problem for problem in problems)


async def test_the_document_listing_pages_both_arms_once_in_order(
    bench: Bench, api_db: DatabaseUrls
) -> None:
    # The two arms the listing reads: the workspace's own documents and the
    # global ones another tenant published; never another workspace's own.
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    world, publisher = bench.world, uuid.uuid4()
    now = datetime.now(UTC)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status)"
                " VALUES (:t, :s, :s, 'active')"
            ),
            {"t": publisher, "s": f"pub-{publisher.hex[:12]}"},
        )
        for minutes, tenant, workspace, scope in (
            (10, publisher, uuid.uuid4(), "global"),
            (20, world.tenant, uuid.uuid4(), "tenant"),
            (30, publisher, uuid.uuid4(), "global"),
        ):
            await conn.execute(
                sa.text(
                    "INSERT INTO knowledge.documents (id, tenant_id, workspace_id, title,"
                    " source_uri, created_by, created_at, scope)"
                    " VALUES (:id, :t, :w, 'pub', 'plan://p', :u, :at, :scope)"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tenant,
                    "w": workspace,
                    "u": world.user,
                    "at": now - timedelta(seconds=minutes * 30),
                    "scope": scope,
                },
            )
    await migrator.dispose()

    seen: list[tuple[str, str]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        body = (await bench.get("/api/v1/knowledge/documents", **params)).json()
        seen += [(item["document_id"], item["created_at"]) for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    # Three of the workspace's own (seeded), two global; the other
    # workspace's own document is not listed.
    assert len(seen) == 5 and len({doc for doc, _ in seen}) == 5
    assert [at for _, at in seen] == sorted((at for _, at in seen), reverse=True)
