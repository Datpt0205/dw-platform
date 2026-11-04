"""Tool executor: the enforcement pipeline for every tool call.

Its steps run in one order, tools-and-skills R2.6 (`TOOL_STEP_ORDER`): control
switch → resolve → validate input → Digital Worker boundary → decision call →
scopes → run mode → approval (with the idempotency key it requires) → Send
floor → claim → log `dispatched` → handler (timeout/retry) → validate output →
record and audit. The gate steps, resolve to the Send floor, are registered in
a `ToolSteps` by `adapters.wflite_host.build_tool_executor_steps`, the one
builder both roots reach through `build_tool_executor`, and `_execute` runs
only what it holds; the last five are the executor's own tail. A step not yet
built is named in `PENDING_STEPS` with the ticket that registers it (H-3);
the Send floor never is (`NEVER_PENDING`).

Each gate step takes the call's state (`ToolCall`) and either goes on (None),
ends the call with a result (a sample outside `live`, a replay), or refuses by
raising. Side effects require an idempotency key; replays return the stored
result without re-executing, and a send whose outcome is unknown is never made
again blindly (ADR-0108 decision 5).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid as uuid_module
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, Protocol

from pydantic import BaseModel, ValidationError

from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.dispatch import (
    DispatchRecord,
    NotDispatchedError,
    OutcomeUnknownError,
    RejectedError,
    ToolClaimPort,
)
from dw_agent_runtime.ports import RunControlPort
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.samples import SampleOutput, sample_of
from dw_agent_runtime.tools import RegisteredTool, SchemaViolation, ToolBehaviour, ToolRegistry
from dw_kernel.errors import (
    ApprovalRequiredError,
    ConfigError,
    ConflictError,
    DomainError,
    DWError,
    IdempotencyConflictError,
    InfrastructureError,
    PermissionDeniedError,
)
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_observability.metrics import DW_TOOL_CALL_TOTAL
from dw_observability.redaction import redact_mapping, redact_text
from dw_observability.semconv import OP_EXECUTE_TOOL, execute_tool_span_name
from dw_observability.telemetry import NullTelemetry, TelemetryPort
from dw_platform.application.decision_gate import ApprovedDecision
from dw_platform.application.digital_workers import DwBoundary
from dw_platform.application.marketing_send import Admission, SendRequest
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent

SleepFn = Callable[[float], Awaitable[None]]

logger = logging.getLogger("dw_agent_runtime.executor")

# Every call at these levels leaves the platform, so it logs its dispatch before
# it leaves (R6.11). A tenant's `connector_action` joins through its level.
_LEAVES_THE_PLATFORM = frozenset({"external", "critical"})

# A provider's code is its own text; it is kept short and scrubbed like any
# free text before it reaches the record.
_PROVIDER_CODE_LIMIT = 64

# Slack past the call's own budget before a claim may be taken over.
_CLAIM_GRACE_SECONDS = 30.0


def _lease_seconds(definition: ToolDefinition) -> float:
    """`timeout_seconds * (1 + max_retries) + 30 s`, ADR-0108 decision 5."""
    return definition.timeout_seconds * (1 + definition.max_retries) + _CLAIM_GRACE_SECONDS


def _error_text(error: Exception) -> str:
    """What the `error` column says about a failed call."""
    if isinstance(error, NotDispatchedError):
        return "not_dispatched"
    if isinstance(error, RejectedError):
        return f"rejected:{redact_text(error.provider_code)[:_PROVIDER_CODE_LIMIT]}"
    return type(error).__name__


class ExecutionStorePort(Protocol):
    """Idempotency + audit-trail persistence for tool executions."""

    async def find_succeeded(
        self, run_context: RunContext, tool_name: str, idempotency_key: str
    ) -> object | None: ...

    async def record(
        self,
        run_context: RunContext,
        *,
        execution_id: uuid_module.UUID,
        tool_name: str,
        tool_version: str,
        status: str,
        input_hash: str,
        output_hash: str | None,
        output: dict[str, object] | None,
        idempotency_key: str | None,
        error: str | None,
        attempts: int,
        started_at: datetime,
        finished_at: datetime,
        dispatch_id: uuid_module.UUID | None = None,
        audit: AuditEvent | None = None,
    ) -> object | None:
        """None once written; the earlier success when the key already had one.
        With `audit`, the event is written in the row's own transaction: both
        or neither (tenant-config R5.2)."""
        ...


class DigitalWorkerBoundaryPort(Protocol):
    """The boundary of a Digital Worker, by the principal its run acts as
    (digital-worker R6). Declared here, satisfied by the platform; None when
    the principal is no DW's in the run's workspace."""

    async def boundary(
        self,
        *,
        tenant_id: uuid_module.UUID,
        workspace_id: uuid_module.UUID,
        principal_id: uuid_module.UUID,
    ) -> DwBoundary | None: ...


@dataclass(frozen=True, slots=True)
class DecisionCall:
    """A tool call taken for a Digital Worker's decision (wf-lite R6.17): its
    decision class and, when a gate guards it, the gate step and the approval
    the gate opened."""

    decision_class: str
    gate_step_id: str | None = None
    approval_id: uuid_module.UUID | None = None


class SendAdmissionPort(Protocol):
    """The Send floor, declared here and satisfied by the platform's
    `MarketingSendPolicy` (ADR-0124 decision 2)."""

    async def admit(self, request: SendRequest) -> Admission: ...

    async def refuse(self, request: SendRequest, reason: str) -> Admission: ...

    async def sent(self, request: SendRequest, admission: Admission) -> None: ...


# The input field a sending tool takes its unsubscribe link in (R3.3).
UNSUBSCRIBE_FIELD = "unsubscribe_url"


def _addresses(payload: Mapping[str, object], fields: Sequence[str]) -> list[str]:
    """Every address the declared fields hold, a list field counting each."""
    found: list[str] = []
    for name in fields:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            found.append(value)
        elif isinstance(value, list | tuple):
            found.extend(str(v) for v in value if str(v).strip())
    return found


class DecisionAutonomyPort(Protocol):
    async def requires_person(
        self,
        *,
        tenant_id: uuid_module.UUID,
        workspace_id: uuid_module.UUID,
        dw_id: uuid_module.UUID,
        key: str,
    ) -> bool: ...


class ApprovedDecisionsPort(Protocol):
    async def approved(
        self,
        *,
        tenant_id: uuid_module.UUID,
        workspace_id: uuid_module.UUID,
        approval_id: uuid_module.UUID,
    ) -> ApprovedDecision | None: ...


def canonical_hash(payload: dict[str, object]) -> str:
    """Stable fingerprint of a payload; also used to derive idempotency keys."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


