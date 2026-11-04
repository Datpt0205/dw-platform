"""Strict args schemas by the model route's capabilities (tools-and-skills
ticket 04: R4.4, R4.6, with R1.1 and R1.3 still held by the executor).

What the model is sent is read where a provider reads it: the tools and the
`bind_tools` arguments the agent handed the model, given to the real
`ChatOpenAI.bind_tools` (no request leaves; it only converts), which is what
the `openai_compatible` and `openai_responses` routes bind with.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from test_agent_factory import _spec
from test_langchain_tools import COPY
from test_studio_tools import (
    OUTPUT,
    SMTP_PIN,
    ActionEntry,
    Handler,
    Stack,
    definition,
    resolver,
    stack,
    studio_run,
)

from dw_agent_runtime.adapters.agent_factory import build_agent
from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.studio_tools import (
    CompiledTool,
    PinnedTools,
    StrictToolsMiddleware,
    drop_strict_nulls,
    render_input_schema,
    studio_tools,
    turn_capabilities,
)
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.profiles import ModelCapabilities
from dw_agent_runtime.ports import PinnedEntry
from dw_agent_runtime.tool_kinds import ToolBinding, ToolContract
from dw_kernel.errors import DomainError

pytestmark = pytest.mark.unit

# The ticket's lead tool: `lead_id` required; `note`, `amount` and `address`
# optional, `address.ward` optional inside it; and the keywords
# `dw.tool-schema/v1` allows that a strict schema does not carry.
LEAD_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lead_id": {"type": "integer", "description": "Mã lead"},
        "note": {"type": "string", "maxLength": 200},
        "amount": {"type": "number", "minimum": 0, "maximum": 1000, "multipleOf": 0.5},
        "score": {"type": "integer", "exclusiveMinimum": 0},
        "email": {"type": "string", "format": "email"},
        "stage": {"enum": ["new", "won"]},
        "address": {
            "type": "object",
            "properties": {"city": {"type": "string"}, "ward": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "by": {"type": "string"}},
                "required": ["label"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["lead_id"],
    "additionalProperties": False,
}
STRICT = ModelCapabilities(tool_calling=True, strict_tools=True)
BOUNDED = ModelCapabilities(tool_calling=True, strict_tools=True, numeric_bounds=True)
PLAIN = ModelCapabilities(tool_calling=True, numeric_bounds=True)
DROPPED = ("maxLength", "format", "exclusiveMinimum", "multipleOf")


@dataclass
class Recorder(Handler):
    """What the executor handed the handler: the input after its check."""

    payloads: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, payload: BaseModel, run_context: RunContext) -> Any:
        self.payloads.append(payload.model_dump())
        return await super().__call__(payload, run_context)


@dataclass
class LeadSource:
    """`connector_action` with the lead tool's schema."""

    def compile(self, entry: Any, pinned: PinnedEntry) -> list[CompiledTool]:
        return [
            CompiledTool(
                ToolBinding("connector_action", {"action": entry.action}, operation="read"),
                ToolContract(definition(entry.action), LEAD_INPUT, OUTPUT),
            )
        ]


def lead_tools(
    s: Stack, capabilities: ModelCapabilities, *actions: str
) -> tuple[PinnedTools, Recorder]:
    recorder = Recorder()
    s.factories["connector_action"].handler = recorder
    pinned = studio_tools(
        [ActionEntry(action) for action in actions or ("lead.update",)],
        resolver(SMTP_PIN),
        s.assembler,
        {"connector_action": LeadSource()},
        s.executor,
        capabilities=capabilities,
        approval_type_prefix="studio.agent.tool.",
        copy=COPY,
    )
    return pinned, recorder


def model_calling(name: str, args: dict[str, Any]) -> MockChatModel:
    return MockChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1"}]),
            AIMessage(content="xong"),
        ],
        mock_reply="[mock]",
    )


async def call_with(pinned: PinnedTools, args: dict[str, Any]) -> ToolMessage:
    """One model call of the first tool with `args`, through a real agent
    carrying the strict middleware when the tools are strict."""
    model = model_calling(pinned.tools[0].name, args)
    middleware: list[AgentMiddleware[Any, Any]] = [StrictToolsMiddleware()] if pinned.strict else []
    agent = create_agent(
        model=model,
        tools=list(pinned.tools),
        middleware=middleware,
        context_schema=RunContext,
    )
    state = await agent.ainvoke({"messages": [HumanMessage("cập nhật lead")]}, context=studio_run())
    return next(m for m in state["messages"] if isinstance(m, ToolMessage))


