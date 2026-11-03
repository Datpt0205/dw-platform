"""The service-account rules that live in Python (org-and-principals 03): the
binding guard's order (R6.15, R6.5, R6.17) and the service's order of
refusals (R6.1: 422 before 403; R6.13, R6.14: 404 before 403).

The fakes honour their Protocols: an unknown id answers None or False, never a
made-up row, and a method these tests do not reach raises.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import ConflictError, NotFoundError, PermissionDeniedError
from dw_kernel.pagination import Page, PageRequest
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.service_principals import (
    SERVICE_PRINCIPALS_MANAGE_SCOPE,
    SERVICE_PRINCIPALS_USE_SCOPE,
    BindingFacts,
    MissingGrant,
    NewServicePrincipal,
    ServicePrincipal,
    ServicePrincipalBindingGuard,
    ServicePrincipalChanges,
    ServicePrincipalService,
    WorkspaceNotInTenantError,
    binding_refusal,
)
from dw_platform.domain.audit import AuditEvent

TENANT, WS, OTHER_WS, ME = (uuid.uuid4() for _ in range(4))
ACCOUNT = uuid.uuid4()

GOOD = BindingFacts(
    found=True,
    is_digital_worker=False,
    owning_workspace_id=WS,
    can_use=True,
    active=True,
    owner_present=True,
    uncovered=(),
)
SHORT = MissingGrant("crm.write", "workspace", WS)


def _context() -> AccessContext:
    return AccessContext(
        tenant_id=TENANT, workspace_id=WS, principal_id=ME, roles=frozenset(), plan_id="pro"
    )


@pytest.mark.parametrize(
    ("facts", "error", "reason"),
    [
        (None, NotFoundError, None),
        (replace(GOOD, found=False, can_use=False, active=False), NotFoundError, None),
        (replace(GOOD, is_digital_worker=True, uncovered=(SHORT,)), NotFoundError, None),
        (replace(GOOD, can_use=False, active=False), PermissionDeniedError, "rbac_escalation"),
        (replace(GOOD, active=False, owner_present=False), ConflictError, "principal_inactive"),
        (replace(GOOD, owner_present=False, uncovered=(SHORT,)), ConflictError, "owner_missing"),
        (replace(GOOD, uncovered=(SHORT,)), PermissionDeniedError, "rbac_escalation"),
    ],
)
def test_the_guard_refuses_in_its_order(
    facts: BindingFacts | None, error: type[Exception], reason: str | None
) -> None:
    refused = binding_refusal(facts)
    assert isinstance(refused, error)
    assert refused.details.get("reason_code") == reason
    if error is NotFoundError:
        assert "missing" not in refused.details


def test_the_guard_names_what_is_missing() -> None:
    no_use = binding_refusal(replace(GOOD, can_use=False))
    assert no_use is not None
    assert no_use.details["missing"] == [
        {
            "permission_key": SERVICE_PRINCIPALS_USE_SCOPE,
            "depth": "workspace",
            "anchor_workspace_id": str(WS),
        }
    ]
    short = binding_refusal(replace(GOOD, uncovered=(SHORT,)))
    assert short is not None
    assert short.details["missing"] == [
        {"permission_key": "crm.write", "depth": "workspace", "anchor_workspace_id": str(WS)}
    ]
    assert binding_refusal(GOOD) is None


@dataclass
class _Facts:
    facts: dict[uuid.UUID, BindingFacts]

    async def binding_facts(
        self, context: AccessContext, principal_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, BindingFacts]:
        return {i: self.facts[i] for i in principal_ids if i in self.facts}


async def test_bindable_is_the_guards_decision_per_row() -> None:
    other = uuid.uuid4()
    guard = ServicePrincipalBindingGuard(
        _Facts({ACCOUNT: GOOD, other: replace(GOOD, uncovered=(SHORT,))})
    )
    unknown = uuid.uuid4()
    assert await guard.bindable(_context(), [ACCOUNT, other, unknown]) == {
        ACCOUNT: True,
        other: False,
        unknown: False,
    }
    decided = await guard.bindable(_context(), [ACCOUNT, other])
    assert decided == {ACCOUNT: True, other: False}
    assert await guard.bindable(_context(), []) == {}
    await guard.require_bindable(_context(), ACCOUNT)
    with pytest.raises(PermissionDeniedError):
        await guard.require_bindable(_context(), other)


@dataclass
class _Repo:
    """Workspaces of the tenant, what the caller reaches per key, and rows."""

    workspaces: set[uuid.UUID] = field(default_factory=lambda: {WS, OTHER_WS})
    reach: dict[str, set[uuid.UUID]] = field(default_factory=dict)
    rows: dict[uuid.UUID, ServicePrincipal] = field(default_factory=dict)
    written: list[AuditEvent] = field(default_factory=list)

    async def workspace_usable(self, context: AccessContext, workspace_id: uuid.UUID) -> bool:
        return workspace_id in self.workspaces

    async def reaches(
        self, context: AccessContext, permission_key: str, workspace_id: uuid.UUID
    ) -> bool:
        return workspace_id in self.reach.get(permission_key, set())

    async def create(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        command: NewServicePrincipal,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        self.rows[principal_id] = ServicePrincipal(
            id=principal_id,
            name=command.name,
            description=command.description,
            owning_workspace_id=command.owning_workspace_id,
            owner_user_id=command.owner_user_id,
            owner_missing=False,
            status="active",
        )
        self.written.append(audit)

    async def get(self, context: AccessContext, principal_id: uuid.UUID) -> ServicePrincipal | None:
        return self.rows.get(principal_id)

    async def update(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        changes: ServicePrincipalChanges,
        *,
        audit: AuditEvent,
    ) -> bool:
        if principal_id not in self.rows:
            return False
        row = self.rows[principal_id]
        self.rows[principal_id] = replace(
            row,
            name=changes.name or row.name,
            owner_user_id=changes.owner_user_id or row.owner_user_id,
        )
        self.written.append(audit)
        return True

    async def page(self, context: AccessContext, request: PageRequest) -> Page[ServicePrincipal]:
        raise NotImplementedError("not exercised by these tests")


def _service(repo: _Repo) -> ServicePrincipalService:
    return ServicePrincipalService(
        repo=repo,
        binding=ServicePrincipalBindingGuard(_Facts({})),
        clock=FixedClock(datetime(2026, 11, 3, tzinfo=UTC)),
        id_generator=Uuid4Generator(),
    )


def _new(workspace: uuid.UUID) -> NewServicePrincipal:
    return NewServicePrincipal(
        name="Lịch đêm", description=None, owning_workspace_id=workspace, owner_user_id=ME
    )


async def test_a_workspace_outside_the_company_is_422_before_any_403() -> None:
    """R6.1: an unknown workspace says nothing about the caller's reach."""
    repo = _Repo()
    with pytest.raises(WorkspaceNotInTenantError) as refused:
        await _service(repo).create(_context(), _new(uuid.uuid4()))
    assert refused.value.pointer == "/owning_workspace_id"
    with pytest.raises(PermissionDeniedError) as denied:
        await _service(repo).create(_context(), _new(WS))
    assert denied.value.details["action"] == SERVICE_PRINCIPALS_MANAGE_SCOPE
    assert repo.rows == {} and repo.written == []


async def test_a_patch_is_404_before_403_and_audits_ids_only() -> None:
    """R6.13 before R6.14; the audit names the old and new owner, not the name."""
    repo = _Repo(reach={SERVICE_PRINCIPALS_MANAGE_SCOPE: {WS}})
    created = await _service(repo).create(_context(), _new(WS))
    account = created.principal.id
    with pytest.raises(NotFoundError):
        await _service(_Repo()).update(_context(), account, ServicePrincipalChanges(name="x"))
    elsewhere = _Repo(rows=dict(repo.rows), reach={SERVICE_PRINCIPALS_MANAGE_SCOPE: {OTHER_WS}})
    with pytest.raises(PermissionDeniedError):
        await _service(elsewhere).update(_context(), account, ServicePrincipalChanges(name="x"))
    assert elsewhere.written == []

    successor = uuid.uuid4()
    await _service(repo).update(
        _context(), account, ServicePrincipalChanges(name="Mới", owner_user_id=successor)
    )
    audit = repo.written[-1]
    assert audit.details == {
        "fields": ["name", "owner_user_id"],
        "owner_user_id": {"from": str(ME), "to": str(successor)},
    }
    assert "Mới" not in str(audit.details)
