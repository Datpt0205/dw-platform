"""Two-person publication over the real store (agent-lifecycle ticket 04):
the submit of a kind without a quality gate (R2.8-R2.12, R5.1, R7.9, R7.13),
the `.decided` settler (R5.5, R5.9, R5.10, R7.12) and the database's backstop
(R5.6), each as `dw_app`.

The kinds are the test's: `object` registered with a fake comparator (a
document with `"tighten": true` only tightens) and a recording publish hook,
since the trigger's tighten-only branch is the `object` kind's alone; and
`fixture_gateless`, which has no comparator (the shape of `endpoint`). The run
controls and, but for the one test that proposes and approves a real Binding
set, the bindings check are stand-ins answering what a test sets. A decision
is written as the approval flow writes it (`decide_for_test`); who may decide
is the API test's (`test_studio_publish.py`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.errors import ConflictError, PreconditionFailedError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.config_versions_repo import SqlConfigVersionStore
from dw_platform.adapters.persistence.connections_repo import SqlConnectionStore
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.config_versions import (
    CONFIG_PREFIX,
    CONFIG_VERSION,
    ConfigKindRegistry,
    ConfigSettlement,
    ConfigVersionDecisions,
    ConfigVersionService,
)
from dw_platform.application.connections import ConnectionUsability, NoConnectorCatalog
from dw_platform.application.work_queue import WorkScope
from dw_platform.testing.rbac import assign, plant_membership, plant_person, plant_role
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.application.bindings import (
    BINDING_SET,
    BINDINGS_APPROVE_SCOPE,
    BINDINGS_PROPOSE_SCOPE,
    BindingSets,
    BindingStatus,
    platform_binding_types,
)
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.lifecycle.adapters.store import SqlLifecycleStore
from dw_studio.lifecycle.application.ports import PublishBindingsCheck
from dw_studio.lifecycle.application.publish import VERSION_LIVE
from dw_studio.lifecycle.application.review import PublishSettler
from dw_studio.lifecycle.application.service import LifecycleService, Submitted
from dw_studio.testing.fixture_kinds import (
    FIXTURE,
    FIXTURE_GATELESS,
    FIXTURE_READ,
    FIXTURE_SUBMIT,
    FIXTURE_WRITE,
    extract_fixture,
    planted_fixture_kinds,
    validate_fixture,
)
from dw_studio.testing.lifecycle import StubBindings, decide_for_test, publish_for_test
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

OBJECT = "object"
GATELESS = "fixture_gateless"


def _tightens(live: Any | None, document: Any) -> bool:
    """The fake comparator: a document saying so only tightens."""
    return isinstance(document, dict) and document.get("tighten") is True


@dataclass
class Hook:
    """The `object` kind's publish hook for these tests: records each version
    it ran for, with the transaction it ran in, or raises when told to."""

    calls: list[uuid.UUID] = field(default_factory=list)
    fail: bool = False

    async def __call__(self, tx: ArtifactTx, version_id: uuid.UUID) -> None:
        self.calls.append(version_id)
        if self.fail:
            raise RuntimeError("the hook could not apply the definition")


HOOK = Hook()
TEST_OBJECT = ArtifactKindEntry(
    kind=OBJECT,
    document_schema="dw.fixture/v1",
    read_key=FIXTURE_READ,
    write_key=FIXTURE_WRITE,
    submit_key=FIXTURE_SUBMIT,
    publish_hook=HOOK,
    validate=validate_fixture,
    extract=extract_fixture,
    compare=_tightens,
)
KINDS = (FIXTURE, FIXTURE_GATELESS, TEST_OBJECT)


@dataclass
class Controls:
    reason: str | None = None

    async def admission_state(
        self, tenant_id: uuid.UUID, artifacts: Sequence[uuid.UUID] = ()
    ) -> str | None:
        return self.reason


@dataclass
class World:
    studio: StudioWorld
    # read and submit in ws1, writes nothing: a submitter who is no author.
    submitter: Person
    # read and propose a Binding set in ws1.
    proposer: Person
    # read and approve a Binding set in ws1.
    binding_approver: Person

    def __getitem__(self, name: str) -> Person:
        return self.studio[name]


async def _plant(conn: Any, world: StudioWorld, keys: dict[str, str]) -> Person:
    tenant = world.tenant
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, world.ws1, user)
    role = await plant_role(conn, tenant.tenant_id, f"pub_{user.hex[:12]}", keys)
    await assign(conn, tenant.tenant_id, world.ws1, membership, role)
    return Person(user, tenant.tenant_id, world.ws1)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sessions(studio_db: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(migrator: AsyncEngine) -> AsyncIterator[World]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            studio = await plant_world(conn)
            submitter = await _plant(
                conn, studio, {FIXTURE_READ: "workspace", FIXTURE_SUBMIT: "workspace"}
            )
            proposer = await _plant(
                conn, studio, {FIXTURE_READ: "workspace", BINDINGS_PROPOSE_SCOPE: "workspace"}
            )
            approver = await _plant(
                conn,
                studio,
                {
                    FIXTURE_READ: "workspace",
                    BINDINGS_APPROVE_SCOPE: "workspace",
                    "approvals.decide": "workspace",
                },
            )
        yield World(studio, submitter, proposer, approver)


@pytest.fixture(autouse=True)
def _fresh_hook() -> None:
    HOOK.calls.clear()
    HOOK.fail = False


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def artifacts(sessions: async_sessionmaker[AsyncSession], world: World) -> ArtifactService:
    ids = Uuid7Generator()
    return ArtifactService(
        SqlArtifactStore(sessions, ids), ArtifactKindRegistry(KINDS), SystemClock(), ids
    )


def lifecycle_of(
    artifacts: ArtifactService, controls: Controls, bindings: PublishBindingsCheck
) -> LifecycleService:
    store = artifacts.store
    assert isinstance(store, SqlArtifactStore)
    return LifecycleService(
        SqlLifecycleStore(store), artifacts, controls, {}, SystemClock(), bindings=bindings
    )


@pytest.fixture
def controls() -> Controls:
    return Controls()


@pytest.fixture
def bindings() -> StubBindings:
    return StubBindings()


@pytest.fixture
def lifecycle(
    artifacts: ArtifactService, controls: Controls, bindings: StubBindings
) -> LifecycleService:
    return lifecycle_of(artifacts, controls, bindings)


@pytest.fixture
def settler(lifecycle: LifecycleService) -> PublishSettler:
    return PublishSettler(lifecycle)


# ---- helpers ----------------------------------------------------------------------


def _doc(*, tighten: bool = False, title: str = "Khách hàng", **extra: Any) -> dict[str, Any]:
    return {"title": title, "uses": [], "tighten": tighten, **extra}


async def created(
    artifacts: ArtifactService, who: Person, *, kind: str = OBJECT, document: Any = None
) -> tuple[uuid.UUID, uuid.UUID, int]:
    row, draft = await artifacts.create(
        who.context(),
        kind=kind,
        api_name=f"a_{uuid.uuid4().hex[:12]}",
        labels=[],
        document=_doc() if document is None else document,
    )
    return row.id, draft.id, draft.row_version


async def with_live(
    artifacts: ArtifactService,
    migrator: AsyncEngine,
    who: Person,
    *,
    kind: str = OBJECT,
    document: Any = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, int]:
    """An artifact whose v1 is live and whose v2 draft holds `document`:
    (artifact, v1, v2 draft, its ETag)."""
    artifact_id, _, row_version = await created(artifacts, who, kind=kind)
    async with artifacts.store.transaction(who.context()) as tx:
        v1 = await artifacts.seal(tx, artifact_id, row_version)
    await publish_for_test(migrator, v1.version_id)
    [(artifact_row_version,)] = await rows(
        migrator, "SELECT row_version FROM studio.artifacts WHERE id = :a", a=artifact_id
    )
    draft = await artifacts.create_draft(
        who.context(), artifact_id, ExpectedVersion(artifact_row_version)
    )
    saved = await artifacts.save_draft(
        who.context(),
        artifact_id,
        ExpectedVersion(draft.row_version),
        _doc() if document is None else document,
    )
    return artifact_id, v1.version_id, draft.id, saved.version.row_version


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def version(migrator: AsyncEngine, version_id: uuid.UUID) -> Any:
    return (
        await rows(migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=version_id)
    )[0]


async def audit_rows(migrator: AsyncEngine, artifact_id: uuid.UUID, action: str) -> list[Any]:
    return await rows(
        migrator,
        "SELECT actor_id, workspace_id, details FROM platform.audit_events"
        " WHERE resource_id = :a AND action = :x ORDER BY occurred_at",
        a=str(artifact_id),
        x=action,
    )


async def lives(migrator: AsyncEngine, version_id: uuid.UUID) -> int:
    found = await rows(
        migrator,
        "SELECT count(*) FROM platform.outbox_events WHERE event_type = :e AND aggregate_id = :v",
        e=VERSION_LIVE,
        v=version_id,
    )
    return int(found[0][0])


async def request_of(migrator: AsyncEngine, approval_id: uuid.UUID) -> Any:
    return (
        await rows(
            migrator, "SELECT * FROM platform.approval_requests WHERE id = :a", a=approval_id
        )
    )[0]


async def submit(
    lifecycle: LifecycleService,
    who: Person,
    artifact_id: uuid.UUID,
    version_id: uuid.UUID,
    row_version: int,
    *,
    kind: str = OBJECT,
) -> Submitted:
    return await lifecycle.submit(
        who.context(), kind, artifact_id, version_id, ExpectedVersion(row_version)
    )


async def awaiting(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: World,
    *,
    kind: str = OBJECT,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """v1 live, v2 submitted by `submitter` and awaiting approval:
    (artifact, v1, v2, its request)."""
    artifact_id, v1, v2, etag = await with_live(artifacts, migrator, world["writer"], kind=kind)
    moved = await submit(lifecycle, world.submitter, artifact_id, v2, etag, kind=kind)
    assert moved.version.stage.value == "awaiting_approval"
    assert moved.version.publish_approval_id is not None
    return artifact_id, v1, v2, moved.version.publish_approval_id


async def decided(
    migrator: AsyncEngine, approval_id: uuid.UUID, *, approve: bool = True
) -> uuid.UUID:
    decider = uuid.uuid4()
    async with migrator.begin() as conn:
        await decide_for_test(conn, approval_id, decided_by=decider, approve=approve)
    return decider


def reason(caught: pytest.ExceptionInfo[Any]) -> object:
    return caught.value.details.get("reason_code")


# ===================================================== R5.1: the request ==


async def test_r5_1_a_submit_that_does_not_only_tighten_opens_its_request(
    artifacts: ArtifactService, lifecycle: LifecycleService, migrator: AsyncEngine, world: World
) -> None:
    """In the submit's transaction: `studio.publish.object`, asked by the
    submitter, stamped, in the owning workspace, ids only, and the authors
    exactly the version's contributors and its submitter."""
    writer, co_writer = world["writer"], world["co_writer"]
    artifact_id, _, v2, _ = await with_live(artifacts, migrator, writer)
    saved = await artifacts.save_draft(
        co_writer.context(),
        artifact_id,
        ExpectedVersion((await version(migrator, v2)).row_version),
        _doc(title="sửa lần hai"),
    )

    moved = await submit(lifecycle, world.submitter, artifact_id, v2, saved.version.row_version)

    row = await version(migrator, v2)
    assert (row.stage, moved.version.stage.value) == ("awaiting_approval", "awaiting_approval")
    request = await request_of(migrator, row.publish_approval_id)
    assert (request.approval_type, request.status, request.required_scope) == (
        "studio.publish.object",
        "pending",
        "studio.publish.approve",
    )
    assert request.requested_by == row.submitted_by == world.submitter.id
    assert request.workspace_id == world.studio.ws1
    assert request.run_id is None
    assert set(request.payload) == {"artifact_id", "version_id", "author_ids"}
    assert request.payload["version_id"] == str(v2)
    assert request.payload["author_ids"] == [
        *(str(c) for c in row.contributor_ids),
        str(world.submitter.id),
    ]
    assert set(row.contributor_ids) == {writer.id, co_writer.id}
    assert not row.tighten_only and HOOK.calls == []


