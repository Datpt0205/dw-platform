import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, TypedDict, cast

import pytest
from fakes import NOW, FakeAuditRepo, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel

from dw_agent_runtime.adapters.chat_model import MockChatModel
from dw_agent_runtime.adapters.langchain_tools import (
    OfferedToolsOnlyMiddleware,
    PlatformToolErrorsMiddleware,
    ScopedToolsMiddleware,
    _preview,
    model_facing_name,
    platform_tools,
)
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.registry import ConfigError
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import (
    DomainError,
    InfrastructureError,
    NotFoundError,
    TenantContextMissingError,
)
from dw_kernel.ports import FixedClock, SequentialIdGenerator

pytestmark = pytest.mark.unit

COPY = load_runtime_copy(
    Path(__file__).resolve().parents[5] / "configs" / "copy" / "runtime@1.3.0.yaml"
)


class LeadInput(BaseModel):
    company: str


class LeadOutput(BaseModel):
    lead_id: str


async def handler(payload: BaseModel, run_context: RunContext) -> LeadOutput:
    return LeadOutput(lead_id=f"lead-{cast(LeadInput, payload).company}")


def make_definition(**overrides: object) -> ToolDefinition:
    defaults: dict[str, object] = {
        "name": "crm.upsert_lead",
        "version": "1.0.0",
        "description": "Tạo hoặc cập nhật lead.",
        "input_schema_ref": "contracts/tools/crm.upsert_lead@1.0.0/input.json",
        "output_schema_ref": "contracts/tools/crm.upsert_lead@1.0.0/output.json",
        "required_scopes": frozenset({"sales_chat.write"}),
        "side_effect_level": "external",
        "approval_policy": "conditional",
        "timeout_seconds": 10,
        "max_retries": 0,
        "idempotent": True,
        "data_classification": frozenset({"internal"}),
    }
    defaults.update(overrides)
    return ToolDefinition(**defaults)


def make_run_context(scopes: frozenset[str] = frozenset({"sales_chat.write"})) -> RunContext:
    return RunContext(
        run_id=uuid.UUID(int=7),
        tenant_id=uuid.UUID(int=1),
        workspace_id=uuid.UUID(int=2),
        actor_id=uuid.UUID(int=3),
        worker_id="sales_chat",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=scopes,
        trace_id="trace-1",
        # A4, stated. The approval gate used to be a function of the tool alone —
        # `always` or `critical` — and that is precisely what A4 decides. These
        # tests were written against that behaviour, so they run at the level that
        # reproduces it. Unset, the policy fails closed and every tool would ask.
        autonomy_level="A4",
        autonomy_ceiling="A4",
    )


def terminal_rows(store: FakeExecutionStore) -> list[dict[str, Any]]:
    """The rows that say how a call ended; an `external` call logs its dispatch first."""
    return [row for row in store.records if row["status"] != "dispatched"]


def make_stack(
    *definitions: ToolDefinition,
) -> tuple[ToolRegistry, ToolExecutor, FakeExecutionStore]:
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(
            RegisteredTool(
                definition=definition,
                input_model=LeadInput,
                output_model=LeadOutput,
                handler=handler,
            )
        )
    store = FakeExecutionStore()
    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=FakeUoWFactory(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
    )
    return registry, executor, store


def build_tools(registry: ToolRegistry, executor: ToolExecutor) -> list[BaseTool]:
    return platform_tools(
        registry.all_definitions(),
        registry,
        executor,
        approval_type_prefix="sales_chat.",
        copy=COPY,
    )


class ToolState(TypedDict, total=False):
    args: dict[str, Any]
    result: str


def build_graph(tool: BaseTool) -> Any:
    """Tools read the runtime and may interrupt, so they only run inside a graph."""

    async def run_tool(state: ToolState) -> ToolState:
        return {"result": await tool.ainvoke(state["args"])}

    graph: StateGraph = StateGraph(ToolState)  # type: ignore[type-arg]
    graph.add_node("run_tool", run_tool)
    graph.add_edge(START, "run_tool")
    graph.add_edge("run_tool", END)
    return graph.compile(checkpointer=InMemorySaver())