# --------------------------------------------------------------- the steps --

# tools-and-skills R2.6: the one order of a call's steps (H-3).
TOOL_STEP_ORDER: Final = (
    "control_switch",
    "resolve",
    "validate_input",
    "dw_boundary",
    "decision_call",
    "scopes",
    "run_mode",
    "approval",
    "send_floor",
    "claim",
    "dispatched",
    "handler",
    "validate_output",
    "audit",
)
# The executor's own tail: named in the order, run only by `_tail`.
TAIL_STEPS: Final = TOOL_STEP_ORDER[-5:]
GATE_STEPS: Final = TOOL_STEP_ORDER[: -len(TAIL_STEPS)]
# A step of R2.6 no ticket has built yet, and the ticket that registers it.
# Absent from the register, it decides nothing (spec, 25/10/2026). Empty since
# agent-lifecycle/01 registered the control switch.
PENDING_STEPS: Final[Mapping[str, str]] = MappingProxyType({})
# A gate step that may never wait. A pending step decides nothing, so the Send
# floor pending would let a message reach its handler unasked instead of being
# refused `blocked:send_floor_unavailable` (compliance-pdpl R3.12, CP25).
NEVER_PENDING: Final = frozenset({"send_floor"})

# The `policy_decision` of a call the control-switch step refuses (ADR-0120
# decision 6): a freeze and a kill by name, anything else the step cannot
# read (`control_state_unavailable`) as the state it could not read.
_HALT_DECISIONS: Final[Mapping[HaltReason, str]] = MappingProxyType(
    {
        HaltReason.PLATFORM_FROZEN: "deny_frozen",
        HaltReason.TENANT_FROZEN: "deny_frozen",
        HaltReason.ARTIFACT_KILLED: "deny_killed",
    }
)

# What needs an idempotency key: every call that leaves the platform, and every
# message, whatever its level, since the Send floor is asked under the key.
_KEYED_LEVELS = frozenset({"external", "critical"})


@dataclass
class ToolCall:
    """One call's state as its steps build it: the tool and its behaviour once
    resolved, the checked input and its hash, the DW boundary the decision
    step reads, `approved`, the Send floor's admission, and what runs once the
    handler succeeded (`after_success`: the floor's `sent`)."""

    name: str
    version: str
    raw_input: dict[str, object]
    run_context: RunContext
    idempotency_key: str | None
    approved: bool
    decision: DecisionCall | None
    # The tool a Studio run pinned (tools-and-skills R4.1): `resolve` takes it
    # as it is and never reads the registry for it.
    pinned: RegisteredTool | None = None
    tool: RegisteredTool | None = None
    input: BaseModel | None = None
    input_payload: dict[str, object] = field(default_factory=dict)
    input_hash: str = ""
    boundary: DwBoundary | None = None
    sending: tuple[SendRequest, Admission] | None = None
    after_success: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    # The `platform.tool_executions` row the call's answer was recorded under:
    # its success, its sample, or the earlier success a replay returns.
    execution_id: uuid_module.UUID | None = None

    @property
    def registered(self) -> RegisteredTool:
        if self.tool is None:
            raise ConfigError("a step read the tool before `resolve` ran")
        return self.tool

    @property
    def definition(self) -> ToolDefinition:
        return self.registered.definition

    @property
    def behaviour(self) -> ToolBehaviour:
        return self.registered.behaviour

    @property
    def checked_input(self) -> BaseModel:
        if self.input is None:
            raise ConfigError("a step read the input before `validate_input` ran")
        return self.input