# ============================================ R2.8-R2.10: the gateless branch ==


async def test_r2_8_r2_9_r2_10_a_tighten_only_submit_goes_live_in_its_own_transaction(
    artifacts: ArtifactService, lifecycle: LifecycleService, migrator: AsyncEngine, world: World
) -> None:
    writer = world["writer"]
    artifact_id, v1, v2, etag = await with_live(
        artifacts, migrator, writer, document=_doc(tighten=True)
    )
    live_hash = (await version(migrator, v1)).definition_hash

    moved = await submit(lifecycle, world.submitter, artifact_id, v2, etag)

    row, old = await version(migrator, v2), await version(migrator, v1)
    assert (moved.version.stage.value, row.stage) == ("live", "live")
    assert row.tighten_only and row.compared_live_hash == live_hash
    assert row.publish_approval_id is None and row.published_by == world.submitter.id
    assert (old.stage, old.retire_reason_code) == ("retired", "superseded")
    assert HOOK.calls == [v2]
    [published] = await audit_rows(migrator, artifact_id, "studio.version.published")
    assert published.actor_id == world.submitter.id
    assert published.details["path"] == "tighten_only"
    assert await lives(migrator, v2) == 1
    requests = await rows(
        migrator,
        "SELECT count(*) FROM platform.approval_requests WHERE payload->>'version_id' = :v",
        v=str(v2),
    )
    assert requests == [(0,)]


