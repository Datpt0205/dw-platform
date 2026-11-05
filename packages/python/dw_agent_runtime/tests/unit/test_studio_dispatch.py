"""Dispatch of a Studio run: the refusal table and the order of its three
questions (workflow-engine/04: R5.9-R5.19, R5.25; WE6, WE17, WE25, WE52).

`StudioAdmission.decide` over the contract fakes of its three ports; the
same decisions written on a real row are `dw_studio`'s
`test_studio_run_lane.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from dw_agent_runtime.adapters.langgraph_runner import _studio_run_context
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import StudioRun
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.studio_dispatch import (
    HUMAN_HOLD,
    TEMPORARY_HOLD,
    Admitted,
    BindingReviewAlert,
    Ended,
    Held,
    PrincipalInactiveAlert,
    StudioAdmission,
    control_refusal,
)
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.testing.studio_runs import FakeBindingReview
from dw_kernel.limits import LimitExceededError, LimitsUnavailableError

pytestmark = pytest.mark.unit

RESETS = datetime(2026, 12, 1, tzinfo=UTC)
SPENT = LimitExceededError(
    "spent", metric="runs", scope_type="tenant", window="day", resets_at=RESETS
)
INTERACTIVE = ("chat", "manual", "test")
TRIGGERED = ("datahub", "provider_app", "record_event")


def taken(trigger_kind: str = "chat", **over: Any) -> StudioRun:
    run_id = uuid.uuid4()
    base = StudioRun(
        run_id=run_id,
        thread_id=run_id,
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        artifact_kind="workflow",
        artifact_id=uuid.uuid4(),
        artifact_version_id=uuid.uuid4(),
        pinned_hash="sha256:" + "c" * 64,
        run_mode="live",
        requested_by=uuid.uuid4(),
        run_as_principal_id=uuid.uuid4(),
        run_manifest_hash="sha256:" + "e" * 64,
        plan_id="professional",
        deadline_at=None,
        input={},
        pinned_results=None,
        document={},
        engine={"durability": "sync"},
        version_no=1,
        trace_id="t",
        trigger_kind=trigger_kind,
    )
    return replace(base, **over)


@dataclass
class Ports:
    control: OpenRunControl = field(default_factory=OpenRunControl)
    review: FakeBindingReview = field(default_factory=FakeBindingReview)
    limits: OpenLimits = field(default_factory=OpenLimits)

    def admission(self, timeout: float = 5.0) -> StudioAdmission:
        return StudioAdmission(self.control, self.review, self.limits, timeout_seconds=timeout)

    async def decide(self, run: StudioRun, timeout: float = 5.0) -> Any:
        return await self.admission(timeout).decide(run, _studio_run_context(run))


def asked_limits(ports: Ports) -> int:
    return len(ports.limits.admitted) + len(ports.limits.resumed)


# ---- R5.9, R5.10, R5.11: a spent limit, by trigger kind ---------------------------


@pytest.mark.parametrize("kind", INTERACTIVE)
async def test_r5_9_an_interactive_run_over_its_limit_fails_with_resets_at_and_metric(
    kind: str,
) -> None:
    ports = Ports(limits=OpenLimits(refuse=SPENT))
    verdict = await ports.decide(taken(kind))
    assert isinstance(verdict, Ended) and verdict.status == "failed"
    assert verdict.error["code"] == "limit_exceeded"
    assert verdict.error["metric"] == "runs"
    assert verdict.error["resets_at"] == RESETS.isoformat()
    assert verdict.refusal is SPENT


@pytest.mark.parametrize("kind", TRIGGERED)
async def test_r5_10_a_triggers_run_over_its_limit_waits_for_the_reset(kind: str) -> None:
    ports = Ports(limits=OpenLimits(refuse=SPENT))
    verdict = await ports.decide(taken(kind))
    assert isinstance(verdict, Held)
    assert verdict.until == RESETS and verdict.refusal is SPENT


async def test_a_schedule_fire_over_its_limit_is_skipped_never_held() -> None:
    """ADR-0113 Amendments 2026-10-24: `limit_refused`, so held fires do not
    all start when the window resets."""
    verdict = await Ports(limits=OpenLimits(refuse=SPENT)).decide(taken("schedule"))
    assert isinstance(verdict, Ended) and verdict.status == "cancelled"
    assert verdict.error["code"] == "limit_refused"


@pytest.mark.parametrize("kind", ["chat", "datahub"])
async def test_a_runs_own_ceiling_spent_ends_it_whatever_asked_since_no_reset_refills_it(
    kind: str,
) -> None:
    ceiling = LimitExceededError("ceiling", metric="cost_usd", scope_type="run")
    verdict = await Ports(limits=OpenLimits(refuse=ceiling)).decide(taken(kind))
    assert isinstance(verdict, Ended) and verdict.status == "failed"


async def test_r5_11_an_eval_trial_never_asks_the_limits() -> None:
    ports = Ports()
    verdict = await ports.decide(taken("eval", run_mode="simulate"))
    assert isinstance(verdict, Admitted) and not verdict.asked_limits
    assert asked_limits(ports) == 0


async def test_r5_11_a_child_run_spends_its_roots_lease_and_is_never_admitted() -> None:
    ports = Ports()
    verdict = await ports.decide(taken("manual", root_run_id=uuid.uuid4()))
    assert isinstance(verdict, Admitted) and asked_limits(ports) == 0


async def test_r5_11_the_first_take_admits_and_every_later_take_resumes() -> None:
    ports = Ports()
    first = taken("chat")
    assert isinstance(await ports.decide(first), Admitted)
    again = replace(first, deadline_at=datetime.now(UTC) + timedelta(days=30))
    for _ in range(3):
        assert isinstance(await ports.decide(again), Admitted)
    assert ports.limits.admitted == [(first.run_id, True)]
    assert ports.limits.resumed == [first.run_id] * 3


async def test_r5_11_resume_refused_ends_a_chat_run_as_admit_would() -> None:
    ports = Ports(limits=OpenLimits(refuse=SPENT))
    later = taken("chat", deadline_at=datetime.now(UTC) + timedelta(days=1))
    verdict = await ports.decide(later)
    assert isinstance(verdict, Ended) and verdict.error["code"] == "limit_exceeded"


# ---- R5.12-R5.18: the switches, by trigger kind -----------------------------------


@pytest.mark.parametrize("reason", [HaltReason.TENANT_FROZEN, HaltReason.PLATFORM_FROZEN])
@pytest.mark.parametrize("kind", [*INTERACTIVE, "eval"])
async def test_r5_12_a_freeze_cancels_an_interactive_run_and_an_eval_trial(
    kind: str, reason: HaltReason
) -> None:
    ports = Ports()
    ports.control.refuse(reason)
    verdict = await ports.decide(taken(kind))
    assert verdict == Ended("cancelled", {"code": reason.value, "door": "admission"})
    assert asked_limits(ports) == 0


@pytest.mark.parametrize("kind", [*TRIGGERED, "schedule"])
async def test_r5_13_a_freeze_holds_a_triggers_run_for_a_person(kind: str) -> None:
    ports = Ports()
    ports.control.refuse(HaltReason.TENANT_FROZEN)
    verdict = await ports.decide(taken(kind))
    assert isinstance(verdict, Held) and verdict.delay == HUMAN_HOLD == timedelta(minutes=5)
    assert ports.review.asked == [] and asked_limits(ports) == 0


@pytest.mark.parametrize("mode", ["live", "test"])
@pytest.mark.parametrize("kind", [*INTERACTIVE, *TRIGGERED, "schedule", "eval"])
async def test_r5_14_a_kill_cancels_every_kind_in_live_and_test(kind: str, mode: str) -> None:
    ports = Ports()
    ports.control.refuse(HaltReason.ARTIFACT_KILLED)
    verdict = await ports.decide(taken(kind, run_mode=mode))
    assert isinstance(verdict, Ended) and verdict.status == "cancelled"


async def test_r5_14_a_simulate_run_is_asked_without_its_component() -> None:
    """The lane filters by the row's mode (gate MEDIUM (b)): the component a
    kill names is not in what a `simulate` run is asked with, so the
    company's own reason is not hidden by `artifact_killed`."""
    ports = Ports()
    verdict = await ports.decide(taken("test", run_mode="simulate"))
    assert isinstance(verdict, Admitted)
    ((context, _),) = ports.control.contexts
    assert context.artifact_id is None
    live = Ports()
    await live.decide(taken("manual"))
    assert live.control.contexts[0][0].artifact_id is not None


