"""Unit: Digital Worker creation, state, people and decision autonomy (digital-worker
R1.2-R1.3, R1.5-R1.10, R1.13, R1.15, R2.1-R2.4; DWK1, DWK3-DWK7, DWK23, DWK24, DWK33).

The fakes keep their Protocols' promises: the repository refuses a state move
from a state the DW is no longer in, the membership check answers None for a
user without a membership in the caller's workspace, whatever tenant they
belong to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.digital_workers import (
    ChangeState,
    CreateDigitalWorker,
    DecisionAutonomy,
    DecisionLevels,
    DigitalWorkerService,
    Standing,
    is_critical_role,
)
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.digital_worker import (
    DecisionClass,
    DigitalWorker,
    DwConfiguration,
    DwPeople,
    DwState,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()
CREATOR, OWNER, TECH, ASSIGNER, VALIDATOR = (uuid.uuid4() for _ in range(5))
OUTSIDER = uuid.uuid4()  # a user of tenant B: no membership in this workspace

MEMBER_SCOPES = frozenset({"approvals.read", "dw.read", "runs.read"})
DECIDER_SCOPES = MEMBER_SCOPES | {"approvals.decide"}
ROLES = {
    "member": frozenset({"approvals.read", "dw.read", "runs.read"}),
    "mailer": frozenset({"email.send"}),
    "approver": DECIDER_SCOPES,
    "org_admin": frozenset({"platform.members.write", "dw.manage", "dw.read"}),
    "workspace_admin": frozenset({"platform.workspaces.write"}),
}


def context(user: uuid.UUID, *scopes: str, roles: frozenset[str] = frozenset()) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        principal_id=user,
        roles=roles,
        scopes=frozenset(scopes),
        plan_id="professional",
    )


CREATOR_CTX = context(CREATOR, "dw.manage", "dw.read", *ROLES["member"], "email.send")


@dataclass
class FakeRepo:
    workers: dict[uuid.UUID, DigitalWorker] = field(default_factory=dict)
    audits: list[AuditEvent] = field(default_factory=list)

    async def create(
        self,
        context: AccessContext,
        worker: DigitalWorker,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        self.workers[worker.id] = worker
        self.audits.append(audit)

    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker | None:
        found = self.workers.get(dw_id)
        if found is None or (found.tenant_id, found.workspace_id) != (
            context.tenant_id,
            context.workspace_id,
        ):
            return None
        return found

    async def list(self, context: AccessContext, request: PageRequest) -> Page[DigitalWorker]:
        raise NotImplementedError("not exercised by these tests")

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
        self.audits.append(audit)
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
        found = await self.get(context, dw_id)
        if found is None:
            return False
        self.workers[dw_id] = replace(found, people=people)
        self.audits.append(audit)
        return True


@dataclass
class FakeMembers:
    standings: dict[uuid.UUID, Standing]

    async def standing(self, context: AccessContext, user_id: uuid.UUID) -> Standing | None:
        return self.standings.get(user_id)


@dataclass(frozen=True)
class FakeTools:
    names: frozenset[str] = frozenset({"email.send"})

    def has_tool(self, name: str) -> bool:
        return name in self.names


class FakeRoles:
    async def role_catalog(self) -> dict[str, frozenset[str]]:
        return dict(ROLES)


def members() -> FakeMembers:
    return FakeMembers(
        {
            CREATOR: Standing("human", MEMBER_SCOPES),
            OWNER: Standing("human", MEMBER_SCOPES),
            TECH: Standing("human", MEMBER_SCOPES | {"email.send"}),
            ASSIGNER: Standing("human", MEMBER_SCOPES),
            VALIDATOR: Standing("human", DECIDER_SCOPES),
        }
    )


def service(repo: FakeRepo, people: FakeMembers | None = None) -> DigitalWorkerService:
    return DigitalWorkerService(
        repo=repo,
        authz=ScopeAuthorizationService(),
        tools=FakeTools(),
        members=people or members(),
        roles=FakeRoles(),
        clock=FixedClock(NOW),
        id_generator=Uuid4Generator(),
    )


def configuration(**changes: object) -> DwConfiguration:
    base: dict[str, object] = {
        "key": "lead_care",
        "name": "Chăm sóc lead",
        "mandate": "Gửi thư chào lead mới và nhắc lại sau hai ngày.",
        "work_kinds": ("lead.new",),
        "allowed_tools": ("email.send",),
        "workflow_key": "leadcare",
        "workflow_version": "1.0.0",
        "parameters": {},
        "role_keys": frozenset({"member", "mailer"}),
        "decision_classes": (DecisionClass("email.first_touch", "external", True, "A3", "A2"),),
    }
    base.update(changes)
    return DwConfiguration(**base)  # type: ignore[arg-type]


def people(**changes: uuid.UUID) -> DwPeople:
    return replace(
        DwPeople(
            business_owner_id=OWNER,
            technical_owner_id=TECH,
            work_assigner_id=ASSIGNER,
            validator_id=VALIDATOR,
        ),
        **changes,
    )


async def created(repo: FakeRepo) -> DigitalWorker:
    return await service(repo).create(
        CREATOR_CTX, CreateDigitalWorker(configuration=configuration(), people=people())
    )


def reason(error: pytest.ExceptionInfo[BaseException]) -> object:
    assert isinstance(error.value, DomainError | ConflictError | PermissionDeniedError)
    return error.value.details.get("reason_code")


# ---------------------------------------------------------------- creation --


async def test_a_valid_dw_is_created_in_draft_with_a_principal_and_an_audit_event() -> None:
    repo = FakeRepo()
    worker = await created(repo)

    assert worker.state == "draft"
    assert (worker.tenant_id, worker.workspace_id) == (TENANT, WORKSPACE)
    assert worker.principal_user_id not in {CREATOR, OWNER, TECH, ASSIGNER, VALIDATOR}
    assert worker.created_by == CREATOR
    assert [c.key for c in worker.configuration.decision_classes] == ["email.first_touch"]
    [audit] = repo.audits
    assert audit.action == "dw.created" and audit.actor_id.value == CREATOR
    assert audit.resource_id == str(worker.id)


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"validator_id": OUTSIDER}, "owner_not_member"),  # DWK1: a user of tenant B
        ({"business_owner_id": OUTSIDER}, "owner_not_member"),
        ({"validator_id": ASSIGNER}, "validator_cannot_decide"),  # DWK1
    ],
)
async def test_the_four_people_are_members_and_the_validator_decides(
    changed: dict[str, uuid.UUID], code: str
) -> None:
    repo = FakeRepo()
    with pytest.raises(DomainError) as refused:
        await service(repo).create(
            CREATOR_CTX,
            CreateDigitalWorker(configuration=configuration(), people=people(**changed)),
        )
    assert reason(refused) == code
    assert repo.workers == {} and repo.audits == []


async def test_a_service_user_is_not_one_of_the_four_people() -> None:
    """DWK39: another DW's principal named as Validator, with every scope."""
    other_principal = uuid.uuid4()
    standing = members()
    standing.standings[other_principal] = Standing("service", DECIDER_SCOPES)
    repo = FakeRepo()
    with pytest.raises(DomainError) as refused:
        await service(repo, standing).create(
            CREATOR_CTX,
            CreateDigitalWorker(
                configuration=configuration(), people=people(validator_id=other_principal)
            ),
        )
    assert reason(refused) == "owner_not_member"
    assert repo.workers == {}


