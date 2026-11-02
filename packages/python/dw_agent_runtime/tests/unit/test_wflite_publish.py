"""Publishing a DW's workflow draft: who may decide, what a decision settles,
and a tenant version's pin and graph (wf-ai ticket 03: R6.3-R6.6, R6.8,
R6.10, R6.11, R6.14, R6.16; WAI10-WAI12, WAI14, WAI16, WAI17).

The settlement is judged here on its facts, as the SQL store hands them over
under its locks; the store's own transaction is the integration suite's.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.wflite import InMemoryTenantVersions
from dw_agent_runtime.wflite.catalog import load_shipped_packs, workflow_sha256
from dw_agent_runtime.wflite.compile import WfPorts, worker_definition_of
from dw_agent_runtime.wflite.drafts import Draft, Simulation
from dw_agent_runtime.wflite.publish import (
    DW_WORKFLOW_PUBLISH,
    PUBLISHED,
    RETURNED,
    PublishAdmission,
    PublishFacts,
    PublishSettlement,
    PublishSettler,
    WorkflowPublishing,
)
from dw_agent_runtime.wflite.versions import (
    PinnedWorkflows,
    TenantVersion,
    TenantWorkflowGraphs,
    base_sha256,
    tenant_pinned,
)
from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import (
    DecisionClass,
    DigitalWorker,
    DwConfiguration,
    DwPeople,
)

pytestmark = pytest.mark.unit

CONFIGS = Path(__file__).resolve().parents[5] / "configs"
PACKS = load_shipped_packs(CONFIGS)
PACK = PACKS.workflow("lead_care", "1.0.0")
assert PACK is not None
BASE = PACK.document.model_dump(by_alias=True, exclude_none=True)
BASE_SHA = base_sha256(PACK)
TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()
SCOPE = WorkScope(tenant_id=TENANT, workspace_id=WORKSPACE)
BO, TO, VALIDATOR, ASSIGNER = (uuid.uuid4() for _ in range(4))
NOW = datetime.now(UTC)


def _steps() -> list[dict[str, Any]]:
    steps = copy.deepcopy(BASE["steps"])
    steps[0] = {**steps[0], "description": "changed"}
    return steps


CONTENT = {**BASE, "steps": _steps()}
CONTENT_SHA = workflow_sha256(CONTENT)


def worker(version: str = "1.0.0", dw_id: uuid.UUID | None = None) -> DigitalWorker:
    return DigitalWorker(
        id=dw_id or uuid.uuid4(),
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_user_id=uuid.uuid4(),
        configuration=DwConfiguration(
            key="lead_care",
            name="Chăm sóc lead",
            mandate="m",
            work_kinds=("marketing.lead",),
            allowed_tools=("email.send",),
            workflow_key="lead_care",
            workflow_version=version,
            parameters={},
            role_keys=frozenset({"member"}),
            decision_classes=(DecisionClass("email.send", "external", False, "A2", "A1"),),
        ),
        people=DwPeople(BO, TO, ASSIGNER, VALIDATOR),
        state="operating",
        created_by=BO,
        created_at=NOW,
        updated_at=NOW,
    )


def context(principal: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=principal,
        roles=frozenset({"member"}),
        scopes=frozenset({"dw.read", "dw.manage", "approvals.decide"}),
        plan_id="p",
    )


def draft(**kw: Any) -> Draft:
    values: dict[str, Any] = {
        "dw_id": uuid.uuid4(),
        "content": CONTENT,
        "content_sha256": CONTENT_SHA,
        "base_sha256": BASE_SHA,
        "saved_by": TO,
        "author_ids": (TO,),
        "state": "draft",
        "reason": None,
        "updated_at": NOW,
    }
    return Draft(**{**values, **kw})


def simulation(**kw: Any) -> Simulation:
    values: dict[str, Any] = {
        "content_sha256": CONTENT_SHA,
        "outcome": "passed",
        "trail": (),
        "tool_calls": (),
        "failed_step": None,
        "error": None,
        "created_at": NOW,
    }
    return Simulation(**{**values, **kw})


# ---------------------------------------------------------------------------
# Submitting and withdrawing (R6.3, R6.4, R6.8, R6.10)
# ---------------------------------------------------------------------------


class Owners:
    def __init__(self, dw: DigitalWorker) -> None:
        self.dw = dw

    async def require_owner(self, ctx: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        return self.dw


class Store:
    """Honours `PublicationStorePort`: the callbacks run on the stored draft
    and simulation, and their refusal writes nothing."""

    def __init__(self, stored: Draft, sim: Simulation | None) -> None:
        self.stored, self.sim = stored, sim
        self.opened: list[ApprovalRequest] = []
        self.audits: list[AuditEvent] = []

    async def submit(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        open_approval: Callable[[Draft, Simulation | None], tuple[ApprovalRequest, AuditEvent]],
        *,
        effect: object,
    ) -> Draft:
        request, audit = open_approval(self.stored, self.sim)
        self.opened.append(request)
        self.audits.append(audit)
        self.stored = replace(self.stored, state="submitted", approval_id=request.id)
        return self.stored

    async def withdraw(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        close: Callable[[Draft], AuditEvent],
        *,
        effect: object,
    ) -> Draft:
        self.audits.append(close(self.stored))
        return self.stored


def publishing(store: Store) -> WorkflowPublishing:
    return WorkflowPublishing(
        workers=Owners(worker()),
        store=store,
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


@pytest.mark.parametrize(
    "sim",
    [None, simulation(outcome="failed", failed_step="x"), simulation(content_sha256="0" * 64)],
    ids=["never", "failed", "other_content"],
)
async def test_a_draft_without_a_passed_simulation_of_its_content_is_not_submitted(
    sim: Simulation | None,
) -> None:
    """R6.3 (WAI10)."""
    store = Store(draft(), sim)
    with pytest.raises(ConflictError) as refused:
        await publishing(store).submit(context(BO), uuid.uuid4())
    assert refused.value.details["reason_code"] == "simulation_required"
    assert store.opened == []


async def test_a_submitted_draft_is_not_submitted_again() -> None:
    """R6.8."""
    store = Store(draft(state="submitted", approval_id=uuid.uuid4()), simulation())
    with pytest.raises(ConflictError) as refused:
        await publishing(store).submit(context(BO), uuid.uuid4())
    assert refused.value.details["reason_code"] == "draft_submitted"


async def test_a_submission_carries_identifiers_hashes_and_every_author() -> None:
    """R6.4: the approval names the draft's content, its base and who wrote
    it, and nothing of the document itself."""
    store = Store(draft(author_ids=(TO, BO)), simulation())
    dw_id = uuid.uuid4()
    await publishing(store).submit(context(BO), dw_id)
    (request,) = store.opened
    assert request.approval_type == DW_WORKFLOW_PUBLISH and request.run_id is None
    assert request.requested_by.value == BO
    assert request.payload == {
        "dw_id": str(dw_id),
        "content_sha256": CONTENT_SHA,
        "base_sha256": BASE_SHA,
        "author_ids": [str(TO), str(BO)],
    }
    assert store.audits[0].action == "dw.workflow.submitted"


async def test_only_a_submitted_draft_is_withdrawn() -> None:
    """R6.10."""
    with pytest.raises(ConflictError) as refused:
        await publishing(Store(draft(), None)).withdraw(context(BO), uuid.uuid4())
    assert refused.value.details["reason_code"] == "draft_not_submitted"


# ---------------------------------------------------------------------------
# Who decides (R6.4; WAI11, WAI16)
# ---------------------------------------------------------------------------


class People:
    async def people_of(self, dw_id: uuid.UUID) -> DwPeople | None:
        return DwPeople(BO, TO, ASSIGNER, VALIDATOR)


class Uow:
    dw_people = People()


def request(authors: Any, requested_by: uuid.UUID = BO) -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(TENANT),
        workspace_id=WorkspaceId(WORKSPACE),
        approval_type=DW_WORKFLOW_PUBLISH,
        requested_by=UserId(requested_by),
        reason="r",
        payload={"dw_id": str(uuid.uuid4()), "author_ids": authors},
    )


async def test_the_validator_decides_a_draft_others_wrote() -> None:
    await PublishAdmission().admit(Uow(), request([str(TO)]), context(VALIDATOR))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("authors", "requested_by", "decider"),
    [
        ([str(TO)], BO, TO),  # WAI11: the one who saved it
        ([str(VALIDATOR), str(BO)], BO, VALIDATOR),  # WAI16: an earlier author
        ([str(BO)], VALIDATOR, VALIDATOR),  # its submitter
        ([], BO, VALIDATOR),  # a payload without its authors
        ("not a list", BO, VALIDATOR),
    ],
    ids=["saver", "earlier_author", "submitter", "no_authors", "malformed"],
)
async def test_nobody_who_wrote_or_submitted_it_decides(
    authors: Any, requested_by: uuid.UUID, decider: uuid.UUID
) -> None:
    with pytest.raises(ConflictError) as refused:
        await PublishAdmission().admit(Uow(), request(authors, requested_by), context(decider))  # type: ignore[arg-type]
    assert refused.value.details["reason_code"] == "second_person_required"


async def test_a_business_owner_who_wrote_nothing_still_does_not_decide() -> None:
    """Only the Validator or the Technical Owner, as they are now."""
    with pytest.raises(ConflictError) as refused:
        await PublishAdmission().admit(Uow(), request([str(TO)], TO), context(BO))  # type: ignore[arg-type]
    assert refused.value.details["reason_code"] == "not_eligible_decider"


# ---------------------------------------------------------------------------
# Settling a decision (R6.5, R6.6, R6.11, R6.14; WAI12, WAI14, WAI17)
# ---------------------------------------------------------------------------

APPROVAL = uuid.uuid4()


def facts(**kw: Any) -> PublishFacts:
    values: dict[str, Any] = {
        "approval_id": APPROVAL,
        "dw_id": uuid.uuid4(),
        "approved": True,
        "decided_by": VALIDATOR,
        "content_sha256": CONTENT_SHA,
        "base_sha256": BASE_SHA,
        "workflow_key": "lead_care",
        "workflow_version": "1.0.0",
        "pinned_version_sha256": None,
        "draft": draft(state="submitted", approval_id=APPROVAL),
        "already_published": False,
        "next_seq": 1,
    }
    return PublishFacts(**{**values, **kw})


class Facts:
    def __init__(self, given: PublishFacts) -> None:
        self.given = given

    async def settle_publish(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[PublishFacts], PublishSettlement],
    ) -> PublishSettlement:
        return settle(self.given)


async def settled(**kw: Any) -> PublishSettlement:
    settler = PublishSettler(
        repo=Facts(facts(**kw)),
        workflows=PinnedWorkflows(catalog=PACKS, versions=InMemoryTenantVersions()),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )
    return await settler.settle_publish(SCOPE, APPROVAL)


async def test_an_approval_publishes_the_next_tenant_version_in_the_deciders_name() -> None:
    """R6.5: `<pack semver>+t<n>`, audited as the decider by the lane."""
    done = await settled(next_seq=3)
    assert done.outcome == "published" and not done.return_draft
    assert done.publish is not None and done.publish.version == "1.0.0+t3"
    assert done.publish.seq == 3
    assert done.audit is not None and done.audit.action == PUBLISHED
    assert done.audit.actor_id.value == VALIDATOR
    assert done.audit.details["lane"] == "outbox"
    assert done.audit.details["version"] == "1.0.0+t3"


async def test_a_version_made_from_a_tenant_version_is_checked_against_its_hash() -> None:
    """R6.5, R6.6: a base that is the DW's own `+t1` compares by its content."""
    tenant_sha = "a" * 64
    done = await settled(
        workflow_version="1.0.0+t1",
        pinned_version_sha256=tenant_sha,
        base_sha256=tenant_sha,
        next_seq=2,
    )
    assert done.publish is not None and done.publish.version == "1.0.0+t2"
    moved = await settled(
        workflow_version="1.0.0+t1", pinned_version_sha256="b" * 64, base_sha256=tenant_sha
    )
    assert moved.outcome == "base_changed" and moved.publish is None