CRITICAL = {"name": "email.send", "side_effect_level": "critical", "approval_policy": "conditional"}
CONFIG: RunnableConfig = {"configurable": {"thread_id": "t-1"}}


async def call_tool(tool: BaseTool) -> Any:
    return await build_graph(tool).ainvoke(
        {"args": {"company": "Alpha"}}, CONFIG, context=make_run_context()
    )


def test_namespace_dot_is_replaced_for_the_model() -> None:
    assert model_facing_name("crm.upsert_lead") == "crm__upsert_lead"


def test_colliding_names_are_refused_at_build_time() -> None:
    registry, executor, _ = make_stack(
        make_definition(name="crm.read__account"),
        make_definition(name="crm__read.account"),
    )
    with pytest.raises(ConfigError, match="collide"):
        build_tools(registry, executor)


async def test_call_goes_through_the_executor_and_returns_validated_output() -> None:
    registry, executor, store = make_stack(make_definition())
    state = await call_tool(build_tools(registry, executor)[0])

    assert state["result"] == '{"lead_id":"lead-Alpha"}'
    assert terminal_rows(store)[0]["status"] == "succeeded"


async def test_repeating_a_side_effect_with_the_same_arguments_replays() -> None:
    registry, executor, store = make_stack(make_definition())
    tool = build_tools(registry, executor)[0]

    await call_tool(tool)
    await call_tool(tool)
    # One send and its one outcome; the repeat replays and logs no second dispatch.
    assert [record["status"] for record in store.records] == ["dispatched", "succeeded"]


async def test_a_read_tool_needs_no_idempotency_key() -> None:
    registry, executor, store = make_stack(
        make_definition(name="crm.read_account", side_effect_level="none")
    )
    await call_tool(build_tools(registry, executor)[0])

    assert terminal_rows(store)[0]["idempotency_key"] is None


async def test_a_tool_needing_approval_pauses_before_running() -> None:
    registry, executor, store = make_stack(make_definition(**CRITICAL))
    state = await call_tool(build_tools(registry, executor)[0])

    payload = state["__interrupt__"][0].value
    assert payload["approval_type"] == "sales_chat.email.send"
    assert payload["payload"] == {"company": "Alpha"}
    assert store.records == [], "nothing may run before a human decides"


class TaskInput(BaseModel):
    """Field types the stdlib JSON encoder has no answer for on its own."""

    title: str
    due_date: date
    lead_id: uuid.UUID


async def test_an_approval_payload_is_json_all_the_way_down() -> None:
    """The interrupt value is streamed to the browser and stored on the row.

    A `date` or a `UUID` reaching `json.dumps` in the SSE writer raised
    TypeError and cut the response mid-stream, after the approval row had
    already been written - the user got a transport error and no card, for
    every write tool whose arguments were not all strings.
    """

    async def task_handler(payload: BaseModel, run_context: RunContext) -> LeadOutput:
        return LeadOutput(lead_id=str(cast(TaskInput, payload).lead_id))

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=make_definition(**CRITICAL),
            input_model=TaskInput,
            output_model=LeadOutput,
            handler=task_handler,
        )
    )
    store = FakeExecutionStore()
    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=FakeUoWFactory(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
    )
    lead_id = uuid.UUID(int=11)

    state = await build_graph(build_tools(registry, executor)[0]).ainvoke(
        {"args": {"title": "Gọi lại", "due_date": "2026-08-20", "lead_id": str(lead_id)}},
        CONFIG,
        context=make_run_context(),
    )

    payload = state["__interrupt__"][0].value
    assert payload["payload"] == {
        "title": "Gọi lại",
        "due_date": "2026-08-20",
        "lead_id": str(lead_id),
    }
    json.dumps(payload)


