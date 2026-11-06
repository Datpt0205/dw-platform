"""Runtime ports: workflow runner and model gateway.

LangGraph and provider SDK adapters implement these in phase 2; workflow nodes
and application handlers depend only on the protocols.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.run_control import HaltReason, RunControlDoor
from dw_kernel.errors import DomainError
from dw_kernel.residency import RouteClass
from dw_platform.domain.audit import AuditEvent

OutputT = TypeVar("OutputT", bound=BaseModel)

RouteKind = Literal["auto", "structured_extraction", "reasoning", "deep_reasoning"]


class ModelRequest(BaseModel):
    """Provider-neutral request for a structured model call."""

    model_config = ConfigDict(frozen=True)

    task: str
    prompt_id: str
    prompt_version: str
    variables: dict[str, str] = {}
    # None runs on the deployment's own profile (the gateway's
    # `default_profile`). Name one only for a call that must differ from it.
    model_profile: str | None = None
    max_output_tokens: int | None = None
    # "auto" preserves legacy routing (task=="reasoning" -> reasoning route).
    route_kind: RouteKind = "auto"
    # The JSON Schema the provider is asked to answer in, when the caller's
    # contract is data rather than a Pydantic type (a workflow step's
    # `output_schema`). None asks in the output type's own schema. A real
    # provider answers in exactly the schema it is sent: an open `{}` type sent
    # strict is a closed object with no properties, so every answer came back
    # `{}` until a live call showed it (leadcare R1.5, 2/11/2026).
    output_schema: dict[str, object] | None = None


class ModelOutputInvalidError(DomainError):
    """Every attempt's output failed the requested schema.

    A subclass, not a bare `DomainError`, so a caller that has to degrade to
    "I did not understand" can catch exactly this — never a
    budget refusal or a prompt/variable mismatch, which are other
    `DomainError`s and must not be dressed up as a misunderstanding.
    """


class ModelGateway(Protocol):
    """Single entry point for LLM calls; output is always schema-validated.
    When no attempt produces valid output, raises `ModelOutputInvalidError`."""

    async def generate_structured(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> OutputT: ...


class TracedModelGateway(ModelGateway, Protocol):
    """Gateway that can also surface the model's visible reasoning text.

    ``generate_structured_traced`` returns ``(output, reasoning)`` where
    reasoning is "" when the routed model does not emit reasoning_content.
    """

    async def generate_structured_traced(
        self,
        request: ModelRequest,
        output_type: type[OutputT],
        *,
        run_context: RunContext,
    ) -> tuple[OutputT, str]: ...


@dataclass(frozen=True, slots=True)
class CallEstimate:
    """What one model call may cost, asked before it is sent (usage-and-limits
    R5.2, R5.10): the input it sends, counted and priced by the book, and the
    book's price of one output token. A price the book does not hold is `None`:
    the call is then bounded by tokens alone, and its settlement, `unpriced`,
    stops the run at its next call (R2.5)."""

    provider: str
    model: str
    input_tokens: int
    input_cost_usd: Decimal | None
    output_usd_per_token: Decimal | None
    # The book the estimate was priced by, which the reaper's estimate of an
    # unsettled call names (R5.4).
    price_book_version: str
    # What the caller asked for; None asks for as much as the lease allows.
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class CallPermit:
    """A call the lease let through: at most `max_output_tokens` of output, and
    the usage record's key, set before the call (ADR-0121 decision 1), so the
    settlement after it and the reaper's estimate are one record. `purpose` is
    the lease's, which the usage record names (a builder's assistance is not
    a run)."""

    lease_id: UUID
    call_id: UUID
    occurred_at: datetime
    max_output_tokens: int
    purpose: str = "run"


@dataclass(frozen=True, slots=True)
class RunLimits:
    """The behavioural limits of one run (usage-and-limits R6.4; ADR-0121
    decision 4): what its version declares, clamped by the plan's ceilings,
    computed at each `admit` and `resume` from the version the run pinned and
    the plan as it stands then, so a plan lowered while a run waits binds
    its resume. A workflow run counts its steps against `max_steps`
    (workflow-engine R4.20, which takes it by injection), an agent loop its
    calls against `max_model_calls` and `max_tool_calls` (usage-and-limits/06);
    the lease is capped by `max_cost_usd` and `max_tokens`."""

    max_steps: int
    max_model_calls: int
    max_tool_calls: int
    max_cost_usd: Decimal
    max_tokens: int


class RunLease(Protocol):
    """The open lease a run's tree spends against (usage-and-limits R5.1-R5.10;
    ADR-0121 decision 5). Every method is a transaction of its own on the
    lease row; none trusts state held in this process.

    The settlement of a permitted call (`after_call` of the spec) is the usage
    record the call's door writes with the permit on it: `dw_usage` writes the
    record and moves the lease in one transaction, and a record whose key the
    reaper already wrote is not counted twice (R5.11)."""

    @property
    def root_run_id(self) -> UUID: ...

    @property
    def run_limits(self) -> RunLimits | None:
        """What the `admit` or `resume` that returned this lease computed for
        the run (R6.4); `None` on a door's handle (`LimitsPort.lease`), an
        operation's lease and a gate's."""
        ...

    async def before_call(self, run_context: RunContext, estimate: CallEstimate) -> CallPermit:
        """A permit for one call, topped up from the counters when the lease
        has too little left; `LimitExceededError` when even the call's input
        does not fit (R5.10), when the lease is closed (`lease_expired`), or
        when the run's own `cost_ceiling_usd` is spent."""
        ...

    async def abandon(self, permit: CallPermit) -> None:
        """Give back a permit whose call never answered (the provider failed or
        refused before it did): its hold leaves the lease unspent. A call that
        answered is settled by its usage record instead, never abandoned."""
        ...

    async def beat(self) -> bool:
        """The heartbeat (R5.9): `expires_at` 300 s on, and what was settled
        since the last beat rolled into the counters, under the lease row's
        lock. False when the lease is no longer open."""
        ...

    async def release(self, reason: str) -> bool:
        """Close the lease and give back what it holds unspent; False when it
        was already closed. `paused` only when no run of the tree still runs:
        the runner asks that before it calls."""
        ...


