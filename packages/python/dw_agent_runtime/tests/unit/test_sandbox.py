"""The sandbox backend: session scoping, wire mapping, and the audit row."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx
import pytest
from fakes import NOW, FakeUoWFactory

from dw_agent_runtime.adapters.docgen_client import DocgenClient
from dw_agent_runtime.adapters.sandbox import DocgenSandbox
from dw_agent_runtime.adapters.sandbox_audit import SANDBOX_EXECUTE_ACTION, AuditedSandbox
from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import InfrastructureError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import FixedClock, SequentialIdGenerator

pytestmark = pytest.mark.unit

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = uuid.UUID("22222222-2222-2222-2222-222222222222")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
RUN = uuid.UUID("44444444-4444-4444-4444-444444444444")
THREAD = uuid.UUID("55555555-5555-5555-5555-555555555555")


def a_run(*, thread_id: uuid.UUID | None = THREAD) -> RunContext:
    return RunContext(
        run_id=RUN,
        # A real run: its tools act (tenant-config R4.3).
        run_mode="live",
        thread_id=thread_id,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        actor_id=ACTOR,
        worker_id="sales_chat",
        worker_version="1.0.0",
        channel="web",
        plan_id="plan",
        roles=frozenset({"sales"}),
        scopes=frozenset({"sales_chat.read"}),
        trace_id="trace-1",
    )


class Recorder:
    """A transport that answers with canned bodies and remembers the requests."""

    def __init__(self, *replies: dict[str, Any] | httpx.Response) -> None:
        self._replies = list(replies)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self._replies.pop(0) if self._replies else {}
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)

    @property
    def body(self) -> dict[str, Any]:
        parsed = json.loads(self.requests[-1].content)
        assert isinstance(parsed, dict)
        return parsed


def a_client(recorder: Recorder, *, token: str = "") -> DocgenClient:
    return DocgenClient(
        base_url="http://docgen:8110",
        token=token,
        client=httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler)),
    )


def a_sandbox(recorder: Recorder, *, token: str = "", **kwargs: Any) -> DocgenSandbox:
    return DocgenSandbox(a_client(recorder, token=token), run_context=a_run(), **kwargs)


# ------------------------------------------------------------------ session --


def test_the_session_is_the_conversation_not_the_turn() -> None:
    """A follow-up finds the files the previous turn wrote; that is what makes
    "shorten the risk section" an edit rather than a regeneration."""
    sandbox = a_sandbox(Recorder())

    assert sandbox.id.endswith(THREAD.hex)


def test_a_run_with_no_conversation_is_its_own_session() -> None:
    sandbox = DocgenSandbox(a_client(Recorder()), run_context=a_run(thread_id=None))

    assert sandbox.id.endswith(RUN.hex)


def test_the_session_name_carries_the_tenant() -> None:
    sandbox = a_sandbox(Recorder())

    assert sandbox.id.startswith(f"t{TENANT.hex[:8]}")


def test_the_working_directory_is_under_the_sandbox_root() -> None:
    sandbox = a_sandbox(Recorder())

    assert sandbox.root == f"/work/{sandbox.id}"


def test_used_outside_a_run_it_says_so_rather_than_guessing() -> None:
    """Guessing means picking some other run's workdir."""
    sandbox = DocgenSandbox(a_client(Recorder()))

    with pytest.raises(InfrastructureError, match="outside a LangGraph run"):
        _ = sandbox.id


# ------------------------------------------------------------------ execute --


async def test_a_command_is_posted_to_the_callers_session() -> None:
    recorder = Recorder({"output": "4\n", "exit_code": 0, "truncated": False})
    sandbox = a_sandbox(recorder)

    result = await sandbox.aexecute("python3 gen.py", timeout=45)

    assert recorder.requests[-1].url.path == f"/v1/sessions/{sandbox.id}/execute"
    assert recorder.body == {"command": "python3 gen.py", "timeout_seconds": 45}
    assert (result.output, result.exit_code, result.truncated) == ("4\n", 0, False)


async def test_no_timeout_means_the_service_decides() -> None:
    recorder = Recorder({"output": "", "exit_code": 0})
    sandbox = a_sandbox(recorder)

    await sandbox.aexecute("ls")

    assert "timeout_seconds" not in recorder.body


async def test_the_token_travels_with_the_request() -> None:
    recorder = Recorder({"output": "", "exit_code": 0})
    sandbox = a_sandbox(recorder, token="s3cret")

    await sandbox.aexecute("ls")

    assert recorder.requests[-1].headers["authorization"] == "Bearer s3cret"


async def test_a_refusal_from_the_service_is_not_read_as_output() -> None:
    recorder = Recorder(httpx.Response(401, text="invalid token"))
    sandbox = a_sandbox(recorder)

    with pytest.raises(InfrastructureError, match="refused the request"):
        await sandbox.aexecute("ls")


async def test_a_sandbox_that_does_not_answer_names_itself() -> None:
    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = DocgenClient(
        base_url="http://docgen:8110",
        client=httpx.AsyncClient(transport=httpx.MockTransport(dead)),
    )
    sandbox = DocgenSandbox(client, run_context=a_run())

    with pytest.raises(InfrastructureError, match="docgen container is running"):
        await sandbox.aexecute("ls")


# -------------------------------------------------------------------- files --


async def test_files_go_out_base64_encoded() -> None:
    recorder = Recorder({"results": [{"path": "gen.py", "error": None}]})
    sandbox = a_sandbox(recorder)

    results = await sandbox.aupload_files([("gen.py", b"print(1)")])

    sent = recorder.body["files"][0]
    assert base64.b64decode(sent["content_b64"]) == b"print(1)"
    assert results[0].error is None


