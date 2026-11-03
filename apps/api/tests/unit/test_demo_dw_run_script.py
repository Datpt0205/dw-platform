"""``scripts/demo_dw_run.py``: the demo stops on a mail sent before its approval
(leadcare R4.4, LCP12), and passes only when the lead reaches sales (R4.2).

Fakes for the platform, Mailpit and SMTP; a fake clock, so nothing waits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from scripts.demo_dw_run import Lead, execute

pytestmark = pytest.mark.unit

SALES = "5a1e5000-0000-4000-8000-000000000001"
VALIDATOR = "5a1e5000-0000-4000-8000-000000000002"
SENDER = "dw-leadcare@demo.local"
# 10:00 in Hanoi, inside the Send floor's hours; 21:00 is outside them.
DAYTIME = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)
NIGHT = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
LEAD = Lead(name="Lan", email="lan@example.com", message="cần tư vấn", reply="gọi tôi nhé")
PACKET = {"problem": "interested", "context": "c", "tried": "t", "recommendation": "r"}


@dataclass
class World:
    """One lead's life as the fakes see it."""

    mail_before_approval: bool = False
    holder: str = SALES
    sent_lead: bool = False
    approved: bool = False
    replied: list[dict[str, str]] = field(default_factory=list)

    def mails(self) -> list[dict[str, Any]]:
        if self.mail_before_approval or self.approved:
            return [{"ID": "m1", "Subject": "Chào chị Lan", "To": [{"Address": LEAD.email}]}]
        return []


@dataclass
class FakePlatform:
    world: World

    def send_lead(self, body: bytes) -> str:
        self.world.sent_lead = True
        return "item-1"

    def work_item(self, item_id: str) -> dict[str, Any]:
        if self.world.replied:
            return {"status": "handed_off", "holder_id": self.world.holder, "handoff": PACKET}
        if self.world.approved:
            return {"status": "waiting_timer", "holder_id": "dw"}
        return {"status": "waiting_approval", "holder_id": "dw"}

    def pending_decision(self, recipient: str) -> dict[str, Any] | None:
        if self.world.approved:
            return None
        return {"id": "ap-1", "approval_type": "dw.decision", "payload": {"proposal": {}}}

    def approve(self, approval_id: str) -> None:
        self.world.approved = True


@dataclass
class FakeMailpit:
    world: World

    def messages_to(self, address: str) -> list[dict[str, Any]]:
        return self.world.mails() if address == LEAD.email else []


@dataclass
class FakeSmtp:
    world: World

    def send(self, *, sender: str, recipient: str, subject: str, body: str) -> None:
        self.world.replied.append({"from": sender, "to": recipient, "body": body})


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run(world: World, *, now: datetime = DAYTIME) -> int:
    clock = Clock()
    return execute(
        FakePlatform(world),
        FakeMailpit(world),
        FakeSmtp(world),
        LEAD,
        sender_address=SENDER,
        sales_id=SALES,
        reply_wait_seconds=60,
        now=now,
        clock=clock,
        sleep=clock.sleep,
    )


def test_a_lead_that_reaches_sales_passes() -> None:
    world = World()
    assert _run(world) == 0
    assert world.approved
    assert world.replied == [{"from": LEAD.email, "to": SENDER, "body": LEAD.reply}]


def test_a_mail_in_mailpit_before_the_approval_fails_the_demo() -> None:
    """R4.4 (LCP12): non-zero, and the Validator's decision is never sent."""
    world = World(mail_before_approval=True)
    assert _run(world) != 0
    assert not world.approved
    assert world.replied == []


def test_a_hand_off_to_someone_other_than_sales_fails_the_demo() -> None:
    world = World(holder=VALIDATOR)
    assert _run(world) != 0


def test_outside_the_send_floors_hours_no_lead_is_sent() -> None:
    world = World()
    assert _run(world, now=NIGHT) != 0
    assert not world.sent_lead
