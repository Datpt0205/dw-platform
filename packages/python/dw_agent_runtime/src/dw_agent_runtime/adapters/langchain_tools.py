"""Exposes registered platform tools to a LangChain agent.

Every call still goes through ``ToolExecutor``, so authorization, approval
policy, idempotency, timeout, retry and audit apply exactly as they do to a
workflow node.

Which tools an agent offers comes from its worker's toolset (``configs/toolsets``),
resolved before either function is called. Neither reads the registry wholesale:
a registry holds every version a host loaded, and offering two versions of one
tool is not something a model can act on — both collapse to the same
model-facing name.

Tools are built once per agent, not per run: an agent is compiled once and
reused, so each call reads its ``RunContext`` from the LangGraph runtime instead
of closing over one. ``ScopedToolsMiddleware`` then hides the tools a run has no
scope for — a model cannot misuse a tool it was never shown, and the executor
still refuses if one slips through.

A tool that needs a human pauses the run from inside the call, in the payload
shape ``LangGraphWorkflowRunner`` turns into an ApprovalRequest. Nothing has
happened yet at that point, so re-running the call on resume is safe.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
    ToolErrorMiddleware,
)
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.runtime import get_runtime
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor, canonical_hash
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.registry import ConfigError
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import (
    DomainError,
    DWError,
    ErrorCode,
    InfrastructureError,
    NotFoundError,
    PermissionDeniedError,
)
from dw_observability.redaction import redact_mapping

_NAME_SEPARATOR = "__"

logger = logging.getLogger("dw_agent_runtime.langchain_tools")


def platform_tools_only(tools: Sequence[Any]) -> list[BaseTool]:
    """Drop every entry that is not a `BaseTool`, logging its type and nothing else.

    A dict or a provider-native tool runs on the provider's side, outside
    `ToolExecutor`, and so outside authorization, idempotency and audit
    (ADR-0116 decision 3). Both middlewares below used to let any non-`BaseTool`
    entry through on the assumption that none would arrive; nothing stopped one
    from arriving.
    """
    kept: list[BaseTool] = []
    for tool in tools:
        if isinstance(tool, BaseTool):
            kept.append(tool)
        else:
            logger.warning(
                "dropped a tool entry that is not a platform tool",
                extra={"entry_type": type(tool).__name__},
            )
    return kept


# Failures where the tool ANSWERED and the answer was a refusal: the row is not
# there, the arguments were wrong, the key collides. Calling again with the same
# arguments returns the same thing, so the model is told exactly that.
#
# The set no longer decides whether the run survives - `PlatformToolErrorsMiddleware`
# does, and almost everything survives now. It decides which of the two things
# the model is told, which is a different and much smaller question.
_ANSWERABLE_ERRORS = frozenset(
    {
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.CONFLICT,
        ErrorCode.PERMISSION_DENIED,
        ErrorCode.ENTITLEMENT_DENIED,
        ErrorCode.IDEMPOTENCY_CONFLICT,
    }
)


def model_facing_name(tool_name: str) -> str:
    """Providers accept ``[a-zA-Z0-9_-]`` only, so the namespace dot cannot survive."""
    return tool_name.replace(".", _NAME_SEPARATOR)


def platform_tools(
    definitions: Sequence[ToolDefinition],
    registry: ToolRegistry,
    executor: ToolExecutor,
    *,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> list[BaseTool]:
    tools: list[BaseTool] = []
    seen: set[str] = set()
    for definition in definitions:
        exposed = model_facing_name(definition.name)
        if exposed in seen:
            raise ConfigError(
                "two tools collide once the namespace dot is replaced",
                details={"tool": definition.name, "exposed_as": exposed},
            )
        seen.add(exposed)
        tools.append(_build_tool(definition, registry, executor, approval_type_prefix, copy))
    return tools


# Two failures that must still END the run rather than become an answer.
#
# `TENANT_CONTEXT_MISSING` is a run with no verified tenant. Isolation is the
# one property this system is not allowed to degrade, and a model told "that
# did not work, carry on" would carry on inside a broken security context.
#
# `APPROVAL_REQUIRED` reaching here means the gate was bypassed - the tool was
# called without the pause that authorizes it. Nothing ran, but reporting it as
# an ordinary hiccup would let the model imply to a person that the write is
# merely pending, when the wiring that asks them is in fact broken.
#
# Both are "our own plumbing is wrong", not "the world is unavailable", and
# neither is a thing the model can do anything about.
_UNANSWERABLE_ERRORS = frozenset(
    {
        ErrorCode.TENANT_CONTEXT_MISSING,
        ErrorCode.APPROVAL_REQUIRED,
    }
)


class PlatformToolErrorsMiddleware(ToolErrorMiddleware):
    """A tool that breaks answers the model instead of killing the turn.

    The turn used to die. `create_agent` builds its `ToolNode` without
    `handle_tool_errors`, so the default handler re-raises anything that is not
    a `ToolInvocationError`; the exception left the tools node, took the agent
    node with it and then the whole graph. For a conversational worker that
    the `persist` node never ran, so the half-written answer and every tool
    result of that turn never reached the transcript - a person typed a
    question, reloaded, and found only their own message.

    The cost of the old behaviour was measured twice before this existed, and
    patched twice, one tool at a time: `intel.search_web` when a Serper account
    ran out of credit (every web question ended in "trợ lý gặp lỗi giữa chừng",
    INCLUDING the part CRM data alone could have answered), and
    `lead_scoring.rescore`'s approval preview on a lead nobody had scored yet.
    Every tool added since was one more way to end a turn. This is that fix
    made general.

    What the model is told, and why the two sentences differ, is in
    `configs/copy/runtime@1.3.0.yaml`: a typed refusal is a real result it must
    report as fact, while a timeout or a crash is explicitly NOT a lookup
    result - answering "no customers found" after one is the failure this
    guards against.

    Deliberately NOT a `try/except` inside the tool, and the difference is
    load-bearing: `ToolErrorMiddleware` re-raises `GraphBubbleUp`, so the
    `interrupt()` that pauses for a human passes straight through. A hand-rolled
    `except Exception` would swallow it and break approvals. `CancelledError` is
    a `BaseException` and passes through too, so a reader closing their tab
    still stops the run.

    Returning `None` re-raises, which is how `_UNANSWERABLE_ERRORS` stays fatal.
    """

    def __init__(self, definitions: Sequence[ToolDefinition], *, copy: RuntimeCopy) -> None:
        # Sync handler: it serves the async path too, and there is nothing here
        # to await.
        super().__init__(on_error=self._on_error)
        # Back to the name a person would recognise. The model calls
        # `crm__read_account`; the sentence should say `crm.read_account`.
        self._dotted = {model_facing_name(d.name): d.name for d in definitions}
        self._copy = copy

    def _on_error(self, exc: Exception, request: ToolCallRequest) -> str | None:
        exposed = request.tool_call["name"]
        # A name absent from the map is a harness tool - `read_file`, `execute`,
        # `task`. They end a turn exactly as easily, and they report under the
        # only name they have.
        tool = self._dotted.get(exposed, exposed)
        if isinstance(exc, DWError):
            if exc.code in _UNANSWERABLE_ERRORS:
                return None
            if exc.code in _ANSWERABLE_ERRORS:
                return self._copy.tool_failed(tool, exc.code, exc.message)
            return self._copy.tool_unavailable(tool, exc.code)
        # Untyped: the class name is the only part safe to pass on. Whatever the
        # library put in the message is its own - a path, a query, a hostname -
        # and this string ends up in the model's context and then on a screen.
        return self._copy.tool_unavailable(tool, type(exc).__name__)


class OneApprovalPerStepMiddleware(AgentMiddleware):
    """Lets at most one approval-gated call per model step reach `interrupt()`.

    Everything downstream of a pause assumes there is exactly one: the run row
    has one `approval_request_id`, the runner and the chat stream both read
    `interrupts[0]`, the panel shows one card, and resume sends a bare
    `Command(resume=...)` that carries no interrupt id. That assumption held
    only as long as the model asked for one gated tool at a time.

    It did not. `create_agent` dispatches every tool call of a step as its own
    `Send` task, sibling interrupts are merged into one `GraphInterrupt`, and
    the second call raised a pause nobody was ever shown - no row, no card. On
    resume the bare payload is consumed by whichever task reaches `interrupt()`
    first, so the decision a person made about one card could run the other
    tool. Reproduced on 2026-09-11; the prompt had been asking the model not to
    do this, which lowers the odds and guarantees nothing.

    So the invariant is enforced here, in code: only the first gated call of a
    step runs; each later one is answered with a deferral that tells the model
    to call again once the pending one is decided. "First" is position in the
    step's AIMessage, which every sibling task reads identically and which
    does not change when the node re-runs on resume - so the call that paused
    is the one that receives the decision.

    A `ToolMessage` rather than an exception: nothing failed, and the tool
    error path would say "do not call this again", which is the opposite of
    what the model must do.
    """

    def __init__(
        self,
        definitions: Sequence[ToolDefinition],
        *,
        copy: RuntimeCopy,
        policy: AutonomyApprovalPolicy,
    ) -> None:
        super().__init__()
        if copy.approval_deferred_template is None:
            raise ConfigError(
                f"runtime copy {copy.version} has no approval_deferred_template; "
                "load runtime@1.3.0 or later"
            )
        # Every offered tool, not only the gated ones: which are gated is no longer
        # a property of the tool. This middleware used to compute that set here,
        # once, when the agent was built — and an agent is compiled once per
        # process, so one frozen set was served to every tenant at every level.
        self._offered = {model_facing_name(d.name): d for d in definitions}
        self._policy = policy
        self._copy = copy

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        # Decided for THIS run, every call. The same tool is gated for an A1 run and
        # free for an A3 one in the same process.
        run_context = get_runtime(RunContext).context
        gated = {
            exposed_name: definition.name
            for exposed_name, definition in self._offered.items()
            if self._policy.decide(definition, run_context)
        }
        exposed = request.tool_call["name"]
        if exposed not in gated:
            return await handler(request)
        call_id = request.tool_call["id"]
        first = _first_gated_call(request.state, call_id, gated)
        if first is None or first["id"] == call_id:
            return await handler(request)
        return ToolMessage(
            content=self._copy.approval_deferred(gated[exposed], gated[first["name"]]),
            tool_call_id=call_id,
            name=exposed,
        )


def _first_gated_call(
    state: object, call_id: str | None, gated: Mapping[str, str]
) -> ToolCall | None:
    """The first gated call of the step this call belongs to, in model order."""
    messages = state.get("messages", ()) if isinstance(state, Mapping) else ()
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        calls = message.tool_calls
        if not any(call["id"] == call_id for call in calls):
            continue
        return next((call for call in calls if call["name"] in gated), None)
    return None


class ScopedToolsMiddleware(AgentMiddleware):
    """Offers the model only the tools the current run is authorized to call.

    Keyed on the same resolved definitions the tool list was built from, so the
    scopes checked here are the ones declared by the version actually offered.
    """

    def __init__(self, definitions: Sequence[ToolDefinition]) -> None:
        super().__init__()
        self._required = {
            model_facing_name(definition.name): definition.required_scopes
            for definition in definitions
        }

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        scopes = get_runtime(RunContext).context.scopes
        allowed: list[BaseTool | dict[str, Any]] = [
            tool
            for tool in platform_tools_only(request.tools)
            if self._required.get(tool.name, frozenset()) <= scopes
        ]
        return await handler(request.override(tools=allowed))


# Kiểu tệp mà nhà cung cấp nhận trong một khối `file`. Danh sách hẹp có chủ ý:
# thứ không nằm ở đây sẽ bị từ chối ở phía họ, và một khối hỏng làm hỏng CẢ
# request chứ không chỉ riêng nó.
_MODEL_READABLE_FILE_MIMES = frozenset(
    {
        "application/pdf",
        "application/json",
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
    }
)

# Cái nhà cung cấp trả về khi không đoán ra kiểu tệp, và cũng là cái làm cả
# request đổ.
_UNKNOWN_MIME = "application/octet-stream"


def _file_block_mime(block: object) -> str | None:
    """MIME của một khối `file`, hoặc `None` nếu đây không phải khối file.

    Hai hình dạng vì hai đời API: `{"type": "file", "mime_type": ...}` của
    LangChain, và `{"file_data": "data:<mime>;base64,..."}` mà provider dựng ra.
    """
    if not isinstance(block, dict):
        return None
    if block.get("type") not in {"file", "input_file"}:
        return None
    mime = block.get("mime_type") or block.get("mimeType")
    if isinstance(mime, str) and mime:
        return mime
    data = block.get("file_data") or block.get("data")
    if isinstance(data, str) and data.startswith("data:"):
        return data[5:].split(";", 1)[0] or None
    return None


class UnreadableFilesMiddleware(AgentMiddleware):
    """Thay khối tệp mà mô hình không đọc được bằng một câu nói rõ điều đó.

    Đo được 2026-09-08 trên stack thật: `document.save` ghi một .docx vào thư
    mục làm việc, mô hình gọi `read_file` lên chính tệp đó, middleware
    filesystem trả về một khối file và đoán MIME là `application/octet-stream`.
    Nhà cung cấp từ chối NGUYÊN CẢ REQUEST:

        openai.BadRequestError: Invalid file data: 'input[113].output[0].file_data'
        ... unsupported MIME type 'application/octet-stream'

    Đây không phải một tool hỏng mà mô hình trả lời thay được: lỗi nổ ở chính
    lời gọi model, nên lượt chết và người dùng hỏi một câu rồi không nhận được
    gì. Một khối trong hàng trăm làm hỏng tất cả.

    Chỗ sửa phải ở đây chứ không ở quyền filesystem. `deepagents` từ chối dựng
    middleware có cả `execute` lẫn luật đụng ra ngoài route - và nó đúng: khi mô
    hình có shell, cấm `read_file` một đường dẫn là hình thức, vì `cat` không đi
    qua file tool nào cả. Còn đây là chỗ duy nhất mọi nội dung đi qua trước khi
    rời máy.

    Thay chứ không xoá: mô hình cần biết nó vừa đọc phải cái gì, nếu không nó
    sẽ đọc lại.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        cleaned = [_without_unreadable_files(message) for message in request.messages]
        return await handler(request.override(messages=cleaned))


