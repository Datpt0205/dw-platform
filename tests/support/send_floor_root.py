"""What a composition root's Send floor test asks of the ToolExecutor that
root builds (compliance-pdpl ticket 04; R3.12, CP25).

The API and the worker each build their executor with `build_tool_executor`
and `build_send_floor`, and each is tested on its own: the floor wired in one
root proves nothing about the other (failure-modes #5). Both tests ask the
same questions, so they are written once here: the register the executor
sealed, the floor it holds, and one `email.send` called through it, as the
`tool.call` step of a run calls it, with what the call left in the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from runtime_harness import make_run_context
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import PENDING_STEPS, TOOL_STEP_ORDER, ToolExecutor
from dw_connectors.adapters.smtp_email import SmtpEmailSender
from dw_kernel.errors import PermissionDeniedError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.marketing_send_repo import SqlConsentStore
from dw_platform.application.marketing_send import ConsentLedger, MarketingSendPolicy
from dw_platform.application.work_queue import WorkScope

SIGNING_SECRET = "integration-unsubscribe-secret-0123456789"


def assert_floor_registered(executor: ToolExecutor, *, wired: bool) -> None:
    """R3.12: `send_floor` is a registered step, after `approval` and before
    `claim` as tools-and-skills R2.6 orders them, not a pending one; with a
    signing secret the step asks the real `MarketingSendPolicy`, without one
    it has no port (`build_send_floor` returns None)."""
    names = executor.steps.names()
    assert names == TOOL_STEP_ORDER
    assert names.index("approval") < names.index("send_floor") < names.index("claim")
    assert dict(executor.steps.entries())["send_floor"] is ToolExecutor.step_send_floor
    assert "send_floor" not in PENDING_STEPS
    if wired:
        assert isinstance(executor.send_admission, MarketingSendPolicy)
    else:
        assert executor.send_admission is None


@dataclass
class FakeSmtp:
    """Every mail `SmtpEmailSender` would have handed the server."""

    sent: list[dict[str, Any]]


def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> FakeSmtp:
    """The root's own SMTP sender, its server replaced: the root builds the
    sender from `smtp_host`, so the class is patched, not the instance."""
    smtp = FakeSmtp(sent=[])

    async def send(self: SmtpEmailSender, **mail: Any) -> None:
        smtp.sent.append(mail)

    monkeypatch.setattr(SmtpEmailSender, "send", send)
    return smtp


async def a_company(migrator: AsyncEngine) -> RunContext:
    """A tenant and workspace of this test alone, and a live run in it."""
    tenant, workspace = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)"),
            {"t": tenant, "s": f"floor-{tenant.hex[:12]}"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'main', 'main')"
            ),
            {"w": workspace, "t": tenant},
        )
    return make_run_context(tenant=tenant, workspace=workspace)


def an_address() -> str:
    return f"lead-{uuid.uuid4().hex[:10]}@khach.vn"


async def grant_consent(app: AsyncEngine, run: RunContext, address: str) -> None:
    ledger = ConsentLedger(
        store=SqlConsentStore(async_sessionmaker(app, expire_on_commit=False)),
        clock=SystemClock(),
        ids=Uuid4Generator(),
    )
    await ledger.record(
        WorkScope(tenant_id=run.tenant_id, workspace_id=run.workspace_id),
        subject=address,
        channel="email",
        state="granted",
        source="web_form",
        notice_version="1.0",
    )


async def send_email(executor: ToolExecutor, run: RunContext, address: str) -> str:
    """The shipped `email.send` (a `message` block), approved, under the key
    a `tool.call` step uses: `sent`, or the refusal's reason code."""
    try:
        await executor.execute(
            name="email.send",
            version="1.0.0",
            raw_input={"to": address, "subject": "Chào", "body": "Cảm ơn."},
            run_context=run,
            idempotency_key=f"wf:{run.run_id}:send:",
            approved=True,
        )
    except PermissionDeniedError as refused:
        return str(refused.details["reason_code"])
    return "sent"


@dataclass(frozen=True)
class CallTrail:
    """What one call left: its send-log rows, the floor's refusal events and
    the executor's execution rows."""

    log: list[tuple[str, str | None]]
    refused_events: int
    executions: list[str]


async def call_trail(migrator: AsyncEngine, run: RunContext) -> CallTrail:
    async with migrator.connect() as conn:
        log = (
            await conn.execute(
                sa.text(
                    "SELECT outcome, blocked_reason FROM platform.marketing_send_log"
                    " WHERE run_id = :r"
                ),
                {"r": run.run_id},
            )
        ).all()
        refused = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM platform.audit_events"
                " WHERE run_id = :r AND action = 'marketing.send_refused'"
            ),
            {"r": run.run_id},
        )
        executions = (
            await conn.execute(
                sa.text("SELECT status FROM platform.tool_executions WHERE run_id = :r"),
                {"r": run.run_id},
            )
        ).scalars()
        return CallTrail(
            log=[(row.outcome, row.blocked_reason) for row in log],
            refused_events=int(refused or 0),
            executions=list(executions),
        )
