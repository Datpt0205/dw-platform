"""The `studio_runs` and `studio_run_reaper` lanes over a queue in memory
(workflow-engine/04: R5.1, R5.2, R5.5, R5.6, R5.7, R5.23).

What the queue does on PostgreSQL (the claim under RLS, the fence, the dead
letter's audit and outbox) is `dw_studio`'s `test_studio_run_lane.py`; here,
what the lane does with what the queue answers.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.adapters.checkpoint_retention import FINISHED_RUN_STATUSES
from dw_agent_runtime.ports import ReapedRuns, StudioClaim, StudioLeaseLostError
from dw_agent_runtime.studio_lane import (
    BATCH,
    CLAIM_LEASE,
    HEARTBEAT_SECONDS,
    LANE_INTERVAL_SECONDS,
    MAX_REQUEUES,
    REAPER_INTERVAL_SECONDS,
    StudioRunReaper,
    StudioRunsLane,
    studio_backoff,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]


@dataclass
class MemoryQueue:
    """`StudioRunQueuePort` over lists: `due` holds each tenant's due run ids
    in claim order; `scopes` the tenants `scopes_due` answers, in order."""

    due: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)
    claims: list[tuple[uuid.UUID, int]] = field(default_factory=list)
    beats: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)
    lost: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    fail_tenant: uuid.UUID | None = None

    async def scopes_due(self, limit: int) -> list[uuid.UUID]:
        return [t for t, runs in self.due.items() if runs][:limit]

    async def claim(
        self, tenant_id: uuid.UUID, *, limit: int, worker: str, lease: timedelta
    ) -> list[StudioClaim]:
        self.claims.append((tenant_id, limit))
        taken, self.due[tenant_id] = self.due[tenant_id][:limit], self.due[tenant_id][limit:]
        found = [StudioClaim(tenant_id, run, f"{worker}:{uuid.uuid4()}") for run in taken]
        self.held |= {c.lease_token for c in found}
        return found

    async def beat(self, claim: StudioClaim, *, lease: timedelta) -> bool:
        self.beats.append(claim.lease_token)
        return claim.lease_token not in self.lost

    async def release(self, claim: StudioClaim) -> bool:
        self.released.append(claim.lease_token)
        return claim.lease_token not in self.lost

    async def orphans_due(self, limit: int) -> list[uuid.UUID]:
        self.calls.append("orphans_due")
        return list(self.due)

    async def requeue_orphans(
        self, tenant_id: uuid.UUID, *, max_requeues: int, backoff: Callable[[int], timedelta]
    ) -> ReapedRuns:
        self.calls.append(f"requeue:{tenant_id}")
        if tenant_id == self.fail_tenant:
            raise ConnectionError("this tenant's pass failed")
        return ReapedRuns()

    async def deadlines_due(self, limit: int, *, unclaimed_after: timedelta) -> list[uuid.UUID]:
        self.calls.append("deadlines_due")
        return list(self.due)

    async def cancel_overdue(
        self, tenant_id: uuid.UUID, *, unclaimed_after: timedelta
    ) -> ReapedRuns:
        self.calls.append(f"cancel:{tenant_id}")
        if tenant_id == self.fail_tenant:
            raise ConnectionError("this tenant's pass failed")
        return ReapedRuns()


@dataclass
class FakeRunner:
    """Runs a claimed run by waiting `seconds`, or raising `error`."""

    seconds: float = 0.0
    error: BaseException | None = None
    ran: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    finished: list[uuid.UUID] = field(default_factory=list)

    async def run_studio(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, lease_token: str) -> Any:
        self.ran.append((run_id, lease_token))
        await asyncio.sleep(self.seconds)
        if self.error is not None:
            raise self.error
        self.finished.append(run_id)
        return "completed"


def runs(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def lane_of(queue: MemoryQueue, runner: FakeRunner, **over: Any) -> StudioRunsLane:
    return StudioRunsLane(queue=queue, runner=runner, worker="w1", **over)


async def settle(lane: StudioRunsLane) -> None:
    while lane.running:
        await asyncio.sleep(0.01)


# ---- R5.2: fair by tenant, at most a batch ---------------------------------------------


async def test_r5_2_each_tenant_gets_its_share_of_the_batch_however_long_anothers_backlog() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    queue = MemoryQueue(due={a: runs(10_000), b: runs(1)})
    runner = FakeRunner()
    lane = lane_of(queue, runner)
    await lane()
    assert queue.claims == [(a, 4), (b, 4)]
    await settle(lane)
    assert sum(1 for run_id, _ in runner.ran if run_id not in queue.due[a]) == 5


async def test_r5_2_a_tick_claims_no_more_than_the_batch_less_what_it_still_runs() -> None:
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: runs(30)})
    runner = FakeRunner(seconds=0.2)
    lane = lane_of(queue, runner)
    await lane()
    assert lane.running == BATCH == 8
    await lane()  # nothing free: no claim at all
    assert queue.claims == [(a, 8)]
    await settle(lane)
    await lane()
    assert queue.claims == [(a, 8), (a, 8)]
    await settle(lane)


async def test_more_tenants_than_room_each_take_one_in_the_order_the_queue_gives() -> None:
    tenants = [uuid.uuid4() for _ in range(12)]
    queue = MemoryQueue(due={t: runs(2) for t in tenants})
    lane = lane_of(queue, FakeRunner())
    await lane()
    assert [t for t, _ in queue.claims] == tenants[:8]
    assert all(limit == 1 for _, limit in queue.claims)
    await settle(lane)


# ---- R5.5, R5.6: the heartbeat, a lost claim, an orderly shutdown ----------------------


async def test_r5_6_each_run_beats_from_its_claim_so_a_batch_outlasting_the_lease_keeps_it() -> (
    None
):
    """Scaled: runs of 0.35 s with a beat every 0.1 s, all eight beating while
    they run, none waiting for the first to finish."""
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: runs(8)})
    runner = FakeRunner(seconds=0.35)
    lane = lane_of(queue, runner, heartbeat_seconds=0.1)
    await lane()
    await settle(lane)
    assert len(runner.finished) == 8
    assert set(queue.beats) == queue.held
    assert len(queue.beats) >= 8 * 3


async def test_r5_5_a_heartbeat_that_finds_the_claim_gone_stops_the_run() -> None:
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: runs(1)})
    runner = FakeRunner(seconds=5)
    lane = lane_of(queue, runner, heartbeat_seconds=0.05)
    await lane()
    queue.lost |= queue.held
    await asyncio.wait_for(settle(lane), timeout=2)
    assert runner.finished == []


async def test_r5_5_a_run_whose_claim_was_taken_over_ends_quietly_in_this_worker() -> None:
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: runs(1)})
    runner = FakeRunner(error=StudioLeaseLostError(uuid.uuid4()))
    lane = lane_of(queue, runner)
    await lane()
    await settle(lane)
    assert queue.released == []


async def test_r5_6_an_orderly_shutdown_hands_every_running_claim_back() -> None:
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: runs(3)})
    runner = FakeRunner(seconds=5)
    lane = lane_of(queue, runner)
    await lane()
    await lane.close()
    assert sorted(queue.released) == sorted(queue.held) and lane.running == 0
    assert runner.finished == []


async def test_a_run_that_raises_keeps_its_claim_for_the_reaper() -> None:
    """Not handed back: a crash, whose claim lapses and is queued again with
    `attempt + 1`."""
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: runs(1)})
    lane = lane_of(queue, FakeRunner(error=RuntimeError("boom")))
    await lane()
    await settle(lane)
    assert queue.released == []


# ---- R5.6, R5.7, R5.23: the reaper -----------------------------------------------------


async def test_r5_23_the_reaper_ends_overdue_runs_before_it_queues_orphans_again() -> None:
    """A run past its deadline whose worker died is ended, not queued again."""
    a = uuid.uuid4()
    queue = MemoryQueue(due={a: []})
    await StudioRunReaper(queue)()
    assert queue.calls == ["deadlines_due", f"cancel:{a}", "orphans_due", f"requeue:{a}"]


async def test_one_tenants_failed_pass_does_not_stop_the_others() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    queue = MemoryQueue(due={a: [], b: []}, fail_tenant=a)
    await StudioRunReaper(queue)()
    assert f"cancel:{b}" in queue.calls and f"requeue:{b}" in queue.calls


def test_r5_7_the_fifth_death_dead_letters_a_run_requeued_four_times() -> None:
    assert MAX_REQUEUES == 4


@pytest.mark.parametrize(
    ("attempt", "base"), [(0, 5), (1, 10), (2, 20), (3, 40), (6, 320), (7, 600), (12, 600)]
)
def test_the_backoff_doubles_from_five_seconds_to_ten_minutes_plus_a_fifth(
    attempt: int, base: int
) -> None:
    assert studio_backoff(attempt, jitter=lambda: 0.0) == timedelta(seconds=base)
    assert studio_backoff(attempt, jitter=lambda: 1.0) == timedelta(seconds=base * 1.2)


def test_r5_6_a_dead_workers_run_is_taken_again_within_ninety_seconds() -> None:
    """The bound the lane's constants promise: the claim lapses, the reaper's
    next tick queues it after the first backoff, the lane's next tick takes
    it."""
    worst = (
        CLAIM_LEASE.total_seconds()
        + REAPER_INTERVAL_SECONDS
        + studio_backoff(0, jitter=lambda: 1.0).total_seconds()
        + LANE_INTERVAL_SECONDS
    )
    assert worst <= 90
    assert CLAIM_LEASE.total_seconds() == HEARTBEAT_SECONDS * 4


def test_r5_26_a_dead_lettered_runs_checkpoints_are_pruned_as_a_finished_runs() -> None:
    assert "dead_lettered" in FINISHED_RUN_STATUSES


# ---- R5.1: a Studio run runs in the worker's lane alone ---------------------------------


def _calls_run_studio(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Attribute) and node.attr == "run_studio" for node in ast.walk(tree)
    )


def run_studio_callers(roots: list[Path]) -> list[str]:
    return sorted(
        path.relative_to(REPO).as_posix()
        for root in roots
        for path in root.rglob("*.py")
        if "tests" not in path.parts and "testing" not in path.parts and _calls_run_studio(path)
    )


def test_r5_1_only_the_studio_runs_lane_runs_a_studio_run() -> None:
    """The API holds no runner of Studio runs: a run it requests stays
    `queued` until the worker's lane takes it."""
    roots = [REPO / "apps", REPO / "packages" / "python"]
    assert run_studio_callers(roots) == [
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/studio_lane.py"
    ]


def test_r5_1_the_scan_names_a_planted_caller(tmp_path: Path) -> None:
    planted = tmp_path / "apps" / "api" / "sneaky.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("async def go(r):\n    await r.run_studio(tenant_id=1)\n", encoding="utf-8")
    assert _calls_run_studio(planted)
