"""Freeze and kill as switches every door of the runtime asks about
(agent-lifecycle R7, R9; ADR-0120 decisions 5-7, amended 2026-11-04).

What a door is told: `RunHaltedError`, a 409 carrying the reason in
`details.reason_code`. The doors themselves hold a `RunControlPort`
(`dw_agent_runtime.ports`) by injection and ask it before they act; the
answer comes from `SqlRunControl`, a per-tenant snapshot that refuses when it
cannot be refreshed (fail closed).

Which runs a reason holds and which it cancels is the caller's to apply: the
runner cancels at the doors it owns, and at admission the `studio_runs` lane
of workflow-engine applies its refusal table by `trigger_kind`.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Final

from dw_kernel.errors import ConflictError
from dw_platform.domain.audit import system_actor

__all__ = [
    "HOLDING_REASONS",
    "PRINCIPAL_DOORS",
    "RUN_REQUESTING_LANES",
    "HaltReason",
    "RunControlDoor",
    "RunHaltedError",
    "lane_actors",
]


class RunControlDoor(StrEnum):
    """Where a run asked; the `door` label of `dw_control_refusals_total`."""

    ADMISSION = "admission"
    START = "start"
    RESUME = "resume"
    NODE = "node"
    DECIDE = "decide"
    MODEL = "model"
    COMPACTION = "compaction"
    TOOL = "tool"
    SEND = "send"


class HaltReason(StrEnum):
    """`details.reason_code` of a refusal (spec, API)."""

    PLATFORM_FROZEN = "platform_frozen"
    TENANT_FROZEN = "tenant_frozen"
    ARTIFACT_KILLED = "artifact_killed"
    CONTROL_STATE_UNAVAILABLE = "control_state_unavailable"
    PRINCIPAL_INACTIVE = "principal_inactive"
    TENANT_LOCKED = "tenant_locked"
    TENANT_OFFBOARDING = "tenant_offboarding"


# The principal's standing and the company's status are read at these doors
# only, one query each time (ADR-0120 decision 6, amended 2026-11-04).
PRINCIPAL_DOORS = frozenset({RunControlDoor.ADMISSION, RunControlDoor.START, RunControlDoor.RESUME})

# What a paused run waits out at the `resume` door, unchanged, instead of being
# cancelled: "keep paused runs paused" (ADR-0120 decision 7; spec R7.14). The
# timer lane tries again at its next tick.
HOLDING_REASONS = frozenset(
    {
        HaltReason.PLATFORM_FROZEN,
        HaltReason.TENANT_FROZEN,
        HaltReason.CONTROL_STATE_UNAVAILABLE,
    }
)


# The lanes that ask for a run as themselves (ADR-0011): no membership is asked
# of their actor at a door (spec R9.1). `dw_work` asks for a Digital Worker's
# run (digital-worker R1.4); a lane that starts asking adds its registry name
# here, the one list both processes read.
RUN_REQUESTING_LANES: Final = frozenset({"dw_work"})


def lane_actors(lanes: frozenset[str] = RUN_REQUESTING_LANES) -> frozenset[uuid.UUID]:
    """The fixed actor ids of `lanes` (`system_actor`), for `SqlRunControl`."""
    return frozenset(system_actor(lane).value for lane in lanes)


class RunHaltedError(ConflictError):
    """A door refused: a switch is open, the switch state is unreadable, or the
    run's principal or company may not run (409, `details.reason_code`).

    `set_by` and `switch_id` name the open switch a refusal comes from (none
    for the other reasons): ticket 05 audits a cancelled run in that person's
    name (spec R8.11)."""

    def __init__(
        self,
        reason: HaltReason,
        *,
        door: RunControlDoor,
        set_by: uuid.UUID | None = None,
        switch_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(
            "the run may not continue",
            details={"reason_code": reason.value, "door": door.value},
        )
        self.reason = reason
        self.door = door
        self.set_by = set_by
        self.switch_id = switch_id