async def test_an_unknown_tool_is_refused_before_anything_is_written() -> None:
    repo = FakeRepo()
    with pytest.raises(DomainError) as refused:
        await service(repo).create(
            CREATOR_CTX,
            CreateDigitalWorker(
                configuration=configuration(allowed_tools=("email.send", "sms.send")),
                people=people(),
            ),
        )
    assert reason(refused) == "tool_unknown"
    assert refused.value.details["tools"] == ["sms.send"]
    assert repo.workers == {}


def test_a_dw_holds_at_least_one_kind_of_work() -> None:
    with pytest.raises(DomainError) as refused:
        configuration(work_kinds=())
    assert reason(refused) == "work_kinds_empty"


def test_an_earned_level_above_its_ceiling_is_refused() -> None:
    """R2.2: A3 earned under an A2 ceiling."""
    with pytest.raises(DomainError) as refused:
        DecisionClass("email.first_touch", "external", True, "A2", "A3")
    assert reason(refused) == "above_ceiling"


async def test_the_creator_hands_out_no_scope_they_lack() -> None:
    """DWK24: the creator does not hold `email.send`, a role carrying it is asked."""
    repo = FakeRepo()
    lacking = context(CREATOR, "dw.manage", "dw.read", *ROLES["member"])
    with pytest.raises(PermissionDeniedError) as refused:
        await service(repo).create(
            lacking, CreateDigitalWorker(configuration=configuration(), people=people())
        )
    assert reason(refused) == "grants_not_covered"
    assert repo.workers == {}