def test_r5_14_a_kill_answered_for_a_simulate_run_is_a_broken_port() -> None:
    held = control_refusal(HaltReason.ARTIFACT_KILLED, "test", "simulate", uuid.uuid4())
    assert isinstance(held, Held) and held.delay == TEMPORARY_HOLD


@pytest.mark.parametrize("kind", [*INTERACTIVE, "eval", "schedule"])
async def test_r5_15_an_inactive_principal_cancels_the_run(kind: str) -> None:
    ports = Ports()
    ports.control.refuse(HaltReason.PRINCIPAL_INACTIVE)
    verdict = await ports.decide(taken(kind))
    assert verdict == Ended("cancelled", {"code": "principal_inactive", "door": "admission"})


@pytest.mark.parametrize("kind", TRIGGERED)
async def test_r5_17_an_inactive_service_account_holds_a_triggers_run_and_tells(
    kind: str,
) -> None:
    ports = Ports()
    ports.control.refuse(HaltReason.PRINCIPAL_INACTIVE)
    run = taken(kind)
    verdict = await ports.decide(run)
    assert isinstance(verdict, Held) and verdict.delay == HUMAN_HOLD
    assert verdict.alert == PrincipalInactiveAlert(run.run_as_principal_id)


@pytest.mark.parametrize("reason", [HaltReason.TENANT_LOCKED, HaltReason.TENANT_OFFBOARDING])
@pytest.mark.parametrize("kind", ["chat", "datahub", "schedule", "eval"])
async def test_r5_18_a_locked_or_leaving_company_cancels_every_kind(
    kind: str, reason: HaltReason
) -> None:
    ports = Ports()
    ports.control.refuse(reason)
    verdict = await ports.decide(taken(kind))
    assert verdict == Ended("cancelled", {"code": reason.value, "door": "admission"})