async def test_a_moved_pin_returns_the_draft_and_publishes_nothing() -> None:
    """R6.6 (WAI12): the DW pins something else since the submission."""
    done = await settled(base_sha256="c" * 64)
    assert done.outcome == "base_changed" and done.publish is None
    assert done.return_draft and done.reason == "base_changed"
    assert done.audit is not None and done.audit.action == RETURNED
    assert done.audit.details["reason"] == "base_changed"


async def test_a_pin_to_a_version_no_longer_there_is_a_moved_base() -> None:
    """A tenant pin whose row is gone has no hash to match (fails closed)."""
    done = await settled(workflow_version="1.0.0+t4", pinned_version_sha256=None)
    assert done.outcome == "base_changed" and done.publish is None


async def test_content_rewritten_after_submission_publishes_nothing() -> None:
    """R6.6 (WAI14): the stored content is hashed again, not trusted by its
    column."""
    tampered = {**CONTENT, "steps": BASE["steps"]}
    done = await settled(
        draft=draft(state="submitted", approval_id=APPROVAL, content=tampered),
    )
    assert done.outcome == "content_changed" and done.publish is None
    assert done.return_draft and done.reason == "content_changed"


async def test_a_rejection_returns_the_draft() -> None:
    """R6.11."""
    done = await settled(approved=False)
    assert done.outcome == "rejected" and done.publish is None
    assert done.return_draft and done.reason is None
    assert done.audit is not None and done.audit.details["reason"] == "rejected"