class LimitsPort(Protocol):
    """Every hard limit on the scope chain, answered where a run begins
    (usage-and-limits R4, R5; ADR-0121 decisions 4-6; ADR-0113 decision 3).

    Declared here and satisfied by `dw_usage`, so neither package reads the
    other's tables (`CLAUDE.md`, Agent and tool rules). The runner is its one
    caller of `admit` and `resume`. A refusal is `LimitExceededError`
    (`limit_exceeded` with the metric, scope, window, limit, used and
    `resets_at`), and nothing was reserved; limits that cannot be read are
    `LimitsUnavailableError`, never an admission."""

    async def admit(self, run_context: RunContext, *, counts_run: bool = True) -> RunLease:
        """Open the tree's lease, or attach to the one already open; `runs`
        counts once per root, at the first lease, and only for a `live` run
        that `counts_run` (a call outside any run does not)."""
        ...

    async def resume(self, run_context: RunContext) -> RunLease:
        """Take a lease again for a run going on after a wait (R5.3): attach to
        the open one, or open a new one; `runs` is never counted again."""
        ...

    async def admit_gate(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        gate_run_id: UUID,
        ceiling_usd: Decimal,
        payer: Literal["tenant", "platform"],
    ) -> RunLease:
        """The `eval_offline` lease of a gate run (agent-lifecycle R4.4): no
        `runs`; `ceiling_usd` in place of the plan's per-run ceiling; a
        platform-paid gate touches no counter of the tenant (DO-29.2 (a))."""
        ...

    async def admit_operation(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        purpose: OperationPurpose,
        operation_id: UUID,
    ) -> RunLease:
        """The lease of a model call that belongs to no run (usage-and-limits
        R6.2; gate 4/11/2026 (a)): an ingestion, a retrieval, a builder's
        assistance. It counts against the money and token limits of the scope
        chain and never against `runs`, and only the period limits bound it,
        never a run's ceiling. Refused, `LimitExceededError` with `resets_at`.
        Its holder beats it while the operation lasts and releases it after."""
        ...

    def lease(self, run_context: RunContext) -> RunLease:
        """The lease of `run_context.lease_root`, for a model door: no admission,
        and a call finds it open or is refused."""
        ...


