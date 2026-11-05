"""A Studio agent's turn stopped mid-way and carried on by another process
runs no tool call a second time (discovery 15, question 4; FOG-36).

Three ways a turn stops after one tool call of a step has finished:

* `died`: the process dies inside the other call of the same step, with
  `os._exit` (no `finally`, no flush), once its sibling has returned. Only a
  real death shows whether the finished sibling's write was already saved
  (failure-modes #4, as in `test_resume_across_processes.py`).
* `approval`: the executor's question pauses the other call for a person
  (`interrupt()`), and the process ends normally; the decision arrives later.
* `frozen`: the company is frozen while the step runs, and the next model
  call is refused at the run-control door (`RunHaltedError`; agent-lifecycle
  R7.1). DO-28 cancels such a run today; whether one could carry on (W3) is
  what this measures.

Each time a second process, with an empty cache, its own executor and a fresh
model, builds the graph from the fixture and carries the turn on from the
`SqlAlchemyCheckpointSaver`: the call that finished in the first process runs
0 times in the second, and the turn ends with the messages of a turn run
whole. `durability="sync"`, as the runner gives every run with a
`definition_hash`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.types import Command
from pg_test_db import DatabaseUrls, database_urls, recreate_database, run_alembic
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from studio_agent_prototype import (
    AgentDocument,
    FixedRoutes,
    StudioGraphSource,
    ToolAnswer,
    ToolSpec,
    answer,
    executor_over,
    register_tools,
    run_context,
)
from test_approval_reaches_the_runner import GATED, OfferInput
from test_resume_across_processes import _seed, shape

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.contracts import RunContext, model_facing_name
from dw_agent_runtime.run_control import HaltReason, RunControlDoor, RunHaltedError
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_kernel.ids import TenantId

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent
TEST_DB = "dw_test_agent_proto_rerun"
FIXTURE = AgentDocument.load()
# The fixture's ten reads and the gated call, as one version's tools.
DOC = dataclasses.replace(
    FIXTURE,
    tools=(*FIXTURE.tools, ToolSpec(GATED.name, GATED.version, GATED.description, ("record_id",))),
)
TENANT, WORKSPACE = uuid.UUID(int=0xA00), uuid.UUID(int=0xA01)
QUESTION = "Lead L-1 thế nào?"
DIED = 17

Stop = Literal["died", "approval", "frozen"]
FIND, GET, SEND = "lead.find", "lead.get", GATED.name
# The call that finishes in the first process, and the one the stop falls on.
SECOND = {"died": GET, "approval": SEND, "frozen": GET}


def _script(stop: Stop) -> MockChatModel:
    """Two calls in one step, then the answer."""
    return MockChatModel(
        mock_reply="",
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": model_facing_name(FIND),
                        "args": {"query": "L-1", "status": "new", "owner": "tôi"},
                        "id": "c1",
                    },
                    {
                        "name": model_facing_name(SECOND[stop]),
                        "args": {"record_id": "L-1"},
                        "id": "c2",
                    },
                ],
            ),
            AIMessage(content="L-1 là lead mới."),
        ],
    )


class Turn:
    """One process's worth of the agent: its own engine, cache, executor,
    model and count of the tool calls it ran."""

    def __init__(self, app_url: str, stop: Stop, *, stopping: bool = False) -> None:
        self.engine = create_async_engine(app_url, poolclass=NullPool)
        saver = SqlAlchemyCheckpointSaver(
            async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False),
            checkpoint_serializer(),
        )
        self.ran: Counter[str] = Counter()
        self.control = OpenRunControl()
        registry = ToolRegistry()
        register_tools(registry, FIXTURE, tenant_id=TENANT, handler=self._handler(stop, stopping))
        # The gated call, under the same company, with the definition that
        # asks a person (`register_tools` registers every fixture tool as a read).
        registry.register(
            RegisteredTool(
                definition=GATED,
                behaviour=pydantic_behaviour(OfferInput, ToolAnswer, self._counted(SEND)),
            ),
            tenant_id=TenantId(TENANT),
        )
        self.model = _script(stop)
        self.source = StudioGraphSource(
            registry=registry,
            executor=executor_over(registry, self.control),
            default_model=MockChatModel(responses=[], mock_reply="mặc định"),
            routes=FixedRoutes({DOC.profile_id: self.model}),
            checkpointer=saver,
        )

    def _counted(self, name: str) -> Any:
        async def handler(payload: BaseModel, run_context: RunContext) -> ToolAnswer:
            self.ran[name] += 1
            return await answer(payload, run_context)

        return handler

    def _handler(self, stop: Stop, stopping: bool) -> Any:
        """Counts each call; in the stopping process, `lead.get` stops the turn
        the way `stop` names, after `lead.find` has returned."""
        counted = {FIND: self._counted(FIND), GET: self._counted(GET)}

        async def handler(payload: BaseModel, run_context: RunContext) -> ToolAnswer:
            name = FIND if "query" in type(payload).model_fields else GET
            if stopping and name == GET:
                # Long enough for the sibling to return and its write to land.
                await asyncio.sleep(1.0)
                if stop == "died":
                    os._exit(DIED)
                self.control.refuse(HaltReason.TENANT_FROZEN, doors=[RunControlDoor.MODEL])
            result: ToolAnswer = await counted[name](payload, run_context)
            return result

        return handler

    @staticmethod
    def config(thread_id: str) -> Any:
        return {
            "configurable": {
                "thread_id": thread_id,
                "tenant_id": str(TENANT),
                "workspace_id": str(WORKSPACE),
            }
        }

    async def run(self, thread_id: str, payload: Any) -> dict[str, Any]:
        graph = self.source.graph(TENANT, DOC)
        result: dict[str, Any] = await graph.ainvoke(
            payload,
            config=self.config(thread_id),
            context=run_context(TENANT, WORKSPACE),
            durability="sync",
        )
        return result

    async def whole(self, thread_id: str) -> list[BaseMessage]:
        """The turn run to its end in this one process, approving if asked."""
        result = await self.run(thread_id, {"messages": [HumanMessage(QUESTION)]})
        if "__interrupt__" in result:
            result = await self.run(thread_id, Command(resume={"approved": True}))
        messages: list[BaseMessage] = result["messages"]
        return messages


async def _stop_in_the_second_call(app_url: str, thread_id: str, stop: Stop) -> None:
    """The first process: asks, and the turn stops the way `stop` names."""
    turn = Turn(app_url, stop, stopping=True)
    try:
        result = await turn.run(thread_id, {"messages": [HumanMessage(QUESTION)]})
        assert stop == "approval" and "__interrupt__" in result, result
    except RunHaltedError:
        assert stop == "frozen"
    finally:
        await turn.engine.dispose()


@pytest.fixture(scope="module")
def urls() -> DatabaseUrls:
    resolved = database_urls(TEST_DB)
    asyncio.run(recreate_database(resolved.admin, TEST_DB))
    migrated = run_alembic(["upgrade", "head"], resolved.migrator)
    assert migrated.returncode == 0, migrated.stderr[-2000:]
    asyncio.run(_seed(resolved.migrator))
    return resolved


@pytest.mark.parametrize("stop", ["died", "approval", "frozen"])
async def test_a_call_that_finished_before_the_stop_does_not_run_again(
    urls: DatabaseUrls, stop: Stop
) -> None:
    reference = Turn(urls.app, stop)
    try:
        whole = await reference.whole(str(uuid.uuid4()))
    finally:
        await reference.engine.dispose()

    thread_id = str(uuid.uuid4())
    child = "\n".join(
        (
            "import asyncio, sys",
            "import test_resume_runs_no_call_twice as t",
            "asyncio.run(t._stop_in_the_second_call(sys.argv[1], sys.argv[2], sys.argv[3]))",
        )
    )
    path = [str(HERE), str(HERE.parent / "unit"), *sys.path]
    first = subprocess.run(
        [sys.executable, "-c", child, urls.app, thread_id, stop],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert first.returncode == (DIED if stop == "died" else 0), first.stderr[-2000:]

    turn = Turn(urls.app, stop)
    try:
        assert len(turn.source.compiled) == 0, "the second process starts with no graph"
        saved = await turn.source.graph(TENANT, DOC).aget_state(Turn.config(thread_id))
        # Where the first process stopped: in the step of the model's two
        # calls, with the finished one's answer saved and the other's not, or,
        # frozen, after that step, at the next model call.
        stopped_at, waiting = (4, ("model",)) if stop == "frozen" else (3, ("tools",))
        assert shape(saved.values["messages"]) == shape(whole[:stopped_at])
        assert saved.next == waiting, saved.next

        payload: Command[Any] | None = (
            Command(resume={"approved": True}) if stop == "approval" else None
        )
        finished = (await turn.run(thread_id, payload))["messages"]
    finally:
        await turn.engine.dispose()

    assert turn.ran[FIND] == 0, f"{FIND} finished in the first process and ran again"
    assert turn.ran[SECOND[stop]] == (0 if stop == "frozen" else 1)
    assert shape(finished) == shape(whole)
    assert len(turn.model.calls) == 1, "the model was asked again for what it had answered"