async def test_a_tool_whose_argument_is_a_reference_can_show_what_it_will_write() -> None:
    """`email.save_to_record` takes an artifact id and nothing else, on purpose,
    so the body cannot drift between the card and the record. That left the card
    asking a human to authorize a write with a UUID as the only thing on it."""

    async def preview(payload: BaseModel, run_context: RunContext) -> dict[str, str]:
        return {"subject": f"Chào {cast(LeadInput, payload).company}", "body": "..."}

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=make_definition(**CRITICAL),
            input_model=LeadInput,
            output_model=LeadOutput,
            handler=handler,
            approval_preview=preview,
        )
    )
    store = FakeExecutionStore()
    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=FakeUoWFactory(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
    )

    state = await call_tool(build_tools(registry, executor)[0])

    payload = state["__interrupt__"][0].value
    assert payload["preview"] == {"subject": "Chào Alpha", "body": "..."}
    assert payload["payload"] == {"company": "Alpha"}


async def test_a_tool_without_a_preview_carries_no_preview_key() -> None:
    """Most tools are their own description; an empty section would be noise."""
    registry, executor, _ = make_stack(make_definition(**CRITICAL))
    state = await call_tool(build_tools(registry, executor)[0])

    assert "preview" not in state["__interrupt__"][0].value


async def test_approving_resumes_and_runs_the_tool() -> None:
    registry, executor, store = make_stack(make_definition(**CRITICAL))
    graph = build_graph(build_tools(registry, executor)[0])
    context = make_run_context()
    await graph.ainvoke({"args": {"company": "Alpha"}}, CONFIG, context=context)

    state = await graph.ainvoke(
        Command(resume={"approved": True, "comment": "ok"}), CONFIG, context=context
    )

    assert state["result"] == '{"lead_id":"lead-Alpha"}'
    assert terminal_rows(store)[0]["status"] == "succeeded"


# ------------------------------------------------------------ tool failure --

READ = {"name": "crm.read_account", "side_effect_level": "none"}
# What the error middleware is keyed on. Only the NAME matters to it - it maps
# the model-facing spelling back to the dotted one - so the retry and ceiling
# overrides some tests pass do not need a second entry here.
FAILING_DEFINITIONS = (make_definition(**READ),)


def make_failing_stack(
    exc: Exception, **overrides: object
) -> tuple[list[BaseTool], FakeExecutionStore, FakeAuditRepo]:
    async def failing(payload: BaseModel, run_context: RunContext) -> LeadOutput:
        raise exc

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=make_definition(**overrides),
            input_model=LeadInput,
            output_model=LeadOutput,
            handler=failing,
        )
    )
    store = FakeExecutionStore()
    uow_factory = FakeUoWFactory()
    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=uow_factory,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
    )
    return build_tools(registry, executor), store, uow_factory.audit_repo


TOOL_CALL_ID = "call-1"


async def call_through_agent(tools: list[BaseTool]) -> ToolMessage:
    """Run one tool the way production does: inside an agent, behind `ToolNode`.

    `call_tool` above drives the coroutine from a hand-rolled node, which is
    fine for asserting what a tool RETURNS but says nothing about what happens
    when one raises - `ToolNode`'s error handling is the whole subject here, and
    that hand-rolled node does not have any.
    """
    model = MockChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": tools[0].name, "args": {"company": "Alpha"}, "id": TOOL_CALL_ID}
                ],
            ),
            AIMessage(content="Xong."),
        ],
        mock_reply="[mock]",
    )
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=tools,
        middleware=[PlatformToolErrorsMiddleware(FAILING_DEFINITIONS, copy=COPY)],
        context_schema=RunContext,
    )
    state = await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())
    return next(m for m in state["messages"] if isinstance(m, ToolMessage))


async def test_a_business_refusal_reaches_the_model_instead_of_ending_the_run() -> None:
    """The failure this guards: a streamed answer cut mid-flight.

    The front door has already sent its headers by the time a tool runs, so an
    exception escaping here cannot become an error response - the connection
    just dies and the user sees a transport error for a business outcome.
    """
    tools, _, _ = make_failing_stack(NotFoundError("account not found"), **READ)

    message = await call_through_agent(tools)

    assert message.status == "error"
    assert "crm.read_account" in message.text()
    assert "not_found" in message.text()
    assert "account not found" in message.text()


