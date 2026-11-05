"""The contract of `RecordsPort` and `RecordAssignPort` (workflow-nodes R5.1,
R5.5, R6.5; custom-objects R5.4, R5.10, R5.11; record-access R8.11, R8.12),
as checks a test runs against any implementation: the fakes here
(workflow-engine/03), `RecordService` and `AssignRecordService` in
workflow-nodes/04. A world factory hands each check fresh doors, two live runs
acting as two principals of one company, and a record of an object both may
write; a check raises `AssertionError` naming what broke.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import IdempotencyConflictError
from dw_studio.workflows.application.ports import RecordAssignPort, RecordRequest, RecordsPort


@dataclass(frozen=True)
class RecordsWorld:
    records: RecordsPort
    assign: RecordAssignPort
    run_a: RunContext
    run_b: RunContext
    api_name: str
    record_id: uuid.UUID


WorldFactory = Callable[[], Awaitable[RecordsWorld]]


def _key() -> str:
    return f"wf:{uuid.uuid4()}:buoc:"


def _update(world: RecordsWorld, value: str) -> RecordRequest:
    return RecordRequest("update", world.api_name, world.record_id, {"ghi_chu": value})


def _read(world: RecordsWorld) -> RecordRequest:
    return RecordRequest("read", world.api_name, world.record_id, {})


async def check_simulate_writes_nothing(make: WorldFactory) -> None:
    world = await make()
    before = await world.records.run(world.run_a, _read(world), write_key=_key(), run_mode="live")
    key = _key()
    await world.records.run(world.run_a, _update(world, "giả"), write_key=key, run_mode="simulate")
    after = await world.records.run(world.run_a, _read(world), write_key=_key(), run_mode="live")
    assert after.version == before.version, "a simulated update changed the record"
    live = await world.records.run(
        world.run_a, _update(world, "thật"), write_key=key, run_mode="live"
    )
    assert not live.replayed, "a simulated write kept its key"


async def check_replays_by_key(make: WorldFactory) -> None:
    world = await make()
    key = _key()
    first = await world.records.run(
        world.run_a, _update(world, "một"), write_key=key, run_mode="live"
    )
    again = await world.records.run(
        world.run_a, _update(world, "hai"), write_key=key, run_mode="live"
    )
    assert again.replayed and not first.replayed, "the second call under the key was not a replay"
    assert again.version == first.version, "a replay wrote again"
    read = await world.records.run(world.run_a, _read(world), write_key=_key(), run_mode="live")
    assert read.version == first.version, "the key's write was applied twice"


async def check_refuses_another_principals_key(make: WorldFactory) -> None:
    world = await make()
    key = _key()
    await world.records.run(world.run_a, _update(world, "a"), write_key=key, run_mode="live")
    try:
        await world.records.run(world.run_b, _update(world, "b"), write_key=key, run_mode="live")
    except IdempotencyConflictError:
        return
    raise AssertionError("another principal's key was accepted")


async def check_assign_replays_by_key(make: WorldFactory) -> None:
    world = await make()
    key = _key()
    first = await world.assign.assign(
        world.run_a, world.api_name, world.record_id, write_key=key, run_mode="live"
    )
    again = await world.assign.assign(
        world.run_a, world.api_name, world.record_id, write_key=key, run_mode="live"
    )
    assert again.replayed and again.assignee_id == first.assignee_id, (
        "a replayed assignment handed the record to someone else"
    )


async def check_assign_simulate_changes_nothing(make: WorldFactory) -> None:
    world = await make()
    simulated = await world.assign.assign(
        world.run_a, world.api_name, world.record_id, write_key=_key(), run_mode="simulate"
    )
    live = await world.assign.assign(
        world.run_a, world.api_name, world.record_id, write_key=_key(), run_mode="live"
    )
    assert live.assignee_id == simulated.assignee_id, "a simulated assignment moved the rotation"


async def check_assign_refuses_another_principals_key(make: WorldFactory) -> None:
    world = await make()
    key = _key()
    await world.assign.assign(
        world.run_a, world.api_name, world.record_id, write_key=key, run_mode="live"
    )
    try:
        await world.assign.assign(
            world.run_b, world.api_name, world.record_id, write_key=key, run_mode="live"
        )
    except IdempotencyConflictError:
        return
    raise AssertionError("another principal's assignment key was accepted")


CHECKS = (
    check_simulate_writes_nothing,
    check_replays_by_key,
    check_refuses_another_principals_key,
    check_assign_replays_by_key,
    check_assign_simulate_changes_nothing,
    check_assign_refuses_another_principals_key,
)