# The purposes of an operation's lease (`platform.budget_leases.purpose`).
OperationPurpose = Literal["ingestion", "retrieval", "builder_assist"]


class MeteredModelGateway(TracedModelGateway, Protocol):
    """The structured model door a bounded context is handed
    (`RuntimeSeam.gateway`; usage-and-limits R6.1; ADR-0121 decision 7): every
    attempt asks the run's lease for a permit before it is sent, refused when
    the lease is spent or closed, and its usage is recorded keyed by that
    permit. `limits` is the port it asks. Only a composition root names the
    implementation, `dw_agent_runtime.model.routing.RoutingModelGateway`."""

    @property
    def limits(self) -> LimitsPort: ...


class RunControlPort(Protocol):
    """What every door of the runtime asks before it acts (agent-lifecycle R7,
    R9; ADR-0120 decision 6, amended 2026-11-04): a freeze, a kill, an
    unreadable switch state, an inactive principal or company. Declared here,
    satisfied by `SqlRunControl`, given to each door by injection, never a
    default."""

    async def require_open(
        self,
        run_context: RunContext,
        *,
        door: RunControlDoor,
        artifacts: Sequence[UUID] = (),
    ) -> None:
        """Return when the run may go through `door`; else raise
        `RunHaltedError` with the reason. A kill of the run's own component
        (`run_context.artifact_id`) refuses it, and of any of `artifacts`, the
        further components the call reaches (a linked agent, R8.5), asked
        after it; a `simulate` run is refused by no kill (ADR-0120 decision 7).
        At `admission`, `start` and `resume` the run's principal and company
        are read too."""
        ...

    async def admission_state(
        self, tenant_id: UUID, artifacts: Sequence[UUID] = ()
    ) -> HaltReason | None:
        """For a trigger's event that has no run yet (the `studio_inbound`
        lane): the reason it may not be admitted now, or None. No principal is
        asked: an event has none until its run is requested."""
        ...


class RunCancelUnit(Protocol):
    """The transaction a `control_switch` lane cancels one run in, as a
    `RunCancelHook` writes through it (agent-lifecycle R8.10; workflow-engine
    ticket 08, MEDIUM (a)): under the run's tenant, committed with the cancel
    or rolled back with it, so a hook opens no connection of its own and what
    it writes cannot outlive a cancel that did not happen. Narrow on purpose:
    what a hook writes is an audit row; a hook that reads adds the read here,
    with the lane's unit its one implementation."""

    async def audit(self, event: AuditEvent) -> None: ...


class RunCancelHook(Protocol):
    """Called for each run the `control_switch` lane cancels, in the cancel's
    transaction and before the run is set `cancelled` (agent-lifecycle R8.10;
    H-22): `actor` is the person who set the kill and `lane` the lane carrying
    it out (ADR-0011). Registered by name at the worker's composition root,
    none by default; workflow-engine/08 registers `record_unresolved_effects`
    (workflow-engine R6.38). Raising rolls that run's cancel back, and the
    outbox delivers the change again: no run is cancelled past a hook."""

    async def on_cancel(
        self, unit: RunCancelUnit, run_id: UUID, *, actor: UUID, lane: str
    ) -> None: ...


class StreamingWorkflowRunnerPort(Protocol):
    """Runs a workflow while emitting its progress, for chat-style channels."""

    async def stream(
        self,
        *,
        run_context: RunContext,
        input_payload: dict[str, object],
    ) -> AsyncIterator[dict[str, object]]:
        """Claim the thread and start the run; the iterator observes it.

        Awaited rather than iterated, so a thread already carrying an unfinished
        run is refused with `ConflictError` before the caller has committed to a
        response. One thread is one checkpoint: a second run on it would invoke
        the same thread with new input and overwrite whatever the first was
        waiting on.
        """
        ...


class WorkflowRunnerPort(Protocol):
    """Starts and resumes durable, checkpointed workflow runs."""

    def hosts(self, *, worker_id: str, worker_version: str, graph_version: str) -> bool:
        """Whether this process can resume that exact run.

        Keyed on the versions recorded when the run started, not on whatever the
        worker config names today: resuming replays the graph the run began on
        and the worker settings it began under. Both have to still be registered
        here, and callers must ask this before spending an approval decision --
        asking about only one of them let a deploy strand a run for ever.
        """
        ...

    async def start(
        self,
        *,
        run_context: RunContext,
        input_payload: dict[str, object],
    ) -> UUID: ...

    async def resume(
        self,
        *,
        run_context: RunContext,
        run_id: UUID,
        resume_payload: dict[str, object],
    ) -> None: ...


