"""One lead, the whole way, on the demo stack (leadcare ticket 02, R4.2 and R4.4).

Against the stack `make demo-dw` started and `demo_dw_seed` seeded:

1. the Business Owner reads the DW's intake key (audited, R2.11) and a website
   form posts one signed lead (``POST /intake/leads``);
2. the run scores and drafts on the real model and stops at its Validator's
   ``dw.decision`` approval;
3. **R4.4**: Mailpit must hold no mail to the lead yet; one there means a mail
   left before a person decided, and the demo ends non-zero without deciding;
4. the Validator approves through the API, and the mail reaches Mailpit;
5. the lead answers over SMTP; after the DW's reply wait the run reads it,
   classifies it and hands the item to the sales person with its four fields.

Each stage is timed and printed. Any deviation, a stage past its deadline, or
a whole run over ten minutes (R4.2) ends with a non-zero exit. The run starts
only inside the Send floor's hours (08:00-20:00 giờ Việt Nam,
``configs/policies/marketing_send@1.0.0.yaml``): outside them the floor refuses
the mail, by design, and the demo says so instead of failing half-way.

    DW_DEMO_API_URL=http://localhost:8010 uv run python -m scripts.demo_dw_run \\
        --state .demo/digital-worker/state.json --mailpit http://127.0.0.1:28045 --smtp-port 21045
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import smtplib
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

import httpx

from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.marketing_send import load_send_floor_policy
from scripts.demo_dw_api import Api, DemoError, Person

ROOT = Path(__file__).resolve().parents[1]
SEND_FLOOR = ROOT / "configs" / "policies" / "marketing_send@1.0.0.yaml"
BUDGET_SECONDS = 600.0  # R4.2: ten minutes, not counting the people
HANDOFF_FIELDS = ("problem", "context", "tried", "recommendation")
FAILED = frozenset({"failed", "cancelled", "done"})


class PlatformPort(Protocol):
    """What the run asks the platform, each as the person who would ask it."""

    def send_lead(self, body: bytes) -> str: ...
    def work_item(self, item_id: str) -> dict[str, Any]: ...
    def pending_decision(self, recipient: str) -> dict[str, Any] | None: ...
    def approve(self, approval_id: str) -> None: ...


class MailboxPort(Protocol):
    def messages_to(self, address: str) -> list[dict[str, Any]]: ...


class ReplyPort(Protocol):
    def send(self, *, sender: str, recipient: str, subject: str, body: str) -> None: ...


@dataclass(frozen=True)
class Lead:
    name: str
    email: str
    message: str
    reply: str

    def body(self) -> bytes:
        return json.dumps(
            {
                "name": self.name,
                "email": self.email,
                "source": "website",
                "message": self.message,
                "consent": {
                    "granted": True,
                    "text_version": "form-demo-1",
                    "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            },
            ensure_ascii=False,
        ).encode()


def demo_lead() -> Lead:
    """A new address each run: the Send floor allows one mail per address a day."""
    return Lead(
        name="Nguyễn Thị Lan",
        email=f"lan.{uuid.uuid4().hex[:8]}@example.com",
        message=(
            "Công ty tôi có 40 nhân viên bán hàng, đang cần phần mềm quản lý khách hàng"
            " và muốn triển khai ngay trong tháng này. Nhờ bên anh chị tư vấn và báo giá."
        ),
        reply=(
            "Chào anh chị, cảm ơn thư. Tôi rất quan tâm và muốn hẹn một cuộc gọi tư vấn"
            " vào chiều thứ Năm này, khoảng 15 giờ."
        ),
    )


@dataclass
class Stages:
    """Elapsed seconds per stage, and the part of them a person spent."""

    clock: Callable[[], float]
    item_id: str = ""
    handoff: dict[str, Any] = field(default_factory=dict)
    started: float = 0.0
    last: float = 0.0
    rows: list[tuple[str, float]] = field(default_factory=list)
    people_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.started = self.last = self.clock()

    def mark(self, name: str, *, by_people: bool = False) -> None:
        now = self.clock()
        elapsed = now - self.last
        self.rows.append((name, elapsed))
        if by_people:
            self.people_seconds += elapsed
        self.last = now
        print(f"  {name}: {elapsed:.1f}s", flush=True)

    @property
    def machine_seconds(self) -> float:
        return self.last - self.started - self.people_seconds


def wait_for(
    what: str,
    probe: Callable[[], Any],
    *,
    seconds: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    every: float = 2.0,
) -> Any:
    deadline = clock() + seconds
    while True:
        found = probe()
        if found:
            return found
        if clock() > deadline:
            raise DemoError(f"{what}: nothing after {seconds:.0f}s")
        sleep(every)


def require_no_mail_before_approval(mailbox: MailboxPort, recipient: str) -> None:
    """R4.4 (LCP12): a mail to the lead before its Validator decided is the
    failure this platform exists to prevent, so the demo stops on it."""
    early = mailbox.messages_to(recipient)
    if early:
        raise DemoError(
            f"{len(early)} mail(s) to {recipient} reached Mailpit before the approval was"
            " decided: a message left without a person's decision"
        )


def require_send_hours(now: datetime, *, budget: float = BUDGET_SECONDS) -> None:
    policy = load_send_floor_policy(SEND_FLOOR)
    if not (policy.within_hours(now) and policy.within_hours(now + timedelta(seconds=budget))):
        hours = policy.sending_hours
        raise DemoError(
            f"outside the Send floor's hours ({hours.start}-{hours.end} {hours.timezone}):"
            " the floor would refuse the mail; run the demo inside them"
        )


def run_demo(
    platform: PlatformPort,
    mailbox: MailboxPort,
    replies: ReplyPort,
    lead: Lead,
    *,
    sender_address: str,
    sales_id: str,
    reply_wait_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    at_approval: Callable[[], None] = lambda: None,
) -> Stages:
    stages = Stages(clock)
    item_id = stages.item_id = platform.send_lead(lead.body())
    stages.mark("lead signed in (202)")

    def reached_approval() -> bool:
        status = platform.work_item(item_id)["status"]
        if status in FAILED or status == "handed_off":
            raise DemoError(f"the lead is {status} before its approval")
        return bool(status == "waiting_approval")

    wait_for(
        "the run to reach its approval", reached_approval, seconds=240, clock=clock, sleep=sleep
    )
    approval = wait_for(
        "the Validator's dw.decision",
        lambda: platform.pending_decision(lead.email),
        seconds=30,
        clock=clock,
        sleep=sleep,
    )
    stages.mark("scored and drafted, waiting for the Validator")

    # The Validator reads the card (the demo's screenshot of it), then decides;
    # the check comes last, right before the decision it guards.
    at_approval()
    require_no_mail_before_approval(mailbox, lead.email)
    platform.approve(str(approval["id"]))
    stages.mark("Validator read the card and approved", by_people=True)

    [mail] = wait_for(
        "the approved mail in Mailpit",
        lambda: mailbox.messages_to(lead.email),
        seconds=120,
        clock=clock,
        sleep=sleep,
    )
    stages.mark("mail in Mailpit")

    replies.send(
        sender=lead.email,
        recipient=sender_address,
        subject=f"Re: {mail.get('Subject', '')}",
        body=lead.reply,
    )
    stages.mark("lead replied", by_people=True)

    def handed_off() -> dict[str, Any] | None:
        item = platform.work_item(item_id)
        if item["status"] in FAILED:
            raise DemoError(f"the lead ended {item['status']}: {item.get('error')}")
        return item if item["status"] == "handed_off" else None

    done = wait_for(
        "the hand-off to sales",
        handed_off,
        seconds=reply_wait_seconds + 240,
        clock=clock,
        sleep=sleep,
    )
    stages.mark("reply read, classified, handed to sales")

    if str(done["holder_id"]) != sales_id:
        raise DemoError(f"handed to {done['holder_id']}, not the sales person {sales_id}")
    packet = done.get("handoff") or {}
    empty = [name for name in HANDOFF_FIELDS if not str(packet.get(name) or "").strip()]
    if empty:
        raise DemoError(f"the hand-off packet lacks {', '.join(empty)}")
    if len(mailbox.messages_to(lead.email)) != 1:
        raise DemoError("the lead received more than one mail")
    if stages.machine_seconds > BUDGET_SECONDS:
        raise DemoError(
            f"{stages.machine_seconds:.0f}s without the people, over {BUDGET_SECONDS:.0f}s"
        )
    stages.handoff = dict(packet)
    print(f"  handed to sales: {json.dumps(packet, ensure_ascii=False)}")
    return stages


def execute(
    platform: PlatformPort,
    mailbox: MailboxPort,
    replies: ReplyPort,
    lead: Lead,
    *,
    sender_address: str,
    sales_id: str,
    reply_wait_seconds: float,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    at_approval: Callable[[], None] = lambda: None,
    on_success: Callable[[Stages], None] = lambda stages: None,
) -> int:
    """The run as an exit code: 0 when the lead reached sales as R4.2 says."""
    try:
        require_send_hours(now or datetime.now(UTC))
        stages = run_demo(
            platform,
            mailbox,
            replies,
            lead,
            sender_address=sender_address,
            sales_id=sales_id,
            reply_wait_seconds=reply_wait_seconds,
            clock=clock,
            sleep=sleep,
            at_approval=at_approval,
        )
    except DemoError as exc:
        print(f"!! demo run: {exc}", file=sys.stderr)
        return 1
    print(
        f"  total {stages.last - stages.started:.1f}s,"
        f" {stages.machine_seconds:.1f}s without the people"
    )
    on_success(stages)
    return 0


# ------------------------------------------------------------------ adapters --


@dataclass
class HttpPlatform:
    """The platform's API, as the Business Owner, a website form and the Validator."""

    api: Api
    scope: tuple[str, str]
    dw_id: str
    owner: Person
    validator: Person

    def send_lead(self, body: bytes) -> str:
        key = self.api.call(
            "GET", f"/digital-workers/{self.dw_id}/intake-key", self.owner, scope=self.scope
        )["key"]
        event, timestamp = f"evt-{uuid.uuid4().hex}", str(int(time.time()))
        signed = f"{timestamp}.{event}.".encode() + body
        signature = hmac.new(str(key).encode(), signed, hashlib.sha256).hexdigest()
        response = self.api.http.post(
            f"{self.api.base_url}/api/v1/intake/leads",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-DW-Worker": self.dw_id,
                "X-DW-Event-Id": event,
                "X-DW-Timestamp": timestamp,
                "X-DW-Signature": signature,
            },
        )
        if response.status_code != 202:
            raise DemoError(f"intake: {response.status_code} {response.text[:300]}")
        return str(response.json()["id"])

    def work_item(self, item_id: str) -> dict[str, Any]:
        item: dict[str, Any] = self.api.call(
            "GET", f"/work-items/{item_id}", self.owner, scope=self.scope
        )
        return item

    def pending_decision(self, recipient: str) -> dict[str, Any] | None:
        page = self.api.call("GET", "/approvals?limit=50", self.validator, scope=self.scope)
        for approval in page.get("items", []):
            proposal = (approval.get("payload") or {}).get("proposal") or {}
            if approval["approval_type"] == "dw.decision" and proposal.get("to") == recipient:
                return dict(approval)
        return None

    def approve(self, approval_id: str) -> None:
        self.api.call(
            "POST",
            f"/approvals/{approval_id}/decisions",
            self.validator,
            scope=self.scope,
            body={"approve": True, "comment": "Đã đọc thư, đồng ý gửi."},
        )