@pytest.mark.parametrize(
    "given",
    [
        {"already_published": True},
        {"draft": None},
        {"draft": draft()},
        {"draft": draft(state="submitted", approval_id=uuid.uuid4())},
    ],
    ids=["delivered_twice", "no_draft", "withdrawn", "resubmitted"],
)
async def test_a_decision_settled_before_changes_nothing(given: dict[str, Any]) -> None:
    """R6.14 (WAI17): a redelivered event, or one whose draft no longer waits
    on it, writes nothing."""
    done = await settled(**given)
    assert done == PublishSettlement("settled")


# ---------------------------------------------------------------------------
# A tenant version's pin and graph (R6.5, R6.16)
# ---------------------------------------------------------------------------


def version(dw_id: uuid.UUID, label: str = "1.0.0+t1", content: Any = None) -> TenantVersion:
    body = content or CONTENT
    return TenantVersion(
        dw_id=dw_id,
        key="lead_care",
        version=label,
        content=body,
        content_sha256=workflow_sha256(body),
        base_sha256=BASE_SHA,
        author_ids=(TO,),
        approved_by=VALIDATOR,
        approval_id=uuid.uuid4(),
        created_at=NOW,
    )


async def test_a_tenant_pin_reads_the_dws_own_version_and_no_other() -> None:
    """R6.16: another DW's `+t1`, or another tenant's, is not shipped."""
    versions = InMemoryTenantVersions()
    mine, other = worker("1.0.0+t1"), worker("1.0.0+t1")
    versions.put(SCOPE, version(mine.id))
    versions.put(WorkScope(tenant_id=uuid.uuid4(), workspace_id=WORKSPACE), version(other.id))
    pins = PinnedWorkflows(catalog=PACKS, versions=versions)
    found = await pins.pinned(mine)
    assert found is not None and found.label == "1.0.0+t1"
    assert found.sha256 == CONTENT_SHA and found.document.steps[0].description == "changed"
    assert found.work_schemas == PACK.work_schemas
    assert await pins.pinned(other) is None
    assert await pins.pinned(worker("1.0.0+t2", dw_id=mine.id)) is None
    assert await pins.pinned(worker("1.0.0")) is PACK


