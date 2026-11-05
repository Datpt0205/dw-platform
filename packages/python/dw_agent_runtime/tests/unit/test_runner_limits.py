"""The runner is the one door that admits a run (usage-and-limits R4.1, R5.1,
R5.6; ADR-0121 decision 6).

Driven through `start` on purpose: a worker reacting to an inbound event starts
runs no HTTP request ever touched, so a limit only the API enforced would be
one a connector walks around (failure-modes #5). The fake store refuses to go
further than the run row, which is exactly the line being tested: a refused run
never reaches it, an admitted one does, and its lease is given back when the
row cannot be written.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.testing.demo_graph import DEMO_WORKER_YAML, build_demo_graph
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_kernel.limits import LimitExceededError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.domain.audit import AuditEvent

pytestmark = pytest.mark.unit

WORKER = "demo_approval"


class _ReachedTheRowError(Exception):
    """Raised by the fake store: the run got past its admission."""


@dataclass
class _FakeRunStore:
    reached: int = 0

    async def create(self, *args: Any, **kwargs: Any) -> None:
        self.reached += 1
        raise _ReachedTheRowError


@dataclass
class _Audit:
    events: list[AuditEvent] = field(default_factory=list)

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class _Uow:
    audit: _Audit

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def _runner(
    tmp_path: Path, limits: OpenLimits
) -> tuple[LangGraphWorkflowRunner, _FakeRunStore, _Audit]:
    config = tmp_path / f"{WORKER}.yaml"
    config.write_text(DEMO_WORKER_YAML, encoding="utf-8")
    graphs = GraphRegistry()
    graphs.register(WORKER, "1.0.0", build_demo_graph)
    workers = WorkerRegistry(graph_registry=graphs)
    workers.load_file(config)
    store, audit = _FakeRunStore(), _Audit()
    runner = LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=cast(Any, None),
        run_store=cast(Any, store),
        uow_factory=cast(Any, lambda context: _Uow(audit)),
        clock=FixedClock(datetime(2026, 11, 10, 3, tzinfo=UTC)),
        id_generator=Uuid4Generator(),
        limits=limits,
        approval_policy=AutonomyApprovalPolicy(),
        run_control=OpenRunControl(),
    )
    return runner, store, audit


def _context(**overrides: Any) -> RunContext:
    fields: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "actor_id": uuid.uuid4(),
        "worker_id": WORKER,
        "worker_version": "1.0.0",
        "channel": "web",
        "plan_id": "professional",
        "roles": frozenset({"member"}),
        "scopes": frozenset(),
        "trace_id": "trace-1",
        "run_mode": "live",
    }
    fields.update(overrides)
    return RunContext(**fields)


async def test_a_root_over_its_limit_is_refused_before_its_row_and_audited(
    tmp_path: Path,
) -> None:
    """R4.10 at the runner's door itself, not through the API: refused, no run
    row, one `limits.refused` in the run's actor's name on the inline path."""
    refusal = LimitExceededError(
        "spent", metric="runs", scope_type="tenant", window="day", limit=3, used=3
    )
    runner, store, audit = _runner(tmp_path, OpenLimits(refuse=refusal))
    context = _context()
    with pytest.raises(LimitExceededError):
        await runner.start(run_context=context, input_payload={"subject": "x"})
    assert store.reached == 0
    (event,) = audit.events
    assert (event.action, event.actor_id.value) == ("limits.refused", context.actor_id)
    assert event.details["metric"] == "runs"


async def test_an_admitted_root_reaches_its_row_and_a_row_that_fails_gives_the_lease_back(
    tmp_path: Path,
) -> None:
    """R5.1: admitted once, counted as a run; failure-modes #6: no row, no lease."""
    limits = OpenLimits()
    runner, store, _ = _runner(tmp_path, limits)
    context = _context()
    with pytest.raises(_ReachedTheRowError):
        await runner.start(run_context=context, input_payload={"subject": "x"})
    assert store.reached == 1
    assert limits.admitted == [(context.run_id, True)]
    assert limits.released == [(context.run_id, "failed")]


@pytest.mark.parametrize("field_name", ["root_run_id", "gate_run_id"])
async def test_a_child_or_a_gate_attempt_is_never_admitted_again(
    tmp_path: Path, field_name: str
) -> None:
    """R5.6: a child run spends its root's lease, a gate attempt its gate
    run's; neither calls `admit`, and neither gives back a lease it did not take."""
    limits = OpenLimits()
    runner, store, _ = _runner(tmp_path, limits)
    owner = uuid.uuid4()
    with pytest.raises(_ReachedTheRowError):
        await runner.start(
            run_context=_context(**{field_name: owner}), input_payload={"subject": "x"}
        )
    assert limits.admitted == []
    assert limits.released == []
    assert store.reached == 1
