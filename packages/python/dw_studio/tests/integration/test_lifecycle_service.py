"""`LifecycleService` over the real store (agent-lifecycle ticket 03): submit,
withdraw, retire and the move to `live`, each in one transaction as `dw_app`
(R1.3, R1.4, R2.1-R2.7, R2.10, R2.12, R7.9).

The kinds are the test kinds: `fixture` (gated, the one whose submit this
ticket builds) and `fixture_gateless` (whose candidates and live versions the
legal path of `dw_studio.testing.lifecycle` places). The run controls are a
stand-in answering what a test sets, and the per-kind checks are the test's.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

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

from dw_kernel.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
)
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.adapters.artifact_store import SqlArtifactStore, SqlArtifactTx
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.lifecycle.adapters.store import SqlLifecycleStore
from dw_studio.lifecycle.application.ports import SubmitCheck
from dw_studio.lifecycle.application.service import LifecycleService
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import (
    RefusingCheck,
    StubBindings,
    decide_for_test,
    move_for_test,
    publish_for_test,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


@dataclass
class Controls:
    """The run controls' one question, answered with what the test sets."""

    reason: str | None = None
    asked: list[uuid.UUID] = field(default_factory=list)

    async def admission_state(
        self, tenant_id: uuid.UUID, artifacts: Sequence[uuid.UUID] = ()
    ) -> str | None:
        self.asked.append(tenant_id)
        return self.reason


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_engine(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(migrator: AsyncEngine) -> AsyncIterator[StudioWorld]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            planted = await plant_world(conn)
        yield planted


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def artifacts(app_engine: AsyncEngine, world: StudioWorld) -> ArtifactService:
    ids = Uuid7Generator()
    sessions = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    return ArtifactService(
        SqlArtifactStore(sessions, ids), ArtifactKindRegistry(FIXTURE_KINDS), SystemClock(), ids
    )


def lifecycle_of(
    artifacts: ArtifactService,
    controls: Controls | None = None,
    checks: Mapping[str, Sequence[SubmitCheck]] | None = None,
) -> LifecycleService:
    store = artifacts.store
    assert isinstance(store, SqlArtifactStore)
    return LifecycleService(
        SqlLifecycleStore(store),
        artifacts,
        controls or Controls(),
        checks or {},
        SystemClock(),
        bindings=StubBindings(),
    )


@pytest.fixture
def lifecycle(artifacts: ArtifactService) -> LifecycleService:
    return lifecycle_of(artifacts)


def name() -> str:
    return f"a_{uuid.uuid4().hex[:12]}"


async def created(
    artifacts: ArtifactService,
    who: Person,
    *,
    kind: str = "fixture",
    uses: Sequence[uuid.UUID] = (),
) -> tuple[uuid.UUID, uuid.UUID, int]:
    row, draft = await artifacts.create(
        who.context(),
        kind=kind,
        api_name=name(),
        labels=[],
        document={"title": "Khách hàng", "uses": [str(u) for u in uses]},
    )
    return row.id, draft.id, draft.row_version


async def live_one(
    artifacts: ArtifactService,
    migrator: AsyncEngine,
    who: Person,
    *,
    uses: Sequence[uuid.UUID] = (),
) -> tuple[uuid.UUID, uuid.UUID]:
    """A `fixture_gateless` artifact whose v1 is live."""
    artifact_id, _, row_version = await created(artifacts, who, kind="fixture_gateless", uses=uses)
    async with artifacts.store.transaction(who.context()) as tx:
        sealed = await artifacts.seal(tx, artifact_id, row_version)
    await publish_for_test(migrator, sealed.version_id)
    return artifact_id, sealed.version_id


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


async def version(migrator: AsyncEngine, version_id: uuid.UUID) -> Any:
    return (
        await rows(migrator, "SELECT * FROM studio.artifact_versions WHERE id = :v", v=version_id)
    )[0]


async def audits(migrator: AsyncEngine, artifact_id: uuid.UUID, action: str) -> int:
    found = await rows(
        migrator,
        "SELECT count(*) FROM platform.audit_events WHERE resource_id = :a AND action = :x",
        a=str(artifact_id),
        x=action,
    )
    return int(found[0][0])


# ================================================================ submit ==


async def test_r2_1_a_submit_seals_records_and_moves_to_evaluating_in_one_go(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """AL3: closure, definition hash, where-used, `submitted_by` and the
    audit; `evaluating` with no gate run (ADR-0120 decision 1)."""
    writer = world["writer"]
    target, target_v1 = await live_one(artifacts, migrator, writer)
    artifact_id, version_id, row_version = await created(artifacts, writer, uses=[target])

    moved = (
        await lifecycle.submit(
            writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
        )
    ).version

    row = await version(migrator, version_id)
    assert (moved.stage.value, row.stage, row.version_no) == ("evaluating", "evaluating", 1)
    assert row.gate_run_id is None and row.submitted_by == writer.id
    assert row.submitted_at is not None and row.compared_live_hash is None
    manifest = await rows(
        migrator,
        "SELECT body FROM studio.definition_manifests WHERE hash = :h",
        h=row.definition_hash,
    )
    assert [c["key"] for c in manifest[0].body["closure"]] == [str(target)]
    pinned = await rows(
        migrator,
        "SELECT to_version_id FROM studio.dependencies WHERE from_version_id = :v",
        v=version_id,
    )
    assert pinned == [(target_v1,)]
    assert await audits(migrator, artifact_id, "studio.version.submitted") == 1


async def test_r2_10_a_submit_records_the_live_version_it_was_compared_with(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """The gated `fixture` kind has no live version until ticket 06, so its
    v1 goes live by the gateless kind's path played by hand (flag lowered
    for the move, raised again before the submit)."""
    writer = world["writer"]
    artifact_id, _, row_version = await created(artifacts, writer)
    async with artifacts.store.transaction(writer.context()) as tx:
        v1 = await artifacts.seal(tx, artifact_id, row_version)
    flag = "UPDATE studio.artifact_kinds SET has_quality_gate = :g WHERE kind = 'fixture'"
    await rows(migrator, flag, g=False)
    try:
        await publish_for_test(migrator, v1.version_id)
    finally:
        await rows(migrator, flag, g=True)
    draft = await artifacts.create_draft(writer.context(), artifact_id, ExpectedVersion(1))

    await lifecycle.submit(
        writer.context(), "fixture", artifact_id, draft.id, ExpectedVersion(draft.row_version)
    )

    assert (await version(migrator, draft.id)).compared_live_hash == v1.definition_hash


async def test_r2_2_one_content_and_closure_give_one_hash_and_a_moved_pin_another(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    target, _ = await live_one(artifacts, migrator, writer)
    first, first_v, rv1 = await created(artifacts, writer, uses=[target])
    second, second_v, rv2 = await created(artifacts, writer, uses=[target])
    await lifecycle.submit(writer.context(), "fixture", first, first_v, ExpectedVersion(rv1))
    await lifecycle.submit(writer.context(), "fixture", second, second_v, ExpectedVersion(rv2))
    a, b = await version(migrator, first_v), await version(migrator, second_v)
    # The root names its own artifact, so the hashes differ by it alone: the
    # closures are equal.
    assert a.content_hash == b.content_hash
    closures = [
        (await rows(migrator, "SELECT body FROM studio.definition_manifests WHERE hash = :h", h=h))[
            0
        ].body["closure"]
        for h in (a.definition_hash, b.definition_hash)
    ]
    assert closures[0] == closures[1]

    # The target moves to v2: the same root content, sealed again, hashes anew.
    draft = await artifacts.create_draft(writer.context(), target, ExpectedVersion(1))
    saved = (
        await artifacts.save_draft(
            writer.context(), target, ExpectedVersion(draft.row_version), {"title": "v2"}
        )
    ).version
    async with artifacts.store.transaction(writer.context()) as tx:
        target_v2 = await artifacts.seal(tx, target, saved.row_version)
    await publish_for_test(migrator, target_v2.version_id)
    third, third_v, rv3 = await created(artifacts, writer, uses=[target])
    await lifecycle.submit(writer.context(), "fixture", third, third_v, ExpectedVersion(rv3))
    assert (await version(migrator, third_v)).definition_hash not in (
        a.definition_hash,
        b.definition_hash,
    )
    # Same root content, same pin: same hash, which the root id alone moves.
    assert (await version(migrator, third_v)).content_hash == a.content_hash


@pytest.mark.parametrize("where", ["audit", "check"])
async def test_r2_3_a_submit_that_fails_midway_leaves_nothing(
    artifacts: ArtifactService,
    migrator: AsyncEngine,
    world: StudioWorld,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
) -> None:
    """The audit write fails, or a check raises instead of answering: no
    number, manifest, where-used row or audit, and the version in `draft`."""
    writer = world["writer"]
    target, _ = await live_one(artifacts, migrator, writer)
    artifact_id, version_id, row_version = await created(artifacts, writer, uses=[target])
    check = RefusingCheck(fail=True)
    lifecycle = lifecycle_of(artifacts, checks={"fixture": [check]} if where == "check" else {})
    if where == "audit":

        async def fail(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("the audit store went away")

        monkeypatch.setattr(SqlArtifactTx, "audit", fail)
    manifests = await rows(migrator, "SELECT count(*) FROM studio.definition_manifests")

    with pytest.raises(RuntimeError):
        await lifecycle.submit(
            writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
        )

    row = await version(migrator, version_id)
    assert (row.stage, row.version_no, row.definition_hash) == ("draft", None, None)
    assert await rows(
        migrator,
        "SELECT count(*) FROM studio.dependencies WHERE from_version_id = :v",
        v=version_id,
    ) == [(0,)]
    assert await rows(migrator, "SELECT count(*) FROM studio.definition_manifests") == manifests
    assert await audits(migrator, artifact_id, "studio.version.submitted") == 0
    assert check.calls == (1 if where == "check" else 0)


async def test_r2_7_a_refusing_check_of_the_kind_answers_422_and_keeps_the_draft(
    artifacts: ArtifactService, migrator: AsyncEngine, world: StudioWorld
) -> None:
    """AL10: the kind's check refuses; another kind's never runs."""
    writer = world["writer"]
    check, other = RefusingCheck("capability_refused"), RefusingCheck()
    lifecycle = lifecycle_of(artifacts, checks={"fixture": [check], "fixture_gateless": [other]})
    artifact_id, version_id, row_version = await created(artifacts, writer)
    manifests = await rows(migrator, "SELECT count(*) FROM studio.definition_manifests")

    with pytest.raises(DomainError) as refused:
        await lifecycle.submit(
            writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
        )

    assert refused.value.details["reason_code"] == "capability_refused"
    assert (check.calls, other.calls) == (1, 0)
    row = await version(migrator, version_id)
    assert (row.stage, row.version_no) == ("draft", None)
    assert await rows(migrator, "SELECT count(*) FROM studio.definition_manifests") == manifests
    assert await audits(migrator, artifact_id, "studio.version.submitted") == 0


async def test_r2_12_a_stale_if_match_is_412_before_any_number(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    artifact_id, version_id, row_version = await created(artifacts, writer)
    await artifacts.save_draft(
        world["co_writer"].context(), artifact_id, ExpectedVersion(row_version), {"title": "x"}
    )

    with pytest.raises(PreconditionFailedError) as refused:
        await lifecycle.submit(
            writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
        )
    assert refused.value.details["reason_code"] == "stale_version"
    row = await version(migrator, version_id)
    assert (row.stage, row.version_no) == ("draft", None)
    assert await rows(
        migrator, "SELECT last_version_no FROM studio.artifacts WHERE id = :a", a=artifact_id
    ) == [(0,)]
    assert await audits(migrator, artifact_id, "studio.version.submitted") == 0

    await lifecycle.submit(
        writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version + 1)
    )
    assert (await version(migrator, version_id)).stage == "evaluating"


@pytest.mark.parametrize(
    "reason", ["tenant_frozen", "platform_frozen", "control_state_unavailable"]
)
async def test_r7_9_a_stopped_company_submits_nothing(
    artifacts: ArtifactService, migrator: AsyncEngine, world: StudioWorld, reason: str
) -> None:
    writer = world["writer"]
    controls = Controls(reason)
    lifecycle = lifecycle_of(artifacts, controls)
    artifact_id, version_id, row_version = await created(artifacts, writer)

    with pytest.raises(ConflictError) as refused:
        await lifecycle.submit(
            writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
        )

    assert refused.value.details["reason_code"] == reason
    assert controls.asked == [writer.tenant_id]
    row = await version(migrator, version_id)
    assert (row.stage, row.version_no, row.definition_hash) == ("draft", None, None)


async def test_r1_3_two_submits_of_one_draft_make_one_candidate(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """AL2: the same `If-Match` twice at once: one moves, one 409
    `candidate_exists` (never a 412 or a 404), one audit."""
    writer = world["writer"]
    artifact_id, version_id, row_version = await created(artifacts, writer)
    outcomes = await asyncio.gather(
        *(
            lifecycle.submit(
                writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    refused = [o for o in outcomes if isinstance(o, Exception)]
    assert len(refused) == 1 and isinstance(refused[0], ConflictError), outcomes
    assert refused[0].details["reason_code"] == "candidate_exists"
    assert (await version(migrator, version_id)).version_no == 1
    assert await audits(migrator, artifact_id, "studio.version.submitted") == 1


@pytest.mark.parametrize(
    ("who", "kind", "error"),
    [
        ("reader", "fixture", PermissionDeniedError),  # reads, lacks the submit key
        ("ws2_writer", "fixture", NotFoundError),  # the key, in another workspace
        ("outsider", "fixture", NotFoundError),  # another company
        ("writer", "fixture_gateless", NotFoundError),  # the segment names another kind
    ],
)
async def test_r2_1_who_may_submit(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
    who: str,
    kind: str,
    error: type[Exception],
) -> None:
    artifact_id, version_id, row_version = await created(artifacts, world["writer"])
    with pytest.raises(error):
        await lifecycle.submit(
            world[who].context(), kind, artifact_id, version_id, ExpectedVersion(row_version)
        )
    row = await version(migrator, version_id)
    assert (row.stage, row.version_no) == ("draft", None)


async def test_r2_1_a_version_that_is_not_this_artifacts_draft_is_404_and_seals_nothing(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    artifact_id, version_id, row_version = await created(artifacts, writer)
    _, elsewhere, _ = await created(artifacts, writer)
    for wrong in (elsewhere, uuid.uuid4()):
        with pytest.raises(NotFoundError):
            await lifecycle.submit(
                writer.context(), "fixture", artifact_id, wrong, ExpectedVersion(row_version)
            )
    row = await version(migrator, version_id)
    assert (row.stage, row.version_no) == ("draft", None)


# ============================================================== withdraw ==


async def test_r2_4_any_submit_key_holder_withdraws_a_candidate_and_its_request(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """Submitted by the writer, withdrawn by the co-writer: back to `draft`,
    the request `cancelled`, every submit column cleared, number and hashes
    kept until the next save, then saved on that very version."""
    writer, co_writer = world["writer"], world["co_writer"]
    artifact_id, version_id, row_version = await created(artifacts, writer, kind="fixture_gateless")
    async with artifacts.store.transaction(writer.context()) as tx:
        await artifacts.seal(tx, artifact_id, row_version)
    await move_for_test(migrator, version_id, "awaiting_approval")
    approval = (await version(migrator, version_id)).publish_approval_id
    with pytest.raises(ConflictError) as pending:
        await artifacts.create_draft(co_writer.context(), artifact_id, ExpectedVersion(1))
    assert pending.value.details["reason_code"] == "candidate_pending"

    moved = await lifecycle.withdraw(
        co_writer.context(), "fixture_gateless", artifact_id, version_id
    )

    row = await version(migrator, version_id)
    assert moved.stage.value == row.stage == "draft"
    assert (row.publish_approval_id, row.submitted_by, row.compared_live_hash) == (None,) * 3
    assert row.version_no == 1 and row.definition_hash is not None
    assert await rows(
        migrator, "SELECT status FROM platform.approval_requests WHERE id = :a", a=approval
    ) == [("cancelled",)]
    withdrawn = await rows(
        migrator,
        "SELECT actor_id, details FROM platform.audit_events"
        " WHERE resource_id = :a AND action = 'studio.version.returned_to_draft'",
        a=str(artifact_id),
    )
    assert [(r.actor_id, r.details["reason_code"]) for r in withdrawn] == [
        (co_writer.id, "withdrawn")
    ]
    saved = (
        await artifacts.save_draft(
            co_writer.context(), artifact_id, ExpectedVersion(row.row_version), {"title": "sửa"}
        )
    ).version
    assert saved.id == version_id and saved.version_no is None
    assert await rows(
        migrator,
        "SELECT count(*) FROM studio.artifact_versions WHERE artifact_id = :a",
        a=artifact_id,
    ) == [(1,)]


async def test_r2_4_a_gated_candidate_in_evaluating_is_withdrawn(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer = world["writer"]
    artifact_id, version_id, row_version = await created(artifacts, writer)
    await lifecycle.submit(
        writer.context(), "fixture", artifact_id, version_id, ExpectedVersion(row_version)
    )
    await lifecycle.withdraw(writer.context(), "fixture", artifact_id, version_id)
    row = await version(migrator, version_id)
    assert (row.stage, row.submitted_by) == ("draft", None)


async def test_r2_4_what_cannot_be_withdrawn(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """A draft: 409 `not_a_candidate`; a decided request: the same, nothing
    changed; without the submit key: 403."""
    writer = world["writer"]
    artifact_id, version_id, _ = await created(artifacts, writer, kind="fixture_gateless")
    with pytest.raises(ConflictError) as draft:
        await lifecycle.withdraw(writer.context(), "fixture_gateless", artifact_id, version_id)
    assert draft.value.details["reason_code"] == "not_a_candidate"

    with pytest.raises(PermissionDeniedError):
        await lifecycle.withdraw(
            world["reader"].context(), "fixture_gateless", artifact_id, version_id
        )

    async with artifacts.store.transaction(writer.context()) as tx:
        await artifacts.seal(tx, artifact_id, 1)
    await move_for_test(migrator, version_id, "awaiting_approval")
    approval = (await version(migrator, version_id)).publish_approval_id
    assert approval is not None
    async with migrator.begin() as conn:
        await decide_for_test(conn, approval, decided_by=world["co_writer"].id, approve=False)
    with pytest.raises(ConflictError) as decided:
        await lifecycle.withdraw(writer.context(), "fixture_gateless", artifact_id, version_id)
    assert decided.value.details["reason_code"] == "not_a_candidate"
    assert (await version(migrator, version_id)).stage == "awaiting_approval"


async def test_al36_a_segment_naming_another_kind_withdraws_nothing(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """A `fixture_gateless` candidate under the `fixture` segment: 404 as if it
    did not exist, the candidate and its request untouched. Withdraw asks no
    gate flag, so the kind check alone answers."""
    writer = world["writer"]
    artifact_id, version_id, row_version = await created(artifacts, writer, kind="fixture_gateless")
    async with artifacts.store.transaction(writer.context()) as tx:
        await artifacts.seal(tx, artifact_id, row_version)
    await move_for_test(migrator, version_id, "awaiting_approval")
    before = await version(migrator, version_id)

    with pytest.raises(NotFoundError):
        await lifecycle.withdraw(writer.context(), "fixture", artifact_id, version_id)

    assert await version(migrator, version_id) == before


# ================================================================ retire ==


async def test_r2_5_a_live_version_nobody_uses_is_retired_explicitly(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    artifact_id, version_id = await live_one(artifacts, migrator, world["writer"])
    retirer = world["retirer"]

    moved = await lifecycle.retire(retirer.context(), "fixture_gateless", artifact_id, version_id)

    row = await version(migrator, version_id)
    assert moved.stage.value == row.stage == "retired"
    assert (row.retire_reason_code, row.retired_by) == ("explicit", retirer.id)
    assert await audits(migrator, artifact_id, "studio.version.retired") == 1


async def test_r2_6_a_version_another_live_version_pins_is_in_use(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """One dependent the retirer reads (named), one in ws2 (counted); a v2
    whose dependents pin only the retired v1 is retired."""
    writer, retirer = world["writer"], world["retirer"]
    target, v1 = await live_one(artifacts, migrator, writer)
    named, _ = await live_one(artifacts, migrator, writer, uses=[target])
    await live_one(artifacts, migrator, world["ws2_writer"], uses=[target])

    with pytest.raises(ConflictError) as refused:
        await lifecycle.retire(retirer.context(), "fixture_gateless", target, v1)
    details: dict[str, Any] = dict(refused.value.details)
    assert details["reason_code"] == "artifact_in_use"
    assert [d["artifact_id"] for d in details["dependents"]] == [str(named)]
    assert details["hidden"] == 1
    assert (await version(migrator, v1)).stage == "live"

    draft = await artifacts.create_draft(writer.context(), target, ExpectedVersion(1))
    async with artifacts.store.transaction(writer.context()) as tx:
        v2 = await artifacts.seal(tx, target, draft.row_version)
    await publish_for_test(migrator, v2.version_id)
    await lifecycle.retire(retirer.context(), "fixture_gateless", target, v2.version_id)
    assert (await version(migrator, v2.version_id)).stage == "retired"


async def test_r2_6_what_cannot_be_retired(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """A draft: 409 `not_live`; the writer, without the retire key: 403."""
    writer = world["writer"]
    artifact_id, version_id, _ = await created(artifacts, writer, kind="fixture_gateless")
    with pytest.raises(ConflictError) as draft:
        await lifecycle.retire(
            world["retirer"].context(), "fixture_gateless", artifact_id, version_id
        )
    assert draft.value.details["reason_code"] == "not_live"
    live_id, live_version = await live_one(artifacts, migrator, writer)
    with pytest.raises(PermissionDeniedError):
        await lifecycle.retire(writer.context(), "fixture_gateless", live_id, live_version)


# ==================================================== AL36: another company ==


async def test_al36_another_company_submits_withdraws_and_retires_nothing(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    """Their ids answer as a random id does; nothing of ours moves, no audit."""
    writer = world["writer"]
    drafted, draft_v, rv = await created(artifacts, writer)
    candidate, candidate_v, crv = await created(artifacts, writer)
    await lifecycle.submit(
        writer.context(), "fixture", candidate, candidate_v, ExpectedVersion(crv)
    )
    live, live_v = await live_one(artifacts, migrator, writer)
    before = [await version(migrator, v) for v in (draft_v, candidate_v, live_v)]
    outsider, outsider_retirer = world["outsider"], world["outsider_retirer"]

    async def submit(a: uuid.UUID, v: uuid.UUID) -> Any:
        return await lifecycle.submit(outsider.context(), "fixture", a, v, ExpectedVersion(rv))

    async def withdraw(a: uuid.UUID, v: uuid.UUID) -> Any:
        return await lifecycle.withdraw(outsider.context(), "fixture", a, v)

    async def retire(a: uuid.UUID, v: uuid.UUID) -> Any:
        return await lifecycle.retire(outsider_retirer.context(), "fixture_gateless", a, v)

    calls: list[tuple[Callable[[uuid.UUID, uuid.UUID], Awaitable[Any]], uuid.UUID, uuid.UUID]] = [
        (submit, drafted, draft_v),
        (withdraw, candidate, candidate_v),
        (retire, live, live_v),
    ]
    for call, artifact_id, version_id in calls:
        with pytest.raises(NotFoundError) as theirs:
            await call(artifact_id, version_id)
        with pytest.raises(NotFoundError) as random_id:
            await call(uuid.uuid4(), uuid.uuid4())
        assert (theirs.value.code, theirs.value.message) == (
            random_id.value.code,
            random_id.value.message,
        )
    assert [await version(migrator, v) for v in (draft_v, candidate_v, live_v)] == before
    for artifact_id in (drafted, candidate, live):
        found = await rows(
            migrator,
            "SELECT count(*) FROM platform.audit_events WHERE resource_id = :a"
            " AND actor_id IN (:o, :r)",
            a=str(artifact_id),
            o=outsider.id,
            r=outsider_retirer.id,
        )
        assert found == [(0,)]


# ============================================================ R1.4: go live ==


async def test_r1_4_going_live_retires_the_live_version_superseded_first(
    artifacts: ArtifactService,
    lifecycle: LifecycleService,
    migrator: AsyncEngine,
    world: StudioWorld,
) -> None:
    writer, approver = world["writer"], world["co_writer"]
    artifact_id, v1 = await live_one(artifacts, migrator, writer)
    draft = await artifacts.create_draft(writer.context(), artifact_id, ExpectedVersion(1))
    async with artifacts.store.transaction(writer.context()) as tx:
        v2 = await artifacts.seal(tx, artifact_id, draft.row_version)
    await move_for_test(migrator, v2.version_id, "awaiting_approval")
    approval = (await version(migrator, v2.version_id)).publish_approval_id
    assert approval is not None
    async with migrator.begin() as conn:
        await decide_for_test(conn, approval, decided_by=approver.id)

    async with lifecycle.store.transaction(approver.context()) as tx:
        candidate = next(
            v for v in await tx.envelope.versions(artifact_id) if v.id == v2.version_id
        )
        moved = await lifecycle.go_live(tx, "fixture_gateless", candidate, actor_id=approver.id)

    assert moved.stage.value == "live"
    old = await version(migrator, v1)
    assert (old.stage, old.retire_reason_code, old.retired_by) == (
        "retired",
        "superseded",
        approver.id,
    )
    new = await version(migrator, v2.version_id)
    assert (new.stage, new.published_by) == ("live", approver.id)