def test_a_tenant_version_runs_at_its_label_and_content_hash() -> None:
    """Two tenants' `+t1` never name one graph unless they are one document."""
    pinned = PinnedWorkflows(catalog=PACKS, versions=InMemoryTenantVersions())
    assert pinned.pack("lead_care", "1.0.0+t7") is PACK
    mine = tenant_pinned(PACK, version(uuid.uuid4()))
    definition = worker_definition_of(mine)
    assert definition.worker_version == f"1.0.0+t1.{CONTENT_SHA}"
    assert definition.graph_version == definition.worker_version
    assert definition.prompt_bundle_version == "1.0.0"
    assert worker_definition_of(PACK).worker_version == "1.0.0"


def graphs_over(versions: InMemoryTenantVersions) -> TenantWorkflowGraphs:
    graphs = GraphRegistry()
    return TenantWorkflowGraphs(
        catalog=PACKS,
        versions=versions,
        ports=WfPorts.__new__(WfPorts),
        graphs=graphs,
        workers=WorkerRegistry(graph_registry=graphs),
    )


def hosted(tenant_graphs: TenantWorkflowGraphs, run_version: str) -> bool:
    try:
        tenant_graphs.workers.resolve("dw:lead_care", run_version)
    except Exception:
        return False
    return True


async def test_a_runs_tenant_graph_registers_under_its_own_tenant_only() -> None:
    """R6.5, R6.16: the graph is read under the run's tenant and workspace."""
    versions = InMemoryTenantVersions()
    versions.put(SCOPE, version(uuid.uuid4()))
    run_version = f"1.0.0+t1.{CONTENT_SHA}"
    elsewhere = graphs_over(versions)
    await elsewhere.ensure(
        tenant_id=uuid.uuid4(),
        workspace_id=WORKSPACE,
        worker_id="dw:lead_care",
        worker_version=run_version,
    )
    assert not hosted(elsewhere, run_version)
    here = graphs_over(versions)
    for _ in range(2):  # a second run of it finds it registered
        await here.ensure(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            worker_id="dw:lead_care",
            worker_version=run_version,
        )
    assert hosted(here, run_version)


