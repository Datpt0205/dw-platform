"""The `records` and `assign` doors of a Studio step (workflow-engine/03,
R4.4, R4.7, R4.22): each a `StepDoor` over the Protocol this package declares,
handing the port the wrapper's key and the run's mode, so the port replays by
key and simulates in `simulate`. The composition root registers them by kind
beside the `tool` and `model` doors.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, cast, get_args

from dw_agent_runtime.wflite.doors import DoorCall, StepDoor
from dw_kernel.errors import ConfigError
from dw_studio.workflows.application.ports import (
    RecordAssignPort,
    RecordCommandName,
    RecordRequest,
    RecordsPort,
)

_COMMANDS: frozenset[str] = frozenset(get_args(RecordCommandName))


def _record_id(payload: Mapping[str, Any]) -> uuid.UUID | None:
    found = payload.get("record_id")
    return None if found in (None, "") else uuid.UUID(str(found))


def records_door(port: RecordsPort) -> StepDoor:
    async def door(call: DoorCall) -> Mapping[str, Any]:
        if call.operation not in _COMMANDS:
            raise ConfigError(
                "no such record command", details={"reason_code": "record_command_unknown"}
            )
        values = call.payload.get("values")
        answer = await port.run(
            call.run,
            RecordRequest(
                command=cast(RecordCommandName, call.operation),
                api_name=str(call.payload["object"]),
                record_id=_record_id(call.payload),
                values=dict(values) if isinstance(values, Mapping) else {},
            ),
            write_key=call.idempotency_key,
            run_mode=call.run_mode,
        )
        return {"record": dict(answer.record), "replayed": answer.replayed}

    return door


def assign_door(port: RecordAssignPort) -> StepDoor:
    async def door(call: DoorCall) -> Mapping[str, Any]:
        record_id = _record_id(call.payload)
        if record_id is None:
            raise ConfigError(
                "an assignment names its record", details={"reason_code": "record_missing"}
            )
        answer = await port.assign(
            call.run,
            str(call.payload["object"]),
            record_id,
            write_key=call.idempotency_key,
            run_mode=call.run_mode,
        )
        return {"assignee": str(answer.assignee_id), "replayed": answer.replayed}

    return door