@dataclass
class Mailpit:
    http: httpx.Client
    base_url: str

    def messages_to(self, address: str) -> list[dict[str, Any]]:
        response = self.http.get(
            f"{self.base_url}/api/v1/search", params={"query": f"to:{address}"}
        )
        response.raise_for_status()
        return list(response.json().get("messages") or [])


@dataclass(frozen=True)
class SmtpReplies:
    host: str
    port: int

    def send(self, *, sender: str, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = sender, recipient, subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.send_message(message)


def _person(state: dict[str, Any], role: str) -> Person:
    who = state["people"][role]
    return Person(role, who["subject"], who["email"], who["display_name"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--mailpit", required=True, help="Mailpit's HTTP API, from the host")
    parser.add_argument("--smtp-host", default="127.0.0.1")
    parser.add_argument("--smtp-port", type=int, required=True)
    parser.add_argument(
        "--at-approval",
        default=None,
        help="a command run while the approval waits (the demo screenshots its card)",
    )
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    base_url = os.environ.get("DW_DEMO_API_URL", state["api_url"]).rstrip("/")
    lead = demo_lead()
    print(f"lead {lead.email} for DW {state['dw_id']}")

    def at_approval() -> None:
        if args.at_approval is None:
            return
        # The Playwright spec reads the lead from the state file.
        state["lead"] = {"email": lead.email, "name": lead.name}
        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        # A command the operator's own Makefile passes, as written there.
        if subprocess.run(args.at_approval, shell=True, check=False).returncode != 0:
            raise DemoError(f"--at-approval failed: {args.at_approval}")

    def record(stages: Stages) -> None:
        # The Playwright spec opens this lead's item and checks its data.
        state["lead"] = {
            "email": lead.email,
            "name": lead.name,
            "item_id": stages.item_id,
            "handoff": stages.handoff,
        }
        state["stages"] = [[name, round(seconds, 1)] for name, seconds in stages.rows]
        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    with httpx.Client(timeout=30) as http:
        api = Api(base_url, DevTokenVerifier(os.environ.get("DW_API_DEV_SECRET", "")), http)
        code = execute(
            HttpPlatform(
                api=api,
                scope=(state["tenant_id"], state["workspace_id"]),
                dw_id=state["dw_id"],
                owner=_person(state, "business_owner"),
                validator=_person(state, "validator"),
            ),
            Mailpit(http, args.mailpit.rstrip("/")),
            SmtpReplies(args.smtp_host, args.smtp_port),
            lead,
            sender_address=state["sender_address"],
            sales_id=state["people"]["sales"]["user_id"],
            reply_wait_seconds=float(state["reply_wait_seconds"]),
            at_approval=at_approval,
            on_success=record,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
