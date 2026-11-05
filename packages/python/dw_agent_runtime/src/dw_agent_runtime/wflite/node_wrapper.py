"""The node wrapper of a Studio run (workflow-engine R4.3-R4.13, R4.21-R4.30,
R6.28; ADR-0112 decisions 4-5; V4.30, V4.37).

One node per step; the wrapper, not LangGraph, owns what happens around the
step's body. At the start of each node, before any effect: the run's switches
(`RunControlPort`, door `node`: a freeze, a kill, an unreadable switch state;
the principal and the company are asked only where a run is taken and resumed,
ADR-0120 Amendments 2026-11-04), then the run's deadline (R4.11). Then, per
attempt:

- `StepRecorderPort.step_started` before the effect, idempotent per attempt,
  so a crashed attempt run again keeps its `started_at`;
- the body, given an `EffectDoors` holding only its type's door, with the key
  `wf:{run_id}:{node_id}:{iteration_path}`, the same on every attempt, take
  and re-run after a crash, never carrying the attempt number (R4.5);
- `asyncio.timeout(timeout_s)` per attempt;
- what came back classified (`classify`): only `not_dispatched`, a `rejected`
  whose code the action declares retryable, and an ordinary failure of an
  internal door or a body without an effect are tried again, within
  `retry.max_attempts`; `outcome_unknown` is never retried, never routed and
  never followed by the next step (R4.23, R4.24, R4.30): it ends the run
  `failed` `outcome_unknown` until workflow-engine/08's review wait;
- an output over 64 KiB is `output_too_large` (R4.6), never checkpointed.

When the attempts are spent, `on_error` decides (R4.3, R4.12): `continue`
writes `{status: "error", error}` to the step's channel and goes on, `route`
does the same and takes the error lane, and `fail` (or `route` with no error
lane at all, which only a hand-built IR reaches) ends the run `failed`.

In `simulate`, a step with a pinned result (R3.16) does not call its door: the
result is checked against the step's output schema and the 64 KiB cap and used
as its output or its error (R4.27); one that does not check, or one pinned for
a step whose type has no door (an approval, a switch), ends the run `failed`
`pinned_result_invalid` without `on_error` (R4.28, R4.29).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.dispatch import (
    NotDispatchedError,
    OutcomeUnknownError,
    RejectedError,
    ToolClaimPort,
)
from dw_agent_runtime.ports import (
    BindingReviewPort,
    HeldRunAlertPort,
    LanePath,
    RunControlPort,
    StepRecorderPort,
    StepRun,
    StepSource,
    StepStatus,
    StudioRunStorePort,
)
from dw_agent_runtime.run_control import RunControlDoor, RunHaltedError
from dw_agent_runtime.wflite.document import Step
from dw_agent_runtime.wflite.doors import (
    EffectDoor,
    EffectDoorRefusedError,
    EffectDoors,
    Routed,
    StepDoor,
)
from dw_agent_runtime.wflite.registry import NodeTypeSpec, step_output_schema
from dw_agent_runtime.wflite.validate import MESSAGES
from dw_kernel.errors import (
    ApprovalRequiredError,
    ConflictError,
    DomainError,
    DWError,
    IdempotencyConflictError,
    PermissionDeniedError,
)
from dw_kernel.expressions import ExpressionEngine
from dw_kernel.ports import UtcClock
from dw_kernel.residency import ResidencyRefusedError
from dw_observability.metrics import DW_NODE_FAILURE_TOTAL
from dw_observability.semconv import DW_NODE
from dw_observability.telemetry import TelemetryPort
from dw_platform.application.json_schema import problems

MAX_OUTPUT_BYTES: Final = 65_536
ERROR_PORT: Final = "error"

# The codes the wrapper and the doors it reads answer with: with the `wf.*`
# table, the closed set `error_type_label` lets through as a label.
WRAPPER_CODES: Final = frozenset(
    {
        "not_dispatched",
        "rejected",
        "outcome_unknown",
        "tool_output_invalid",
        "output_too_large",
        "pinned_result_invalid",
        "step_failed",
        "timeout",
        "deadline_exceeded",
        "deadline_unset",
        "effect_door_undeclared",
        "second_effect",
        "effect_door_unwired",
        "approval_wait_unavailable",
        "approval_decision_missing",
        "idempotency_conflict",
        "permission_denied",
        "approval_required",
        "validation_failed",
    }
)


def error_type_label(code: str) -> str:
    """The one label of a step's failure: its code when the code is one of the
    closed set (`wf.*` and the doors' outcomes), `unknown_error` otherwise, so
    a provider's text never becomes a metric label, a span's `error.type` or a
    column value (telemetry-and-audit R1.3)."""
    return code if code in WRAPPER_CODES or code in MESSAGES else "unknown_error"


def output_bytes(output: Any) -> int:
    """What R4.6 measures: the output as compact JSON, UTF-8."""
    return len(json.dumps(output, ensure_ascii=False, separators=(",", ":"), default=str).encode())


def port_label(port: str | None) -> str | None:
    """A lane as a person reads it: a keyed port `cases.b` is `b`."""
    if port is None:
        return None
    head, dot, rest = port.partition(".")
    return rest if dot and rest else head


# ---- signals out of the graph ---------------------------------------------------


class StudioRunFailedError(Exception):
    """The run ends `failed` with `code` at `step_id` (`on_error: fail`, a
    pinned result that does not check)."""

    def __init__(self, code: str, step_id: str) -> None:
        super().__init__(f"{code} at {step_id}")
        self.code = code
        self.step_id = step_id


class OutcomeUnknownSignal(StudioRunFailedError):  # noqa: N818 - a signal, like StepHandedOff
    """An effect that may have been applied: no retry, no `on_error`, no next
    step (R4.24). workflow-engine/08 turns it into an `outcome_review` wait;
    until then the run ends `failed` `outcome_unknown`."""

    def __init__(self, step_id: str, idempotency_key: str) -> None:
        super().__init__("outcome_unknown", step_id)
        self.idempotency_key = idempotency_key


class RunDeadlineExceededError(Exception):
    """The run passed its `deadline_at`; the store already ended it."""


# ---- what one attempt's failure means -----------------------------------------


@dataclass(frozen=True, slots=True)
class Failure:
    code: str
    message: str
    retryable: bool = False
    unknown: bool = False


def _reason(exc: BaseException, fallback: str) -> str:
    if isinstance(exc, DWError):
        found = exc.details.get("reason_code")
        if isinstance(found, str) and found:
            return found
        return str(exc.code)
    return fallback


def classify(
    exc: BaseException, door: EffectDoor | None, retryable_rejections: frozenset[str]
) -> Failure:
    """An attempt's exception as R4.23 and R4.30 read it, closed when unsure:
    an untyped failure of the `ToolExecutor`, the one door out of the platform
    in W1, may have left, so it is `outcome_unknown`."""
    # Never the exception's text: a provider's words do not reach the run.
    message = "Bước không chạy xong"
    if isinstance(exc, EffectDoorRefusedError):
        return Failure(_reason(exc, "effect_door_undeclared"), message)
    if isinstance(exc, OutcomeUnknownError):
        return Failure("outcome_unknown", message, unknown=True)
    if isinstance(exc, NotDispatchedError):
        return Failure("not_dispatched", message, retryable=True)
    if isinstance(exc, RejectedError):
        return Failure("rejected", message, retryable=exc.provider_code in retryable_rejections)
    if door == "tool":
        if isinstance(exc, IdempotencyConflictError):
            return Failure("idempotency_conflict", message)
        if isinstance(exc, ConflictError):
            # A live claim on the key, or one taken over before it sent: this
            # attempt sent nothing (runtime-hardening R6.1).
            return Failure("not_dispatched", message, retryable=True)
        if isinstance(exc, DomainError) and _reason(exc, "") == "tool_output_invalid":
            # The provider answered and its answer does not check: retrying
            # is sending again; the step's `on_error` decides.
            return Failure("tool_output_invalid", message)
        if isinstance(exc, DomainError | PermissionDeniedError | ApprovalRequiredError):
            # A policy, approval or input refusal: a typed `rejected`, never
            # retried (R4.23).
            return Failure("rejected", message)
        return Failure("outcome_unknown", message, unknown=True)
    if door is None and isinstance(exc, DWError):
        # A body without an effect that refuses (a CEL error, a config the
        # validator could not see) refuses the same way next time.
        return Failure(_reason(exc, "step_failed"), message)
    # An internal door (records, assign, model, a child run) replays by key,
    # so an ordinary failure is tried again under the same key (R4.22).
    return Failure(_reason(exc, "step_failed"), message, retryable=True)


# ---- the ports and the run's own context ---------------------------------------


def no_retryable_rejections(step: Step) -> frozenset[str]:
    """No `rejected` code is retryable until an action's `delivery` block
    declares some (connections-and-vault): closed when missing."""
    return frozenset()


@dataclass(frozen=True)
class StudioNodePorts:
    """What every node of every Studio graph uses, built once at the
    composition root; nothing here belongs to one run."""

    doors: Mapping[EffectDoor, StepDoor]
    claims: ToolClaimPort
    run_control: RunControlPort
    runs: StudioRunStorePort
    recorder: StepRecorderPort
    telemetry: TelemetryPort
    clock: UtcClock
    retryable_rejections: Callable[[Step], frozenset[str]] = no_retryable_rejections
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    backoff_seconds: float = 1.0


@dataclass(frozen=True)
class StudioRunContext:
    """A Studio run's LangGraph context, built by the runner from the run's row
    each time the graph runs: never checkpointed, never from a caller."""

    run: RunContext
    deadline_at: datetime | None
    pinned_results: Mapping[str, Any] | None = None
    # The simulated decision of each approval step (workflow-nodes R9.9).
    approval_decisions: Mapping[str, str] = field(default_factory=dict)
    # The `studio_runs` lane's claim every write of the run names (R5.5).
    lease_token: str = ""


# ---- the wrapper ------------------------------------------------------------------


Resolve = Callable[[Any, Mapping[str, Any]], Any]


@dataclass(frozen=True)
class _Outcome:
    update: dict[str, Any]
    status: StepStatus
    port: str | None
    error_type: str | None
    output: Mapping[str, Any]


class StudioNode:
    """The node of one step of a Studio graph."""

    def __init__(
        self,
        *,
        step: Step,
        spec: NodeTypeSpec,
        lane_path: LanePath,
        ports: StudioNodePorts,
        resolve: Resolve,
        has_error_lane: bool = False,
        lane_taken: Callable[[str | None], str | None] = lambda port: port,
        iteration_path: str = "",
    ) -> None:
        if spec.body is None:
            raise ValueError(f"{spec.type} has no body for a Studio run")
        self.step = step
        self.spec = spec
        self.body = spec.body
        self.lane_path = lane_path
        self.ports = ports
        self.resolve = resolve
        # From the IR, the one reader of where a step's lanes sit (R2.12).
        self.has_error_lane = has_error_lane
        self.lane_taken = lane_taken
        self.iteration_path = iteration_path
        self.output_schema = step_output_schema(spec, step.config, step.on_error)

    # The run's guards, before any effect (R4.8, R4.11).
    async def _guard(self, ctx: StudioRunContext) -> None:
        run = ctx.run
        await self.ports.run_control.require_open(run, door=RunControlDoor.NODE)
        if ctx.deadline_at is None:
            # Only a run that did not come through the `studio_runs` lane has
            # none: closed, nothing runs (gate MEDIUM (b)).
            raise StudioRunFailedError("deadline_unset", self.step.id)
        if self.ports.clock.now() >= ctx.deadline_at:
            await self.ports.runs.cancel_past_deadline(
                run.tenant_id, run.run_id, lease_token=ctx.lease_token
            )
            raise RunDeadlineExceededError(self.step.id)

    async def __call__(
        self, state: Mapping[str, Any], runtime: Runtime[StudioRunContext]
    ) -> dict[str, Any]:
        ctx = runtime.context
        await self._guard(ctx)
        run = ctx.run
        key = f"wf:{run.run_id}:{self.step.id}:{self.iteration_path}"
        inputs = self.resolve(self.step.config, state)
        inputs = dict(inputs) if isinstance(inputs, Mapping) else {}
        pinned = None
        if run.run_mode == "simulate" and ctx.pinned_results:
            pinned = ctx.pinned_results.get(self.step.id)
        if pinned is not None:
            return await self._pinned(ctx, pinned, inputs)
        attempt = 1 + await self.ports.recorder.attempts(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            node_id=self.step.id,
            iteration_path=self.iteration_path,
        )
        limit = max(self.step.retry.max_attempts if self.step.retry else 1, attempt)
        while True:
            started_at = await self._started(run, attempt)
            failure, result = await self._attempt(ctx, key, inputs)
            if failure is None:
                assert result is not None
                outcome = self._succeeded(result)
                await self._record(run, attempt, started_at, outcome, inputs, "door")
                return outcome.update
            self.ports.telemetry.add_metric(
                DW_NODE_FAILURE_TOTAL, 1, {"error_type": error_type_label(failure.code)}
            )
            if failure.unknown:
                await self._record(
                    run,
                    attempt,
                    started_at,
                    _Outcome({}, "outcome_unknown", None, "outcome_unknown", {}),
                    inputs,
                    "door",
                )
                raise OutcomeUnknownSignal(self.step.id, key)
            if failure.retryable and attempt < limit:
                await self._record(
                    run, attempt, started_at, self._failed_attempt(failure), inputs, "door"
                )
                await self.ports.sleep(self._backoff(attempt))
                attempt += 1
                continue
            outcome = self._on_error(failure)
            await self._record(run, attempt, started_at, outcome, inputs, "door")
            return outcome.update

    async def _started(self, run: RunContext, attempt: int) -> datetime:
        return await self.ports.recorder.step_started(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            node_id=self.step.id,
            lane_path=self.lane_path,
            iteration_path=self.iteration_path,
            attempt=attempt,
        )

    async def _attempt(
        self, ctx: StudioRunContext, key: str, inputs: Mapping[str, Any]
    ) -> tuple[Failure | None, Routed | None]:
        doors = EffectDoors(
            declared=self.spec.effect_door,
            doors=self.ports.doors,
            idempotency_key=key,
            run=ctx.run,
            simulated_decision=ctx.approval_decisions.get(self.step.id),
        )
        attributes = {
            "dw.run_id": str(ctx.run.run_id),
            "dw.tenant_id": str(ctx.run.tenant_id),
            "dw.step_id": self.step.id,
            "dw.step_type": self.step.type,
            "dw.run_mode": ctx.run.run_mode,
        }
        with self.ports.telemetry.span(DW_NODE, attributes):
            try:
                async with asyncio.timeout(self.step.timeout_s):
                    answer = await self.body(self.step.config, inputs, doors)
            except (GraphBubbleUp, RunHaltedError, ResidencyRefusedError):
                # A residency refusal ends the run `residency_refused`: a policy
                # answer, never a retried or routed step (compliance-pdpl R2.2).
                raise
            except TimeoutError:
                return await self._timed_out(ctx.run, doors), None
            except Exception as exc:
                return classify(exc, self.spec.effect_door, self._retryable()), None
        routed = answer if isinstance(answer, Routed) else Routed(answer, None)
        if output_bytes(routed.output) > MAX_OUTPUT_BYTES:
            return Failure("output_too_large", "output over 64 KiB"), None
        return None, routed

    async def _timed_out(self, run: RunContext, doors: EffectDoors) -> Failure:
        """R4.30: a cut `ToolExecutor` call is `outcome_unknown` while its key
        has an unresolved `dispatched` row, `not_dispatched` only when it has
        none; any other door replays by key and is tried again."""
        if self.spec.effect_door == "tool" and doors.calls:
            tool_name = doors.calls[0].operation.partition("@")[0]
            if await self.ports.claims.has_unresolved_dispatch(
                run, tool_name, doors.idempotency_key
            ):
                return Failure("outcome_unknown", "timeout after dispatch", unknown=True)
            return Failure("not_dispatched", "timeout before dispatch", retryable=True)
        return Failure("timeout", "timeout", retryable=True)

    def _retryable(self) -> frozenset[str]:
        return self.ports.retryable_rejections(self.step)

    def _backoff(self, attempt: int) -> float:
        base = self.ports.backoff_seconds
        if self.step.retry is not None and self.step.retry.backoff == "exponential":
            return float(base * (2 ** (attempt - 1)))
        return float(base)

    def _succeeded(self, routed: Routed) -> _Outcome:
        output = dict(routed.output)
        port = self.lane_taken(routed.port)
        update: dict[str, Any] = {
            f"out__{self.step.id}": output,
            f"port__{self.step.id}": port or "",
            "trail": [{"step_id": self.step.id, "status": "done"}],
        }
        return _Outcome(update, "succeeded", port_label(port), None, output)

    def _failed_attempt(self, failure: Failure) -> _Outcome:
        return _Outcome({}, "failed", None, error_type_label(failure.code), {})

    def _on_error(self, failure: Failure) -> _Outcome:
        policy = self.step.on_error or "fail"
        error = {"code": failure.code, "message": failure.message}
        output = {"status": "error", "error": error}
        label = error_type_label(failure.code)
        trail = [{"step_id": self.step.id, "status": "error"}]
        if policy == "route" and self.has_error_lane:
            update = {f"out__{self.step.id}": output, f"err__{self.step.id}": True, "trail": trail}
            return _Outcome(update, "failed", ERROR_PORT, label, output)
        if policy == "continue":
            update = {f"out__{self.step.id}": output, "trail": trail}
            return _Outcome(update, "failed", None, label, output)
        raise StudioRunFailedError(failure.code, self.step.id)

    async def _record(
        self,
        run: RunContext,
        attempt: int,
        started_at: datetime,
        outcome: _Outcome,
        inputs: Mapping[str, Any],
        source: StepSource,
    ) -> None:
        await self.ports.recorder.step_finished(
            StepRun(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                node_id=self.step.id,
                lane_path=self.lane_path,
                iteration_path=self.iteration_path,
                attempt=attempt,
                started_at=started_at,
                status=outcome.status,
                port=outcome.port,
                error_type=outcome.error_type,
                simulated=run.run_mode != "live",
                source=source,
                inputs=inputs,
                output=outcome.output,
                field_ids={},
            )
        )

    # ---- a pinned result (R4.27-R4.29) ----

    def _check_pinned(self, pinned: Any) -> tuple[Mapping[str, Any] | None, Failure | None]:
        invalid = StudioRunFailedError("pinned_result_invalid", self.step.id)
        if self.spec.effect_door is None or not isinstance(pinned, Mapping) or len(pinned) != 1:
            raise invalid
        if "output" in pinned:
            output = pinned["output"]
            if (
                not isinstance(output, Mapping)
                or output_bytes(output) > MAX_OUTPUT_BYTES
                or problems(self.output_schema, dict(output))
            ):
                raise invalid
            return output, None
        error = pinned.get("error")
        if (
            not isinstance(error, Mapping)
            or set(error) != {"code", "message"}
            or not all(isinstance(error[k], str) and error[k] for k in ("code", "message"))
        ):
            raise invalid
        return None, Failure(str(error["code"]), str(error["message"]))

    async def _pinned(
        self, ctx: StudioRunContext, pinned: Any, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        output, failure = self._check_pinned(pinned)
        run = ctx.run
        attempt = 1 + await self.ports.recorder.attempts(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            node_id=self.step.id,
            iteration_path=self.iteration_path,
        )
        started_at = await self._started(run, attempt)
        if failure is None:
            assert output is not None
            outcome = self._succeeded(Routed(output, None))
        else:
            # A pinned error is one attempt, never retried.
            self.ports.telemetry.add_metric(
                DW_NODE_FAILURE_TOTAL, 1, {"error_type": error_type_label(failure.code)}
            )
            outcome = self._on_error(failure)
        await self._record(run, attempt, started_at, outcome, inputs, "pinned")
        return outcome.update


__all__ = [
    "ERROR_PORT",
    "MAX_OUTPUT_BYTES",
    "WRAPPER_CODES",
    "Failure",
    "OutcomeUnknownSignal",
    "RunDeadlineExceededError",
    "StudioNode",
    "StudioNodePorts",
    "StudioRunContext",
    "StudioRunFailedError",
    "StudioRunPorts",
    "classify",
    "error_type_label",
    "no_retryable_rejections",
    "output_bytes",
    "port_label",
]


@dataclass(frozen=True)
class StudioRunPorts:
    """What a runner needs to run Studio runs: the nodes' ports (whose `runs`
    takes and ends the run) and the step-type registry the worker's
    composition root builds, the one the API validated against (R1.1)."""

    nodes: StudioNodePorts
    registry: Mapping[str, NodeTypeSpec]
    # Dispatch (workflow-engine/04): whether a trigger's run must wait for its
    # binding to be approved again, and who is told of a held run.
    binding_review: BindingReviewPort
    alerts: HeldRunAlertPort
    # What evaluates the document's `outcomes[]` when the run ends (R5.24).
    expressions: ExpressionEngine