class RunGraphsPort(Protocol):
    """What makes a run's graph resolvable here before the runner or the
    approval flow asks `hosts`: a tenant's published workflow is registered on
    first use (wf-ai R6.5, `dw_agent_runtime.wflite.versions`). Leaves any
    other version as it is."""

    async def ensure(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        worker_id: str,
        worker_version: str,
    ) -> None: ...


class RunWaitsPort(Protocol):
    """Where a Digital Worker's run tells its work item what it is doing
    (wf-lite R6.3, R6.5, R6.7): waiting for a person or a timer, running again,
    finished. Called by the runner only for a run that acts as a principal;
    satisfied by the platform's work queue, which ignores a run that holds no
    item."""

    async def waiting(
        self,
        run_context: RunContext,
        run_id: UUID,
        *,
        kind: Literal["approval", "timer"],
        wake_at: datetime | None = None,
    ) -> None: ...

    async def resumed(self, run_context: RunContext, run_id: UUID) -> None: ...

    async def finished(self, run_context: RunContext, run_id: UUID, *, failed: bool) -> None: ...


# ---- what a Studio run pinned (tenant-config R6; ADR-0109 decisions 6-7) ----


@dataclass(frozen=True, slots=True)
class PinnedVersion:
    """One version row a run manifest's keys hold, read as it is now.

    A version outside `draft` never changes (tenant-config R2.9), so
    `current_hash` is None for it. One in `draft` (a draft root, or a candidate
    sent back after the run pinned it) can be edited, so the store hashes its
    content again the way it was pinned: `current_hash` is that hash.
    """

    id: UUID
    artifact_id: UUID
    version_no: int | None
    stage: str
    content_hash: str | None
    definition_hash: str | None
    document_schema: str
    document: Any
    current_hash: str | None


@dataclass(frozen=True, slots=True)
class PinnedEntry:
    """One pinned thing, as the manifest names it: `kind`, `key`, the version
    and the hash it pinned, and for an `artifact` (and the root) its row."""

    kind: str
    key: str
    version: int | None
    content_hash: str | None
    artifact: PinnedVersion | None = None


@dataclass(frozen=True, slots=True)
class PinnedManifest:
    """A run manifest and the rows its keys hold. `root.content_hash` is the
    root's pinned `definition_hash`; `unread_keys` names each key row whose
    version could not be read under the transaction's tenant."""

    hash: str
    body: Mapping[str, Any]
    root: PinnedEntry
    closure: tuple[PinnedEntry, ...]
    unread_keys: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundConnection:
    """The connection a run's manifest pinned under one binding name, with
    what `connection_usable` is asked with at the egress call: the run's
    workspace, the principal it acts for (`coalesce(run_as_principal_id,
    requested_by)` of its row) and when it was requested (tenant-config R7.5;
    ADR-0109 decision 6; V4.35). Never a secret or its version."""

    connection_id: UUID
    workspace_id: UUID
    principal_id: UUID
    run_requested_at: datetime


class RunBindingsPort(Protocol):
    """What a run's binding names resolve to, read from its own pinned
    manifest under the tenant's RLS, never from the Binding set in force
    (tenant-config ticket 05 step 9). Declared here beside `RunManifestPort`,
    satisfied by `dw_studio`; connections-and-vault/05's action handler is
    its reader."""

    async def connection(
        self, tenant_id: UUID, run_id: UUID, binding_name: str
    ) -> BoundConnection | None:
        """None for another tenant's run, a run without a manifest, or a name
        its manifest does not bind to a connection."""
        ...


class PlanModelProfilesPort(Protocol):
    """The platform model profiles a plan lists (`platform.plan_model_profiles`;
    model-connections R2.1, R2.2, R2.6). Declared here, satisfied by
    `dw_platform`, which this package never imports, and injected at the
    composition roots; scripts and tests inject one in memory."""

    async def allowed(self, plan_id: str) -> frozenset[str]:
        """Empty for a plan with no rows. A read that fails raises: it is
        never "every profile"."""
        ...


