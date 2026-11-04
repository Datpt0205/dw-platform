"""A tenant's own configuration versions: one person proposes, another approves
(tenant-config R8; ADR-0110 decisions 1-4, 7; ADR-0104 decision 11; D11).

`platform.config_versions` holds every proposal of every registered kind, and
the database holds what a row may become: `approved` only through an approved
`config.version` request (`approved_by_approval`), never decided by its own
proposer (`ck_config_versions_checker_not_maker`), one open proposal and one
approved version per key. This module asks the questions the database cannot:

- `ConfigKindRegistry`: the kinds there are (W1: `binding_set`, registered by
  Studio at the composition root). What a key is, who may read it, what a
  value must be and whether a proposal is still current are the kind's
  (`ConfigKind`); an unregistered kind is a 422.
- `ConfigVersionService.propose`: in the key's owning workspace, never the
  caller's working one (R8.17): the kind answers 404 for a key the caller
  cannot read, then `propose_key` at that workspace or 403; the value checked
  by the kind (404, 422); someone else who holds `approve_key` there and can
  read the key, or 409 `no_checker_available`; then one transaction writes the
  `proposed` row, a run-less strict `config.version` request stamped with
  `approve_key` and `config.version.proposed`.
- `ConfigVersionService.withdraw`: the proposer alone (403), while the request
  is `pending` (409 `proposal_decided`), with the request read `FOR UPDATE`.
- `ConfigVersionDecisions`: the `config.version` guard the approval flow asks
  before it writes a decision: the decider reads the key (404), and the
  proposal is still current (409 `decision_stale`, R8.9, R8.11).
- `ConfigSettlement`: the worker's handler of `config.version.decided`, at
  least once, in the decider's name with `details.lane` `outbox` (R8.10,
  R8.11, R8.15, R8.19).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

from dw_kernel.canonical import content_hash
from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import EffectClaim, PendingEffect
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import (
    ApprovalRequest,
    ApprovalStatus,
    DecisionOutcome,
    ProposedDecision,
    decided_event_type,
)
from dw_platform.domain.audit import AuditEvent

__all__ = [
    "CONFIG_PREFIX",
    "CONFIG_VERSION",
    "CONFIG_VERSION_DECIDED",
    "ConfigKind",
    "ConfigKindRegistry",
    "ConfigSettlement",
    "ConfigTarget",
    "ConfigVersionDecisions",
    "ConfigVersionRow",
    "ConfigVersionService",
    "ConfigVersionStore",
    "ConfigVersionTx",
    "NewConfigVersion",
    "RecordedDecision",
]

# The run-less approval of a proposal, strict by its prefix at both
# composition roots (R8.8).
CONFIG_PREFIX: Final = "config."
CONFIG_VERSION: Final = "config.version"
CONFIG_VERSION_DECIDED: Final = decided_event_type(CONFIG_VERSION)

PROPOSED: Final = "config.version.proposed"
APPROVED: Final = "config.version.approved"
REJECTED: Final = "config.version.rejected"
WITHDRAWN: Final = "config.version.withdrawn"
RESOURCE: Final = "config_version"
# The lane carrying out a person's recorded decision (CLAUDE.md, lane audit).
SETTLING_LANE: Final = "outbox"

Status = Literal["proposed", "approved", "rejected", "withdrawn", "superseded"]


@dataclass(frozen=True, slots=True)
class ConfigTarget:
    """What a kind says of one key, as the caller sees it now."""

    key: str
    owning_workspace_id: uuid.UUID
    read_key: str
    # The base a proposal is checked against: its number and the hash a later
    # base must keep for the proposal to stay current (`base_bindings_hash`).
    base_version: int
    base_hash: str
    # The numbers still sealed: a base taken back to its draft is not one.
    sealed_versions: frozenset[int]
    # What the approval's reason shows the decider.
    label: str


class ConfigKind(Protocol):
    """One registered kind. Raising is refusing: `NotFoundError` for a key, a
    connection or a principal the caller may not see, `DocumentInvalidError`
    (422, one problem per pointer) for a value."""

    @property
    def kind(self) -> str: ...

    @property
    def propose_key(self) -> str: ...

    @property
    def approve_key(self) -> str: ...

    async def readable(self, context: AccessContext, key: str) -> None:
        """404 for a key the caller cannot read at its owning workspace."""
        ...

    async def target(self, context: AccessContext, key: str) -> ConfigTarget:
        """`readable`'s 404, then 409 `no_sealed_version` for a key with
        nothing to check a value against."""
        ...

    async def check(self, context: AccessContext, target: ConfigTarget, document: Any) -> None:
        """Every value, against the base, for the proposer."""
        ...

    async def usable(
        self,
        tenant_id: uuid.UUID,
        key: str,
        workspace_id: uuid.UUID,
        proposer: uuid.UUID,
        document: Any,
    ) -> bool:
        """Whether what the value uses is still usable by its proposer there,
        asked again when it is approved (R8.9; ADR-0110 decision 7)."""
        ...


class ConfigKindRegistry:
    """The kinds `platform.config_versions` takes (`ck_config_versions_kind`),
    frozen at the composition root."""

    def __init__(self, kinds: Sequence[ConfigKind]) -> None:
        by_kind: dict[str, ConfigKind] = {}
        for entry in kinds:
            if entry.kind in by_kind:
                raise ValueError(f"config kind {entry.kind!r} registered twice")
            by_kind[entry.kind] = entry
        self._kinds: Mapping[str, ConfigKind] = MappingProxyType(by_kind)

    def get(self, kind: str) -> ConfigKind | None:
        return self._kinds.get(kind)

    def __iter__(self) -> Iterator[ConfigKind]:
        return iter(self._kinds.values())

    def require(self, kind: str) -> ConfigKind:
        found = self._kinds.get(kind)
        if found is None:
            raise DomainError(
                "this kind of configuration is not registered",
                details={"reason_code": "config_kind_unknown", "kind": kind},
            )
        return found


# ---- storage ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigVersionRow:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    key: str
    version_no: int
    base_version: int
    base_bindings_hash: str
    base_approved_id: uuid.UUID | None
    document: Any
    document_hash: str
    status: Status
    approval_id: uuid.UUID
    proposed_by: uuid.UUID
    proposed_at: datetime
    decided_by: uuid.UUID | None
    decided_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewConfigVersion:
    id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    key: str
    version_no: int
    base_version: int
    base_bindings_hash: str
    base_approved_id: uuid.UUID | None
    document: Any
    document_hash: str
    approval_id: uuid.UUID
    proposed_by: uuid.UUID


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """The decision row of a `config.version` request."""

    outcome: DecisionOutcome
    decided_by: uuid.UUID
    decided_at: datetime
    comment: str


class ConfigVersionTx(Protocol):
    """One transaction under one company's RLS, its principal kept for
    `platform.workspace_reach`."""

    async def reach(self, key: str) -> frozenset[uuid.UUID]: ...

    async def has_checker(
        self, approve_key: str, read_key: str, proposer: uuid.UUID, workspace_id: uuid.UUID
    ) -> bool:
        """Someone but the proposer who holds `approve_key` reaching the
        workspace (`platform.checker_candidates`) and reads the key there."""
        ...

    async def current(
        self, kind: str, key: str, status: Status, *, lock: bool = False
    ) -> ConfigVersionRow | None:
        """The key's one `proposed` or one `approved` row."""
        ...

    async def next_version_no(self, kind: str, key: str) -> int: ...

    async def insert(self, row: NewConfigVersion) -> None:
        """`ConflictError` `proposal_open` when the key already has an open
        proposal, by the constraint's name."""
        ...

    async def by_id(
        self, config_version_id: uuid.UUID, *, lock: bool
    ) -> ConfigVersionRow | None: ...

    async def by_approval(
        self, approval_id: uuid.UUID, *, lock: bool
    ) -> ConfigVersionRow | None: ...

    async def open_approval(self, request: ApprovalRequest) -> None: ...

    async def approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        """The request, read `FOR UPDATE`, under the tenant's RLS alone."""
        ...

    async def save_approval(self, request: ApprovalRequest) -> None: ...

    async def decision(self, approval_id: uuid.UUID) -> RecordedDecision | None: ...

    async def set_status(
        self,
        config_version_id: uuid.UUID,
        status: Status,
        *,
        decided_by: uuid.UUID | None = None,
        decision_comment: str | None = None,
    ) -> None:
        """The status, with `decided_at` (or `superseded_at`) the database's now."""
        ...

    async def claim(self, claim: EffectClaim) -> None: ...

    async def audit(self, event: AuditEvent) -> None: ...


