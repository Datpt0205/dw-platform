"""The approval interrupt reaches the runner whichever side of the platform's
stack deepagents' tool wrapper stands on (discovery 15, question 3; FOG-35).

`FilesystemMiddleware` wraps every tool call of the agent it is installed on
(`awrap_tool_call`, to evict a large result to its backend). A wrapper that
catches what the tool raises would eat the `interrupt()` an approval raises,
and the run would carry on as if a person had said yes (failure-modes #5). So
it is put on both sides of `platform_middleware`, outer (listed first) and
inner (listed last, closest to the tool), on the caller and on the linked
agent, and the gated call has to pause the turn, surface one approval to the
caller of the graph (what the runner reads, `interrupts[0]`), run nothing
until it is decided, and run exactly once after.

The second test is why the first can fail: a wrapper of the same class that
swallows what it catches, in either position, leaves no interrupt to read.

Built on the code-defined path (`offered`, tools at the platform layer), as
`test_studio_sub_agent_stack.py` is: a Studio agent's `pinned` spec refuses
sub-agents today (`offered_definitions`).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

import pytest
from deepagents import FilesystemMiddleware, SubAgent, SubAgentMiddleware
from deepagents.backends import StateBackend
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel
from studio_agent_prototype import (
    COPY,
    FRAME,
    FRAME_ID,
    FRAME_VERSION,
    AgentDocument,
    ProbedRunControl,
    ToolAnswer,
    answer,
    definition_of,
    executor_over,
    models_for,
    register_tools,
    run_context,
)

from dw_agent_runtime.adapters.agent_factory import AgentSpec, platform_middleware
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.langchain_tools import platform_tools
from dw_agent_runtime.adapters.sub_agents import SubAgentSpec, sub_agent_spec
from dw_agent_runtime.contracts import RunContext, ToolDefinition, model_facing_name
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_platform.testing.residency import run_gate

pytestmark = pytest.mark.unit

DOC = AgentDocument.load()
TENANT = uuid.UUID(int=0xA00)
PREFIX = "studio.agent."

# The one call that waits for a person: `always` asks at every autonomy level,
# A4 included (`autonomy.py`), so the fixture's A4 run still pauses on it.
GATED = ToolDefinition(
    name="lead.send_offer",
    version="1.0.0",
    description="Gửi ưu đãi cho một lead.",
    input_schema_ref="studio/lead.send_offer@1.0.0/input",
    output_schema_ref="studio/lead.send_offer@1.0.0/output",
    required_scopes=frozenset(),
    side_effect_level="external",
    approval_policy="always",
    timeout_seconds=10,
    max_retries=0,
    idempotent=True,
    data_classification=frozenset({"internal"}),
)

Position = Literal["outer", "inner"]
Caller = Literal["parent", "child"]


class OfferInput(BaseModel):
    record_id: str


class _SwallowingFilesystem(FilesystemMiddleware):
    """The wrapper with a catch-all: what a careless subclass, or a library
    release that starts handling tool errors itself, would look like."""

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        try:
            return await handler(request)
        except BaseException:
            return ToolMessage(content="đã xử lý", tool_call_id=request.tool_call["id"])


def _call(name: str, args: dict[str, str], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _placed(
    stack: list[AgentMiddleware[Any, Any]],
    wrapper: AgentMiddleware[Any, Any],
    position: Position,
) -> list[AgentMiddleware[Any, Any]]:
    """Listed first is the outer layer (M2, `test_library_contracts.py` (b))."""
    return [wrapper, *stack] if position == "outer" else [*stack, wrapper]


class _Turn:
    """One agent with a linked agent, `wrapper_cls` on both of their stacks."""

    def __init__(
        self,
        position: Position,
        caller: Caller,
        wrapper_cls: type[FilesystemMiddleware] = FilesystemMiddleware,
    ) -> None:
        self.sent: list[str] = []
        registry = ToolRegistry()
        register_tools(registry, DOC, tenant_id=None)

        async def send(payload: BaseModel, run_context: RunContext) -> ToolAnswer:
            self.sent.append(payload.model_dump_json())
            return await answer(payload, run_context)

        registry.register(
            RegisteredTool(
                definition=GATED, behaviour=pydantic_behaviour(OfferInput, ToolAnswer, send)
            )
        )
        executor = executor_over(registry, ProbedRunControl([]))
        prompts = PromptRegistry()
        prompts.register(FRAME)
        offered = (*(definition_of(tool) for tool in DOC.tools), GATED)
        gated_call = _call(model_facing_name(GATED.name), {"record_id": "L-1"}, "g1")
        self.parent_model = MockChatModel(
            mock_reply="",
            responses=[
                gated_call
                if caller == "parent"
                else _call(
                    "task",
                    {"description": "gửi ưu đãi cho L-1", "subagent_type": "researcher"},
                    "t1",
                ),
                AIMessage(content="cha xong"),
            ],
        )
        self.child_model = MockChatModel(
            mock_reply="", responses=[gated_call, AIMessage(content="con xong")]
        )
        spec = AgentSpec(
            residency=run_gate(),
            model=self.parent_model,
            offered=offered,
            registry=registry,
            executor=executor,
            copy=COPY,
            approval_type_prefix=PREFIX,
            prompt_id=FRAME_ID,
            prompt_version=FRAME_VERSION,
            prompts=prompts,
            prompt_variables=lambda request: {"instructions": DOC.instructions},
            limits=OpenLimits(),
            usage_recorder=InMemoryUsageRecorder(),
            pricing=FlatPricing(),
            models=models_for(DOC),
            profile_id=DOC.profile_id,
        )
        child = SubAgentSpec(
            name=DOC.sub_agent.name,
            description=DOC.sub_agent.description,
            offered=tuple(d for d in offered if d.name in {"lead.get", GATED.name}),
            model=self.child_model,
            profile_id=DOC.sub_agent.profile_id,
        )
        built = sub_agent_spec(spec, child)
        built["middleware"] = _placed(
            built["middleware"], wrapper_cls(backend=StateBackend()), position
        )
        subagent = cast("SubAgent", built)
        self.agent = create_agent(
            model=spec.model,
            tools=platform_tools(
                offered, registry, executor, approval_type_prefix=PREFIX, copy=COPY
            ),
            middleware=_placed(
                [
                    *platform_middleware(spec),
                    SubAgentMiddleware(backend=StateBackend(), subagents=[subagent]),
                ],
                wrapper_cls(backend=StateBackend()),
                position,
            ),
            context_schema=RunContext,
            checkpointer=InMemorySaver(),
        )
        self.config: Any = {"configurable": {"thread_id": str(uuid.uuid4())}}
        self.context = run_context(TENANT)

    async def ask(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.agent.ainvoke(
            {"messages": [HumanMessage(content="gửi ưu đãi cho lead L-1")]},
            config=self.config,
            context=self.context,
        )
        return result

    async def decide(self, approved: bool) -> dict[str, Any]:
        result: dict[str, Any] = await self.agent.ainvoke(
            Command(resume={"approved": approved}), config=self.config, context=self.context
        )
        return result


@pytest.mark.parametrize("caller", ["parent", "child"])
@pytest.mark.parametrize("position", ["outer", "inner"])
async def test_the_approval_reaches_the_runner_whichever_side_the_wrapper_stands(
    position: Position, caller: Caller
) -> None:
    turn = _Turn(position, caller)

    paused = await turn.ask()

    interrupts = paused.get("__interrupt__", ())
    assert len(interrupts) == 1, paused.get("messages")
    assert interrupts[0].value["approval_type"] == f"{PREFIX}{GATED.name}"
    state = await turn.agent.aget_state(turn.config)
    assert [i.value["approval_type"] for i in state.interrupts] == [f"{PREFIX}{GATED.name}"]
    assert turn.sent == [], "the gated call ran before anyone decided"

    finished = await turn.decide(approved=True)

    assert "__interrupt__" not in finished
    assert finished["messages"][-1].content == "cha xong"
    assert len(turn.sent) == 1, "the approved call ran other than once"
    # A delegated turn carries on from where it paused: the child's model is
    # asked for its answer, not asked again for the call it already made.
    assert len(turn.child_model.calls) == (2 if caller == "child" else 0)
    assert len(turn.parent_model.calls) == 2


@pytest.mark.parametrize("caller", ["parent", "child"])
@pytest.mark.parametrize("position", ["outer", "inner"])
async def test_a_wrapper_that_swallows_the_interrupt_leaves_the_runner_nothing_to_read(
    position: Position, caller: Caller
) -> None:
    """The measurement above can fail: a catch-all in either position eats
    the interrupt, and the turn ends with no approval pending."""
    turn = _Turn(position, caller, _SwallowingFilesystem)

    ended = await turn.ask()

    assert "__interrupt__" not in ended
    assert (await turn.agent.aget_state(turn.config)).interrupts == ()