async def test_a_platform_admin_role_does_not_stand_in_for_the_scopes_handed_out() -> None:
    repo = FakeRepo()
    admin = context(CREATOR, "dw.manage", roles=frozenset({"platform_admin"}))
    with pytest.raises(PermissionDeniedError) as refused:
        await service(repo).create(
            admin, CreateDigitalWorker(configuration=configuration(), people=people())
        )
    assert reason(refused) == "grants_not_covered"


@pytest.mark.parametrize("role", ["org_admin", "workspace_admin"])
async def test_a_principal_holds_no_critical_role(role: str) -> None:
    """DWK33: `org_admin` by name, and a role carrying an administrative scope."""
    repo = FakeRepo()
    everything = context(CREATOR, "dw.manage", *{s for scopes in ROLES.values() for s in scopes})
    with pytest.raises(DomainError) as refused:
        await service(repo).create(
            everything,
            CreateDigitalWorker(
                configuration=configuration(role_keys=frozenset({"member", role})),
                people=people(),
            ),
        )
    assert reason(refused) == "role_not_allowed_for_service"
    assert repo.workers == {}


def test_the_critical_roles_are_named_and_found_by_scope() -> None:
    assert is_critical_role("tenant_owner", frozenset())
    assert is_critical_role("platform_admin", frozenset({"platform.admin"}))
    assert is_critical_role("anything", frozenset({"admin.billing"}))
    assert not is_critical_role("member", ROLES["member"])


async def test_creating_takes_dw_manage() -> None:
    repo = FakeRepo()
    with pytest.raises(PermissionDeniedError):
        await service(repo).create(
            context(CREATOR, "dw.read", *ROLES["member"], "email.send"),
            CreateDigitalWorker(configuration=configuration(), people=people()),
        )
    assert repo.workers == {}


# ------------------------------------------------------------------ reading --


async def test_a_dw_the_caller_may_not_read_is_not_found() -> None:
    """R1.5: no `dw.read`, another workspace and an unknown id are one answer."""
    repo = FakeRepo()
    worker = await created(repo)
    elsewhere = AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=OWNER,
        roles=frozenset(),
        scopes=frozenset({"dw.read"}),
        plan_id="professional",
    )
    for caller, dw_id in (
        (context(OWNER, "runs.read"), worker.id),
        (elsewhere, worker.id),
        (context(OWNER, "dw.read"), uuid.uuid4()),
    ):
        with pytest.raises(NotFoundError):
            await service(repo).get(caller, dw_id)


async def test_not_found_comes_before_not_owner() -> None:
    repo = FakeRepo()
    worker = await created(repo)
    with pytest.raises(NotFoundError):
        await service(repo).change_state(
            context(OWNER, "runs.read"), worker.id, ChangeState("operating")
        )


# ------------------------------------------------------------------- state --


