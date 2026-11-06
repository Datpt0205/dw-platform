"""`FieldSecurityToolSchemaMiddleware` in the platform's own stack
(tools-and-skills ticket 03, R6.3; field-security R4.2).

A pinned tool that carries a `FieldNarrowing` is shown to the model only as
its narrowing says for the fields the run's actor reads, at every call; a
Studio agent whose tools carry one and no `ObjectFieldsPort` is refused at
assembly rather than shown fields nobody checked. The object tools' own views
are `dw_studio`'s tests; the narrowing here is a local stand-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from test_agent_factory import _spec
from test_langchain_tools import COPY
from test_studio_tools import (
    LEAD,
    LEAD_PIN,
    ObjectEntry,
    ObjectSource,
    resolver,
    stack,
    studio_run,
)

from dw_agent_runtime.adapters.agent_factory import build_agent, platform_middleware
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.studio_tools import (
    FIELD_NARROWING,
    FieldSecurityToolSchemaMiddleware,
    PinnedTools,
    studio_tools,
)
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.profiles import ModelCapabilities
from dw_agent_runtime.tool_kinds import ToolBinding, ToolContract
from dw_agent_runtime.tool_schema import json_schema_behaviour
from dw_agent_runtime.tools import FieldNarrowing, ModelView, ToolBehaviour
from dw_kernel.errors import ConfigError

pytestmark = pytest.mark.unit

FIELDS = ("name", "phone", "status")


def view(readable: frozenset[str]) -> ModelView:
    seen = [name for name in FIELDS if name in readable]
    return ModelView(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"field": {"type": "string", "enum": seen}},
        },
        "Tìm lead theo: " + ", ".join(seen),
    )


@dataclass
class NarrowedFactory:
    """`object_crud` whose behaviour narrows its view to the readable fields."""

    def build(self, binding: ToolBinding, contract: ToolContract) -> ToolBehaviour:
        async def handler(payload: Any, run: RunContext) -> Any:
            return {"text": "x"}

        behaviour = json_schema_behaviour(contract.input_schema, contract.output_schema, handler)
        return replace(
            behaviour,
            args_schema=view(frozenset(FIELDS)).args_schema,
            narrowing=FieldNarrowing("lead", view),
        )


@dataclass
class Fields:
    hidden: set[str] = field(default_factory=set)
    asked: list[str] = field(default_factory=list)

    async def readable(self, run: RunContext, api_name: str) -> frozenset[str]:
        self.asked.append(api_name)
        return frozenset(set(FIELDS) - self.hidden)


def narrowed_tools() -> PinnedTools:
    s = stack()
    assembler = replace(s.assembler, kinds={"object_crud": NarrowedFactory()})
    return studio_tools(
        [ObjectEntry(LEAD, ("search", "get"))],
        resolver(LEAD_PIN),
        assembler,
        {"object_crud": ObjectSource()},
        s.executor,
        capabilities=ModelCapabilities(),
        approval_type_prefix="studio.agent.tool.",
        copy=COPY,
    )


def test_a_narrowed_tool_carries_its_narrowing_and_others_do_not() -> None:
    pinned = narrowed_tools()
    assert all(
        isinstance((t.metadata or {})[FIELD_NARROWING], FieldNarrowing) for t in pinned.tools
    )
    plain = studio_tools(
        [ObjectEntry(LEAD)],
        resolver(LEAD_PIN),
        stack().assembler,
        {"object_crud": ObjectSource()},
        stack().executor,
        capabilities=ModelCapabilities(),
        approval_type_prefix="studio.agent.tool.",
        copy=COPY,
    )
    assert FIELD_NARROWING not in (plain.tools[0].metadata or {})


def test_a_studio_agent_with_narrowed_tools_and_no_field_port_is_refused() -> None:
    """Closed on a gap: the stack is not built without the port."""
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    spec = replace(_spec(model), offered=(), pinned=narrowed_tools())

    with pytest.raises(ConfigError) as caught:
        platform_middleware(spec)

    assert caught.value.details["tools"] == ["obj_lead__search", "obj_lead__get"]


async def test_the_platform_stack_narrows_every_model_call() -> None:
    """R6.3 through `build_agent`: the model is shown the view for what the
    actor reads, `phone` hidden; one read for the object though two tools
    name it. Without the middleware in the stack the model sees `phone`."""
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    fields = Fields(hidden={"phone"})
    spec = replace(_spec(model), offered=(), pinned=narrowed_tools(), object_fields=fields)
    assert any(isinstance(m, FieldSecurityToolSchemaMiddleware) for m in platform_middleware(spec))

    await build_agent(spec).ainvoke({"messages": [HumanMessage("chào")]}, context=studio_run())

    shown = {tool.name: tool for tool in model.bound_tools}
    assert shown["obj_lead__search"].args_schema["properties"]["field"]["enum"] == [
        "name",
        "status",
    ]
    assert "phone" not in shown["obj_lead__get"].description
    assert fields.asked == ["lead"]

    bare = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    agent = create_agent(model=bare, tools=list(narrowed_tools().tools), context_schema=RunContext)
    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=studio_run())
    assert "phone" in str(bare.bound_tools[0].args_schema)