class PinnedEnginePort(Protocol):
    """The `engine` section a Studio run's manifest pinned, read when a model
    door of that run asks `ModelResolver` (model-connections R1.4, R1.5).
    Declared here, satisfied by `dw_studio` at the composition root; the body
    is content-addressed, so what it answers for a hash never changes."""

    async def engine(self, tenant_id: UUID, run_manifest_hash: str) -> Mapping[str, Any] | None:
        """None when this tenant has no manifest under that hash."""
        ...


class RunManifestPort(Protocol):
    """What a Studio run reads its manifest through when it runs and when it
    resumes, in any process (ADR-0109 decision 7, amended 2026-11-03).
    Declared here, satisfied by `dw_studio`, which this package never imports.
    Reads under the tenant of the transaction it is bound to (RLS)."""

    async def load(self, run_manifest_hash: str) -> PinnedManifest | None:
        """The manifest and its rows, or None when this tenant has no such hash."""
        ...


# ---- a Studio run's steps (workflow-engine/03) ---------------------------------

# A step's place in the tree: each enclosing step's id with the port of the lane
# the walk came through, outermost first; empty on the root chain (R4.21).
LanePath = tuple[tuple[str, str], ...]
StepStatus = Literal["succeeded", "failed", "outcome_unknown"]
StepSource = Literal["door", "pinned"]


@dataclass(frozen=True, slots=True)
class StepRun:
    """One attempt of one step, as the node wrapper records it when it ends
    (workflow-engine R4.9, R4.21, R4.26, R4.28, R6.28).

    `attempt` counts from 1. `iteration_path` is the one in the attempt's
    idempotency key, "" outside a loop's body. `port` is the lane the step
    took (a switch's case, an approval's decision, `error`), None when it took
    none. `error_type` is `error_type_label(code)`, never a provider's text.
    `simulated` and `source` tell a pinned result from a door's simulation.
    `field_ids` maps a value's path in `inputs`/`output` to the field it is a
    value of, for each one the wrapper knows; a value without one is masked
    when read back (telemetry-and-audit R3.12)."""

    tenant_id: UUID
    run_id: UUID
    node_id: str
    lane_path: LanePath
    iteration_path: str
    attempt: int
    started_at: datetime
    status: StepStatus
    port: str | None
    error_type: str | None
    simulated: bool
    source: StepSource
    inputs: Mapping[str, Any]
    output: Mapping[str, Any]
    field_ids: Mapping[str, str]


class StepRecorderPort(Protocol):
    """Where a Studio run's step attempts are recorded (workflow-engine R4.9,
    R4.21, R4.26; telemetry-and-audit R3.1, R3.12). Declared here by its first
    consumer, the node wrapper; telemetry-and-audit/03 satisfies it over
    `platform.run_steps` and runs `dw_agent_runtime.testing.
    step_recorder_contract` against it.

    Every method refuses an `attempt` below 1 and a `lane_path` or
    `iteration_path` that is not given (`ValueError`), before it writes."""

    async def attempts(
        self, *, tenant_id: UUID, run_id: UUID, node_id: str, iteration_path: str
    ) -> int:
        """How many attempts of the step are recorded already, so a run taken
        again after a crash goes on counting instead of starting from 1."""
        ...

    async def step_started(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        node_id: str,
        lane_path: LanePath,
        iteration_path: str,
        attempt: int,
    ) -> datetime:
        """Record the attempt's start before its effect, once per `(run_id,
        node_id, iteration_path, attempt)`; return the `started_at` of the
        first call, so the same attempt run again after a crash gets the same
        time without a checkpoint of its own."""
        ...

    async def step_finished(self, step: StepRun) -> None: ...