async def test_a_version_whose_content_no_longer_hashes_to_its_name_is_not_hosted() -> None:
    versions = InMemoryTenantVersions()
    row = version(uuid.uuid4())
    versions.put(SCOPE, replace(row, content=BASE))
    tenant_graphs = graphs_over(versions)
    await tenant_graphs.ensure(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        worker_id="dw:lead_care",
        worker_version=f"1.0.0+t1.{CONTENT_SHA}",
    )
    assert not hosted(tenant_graphs, f"1.0.0+t1.{CONTENT_SHA}")


async def test_a_pack_version_is_left_to_the_registration_at_start() -> None:
    tenant_graphs = graphs_over(InMemoryTenantVersions())
    await tenant_graphs.ensure(
        tenant_id=TENANT, workspace_id=WORKSPACE, worker_id="dw:lead_care", worker_version="1.0.0"
    )
    assert not hosted(tenant_graphs, "1.0.0")


def test_a_new_dw_pins_a_packs_version_and_a_published_pin_reads_back() -> None:
    """R6.16: a tenant pin is valid on a DW (read back from its row), and
    only publication sets one: creation refuses it (application test)."""
    assert worker("1.0.0+t12").configuration.workflow_version == "1.0.0+t12"
    for bad in ("1.0.0+t0", "1.0.0+x1", "1.0.0+t1.abc"):
        with pytest.raises(DomainError):
            worker(bad)