async def test_r2_8_r2_10_not_tighten_only_or_no_live_waits_for_approval(
    artifacts: ArtifactService, lifecycle: LifecycleService, migrator: AsyncEngine, world: World
) -> None:
    writer = world["writer"]
    artifact_id, v1, v2, etag = await with_live(artifacts, migrator, writer)
    await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    row = await version(migrator, v2)
    assert (row.stage, row.tighten_only) == ("awaiting_approval", False)
    assert row.compared_live_hash == (await version(migrator, v1)).definition_hash

    first, first_v, first_etag = await created(artifacts, writer, document=_doc(tighten=True))
    await submit(lifecycle, world.submitter, first, first_v, first_etag)
    row = await version(migrator, first_v)
    assert (row.stage, row.tighten_only, row.compared_live_hash) == (
        "awaiting_approval",
        False,
        None,
    )
    assert row.publish_approval_id is not None and HOOK.calls == []


async def test_r2_8_a_kind_without_a_comparator_always_waits_for_approval(
    artifacts: ArtifactService, lifecycle: LifecycleService, migrator: AsyncEngine, world: World
) -> None:
    """The shape of `endpoint`: even a change that would only tighten."""
    artifact_id, _, v2, etag = await with_live(
        artifacts, migrator, world["writer"], kind=GATELESS, document=_doc(tighten=True)
    )
    await submit(lifecycle, world.submitter, artifact_id, v2, etag, kind=GATELESS)
    row = await version(migrator, v2)
    assert (row.stage, row.tighten_only) == ("awaiting_approval", False)
    request = await request_of(migrator, row.publish_approval_id)
    assert request.approval_type == "studio.publish.fixture_gateless"