async def sent_to_provider(pinned: PinnedTools) -> list[dict[str, Any]]:
    """The function definitions the provider is sent for `pinned`, through the
    platform's own stack (`build_agent`): what the agent bound, converted by
    the real `ChatOpenAI.bind_tools`."""
    model = MockChatModel(responses=[AIMessage(content="xong")], mock_reply="[mock]")
    await build_agent(replace(_spec(model), offered=(), pinned=pinned)).ainvoke(
        {"messages": [HumanMessage("chào")]}, context=studio_run()
    )
    provider = ChatOpenAI(model="gpt-test", api_key="sk-test")
    bound = provider.bind_tools(model.bound_tools, **model.bound_kwargs)
    return [tool["function"] for tool in bound.kwargs["tools"]]  # type: ignore[attr-defined]


def as_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode()


# ------------------------------------------------------------------ R4.4 --


async def test_a_strict_route_sends_the_strict_schema_byte_for_byte_with_the_flag() -> None:
    """R4.4: the optional `note` is in `required` as `["string", "null"]`, so
    is the nested optional `address.ward`; the provider receives exactly the
    rendered schema and `strict: true` on the function."""
    pinned, _ = lead_tools(stack(), STRICT)

    [sent] = await sent_to_provider(pinned)

    rendered = render_input_schema(LEAD_INPUT, STRICT)
    assert as_bytes(sent["parameters"]) == as_bytes(rendered)
    assert sent["strict"] is True
    assert pinned.strict is True
    properties = rendered["properties"]
    assert rendered["required"] == list(LEAD_INPUT["properties"])
    assert properties["note"] == {"type": ["string", "null"]}
    assert properties["lead_id"] == {"type": "integer", "description": "Mã lead"}
    address = properties["address"]
    assert address["type"] == ["object", "null"]
    assert address["required"] == ["city", "ward"]
    assert address["properties"]["ward"] == {"type": ["string", "null"]}
    assert address["properties"]["city"] == {"type": "string"}
    assert properties["stage"] == {"enum": ["new", "won", None]}
    item = properties["tags"]["items"]
    assert item["required"] == ["label", "by"]
    assert item["additionalProperties"] is False
    assert item["properties"]["by"] == {"type": ["string", "null"]}


async def test_a_plain_route_sends_the_original_schema_and_no_strict_flag() -> None:
    """R4.6 at the provider: no `strict` key at all, and the schema as the
    tenant wrote it (the tool's description aside, which LangChain lifts)."""
    pinned, _ = lead_tools(stack(), PLAIN)

    [sent] = await sent_to_provider(pinned)

    assert "strict" not in sent
    assert pinned.strict is False
    assert sent["parameters"] == LEAD_INPUT


async def test_a_null_for_an_optional_key_is_dropped_before_the_executor() -> None:
    """R4.4, step 3: `note: null` and `address.ward: null` reach the executor
    as absent keys, and the call runs."""
    pinned, recorder = lead_tools(stack(), STRICT)

    reply = await call_with(
        pinned,
        {
            "lead_id": 7,
            "note": None,
            "amount": None,
            "score": None,
            "email": None,
            "stage": None,
            "address": {"city": "Huế", "ward": None},
            "tags": [{"label": "vip", "by": None}],
        },
    )

    assert recorder.payloads == [
        {"lead_id": 7, "address": {"city": "Huế"}, "tags": [{"label": "vip"}]}
    ]
    assert "lead A" in str(reply.content)


async def test_a_null_for_a_required_key_still_reaches_the_executor_and_is_refused() -> None:
    """R4.4, R1.1: `lead_id: null` is not dropped; `validation_failed`, and
    no handler runs."""
    pinned, recorder = lead_tools(stack(), STRICT)

    with pytest.raises(DomainError) as refused:
        await call_with(pinned, {"lead_id": None, "note": None, "address": None})

    assert refused.value.code == "validation_failed"
    assert {"path": "lead_id", "keyword": "type"} in refused.value.details["errors"]  # type: ignore[operator]
    assert recorder.payloads == []


async def test_a_plain_tool_keeps_the_null_and_the_executor_refuses_it() -> None:
    """Why step 3 is there: without it, the `note: null` a strict model must
    send is refused by the original schema (R1.1)."""
    pinned, recorder = lead_tools(stack(), PLAIN)

    with pytest.raises(DomainError) as refused:
        await call_with(pinned, {"lead_id": 7, "note": None})

    assert {"path": "note", "keyword": "type"} in refused.value.details["errors"]  # type: ignore[operator]
    assert recorder.payloads == []