async def test_a_business_refusal_is_recorded_and_audited() -> None:
    """It used to escape the executor's loop entirely, leaving no trace."""
    tools, store, audit = make_failing_stack(NotFoundError("account not found"), **READ)

    await call_through_agent(tools)

    assert terminal_rows(store)[0]["status"] == "failed"
    assert terminal_rows(store)[0]["error"] == "NotFoundError"
    assert [event.action for event in audit.events] == ["tool.failed"]


async def test_the_error_details_are_never_handed_to_the_model() -> None:
    """``details`` carries whatever the raiser put there; only code and message go out."""
    tools, _, _ = make_failing_stack(
        NotFoundError("account not found", details={"account_id": "0e5f-secret"}), **READ
    )

    message = await call_through_agent(tools)

    assert "0e5f-secret" not in message.text()


async def test_a_business_refusal_is_not_retried() -> None:
    """Re-reading the same absent row costs a turn and returns the same answer."""
    tools, store, _ = make_failing_stack(NotFoundError("account not found"), **READ, max_retries=3)

    await call_through_agent(tools)

    assert terminal_rows(store)[0]["attempts"] == 1


async def test_an_upstream_failure_reaches_the_model_instead_of_ending_the_run() -> None:
    """Reverses the rule this file held until runtime copy 1.2.0.

    The old reasoning was sound and priced one side only: telling the model "it
    did not work" invites it to reassure the user that nothing is wrong. What
    it bought instead was the death of the WHOLE turn - the front door has
    already sent its headers, so the person got a transport error in place of
    an answer, and a graph that persists the turn in a last node never reached
    it either, so the transcript kept their question and nothing else.

    A model that phrases a hiccup clumsily is cheaper than that, and the
    clumsiness is what `tool_unavailable_template` exists to prevent: it says in
    so many words that this is NOT a lookup result.
    """
    tools, _, _ = make_failing_stack(InfrastructureError("gateway unreachable"), **READ)

    message = await call_through_agent(tools)

    assert message.status == "error"
    assert "upstream_unavailable" in message.text()
    # The other template's wording must NOT appear: reporting a dead dependency
    # as a real result is the specific mistake being guarded against.
    assert "kết quả thật" not in message.text()


async def test_a_crashing_tool_hands_over_its_type_and_not_its_message() -> None:
    """An untyped failure's message is the library's, not ours.

    Paths, SQL and internal hostnames travel in it, and this string goes into
    the model's context and from there onto somebody's screen.
    """
    tools, _, _ = make_failing_stack(
        TypeError("connect to 10.0.0.5 failed: password=hunter2"), **READ
    )

    message = await call_through_agent(tools)

    assert message.status == "error"
    assert "hunter2" not in message.text()
    assert "10.0.0.5" not in message.text()


async def test_a_missing_tenant_context_still_ends_the_run() -> None:
    """A typed error, but not one the model may paper over: the wiring is broken.

    Isolation is the one property this system may not degrade, so this stays
    fatal even though nearly everything else no longer is - a model told to
    carry on would carry on inside a broken security context.
    """
    tools, _, _ = make_failing_stack(TenantContextMissingError("no tenant bound"), **READ)

    with pytest.raises(TenantContextMissingError):
        await call_through_agent(tools)


async def test_rejecting_tells_the_model_and_runs_nothing() -> None:
    registry, executor, store = make_stack(make_definition(**CRITICAL))
    graph = build_graph(build_tools(registry, executor)[0])
    context = make_run_context()
    await graph.ainvoke({"args": {"company": "Alpha"}}, CONFIG, context=context)

    state = await graph.ainvoke(
        Command(resume={"approved": False, "comment": "sai khách hàng"}), CONFIG, context=context
    )

    assert "từ chối" in state["result"] and "sai khách hàng" in state["result"]
    assert store.records == []


def build_agent(registry: ToolRegistry, executor: ToolExecutor) -> tuple[Any, MockChatModel]:
    model = MockChatModel(responses=[AIMessage(content="Xong.")], mock_reply="[mock]")
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=build_tools(registry, executor),
        middleware=[ScopedToolsMiddleware(registry.all_definitions())],
        context_schema=RunContext,
    )
    return agent, model