async def test_r2_9_a_hook_that_fails_rolls_the_whole_submit_back(
    artifacts: ArtifactService, lifecycle: LifecycleService, migrator: AsyncEngine, world: World
) -> None:
    artifact_id, v1, v2, etag = await with_live(
        artifacts, migrator, world["writer"], document=_doc(tighten=True)
    )
    HOOK.fail = True
    with pytest.raises(RuntimeError):
        await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    row = await version(migrator, v2)
    assert (row.stage, row.version_no) == ("draft", None)
    assert (await version(migrator, v1)).stage == "live"
    assert await audit_rows(migrator, artifact_id, "studio.version.published") == []
    assert await audit_rows(migrator, artifact_id, "studio.version.submitted") == []
    assert await lives(migrator, v2) == 0


async def test_r2_12_a_stale_if_match_on_the_tighten_only_branch_is_412(
    artifacts: ArtifactService, lifecycle: LifecycleService, migrator: AsyncEngine, world: World
) -> None:
    """The submit's `If-Match` is what `seal` compares, never the draft's own
    `row_version`: a draft saved again since stays a draft."""
    writer = world["writer"]
    artifact_id, v1, v2, etag = await with_live(
        artifacts, migrator, writer, document=_doc(tighten=True)
    )
    await artifacts.save_draft(
        writer.context(), artifact_id, ExpectedVersion(etag), _doc(tighten=True, title="mới")
    )
    with pytest.raises(PreconditionFailedError) as stale:
        await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    assert reason(stale) == "stale_version"
    row = await version(migrator, v2)
    assert (row.stage, row.version_no) == ("draft", None)
    assert (await version(migrator, v1)).stage == "live"
    assert await audit_rows(migrator, artifact_id, "studio.version.submitted") == []
    assert HOOK.calls == []