async def test_without_numeric_bounds_the_model_sees_no_minimum_and_the_executor_still_does() -> (
    None
):
    """R4.4: no `minimum` in what the provider receives; `amount: -5` is
    still refused by the executor against the original schema."""
    pinned, recorder = lead_tools(stack(), STRICT)

    [sent] = await sent_to_provider(pinned)
    assert "minimum" not in json.dumps(sent["parameters"])
    assert "maximum" not in json.dumps(sent["parameters"])

    with pytest.raises(DomainError) as refused:
        await call_with(pinned, {"lead_id": 7, "amount": -5})
    assert refused.value.code == "validation_failed"
    assert {"path": "amount", "keyword": "minimum"} in refused.value.details["errors"]  # type: ignore[operator]
    assert recorder.payloads == []


def test_numeric_bounds_keep_minimum_and_maximum_in_the_strict_schema() -> None:
    amount = render_input_schema(LEAD_INPUT, BOUNDED)["properties"]["amount"]
    assert amount == {"type": ["number", "null"], "minimum": 0, "maximum": 1000}


@pytest.mark.parametrize("capabilities", [STRICT, BOUNDED])
def test_keywords_a_strict_schema_does_not_carry_stay_out_of_it(
    capabilities: ModelCapabilities,
) -> None:
    """R4.4: `maxLength`, `format`, `exclusiveMinimum`, `multipleOf` never
    reach the strict form; the plain form keeps every one."""
    strict = json.dumps(render_input_schema(LEAD_INPUT, capabilities))
    plain = json.dumps(render_input_schema(LEAD_INPUT, PLAIN))
    for keyword in DROPPED:
        assert f'"{keyword}"' not in strict
        assert f'"{keyword}"' in plain


@pytest.mark.parametrize(("ceiling", "strict"), [(3, True), (2, False)])
async def test_past_max_strict_tools_every_tool_is_plain(ceiling: int, strict: bool) -> None:
    """R4.4: three tools on a route allowing three are all strict; allowing
    two, all three are plain and the provider is told no `strict`."""
    capabilities = STRICT.model_copy(update={"max_strict_tools": ceiling})
    pinned, _ = lead_tools(stack(), capabilities, "lead.update", "lead.tag", "lead.close")

    sent = await sent_to_provider(pinned)

    assert pinned.strict is strict
    assert len(sent) == 3
    expected = render_input_schema(LEAD_INPUT, STRICT) if strict else LEAD_INPUT
    for function in sent:
        assert function["parameters"] == expected
        assert function.get("strict") is (True if strict else None)


def test_an_unset_ceiling_is_no_ceiling() -> None:
    assert turn_capabilities(STRICT, 40).strict_tools is True
    assert turn_capabilities(PLAIN, 1).strict_tools is False


# ------------------------------------------------------------------ R4.6 --


def test_a_route_without_strict_tools_renders_the_original_schema() -> None:
    """R4.6: equal to the original and not the same object, whatever the other
    flags say; reading the flag as always strict turns this red."""
    for capabilities in (ModelCapabilities(), PLAIN):
        rendered = render_input_schema(LEAD_INPUT, capabilities)
        assert rendered == LEAD_INPUT
        assert rendered is not LEAD_INPUT


# ----------------------------------------------------- dropping the nulls --


def test_a_null_the_original_schema_accepts_is_kept() -> None:
    schema = {
        "type": "object",
        "properties": {
            "note": {"type": ["string", "null"]},
            "stage": {"enum": ["new", None]},
            "free": {},
            "picked": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "plain": {"type": "string"},
        },
        "additionalProperties": False,
    }
    sent = {"note": None, "stage": None, "free": None, "picked": None, "plain": None}

    assert drop_strict_nulls(schema, sent) == {
        "note": None,
        "stage": None,
        "free": None,
        "picked": None,
    }


def test_nulls_inside_an_any_of_object_branch_are_dropped_too() -> None:
    schema = {
        "type": "object",
        "properties": {
            "target": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}, "why": {"type": "string"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                    {"type": "string"},
                ]
            }
        },
        "additionalProperties": False,
    }

    assert drop_strict_nulls(schema, {"target": {"id": 1, "why": None}}) == {"target": {"id": 1}}
    assert drop_strict_nulls(schema, {"target": {"id": None}}) == {"target": {"id": None}}
    rendered = render_input_schema(schema, STRICT)["properties"]["target"]
    assert rendered["anyOf"][0]["properties"]["why"] == {"type": ["string", "null"]}
    assert rendered["anyOf"][-1] == {"type": "null"}
