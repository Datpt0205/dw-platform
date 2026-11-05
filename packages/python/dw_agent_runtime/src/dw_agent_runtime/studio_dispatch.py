"""Where a Studio run is admitted, and the one table that shapes a refusal
(workflow-engine R5.9-R5.19, R5.22, R5.25; ADR-0113 decision 3 and its
Amendments 2026-10-24; ADR-0121 decision 5).

`StudioAdmission.decide` asks, in this order and outside any row lock, each
under `PORT_TIMEOUT_SECONDS`: `RunControlPort` at the `admission` door, then
`BindingReviewPort` for a run a trigger requested, then `LimitsPort` (`admit`
at the first take, `resume` at every later one, nothing for an `eval` trial or
a child, which spend a lease opened elsewhere, usage-and-limits R5.6). The
runner (`LangGraphWorkflowRunner.run_studio`) is its one caller, so the claim
of the `studio_runs` lane is the one place a Studio run is admitted.

The answer is `Admitted`, `Held` (back to `queued`, due later) or `Ended`
(`cancelled` or `failed` at once). The functions `control_refusal`,
`binding_refusal` and `limit_refusal` are the table: the spec's R5 table is
its source, ADR-0113 gives the kinds W1 does not write yet their rows, and a
kind or a reason the table has no row for is held as a broken port is
(R5.25): a new reason never opens the door (failure-modes #7).

The lane's time constants live here and nowhere else: a hold that waits on
a component (`TEMPORARY_HOLD`) or on a person (`HUMAN_HOLD`), and the run's
deadline (`RUN_DEADLINE`, R5.22), which W2 replaces with the version's
`limits.max_run_seconds` under the plan's ceiling.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import (
    BindingHold,
    BindingReviewPort,
    LimitsPort,
    RunControlPort,
    RunLease,
    StudioRun,
)
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_kernel.limits import LIMIT_EXCEEDED, LIMITS_UNAVAILABLE, LimitExceededError

logger = logging.getLogger(__name__)

__all__ = [
    "BINDING_REVIEWED_KINDS",
    "EVAL",
    "HUMAN_HOLD",
    "INTERACTIVE",
    "PORT_TIMEOUT_SECONDS",
    "RUN_DEADLINE",
    "SCHEDULE",
    "TEMPORARY_HOLD",
    "TRIGGERED",
    "Admitted",
    "Ended",
    "Held",
    "StudioAdmission",
    "Verdict",
    "binding_refusal",
    "control_refusal",
    "limit_refusal",
]

# A hold that waits on a component to answer again (the switch state, the
# limits, a port that failed) or on a person (a freeze, an inactive principal,
# a binding to approve again): when the run is due next.
TEMPORARY_HOLD: Final = timedelta(seconds=60)
HUMAN_HOLD: Final = timedelta(minutes=5)
# A run's deadline from its first take (R5.22), and the age past which a run
# never taken is ended (R5.23). W2: `min(limits.max_run_seconds, plan
# ceiling)`, at most 90 days, from `LimitsPort`.
RUN_DEADLINE: Final = timedelta(days=30)
# How long dispatch waits on each port before holding the run (R5.25).
PORT_TIMEOUT_SECONDS: Final = 10.0

# ADR-0113 decision 3's kinds. `replay` and `fork` are interactive; a child
# (`subworkflow`, `agent_*`) is never admitted on its own and joins with
# workflow-engine/09's row.
INTERACTIVE: Final = frozenset({"chat", "manual", "test", "replay", "fork"})
TRIGGERED: Final = frozenset({"datahub", "provider_app", "record_event"})
SCHEDULE: Final = "schedule"
EVAL: Final = "eval"
_KNOWN: Final = INTERACTIVE | TRIGGERED | {SCHEDULE, EVAL}
# The kinds whose run-as principal is a service account a binding names.
BINDING_REVIEWED_KINDS: Final = TRIGGERED | {SCHEDULE}

# `error.code` of a run refused at dispatch, beside the switch reasons.
LIMIT_REFUSED: Final = "limit_refused"
BINDING_NEEDS_REVIEW: Final = "binding_needs_review"


@dataclass(frozen=True, slots=True)
class Admitted:
    """The run passed every row; `lease` is what its model calls spend."""

    lease: RunLease
    # True when `LimitsPort.admit` or `resume` opened or joined it here,
    # False for a lease opened elsewhere (an `eval` trial's, a root's).
    asked_limits: bool


@dataclass(frozen=True, slots=True)
class PrincipalInactiveAlert:
    principal_id: UUID


@dataclass(frozen=True, slots=True)
class BindingReviewAlert:
    principal_id: UUID
    grants_changed_at: datetime


@dataclass(frozen=True, slots=True)
class Held:
    """Back to `queued`: due at `until` when set, else after `delay`."""

    reason: str
    delay: timedelta
    until: datetime | None = None
    alert: PrincipalInactiveAlert | BindingReviewAlert | None = None
    # The limit's refusal, audited `limits.refused` once (R5.10).
    refusal: LimitExceededError | None = None


@dataclass(frozen=True, slots=True)
class Ended:
    status: Literal["cancelled", "failed"]
    error: dict[str, object]
    refusal: LimitExceededError | None = None


Verdict = Admitted | Held | Ended


def _broken(reason: str) -> Held:
    """R5.25: a port that failed, timed out or answered with no row here."""
    return Held(reason, TEMPORARY_HOLD)


def control_refusal(
    reason: HaltReason | str, trigger_kind: str, run_mode: str, principal_id: UUID
) -> Held | Ended:
    """R5.12-R5.18: what `RunControlPort`'s refusal does to a run of
    `trigger_kind` in `run_mode` acting as `principal_id`."""
    code = str(reason)
    cancelled = Ended("cancelled", {"code": code, "door": RunControlDoor.ADMISSION.value})
    if trigger_kind not in _KNOWN:
        return _broken(code)
    match reason:
        case HaltReason.PLATFORM_FROZEN | HaltReason.TENANT_FROZEN:
            if trigger_kind in INTERACTIVE or trigger_kind == EVAL:
                return cancelled
            return Held(code, HUMAN_HOLD)
        case HaltReason.ARTIFACT_KILLED:
            # A kill stops `live` and `test` runs only; a `simulate` run is
            # asked without its component, so this answer for one is a port
            # that broke its contract.
            return cancelled if run_mode in ("live", "test") else _broken(code)
        case HaltReason.PRINCIPAL_INACTIVE:
            if trigger_kind in TRIGGERED:
                return Held(code, HUMAN_HOLD, alert=PrincipalInactiveAlert(principal_id))
            return cancelled
        case HaltReason.TENANT_LOCKED | HaltReason.TENANT_OFFBOARDING:
            return cancelled
        case HaltReason.CONTROL_STATE_UNAVAILABLE:
            return Held(code, TEMPORARY_HOLD)
        case _:
            return _broken(code)


def binding_refusal(trigger_kind: str, hold: BindingHold, principal_id: UUID) -> Held | Ended:
    """R5.19: a trigger's run waits for its binding to be approved again; a
    `schedule` fire is ended (ADR-0113 decision 3)."""
    if trigger_kind == SCHEDULE:
        return Ended("cancelled", {"code": BINDING_NEEDS_REVIEW})
    if trigger_kind not in TRIGGERED:
        return _broken(BINDING_NEEDS_REVIEW)
    return Held(
        BINDING_NEEDS_REVIEW,
        HUMAN_HOLD,
        alert=BindingReviewAlert(principal_id, hold.grants_changed_at),
    )


def limit_refusal(trigger_kind: str, refused: LimitExceededError) -> Held | Ended:
    """R5.9, R5.10: a spent period. A refusal with no `resets_at` is the
    run's own ceiling, which no waiting refills, so it ends the run of every
    kind."""
    details = dict(refused.details)
    resets_at = details.get("resets_at")
    error: dict[str, object] = {**details, "code": LIMIT_EXCEEDED}
    if resets_at is None:
        return Ended("failed", error, refused)
    if trigger_kind in INTERACTIVE:
        return Ended("failed", error, refused)
    if trigger_kind in TRIGGERED:
        until = datetime.fromisoformat(str(resets_at))
        return Held(LIMIT_EXCEEDED, TEMPORARY_HOLD, until=until, refusal=refused)
    if trigger_kind == SCHEDULE:
        # Skipped, never held: held fires would all start when the window
        # resets (ADR-0113 Amendments 2026-10-24).
        return Ended("cancelled", {**error, "code": LIMIT_REFUSED}, refused)
    return _broken(LIMIT_EXCEEDED)


@dataclass(frozen=True)
class StudioAdmission:
    """The three questions of dispatch, asked for one taken run."""

    run_control: RunControlPort
    binding_review: BindingReviewPort
    limits: LimitsPort
    timeout_seconds: float = PORT_TIMEOUT_SECONDS

    async def decide(self, taken: StudioRun, run: RunContext) -> Verdict:
        kind = taken.trigger_kind
        if kind not in _KNOWN:
            return _broken("trigger_kind_unshaped")
        # The lane filters by the row's mode, never waiting on the port to: a
        # `simulate` run is asked without its component, so a kill does not
        # hide a company's reason (gate MEDIUM (b); ADR-0120 decision 7).
        asked = run if run.run_mode != "simulate" else run.model_copy(update={"artifact_id": None})
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.run_control.require_open(asked, door=RunControlDoor.ADMISSION)
        except RunHaltedError as halted:
            return control_refusal(halted.reason, kind, run.run_mode, taken.run_as_principal_id)
        except Exception:
            logger.warning("RunControlPort failed at dispatch", exc_info=True)
            return _broken(HaltReason.CONTROL_STATE_UNAVAILABLE.value)
        if kind in BINDING_REVIEWED_KINDS:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    hold = await self.binding_review.review(taken)
            except Exception:
                logger.warning("BindingReviewPort failed at dispatch", exc_info=True)
                return _broken("binding_review_unavailable")
            if hold is not None:
                return binding_refusal(kind, hold, taken.run_as_principal_id)
        # An `eval` trial spends its gate run's lease and a child its root's;
        # neither is admitted on its own (R5.11; usage-and-limits R5.6).
        if kind == EVAL or run.lease_root != run.run_id:
            return Admitted(self.limits.lease(run), asked_limits=False)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                if taken.deadline_at is None:
                    lease = await self.limits.admit(run)
                else:
                    lease = await self.limits.resume(run)
        except LimitExceededError as refused:
            return limit_refusal(kind, refused)
        except Exception:
            logger.warning("LimitsPort failed at dispatch", exc_info=True)
            return _broken(LIMITS_UNAVAILABLE)
        return Admitted(lease, asked_limits=True)
