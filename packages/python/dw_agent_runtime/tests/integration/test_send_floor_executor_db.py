"""Integration: the Send floor at the ToolExecutor, on real PostgreSQL
(compliance-pdpl ticket 08; ADR-0124 decision 2).

R3.2 (CP8): a tool that sends a message is refused at the executor itself
without consent, whatever path reached it (a `tool.call` step and an agent's
tool both end in `execute`), and the tool is not called. R3.9 (CP24): an
admitted send's `dispatching` row is committed before the tool is called (a
second connection sees it). R3.3: the tool takes the unsubscribe link in its
input, and a success records `marketing.sent` with its consent record. CP28:
two addresses are `blocked:multiple_recipients`. No floor wired refuses too.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from runtime_harness import RuntimeUrls, make_run_context
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.wflite_host import build_send_floor, build_tool_executor
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import MessageSpec, RunContext, ToolDefinition
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import PermissionDeniedError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_observability.telemetry import NullTelemetry
from dw_platform.adapters.persistence.marketing_send_repo import SqlConsentStore
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.marketing_send import ConsentLedger
from dw_platform.application.work_queue import WorkScope

pytestmark = pytest.mark.integration

POLICIES = Path(__file__).resolve().parents[5] / "configs" / "policies"
DAYTIME = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)  # 10:00 in Hanoi
SECRET = "integration-unsubscribe-secret-0123456789"


class EmailInput(BaseModel):
    to: str
    cc: list[str] = []
    subject: str
    body: str
    unsubscribe_url: str | None = None


class Sent(BaseModel):
    ok: bool = True


@pytest.fixture
async def engines(urls: RuntimeUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(urls.migrator, poolclass=NullPool)
    app = create_async_engine(urls.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


class Tool:
    """The sending tool: records each call, and whether the floor's row was
    already committed when it was called."""

    def __init__(self, migrator: AsyncEngine) -> None:
        self.migrator = migrator
        self.calls: list[dict[str, Any]] = []
        self.row_seen: list[bool] = []

    async def __call__(self, payload: BaseModel, run_context: RunContext) -> Sent:
        async with self.migrator.connect() as conn:
            seen = await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM platform.marketing_send_log"
                    " WHERE run_id = :r AND outcome = 'dispatching'"
                ),
                {"r": run_context.run_id},
            )
        self.row_seen.append(bool(seen))
        self.calls.append(payload.model_dump())
        return Sent()


def executor(app: AsyncEngine, tool: Tool, *, with_floor: bool = True) -> ToolExecutor:
    sessions = async_sessionmaker(app, expire_on_commit=False)
    clock = FixedClock(DAYTIME)
    ids = Uuid4Generator()
    tools = ToolRegistry()
    tools.register(
        RegisteredTool(
            ToolDefinition(
                name="email.send",
                version="1.0.0",
                description="send one email",
                input_schema_ref="x",
                output_schema_ref="y",
                required_scopes=frozenset(),
                side_effect_level="external",
                approval_policy="conditional",
                timeout_seconds=10,
                max_retries=0,
                idempotent=True,
                data_classification=frozenset({"internal"}),
                message=MessageSpec(channel="email", recipient_fields=("to", "cc")),
            ),
            EmailInput,
            Sent,
            tool,
        )
    )
    return build_tool_executor(
        tools=tools,
        session_factory=sessions,
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        approval_policy=AutonomyApprovalPolicy(),
        telemetry=NullTelemetry(),
        clock=clock,
        ids=ids,
        send_admission=build_send_floor(
            session_factory=sessions,
            policies=POLICIES,
            signing_secret=SECRET if with_floor else "",
            web_url="https://app.example.com",
            clock=clock,
            ids=ids,
        ),
    )


async def consent(app: AsyncEngine, run: RunContext, address: str) -> uuid.UUID:
    ledger = ConsentLedger(
        store=SqlConsentStore(async_sessionmaker(app, expire_on_commit=False)),
        clock=FixedClock(DAYTIME),
        ids=Uuid4Generator(),
    )
    return await ledger.record(
        WorkScope(tenant_id=run.tenant_id, workspace_id=run.workspace_id),
        subject=address,
        channel="email",
        state="granted",
        source="web_form",
        notice_version="1.0",
    )


async def send(ex: ToolExecutor, run: RunContext, **fields: Any) -> str:
    try:
        await ex.execute(
            name="email.send",
            version="1.0.0",
            raw_input={"subject": "Chào", "body": "Cảm ơn.", **fields},
            run_context=run,
            idempotency_key=f"wf:{run.run_id}:send:",
        )
    except PermissionDeniedError as refused:
        return str(refused.details["reason_code"])
    return "sent"


def an_address() -> str:
    return f"lead-{uuid.uuid4().hex[:10]}@khach.vn"


async def test_a_send_without_consent_is_refused_at_the_executor(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.2 (CP8): refused where the effect happens; the tool is not called."""
    migrator, app = engines
    tool = Tool(migrator)
    assert await send(executor(app, tool), make_run_context(), to=an_address()) == (
        "blocked:no_consent"
    )
    assert tool.calls == []


async def test_an_admitted_send_is_logged_before_the_tool_and_carries_its_link(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.9 (CP24), R3.3."""
    migrator, app = engines
    tool = Tool(migrator)
    run = make_run_context()
    address = an_address()
    consent_id = await consent(app, run, address)
    assert await send(executor(app, tool), run, to=address) == "sent"
    assert tool.row_seen == [True]
    [call] = tool.calls
    assert str(call["unsubscribe_url"]).startswith("https://app.example.com/unsubscribe/")
    async with migrator.connect() as conn:
        details = (
            await conn.execute(
                sa.text(
                    "SELECT details FROM platform.audit_events"
                    " WHERE run_id = :r AND action = 'marketing.sent'"
                ),
                {"r": run.run_id},
            )
        ).scalar_one()
    assert details["consent_record_id"] == str(consent_id)


async def test_two_addresses_in_one_call_are_refused(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """CP28: every address field counts; more than one is refused, one row."""
    migrator, app = engines
    tool = Tool(migrator)
    run = make_run_context()
    first, second = an_address(), an_address()
    await consent(app, run, first)
    await consent(app, run, second)
    answer = await send(executor(app, tool), run, to=first, cc=[second])
    assert answer == "blocked:multiple_recipients"
    assert tool.calls == []
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT outcome, blocked_reason FROM platform.marketing_send_log"
                    " WHERE run_id = :r"
                ),
                {"r": run.run_id},
            )
        ).all()
    assert [(r.outcome, r.blocked_reason) for r in rows] == [("blocked", "multiple_recipients")]


async def test_without_a_floor_no_message_leaves(engines: tuple[AsyncEngine, AsyncEngine]) -> None:
    migrator, app = engines
    tool = Tool(migrator)
    run = make_run_context()
    address = an_address()
    await consent(app, run, address)
    assert await send(executor(app, tool, with_floor=False), run, to=address) == (
        "blocked:send_floor_unavailable"
    )
    assert tool.calls == []
