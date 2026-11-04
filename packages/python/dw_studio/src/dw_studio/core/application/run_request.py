"""`RunRequestService`: the one door a Studio run is created through
(workflow-engine R3; ADR-0113 decision 1, ADR-0103 decision 4, ADR-0109
decisions 4 and 6).

It writes one `queued` row of `platform.worker_runs` in the caller's
transaction and never calls a runner: the `studio_runs` lane takes the row
(workflow-engine/04). Everything the row says about the run comes from data
the door verified, never from the request:

- the workspace from the root artifact's `owning_workspace_id`, and
  `artifact_kind`, `artifact_id`, `definition_hash` from the version row, both
  read under RLS with the artifact row `FOR SHARE`, so a concurrent
  `save_draft` waits and the content validated is the content hashed (R3.18,
  R3.11);
- who asks and whom the run acts as from the verified requester: a person
  (`PersonRequester`, an `AccessContext`) for `chat`, `manual` and `test`; a
  lane (`LaneRequester`) issued only by the `RunLaneRegistry` frozen at the
  composition root, for the trigger kinds that registry gives it (R3.19);
- the person's right to run, checked here and not only at a route: the run
  key the run-key table names for `(artifact_kind, trigger_kind)` must reach
  the run's workspace through `platform.workspace_reach` (R3.17; ADR-0104
  decision 5), never `authz.require`, which reads the context's workspace
  only and lets `platform_admin` through.

- the run's bindings (tenant-config ticket 05; R7.3, R7.4, R7.6): the
  artifact's approved Binding set checked against the root version's own
  declarations and its connections asked for the run's principal at the run's
  workspace, by `BindingPins`, before the manifest is written; a refusal
  (`binding_unset`, `binding_degraded`) leaves no manifest and no run row.
- the run's models (model-connections ticket 02; R1.4, R1.6): pinned by value
  in the manifest for the tenant of the transaction and that tenant's plan,
  read here, for a person and a lane alike; a profile the root declares that
  the plan does not list (`model_profile_unavailable`) leaves no manifest and
  no run row.

A request repeated under the same `request_key` gets the first run back, and a
different request under it is refused (R3.20). Whether the run-as principal
is still active is the dispatch's question (R5.15), not the door's.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

from dw_kernel.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.run_mode import RunMode
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.audit import AuditEvent, lane_audit_event, system_actor, system_actor_label
from dw_studio.core.application.bindings import BindingPins, PinnedBindings
from dw_studio.core.application.ports import RootVersion, RunManifestTx
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.service import document_problems
from dw_studio.core.domain.artifacts import DocumentInvalidError, Stage
from dw_studio.core.domain.bindings import BindingDecl

RESOURCE: Final = "worker_run"
STARTED: Final = "run.started"


@dataclass(frozen=True, slots=True)
class _TriggerRule:
    run_mode: RunMode
    # 0 a person's interactive run, 1 a trigger's, 2 the quality gate's (ADR-0113).
    priority: int
    asked_by: Literal["person", "lane"]
    # A lane acting on its own (an inbound event) is its own requester; a lane
    # carrying out one person's recorded decision (the gate's trial of their
    # candidate) asks in that person's name (CLAUDE.md, Agent and tool rules).
    lane_acts_as_itself: bool = False


# The W1 set of `ck_worker_runs_trigger_kind`, one rule per kind; a W2 kind
# joins with its CHECK and its writer. `test` and `eval` run `simulate` in W1
# (workflow-triggers R2.3; ADR-0120).
_TRIGGERS: Final[Mapping[str, _TriggerRule]] = MappingProxyType(
    {
        "chat": _TriggerRule("live", 0, "person"),
        "manual": _TriggerRule("live", 0, "person"),
        "test": _TriggerRule("simulate", 0, "person"),
        "datahub": _TriggerRule("live", 1, "lane", lane_acts_as_itself=True),
        "eval": _TriggerRule("simulate", 2, "lane"),
    }
)
W1_TRIGGER_KINDS: Final = frozenset(_TRIGGERS)
LANE_TRIGGER_KINDS: Final = frozenset(k for k, r in _TRIGGERS.items() if r.asked_by == "lane")


# ---- who asks ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PersonRequester:
    """A person, as their verified access context."""

    context: AccessContext


@dataclass(frozen=True, slots=True)
class LaneRequester:
    """A background lane asking in one tenant. Only `RunLaneRegistry.requester`
    builds one (an architecture test holds that); the door also refuses a lane
    its own registry does not list."""

    lane: str
    tenant_id: uuid.UUID


Requester = PersonRequester | LaneRequester


class RunLaneRegistry:
    """The lanes that may ask for a run, each with the trigger kinds it may
    ask for, frozen at the composition root (like `tenant_wide_scope()`'s)."""

    def __init__(self, lanes: Mapping[str, Iterable[str]]) -> None:
        frozen: dict[str, frozenset[str]] = {}
        for lane, kinds in lanes.items():
            system_actor_label(lane)  # a worker registry name, or ValueError
            asked = frozenset(kinds)
            if not asked or not asked <= LANE_TRIGGER_KINDS:
                raise ValueError(f"lane {lane!r}: {sorted(asked)} not within a lane's kinds")
            frozen[lane] = asked
        self._lanes: Mapping[str, frozenset[str]] = MappingProxyType(frozen)

    def requester(self, lane: str, tenant_id: uuid.UUID) -> LaneRequester:
        if lane not in self._lanes:
            raise KeyError(f"lane {lane!r} is not registered to request runs")
        return LaneRequester(lane, tenant_id)

    def may_request(self, requester: LaneRequester, trigger_kind: str) -> bool:
        return trigger_kind in self._lanes.get(requester.lane, frozenset())


# ---- the request and its answer ---------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRequest:
    """What a caller may say. No workspace, kind, artifact or hash: the door
    reads those (R3.18)."""

    requester: Requester
    version_id: uuid.UUID
    trigger_kind: str
    # The route's `Idempotency-Key` (already bound to its caller,
    # app-standards/02) or the key the lane names (the inbound event with its
    # subscription, the gate run with its case).
    source_key: str
    input: Mapping[str, Any] = field(default_factory=dict)
    # A person may name only themself; a lane names the subscription's
    # principal (`datahub`) or the candidate's submitter (`eval`).
    run_as_principal_id: uuid.UUID | None = None
    # The inbound event a `datahub` run is asked for.
    inbound_event_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RunRequestResult:
    run_id: uuid.UUID
    created: bool


# ---- what the door asks of storage ------------------------------------------


@dataclass(frozen=True, slots=True)
class QueuedRun:
    """The row the door writes, every NOT NULL column of the base named."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    worker_id: str
    worker_version: str
    graph_version: str
    requested_by: uuid.UUID
    run_as_principal_id: uuid.UUID
    run_mode: RunMode
    run_manifest_hash: str
    definition_hash: str | None
    artifact_kind: str
    artifact_id: uuid.UUID
    artifact_version_id: uuid.UUID
    trigger_kind: str
    inbound_event_id: uuid.UUID | None
    request_key: str
    priority: int
    input: Mapping[str, Any]
    release_manifest_ref: str


@dataclass(frozen=True, slots=True)
class ExistingRun:
    """What R3.20 compares of the run already holding a request key."""

    id: uuid.UUID
    artifact_version_id: uuid.UUID | None
    run_mode: str
    run_as_principal_id: uuid.UUID | None
    input: Any


class RunIntakeTx(RunManifestTx, Protocol):
    """The caller's transaction: the manifest's reads and writes, and the run
    row's."""

    async def run_by_request_key(self, request_key: str) -> ExistingRun | None: ...

    async def tenant_plan(self) -> str | None:
        """The plan of the transaction's tenant (`platform.entitlements`, read
        under RLS now), or None when it has none: the plan the run's model
        profiles are pinned under (model-connections R1.4, R1.6), for a
        person's run and a lane's alike, never from the request."""
        ...

    async def insert_queued_run(self, run: QueuedRun) -> bool:
        """`INSERT ... ON CONFLICT (tenant_id, request_key) DO NOTHING`; False
        when another run already holds the key."""
        ...


class RunIntakeStore(Protocol):
    """One transaction under the requester's tenant: a person's from their
    verified context, a lane's from the tenant its registry issued it for."""

    def for_person(self, context: AccessContext) -> AbstractAsyncContextManager[RunIntakeTx]: ...

    def for_lane(self, lane: LaneRequester) -> AbstractAsyncContextManager[RunIntakeTx]: ...


# ---- refusals ---------------------------------------------------------------


def _run_as_mismatch(message: str) -> PermissionDeniedError:
    return PermissionDeniedError(message, details={"reason_code": "run_as_mismatch"})


@dataclass(frozen=True, slots=True)
class _Parties:
    tenant_id: uuid.UUID
    requested_by: uuid.UUID
    run_as: uuid.UUID
    lane: str | None
    lane_acts_as_itself: bool


# ---- the door -----------------------------------------------------------------


class RunRequestService:
    def __init__(
        self,
        store: RunIntakeStore,
        registry: ArtifactKindRegistry,
        manifests: RunManifestBuilder,
        run_keys: Mapping[tuple[str, str], str],
        lanes: RunLaneRegistry,
        clock: UtcClock,
        ids: IdGenerator,
        *,
        bindings: BindingPins,
    ) -> None:
        self.store = store
        self.bindings = bindings
        self.registry = registry
        self.manifests = manifests
        # (artifact_kind, trigger_kind) -> the key a person must hold to ask.
        self.run_keys: Mapping[tuple[str, str], str] = MappingProxyType(dict(run_keys))
        self.lanes = lanes
        self.clock = clock
        self.ids = ids

    async def request(self, request: RunRequest) -> RunRequestResult:
        """One `queued` run, or the one this request key already made."""
        # (a) R3.22: before any read.
        rule = _TRIGGERS.get(request.trigger_kind)
        if rule is None:
            raise DomainError(
                "this trigger kind cannot start a run",
                details={"reason_code": "trigger_kind_unsupported"},
            )
        if request.inbound_event_id is not None and request.trigger_kind != "datahub":
            raise DomainError(
                "only a data-hub run is asked for an inbound event",
                details={"reason_code": "inbound_event_unexpected"},
            )
        parties = self._parties(request, rule)  # (c) R3.19
        requester = request.requester
        opened = (
            self.store.for_person(requester.context)
            if isinstance(requester, PersonRequester)
            else self.store.for_lane(requester)
        )
        async with opened as tx:
            return await self._request(tx, request, rule, parties)

    def _parties(self, request: RunRequest, rule: _TriggerRule) -> _Parties:
        requester = request.requester
        if isinstance(requester, PersonRequester):
            if rule.asked_by != "person":
                raise _run_as_mismatch("a person cannot ask for this kind of run")
            person = requester.context.principal_id
            run_as = request.run_as_principal_id or person
            if run_as != person:
                raise _run_as_mismatch("a person's run acts as that person")
            return _Parties(requester.context.tenant_id, person, person, None, False)
        if rule.asked_by != "lane" or not self.lanes.may_request(requester, request.trigger_kind):
            raise _run_as_mismatch("this lane cannot ask for this kind of run")
        if request.run_as_principal_id is None:
            raise _run_as_mismatch("a lane's run names the principal it acts as")
        run_as = request.run_as_principal_id
        requested_by = system_actor(requester.lane).value if rule.lane_acts_as_itself else run_as
        return _Parties(
            requester.tenant_id, requested_by, run_as, requester.lane, rule.lane_acts_as_itself
        )

    async def _request(
        self, tx: RunIntakeTx, request: RunRequest, rule: _TriggerRule, parties: _Parties
    ) -> RunRequestResult:
        # (b) R3.18: under RLS, the artifact row FOR SHARE; another tenant's
        # version is no version.
        root = await tx.root_version(request.version_id)
        entry = None if root is None else self.registry.get(root.kind)
        if root is None or entry is None:
            raise NotFoundError("version not found")
        workspace_id = root.owning_workspace_id
        # (d) R3.17
        if rule.asked_by == "person":
            await self._may_run(tx, root, request.trigger_kind, workspace_id)
        # (e) R3.10: a sealed version runs `live` only while it is `live`. A
        # draft asked for `live` is the manifest's refusal (tenant-config R6.7).
        version = root.version
        if rule.run_mode == "live" and version.stage not in (Stage.LIVE, Stage.DRAFT):
            raise ConflictError(
                "only the live version runs live",
                details={"reason_code": "version_not_live", "stage": version.stage.value},
            )
        request_key = f"{request.trigger_kind}:{parties.requested_by}:{request.source_key}"
        input_payload = dict(request.input)
        existing = await tx.run_by_request_key(request_key)
        if existing is not None:
            return _same_request(existing, request, rule, parties, input_payload)
        draft = version.stage is Stage.DRAFT
        if draft and rule.run_mode == "simulate":
            # R3.11: the kind's whole check, once, on the content read under
            # the lock, the way a submit runs it.
            problems = document_problems(entry, version.document)
            if problems:
                raise DocumentInvalidError("the draft is not valid", problems)

        async def pin(decls: Sequence[BindingDecl]) -> PinnedBindings | None:
            return await self.bindings.pin(
                tx,
                decls,
                version.artifact_id,
                simulate=rule.run_mode == "simulate",
                tenant_id=parties.tenant_id,
                workspace_id=workspace_id,
                principal_id=parties.run_as,
            )

        # The plan the run's model profiles are pinned under (model-connections
        # R1.4, R1.6): the tenant's own, read in this transaction.
        manifest_hash = await self.manifests.build(
            tx,
            version.id,
            rule.run_mode,
            tenant_id=parties.tenant_id,
            plan_id=await tx.tenant_plan(),
            pin=pin,
        )
        run = QueuedRun(
            id=self.ids.new_uuid(),
            workspace_id=workspace_id,
            worker_id=f"studio:{root.kind}:{version.artifact_id}",
            worker_version="draft" if draft else str(version.version_no),
            # A draft has no definition hash; its manifest names its content.
            graph_version=manifest_hash if draft else (version.definition_hash or ""),
            requested_by=parties.requested_by,
            run_as_principal_id=parties.run_as,
            run_mode=rule.run_mode,
            run_manifest_hash=manifest_hash,
            definition_hash=None if draft else version.definition_hash,
            artifact_kind=root.kind,
            artifact_id=version.artifact_id,
            artifact_version_id=version.id,
            trigger_kind=request.trigger_kind,
            inbound_event_id=request.inbound_event_id,
            request_key=request_key,
            priority=rule.priority,
            input=input_payload,
            release_manifest_ref=self.manifests.release_manifest_ref,
        )
        if not await tx.insert_queued_run(run):
            # R3.6: a concurrent request with this key committed first.
            raced = await tx.run_by_request_key(request_key)
            if raced is None:  # pragma: no cover - the key's holder was just seen
                raise ConflictError(
                    "the request key is held by a run this transaction cannot read",
                    details={"reason_code": "request_key_reused"},
                )
            return _same_request(raced, request, rule, parties, input_payload)
        await tx.audit(self._started(run, parties))  # R3.21
        return RunRequestResult(run.id, created=True)

    async def _may_run(
        self, tx: RunIntakeTx, root: RootVersion, trigger_kind: str, workspace_id: uuid.UUID
    ) -> None:
        key = self.run_keys.get((root.kind, trigger_kind))
        if key is None or workspace_id not in await tx.reach(key):
            raise PermissionDeniedError(
                "you may not run this here",
                details={"reason_code": "permission_denied", "action": key},
            )

    def _started(self, run: QueuedRun, parties: _Parties) -> AuditEvent:
        details: dict[str, object] = {
            "run_mode": run.run_mode,
            "trigger_kind": run.trigger_kind,
            "artifact_kind": run.artifact_kind,
            "artifact_version_id": str(run.artifact_version_id),
            "run_manifest_hash": run.run_manifest_hash,
        }
        if parties.lane is not None and parties.lane_acts_as_itself:
            return lane_audit_event(
                lane=parties.lane,
                event_id=self.ids.new_uuid(),
                tenant_id=TenantId(parties.tenant_id),
                workspace_id=WorkspaceId(run.workspace_id),
                action=STARTED,
                resource_type=RESOURCE,
                resource_id=str(run.id),
                occurred_at=self.clock.now(),
                details=details,
                run_id=run.id,
            )
        if parties.lane is not None:
            # The lane carries out this person's decision, and says so.
            details["lane"] = parties.lane
        return AuditEvent(
            id=self.ids.new_uuid(),
            tenant_id=TenantId(parties.tenant_id),
            workspace_id=WorkspaceId(run.workspace_id),
            actor_id=UserId(parties.requested_by),
            action=STARTED,
            resource_type=RESOURCE,
            resource_id=str(run.id),
            occurred_at=self.clock.now(),
            run_id=run.id,
            details=details,
        )


def _same_request(
    existing: ExistingRun,
    request: RunRequest,
    rule: _TriggerRule,
    parties: _Parties,
    input_payload: Mapping[str, Any],
) -> RunRequestResult:
    """R3.20: the run already under this key, if it is this request's."""
    if (
        existing.artifact_version_id != request.version_id
        or existing.run_mode != rule.run_mode
        or existing.run_as_principal_id != parties.run_as
        or existing.input != input_payload
    ):
        raise ConflictError(
            "this request key already started a different run",
            details={"reason_code": "request_key_reused"},
        )
    return RunRequestResult(existing.id, created=False)
