"""The Allowed host rules that live in Python (connections-and-vault R3.8,
R3.9, R3.11, R3.12, R3.18, R3.19): the pattern, the order of refusals, what a
request writes and what a settlement decides.

The fake honours its Protocol: `open_request` writes only while a checker
exists, `remove` answers None for a row that is not live, and `settle` writes
the row and its audit only when the row is new, like the SQL it stands in for.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.pagination import Page, PageQuery, PageRequest
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.application.access_context import AccessContext
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.egress_allowlist import (
    ALLOWLIST_ADDED,
    ALLOWLIST_REMOVED,
    ALLOWLIST_REQUESTED,
    EGRESS_ALLOWED_HOST,
    INTEGRATIONS_ADMIN_SCOPE,
    AllowedHostDecision,
    AllowedHostSettlement,
    AllowedHostSettler,
    EgressAllowlistService,
    NewAllowedHost,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.allowed_hosts import (
    AllowedHost,
    HostPatternError,
    PublicSuffixList,
    normalize_allowed_host_pattern,
    normalize_ports,
)
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

TENANT, WS, ME, OTHER = (uuid.uuid4() for _ in range(4))
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _context(*scopes: str) -> AccessContext:
    return AccessContext(
        tenant_id=TENANT,
        workspace_id=WS,
        principal_id=ME,
        roles=frozenset(),
        scopes=frozenset(scopes),
        plan_id="pro",
    )


ADMIN = _context(INTEGRATIONS_ADMIN_SCOPE)


# -- the pattern (R3.8, R3.21) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("*.acme.vn", "*.acme.vn"),
        ("API.Acme.vn.", "api.acme.vn"),
        ("*.Bộ-Công-An.vn", "*.xn--b-cng-an-63a1467e.vn"),
        ("github.io", "github.io"),
        ("*.www.ck", "*.www.ck"),
    ],
)
def test_a_pattern_is_stored_the_way_egress_compares_it(raw: str, stored: str) -> None:
    assert normalize_allowed_host_pattern(raw) == stored


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("*.com.vn", "host_pattern_public_suffix"),
        ("*.vn", "host_pattern_public_suffix"),
        ("*.github.io", "host_pattern_public_suffix"),
        ("*.foo.ck", "host_pattern_public_suffix"),
        ("203.0.113.5", "host_pattern_ip_literal"),
        ("*.1.2.3.4", "host_pattern_ip_literal"),
        ("::1", "host_pattern_ip_literal"),
        ("[2606:4700::1]", "host_pattern_ip_literal"),
        ("a_b.acme.vn", "host_pattern_invalid"),
        ("*.*.acme.vn", "host_pattern_invalid"),
        ("api.acme.vn:443", "host_pattern_invalid"),
        ("a..b", "host_pattern_invalid"),
        ("x" * 250 + ".vn", "host_pattern_invalid"),
    ],
)
def test_a_pattern_that_may_not_be_an_allowed_host_is_refused(raw: str, reason: str) -> None:
    """R3.8 (CV19): a wildcard on a public suffix, ICANN and PRIVATE alike, and
    an IP literal."""
    with pytest.raises(HostPatternError) as refused:
        normalize_allowed_host_pattern(raw)
    assert refused.value.details["reason_code"] == reason


def test_the_suffix_rules_read_exceptions_and_wildcards() -> None:
    psl = PublicSuffixList.parse(
        "// c\nvn\ncom.vn\n*.ck\n!www.ck\n// ===BEGIN PRIVATE===\ngithub.io\n"
    )
    assert psl.is_public_suffix("com.vn") and psl.is_public_suffix("github.io")
    assert psl.is_public_suffix("foo.ck") and not psl.is_public_suffix("www.ck")
    assert psl.is_public_suffix("org")  # the implicit `*` rule
    assert not psl.is_public_suffix("acme.vn")


@pytest.mark.parametrize("ports", [(), (0,), (65536,), tuple(range(1, 18))])
def test_ports_are_one_to_sixteen_tcp_ports(ports: tuple[int, ...]) -> None:
    with pytest.raises(DomainError):
        normalize_ports(ports)


def test_ports_are_kept_distinct_and_in_order() -> None:
    assert normalize_ports((8443, 443, 443)) == (443, 8443)


# -- the service --------------------------------------------------------------------------


@dataclass
class FakeRepo:
    checkers: bool = True
    rows: dict[uuid.UUID, AllowedHost] = field(default_factory=dict)
    removed: set[uuid.UUID] = field(default_factory=set)
    requests: list[ApprovalRequest] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)

    async def list(self, context: AccessContext, request: PageRequest) -> Page[AllowedHost]:
        live = [r for r in self.rows.values() if r.id not in self.removed]
        return Page(items=tuple(live), next_cursor=None)

    async def open_request(
        self, context: AccessContext, request: ApprovalRequest, *, audit: AuditEvent
    ) -> bool:
        if not self.checkers:
            return False
        self.requests.append(request)
        self.audit.append(audit)
        return True

    async def remove(
        self,
        context: AccessContext,
        host_id: uuid.UUID,
        *,
        audit_for: Callable[[AllowedHost], AuditEvent],
    ) -> AllowedHost | None:
        row = self.rows.get(host_id)
        if row is None or host_id in self.removed:
            return None
        self.removed.add(host_id)
        self.audit.append(audit_for(row))
        return row


def _service(repo: FakeRepo) -> EgressAllowlistService:
    return EgressAllowlistService(
        repo=repo,
        authz=ScopeAuthorizationService(),
        clock=FixedClock(NOW),
        id_generator=Uuid4Generator(),
    )


def _row(host_id: uuid.UUID | None = None) -> AllowedHost:
    return AllowedHost(
        id=host_id or uuid.uuid4(),
        host_pattern="*.acme.vn",
        ports=(443,),
        purpose="http_tool",
        note=None,
        owning_workspace_id=WS,
        created_by=OTHER,
        created_at=NOW,
    )


async def test_a_request_opens_a_stamped_strict_approval_and_writes_no_row() -> None:
    """R3.9 (CV22): the normalized form in the payload, nothing allowed yet."""
    repo = FakeRepo()

    approval_id = await _service(repo).propose(
        ADMIN, NewAllowedHost("*.ACME.vn.", "http_tool", (8443, 443), note="CRM")
    )

    (request,) = repo.requests
    assert request.id == approval_id
    assert request.approval_type == EGRESS_ALLOWED_HOST
    assert request.required_scope == INTEGRATIONS_ADMIN_SCOPE
    assert request.run_id is None and request.requested_by.value == ME
    assert request.payload == {
        "host_pattern": "*.acme.vn",
        "ports": [443, 8443],
        "purpose": "http_tool",
        "note": "CRM",
    }
    assert [e.action for e in repo.audit] == [ALLOWLIST_REQUESTED]
    assert repo.rows == {}


async def test_without_a_checker_no_approval_is_opened() -> None:
    """R3.12 (CV22)."""
    repo = FakeRepo(checkers=False)

    with pytest.raises(ConflictError) as refused:
        await _service(repo).propose(ADMIN, NewAllowedHost("api.acme.vn", "http_tool"))

    assert refused.value.details == {"reason_code": "no_checker_available"}
    assert repo.requests == [] and repo.audit == []


@pytest.mark.parametrize("context", [_context(), _context("approvals.decide")])
async def test_without_the_key_every_operation_is_refused_before_anything(
    context: AccessContext,
) -> None:
    """R3.19 (CV30): 403 before a row is read, even for a malformed pattern."""
    row = _row()
    repo = FakeRepo(rows={row.id: row})
    service = _service(repo)
    page = PageRequest(limit=10, after=None, query=PageQuery(key=None))

    for attempt in (
        service.list(context, page),
        service.propose(context, NewAllowedHost("203.0.113.5", "http_tool")),
        service.remove(context, row.id),
    ):
        with pytest.raises(PermissionDeniedError):
            await attempt

    assert repo.requests == [] and repo.removed == set() and repo.audit == []


async def test_a_bad_pattern_is_refused_before_an_approval_is_opened() -> None:
    repo = FakeRepo()

    with pytest.raises(HostPatternError):
        await _service(repo).propose(ADMIN, NewAllowedHost("*.com.vn", "http_tool"))

    assert repo.requests == []


async def test_removing_a_live_row_audits_it_and_a_second_removal_is_not_found() -> None:
    """R3.18, R3.19 (CV30)."""
    row = _row()
    repo = FakeRepo(rows={row.id: row})
    service = _service(repo)

    await service.remove(ADMIN, row.id)
    with pytest.raises(NotFoundError):
        await service.remove(ADMIN, row.id)
    with pytest.raises(NotFoundError):
        await service.remove(ADMIN, uuid.uuid4())

    (event,) = repo.audit
    assert (event.action, event.resource_id, event.actor_id.value) == (
        ALLOWLIST_REMOVED,
        str(row.id),
        ME,
    )


# -- the settlement (R3.11) -------------------------------------------------------------------


@dataclass
class FakeSettlementRepo:
    """Inserts `ON CONFLICT DO NOTHING` on the id and on the live pattern."""

    decisions: dict[uuid.UUID, AllowedHostDecision]
    rows: dict[uuid.UUID, AllowedHost] = field(default_factory=dict)
    removed: set[uuid.UUID] = field(default_factory=set)
    audit: list[AuditEvent] = field(default_factory=list)

    async def settle(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[AllowedHostDecision], AllowedHostSettlement],
    ) -> AllowedHostSettlement:
        decision = self.decisions.get(approval_id)
        if decision is None:
            raise NotFoundError("no decided approval")
        settlement = settle(decision)
        row = settlement.row
        if row is None:
            return settlement
        live = {(r.host_pattern, r.purpose) for r in self.rows.values() if r.id not in self.removed}
        if row.id in self.rows or (row.host_pattern, row.purpose) in live:
            return AllowedHostSettlement("already_present")
        self.rows[row.id] = row
        if settlement.audit is not None:
            self.audit.append(settlement.audit)
        return settlement


def _decision(approved: bool = True, approval_id: uuid.UUID | None = None) -> AllowedHostDecision:
    return AllowedHostDecision(
        approval_id=approval_id or uuid.uuid4(),
        approved=approved,
        decided_by=OTHER,
        requested_by=ME,
        workspace_id=WS,
        host_pattern="*.acme.vn",
        ports=(443,),
        purpose="http_tool",
        note=None,
    )


def _settler(repo: FakeSettlementRepo) -> AllowedHostSettler:
    return AllowedHostSettler(repo=repo, clock=FixedClock(NOW), id_generator=Uuid4Generator())


SCOPE = WorkScope(tenant_id=TENANT, workspace_id=WS)


async def test_an_approval_adds_the_row_named_by_the_approval_audited_in_the_deciders_name() -> (
    None
):
    decision = _decision()
    repo = FakeSettlementRepo({decision.approval_id: decision})

    settled = await _settler(repo).settle(SCOPE, decision.approval_id)

    assert settled.outcome == "added"
    assert list(repo.rows) == [decision.approval_id]
    assert repo.rows[decision.approval_id].created_by == ME
    (event,) = repo.audit
    assert event.action == ALLOWLIST_ADDED and event.actor_id.value == OTHER
    assert event.tenant_id.value == TENANT
    assert event.details["lane"] == "outbox"
    assert event.details["approval_id"] == str(decision.approval_id)


async def test_a_replay_even_after_removal_and_a_second_approval_of_the_pattern_add_nothing() -> (
    None
):
    first, second = _decision(), _decision()
    repo = FakeSettlementRepo({first.approval_id: first, second.approval_id: second})
    settler = _settler(repo)

    await settler.settle(SCOPE, first.approval_id)
    assert (await settler.settle(SCOPE, first.approval_id)).outcome == "already_present"
    assert (await settler.settle(SCOPE, second.approval_id)).outcome == "already_present"
    repo.removed.add(first.approval_id)
    assert (await settler.settle(SCOPE, first.approval_id)).outcome == "already_present"

    assert list(repo.rows) == [first.approval_id] and len(repo.audit) == 1


async def test_a_rejection_writes_nothing() -> None:
    decision = _decision(approved=False)
    repo = FakeSettlementRepo({decision.approval_id: decision})

    assert (await _settler(repo).settle(SCOPE, decision.approval_id)).outcome == "rejected"
    assert repo.rows == {} and repo.audit == []