# ==================================================== R2.11: the bindings ==


async def test_r2_11_tighten_only_with_an_unset_binding_is_refused_409(
    artifacts: ArtifactService,
    controls: Controls,
    migrator: AsyncEngine,
    world: World,
) -> None:
    lifecycle = lifecycle_of(artifacts, controls, StubBindings(unset=("principal",)))
    artifact_id, v1, v2, etag = await with_live(
        artifacts, migrator, world["writer"], document=_doc(tighten=True)
    )
    with pytest.raises(ConflictError) as refused:
        await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    assert reason(refused) == "binding_unset"
    assert refused.value.details["bindings"] == ["principal"]
    assert (await version(migrator, v2)).stage == "draft"
    assert (await version(migrator, v1)).stage == "live"
    assert await audit_rows(migrator, artifact_id, "studio.version.submitted") == []
    assert HOOK.calls == []


async def test_r2_11_on_the_approval_branch_the_202_names_them(
    artifacts: ArtifactService, controls: Controls, migrator: AsyncEngine, world: World
) -> None:
    stub = StubBindings(unset=("principal",))
    lifecycle = lifecycle_of(artifacts, controls, stub)
    artifact_id, _, v2, etag = await with_live(artifacts, migrator, world["writer"])
    moved = await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    assert moved.version.stage.value == "awaiting_approval"
    assert moved.binding_unset == ("principal",)
    assert stub.asked == [v2]