def _without_unreadable_files(message: Any) -> Any:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return message

    changed = False
    kept: list[Any] = []
    for block in content:
        mime = _file_block_mime(block)
        if mime is None or mime in _MODEL_READABLE_FILE_MIMES:
            kept.append(block)
            continue
        changed = True
        name = block.get("filename") or block.get("name") if isinstance(block, dict) else None
        kept.append(
            {
                "type": "text",
                "text": (
                    f"[tệp {name or 'nhị phân'} không đọc được: kiểu {mime}. "
                    "Nội dung của nó không tới được mô hình - đừng đọc lại, và "
                    "đừng suy đoán nội dung.]"
                ),
            }
        )

    if not changed:
        return message
    # `model_copy` giữ nguyên id và metadata; dựng lại một message mới sẽ làm
    # đứt liên kết tool_call_id mà nhà cung cấp đối chiếu.
    return message.model_copy(update={"content": kept})


# Nothing is offered beyond the worker's own toolset. `write_todos` used to be
# allowed here for a TodoListMiddleware that `create_deep_agent` installs; the
# platform builds on `create_agent`, which installs no tool at all (measured on
# deepagents 0.7.15, 30/10/2026), so the allowance read a tool nothing offered.
# What `create_deep_agent` would install is listed in `agent_factory`, measured.