async def test_the_model_is_only_offered_tools_the_run_can_call() -> None:
    registry, executor, _ = make_stack(
        make_definition(),
        make_definition(name="crm.delete_account", required_scopes=frozenset({"crm.admin"})),
    )
    agent, model = build_agent(registry, executor)

    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert model.bound_tool_names == ["crm__upsert_lead"]


class _Builtin(BaseTool):
    """Stands in for a tool the harness installs without any worker asking.

    deepagents 0.7.5 offers eight of these (`ls`, `read_file`, `write_file`,
    `edit_file`, `glob`, `grep`, `execute`, `task`). Reproduced here rather than
    imported so this test keeps meaning if the library's list changes.
    """

    name: str = "write_file"
    description: str = "Ghi một tệp."

    def _run(self, *args: Any, **kwargs: Any) -> str:
        return "ghi xong"


def build_guarded_agent(
    registry: ToolRegistry, executor: ToolExecutor
) -> tuple[Any, MockChatModel]:
    model = MockChatModel(responses=[AIMessage(content="Xong.")], mock_reply="[mock]")
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=[*build_tools(registry, executor), _Builtin()],
        middleware=[
            OfferedToolsOnlyMiddleware(registry.all_definitions()),
            ScopedToolsMiddleware(registry.all_definitions()),
        ],
        context_schema=RunContext,
    )
    return agent, model


async def test_a_tool_no_worker_offered_never_reaches_the_model() -> None:
    """The hole ScopedToolsMiddleware cannot close.

    An undeclared tool looks up to an EMPTY required-scope set, and
    `frozenset() <= scopes` is true for every scope set — so scope filtering
    alone waves through exactly the tools nobody authorised.
    """
    registry, executor, _ = make_stack(make_definition())
    agent, model = build_guarded_agent(registry, executor)

    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert model.bound_tool_names == ["crm__upsert_lead"]
    assert "write_file" not in model.bound_tool_names


async def test_scope_filtering_alone_would_have_let_it_through() -> None:
    """Pins the reason the second middleware exists, so removing it fails here."""
    registry, executor, _ = make_stack(make_definition())
    model = MockChatModel(responses=[AIMessage(content="Xong.")], mock_reply="[mock]")
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=[*build_tools(registry, executor), _Builtin()],
        middleware=[ScopedToolsMiddleware(registry.all_definitions())],
        context_schema=RunContext,
    )

    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert "write_file" in model.bound_tool_names


async def test_a_todo_tool_nobody_offered_is_hidden_like_any_other() -> None:
    """`write_todos` used to be allowlisted for a TodoListMiddleware the platform
    never installs: `create_agent` adds no tool (measured on deepagents 0.7.15).
    An allowance for a tool nothing offers is a door nobody watches, so it is
    hidden like every other tool outside the toolset (runtime-hardening R6.6)."""

    class _Todos(_Builtin):
        name: str = "write_todos"

    registry, executor, _ = make_stack(make_definition())
    model = MockChatModel(responses=[AIMessage(content="Xong.")], mock_reply="[mock]")
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=[*build_tools(registry, executor), _Todos()],
        middleware=[OfferedToolsOnlyMiddleware(registry.all_definitions())],
        context_schema=RunContext,
    )

    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert sorted(model.bound_tool_names) == ["crm__upsert_lead"]


