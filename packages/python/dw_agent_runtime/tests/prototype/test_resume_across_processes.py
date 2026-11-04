"""A Studio agent's turn survives the death of the process that ran it
(agent-builder ticket 01, step 6 and criterion 4).

A child process runs the fixture agent on `SqlAlchemyCheckpointSaver` to its
first checkpoint, the model's tool call, and dies inside that tool with
`os._exit`: no `finally`, no flush of a pending write, as in
`apps/worker/tests/integration/test_wflite_runs_db.py`'s precedent (a failure
raised inside the process lets LangGraph flush on the way out and proves
nothing). This process, with an empty cache, builds the graph again from the
fixture under the same key and carries the turn on from the checkpoint.

`durability="sync"`, as the runner gives every run with a `definition_hash`
(`langgraph_runner._durability`): a Studio run is one. Only the existing
checkpoint tables are used; the database is this file's own.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pg_test_db import DatabaseUrls, database_urls, recreate_database, run_alembic
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from studio_agent_prototype import (
    AgentDocument,
    FixedRoutes,
    Handler,
    ProbedRunControl,
    StudioGraphSource,
    answer,
    executor_over,
    register_tools,
    run_context,
)

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.contracts import RunContext, model_facing_name
from dw_agent_runtime.tools import ToolRegistry

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent
TEST_DB = "dw_test_agent_proto"
DOC = AgentDocument.load()
TENANT, WORKSPACE = uuid.UUID(int=0xA00), uuid.UUID(int=0xA01)
QUESTION = "Lead mới hôm nay của tôi?"
DIED = 17


def _script() -> MockChatModel:
    """The pinned route's model: one tool call, then the answer."""
    return MockChatModel(
        mock_reply="",
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": model_facing_name("lead.find"),
                        "args": {"query": "hôm nay", "status": "new", "owner": "tôi"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="Có một lead mới: L-1."),
        ],
    )


class Turn:
    """One process's worth of the fixture agent on the SQL checkpointer."""

    def __init__(self, app_url: str, handler: Handler = answer) -> None:
        self.engine = create_async_engine(app_url, poolclass=NullPool)
        saver = SqlAlchemyCheckpointSaver(
            async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False),
            checkpoint_serializer(),
        )
        registry = ToolRegistry()
        register_tools(registry, DOC, tenant_id=TENANT, handler=handler)
        self.model = _script()
        self.source = StudioGraphSource(
            registry=registry,
            executor=executor_over(registry, ProbedRunControl([])),
            default_model=MockChatModel(responses=[], mock_reply="mặc định"),
            routes=FixedRoutes({DOC.profile_id: self.model}),
            checkpointer=saver,
        )

    @staticmethod
    def config(thread_id: str) -> Any:
        return {
            "configurable": {
                "thread_id": thread_id,
                "tenant_id": str(TENANT),
                "workspace_id": str(WORKSPACE),
            }
        }

    @staticmethod
    def context() -> RunContext:
        return run_context(TENANT, WORKSPACE)

    async def run(self, thread_id: str, payload: Any) -> list[BaseMessage]:
        graph = self.source.graph(TENANT, DOC)
        result = await graph.ainvoke(
            payload, config=self.config(thread_id), context=self.context(), durability="sync"
        )
        messages: list[BaseMessage] = result["messages"]
        return messages


async def _dies(payload: BaseModel, run_context: RunContext) -> Any:
    os._exit(DIED)


async def _die_in_the_first_tool(app_url: str, thread_id: str) -> None:
    """The child process: asks, the model calls a tool, and the process dies there."""
    await Turn(app_url, handler=_dies).run(thread_id, {"messages": [HumanMessage(QUESTION)]})


def shape(messages: list[BaseMessage]) -> list[tuple[Any, ...]]:
    """What a turn said, without the ids LangGraph mints per process."""
    return [
        (
            m.type,
            m.content,
            [(c["name"], c["args"], c["id"]) for c in getattr(m, "tool_calls", [])],
            getattr(m, "tool_call_id", None),
        )
        for m in messages
    ]


@pytest.fixture(scope="module")
def urls() -> DatabaseUrls:
    resolved = database_urls(TEST_DB)
    asyncio.run(recreate_database(resolved.admin, TEST_DB))
    migrated = run_alembic(["upgrade", "head"], resolved.migrator)
    assert migrated.returncode == 0, migrated.stderr[-2000:]
    asyncio.run(_seed(resolved.migrator))
    return resolved


async def _seed(migrator_url: str) -> None:
    engine = create_async_engine(migrator_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO platform.tenants (id, slug, name) VALUES (:id, 'proto', 'proto')"
                ),
                {"id": TENANT},
            )
            await conn.execute(
                text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:id, :tenant, 'main', 'main')"
                ),
                {"id": WORKSPACE, "tenant": TENANT},
            )
    finally:
        await engine.dispose()


@pytest.fixture
async def reference(urls: DatabaseUrls) -> AsyncIterator[list[BaseMessage]]:
    """The same turn run whole, in one process."""
    turn = Turn(urls.app)
    try:
        yield await turn.run(str(uuid.uuid4()), {"messages": [HumanMessage(QUESTION)]})
    finally:
        await turn.engine.dispose()


async def test_a_second_process_carries_the_turn_on_from_the_first_ones_checkpoint(
    urls: DatabaseUrls, reference: list[BaseMessage]
) -> None:
    thread_id = str(uuid.uuid4())
    child = "\n".join(
        (
            "import asyncio, sys",
            "import test_resume_across_processes as t",
            "asyncio.run(t._die_in_the_first_tool(sys.argv[1], sys.argv[2]))",
        )
    )
    path = [str(HERE), str(HERE.parent / "unit"), *sys.path]
    died = subprocess.run(
        [sys.executable, "-c", child, urls.app, thread_id],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert died.returncode == DIED, died.stderr[-2000:]

    turn = Turn(urls.app)
    try:
        assert len(turn.source.compiled) == 0, "the second process starts with no graph"
        graph = turn.source.graph(TENANT, DOC)
        saved = await graph.aget_state(Turn.config(thread_id))
        # What the first process left: the question and the model's tool call,
        # with the tool still to run.
        assert shape(saved.values["messages"]) == shape(reference[:2])
        assert saved.next == ("tools",)

        finished = await turn.run(thread_id, None)
    finally:
        await turn.engine.dispose()

    assert shape(finished) == shape(reference)
    assert len(reference) == 4
    assert len(turn.model.calls) == 1, "the model was asked again for what it had answered"
    assert turn.source.builds == 1