async def test_r2_11_r5_10_a_real_principal_binding_unset_then_approved(
    artifacts: ArtifactService,
    controls: Controls,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """tenant-config/05's `BindingStatus`, in the submit's own transaction:
    the first version of a kind without a comparator declares a required
    `principal`; the 202 names it; approved while still unset, the handler
    sends it back `binding_unset`. Once a Binding set is approved for it, the
    next submit names nothing and its approval goes live."""
    ids, clock = Uuid7Generator(), SystemClock()
    store = artifacts.store
    assert isinstance(store, SqlArtifactStore)
    usability = ConnectionUsability(
        store=SqlConnectionStore(sessions), catalog=NoConnectorCatalog()
    )
    types = platform_binding_types(usability)
    lifecycle = lifecycle_of(artifacts, controls, BindingStatus(store, types))
    settler = PublishSettler(lifecycle)
    principal = {"name": "principal", "kind": "principal", "required": True}
    writer = world["writer"]
    artifact_id, v1, etag = await created(
        artifacts, writer, kind=GATELESS, document=_doc(bindings=[principal])
    )

    first = await submit(lifecycle, world.submitter, artifact_id, v1, etag, kind=GATELESS)
    assert first.binding_unset == ("principal",)
    approval = first.version.publish_approval_id
    assert approval is not None
    decider = await decided(migrator, approval)
    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "binding_unset"
    row = await version(migrator, v1)
    assert (row.stage, row.publish_approval_id) == ("draft", None)
    [sent_back] = await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft")
    assert sent_back.actor_id == decider
    assert sent_back.details["reason_code"] == "binding_unset"
    assert sent_back.details["lane"] == "outbox"

    # The Binding set proposed and approved for the sealed version.
    config_kinds = ConfigKindRegistry([BindingSets(store, artifacts.registry, types, usability)])
    config_store = SqlConfigVersionStore(sessions)
    again = await submit(
        lifecycle,
        world.submitter,
        artifact_id,
        v1,
        (await version(migrator, v1)).row_version,
        kind=GATELESS,
    )
    assert again.binding_unset == ("principal",)
    proposal = await ConfigVersionService(config_kinds, config_store, clock, ids).propose(
        world.proposer.context(),
        BINDING_SET,
        str(artifact_id),
        {"values": {"principal": str(world["writer"].id)}},
    )
    flow = ApproveAndResumeService(
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        runner=cast(Any, None),
        run_store=cast(Any, None),
        clock=clock,
        id_generator=ids,
        run_control=OpenRunControl(),
        strict_approval_prefixes=frozenset({CONFIG_PREFIX}),
        decision_guards={CONFIG_VERSION: ConfigVersionDecisions(config_kinds, config_store)},
    )
    approver = world.binding_approver
    await flow.decide(
        approval_id=proposal.approval_id,
        approve=True,
        comment="đã xem",
        context=AccessContext(
            tenant_id=approver.tenant_id,
            workspace_id=proposal.workspace_id,
            principal_id=approver.id,
            roles=frozenset(),
            scopes=frozenset({"approvals.decide", BINDINGS_APPROVE_SCOPE}),
            plan_id="professional",
        ),
        authorization=ScopeAuthorizationService(),
    )
    assert (
        await ConfigSettlement(config_store, clock, ids).settle(
            WorkScope(proposal.tenant_id, proposal.workspace_id), proposal.approval_id
        )
        == "approved"
    )
    assert (
        await lifecycle.submitted(world.submitter.context(), GATELESS, artifact_id, v1)
    ).binding_unset == ()
    approval = (await version(migrator, v1)).publish_approval_id
    assert approval is not None
    await decided(migrator, approval)
    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "published"
    assert (await version(migrator, v1)).stage == "live"


# ================================================ R7.9, R7.13: the freeze ==


@pytest.mark.parametrize(
    ("frozen", "tighten", "refused"),
    [
        ("tenant_frozen", False, "tenant_frozen"),
        ("platform_frozen", True, "platform_frozen"),
        ("platform_frozen", False, "platform_frozen"),
        ("control_state_unavailable", True, "control_state_unavailable"),
        ("control_state_unavailable", False, "control_state_unavailable"),
    ],
)
async def test_r7_9_a_freeze_refuses_the_submit_and_keeps_the_draft(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    controls: Controls,
    migrator: AsyncEngine,
    world: World,
    frozen: str,
    tighten: bool,
    refused: str,
) -> None:
    artifact_id, v1, v2, etag = await with_live(
        artifacts, migrator, world["writer"], document=_doc(tighten=tighten)
    )
    controls.reason = frozen
    with pytest.raises(ConflictError) as caught:
        await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    assert reason(caught) == refused
    row = await version(migrator, v2)
    assert (row.stage, row.version_no) == ("draft", None)
    assert (await version(migrator, v1)).stage == "live"
    assert HOOK.calls == []


async def test_r7_9_a_freeze_and_an_unset_binding_answer_with_the_freeze(
    artifacts: ArtifactService, controls: Controls, migrator: AsyncEngine, world: World
) -> None:
    lifecycle = lifecycle_of(artifacts, controls, StubBindings(unset=("principal",)))
    artifact_id, _, v2, etag = await with_live(
        artifacts, migrator, world["writer"], document=_doc(tighten=True)
    )
    controls.reason = "platform_frozen"
    with pytest.raises(ConflictError) as caught:
        await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    assert reason(caught) == "platform_frozen"


async def test_r7_13_a_companys_freeze_lets_a_tighten_only_submit_through(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    controls: Controls,
    migrator: AsyncEngine,
    world: World,
) -> None:
    artifact_id, _, v2, etag = await with_live(
        artifacts, migrator, world["writer"], document=_doc(tighten=True)
    )
    controls.reason = "tenant_frozen"
    moved = await submit(lifecycle, world.submitter, artifact_id, v2, etag)
    assert moved.version.stage.value == "live"
    [published] = await audit_rows(migrator, artifact_id, "studio.version.published")
    assert published.details["path"] == "tighten_only"


# ============================================== R5.5: the decision settled ==


async def test_r5_5_approved_goes_live_once_in_the_deciders_name(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    migrator: AsyncEngine,
    world: World,
) -> None:
    artifact_id, v1, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    decider = await decided(migrator, approval)
    tenant = world.studio.tenant.tenant_id

    assert await settler.settle(tenant, approval) == "published"
    assert await settler.settle(tenant, approval) == "ignored"  # delivered again

    row, old = await version(migrator, v2), await version(migrator, v1)
    assert (row.stage, row.published_by) == ("live", decider)
    assert (old.stage, old.retire_reason_code, old.retired_by) == (
        "retired",
        "superseded",
        decider,
    )
    assert HOOK.calls == [v2]
    [published] = await audit_rows(migrator, artifact_id, "studio.version.published")
    assert published.actor_id == decider
    assert published.workspace_id == world.studio.ws1
    assert (published.details["path"], published.details["lane"]) == ("approved", "outbox")
    assert published.details["approval_id"] == str(approval)
    assert await lives(migrator, v2) == 1


async def test_r5_5_a_hook_that_fails_is_retried_with_nothing_published(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    migrator: AsyncEngine,
    world: World,
) -> None:
    artifact_id, v1, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    await decided(migrator, approval)
    HOOK.fail = True
    with pytest.raises(RuntimeError):
        await settler.settle(world.studio.tenant.tenant_id, approval)
    assert (await version(migrator, v2)).stage == "awaiting_approval"
    assert (await version(migrator, v1)).stage == "live"
    assert await audit_rows(migrator, artifact_id, "studio.version.published") == []
    HOOK.fail = False
    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "published"


async def test_r5_5_rejected_goes_back_to_the_draft_in_the_deciders_name(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    migrator: AsyncEngine,
    world: World,
) -> None:
    artifact_id, v1, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    decider = await decided(migrator, approval, approve=False)

    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "rejected"
    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "ignored"

    row = await version(migrator, v2)
    assert (row.stage, row.publish_approval_id, row.submitted_by) == ("draft", None, None)
    assert (await version(migrator, v1)).stage == "live"
    [sent_back] = await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft")
    assert sent_back.actor_id == decider
    assert (sent_back.details["reason_code"], sent_back.details["lane"]) == (
        "rejected",
        "outbox",
    )


async def test_r5_5_a_withdrawn_versions_decision_changes_nothing(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    migrator: AsyncEngine,
    world: World,
) -> None:
    """Withdrawn first (its request cancelled), then a decision recorded on
    it by hand: the handler finds no version waiting on the request."""
    artifact_id, _, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    await lifecycle.withdraw(world["writer"].context(), OBJECT, artifact_id, v2)
    await rows(
        migrator,
        "UPDATE platform.approval_requests SET status = 'pending' WHERE id = :a",
        a=approval,
    )
    await decided(migrator, approval)
    before = await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft")

    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "ignored"
    assert await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft") == before
    assert (await version(migrator, v2)).stage == "draft"


# ===================== R5.9, R5.10, R7.12: approved but not carried out ==


async def test_r5_9_the_live_version_retired_meanwhile_sends_it_back_base_changed(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    migrator: AsyncEngine,
    world: World,
) -> None:
    """AL19: retired `explicit` through `LifecycleService` while the
    candidate waits; without the handler's check the trigger refuses `live`
    (23514) and the version stays waiting."""
    artifact_id, v1, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    await lifecycle.retire(world["retirer"].context(), OBJECT, artifact_id, v1)
    decider = await decided(migrator, approval)

    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "base_changed"

    row = await version(migrator, v2)
    assert (row.stage, row.compared_live_hash) == ("draft", None)
    live = await rows(
        migrator,
        "SELECT count(*) FROM studio.artifact_versions WHERE artifact_id = :a AND stage = 'live'",
        a=artifact_id,
    )
    assert live == [(0,)]
    [sent_back] = await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft")
    assert (sent_back.actor_id, sent_back.details["reason_code"]) == (decider, "base_changed")
    assert HOOK.calls == []


async def test_r5_10_an_unset_binding_sends_it_back_once(
    artifacts: ArtifactService,
    controls: Controls,
    migrator: AsyncEngine,
    world: World,
) -> None:
    stub = StubBindings()
    lifecycle = lifecycle_of(artifacts, controls, stub)
    artifact_id, v1, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    decider = await decided(migrator, approval)
    stub.unset = ("principal",)
    settler = PublishSettler(lifecycle)

    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "binding_unset"
    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "ignored"

    assert (await version(migrator, v2)).stage == "draft"
    assert (await version(migrator, v1)).stage == "live"
    [sent_back] = await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft")
    assert (sent_back.actor_id, sent_back.details["reason_code"]) == (decider, "binding_unset")
    assert stub.asked[-1] == v2


async def test_r5_5_a_bindings_check_that_raises_is_retried(
    artifacts: ArtifactService, controls: Controls, migrator: AsyncEngine, world: World
) -> None:
    stub = StubBindings()
    lifecycle = lifecycle_of(artifacts, controls, stub)
    artifact_id, _, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    await decided(migrator, approval)
    settler = PublishSettler(lifecycle)
    stub.fail = True
    with pytest.raises(RuntimeError):
        await settler.settle(world.studio.tenant.tenant_id, approval)
    assert (await version(migrator, v2)).stage == "awaiting_approval"
    assert await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft") == []
    stub.fail = False
    assert await settler.settle(world.studio.tenant.tenant_id, approval) == "published"


@pytest.mark.parametrize("frozen", ["tenant_frozen", "platform_frozen"])
async def test_r7_12_a_freeze_sends_an_approved_version_back(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    controls: Controls,
    migrator: AsyncEngine,
    world: World,
    frozen: str,
) -> None:
    artifact_id, v1, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    decider = await decided(migrator, approval)
    controls.reason = frozen

    assert await settler.settle(world.studio.tenant.tenant_id, approval) == frozen

    assert (await version(migrator, v2)).stage == "draft"
    assert (await version(migrator, v1)).stage == "live"
    [sent_back] = await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft")
    assert (sent_back.actor_id, sent_back.details["reason_code"]) == (decider, frozen)


async def test_r7_12_run_controls_that_do_not_answer_are_retried(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    controls: Controls,
    migrator: AsyncEngine,
    world: World,
) -> None:
    artifact_id, _, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    await decided(migrator, approval)
    controls.reason = "control_state_unavailable"
    with pytest.raises(Exception, match="did not answer"):
        await settler.settle(world.studio.tenant.tenant_id, approval)
    assert (await version(migrator, v2)).stage == "awaiting_approval"
    assert await audit_rows(migrator, artifact_id, "studio.version.returned_to_draft") == []


async def test_another_companys_request_is_not_found(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    settler: PublishSettler,
    migrator: AsyncEngine,
    world: World,
) -> None:
    """The tenant is the envelope's: B's settler reads none of A's rows."""
    _, _, v2, approval = await awaiting(artifacts, lifecycle, migrator, world)
    await decided(migrator, approval)
    with pytest.raises(Exception, match="no decided publish request"):
        await settler.settle(world.studio.other.tenant_id, approval)
    assert (await version(migrator, v2)).stage == "awaiting_approval"


# ======================================================= R5.6: the backstop ==


async def test_r5_6_live_while_the_request_is_pending_is_refused_by_the_trigger(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: World,
) -> None:
    """`go_live` called past the handler: 23514 read back as `stage_refused`."""
    artifact_id, v1, v2, _ = await awaiting(artifacts, lifecycle, migrator, world)
    with pytest.raises(ConflictError) as refused:
        async with lifecycle.store.transaction(world["retirer"].context()) as tx:
            candidate = next(v for v in await tx.envelope.versions(artifact_id) if v.id == v2)
            await lifecycle.go_live(tx, OBJECT, candidate, actor_id=uuid.uuid4())
    assert reason(refused) == "stage_refused"
    assert (await version(migrator, v2)).stage == "awaiting_approval"
    assert (await version(migrator, v1)).stage == "live"
