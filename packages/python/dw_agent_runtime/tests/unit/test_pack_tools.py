"""Unit: the Marketing pack's tools with a fake SMTP server and a fake Mailpit
(leadcare R3.1-R3.5, R3.7; LCP9-LCP11, LCP13, LCP15).

The recipient and the consent come from the run's work item, never from the
tool's input; nothing but the dev mailbox is ever reached, and not at all in a
deployed profile; a mail that may have left is `send_outcome_unknown`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from dw_agent_runtime.adapters.pack_tools import (
    AI_HEADER,
    AI_LINE,
    EmailInput,
    FetchInput,
    HandoffInput,
    LeadcareTools,
    load_leadcare_handoffs,
)
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.dispatch import NotDispatchedError, OutcomeUnknownError
from dw_connectors.adapters.mailpit_mailbox import MailpitMailbox
from dw_connectors.adapters.smtp_email import SmtpOutcomeUnknownError
from dw_kernel.errors import DWError, PermissionDeniedError
from dw_kernel.ports import FixedClock
from dw_platform.domain.digital_worker import DigitalWorker, DwConfiguration, DwPeople
from dw_platform.domain.work_item import WorkItem

pytestmark = pytest.mark.unit

CONFIGS = Path(__file__).resolve().parents[5] / "configs"
NOW = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)
VALIDATOR, SALES = uuid.uuid4(), uuid.uuid4()
LEAD = {
    "name": "Anh An",
    "email": "An@Khach.vn",
    "source": "website",
    "message": "x",
    "consent": {"granted": True, "text_version": "1", "captured_at": "2026-10-30T00:00:00Z"},
}


def work_item(payload: dict[str, Any]) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        dw_id=uuid.uuid4(),
        kind="marketing.lead",
        source_key="e1",
        payload=payload,
        payload_hash="a" * 64,
        holder_kind="digital_worker",
        holder_id=uuid.uuid4(),
        status="in_progress",
        available_at=NOW,
        run_id=uuid.uuid4(),
        wake_at=None,
        handoff=None,
        error=None,
        created_at=NOW,
        updated_at=NOW,
        closed_at=None,
    )


@dataclass
class Queue:
    item: WorkItem
    handed: list[dict[str, Any]] = field(default_factory=list)

    async def by_run(self, scope: Any, run_id: Any) -> WorkItem:
        return self.item

    async def hand_off(self, scope: Any, item_id: Any, *, to_user: Any, packet: Any) -> None:
        self.handed.append({"to": to_user, **packet})


class Workers:
    async def digital_worker(self, scope: Any, dw_id: Any) -> DigitalWorker:
        return DigitalWorker(
            id=dw_id,
            tenant_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            principal_user_id=uuid.uuid4(),
            configuration=DwConfiguration(
                key="lc",
                name="lc",
                mandate="x",
                work_kinds=("marketing.lead",),
                allowed_tools=("email.send",),
                workflow_key="lead_care",
                workflow_version="1.0.0",
                parameters={"sender_address": "dw@cong-ty.test"},
                role_keys=frozenset({"member"}),
                decision_classes=(),
            ),
            people=DwPeople(VALIDATOR, VALIDATOR, VALIDATOR, VALIDATOR),
            state="operating",
            created_by=VALIDATOR,
            created_at=NOW,
            updated_at=NOW,
        )


@dataclass
class Smtp:
    raises: Exception | None = None
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send(self, **mail: Any) -> None:
        if self.raises is not None:
            self.raises_once = self.raises
            raise self.raises
        self.sent.append(mail)


def tools(
    *,
    payload: dict[str, Any] = LEAD,
    smtp: Smtp | None = None,
    host: str = "mailpit",
    deployed: bool = False,
    mailbox: Any = None,
) -> tuple[LeadcareTools, Queue, Smtp]:
    queue = Queue(work_item(dict(payload)))
    sender = smtp if smtp is not None else Smtp()
    return (
        LeadcareTools(
            queue=queue,  # type: ignore[arg-type]
            workers=Workers(),
            clock=FixedClock(NOW),
            handoffs=load_leadcare_handoffs(CONFIGS / "copy" / "leadcare_handoff.yaml"),
            is_deployed=deployed,
            smtp_host=host,
            sender=sender,
            mailbox=mailbox,
        ),
        queue,
        sender,
    )


RUN = RunContext(
    run_id=uuid.uuid4(),
    tenant_id=uuid.uuid4(),
    workspace_id=uuid.uuid4(),
    actor_id=uuid.uuid4(),
    worker_id="dw:lead_care",
    worker_version="1.0.0",
    channel="dw_work",
    plan_id="professional",
    roles=frozenset(),
    scopes=frozenset(),
    trace_id="t",
)
MAIL = EmailInput(
    to="an@khach.vn", subject="Chào anh", body="Cảm ơn anh.", unsubscribe_url="https://x/u/t"
)


async def test_the_mail_is_from_the_dw_to_the_lead_with_the_ai_marks() -> None:
    """R3.1."""
    pack, _, smtp = tools()
    answer = await pack.send_email(MAIL, RUN)
    [mail] = smtp.sent
    assert (mail["sender"], mail["to"]) == ("dw@cong-ty.test", "an@khach.vn")
    assert mail["headers"] == {AI_HEADER: "true"}
    assert AI_LINE in mail["body"] and "https://x/u/t" in mail["body"]
    assert answer.sent_at == NOW.isoformat()


async def test_a_recipient_other_than_the_lead_is_refused() -> None:
    """R3.2 (LCP9)."""
    pack, _, smtp = tools()
    with pytest.raises(PermissionDeniedError) as refused:
        await pack.send_email(MAIL.model_copy(update={"to": "ke-khac@x.vn"}), RUN)
    assert refused.value.details["reason_code"] == "recipient_mismatch"
    assert smtp.sent == []


async def test_a_lead_without_consent_is_refused() -> None:
    """R3.2 (LCP10)."""
    pack, _, smtp = tools(payload={**LEAD, "consent": {"granted": False}})
    with pytest.raises(PermissionDeniedError) as refused:
        await pack.send_email(MAIL, RUN)
    assert refused.value.details["reason_code"] == "consent_missing"
    assert smtp.sent == []


@pytest.mark.parametrize(("host", "deployed"), [("smtp.gmail.com", False), ("mailpit", True)])
async def test_nothing_but_the_dev_mailbox_is_reached(host: str, deployed: bool) -> None:
    """R3.6 (LCP13): refused before any connection, in both cases."""
    pack, _, smtp = tools(host=host, deployed=deployed)
    with pytest.raises(NotDispatchedError) as refused:
        await pack.send_email(MAIL, RUN)
    assert refused.value.details["reason_code"] == "send_sink_only"
    assert smtp.sent == []


async def test_a_mail_that_may_have_left_is_outcome_unknown() -> None:
    """R3.7 (LCP15)."""
    pack, _, _ = tools(smtp=Smtp(raises=SmtpOutcomeUnknownError("timeout after DATA")))
    with pytest.raises(OutcomeUnknownError) as unknown:
        await pack.send_email(MAIL, RUN)
    assert unknown.value.details["reason_code"] == "send_outcome_unknown"


def mailpit(messages: list[dict[str, Any]], texts: dict[str, str]) -> MailpitMailbox:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/search":
            return httpx.Response(200, json={"messages": messages})
        return httpx.Response(200, json={"Text": texts[request.url.path.rsplit("/", 1)[1]]})

    return MailpitMailbox(base_url="http://mailpit:8025", transport=httpx.MockTransport(handle))


async def test_the_latest_reply_after_the_send_is_found() -> None:
    """R3.3: a reply before the send does not count."""
    box = mailpit(
        [
            {"ID": "old", "Created": "2026-10-30T02:00:00Z"},
            {"ID": "new", "Created": "2026-10-30T04:00:00Z"},
        ],
        {"old": "trước", "new": "Tôi quan tâm"},
    )
    pack, _, _ = tools(mailbox=box)
    since = FetchInput.model_validate({"from": "an@khach.vn", "since": NOW.isoformat()})
    assert (await pack.fetch_reply(since, RUN)).model_dump() == {
        "found": True,
        "text": "Tôi quan tâm",
    }
    nothing = replace(pack, mailbox=mailpit([{"ID": "old", "Created": "2026-10-30T02:00:00Z"}], {}))
    assert (await nothing.fetch_reply(since, RUN)).found is False


async def test_without_a_mailbox_the_reply_cannot_be_read() -> None:
    """R3.4 (LCP11)."""
    pack, _, _ = tools(mailbox=None)
    with pytest.raises(DWError) as refused:
        await pack.fetch_reply(
            FetchInput.model_validate({"from": "a@b.vn", "since": NOW.isoformat()}), RUN
        )
    assert refused.value.details["reason_code"] == "mailbox_unconfigured"


async def test_a_hand_off_goes_to_sales_or_the_validator_with_four_fields() -> None:
    """R3.5."""
    pack, queue, _ = tools()
    await pack.hand_off(
        HandoffInput(
            to={"user": str(SALES)},
            code="lead_replied",
            facts={"label": "interested", "summary": "muốn gọi", "tier": "A"},
        ),
        RUN,
    )
    await pack.hand_off(
        HandoffInput(to={"role": "validator"}, code="send_rejected", facts={"comment": "sai"}),
        RUN,
    )
    to_sales, to_validator = queue.handed
    assert to_sales["to"] == SALES and "interested" in to_sales["problem"]
    assert to_validator["to"] == VALIDATOR and "sai" in to_validator["context"]
    for packet in queue.handed:
        assert all(
            str(packet[f]).strip() for f in ("problem", "context", "tried", "recommendation")
        )
