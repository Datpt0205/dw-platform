"""A `RunControlPort` for tests and offline tools that run no company's work
(an eval script, a gateway check): it records every door asked and refuses
only what a test tells it to, so a test can freeze one door and watch it.

Never wired into the API or the worker: those hold `SqlRunControl`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError

__all__ = ["OpenRunControl"]


@dataclass
class OpenRunControl:
    """Open by default. `refuse(reason)` refuses every door from then on, or
    only `doors` when given; `reopen()` opens them again."""

    asked: list[tuple[RunControlDoor, uuid.UUID]] = field(default_factory=list)
    _reason: HaltReason | None = None
    _doors: frozenset[RunControlDoor] | None = None
    set_by: uuid.UUID | None = None

    def refuse(
        self,
        reason: HaltReason,
        *,
        doors: Sequence[RunControlDoor] | None = None,
        set_by: uuid.UUID | None = None,
    ) -> None:
        self._reason = reason
        self._doors = None if doors is None else frozenset(doors)
        self.set_by = set_by

    def reopen(self) -> None:
        self._reason = None
        self._doors = None

    def doors(self) -> list[RunControlDoor]:
        return [door for door, _ in self.asked]

    async def require_open(
        self,
        run_context: RunContext,
        *,
        door: RunControlDoor,
        artifacts: Sequence[uuid.UUID] = (),
    ) -> None:
        self.asked.append((door, run_context.run_id))
        if self._reason is not None and (self._doors is None or door in self._doors):
            raise RunHaltedError(self._reason, door=door, set_by=self.set_by)

    async def admission_state(
        self, tenant_id: uuid.UUID, artifacts: Sequence[uuid.UUID] = ()
    ) -> HaltReason | None:
        if self._doors is None or RunControlDoor.ADMISSION in self._doors:
            return self._reason
        return None
