"""The Marketing pack's three tools (leadcare R3), registered by both processes
that host its workflow: the worker runs a lead's steps, the API resumes a run a
person decided, and the send after an approval runs there.

Every effect goes through the ToolExecutor; these are what it calls once its
checks passed:

- `email.send`: one email to the lead of the run's work item, from the DW's
  `sender_address`. Its recipient and consent are read from the work item,
  never from the tool's input: a `to` that is not the lead's email is
  `recipient_mismatch`, a lead without `consent.granted = true` is
  `consent_missing` (R3.2). Anything but the dev mailbox is `send_sink_only`
  before a connection is opened (R3.6). A send that may have left is
  `send_outcome_unknown`, never tried again (R3.7). The mail carries
  `X-DW-AI-Drafted: true`, the AI line and the unsubscribe link (R3.1).
- `mailbox.fetch_reply`: the latest reply from the lead since the send, from the
  dev mailbox's API; without one configured, `mailbox_unconfigured` (R3.3, R3.4).
- `work.handoff`: the work item to a person, the DW's sales assignee or its
  Validator as it is now, with a four-field packet built from `facts` by the
  copy of `code` (R3.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError
from dw_agent_runtime.tool_specs import ToolSpecRegistry
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_connectors.adapters.smtp_email import (
    SmtpNotSentError,
    SmtpOutcomeUnknownError,
    SmtpRejectedError,
)
from dw_kernel.errors import ConfigError, DomainError, InfrastructureError, PermissionDeniedError
from dw_kernel.ports import UtcClock
from dw_platform.application.marketing_send import normalize_address
from dw_platform.application.work_queue import DwLookupPort, WorkQueue, WorkScope
from dw_platform.domain.work_item import WorkItem

# The hosts a send may reach in this slice: the dev mailbox only (R3.6).
SINK_HOSTS = frozenset({"mailpit", "localhost", "127.0.0.1"})
AI_HEADER = "X-DW-AI-Drafted"
AI_LINE = "Thư do trợ lý AI soạn và đã được người duyệt."


class EmailSenderPort(Protocol):
    async def send(
        self, *, sender: str, to: str, subject: str, body: str, headers: Mapping[str, str]
    ) -> None: ...


class MailboxPort(Protocol):
    async def latest_reply(self, *, sender: str, recipient: str, since: datetime) -> Any: ...


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=4000)
    # Set by the ToolExecutor from the Send floor's admission (compliance-pdpl R3.3).
    unsubscribe_url: str | None = None


class EmailSent(BaseModel):
    sent_at: str


class FetchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from", min_length=3, max_length=320)
    since: str


class FetchOutput(BaseModel):
    found: bool
    text: str = ""


class HandoffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: dict[str, str]
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    facts: dict[str, Any] = Field(default_factory=dict)


class HandoffDone(BaseModel):
    to_user: str


class _Packet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    problem: str = Field(min_length=1)
    context: str = Field(min_length=1)
    tried: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)


class _HandoffCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    copy_id: str
    version: str
    handoffs: dict[str, _Packet]


def load_leadcare_handoffs(path: Path) -> Mapping[str, Mapping[str, str]]:
    """`configs/copy/leadcare_handoff.yaml`: the four fields per code."""
    try:
        loaded = _HandoffCopy.model_validate(yaml.safe_load(path.read_bytes()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"hand-off copy {path.name} invalid: {exc}") from exc
    return {code: packet.model_dump() for code, packet in loaded.handoffs.items()}


def _refused(code: str) -> PermissionDeniedError:
    return PermissionDeniedError(f"refused: {code}", details={"reason_code": code})


class _Facts(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


@dataclass(frozen=True)
class LeadcareTools:
    queue: WorkQueue
    workers: DwLookupPort
    clock: UtcClock
    handoffs: Mapping[str, Mapping[str, str]]
    is_deployed: bool
    smtp_host: str
    sender: EmailSenderPort | None
    mailbox: MailboxPort | None

    async def _item(self, run: RunContext) -> tuple[WorkScope, WorkItem]:
        scope = WorkScope(tenant_id=run.tenant_id, workspace_id=run.workspace_id)
        item = await self.queue.by_run(scope, run.run_id)
        if item is None:
            raise _refused("work_item_missing")
        return scope, item

    async def _parameter(self, scope: WorkScope, item: WorkItem, name: str) -> Any:
        worker = await self.workers.digital_worker(scope, item.dw_id)
        if worker is None:
            raise _refused("dw_missing")
        return worker, worker.configuration.parameters.get(name)

    async def send_email(self, payload: BaseModel, run: RunContext) -> EmailSent:
        assert isinstance(payload, EmailInput)
        scope, item = await self._item(run)
        lead = item.payload
        if normalize_address("email", payload.to) != normalize_address(
            "email", str(lead.get("email", ""))
        ):
            raise _refused("recipient_mismatch")
        consent = lead.get("consent")
        if not (isinstance(consent, Mapping) and consent.get("granted") is True):
            raise _refused("consent_missing")
        if self.is_deployed or self.smtp_host not in SINK_HOSTS or self.sender is None:
            # Before any connection: nothing left (R3.6).
            raise NotDispatchedError("send_sink_only", details={"reason_code": "send_sink_only"})
        _, sender_address = await self._parameter(scope, item, "sender_address")
        if not sender_address:
            raise NotDispatchedError("no sender address", details={"reason_code": "sender_missing"})
        body = f"{payload.body}\n\n--\n{AI_LINE}\n"
        if payload.unsubscribe_url:
            body += f"Hủy nhận thư: {payload.unsubscribe_url}\n"
        try:
            await self.sender.send(
                sender=str(sender_address),
                to=payload.to,
                subject=payload.subject,
                body=body,
                headers={AI_HEADER: "true"},
            )
        except SmtpNotSentError as exc:
            raise NotDispatchedError(
                "the mail did not leave", details={"reason_code": "send_not_sent"}
            ) from exc
        except SmtpRejectedError as exc:
            raise RejectedError(
                "the mail server refused the mail",
                provider_code=str(exc.code),
                details={"reason_code": "send_rejected"},
            ) from exc
        except SmtpOutcomeUnknownError as exc:
            raise OutcomeUnknownError(
                "the mail may have left", details={"reason_code": "send_outcome_unknown"}
            ) from exc
        return EmailSent(sent_at=self.clock.now().isoformat())

    async def fetch_reply(self, payload: BaseModel, run: RunContext) -> FetchOutput:
        assert isinstance(payload, FetchInput)
        if self.mailbox is None:
            raise DomainError("no mailbox", details={"reason_code": "mailbox_unconfigured"})
        scope, item = await self._item(run)
        _, sender_address = await self._parameter(scope, item, "sender_address")
        try:
            since = datetime.fromisoformat(payload.since)
        except ValueError as exc:
            raise DomainError(
                "since is not a time", details={"reason_code": "since_invalid"}
            ) from exc
        try:
            reply = await self.mailbox.latest_reply(
                sender=payload.from_, recipient=str(sender_address), since=since
            )
        except Exception as exc:  # the dev mailbox down is the infrastructure's
            raise InfrastructureError("the mailbox did not answer") from exc
        return (
            FetchOutput(found=False) if reply is None else FetchOutput(found=True, text=reply.text)
        )

    async def hand_off(self, payload: BaseModel, run: RunContext) -> HandoffDone:
        assert isinstance(payload, HandoffInput)
        scope, item = await self._item(run)
        worker = await self.workers.digital_worker(scope, item.dw_id)
        if worker is None:
            raise _refused("dw_missing")
        if payload.to.get("role") == "validator":
            to_user = worker.people.validator_id
        else:
            try:
                to_user = uuid.UUID(str(payload.to.get("user")))
            except ValueError as exc:
                raise DomainError(
                    "no such person", details={"reason_code": "handoff_to_invalid"}
                ) from exc
        template = self.handoffs.get(payload.code)
        if template is None:
            raise DomainError("no such hand-off", details={"reason_code": "handoff_code_unknown"})
        facts = _Facts({k: str(v) for k, v in payload.facts.items()})
        packet = {field: text.format_map(facts)[:4000] for field, text in template.items()}
        await self.queue.hand_off(scope, item.id, to_user=to_user, packet=packet)
        return HandoffDone(to_user=str(to_user))


def register_leadcare_tools(
    tools: ToolRegistry, specs: ToolSpecRegistry, implementation: LeadcareTools
) -> None:
    """Each tool's definition from its spec in `configs/tools`, its handler here."""
    for name, input_model, output_model, handler in (
        ("email.send", EmailInput, EmailSent, implementation.send_email),
        ("mailbox.fetch_reply", FetchInput, FetchOutput, implementation.fetch_reply),
        ("work.handoff", HandoffInput, HandoffDone, implementation.hand_off),
    ):
        definition = specs.definition(name, "1.0.0")
        tools.register(RegisteredTool(definition, input_model, output_model, handler))


def build_leadcare_tools(
    *,
    session_factory: Any,
    queue: WorkQueue,
    clock: UtcClock,
    handoffs: Path,
    is_deployed: bool,
    smtp_host: str,
    smtp_port: int,
    mailbox_url: str | None,
) -> LeadcareTools:
    """What both roots register for the Marketing pack: its SMTP sender only
    with a host, its mailbox only with an API URL."""
    from dw_connectors.adapters.mailpit_mailbox import MailpitMailbox
    from dw_connectors.adapters.smtp_email import SmtpEmailSender
    from dw_platform.adapters.persistence.digital_workers_repo import SqlDigitalWorkerRepository

    return LeadcareTools(
        queue=queue,
        workers=SqlDigitalWorkerRepository(session_factory),
        clock=clock,
        handoffs=load_leadcare_handoffs(handoffs),
        is_deployed=is_deployed,
        smtp_host=smtp_host,
        sender=SmtpEmailSender(host=smtp_host, port=smtp_port) if smtp_host else None,
        mailbox=MailpitMailbox(base_url=mailbox_url) if mailbox_url else None,
    )