async def test_two_versions_of_one_tool_coexist_and_only_the_pinned_one_is_offered() -> None:
    """A registry holds every version a host loaded; a toolset picks one.

    Both versions collapse to the same model-facing name, so offering both used
    to abort agent construction outright.
    """
    registry, executor, _ = make_stack(
        make_definition(version="1.0.0"),
        make_definition(version="2.0.0", required_scopes=frozenset({"crm.admin"})),
    )
    offered = registry.definitions_for([("crm.upsert_lead", "2.0.0")])
    model = MockChatModel(responses=[AIMessage(content="Xong.")], mock_reply="[mock]")
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=platform_tools(
            offered, registry, executor, approval_type_prefix="sales_chat.", copy=COPY
        ),
        middleware=[ScopedToolsMiddleware(offered)],
        context_schema=RunContext,
    )

    # The scope map follows the pinned version, so 1.0.0's scopes cannot govern
    # the offer: a run holding only sales_chat.write is shown nothing.
    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())
    assert model.bound_tool_names == []

    await agent.ainvoke(
        {"messages": [HumanMessage("chào")]},
        context=make_run_context(scopes=frozenset({"crm.admin"})),
    )
    assert model.bound_tool_names == ["crm__upsert_lead"]


async def test_a_pin_naming_an_unregistered_tool_fails_at_build_time() -> None:
    registry, _executor, _ = make_stack(make_definition())
    with pytest.raises(NotFoundError):
        registry.definitions_for([("crm.upsert_lead", "9.9.9")])


# ---- a preview that cannot answer must not kill the turn --------------------


def _registered(preview: object) -> RegisteredTool:
    return RegisteredTool(
        definition=make_definition(approval_policy="always"),
        input_model=LeadInput,
        output_model=LeadOutput,
        handler=handler,
        approval_preview=cast(Any, preview),
    )


async def test_a_failing_approval_preview_still_produces_a_card() -> None:
    """Measured on the running UI, on the most ordinary case there is.

    `lead_scoring.rescore`'s preview reads the score it is about to replace. On
    a lead nobody had scored yet that read refused, the refusal escaped
    `_ask_human`, and the whole turn died with "Trợ lý gặp lỗi giữa chừng" - no
    card, no explanation, nothing the user could do about it. A preview is
    decoration on top of the arguments; it must never be able to do that.
    """

    async def refuses(payload: BaseModel, run_context: RunContext) -> dict[str, str]:
        raise DomainError("nothing to preview here")

    shown = await _preview(_registered(refuses), LeadInput(company="Beta"), make_run_context())

    assert shown == {"preview_unavailable": "nothing to preview here"}


async def test_a_preview_that_works_is_passed_through_untouched() -> None:
    async def answers(payload: BaseModel, run_context: RunContext) -> dict[str, str]:
        return {"lead": "Beta", "current_score": "6"}

    shown = await _preview(_registered(answers), LeadInput(company="Beta"), make_run_context())

    assert shown == {"lead": "Beta", "current_score": "6"}


async def test_an_unexpected_preview_bug_still_fails_loudly() -> None:
    """Narrow on purpose: a crash nobody predicted is not a degraded card."""

    async def explodes(payload: BaseModel, run_context: RunContext) -> dict[str, str]:
        raise ZeroDivisionError("a real bug")

    with pytest.raises(ZeroDivisionError):
        await _preview(_registered(explodes), LeadInput(company="Beta"), make_run_context())


# A provider-native tool: the provider runs it, so it never passes ToolExecutor.
_PROVIDER_NATIVE = {"type": "web_search_preview"}


@pytest.mark.parametrize("middleware_kind", ["offered", "scoped"])
async def test_an_entry_that_is_not_a_platform_tool_never_reaches_the_model(
    middleware_kind: str,
) -> None:
    """runtime-hardening R6.4: each middleware drops it on its own."""
    registry, executor, _ = make_stack(make_definition())
    definitions = registry.all_definitions()
    middleware = (
        OfferedToolsOnlyMiddleware(definitions)
        if middleware_kind == "offered"
        else ScopedToolsMiddleware(definitions)
    )
    model = MockChatModel(responses=[AIMessage(content="Xong.")], mock_reply="[mock]")
    agent = create_agent(  # type: ignore[misc]
        model=model,
        tools=[*build_tools(registry, executor), _PROVIDER_NATIVE],
        middleware=[middleware],
        context_schema=RunContext,
    )

    await agent.ainvoke({"messages": [HumanMessage("chào")]}, context=make_run_context())

    assert model.bound_tool_names == ["crm__upsert_lead"]
    assert all(isinstance(tool, BaseTool) for tool in model.bound_tools)