@pytest.mark.parametrize("kind", ["chat", "datahub", "eval"])
async def test_r5_16_an_unreadable_switch_state_holds_every_kind_briefly(kind: str) -> None:
    ports = Ports()
    ports.control.refuse(HaltReason.CONTROL_STATE_UNAVAILABLE)
    verdict = await ports.decide(taken(kind))
    assert isinstance(verdict, Held) and verdict.delay == TEMPORARY_HOLD == timedelta(seconds=60)
    assert asked_limits(ports) == 0


# ---- R5.19: a binding to approve again ----------------------------------------------


@pytest.mark.parametrize("kind", TRIGGERED)
async def test_r5_19_a_binding_to_review_holds_a_triggers_run_before_any_limit(
    kind: str,
) -> None:
    changed = datetime(2026, 11, 4, tzinfo=UTC)
    run = taken(kind)
    ports = Ports(review=FakeBindingReview(holds={run.run_as_principal_id: changed}))
    verdict = await ports.decide(run)
    assert isinstance(verdict, Held) and verdict.delay == HUMAN_HOLD
    assert verdict.alert == BindingReviewAlert(run.run_as_principal_id, changed)
    assert asked_limits(ports) == 0


async def test_r5_19_an_interactive_run_is_never_asked_about_a_binding() -> None:
    ports = Ports(review=FakeBindingReview(fails=True))
    assert isinstance(await ports.decide(taken("manual")), Admitted)
    assert ports.review.asked == []