class ConfigVersionStore(Protocol):
    def transaction(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None,
        principal_id: uuid.UUID | None,
    ) -> AbstractAsyncContextManager[ConfigVersionTx]: ...


def _conflict(message: str, reason: str, **details: object) -> ConflictError:
    return ConflictError(message, details={"reason_code": reason, **details})


# ---- propose and withdraw -------------------------------------------------------


@dataclass(frozen=True)
class ConfigVersionService:
    registry: ConfigKindRegistry
    store: ConfigVersionStore
    clock: UtcClock
    id_generator: IdGenerator

    def _tx(self, context: AccessContext) -> AbstractAsyncContextManager[ConfigVersionTx]:
        return self.store.transaction(
            context.tenant_id, workspace_id=context.workspace_id, principal_id=context.principal_id
        )

    async def check_propose(self, context: AccessContext, kind: str, key: str) -> ConfigTarget:
        """Who may propose (404, 403), before a key row or a value is read
        (app-standards R2.30)."""
        entry = self.registry.require(kind)
        target = await entry.target(context, key)
        async with self._tx(context) as tx:
            if target.owning_workspace_id not in await tx.reach(entry.propose_key):
                raise PermissionDeniedError(
                    "you may read this and not propose its configuration",
                    details={"reason_code": "permission_denied", "action": entry.propose_key},
                )
        return target

    async def propose(
        self,
        context: AccessContext,
        kind: str,
        key: str,
        document: Any,
        *,
        effect: PendingEffect | None = None,
    ) -> ConfigVersionRow:
        """R8.1-R8.7, R8.17: one `proposed` row, its request and its audit."""
        entry = self.registry.require(kind)
        target = await self.check_propose(context, kind, key)
        await entry.check(context, target, document)
        workspace = target.owning_workspace_id
        config_version_id = self.id_generator.new_uuid()
        approval_id = self.id_generator.new_uuid()
        document_hash = content_hash(document)
        async with self._tx(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(config_version_id))
            if await tx.current(kind, key, "proposed") is not None:
                raise _conflict("this configuration already has an open proposal", "proposal_open")
            if not await tx.has_checker(
                entry.approve_key, target.read_key, context.principal_id, workspace
            ):
                raise _conflict(
                    "nobody but the proposer could approve this configuration",
                    "no_checker_available",
                )
            approved = await tx.current(kind, key, "approved")
            version_no = await tx.next_version_no(kind, key)
            await tx.open_approval(
                ApprovalRequest(
                    id=approval_id,
                    tenant_id=TenantId(context.tenant_id),
                    workspace_id=WorkspaceId(workspace),
                    approval_type=CONFIG_VERSION,
                    requested_by=UserId(context.principal_id),
                    reason=f"{kind} {target.label} v{version_no}",
                    # Identifiers only: the decider reads the values where
                    # they may (`GET .../bindings`, R8.17).
                    payload={
                        "config_version_id": str(config_version_id),
                        "kind": kind,
                        "key": key,
                        "version_no": version_no,
                        "document_hash": document_hash,
                    },
                    required_scope=entry.approve_key,
                )
            )
            await tx.insert(
                NewConfigVersion(
                    id=config_version_id,
                    workspace_id=workspace,
                    kind=kind,
                    key=key,
                    version_no=version_no,
                    base_version=target.base_version,
                    base_bindings_hash=target.base_hash,
                    base_approved_id=None if approved is None else approved.id,
                    document=document,
                    document_hash=document_hash,
                    approval_id=approval_id,
                    proposed_by=context.principal_id,
                )
            )
            await tx.audit(
                self._event(
                    context.tenant_id,
                    workspace,
                    context.principal_id,
                    PROPOSED,
                    config_version_id,
                    {
                        "kind": kind,
                        "key": key,
                        "version_no": version_no,
                        "approval_id": str(approval_id),
                        "document_hash": document_hash,
                    },
                )
            )
            row = await tx.by_id(config_version_id, lock=False)
        assert row is not None
        return row

    async def get(
        self, context: AccessContext, kind: str, key: str, config_version_id: uuid.UUID
    ) -> ConfigVersionRow:
        """One proposal of a key the caller reads (404 otherwise)."""
        await self.registry.require(kind).readable(context, key)
        async with self._tx(context) as tx:
            row = await tx.by_id(config_version_id, lock=False)
        if row is None or row.kind != kind or row.key != key:
            raise NotFoundError("proposal not found", details={"id": str(config_version_id)})
        return row

    async def check_withdraw(
        self, context: AccessContext, kind: str, key: str, config_version_id: uuid.UUID
    ) -> None:
        """404 unless the caller reads the key and the proposal is of it; 403
        unless they proposed it (R8.14, TC26)."""
        await self.registry.require(kind).readable(context, key)
        async with self._tx(context) as tx:
            row = await tx.by_id(config_version_id, lock=False)
        self._own(context, kind, key, config_version_id, row)

    @staticmethod
    def _own(
        context: AccessContext,
        kind: str,
        key: str,
        config_version_id: uuid.UUID,
        row: ConfigVersionRow | None,
    ) -> ConfigVersionRow:
        if row is None or row.kind != kind or row.key != key:
            raise NotFoundError("proposal not found", details={"id": str(config_version_id)})
        if row.proposed_by != context.principal_id:
            raise PermissionDeniedError(
                "only its proposer withdraws a proposal",
                details={"reason_code": "permission_denied", "action": "withdraw"},
            )
        return row

    async def withdraw(
        self,
        context: AccessContext,
        kind: str,
        key: str,
        config_version_id: uuid.UUID,
        *,
        effect: PendingEffect | None = None,
    ) -> ConfigVersionRow:
        """R8.13, R8.14, R8.18: `withdrawn` and the request `cancelled` in one
        transaction, only while the request is `pending`."""
        await self.registry.require(kind).readable(context, key)
        async with self._tx(context) as tx:
            if effect is not None:
                await tx.claim(effect.of(config_version_id))
            row = self._own(
                context, kind, key, config_version_id, await tx.by_id(config_version_id, lock=True)
            )
            # The request first, FOR UPDATE: a decision committed before this
            # lock is seen, and one after it waits and meets `cancelled`.
            request = await tx.approval(row.approval_id)
            if (
                request is None
                or request.status is not ApprovalStatus.PENDING
                or row.status != "proposed"
            ):
                raise _conflict("this proposal has been decided", "proposal_decided")
            await tx.set_status(row.id, "withdrawn")
            request.cancel()
            await tx.save_approval(request)
            await tx.audit(
                self._event(
                    context.tenant_id,
                    row.workspace_id,
                    context.principal_id,
                    WITHDRAWN,
                    row.id,
                    {"kind": kind, "key": key, "approval_id": str(row.approval_id)},
                )
            )
            withdrawn = await tx.by_id(row.id, lock=False)
        assert withdrawn is not None
        return withdrawn

    def _event(
        self,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        action: str,
        config_version_id: uuid.UUID,
        details: dict[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(tenant_id),
            workspace_id=WorkspaceId(workspace_id),
            actor_id=UserId(actor),
            action=action,
            resource_type=RESOURCE,
            resource_id=str(config_version_id),
            occurred_at=self.clock.now(),
            details=details,
        )


# ---- the decision guard ---------------------------------------------------------


@dataclass(frozen=True)
class ConfigVersionDecisions:
    """The `config.version` entry of the approval flow's `decision_guards`
    (R8.9, R8.11, R8.17): asked before a decision is written, so a refusal
    leaves the request `pending`."""

    registry: ConfigKindRegistry
    store: ConfigVersionStore

    async def check(
        self, request: ApprovalRequest, decision: ProposedDecision, context: AccessContext
    ) -> None:
        if request.status is not ApprovalStatus.PENDING:
            # A retry of a decision already made meets its own answer in `decide`.
            return
        async with self.store.transaction(
            context.tenant_id, workspace_id=context.workspace_id, principal_id=context.principal_id
        ) as tx:
            row = await tx.by_approval(request.id, lock=False)
            if row is None:
                raise NotFoundError("proposal not found", details={"approval_id": str(request.id)})
            approved = await tx.current(row.kind, row.key, "approved")
        entry = self.registry.require(row.kind)
        # The decider must read what they decide (R8.17, gate 4/11/2026 (e)):
        # a 404 from the kind passes through.
        try:
            target = await entry.target(context, row.key)
        except ConflictError:
            raise _stale(request, "no_sealed_version") from None
        if target.base_hash != row.base_bindings_hash:
            raise _stale(request, "bindings_changed")
        if row.base_version not in target.sealed_versions:
            raise _stale(request, "base_not_sealed")
        if (None if approved is None else approved.id) != row.base_approved_id:
            raise _stale(request, "approved_changed")
        if decision.approve and not await entry.usable(
            row.tenant_id, row.key, row.workspace_id, row.proposed_by, row.document
        ):
            raise _stale(request, "connection_unusable")


def _stale(request: ApprovalRequest, why: str) -> ConflictError:
    return _conflict(
        "the proposal no longer matches what it was proposed against",
        "decision_stale",
        approval_id=str(request.id),
        stale=why,
    )


# ---- settlement on the worker ---------------------------------------------------

SettlementOutcome = Literal["approved", "rejected", "settlement_conflict", "unchanged"]


@dataclass(frozen=True)
class ConfigSettlement:
    """`config.version.decided`, carried out (R8.10, R8.11, R8.15, R8.19).

    Idempotent by the request's id: a row no longer `proposed` (settled
    already, or withdrawn by its proposer) is left as it is and audited
    nothing; the trigger would refuse anything else."""

    store: ConfigVersionStore
    clock: UtcClock
    id_generator: IdGenerator

    async def settle(self, scope: WorkScope, approval_id: uuid.UUID) -> SettlementOutcome:
        async with self.store.transaction(
            scope.tenant_id, workspace_id=scope.workspace_id, principal_id=None
        ) as tx:
            row = await tx.by_approval(approval_id, lock=True)
            decision = await tx.decision(approval_id)
            if row is None or decision is None:
                raise NotFoundError(
                    "no decided config.version request of that id",
                    details={"approval_id": str(approval_id)},
                )
            if row.status != "proposed":
                return "unchanged"
            outcome: SettlementOutcome
            details: dict[str, object] = {
                "kind": row.kind,
                "key": row.key,
                "version_no": row.version_no,
                "approval_id": str(approval_id),
                "proposed_by": str(row.proposed_by),
                "lane": SETTLING_LANE,
            }
            if decision.outcome is DecisionOutcome.APPROVED:
                current = await tx.current(row.kind, row.key, "approved", lock=True)
                current_id = None if current is None else current.id
                if current_id != row.base_approved_id:
                    outcome = "settlement_conflict"
                    details["reason"] = "settlement_conflict"
                else:
                    if current is not None:
                        await tx.set_status(current.id, "superseded")
                        details["superseded_id"] = str(current.id)
                    outcome = "approved"
            else:
                outcome = "rejected"
            await tx.set_status(
                row.id,
                "approved" if outcome == "approved" else "rejected",
                decided_by=decision.decided_by,
                decision_comment=decision.comment,
            )
            await tx.audit(
                AuditEvent(
                    id=self.id_generator.new_uuid(),
                    tenant_id=TenantId(row.tenant_id),
                    workspace_id=WorkspaceId(row.workspace_id),
                    # A lane carrying out one person's decision audits that person.
                    actor_id=UserId(decision.decided_by),
                    action=APPROVED if outcome == "approved" else REJECTED,
                    resource_type=RESOURCE,
                    resource_id=str(row.id),
                    occurred_at=self.clock.now(),
                    details=details,
                )
            )
        return outcome