ToolStep = Callable[["ToolExecutor", ToolCall], Awaitable[BaseModel | None]]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A call's answer and the execution row it was recorded under, which the
    model-facing view names in its artifact (ADR-0116 decision 5)."""

    output: BaseModel
    execution_id: uuid_module.UUID | None


class ToolSteps:
    """The ordered register of a `ToolExecutor`'s gate steps (R2.6, R2.7).

    Construction refuses a pending name outside R2.6's gate steps and the
    Send floor as pending (`NEVER_PENDING`); `register` refuses a name outside
    R2.6, a name twice, a tail name and a pending one; `seal`, run when the
    executor is built, refuses two steps out of R2.6's order and a gate step
    neither registered nor pending. Each refusal is a `ConfigError` naming the
    step, so a root with a wrong register does not start."""

    def __init__(self, *, pending: Mapping[str, str] = PENDING_STEPS) -> None:
        unknown = sorted(set(pending) - set(GATE_STEPS))
        if unknown:
            raise ConfigError(
                "a pending step is not a gate step of R2.6", details={"step": unknown[0]}
            )
        never = sorted(set(pending) & NEVER_PENDING)
        if never:
            raise ConfigError(
                "this step may never be pending: pending decides nothing",
                details={"step": never[0]},
            )
        self._pending = dict(pending)
        self._steps: list[tuple[str, ToolStep]] = []

    def register(self, name: str, step: ToolStep) -> None:
        if name in TAIL_STEPS:
            raise ConfigError(
                "the tail of R2.6 is run by the executor alone", details={"step": name}
            )
        if name not in GATE_STEPS:
            raise ConfigError("not a step of R2.6", details={"step": name})
        if any(known == name for known, _ in self._steps):
            raise ConfigError("step registered twice", details={"step": name})
        if name in self._pending:
            raise ConfigError(
                "a pending step is registered; take it off the pending list",
                details={"step": name},
            )
        self._steps.append((name, step))

    def entries(self) -> tuple[tuple[str, ToolStep], ...]:
        """Each registered gate step with its name, in registration order."""
        return tuple(self._steps)

    def names(self) -> tuple[str, ...]:
        """The steps a call runs, in the order it runs them."""
        return tuple(name for name, _ in self.entries()) + TAIL_STEPS

    def seal(self) -> tuple[ToolStep, ...]:
        """The gate steps in order, or `ConfigError` naming the first wrong one."""
        last = -1
        for name, _ in self.entries():
            at = GATE_STEPS.index(name)
            if at < last:
                raise ConfigError("step out of R2.6's order", details={"step": name})
            last = at
        registered = {name for name, _ in self.entries()}
        for name in GATE_STEPS:
            if name not in registered and name not in self._pending:
                raise ConfigError(
                    "a step of R2.6 is neither registered nor pending", details={"step": name}
                )
        return tuple(step for _, step in self.entries())


@dataclass
class ToolExecutor:
    registry: ToolRegistry
    execution_store: ExecutionStorePort
    uow_factory: PlatformUnitOfWorkFactory
    clock: UtcClock
    id_generator: IdGenerator
    # The one policy this process decides approvals with. Read by the agent's
    # tool wrapper and its approval middleware through this executor rather than
    # held separately, so the three gates cannot disagree about one call.
    approval_policy: AutonomyApprovalPolicy
    # Claims on a key and the dispatch log they fence (ADR-0108 decision 5).
    # Required: an executor without one would run two calls with one key at once.
    claims: ToolClaimPort
    # The gate steps, in R2.6's order (`build_tool_executor_steps`). Required:
    # an executor with no register would check nothing.
    steps: ToolSteps
    # The freeze and the kill (agent-lifecycle R7.1): the control-switch step
    # asks it first. Required: the register takes no dependencies, so a step
    # reaches its port through the executor it runs in. The agent's model
    # middleware asks the same instance.
    run_control: RunControlPort
    sleep: SleepFn = field(default=asyncio.sleep)
    base_backoff_seconds: float = 0.2
    # One span per tool call, so "how many tools did this run use, and how long
    # did each take" is answerable from the trace instead of only from the
    # audit table. Defaults to the no-op port: every existing construction site
    # and every test keeps working, and an unconfigured process pays nothing.
    telemetry: TelemetryPort = field(default_factory=NullTelemetry)
    # A Digital Worker's boundary, asked for every call of a run that acts as
    # a service principal (digital-worker R6). Unset, such a call is refused:
    # a DW run with nothing to ask about its DW reaches nothing.
    dw_boundary: DigitalWorkerBoundaryPort | None = None
    # A decision class's level now, and the approvals a call shows (wf-lite
    # R6.17). Unset, a call naming a decision class is refused.
    decision_autonomy: DecisionAutonomyPort | None = None
    approved_decisions: ApprovedDecisionsPort | None = None
    # The Send floor (ADR-0124): asked for every tool whose spec says it sends
    # a message. Unset, such a call is refused (`blocked:send_floor_unavailable`).
    send_admission: SendAdmissionPort | None = None
    _gates: tuple[ToolStep, ...] = field(init=False, repr=False, default=())

    def __post_init__(self) -> None:
        self._gates = self.steps.seal()

    def approval_required(self, definition: ToolDefinition, run_context: RunContext) -> bool:
        """The one answer to "does this call wait for a person" (R2.5;
        ADR-0116 decision 3, amended 2026-11-02): the run's autonomy decides
        it, and a call the run's mode intercepts never does, since it opens no
        approval (tenant-config R5.6). The tool wrapper and
        `OneApprovalPerStepMiddleware` ask this, and the approval step too."""
        return self.approval_policy.decide(
            definition, run_context
        ) and not definition.intercepted_in(run_context.run_mode)

    async def execute(
        self,
        *,
        name: str,
        version: str,
        raw_input: dict[str, object],
        run_context: RunContext,
        idempotency_key: str | None = None,
        approved: bool = False,
        decision: DecisionCall | None = None,
        pinned: RegisteredTool | None = None,
    ) -> BaseModel:
        """The call's checked output; `execute_recorded` says which row holds it."""
        result = await self.execute_recorded(
            name=name,
            version=version,
            raw_input=raw_input,
            run_context=run_context,
            idempotency_key=idempotency_key,
            approved=approved,
            decision=decision,
            pinned=pinned,
        )
        return result.output

    async def execute_recorded(
        self,
        *,
        name: str,
        version: str,
        raw_input: dict[str, object],
        run_context: RunContext,
        idempotency_key: str | None = None,
        approved: bool = False,
        decision: DecisionCall | None = None,
        pinned: RegisteredTool | None = None,
    ) -> ToolResult:
        """Span wrapper around the pipeline; the enforcement itself is `_execute`.

        `pinned` is the tool a Studio run pinned (tools-and-skills R4.1): the
        call resolves to it and to nothing else, and a run with a manifest that
        is not handed one is refused at `resolve`.

        Attributes carry NAMES AND COUNTS ONLY — never the tool's input or
        output. Step 4 of the pipeline masks payloads before anything is
        logged, and a span that re-attached them would walk around that
        decision by another door.
        """
        with self.telemetry.span(
            execute_tool_span_name(name),
            {
                "dw.run_id": str(run_context.run_id),
                "dw.worker_id": run_context.worker_id,
                "dw.tool_name": name,
                "dw.tool_version": version,
                # OTel GenAI semconv: what makes Langfuse render this as a
                # tool step rather than an unnamed span.
                "gen_ai.operation.name": OP_EXECUTE_TOOL,
                "gen_ai.tool.name": name,
            },
        ):
            status = "error"
            try:
                result = await self._execute(
                    name=name,
                    version=version,
                    decision=decision,
                    raw_input=raw_input,
                    run_context=run_context,
                    idempotency_key=idempotency_key,
                    approved=approved,
                    pinned=pinned,
                )
                status = "ok"
                return result
            except ApprovalRequiredError:
                status = "approval_required"
                raise
            except RunHaltedError:
                status = "halted"
                raise
            except PermissionDeniedError:
                status = "denied"
                raise
            finally:
                self.telemetry.add_metric(DW_TOOL_CALL_TOTAL, 1, {"tool": name, "status": status})

    async def _execute(
        self,
        *,
        name: str,
        version: str,
        raw_input: dict[str, object],
        run_context: RunContext,
        idempotency_key: str | None = None,
        approved: bool = False,
        decision: DecisionCall | None = None,
        pinned: RegisteredTool | None = None,
    ) -> ToolResult:
        call = ToolCall(
            name=name,
            version=version,
            raw_input=raw_input,
            run_context=run_context,
            idempotency_key=idempotency_key,
            approved=approved,
            decision=decision,
            pinned=pinned,
        )
        for step in self._gates:
            ended = await step(self, call)
            if ended is not None:
                return ToolResult(ended, call.execution_id)
        return ToolResult(await self._tail(call), call.execution_id)

    # ------------------------------------------------------- the gate steps --

    async def step_control_switch(self, call: ToolCall) -> None:
        """A freeze, a kill or an unreadable switch state refuses the call
        before anything is resolved or checked (agent-lifecycle R7.1, R7.3):
        no execution row, since nothing is resolved yet; a `tool.denied` audit
        under the name and version the call asked for; then `RunHaltedError`,
        never a permission refusal, so the runner cancels the run."""
        try:
            await self.run_control.require_open(call.run_context, door=RunControlDoor.TOOL)
        except RunHaltedError as halted:
            await self._audit(
                call.run_context,
                "tool.denied",
                call,
                canonical_hash(call.raw_input),
                policy_decision=_HALT_DECISIONS.get(halted.reason, "deny_control_state"),
                details={"reason_code": halted.reason.value},
            )
            raise

    async def step_resolve(self, call: ToolCall) -> None:
        """By the run's tenant: its own tool, else the platform's (R2.1). A
        Studio run's tool is the one it pinned, taken as handed and never read
        from the registry (R4.1; DO-05): a pinned tool that is not the one
        called, or a run with a manifest that hands none, is a `ConfigError`
        before anything is checked or run."""
        pinned = call.pinned
        if pinned is not None:
            if (pinned.definition.name, pinned.definition.version) != (call.name, call.version):
                raise ConfigError(
                    "the pinned tool is not the one called",
                    details={
                        "reason": "pinned_mismatch",
                        "tool": call.name,
                        "version": call.version,
                        "pinned": f"{pinned.definition.name}@{pinned.definition.version}",
                    },
                )
            call.tool = pinned
            return
        if call.run_context.run_manifest_hash is not None:
            raise ConfigError(
                "a Studio run calls only the tools it pinned",
                details={"reason": "tool_not_pinned", "tool": call.name, "version": call.version},
            )
        call.tool = self.registry.resolve(
            call.name, call.version, tenant_id=TenantId(call.run_context.tenant_id)
        )

    async def step_validate_input(self, call: ToolCall) -> None:
        """The tool's own schema, Pydantic or JSON (R1.1, R1.3, G1): a refusal
        names paths and keywords, never a value."""
        try:
            call.input = call.behaviour.validate_input(call.raw_input)
        except SchemaViolation as exc:
            raise DomainError(
                "tool input failed schema validation",
                details={"tool": call.name, "errors": exc.problems},
            ) from exc
        call.input_payload = call.input.model_dump(mode="json")
        call.input_hash = canonical_hash(call.input_payload)

    async def step_dw_boundary(self, call: ToolCall) -> None:
        """A Digital Worker's boundary, read now (R6): before every other
        check, so a paused DW or a tool outside its mandate is refused
        whatever the run's stamped scopes or autonomy say."""
        if call.run_context.run_as_principal_id is not None:
            call.boundary = await self._within_dw_boundary(
                call.run_context, call.definition, call.input_hash
            )

    async def step_decision_call(self, call: ToolCall) -> None:
        """A DW decision's call: its class's level now, and, when a person is
        needed, the approved decision of this run and gate with the same
        content (R6.17). It stands in for the tool-level approval below."""
        if call.decision is None:
            return
        await self._decision_cleared(
            call.run_context,
            call.definition,
            call.input_hash,
            call.raw_input,
            call.decision,
            call.boundary,
        )
        call.approved = True

    async def step_scopes(self, call: ToolCall) -> None:
        definition = call.definition
        missing = definition.required_scopes - call.run_context.scopes
        if missing:
            await self._audit(
                call.run_context,
                "tool.denied",
                definition,
                call.input_hash,
                policy_decision="deny_missing_scope",
                details={"missing_scopes": sorted(missing)},
            )
            raise PermissionDeniedError(
                "run context lacks required tool scopes",
                details={"tool": call.name, "missing_scopes": sorted(missing)},
            )

    async def step_run_mode(self, call: ToolCall) -> BaseModel | None:
        """The run's mode (tenant-config R5; N2): outside `live`, a call of a
        tool that is not `simulate_safe` is answered with a sample here, before
        the approval, the key, the Send floor, the claim and the handler, so it
        opens no approval, sends nothing and runs nothing (R5.6)."""
        if not call.definition.intercepted_in(call.run_context.run_mode):
            return None
        return await self._simulated(call)

    async def step_approval(self, call: ToolCall) -> None:
        """R2.5: a call that needs a person runs only approved, whoever called.
        Then the key: every call that leaves the platform, and every message,
        since the Send floor is asked under it (R3.1)."""
        definition = call.definition
        run_context = call.run_context
        if self.approval_required(definition, run_context) and not call.approved:
            await self._audit(
                run_context,
                "tool.approval_required",
                definition,
                call.input_hash,
                policy_decision="require_approval",
                # What made it ask. "Why did this pause" is otherwise a question
                # only the code can answer, and the code changes.
                details={
                    "autonomy_level": run_context.autonomy_level,
                    "approval_policy_version": run_context.approval_policy_version,
                },
            )
            raise ApprovalRequiredError(
                "tool requires human approval before execution",
                details={"tool": call.name, "side_effect_level": definition.side_effect_level},
            )
        needs_key = definition.side_effect_level in _KEYED_LEVELS or definition.message is not None
        if needs_key and not call.idempotency_key:
            raise DomainError(
                "side-effect tools require an idempotency key",
                details={"tool": call.name},
            )

    async def step_send_floor(self, call: ToolCall) -> BaseModel | None:
        """A message passes the Send floor (ADR-0124; compliance-pdpl R3.2),
        asked at every call (R3.1): after the approval and decision checks,
        after the replay of a recorded success, before the claim and the send.
        Every path to a tool reaches this step, so no node checks it instead."""
        if call.definition.message is None:
            return None
        key = call.idempotency_key
        if key is None:
            # The approval step requires the key; reaching here without one is
            # a register that lost that rule, refused rather than sent unasked.
            await self._refuse(
                call.run_context, call.definition, call.input_hash, "blocked:no_idempotency_key"
            )
            return None  # pragma: no cover - _refuse raises
        replayed = await self._replay(call, key)
        if replayed is not None:
            return replayed
        sending = await self._admitted_send(
            call.run_context, call.registered, call.input_payload, call.input_hash, key
        )
        call.sending = sending
        call.input = call.checked_input.model_copy(
            update={UNSUBSCRIBE_FIELD: sending[1].unsubscribe_url}
        )
        floor = self.send_admission
        if floor is not None:

            async def sent() -> None:
                await floor.sent(*sending)

            call.after_success.append(sent)
        return None

    # ------------------------------------------------------------- the tail --

    async def _tail(self, call: ToolCall) -> BaseModel:
        """Claim, log `dispatched`, run, check the output, record and audit:
        the executor's own steps, in R2.6's order, then what the gate steps
        left to run on success."""
        tool = call.registered
        definition = tool.definition
        name = definition.name
        run_context = call.run_context
        idempotency_key = call.idempotency_key
        input_hash = call.input_hash
        # Masked telemetry: a payload is never logged raw.
        safe_input = redact_mapping(call.input_payload)

        # Claim the key before looking for a success (ADR-0108 decision 5), so
        # two calls with one key never both run while the claim is live (R6.1).
        # A key on a `none` tool has nothing to protect and is not claimed.
        if idempotency_key is None or definition.side_effect_level == "none":
            if idempotency_key is not None:
                replayed = await self._replay(call, idempotency_key)
                if replayed is not None:
                    return replayed
            result = await self._run(call, safe_input, dispatch_logged=False, token=None)
            await self._after_success(call)
            return result

        token = await self.claims.claim(
            run_context, name, idempotency_key, lease_seconds=_lease_seconds(definition)
        )
        if token is None:
            replayed = await self._replay(call, idempotency_key)
            if replayed is not None:
                return replayed
            raise ConflictError(
                "another call holds this idempotency key",
                details={"tool": name, "idempotency_key": idempotency_key},
            )
        try:
            replayed = await self._replay(call, idempotency_key)
            if replayed is not None:
                return replayed
            # A send that may have been applied is never made again blindly,
            # whether this claim is new, taken over, or the lane already removed
            # the claim of the call that sent it (R6.9).
            if await self.claims.has_unresolved_dispatch(run_context, name, idempotency_key):
                await self._audit(
                    run_context,
                    "tool.failed",
                    definition,
                    input_hash,
                    policy_decision="allow",
                    details={
                        "outcome": "outcome_unknown",
                        "reason": "unresolved_dispatch",
                        "idempotency_key": idempotency_key,
                    },
                )
                raise OutcomeUnknownError(
                    "an earlier send with this key has no known outcome",
                    details={"tool": name, "idempotency_key": idempotency_key},
                )
            result = await self._run(
                call,
                safe_input,
                dispatch_logged=definition.side_effect_level in _LEAVES_THE_PLATFORM,
                token=token,
            )
            await self._after_success(call)
            return result
        finally:
            try:
                await self.claims.release(run_context, name, idempotency_key, token)
            except Exception:
                # The claim expires on its own at `expires_at`; a failed release
                # only delays the next call with this key until then.
                logger.exception("tool claim release failed", extra={"tool": name})

    @staticmethod
    async def _after_success(call: ToolCall) -> None:
        for then in call.after_success:
            await then()

    async def _admitted_send(
        self,
        run_context: RunContext,
        tool: RegisteredTool,
        input_payload: dict[str, object],
        input_hash: str,
        idempotency_key: str,
    ) -> tuple[SendRequest, Admission]:
        """The floor's admission of this call's one address, or a refusal: a
        `refused` row, `tool.denied` and `PermissionDeniedError` naming
        `blocked:<reason>`. No floor wired is a refusal too."""
        definition = tool.definition
        message = definition.message
        assert message is not None
        if UNSUBSCRIBE_FIELD not in tool.behaviour.input_schema().get("properties", {}):
            raise ConfigError(
                "a tool that sends a message takes the unsubscribe link in its input",
                details={"tool": definition.name, "field": UNSUBSCRIBE_FIELD},
            )
        addresses = _addresses(input_payload, message.recipient_fields)
        if self.send_admission is None or not addresses:
            reason = "send_floor_unavailable" if self.send_admission is None else "no_recipient"
            await self._refuse(run_context, definition, input_hash, f"blocked:{reason}")
            raise AssertionError("unreachable")  # pragma: no cover - _refuse raises
        request = SendRequest(
            scope=WorkScope(tenant_id=run_context.tenant_id, workspace_id=run_context.workspace_id),
            actor_id=run_context.actor_id,
            channel=message.channel,
            address=addresses[0],
            idempotency_key=idempotency_key,
            tool_name=definition.name,
            tool_version=definition.version,
            run_id=run_context.run_id,
            # A wf-lite run has no child runs yet: it is its own root (ticket 08).
            root_run_id=run_context.run_id,
        )
        if len(addresses) > 1:
            admission = await self.send_admission.refuse(request, "multiple_recipients")
        else:
            admission = await self.send_admission.admit(request)
        if not admission.admitted:
            await self._refuse(run_context, definition, input_hash, admission.code)
        return request, admission

    async def _replay(self, call: ToolCall, idempotency_key: str) -> BaseModel | None:
        tool = call.registered
        run_context = call.run_context
        input_hash = call.input_hash
        definition = tool.definition
        existing = await self.execution_store.find_succeeded(
            run_context, definition.name, idempotency_key
        )
        if existing is None:
            return None
        if getattr(existing, "input_hash", None) != input_hash:
            raise IdempotencyConflictError(
                "idempotency key reused with a different payload",
                details={"tool": definition.name, "idempotency_key": idempotency_key},
            )
        stored_output = getattr(existing, "output", None) or {}
        stored_id = getattr(existing, "id", None)
        call.execution_id = stored_id if isinstance(stored_id, uuid_module.UUID) else None
        await self._audit(
            run_context,
            "tool.replayed",
            definition,
            input_hash,
            policy_decision="allow",
            details={"idempotency_key": idempotency_key},
        )
        try:
            return tool.behaviour.validate_output(stored_output)
        except SchemaViolation as exc:
            raise DomainError(
                "a stored output failed the tool's output schema",
                details={
                    "tool": definition.name,
                    "reason_code": "tool_output_invalid",
                    "errors": exc.problems,
                },
            ) from exc

    async def _run(
        self,
        call: ToolCall,
        safe_input: dict[str, object],
        *,
        dispatch_logged: bool,
        token: uuid_module.UUID | None,
    ) -> BaseModel:
        tool = call.registered
        version = call.version
        input_model = call.checked_input
        input_hash = call.input_hash
        run_context = call.run_context
        idempotency_key = call.idempotency_key
        definition = tool.definition
        name = definition.name
        started_at = self.clock.now().astimezone(UTC)

        # 6. the dispatch log: committed in its own transaction before the call
        # leaves, and only while this call's own claim is live (R6.11, R6.13).
        dispatch_id: uuid_module.UUID | None = None
        if dispatch_logged:
            assert idempotency_key is not None and token is not None
            dispatch_id = self.id_generator.new_uuid()
            dispatched = await self.claims.dispatch(
                run_context,
                name,
                idempotency_key,
                token,
                DispatchRecord(
                    execution_id=dispatch_id,
                    tool_version=version,
                    input_hash=input_hash,
                    started_at=started_at,
                ),
            )
            if not dispatched:
                raise ConflictError(
                    "this call's claim was taken over before it could send",
                    details={"tool": name, "idempotency_key": idempotency_key},
                )

        # 7. execute with timeout + bounded retries. Retried only if idempotent,
        # and never once the call has left: a retry after a send is the blind
        # resend the dispatch log exists to prevent, so the caller decides.
        attempts_allowed = (
            1 if dispatch_logged else 1 + (definition.max_retries if definition.idempotent else 0)
        )
        attempt = 0
        last_error: Exception | None = None
        output_model: BaseModel | None = None
        while attempt < attempts_allowed:
            attempt += 1
            try:
                raw_output = await asyncio.wait_for(
                    tool.behaviour.handler(input_model, run_context),
                    timeout=definition.timeout_seconds,
                )
                # 8. validate output: the model never receives an output its
                # schema refuses (R1.2).
                output_model = tool.behaviour.validate_output(raw_output)
                break
            except SchemaViolation as exc:
                last_error = DomainError(
                    "tool output failed schema validation",
                    details={
                        "tool": name,
                        "reason_code": "tool_output_invalid",
                        "errors": exc.problems,
                    },
                )
                last_error.__cause__ = exc
                break
            except (TimeoutError, InfrastructureError) as exc:
                last_error = exc
                if attempt < attempts_allowed:
                    await self.sleep(self.base_backoff_seconds * (2 ** (attempt - 1)))
            except DWError as exc:
                # The tool answered, and the answer is a refusal: the row is not
                # there, the rule was broken. Retrying re-reads the same absence,
                # and letting it escape the loop would skip the record and the
                # audit below - which is how a domain failure used to leave no
                # trace at all.
                last_error = exc
                break
            except ValidationError as exc:
                # A handler that built its own output model wrongly.
                last_error = DomainError(
                    "tool output failed schema validation",
                    details={"tool": name, "reason_code": "tool_output_invalid"},
                )
                last_error.__cause__ = exc
                break
            except Exception as exc:
                # A handler that raised something untyped is a bug in the tool,
                # not a refusal anyone can answer for. It still belongs in the
                # record and the audit below: without this clause it escaped
                # `_execute` entirely, so a crash was the ONE failure mode that
                # left no execution row, no `tool.failed` event and no attempt
                # count - invisible to exactly the trail built to explain it.
                # The wrapping this then reaches is what the comment there has
                # described all along; the branch was simply unreachable.
                #
                # Broad on purpose, and last: every clause above it is narrower.
                # `asyncio.CancelledError` is a `BaseException`, so a cancelled
                # run still tears down rather than being recorded as a failure.
                # Not retried - a bug repeats, and re-running it would only
                # double whatever the handler did before it raised.
                last_error = exc
                break

        finished_at = self.clock.now().astimezone(UTC)

        if output_model is None:
            assert last_error is not None
            # After a send, only a typed answer that nothing was applied is a
            # failure; anything else - a timeout, an untyped crash - may have
            # been applied, and `failed` would invite the resend (R6.12, #7).
            unknown = dispatch_logged and not isinstance(
                last_error, NotDispatchedError | RejectedError
            )
            await self.execution_store.record(
                run_context,
                execution_id=self.id_generator.new_uuid(),
                tool_name=name,
                tool_version=version,
                status="outcome_unknown" if unknown else "failed",
                input_hash=input_hash,
                output_hash=None,
                output=None,
                idempotency_key=idempotency_key,
                error="outcome_unknown" if unknown else _error_text(last_error),
                attempts=attempt,
                started_at=started_at,
                finished_at=finished_at,
                dispatch_id=dispatch_id,
            )
            await self._audit(
                run_context,
                "tool.failed",
                definition,
                input_hash,
                policy_decision="allow",
                details={
                    "error": type(last_error).__name__,
                    "attempts": attempt,
                    "input": safe_input,
                    **({"outcome": "outcome_unknown"} if unknown else {}),
                },
            )
            if unknown:
                raise OutcomeUnknownError(
                    "the tool call may have been applied; it will not be sent again",
                    details={"tool": name, "error": type(last_error).__name__},
                ) from last_error
            # A typed failure keeps its code, because the caller routes on it:
            # a refusal the model can answer for, versus a run that is over.
            # Only untyped failures become an InfrastructureError, and that one
            # gains the tool name the raw exception never carried.
            if isinstance(last_error, DWError) and not isinstance(last_error, InfrastructureError):
                raise last_error
            raise InfrastructureError(
                "tool execution failed",
                details={"tool": name, "error": type(last_error).__name__},
            ) from last_error

        output_payload = output_model.model_dump(mode="json")
        output_hash = canonical_hash(output_payload)

        # 9. persist execution + audit
        execution_id = self.id_generator.new_uuid()
        earlier = await self.execution_store.record(
            run_context,
            execution_id=execution_id,
            tool_name=name,
            tool_version=version,
            status="succeeded",
            input_hash=input_hash,
            output_hash=output_hash,
            output=output_payload,
            idempotency_key=idempotency_key,
            error=None,
            attempts=attempt,
            started_at=started_at,
            finished_at=finished_at,
            dispatch_id=dispatch_id,
        )
        if earlier is not None:
            # The unique index refused a second success for this key: the first
            # one is the answer (the backstop behind the claim, ADR-0108 d. 5).
            assert idempotency_key is not None
            replayed = await self._replay(call, idempotency_key)
            if replayed is not None:
                return replayed
        call.execution_id = execution_id
        await self._audit(
            run_context,
            "tool.executed",
            definition,
            input_hash,
            policy_decision="allow",
            details={"output_hash": output_hash, "attempts": attempt},
        )

        # 10. typed result
        return output_model

    async def _within_dw_boundary(
        self, run_context: RunContext, definition: ToolDefinition, input_hash: str
    ) -> DwBoundary | None:
        """R6.1-R6.3: refuse `dw_not_operating` when the DW is not operating
        or its state cannot be read, `tool_not_allowed` outside its
        `allowed_tools`, `scope_lost` when its principal no longer holds a
        scope the tool needs. The refusal is a `refused` execution row and a
        `tool.denied` audit event; the tool does not run."""
        principal = run_context.run_as_principal_id
        assert principal is not None
        reason: str | None = None
        boundary: DwBoundary | None = None
        if self.dw_boundary is None:
            reason = "dw_not_operating"
        else:
            try:
                boundary = await self.dw_boundary.boundary(
                    tenant_id=run_context.tenant_id,
                    workspace_id=run_context.workspace_id,
                    principal_id=principal,
                )
            except Exception:
                logger.exception(
                    "dw boundary unreadable", extra={"run_id": str(run_context.run_id)}
                )
                boundary = None
            if boundary is None or not boundary.operating:
                reason = "dw_not_operating"
            elif definition.name not in boundary.allowed_tools:
                reason = "tool_not_allowed"
            elif not definition.required_scopes <= boundary.scopes:
                reason = "scope_lost"
        if reason is None:
            return boundary
        await self._refuse(run_context, definition, input_hash, reason)
        return None

    async def _decision_cleared(
        self,
        run_context: RunContext,
        definition: ToolDefinition,
        input_hash: str,
        raw_input: dict[str, object],
        decision: DecisionCall,
        boundary: DwBoundary | None,
    ) -> None:
        if (
            boundary is None
            or boundary.dw_id is None
            or self.decision_autonomy is None
            or self.approved_decisions is None
        ):
            await self._refuse(run_context, definition, input_hash, "approval_missing")
            return
        needs_person = await self.decision_autonomy.requires_person(
            tenant_id=run_context.tenant_id,
            workspace_id=run_context.workspace_id,
            dw_id=boundary.dw_id,
            key=decision.decision_class,
        )
        if not needs_person:
            return
        found = (
            None
            if decision.approval_id is None
            else await self.approved_decisions.approved(
                tenant_id=run_context.tenant_id,
                workspace_id=run_context.workspace_id,
                approval_id=decision.approval_id,
            )
        )
        if (
            found is None
            or found.run_id != run_context.run_id
            or found.step_id is None
            or found.step_id != decision.gate_step_id
        ):
            await self._refuse(run_context, definition, input_hash, "approval_missing")
            return
        if canonical_hash(dict(found.content)) != canonical_hash(raw_input):
            await self._refuse(run_context, definition, input_hash, "subject_changed")

    async def _refuse(
        self, run_context: RunContext, definition: ToolDefinition, input_hash: str, reason: str
    ) -> None:
        """A refused call: a `refused` execution row, a `tool.denied` audit
        event, and `PermissionDeniedError` naming the reason. The tool does not
        run."""
        now = self.clock.now()
        await self.execution_store.record(
            run_context,
            execution_id=self.id_generator.new_uuid(),
            tool_name=definition.name,
            tool_version=definition.version,
            status="refused",
            input_hash=input_hash,
            output_hash=None,
            output=None,
            idempotency_key=None,
            error=reason,
            attempts=0,
            started_at=now,
            finished_at=now,
        )
        await self._audit(
            run_context,
            "tool.denied",
            definition,
            input_hash,
            policy_decision=reason,
            details={"reason_code": reason},
        )
        raise PermissionDeniedError(
            "the digital worker's boundary refuses this call",
            details={"tool": definition.name, "reason_code": reason},
        )

    async def _simulated(self, call: ToolCall) -> BaseModel:
        """R5.1-R5.3: a sample of the tool's output schema, checked by its
        output model as a real output is, marked `simulated`; a `simulated`
        row and its `tool.simulated` audit event in one transaction."""
        tool = call.registered
        run_context = call.run_context
        input_hash = call.input_hash
        definition = tool.definition
        try:
            validated = tool.behaviour.validate_output(sample_of(tool.behaviour.output_schema()))
        except SchemaViolation as exc:
            raise DomainError(
                "the simulated output failed the tool's output schema",
                details={"tool": definition.name, "errors": exc.problems},
            ) from exc
        output: dict[str, object] = {**validated.model_dump(mode="json"), "simulated": True}
        now = self.clock.now()
        call.execution_id = self.id_generator.new_uuid()
        await self.execution_store.record(
            run_context,
            execution_id=call.execution_id,
            tool_name=definition.name,
            tool_version=definition.version,
            status="simulated",
            input_hash=input_hash,
            output_hash=canonical_hash(output),
            output=output,
            idempotency_key=None,
            error=None,
            attempts=0,
            started_at=now,
            finished_at=now,
            audit=self._audit_event(
                run_context,
                "tool.simulated",
                definition,
                input_hash,
                policy_decision="simulate",
                details={"run_mode": run_context.run_mode, "reason": "not_simulate_safe"},
            ),
        )
        return SampleOutput.model_validate(output)

    def _audit_event(
        self,
        run_context: RunContext,
        action: str,
        definition: object,
        input_hash: str,
        *,
        policy_decision: str,
        details: dict[str, object] | None = None,
    ) -> AuditEvent:
        tool_name = getattr(definition, "name", "unknown")
        tool_version = getattr(definition, "version", "unknown")
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            actor_id=UserId(run_context.actor_id),
            action=action,
            resource_type="tool",
            resource_id=f"{tool_name}@{tool_version}",
            run_id=run_context.run_id,
            policy_decision=policy_decision,
            trace_id=run_context.trace_id,
            details={"input_hash": input_hash, **(details or {})},
            occurred_at=self.clock.now().astimezone(UTC),
        )

    async def _audit(
        self,
        run_context: RunContext,
        action: str,
        definition: object,
        input_hash: str,
        *,
        policy_decision: str,
        details: dict[str, object] | None = None,
    ) -> None:
        event = self._audit_event(
            run_context,
            action,
            definition,
            input_hash,
            policy_decision=policy_decision,
            details=details,
        )
        context = access_context_from_run(run_context)
        async with self.uow_factory(context) as uow:
            await uow.audit.append(event)
            await uow.commit()
