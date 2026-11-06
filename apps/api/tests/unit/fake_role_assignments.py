"""One company's people, memberships and role assignments, held in memory.

`FakeRoleAssignments` stands in for `SqlRoleAssignmentRepository` (and answers
`TenantMembersRepositoryPort.list_members` from the same rows, as the database
does) for the route tests of `/admin/members` and `/admin/invitations`. It
refuses where the SQL adapter and the database behind it refuse, so a route test
written against it cannot pass on a path the real one would not take
(`.claude/rules/code-quality.md`, "Liskov"):

- `refusals` is `platform.rbac_refusals` in small: nobody grants to themselves
  (`rbac_self_assignment`), `platform_admin` is not grantable
  (`rbac_not_grantable`), and the hold rule (`rbac_escalation`, one row per
  privilege) unless the actor holds `platform.roles.bind` and the role is not
  critical. The actor's grants are the context's scopes.
- `apply` never writes an assignment: a grant is a proposal, a revocation is
  applied with one audit event, a dropped membership takes its roles with it
  (an audit event each), a workspace outside the company is NotFoundError, and
  removing the last `tenant_owner` is 409 `last_owner`.
- `invite` refuses a person already in the company (409
  `member_email_exists_in_tenant`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.role_admin import (
    ACTION_REVOKE,
    ROLES_BIND,
    AuditFactory,
    NewProposal,
    Refusal,
)
from dw_platform.application.role_assignments import (
    AssignmentOutcome,
    AssignmentPlan,
    HeldRole,
    MemberHoldings,
    MembershipHolding,
    PersonRef,
    TenantRole,
)
from dw_platform.application.tenant_members import MemberWorkspace, TenantMember
from dw_platform.domain.audit import AuditEvent

_ACTION_MEMBERSHIP_REVOKE = "platform.membership.revoke"
_ACTION_INVITED = "platform.member.invited"
OWNER = "tenant_owner"
NOT_GRANTABLE = frozenset({"platform_admin"})


@dataclass(frozen=True, slots=True)
class FakeRole:
    key: str
    privileges: frozenset[str]
    kind: Literal["role", "permission_set"] = "role"
    critical: bool = False
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def as_tenant_role(self) -> TenantRole:
        return TenantRole(self.id, self.key, self.kind, self.critical)


@dataclass
class FakePerson:
    ref: PersonRef
    kind: Literal["human", "service"] = "human"
    dw_principal: bool = False
    signed_in: bool = True
    status: Literal["invited", "active", "suspended"] | None = None


@dataclass(frozen=True, slots=True)
class FakeAssignment:
    id: uuid.UUID
    membership_id: uuid.UUID
    role_id: uuid.UUID


class FakeRoleAssignments:
    """Implements ``RoleAssignmentRepositoryPort`` and ``TenantMembersRepositoryPort``."""

    def __init__(
        self,
        tenant_id: uuid.UUID,
        workspaces: Mapping[uuid.UUID, str],
        roles: Sequence[FakeRole],
        *,
        checker: bool = True,
        checkers: frozenset[uuid.UUID] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.workspaces = dict(workspaces)
        self.roles = {r.key: r for r in roles}
        self.checker = checker
        # Who `platform.checker_candidates` would answer, when a test names
        # them: then the caller and the person placed are dropped, as the SQL
        # drops them (R6.4, R7.3). None keeps `checker`'s fixed answer.
        self.checkers = checkers
        self.people: dict[uuid.UUID, FakePerson] = {}
        # (user, workspace) -> membership id
        self.memberships: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
        self.assignments: dict[uuid.UUID, FakeAssignment] = {}
        self.proposals: list[NewProposal] = []
        self.audits: list[AuditEvent] = []

    # -- planting -----------------------------------------------------------

    def add_person(
        self,
        user_id: uuid.UUID,
        email: str,
        display_name: str = "Người thử",
        *,
        status: Literal["invited", "active", "suspended"] | None = None,
        kind: Literal["human", "service"] = "human",
        dw_principal: bool = False,
        signed_in: bool = True,
    ) -> None:
        self.people[user_id] = FakePerson(
            PersonRef(user_id, email, display_name), kind, dw_principal, signed_in, status
        )

    def place(self, user_id: uuid.UUID, workspace_id: uuid.UUID, *role_keys: str) -> None:
        """A membership holding ``role_keys``, as a migrator fixture plants it."""
        membership = self.memberships.setdefault((user_id, workspace_id), uuid.uuid4())
        for key in role_keys:
            assignment = FakeAssignment(uuid.uuid4(), membership, self.roles[key].id)
            self.assignments[assignment.id] = assignment

    def held(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> frozenset[str]:
        """The role keys assigned on the person's membership there."""
        membership = self.memberships.get((user_id, workspace_id))
        by_id = {r.id: r.key for r in self.roles.values()}
        return frozenset(
            by_id[a.role_id] for a in self.assignments.values() if a.membership_id == membership
        )

    # -- the port -------------------------------------------------------------

    async def holdings(self, context: AccessContext, user_id: uuid.UUID) -> MemberHoldings | None:
        self._bound(context)
        mine = {ws: m for (u, ws), m in self.memberships.items() if u == user_id}
        if not mine:
            return None
        person = self.people[user_id]
        by_id = {r.id: r for r in self.roles.values()}
        return MemberHoldings(
            user_id=user_id,
            kind=person.kind,
            dw_principal=person.dw_principal,
            memberships={
                ws: MembershipHolding(
                    membership_id=membership,
                    roles={
                        by_id[a.role_id].key: HeldRole(
                            a.id, a.role_id, by_id[a.role_id].key, by_id[a.role_id].kind
                        )
                        for a in self.assignments.values()
                        if a.membership_id == membership
                    },
                )
                for ws, membership in mine.items()
            },
        )

    async def tenant_roles(
        self, context: AccessContext, keys: frozenset[str]
    ) -> Mapping[str, TenantRole]:
        self._bound(context)
        return {k: self.roles[k].as_tenant_role() for k in keys if k in self.roles}

    async def refusals(
        self, context: AccessContext, changes: Sequence[Mapping[str, object]]
    ) -> list[Refusal]:
        self._bound(context)
        by_id = {str(r.id): r for r in self.roles.values()}
        found: list[Refusal] = []
        for change in changes:
            role = by_id[str(change["role_id"])]
            if change["op"] == "grant" and change.get("user_id") == str(context.principal_id):
                found.append(Refusal("rbac_self_assignment"))
            if role.key in NOT_GRANTABLE:
                found.append(Refusal("rbac_not_grantable"))
                continue
            if ROLES_BIND in context.scopes and not role.critical:
                continue
            found += [
                Refusal("rbac_escalation", key, "workspace")
                for key in sorted(role.privileges - context.scopes)
            ]
        return found

    async def has_checker(
        self, context: AccessContext, permission: str, *, assignee: uuid.UUID | None = None
    ) -> bool:
        self._bound(context)
        if self.checkers is None:
            return self.checker
        return any(c not in (context.principal_id, assignee) for c in self.checkers)

    async def find_person(self, email: str) -> PersonRef | None:
        wanted = email.strip().lower()
        for person in self.people.values():
            if person.signed_in and person.kind == "human" and person.ref.email == wanted:
                return person.ref
        return None

    async def apply(
        self,
        context: AccessContext,
        plan: AssignmentPlan,
        *,
        audits: AuditFactory,
        member_status: Literal["invited", "active"] | None = None,
        department: str = "general",
        effect: PendingEffect | None = None,
    ) -> AssignmentOutcome:
        assert plan.user_id is not None
        self._bound(context)
        self._require_workspaces(plan.new_memberships)
        self._keep_an_owner(plan)
        return self._write(plan, plan.user_id, audits, member_status)

    async def invite(
        self,
        context: AccessContext,
        *,
        display_name: str,
        email: str,
        plan: AssignmentPlan,
        audits: AuditFactory,
        effect: PendingEffect | None = None,
    ) -> tuple[PersonRef, AssignmentOutcome]:
        self._bound(context)
        self._require_workspaces(plan.new_memberships)
        existing = next((p for p in self.people.values() if p.ref.email == email), None)
        if existing is None:
            user_id = uuid.uuid4()
            self.add_person(user_id, email, display_name, signed_in=False)
            person = self.people[user_id].ref
        else:
            person = existing.ref
            if any(u == person.user_id for u, _ in self.memberships):
                raise ConflictError(
                    "a person with that email is already a member of this organisation",
                    details={"reason_code": "member_email_exists_in_tenant"},
                )
        for ws in plan.new_memberships:
            self.audits.append(
                audits.event(
                    _ACTION_INVITED,
                    "membership",
                    person.user_id,
                    {"user_id": str(person.user_id)},
                    workspace_id=ws,
                )
            )
        return person, self._write(plan, person.user_id, audits, "invited")

    async def list_members(self, context: AccessContext) -> list[TenantMember]:
        self._bound(context)
        roles = {r.id: r for r in self.roles.values()}
        members = []
        for user_id, person in self.people.items():
            mine = sorted(
                ((ws, m) for (u, ws), m in self.memberships.items() if u == user_id),
                key=lambda item: (self.workspaces[item[0]], str(item[0])),
            )
            if not mine or person.kind != "human":
                continue
            members.append(
                TenantMember(
                    user_id=user_id,
                    display_name=person.ref.display_name,
                    email=person.ref.email,
                    status=person.status or "active",
                    memberships=tuple(
                        MemberWorkspace(
                            ws,
                            self.workspaces[ws],
                            tuple(
                                sorted(
                                    roles[a.role_id].key
                                    for a in self.assignments.values()
                                    if a.membership_id == m and roles[a.role_id].kind == "role"
                                )
                            ),
                        )
                        for ws, m in mine
                    ),
                )
            )
        return sorted(members, key=lambda m: (m.display_name, str(m.user_id)))

    # -- what the database does ---------------------------------------------

    def _bound(self, context: AccessContext) -> None:
        """RLS: another company's caller sees none of these rows."""
        if context.tenant_id != self.tenant_id:
            raise NotFoundError("no such member in this tenant")

    def _require_workspaces(self, workspace_ids: Sequence[uuid.UUID]) -> None:
        missing = sorted(str(ws) for ws in workspace_ids if ws not in self.workspaces)
        if missing:
            raise NotFoundError(
                "workspace not found in this tenant", details={"workspace_ids": missing}
            )

    def _keep_an_owner(self, plan: AssignmentPlan) -> None:
        """`ck_role_assignments_last_owner`, cascades included."""
        owner = self.roles.get(OWNER)
        if owner is None:
            return
        assert plan.user_id is not None
        going = {r.assignment_id for r in plan.revokes} | {
            a.id
            for ws in plan.dropped_memberships
            for a in self.assignments.values()
            if a.membership_id == self.memberships.get((plan.user_id, ws))
        }
        owners = [a for a in self.assignments.values() if a.role_id == owner.id]
        if owners and all(a.id in going for a in owners):
            raise ConflictError(
                "the company keeps at least one active owner",
                details={"reason_code": "last_owner"},
            )

    def _write(
        self,
        plan: AssignmentPlan,
        user_id: uuid.UUID,
        audits: AuditFactory,
        member_status: Literal["invited", "active"] | None,
    ) -> AssignmentOutcome:
        person = self.people[user_id]
        if member_status is not None and person.status is None:
            person.status = member_status
        for ws in plan.new_memberships:
            self.memberships.setdefault((user_id, ws), uuid.uuid4())
        for revoke in plan.revokes:
            del self.assignments[revoke.assignment_id]
            self.audits.append(
                audits.event(
                    ACTION_REVOKE,
                    "role_assignment",
                    revoke.assignment_id,
                    {
                        "role_id": str(revoke.role_id),
                        "role_key": revoke.role_key,
                        "workspace_id": str(revoke.workspace_id),
                        "user_id": str(user_id),
                    },
                    workspace_id=revoke.workspace_id,
                )
            )
        for ws in plan.dropped_memberships:
            membership = self.memberships.pop((user_id, ws))
            for gone in [a for a in self.assignments.values() if a.membership_id == membership]:
                del self.assignments[gone.id]
            self.audits.append(
                audits.event(
                    _ACTION_MEMBERSHIP_REVOKE,
                    "membership",
                    user_id,
                    {"user_id": str(user_id), "workspace_id": str(ws)},
                    workspace_id=ws,
                )
            )
        proposals: list[uuid.UUID] = []
        for grant in plan.grants:
            proposal = NewProposal(
                id=uuid.uuid4(),
                kind="assignment_grant",
                role_id=grant.role_id,
                base_version=1,
                payload={
                    "membership_id": str(self.memberships[(user_id, grant.workspace_id)]),
                    "workspace_id": str(grant.workspace_id),
                    "user_id": str(user_id),
                    "role_key": grant.role_key,
                },
            )
            self.proposals.append(proposal)
            self.audits.append(audits.proposed(proposal))
            proposals.append(proposal.id)
        return AssignmentOutcome(user_id=user_id, applied=plan.revokes, proposals=tuple(proposals))
