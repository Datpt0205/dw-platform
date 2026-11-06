"""A run's waits in memory, for the tests of the wait path (workflow-engine/05),
honouring the contract of `RunWaitPort` and of the SQL behind it:

- `FakeUnitOfWork` defers what is written in it to its commit, so a wait, and
  what is opened beside it, exists only once the step's transaction commits;
  leaving it without a commit drops everything;
- `FakeRunWaits` keeps rows as `platform.run_waits` does: the id
  `wait:<node_id>:<iteration_path>:<n>`, `open` handing back the row of the
  pair not yet used, `resolve` refusing a wait no longer open
  (`stale_interrupt`) and moving the run's status as the decision's two
  conditional writes do (`waiting` -> `queued`; `running` left to the park).

None of them is wired into the API or the worker.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any
from uuid import UUID

from dw_agent_runtime.adapters.run_waits import interrupt_id_of, stale_interrupt
from dw_agent_runtime.ports import WaitKind
from dw_platform.application.access_context import AccessContext


@dataclass
class FakeUnitOfWork:
    context: AccessContext | None = None
    committed: bool = False
    _pending: list[Callable[[], None]] = field(default_factory=list)

    def on_commit(self, write: Callable[[], None]) -> None:
        self._pending.append(write)

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._pending.clear()

    async def commit(self) -> None:
        for write in self._pending:
            write()
        self._pending.clear()
        self.committed = True

    async def rollback(self) -> None:
        self._pending.clear()


@dataclass
class FakeUowFactory:
    opened: list[FakeUnitOfWork] = field(default_factory=list)

    def __call__(self, context: AccessContext) -> FakeUnitOfWork:
        uow = FakeUnitOfWork(context)
        self.opened.append(uow)
        return uow


@dataclass
class WaitRow:
    run_id: UUID
    interrupt_id: str
    node_id: str
    iteration_path: str
    kind: WaitKind
    status: str
    detail: Mapping[str, Any] | None = None
    resolution: Mapping[str, Any] | None = None


@dataclass
class FakeRunWaits:
    rows: list[WaitRow] = field(default_factory=list)
    # The status of each run the decisions move, as `platform.worker_runs` has it.
    runs: dict[UUID, str] = field(default_factory=dict)

    def _pair(self, run_id: UUID, node_id: str, iteration_path: str) -> list[WaitRow]:
        return [
            r
            for r in self.rows
            if (r.run_id, r.node_id, r.iteration_path) == (run_id, node_id, iteration_path)
        ]

    async def open(
        self,
        uow: Any,
        run_id: UUID,
        node_id: str,
        iteration_path: str,
        kind: WaitKind,
        detail: Mapping[str, Any] | None = None,
    ) -> str:
        pair = self._pair(run_id, node_id, iteration_path)
        unused = [r for r in pair if r.status in ("open", "resolved")]
        if unused:
            return unused[-1].interrupt_id
        closed = sum(r.status in ("resolved", "consumed", "cancelled") for r in pair)
        row = WaitRow(
            run_id,
            interrupt_id_of(node_id, iteration_path, closed),
            node_id,
            iteration_path,
            kind,
            "open",
            dict(detail) if detail else None,
        )
        uow.on_commit(lambda: self.rows.append(row))
        return row.interrupt_id

    async def resolve(
        self, uow: Any, run_id: UUID, interrupt_id: str, resolution: Mapping[str, Any]
    ) -> None:
        found = next(
            (r for r in self.rows if (r.run_id, r.interrupt_id) == (run_id, interrupt_id)), None
        )
        if found is None or found.status != "open":
            raise stale_interrupt(run_id, interrupt_id)
        status = self.runs.get(run_id, "waiting")
        if status not in ("waiting", "running"):
            raise stale_interrupt(run_id, interrupt_id)

        def write() -> None:
            found.status, found.resolution = "resolved", dict(resolution)
            if status == "waiting":
                self.runs[run_id] = "queued"

        uow.on_commit(write)

    def of(self, run_id: UUID) -> list[WaitRow]:
        return [r for r in self.rows if r.run_id == run_id]
