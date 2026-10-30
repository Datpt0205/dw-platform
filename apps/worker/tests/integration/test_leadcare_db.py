"""Integration: one lead, from the signed intake to the sales hand-off, on real
PostgreSQL with a fake model, a fake SMTP server and a fake mailbox (leadcare
ticket 01, step 8).

The shipped Marketing pack, the real tools of the pack, the Send floor, the
decision gate, the runner, the `dw_work` and `dw_timers` lanes: a lead is
signed in, scored and drafted, waits for its Validator, is sent once to the
lead's own address with the AI marks and an unsubscribe link, waits for a
reply, and goes to the DW's sales assignee with a four-field packet (R1.1,
R2.1, R2.13, R3.1-R3.3, R3.5). And R3.8: a reply wait under 30 seconds is
`parameter_invalid` at the start, 30 runs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from test_wflite_runs_db import as_validator, engines  # noqa: F401 - the fixture

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.pack_tools import (
    LeadcareTools,
    load_leadcare_handoffs,
    register_leadcare_tools,
)
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.wflite_host import (
    build_run_starter,
    build_send_floor,
    build_tool_executor,
    build_wflite_ports,
    load_handoff_copy,
    register_workflows,
)
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tool_specs import ToolSpecRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.wflite.catalog import load_shipped_packs
from dw_agent_runtime.wflite.waits import WorkQueueRunWaits
from dw_kernel.ports import FixedClock, SystemClock, Uuid4Generator
from dw_observability.telemetry import NullTelemetry
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.marketing_send_repo import SqlConsentStore, SqlIntakeScopes
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.decision_gate import (
    DW_DECISION,
    DwDecisionAdmission,
    check_edited_proposal,
)
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.intake import IntakeKeys, LeadIntake
from dw_platform.application.marketing_send import ConsentLedger
from dw_platform.application.work_queue import WorkQueue
from dw_worker.consumers.dw_timers import build_dw_timers_consumer
from dw_worker.consumers.dw_work import build_dw_work_consumer

pytestmark = pytest.mark.integration

CONFIGS = Path(__file__).resolve().parents[4] / "configs"
# 10:00 in Hanoi, inside the floor's sending hours.
DAYTIME = datetime.now(UTC).replace(hour=3, minute=0, second=0, microsecond=0)
SECRET = b"integration-intake-secret-0123456789abcdef"
LEAD = {
    "name": "Chị Lan",
    "email": "Lan@Khach.vn",
    "source": "website",
    "message": "Tôi muốn tư vấn phần mềm.",
    "consent": {"granted": True, "text_version": "form-1", "captured_at": "2026-10-30T08:00:00Z"},
}
ANSWERS = {
    "marketing.lead_score": {"score": 80, "tier": "A", "reasons": ["cần ngay"], "confidence": 0.9},
    "marketing.lead_email_draft": {
        "subject": "Chào chị Lan",
        "body": "Cảm ơn chị.",
        "confidence": 0.9,
    },
    "marketing.lead_reply_classify": {
        "label": "interested",
        "summary": "muốn gọi",
        "confidence": 0.9,
    },
}


@dataclass
class Gateway:
    async def generate_structured(self, request: Any, output_type: Any, *, run_context: Any) -> Any:
        return output_type.model_validate(ANSWERS[request.prompt_id])


@dataclass
class Smtp:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send(self, **mail: Any) -> None:
        self.sent.append(mail)


@dataclass
class Reply:
    text: str
    received_at: datetime


@dataclass
class Mailbox:
    reply: Reply | None = None

    async def latest_reply(self, *, sender: str, recipient: str, since: datetime) -> Reply | None:
        return self.reply


@dataclass
class Lead:
    tenant: uuid.UUID
    workspace: uuid.UUID
    dw: uuid.UUID
    validator: uuid.UUID
    sales: uuid.UUID


async def seed(migrator: AsyncEngine, *, reply_wait: int = 30) -> Lead:
    t, w, owner, validator, sales, principal, dw = (uuid.uuid4() for _ in range(7))
    async with migrator.begin() as conn:

        async def run(sql: str, **values: Any) -> None:
            await conn.execute(sa.text(sql), values)

        await run(
            "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)",
            t=t,
            s=f"lc-{t.hex[:12]}",
        )
        await run(
            "INSERT INTO platform.entitlements (id, tenant_id, plan_id)"
            " VALUES (:i, :t, 'professional')",
            i=uuid.uuid4(),
            t=t,
        )
        await run(
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
            " VALUES (:w, :t, 'main', 'main')",
            w=w,
            t=t,
        )
        for user in (owner, validator, sales):
            await run(
                "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'p')",
                u=user,
                s=f"lc-{user}",
            )
            await run(
                "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
                " VALUES (:i, :t, :w, :u, '[\"approver\"]'::jsonb)",
                i=uuid.uuid4(),
                t=t,
                w=w,
                u=user,
            )
        await run(
            "INSERT INTO platform.users (id, subject, display_name, kind, owner_tenant_id)"
            " VALUES (:u, :s, 'dw', 'service', :t)",
            u=principal,
            s=f"service:{principal}",
            t=t,
        )
        await run(
            "INSERT INTO platform.service_principals (user_id, tenant_id, owning_workspace_id,"
            " name,"
            " owner_user_id) VALUES (:u, :t, :w, 'dw', :o)",
            u=principal,
            t=t,
            w=w,
            o=owner,
        )
        await run(
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id, role_keys)"
            " VALUES (:i, :t, :w, :u, '[\"member\"]'::jsonb)",
            i=uuid.uuid4(),
            t=t,
            w=w,
            u=principal,
        )
        params = {
            "sender_address": "dw@cong-ty.test",
            "sales_assignee_id": str(sales),
            "reply_wait_seconds": reply_wait,
        }
        await run(
            "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id, principal_user_id,"
            " key, name, mandate, work_kinds, allowed_tools, workflow_key, workflow_version,"
            " parameters, state, technical_owner_id, work_assigner_id, validator_id, created_by)"
            " VALUES (:d, :t, :w, :u, :k, 'dw', 'dw', ARRAY['marketing.lead'],"
            " ARRAY['email.send', 'mailbox.fetch_reply', 'work.handoff'], 'lead_care', '1.0.0',"
            " CAST(:p AS jsonb), 'operating', :o, :o, :v, :o)",
            d=dw,
            t=t,
            w=w,
            u=principal,
            k=f"lc_{dw.hex[:12]}",
            p=json.dumps(params),
            o=owner,
            v=validator,
        )
        for key, effect, reversible, level in (
            ("email.send", "external", False, "A2"),
            ("work.handoff", "internal", True, "A3"),
        ):
            await run(
                "INSERT INTO platform.dw_decision_classes (dw_id, key, tenant_id, workspace_id,"
                " effect_level, reversible, ceiling, earned_level)"
                " VALUES (:d, :k, :t, :w, :e, :r, :c, :c)",
                d=dw,
                k=key,
                t=t,
                w=w,
                e=effect,
                r=reversible,
                c=level,
            )
    return Lead(t, w, dw, validator, sales)


@dataclass
class Process:
    intake: LeadIntake
    queue: WorkQueue
    runner: LangGraphWorkflowRunner
    run_store: SqlWorkerRunStore
    flow: ApproveAndResumeService
    starter: Any
    smtp: Smtp
    mailbox: Mailbox

    async def work(self) -> None:
        await build_dw_work_consumer(self.queue, self.starter)()

    async def timers(self) -> None:
        await build_dw_timers_consumer(self.queue, self.run_store, self.runner, SystemClock())()


def process(app: AsyncEngine) -> Process:
    sessions = async_sessionmaker(app, expire_on_commit=False)
    clock, floor_clock, ids = SystemClock(), FixedClock(DAYTIME), Uuid4Generator()
    catalog = load_shipped_packs(CONFIGS)
    uow = SqlPlatformUnitOfWorkFactory(sessions)
    policy = AutonomyApprovalPolicy()
    queue = WorkQueue(
        repo=SqlWorkQueueRepository(sessions),
        workers=SqlDigitalWorkerRepository(sessions),
        people=SqlDwMembershipCheck(sessions),
        schemas=catalog,
        authz=ScopeAuthorizationService(),
        clock=clock,
        id_generator=ids,
    )
    tools = ToolRegistry()
    executor = build_tool_executor(
        tools=tools,
        session_factory=sessions,
        uow_factory=uow,
        approval_policy=policy,
        telemetry=NullTelemetry(),
        clock=clock,
        ids=ids,
        send_admission=build_send_floor(
            session_factory=sessions,
            policies=CONFIGS / "policies",
            signing_secret="integration-unsubscribe-secret-0123456789",
            web_url="https://app.example.com",
            clock=floor_clock,
            ids=ids,
        ),
    )
    smtp, mailbox = Smtp(), Mailbox()
    specs = ToolSpecRegistry(copy=load_runtime_copy(CONFIGS / "copy" / "runtime@1.6.0.yaml"))
    specs.load_directory(CONFIGS / "tools")
    register_leadcare_tools(
        tools,
        specs,
        LeadcareTools(
            queue=queue,
            workers=SqlDigitalWorkerRepository(sessions),
            clock=clock,
            handoffs=load_leadcare_handoffs(CONFIGS / "copy" / "leadcare_handoff.yaml"),
            is_deployed=False,
            smtp_host="mailpit",
            sender=smtp,
            mailbox=mailbox,
        ),
    )
    graphs = GraphRegistry()
    workers = WorkerRegistry(graph_registry=graphs)
    run_store = SqlWorkerRunStore(sessions, stale_run_after_seconds=3600)
    runner = LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
        run_store=run_store,
        uow_factory=uow,
        clock=clock,
        id_generator=ids,
        allowance=PlanEntitlementService(DEFAULT_PLANS),
        budget=RunBudgetLedger(),
        approval_policy=policy,
        run_waits=WorkQueueRunWaits(queue),
    )
    register_workflows(
        catalog,
        build_wflite_ports(
            session_factory=sessions,
            gateway=Gateway(),
            executor=executor,
            tools=tools,
            queue=queue,
            recommendations=load_handoff_copy(CONFIGS / "copy" / "wflite_handoff.yaml"),
            clock=clock,
            ids=ids,
        ),
        graphs=graphs,
        workers=workers,
    )
    return Process(
        intake=LeadIntake(
            keys=IntakeKeys(SECRET),
            scopes=SqlIntakeScopes(sessions),
            queue=queue,
            consents=ConsentLedger(store=SqlConsentStore(sessions), clock=clock, ids=ids),
            clock=clock,
        ),
        queue=queue,
        runner=runner,
        run_store=run_store,
        flow=ApproveAndResumeService(
            uow_factory=uow,
            runner=runner,
            run_store=run_store,
            clock=clock,
            id_generator=ids,
            type_admissions={DW_DECISION: DwDecisionAdmission()},
            proposal_editors={DW_DECISION: check_edited_proposal},
        ),
        starter=build_run_starter(
            catalog=catalog, session_factory=sessions, tools=tools, runner=runner
        ),
        smtp=smtp,
        mailbox=mailbox,
    )


async def signed_in(p: Process, lead: Lead) -> uuid.UUID:
    keys = IntakeKeys(SECRET)
    body = json.dumps(LEAD).encode()
    event, timestamp = f"evt-{uuid.uuid4().hex}", str(int(datetime.now(UTC).timestamp()))
    item = await p.intake.receive(
        worker=str(lead.dw),
        event_id=event,
        timestamp=timestamp,
        signature=keys.signature(lead.dw, timestamp, event, body),
        body=body,
    )
    return item.id


async def item(migrator: AsyncEngine, item_id: uuid.UUID) -> Any:
    async with migrator.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT status, run_id, holder_id, handoff, error"
                    " FROM platform.work_items WHERE id = :i"
                ),
                {"i": item_id},
            )
        ).one()


async def test_a_lead_goes_from_the_intake_to_sales(
    engines: tuple[AsyncEngine, AsyncEngine],  # noqa: F811
    worker_db: DatabaseUrls,
) -> None:
    migrator, app = engines
    lead = await seed(migrator)
    p = process(app)
    item_id = await signed_in(p, lead)
    await p.work()
    row = await item(migrator, item_id)
    assert row.status == "waiting_approval", row
    assert p.smtp.sent == []
    async with migrator.connect() as conn:
        approval = (
            await conn.execute(
                sa.text("SELECT id, payload FROM platform.approval_requests WHERE run_id = :r"),
                {"r": row.run_id},
            )
        ).one()
    assert approval.payload["proposal"]["to"] == "Lan@Khach.vn"
    validator = as_validator(
        type(
            "W",
            (),
            {"tenant": lead.tenant, "workspace": lead.workspace, "validator": lead.validator},
        )()
    )
    from dw_platform.application.authorization import ScopeAuthorizationService as Authz

    await p.flow.decide(
        approval_id=approval.id,
        approve=True,
        comment="ok",
        context=validator,
        authorization=Authz(),
    )
    [mail] = p.smtp.sent
    assert (mail["sender"], mail["to"]) == ("dw@cong-ty.test", "Lan@Khach.vn")
    assert mail["headers"] == {"X-DW-AI-Drafted": "true"}
    assert "https://app.example.com/unsubscribe/" in mail["body"]
    assert (await item(migrator, item_id)).status == "waiting_timer"

    p.mailbox.reply = Reply(text="Tôi muốn hẹn gọi.", received_at=datetime.now(UTC))
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.work_items SET wake_at = now() - interval '1 second' WHERE id = :i"
            ),
            {"i": item_id},
        )
    await p.timers()
    done = await item(migrator, item_id)
    assert done.status == "handed_off" and done.holder_id == lead.sales, done
    assert "interested" in done.handoff["problem"]
    assert all(
        str(done.handoff[f]).strip() for f in ("problem", "context", "tried", "recommendation")
    )
    assert len(p.smtp.sent) == 1


@pytest.mark.parametrize(("wait", "failed"), [(29, True), (30, False)])
async def test_a_reply_wait_under_30_seconds_does_not_start(
    engines: tuple[AsyncEngine, AsyncEngine],  # noqa: F811
    wait: int,
    failed: bool,
) -> None:
    """R3.8."""
    migrator, app = engines
    lead = await seed(migrator, reply_wait=wait)
    p = process(app)
    item_id = await signed_in(p, lead)
    await p.work()
    row = await item(migrator, item_id)
    if failed:
        assert (row.status, row.error) == ("failed", "parameter_invalid")
    else:
        assert row.status == "waiting_approval"