async def test_only_an_owner_changes_state() -> None:
    """DWK4: a holder of `dw.manage` who is neither owner is refused."""
    repo = FakeRepo()
    worker = await created(repo)
    with pytest.raises(PermissionDeniedError) as refused:
        await service(repo).change_state(CREATOR_CTX, worker.id, ChangeState("retired"))
    assert reason(refused) == "not_dw_owner"
    assert repo.workers[worker.id].state == "draft"
    assert [a.action for a in repo.audits] == ["dw.created"]


async def test_a_business_owner_without_dw_manage_changes_state() -> None:
    repo = FakeRepo()
    worker = await created(repo)
    owner = context(OWNER, *MEMBER_SCOPES, "email.send")
    moved = await service(repo).change_state(owner, worker.id, ChangeState("operating"))
    assert moved.state == "operating"
    audit = repo.audits[-1]
    assert audit.action == "dw.state_changed" and audit.actor_id.value == OWNER
    assert audit.details == {"from": "draft", "to": "operating"}


async def test_a_retired_dw_does_not_operate_again() -> None:
    """DWK5."""
    repo = FakeRepo()
    worker = await created(repo)
    owner = context(OWNER, *MEMBER_SCOPES)
    await service(repo).change_state(owner, worker.id, ChangeState("retired"))
    with pytest.raises(ConflictError) as refused:
        await service(repo).change_state(owner, worker.id, ChangeState("operating"))
    assert reason(refused) == "invalid_transition"
    assert repo.workers[worker.id].state == "retired"


async def test_the_creator_does_not_put_their_own_dw_into_operation() -> None:
    """DWK23: the creator is also the Technical Owner."""
    repo = FakeRepo()
    worker = await service(repo).create(
        CREATOR_CTX,
        CreateDigitalWorker(
            configuration=configuration(), people=people(technical_owner_id=CREATOR)
        ),
    )
    with pytest.raises(ConflictError) as refused:
        await service(repo).change_state(CREATOR_CTX, worker.id, ChangeState("operating"))
    assert reason(refused) == "second_person_required"
    assert repo.workers[worker.id].state == "draft"


async def test_who_puts_a_dw_into_operation_holds_every_scope_of_its_principal() -> None:
    """DWK23: the Technical Owner lacks `email.send`, which the principal holds."""
    standing = members()
    principal_scopes = ROLES["member"] | ROLES["mailer"]
    repo = FakeRepo()
    worker = await service(repo, standing).create(
        CREATOR_CTX, CreateDigitalWorker(configuration=configuration(), people=people())
    )
    standing.standings[worker.principal_user_id] = Standing("service", principal_scopes)

    lacking = context(TECH, *MEMBER_SCOPES)
    with pytest.raises(PermissionDeniedError) as refused:
        await service(repo, standing).change_state(lacking, worker.id, ChangeState("operating"))
    assert reason(refused) == "grants_not_covered"
    assert repo.workers[worker.id].state == "draft"

    covering = context(TECH, *principal_scopes)
    moved = await service(repo, standing).change_state(
        covering, worker.id, ChangeState("operating")
    )
    assert moved.state == "operating"


async def test_pausing_and_resuming_need_no_second_person() -> None:
    repo = FakeRepo()
    worker = await created(repo)
    repo.workers[worker.id] = replace(worker, state="operating")
    owner = context(OWNER, *MEMBER_SCOPES)
    paused = await service(repo).change_state(owner, worker.id, ChangeState("paused"))
    assert paused.state == "paused"
    resumed = await service(repo).change_state(owner, worker.id, ChangeState("operating"))
    assert resumed.state == "operating"


# ------------------------------------------------------------------ people --


