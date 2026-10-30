"""The SQL checkpointer must record writes the way the reference saver does.

`InMemorySaver` is upstream's own implementation and the semantics every other
saver is written against, so these are differential: drive both through the
call sequence LangGraph makes around an interrupt, and demand the same pending
writes back.

The sequence matters. A task that interrupts writes ``__interrupt__``; when the
approval arrives the SAME task re-runs against the SAME checkpoint and writes
its real output. Upstream keeps the two apart by reserving negative indices for
the special channels (``WRITES_IDX_MAP``), so the output write is free to take
index 0. A saver that enumerates blindly puts ``__interrupt__`` on index 0 and
then drops the output write as a duplicate - and what sits at index 0 of an
agent's output batch is ``messages``.

Measured in production before this was fixed: every turn that paused for
approval vanished from the assistant's memory the moment the next turn began.
It kept proposing the write it had already made, and a salesperson approving
each proposal ended up with three identical leads.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, ClassVar, cast

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from runtime_harness import RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer

pytestmark = pytest.mark.integration

TASK_ID = "90f485fe-5d27-87a2-f401-a7d73b1ec4c9"
# What the agent node writes when it finishes: `messages` first, which is the
# whole point - it is the entry that lands on the index the interrupt took.
RESUMED_WRITES: list[tuple[str, Any]] = [
    ("messages", ["the tool ran", "and here is what it produced"]),
    ("schema_version", "1.0"),
    ("branch:to:persist", None),
]


def _config(thread_id: uuid.UUID, checkpoint_id: str | None = None) -> Any:
    run_context = make_run_context()
    configurable: dict[str, Any] = {
        "thread_id": str(thread_id),
        "checkpoint_ns": "",
        "tenant_id": str(run_context.tenant_id),
        "workspace_id": str(run_context.workspace_id),
    }
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


async def pause_then_resume(saver: BaseCheckpointSaver[Any]) -> list[tuple[str, Any]]:
    """One checkpoint, one task: it interrupts, then it is resumed."""
    thread_id = uuid.uuid4()
    checkpoint = empty_checkpoint()
    await saver.aput(_config(thread_id), checkpoint, {}, {})

    at_checkpoint = _config(thread_id, checkpoint["id"])
    await saver.aput_writes(at_checkpoint, [("__interrupt__", "waiting for a human")], TASK_ID)
    await saver.aput_writes(at_checkpoint, RESUMED_WRITES, TASK_ID)

    stored = await saver.aget_tuple(_config(thread_id))
    assert stored is not None
    return [(channel, value) for _task, channel, value in stored.pending_writes or []]


async def test_a_resumed_task_can_still_write_what_it_produced(urls: RuntimeUrls) -> None:
    reference = await pause_then_resume(InMemorySaver())

    engine = create_async_engine(urls.app, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        durable = await pause_then_resume(
            SqlAlchemyCheckpointSaver(session_factory, checkpoint_serializer())
        )
    finally:
        await engine.dispose()

    assert sorted(durable, key=repr) == sorted(reference, key=repr)
    assert dict(durable)["messages"] == RESUMED_WRITES[0][1], "the resumed task's output was lost"


async def test_replaying_a_step_stores_what_came_out_of_it_the_second_time(
    urls: RuntimeUrls,
) -> None:
    """A re-put checkpoint carries the replayed step's state, not the first try's."""
    thread_id = uuid.uuid4()
    engine = create_async_engine(urls.app, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        saver = SqlAlchemyCheckpointSaver(session_factory, checkpoint_serializer())
        first = empty_checkpoint()
        await saver.aput(_config(thread_id), first, {"step": 1}, {})

        replayed = {**first, "channel_values": {"log": ["after the approval"]}}
        await saver.aput(_config(thread_id), cast(Any, replayed), {"step": 2}, {})

        stored = await saver.aget_tuple(_config(thread_id))
    finally:
        await engine.dispose()

    assert stored is not None
    assert stored.checkpoint["channel_values"] == {"log": ["after the approval"]}
    assert stored.metadata == {"step": 2}


@dataclass
class _Smuggled:
    """A type no allowlist names. Building one is what a crafted row would make
    the process do; the counter says whether it happened."""

    built: ClassVar[int] = 0
    payload: str

    def __post_init__(self) -> None:
        type(self).built += 1


async def test_a_type_outside_the_allowlist_loads_as_data_not_as_an_object(
    urls: RuntimeUrls,
) -> None:
    """R2.5 (FH6): the row is written by a permissive serializer, the way a row
    nobody vetted would be, and read back through the composition root's."""
    thread_id = uuid.uuid4()
    engine = create_async_engine(urls.app, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        writer = SqlAlchemyCheckpointSaver(session_factory, JsonPlusSerializer())
        planted = {**empty_checkpoint(), "channel_values": {"state": _Smuggled("x")}}
        await writer.aput(_config(thread_id), cast(Any, planted), {"step": 1}, {})
        _Smuggled.built = 0

        reader = SqlAlchemyCheckpointSaver(session_factory, checkpoint_serializer())
        stored = await reader.aget_tuple(_config(thread_id))
    finally:
        await engine.dispose()

    assert stored is not None
    loaded = stored.checkpoint["channel_values"]["state"]
    assert not isinstance(loaded, _Smuggled)
    assert _Smuggled.built == 0, "a type outside ALLOWED was constructed"