async def test_a_schedule_fire_whose_binding_must_be_reviewed_is_ended() -> None:
    run = taken("schedule")
    ports = Ports(review=FakeBindingReview(holds={run.run_as_principal_id: RESETS}))
    verdict = await ports.decide(run)
    assert verdict == Ended("cancelled", {"code": "binding_needs_review"})


async def test_the_three_ports_are_asked_in_the_tables_order() -> None:
    order: list[str] = []
    run = taken("datahub")

    class Control(OpenRunControl):
        async def require_open(self, *args: Any, **kwargs: Any) -> None:
            order.append("control")

    class Review(FakeBindingReview):
        async def review(self, run: StudioRun) -> Any:
            order.append("review")

    class Limits(OpenLimits):
        async def admit(self, run_context: RunContext, *, counts_run: bool = True) -> Any:
            order.append("limits")
            return await super().admit(run_context, counts_run=counts_run)

    await StudioAdmission(Control(), Review(), Limits()).decide(run, _studio_run_context(run))
    assert order == ["control", "review", "limits"]


# ---- R5.25: a broken port or an unknown reason never opens the door ---------------


class _Raising(OpenRunControl):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def require_open(
        self, run_context: RunContext, *, door: RunControlDoor, artifacts: Sequence[Any] = ()
    ) -> None:
        raise self.error


class _Unavailable(OpenLimits):
    async def admit(self, run_context: RunContext, *, counts_run: bool = True) -> Any:
        raise LimitsUnavailableError("the policies could not be read")


class _Hangs(OpenRunControl):
    async def require_open(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(3600)


def _unknown_reason() -> RunHaltedError:
    """A reason the table has no row for (`workspace_archived`, W2)."""
    halted = RunHaltedError(HaltReason.CONTROL_STATE_UNAVAILABLE, door=RunControlDoor.ADMISSION)
    setattr(halted, "reason", "workspace_archived")  # noqa: B010 - past its type on purpose
    return halted


@pytest.mark.parametrize(
    "ports",
    [
        pytest.param(Ports(control=_Raising(ConnectionError("down"))), id="control raises"),
        pytest.param(Ports(control=_Raising(_unknown_reason())), id="unknown reason"),
        pytest.param(Ports(review=FakeBindingReview(fails=True)), id="review raises"),
        pytest.param(Ports(limits=_Unavailable()), id="limits unavailable"),
    ],
)
async def test_r5_25_a_broken_port_holds_the_run_briefly_and_never_lets_it_through(
    ports: Ports,
) -> None:
    verdict = await ports.decide(taken("datahub"))
    assert isinstance(verdict, Held) and verdict.delay == TEMPORARY_HOLD
    assert verdict.until is None and verdict.alert is None


async def test_r5_25_a_limits_port_that_raises_holds_the_run() -> None:
    class Broken(OpenLimits):
        async def admit(self, run_context: RunContext, *, counts_run: bool = True) -> Any:
            raise RuntimeError("the counters are gone")

    verdict = await Ports(limits=Broken()).decide(taken("chat"))
    assert isinstance(verdict, Held) and verdict.delay == TEMPORARY_HOLD


async def test_r5_25_a_port_that_hangs_is_cut_by_the_timeout_and_holds_the_run() -> None:
    verdict = await Ports(control=_Hangs()).decide(taken("chat"), timeout=0.05)
    assert isinstance(verdict, Held) and verdict.delay == TEMPORARY_HOLD


@pytest.mark.parametrize("kind", ["", "subworkflow", "something_new"])
async def test_a_kind_the_table_has_no_row_for_is_held_never_admitted(kind: str) -> None:
    ports = Ports()
    verdict = await ports.decide(taken(kind))
    assert isinstance(verdict, Held) and ports.control.asked == [] and asked_limits(ports) == 0