async def test_an_owner_replaces_the_validator_on_the_record() -> None:
    """R1.13."""
    repo = FakeRepo()
    worker = await created(repo)
    new_validator = uuid.uuid4()
    standing = members()
    standing.standings[new_validator] = Standing("human", DECIDER_SCOPES)

    changed = await service(repo, standing).replace_people(
        context(TECH, *MEMBER_SCOPES), worker.id, people(validator_id=new_validator)
    )
    assert changed.people.validator_id == new_validator
    audit = repo.audits[-1]
    assert audit.action == "dw.people_changed" and audit.actor_id.value == TECH
    assert audit.details["before"]["validator_id"] == str(VALIDATOR)  # type: ignore[index]
    assert audit.details["after"]["validator_id"] == str(new_validator)  # type: ignore[index]


async def test_people_are_replaced_only_by_an_owner_and_only_with_members() -> None:
    """DWK4 and R1.13."""
    repo = FakeRepo()
    worker = await created(repo)
    with pytest.raises(PermissionDeniedError) as refused:
        await service(repo).replace_people(
            context(VALIDATOR, *DECIDER_SCOPES), worker.id, people(validator_id=TECH)
        )
    assert reason(refused) == "not_dw_owner"
    with pytest.raises(DomainError) as outside:
        await service(repo).replace_people(
            context(OWNER, *MEMBER_SCOPES), worker.id, people(validator_id=OUTSIDER)
        )
    assert reason(outside) == "owner_not_member"
    assert repo.workers[worker.id].people == people()
    assert [a.action for a in repo.audits] == ["dw.created"]


# ----------------------------------------------------------- the autonomy --


@dataclass
class FakeLevels:
    found: DecisionLevels | None = None
    fails: bool = False

    async def levels(
        self, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID, dw_id: uuid.UUID, key: str
    ) -> DecisionLevels | None:
        if self.fails:
            raise RuntimeError("connection lost")
        return self.found


def levels(
    effect: str = "external",
    *,
    reversible: bool = True,
    ceiling: str = "A4",
    earned: str = "A3",
    tenant: str = "A4",
) -> DecisionLevels:
    return DecisionLevels(
        effect_level=effect,  # type: ignore[arg-type]
        reversible=reversible,
        ceiling=ceiling,
        earned_level=earned,
        tenant_ceiling=tenant,
    )


async def _effective(port: FakeLevels) -> str:
    return await DecisionAutonomy(port).effective_level(
        tenant_id=TENANT, workspace_id=WORKSPACE, dw_id=uuid.uuid4(), key="k.x"
    )


async def _requires(port: FakeLevels) -> bool:
    return await DecisionAutonomy(port).requires_person(
        tenant_id=TENANT, workspace_id=WORKSPACE, dw_id=uuid.uuid4(), key="k.x"
    )


async def test_the_effective_level_is_the_lowest_of_three() -> None:
    """DWK6: tenant A1, earned A3, class ceiling A4."""
    assert await _effective(FakeLevels(levels(tenant="A1", earned="A3", ceiling="A4"))) == "A1"
    assert await _effective(FakeLevels(levels(tenant="A4", earned="A3", ceiling="A2"))) == "A2"
    assert await _effective(FakeLevels(levels(tenant="A4", earned="A2", ceiling="A3"))) == "A2"


async def test_an_unreadable_level_is_a0() -> None:
    """DWK6: a class that does not exist, a value that is not a level, a read
    that fails."""
    assert await _effective(FakeLevels(None)) == "A0"
    assert await _effective(FakeLevels(levels(tenant="A9"))) == "A0"
    assert await _effective(FakeLevels(fails=True)) == "A0"
    assert await _requires(FakeLevels(None)) is True
    assert await _requires(FakeLevels(fails=True)) is True


async def test_the_decision_ladder_is_the_tool_ladder() -> None:
    """DWK7."""
    assert await _requires(FakeLevels(levels("critical", earned="A4"))) is True
    assert await _requires(FakeLevels(levels("external", reversible=False, earned="A3"))) is True
    assert await _requires(FakeLevels(levels("external", reversible=True, earned="A3"))) is False
    assert await _requires(FakeLevels(levels("internal", earned="A2"))) is False
    assert await _requires(FakeLevels(levels("internal", earned="A1"))) is True
