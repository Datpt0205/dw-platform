"""The doors a Studio step's body reaches the world through (workflow-engine
R4.4, R4.5, R4.7; ADR-0112 decisions 4-5).

A body is `body(config, inputs, doors) -> output`: it holds no door in a
closure. The node wrapper builds one `EffectDoors` per attempt holding only
the door the step's type declares in `NodeTypeSpec.effect_door` (`tool`,
`records`, `assign`, `model`, `child_run`, or none), and every call through it
carries the attempt's idempotency key and the run's mode, so the door itself
simulates in `simulate` (tenant-config R5.1, custom-objects R5.4) and replays
by key after a crash. A second call in one attempt, or a call to a door the
type did not declare, is refused before anything leaves (R4.4).

Each door is a `StepDoor` the composition root registers by kind: the
`ToolExecutor` for `tool`, `ModelResolver` for `model`, and Studio's
`RecordsPort` and `RecordAssignPort` for `records` and `assign`, adapted where
the root is wired, never imported here.

A body of a `choice` type answers `Routed`: its output and the port of the lane
the run takes ("Nhánh ra"), which the wrapper records and the graph routes on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import DWError, ErrorCode
from dw_kernel.run_mode import RunMode

EffectDoor = Literal["tool", "records", "assign", "model", "child_run"]


@dataclass(frozen=True, slots=True)
class DoorCall:
    """One effect a step asks for: `operation` names it at its door (a tool
    `name@version`, a record command, a model task)."""

    door: EffectDoor
    operation: str
    payload: Mapping[str, Any]
    idempotency_key: str
    run_mode: RunMode
    run: RunContext


class StepDoor(Protocol):
    """A door of one kind, as the composition root wires it. It raises the
    kernel's typed dispatch errors (`NotDispatchedError`, `RejectedError`,
    `OutcomeUnknownError`) when its send did not simply succeed."""

    async def __call__(self, call: DoorCall) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Routed:
    """A `choice` body's answer: its output, and the port it leaves by, or
    None when no lane takes the run (a switch with no matching case)."""

    output: Mapping[str, Any]
    port: str | None


BodyResult = Mapping[str, Any] | Routed


class EffectDoorRefusedError(DWError):
    """A body asked for a door its type did not declare, or for a second
    effect in one attempt (R4.4). Never retried: the body is wrong."""

    code = ErrorCode.VALIDATION_FAILED


class EffectDoors:
    """The doors of one attempt of one step."""

    def __init__(
        self,
        *,
        declared: EffectDoor | None,
        doors: Mapping[EffectDoor, StepDoor],
        idempotency_key: str,
        run: RunContext,
        simulated_decision: str | None = None,
    ) -> None:
        self._declared = declared
        self._doors = doors
        self.idempotency_key = idempotency_key
        self.run = run
        self.run_mode: RunMode = run.run_mode
        # What a person decided in a simulated run, for an approval step
        # (workflow-nodes R9.9), from the run's own input.
        self.simulated_decision = simulated_decision
        self.calls: list[DoorCall] = []

    async def call(
        self, door: EffectDoor, operation: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if door != self._declared:
            raise EffectDoorRefusedError(
                "this step's type does not declare that door",
                details={"reason_code": "effect_door_undeclared", "door": door},
            )
        if self.calls:
            raise EffectDoorRefusedError(
                "a step makes one effect per attempt",
                details={"reason_code": "second_effect", "door": door},
            )
        target = self._doors.get(door)
        if target is None:
            raise EffectDoorRefusedError(
                "no door of this kind is wired",
                details={"reason_code": "effect_door_unwired", "door": door},
            )
        call = DoorCall(
            door, operation, dict(payload), self.idempotency_key, self.run_mode, self.run
        )
        self.calls.append(call)
        return await target(call)


StepBody = Callable[[Mapping[str, Any], Mapping[str, Any], EffectDoors], Awaitable[BodyResult]]
"""`body(config, inputs, doors)`: `config` as written, `inputs` the config with
every reference resolved against the run's state."""


__all__ = [
    "BodyResult",
    "DoorCall",
    "EffectDoor",
    "EffectDoorRefusedError",
    "EffectDoors",
    "Routed",
    "StepBody",
    "StepDoor",
]