class OfferedToolsOnlyMiddleware(AgentMiddleware):
    """Hides every tool the worker did not actually offer.

    ScopedToolsMiddleware cannot do this. It filters by looking each tool up in
    the definitions it was built from, and an unknown tool falls back to an
    EMPTY scope set — `frozenset() <= scopes` is true for every scope set there
    is, so a tool nobody declared passes the check by not being declared. The
    two middlewares answer different questions: that one asks "may this run call
    a tool it was offered", this one asks "was it offered at all".

    Measured on the pinned deepagents 0.7.5: `create_deep_agent` hands the model
    eight builtin filesystem and shell tools regardless of the toolset. Two of
    them (`write_file`, `execute`) are a write path around ToolExecutor, which
    means around authorization, idempotency and audit.

    Not solved with a library knob because the pinned version has none: the docs
    describe `FilesystemMiddleware(tools=...)` but that parameter does not exist
    in 0.7.5, `excluded_middleware` is refused for `_REQUIRED_MIDDLEWARE`, and
    `permissions=[...]` still offers the tool and only fails on call — which is
    not the same as not offering it.
    """

    def __init__(self, definitions: Sequence[ToolDefinition]) -> None:
        super().__init__()
        self._offered = {model_facing_name(d.name) for d in definitions}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        allowed: list[BaseTool | dict[str, Any]] = [
            tool for tool in platform_tools_only(request.tools) if tool.name in self._offered
        ]
        return await handler(request.override(tools=allowed))