@dataclass(frozen=True, slots=True)
class StudioRun:
    """A Studio run as its row, its manifest and its pinned document say,
    read under the run's tenant when it is taken (workflow-engine/03 step 2).
    Nothing here comes from the caller."""

    run_id: UUID
    thread_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    artifact_kind: str
    artifact_id: UUID
    artifact_version_id: UUID
    # The root's pinned hash: the sealed `definition_hash`, or a draft's
    # provisional one from its manifest; with `COMPILER_VERSION`, what the
    # graph is cached under (R4.2).
    pinned_hash: str
    run_mode: Literal["live", "test", "simulate"]
    requested_by: UUID
    run_as_principal_id: UUID
    run_manifest_hash: str
    plan_id: str
    deadline_at: datetime | None
    input: Mapping[str, Any]
    pinned_results: Mapping[str, Any] | None
    document: Mapping[str, Any]
    # The manifest's `engine` section (ADR-0109 decision 8): `durability`.
    engine: Mapping[str, Any]
    version_no: int | None
    trace_id: str
    # The data route class `RunRequestService` pinned on the row at admission
    # (compliance-pdpl R2.1); a row admitted before it existed reads `vn_only`.
    data_route_class: RouteClass = "vn_only"
    # What asked for the run, which shapes a refusal at dispatch (workflow-
    # engine R5.9-R5.19). Empty matches no row of the table, so a run read
    # without it is held, never let through (R5.25).
    trigger_kind: str = ""
    # The root of the run's tree, whose lease a child spends (usage-and-limits
    # R5.6); None for a root.
    root_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StudioRunBlocked:
    """A run the take refused to start and left `blocked` with its reason
    (`incompatible_resume`: a draft whose content changed since the run pinned
    it, R6.14)."""

    run_id: UUID
    reason_code: str


class StudioLeaseLostError(Exception):
    """The run's claim is no longer this worker's: another took it after the
    lease lapsed (workflow-engine R5.5). Nothing was written; the worker stops
    running the run and leaves its row, its money lease and its waits to the
    holder of the new claim."""

    def __init__(self, run_id: UUID) -> None:
        super().__init__(f"the claim on run {run_id} is held by another worker")
        self.run_id = run_id


class StudioRunStorePort(Protocol):
    """A Studio run's row as the runner moves it (workflow-engine/03, 04).
    Declared here, satisfied by `dw_studio`, which reads the manifest and the
    version rows; every call runs in a transaction of its own under
    `tenant_id`'s RLS, and every write names the claim's `lease_token`
    (`WHERE lease_owner = :token`, R5.5): a worker whose claim was taken over
    writes nothing and gets `StudioLeaseLostError`."""

    async def take(
        self, tenant_id: UUID, run_id: UUID, *, lease_token: str
    ) -> StudioRun | StudioRunBlocked:
        """The run the `studio_runs` lane claimed (`running` under
        `lease_token`), with its manifest loaded and its pinned versions
        checked (`PinnedResolver.load`), its root artifact read `FOR SHARE` so
        a concurrent `save_draft` waits; a pinned version that changed leaves
        the run `blocked` (`incompatible_resume`) instead."""
        ...

    async def admitted(
        self, tenant_id: UUID, run_id: UUID, *, lease_token: str, deadline: timedelta
    ) -> datetime:
        """The run passed dispatch: its `deadline_at` set to now plus
        `deadline` when it has none (the first take, R5.22), never moved
        after; the deadline in force."""
        ...

    async def hold(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        lease_token: str,
        delay: timedelta,
        until: datetime | None = None,
    ) -> None:
        """Back to `queued` with no claim, `attempt` unchanged, due at `until`
        when given (a limit's `resets_at`), else now plus `delay`."""
        ...

    async def finish(
        self,
        tenant_id: UUID,
        run_id: UUID,
        status: Literal["completed", "failed", "cancelled"],
        *,
        lease_token: str,
        error: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        outcomes: Sequence[str] = (),
    ) -> None:
        """End the claimed run with the `outcomes[]` it reached (R5.24), in
        one transaction."""
        ...

    async def cancel_past_deadline(
        self, tenant_id: UUID, run_id: UUID, *, lease_token: str
    ) -> bool:
        """End the claimed run `cancelled` with `error.code`
        `deadline_exceeded` and audit `run.deadline_exceeded` as
        `system:studio_runs`, in one transaction (R4.11). False when the run
        was no longer running."""
        ...


@dataclass(frozen=True, slots=True)
class StudioClaim:
    """One run the `studio_runs` lane took, and the token its writes name."""

    tenant_id: UUID
    run_id: UUID
    lease_token: str