async def test_files_come_back_decoded() -> None:
    payload = base64.b64encode(b"PK\x03\x04").decode()
    recorder = Recorder({"results": [{"path": "out.docx", "content_b64": payload}]})
    sandbox = a_sandbox(recorder)

    results = await sandbox.adownload_files(["out.docx"])

    assert results[0].content == b"PK\x03\x04"
    assert results[0].error is None


async def test_a_missing_file_keeps_the_services_own_word_for_it() -> None:
    recorder = Recorder({"results": [{"path": "nope.docx", "error": "file_not_found"}]})
    sandbox = a_sandbox(recorder)

    results = await sandbox.adownload_files(["nope.docx"])

    assert results[0].error == "file_not_found"


async def test_a_path_outside_the_session_is_explained_not_just_named() -> None:
    """ "invalid_path" makes a model retry the same path; naming the directory
    it may write to makes it correct itself."""
    recorder = Recorder({"results": [{"path": "/etc/passwd", "error": "invalid_path"}]})
    sandbox = a_sandbox(recorder)

    results = await sandbox.adownload_files(["/etc/passwd"])

    assert results[0].error is not None
    assert sandbox.root in results[0].error


async def test_an_unreachable_sandbox_reports_per_file_rather_than_raising() -> None:
    """`deepagents` requires batch file operations to report failures per file;
    raising here kills the turn instead of letting the model react."""

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = DocgenClient(
        base_url="http://docgen:8110",
        client=httpx.AsyncClient(transport=httpx.MockTransport(dead)),
    )
    sandbox = DocgenSandbox(client, run_context=a_run())

    results = await sandbox.aupload_files([("a.py", b"x"), ("b.py", b"y")])

    assert [r.path for r in results] == ["a.py", "b.py"]
    assert all(r.error for r in results)


# -------------------------------------------------------------------- audit --


def an_audited(recorder: Recorder) -> tuple[AuditedSandbox, FakeUoWFactory]:
    uow_factory = FakeUoWFactory()
    audited = AuditedSandbox(
        a_sandbox(recorder),
        uow_factory=uow_factory,
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        run_context=a_run(),
    )
    return audited, uow_factory


async def test_every_command_leaves_a_row_on_the_same_trail_as_the_tool_calls() -> None:
    recorder = Recorder({"output": "done", "exit_code": 0, "truncated": False})
    audited, uow_factory = an_audited(recorder)

    await audited.aexecute("python3 gen.py")

    (event,) = uow_factory.audit_repo.events
    assert event.action == SANDBOX_EXECUTE_ACTION
    assert event.tenant_id == TenantId(TENANT)
    assert event.workspace_id == WorkspaceId(WORKSPACE)
    assert event.run_id == RUN
    assert event.trace_id == "trace-1"


async def test_the_row_says_what_ran_and_how_it_ended() -> None:
    """A hash alone cannot answer "what did it run", which is the only question
    an incident review has here."""
    recorder = Recorder({"output": "boom", "exit_code": 3, "truncated": True})
    audited, uow_factory = an_audited(recorder)

    await audited.aexecute("python3 gen.py")

    details = uow_factory.audit_repo.events[0].details
    assert details["command"] == "python3 gen.py"
    assert details["exit_code"] == 3
    assert details["output_truncated"] is True
    assert len(str(details["command_sha256"])) == 64


async def test_a_long_command_is_truncated_but_still_identified() -> None:
    recorder = Recorder({"output": "", "exit_code": 0})
    audited, uow_factory = an_audited(recorder)
    command = "x" * 5000

    await audited.aexecute(command)

    details = uow_factory.audit_repo.events[0].details
    assert len(str(details["command"])) == 1000
    assert details["command_chars"] == 5000


async def test_the_row_says_no_policy_rather_than_allow() -> None:
    """No policy was evaluated. Recording "allow" would claim a gate passed."""
    recorder = Recorder({"output": "", "exit_code": 0})
    audited, uow_factory = an_audited(recorder)

    await audited.aexecute("ls")

    assert uow_factory.audit_repo.events[0].policy_decision == "no_policy"


async def test_the_command_still_returns_what_the_sandbox_said() -> None:
    recorder = Recorder({"output": "hello", "exit_code": 0, "truncated": False})
    audited, _ = an_audited(recorder)

    result = await audited.aexecute("echo hello")

    assert result.output == "hello"


def test_synchronous_execution_is_refused_rather_than_run_unaudited() -> None:
    audited, uow_factory = an_audited(Recorder())

    with pytest.raises(InfrastructureError, match="synchronous execution"):
        audited.execute("ls")

    assert uow_factory.audit_repo.events == []


async def test_a_derived_file_operation_is_recorded_too() -> None:
    """`read_file` is a shell command underneath. The trail says what executed
    in the container, not only what the model typed."""
    recorder = Recorder({"output": "hello", "exit_code": 0})
    audited, uow_factory = an_audited(recorder)

    await audited.als("/work")

    assert len(uow_factory.audit_repo.events) == 1


async def test_file_transfers_are_not_recorded() -> None:
    """They run nothing, and one row per `write_file` would bury the rows that
    matter. A file only becomes reviewable when a real tool takes it out."""
    recorder = Recorder({"results": [{"path": "gen.py", "error": None}]})
    audited, uow_factory = an_audited(recorder)

    await audited.aupload_files([("gen.py", b"print(1)")])

    assert uow_factory.audit_repo.events == []