def _build_tool(
    definition: ToolDefinition,
    registry: ToolRegistry,
    executor: ToolExecutor,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> BaseTool:
    registered = registry.resolve(definition.name, definition.version)

    async def call(**kwargs: object) -> str:
        run_context = get_runtime(RunContext).context
        approved = False
        if executor.approval_policy.decide(definition, run_context):
            decision = await _ask_human(
                definition, registered, kwargs, run_context, approval_type_prefix, copy
            )
            if not decision.get("approved"):
                return copy.tool_rejected(definition.name, str(decision.get("comment", "")))
            approved = True

        # No failure handling here: `PlatformToolErrorsMiddleware` owns that, for
        # every tool and not only the ones built below. Two handlers would be
        # two answers to "what is the model told", and the one that fired first
        # would silently win.
        output = await executor.execute(
            name=definition.name,
            version=definition.version,
            raw_input=kwargs,
            run_context=run_context,
            idempotency_key=_idempotency_key(definition, kwargs, run_context),
            approved=approved,
        )
        return output.model_dump_json()

    return StructuredTool(
        name=model_facing_name(definition.name),
        description=definition.description,
        args_schema=registered.input_model,
        coroutine=call,
    )


async def _ask_human(
    definition: ToolDefinition,
    registered: RegisteredTool,
    arguments: dict[str, object],
    run_context: RunContext,
    approval_type_prefix: str,
    copy: RuntimeCopy,
) -> dict[str, Any]:
    """Pause for a decision, showing what the decision is about.

    Two things the card needs and the raw arguments do not give it.

    JSON: LangChain hands the coroutine values already coerced to the input
    model, so a `due_date` arrives as a `date` and a `lead_id` as a `UUID`. This
    dict is not local - it is written into the checkpoint, copied onto the
    approval row and streamed to the browser - and `json.dumps` raised TypeError
    on it mid-stream. Dumping through the tool's own model also keeps the
    streamed card and the stored row the same bytes.

    Effect: a tool whose arguments are references cannot describe itself.
    `email.save_to_record` takes an artifact id and nothing else, so the card
    asked a human to authorize writing an email into a customer record while
    showing them a UUID. `approval_preview` is how such a tool reads out what
    is about to be written; it runs before the pause, on the requester's own
    context, so it can only show what that requester could already read.
    """
    payload = registered.input_model.model_validate(arguments)
    body: dict[str, Any] = {
        "approval_type": f"{approval_type_prefix}{definition.name}",
        "reason": copy.approval_reason(definition.name),
        "tool": definition.name,
        "tool_version": definition.version,
        "payload": redact_mapping(payload.model_dump(mode="json")),
    }
    if registered.approval_preview is not None:
        body["preview"] = redact_mapping(await _preview(registered, payload, run_context))
    decision = interrupt(body)
    return decision if isinstance(decision, dict) else {"approved": bool(decision)}


async def _preview(
    registered: RegisteredTool, payload: BaseModel, run_context: RunContext
) -> dict[str, str]:
    """Build the card's preview, or say why it could not be built.

    A preview is decoration ON TOP of the arguments: it reads extra context so
    the approver is not authorizing a UUID. Letting it kill the turn inverts
    that - measured on `lead_scoring.rescore`, whose preview reads the score it
    is about to replace: on a lead never scored before, the read refused and the
    whole turn died with "Trợ lý gặp lỗi giữa chừng", no card, no way forward,
    for the single most ordinary case there is.

    So a preview that cannot answer degrades into a card that says so. The gate
    is untouched - the interrupt still happens and a person still decides - and
    the approver is told what they are NOT being shown, which is the one thing
    they must not be left to assume.

    Narrow on purpose. An unexpected exception here is a bug in the preview, and
    the run should still fail loudly rather than hand somebody a card built by
    code that crashed in a way nobody predicted.
    """
    try:
        return await registered.approval_preview(payload, run_context)  # type: ignore[misc]
    except (DomainError, NotFoundError, PermissionDeniedError, InfrastructureError) as exc:
        return {"preview_unavailable": str(exc)}


def _idempotency_key(
    definition: ToolDefinition, arguments: dict[str, object], run_context: RunContext
) -> str | None:
    """Key on what the call does, not on which attempt made it.

    A model that retries the same action produces a new tool-call id but the
    same arguments, so hashing the arguments is what actually prevents a
    duplicate side effect within a run.

    Every level except ``none``, not only the outward-facing ones. An internal
    write is still a write: `lead_scoring.propose_field_update` pauses for a
    person, and LangGraph re-runs the whole node on resume — so without a key
    the approved write would land, the node would restart, and the same field
    would be written a second time.
    """
    if definition.side_effect_level == "none":
        return None
    return f"{run_context.run_id}:{definition.name}:{canonical_hash(arguments)}"