@dataclass(frozen=True, slots=True)
class ReapedRuns:
    """What one pass of `studio_run_reaper` did in one tenant."""

    requeued: int = 0
    dead_lettered: int = 0
    cancelled: int = 0


class StudioRunQueuePort(Protocol):
    """The queue the `studio_runs` and `studio_run_reaper` lanes work
    (workflow-engine R5.2-R5.7, R5.23; ADR-0113 decisions 2, 3). The three
    `*_due` reads cross tenants through SECURITY DEFINER functions and return
    tenant ids only; every other call runs under one tenant's RLS. Declared
    here, satisfied by `SqlStudioRunQueue`."""

    async def scopes_due(self, limit: int) -> list[UUID]:
        """Tenants with a due `queued` run, the longest waiting first."""
        ...

    async def claim(
        self, tenant_id: UUID, *, limit: int, worker: str, lease: timedelta
    ) -> list[StudioClaim]:
        """Up to `limit` of the tenant's due runs by `(priority, available_at,
        created_at, id)`, each moved to `running` under a new token
        `<worker>:<uuid>` until now plus `lease`, in one short transaction."""
        ...

    async def beat(self, claim: StudioClaim, *, lease: timedelta) -> bool:
        """`lease_until` moved on; False when the claim is no longer held."""
        ...

    async def release(self, claim: StudioClaim) -> bool:
        """An orderly shutdown's hand-back: `queued`, due now, no claim,
        `attempt` unchanged; False when the claim is no longer held."""
        ...

    async def orphans_due(self, limit: int) -> list[UUID]: ...

    async def requeue_orphans(
        self, tenant_id: UUID, *, max_requeues: int, backoff: Callable[[int], timedelta]
    ) -> ReapedRuns:
        """Each `running` run whose claim lapsed: `queued` with `attempt + 1`
        and `available_at` after `backoff(attempt)`, or, once it was requeued
        `max_requeues` times, `dead_lettered` with its audit and outbox event
        in the same transaction (R5.6, R5.7)."""
        ...

    async def deadlines_due(self, limit: int, *, unclaimed_after: timedelta) -> list[UUID]: ...

    async def cancel_overdue(self, tenant_id: UUID, *, unclaimed_after: timedelta) -> ReapedRuns:
        """Each unfinished run past `deadline_at` that no live claim holds,
        and each never admitted `queued` run older than `unclaimed_after`,
        `cancelled` `deadline_exceeded` with its audit (R5.23)."""
        ...


@dataclass(frozen=True, slots=True)
class BindingHold:
    """`binding_needs_review`: the run-as service principal's grants grew at
    `grants_changed_at`, after the binding set naming it was approved
    (workflow-triggers R3.7)."""

    grants_changed_at: datetime


class BindingReviewPort(Protocol):
    """Asked at dispatch for a run a trigger requested (workflow-engine R5.19):
    whether its binding must be approved again first. Declared here, where it
    is asked; workflow-triggers/03 satisfies it. None lets the run on."""

    async def review(self, run: StudioRun) -> BindingHold | None: ...


class HeldRunAlertPort(Protocol):
    """Who is told that a trigger's runs are held (workflow-engine R5.20,
    R5.21), through the platform's notification door. The adapter builds the
    `source_key` from what it reads (a member's `status_changed_at`, the
    hold's `grants_changed_at`), so a hold of many runs over many cycles tells
    each person once per change, and the lane keeps no state of its own."""

    async def principal_inactive(
        self, tenant_id: UUID, *, workspace_id: UUID, principal_id: UUID
    ) -> None: ...

    async def binding_needs_review(
        self,
        tenant_id: UUID,
        *,
        workspace_id: UUID,
        artifact_id: UUID,
        principal_id: UUID,
        grants_changed_at: datetime,
    ) -> None: ...


def check_step_run(attempt: int, lane_path: object, iteration_path: object) -> None:
    """What every `StepRecorderPort` refuses before it writes (R4.21, R4.26)."""
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError(f"an attempt counts from 1, not {attempt!r}")
    if not isinstance(lane_path, tuple) or not all(
        isinstance(pair, tuple) and len(pair) == 2 for pair in lane_path
    ):
        raise ValueError("a step run names its lane path")
    if not isinstance(iteration_path, str):
        raise ValueError("a step run names its iteration path")
