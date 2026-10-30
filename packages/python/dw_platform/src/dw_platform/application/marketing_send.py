"""The Send floor a marketing message passes before it leaves (ADR-0124;
compliance-pdpl ticket 08; spec R3).

`MarketingSendPolicy.admit` answers the runtime's `SendAdmissionPort`: the
ToolExecutor asks it for every tool whose spec says it sends a message, so a
`tool.call` step and an agent's tool call meet the same floor, once. In one
transaction of its own, under two advisory locks (the address, then the root
run), it checks in ADR-0124's order:

1. suppressed: the address opted out (`contact_suppressions`);
2. consent: the latest record for `(subject, purpose, channel)` is `granted`,
   else `consent_withdrawn` or `no_consent`;
3. frequency: `dispatching` rows to the address in the window, every workspace
   of the tenant (the cap is the controller's, ADR-0124 decision 4);
4. quiet hours: the fixed `Asia/Ho_Chi_Minh` window of decision 6, never the
   company's own time zone (changing it would loosen the floor);
5. recipients: distinct addresses already sent to by the root run.

A refusal writes one `blocked` row and `marketing.send_refused` together. An
admission writes the `dispatching` row and commits before anything is sent, so
a send still in flight counts against the cap (R3.9). A call whose key already
has a `dispatching` row is the same send again (a replay after an unknown
outcome): it writes no row and is not counted, but suppression and consent are
asked again, so an opt-out in between holds (R3.11), and a refused replay
writes only its audit event (R3.7).

The address is normalized and hashed one way for the floor, suppression and the
unsubscribe token (`normalize_address`, `address_hash`); the floor's rows hold
the hash, never the address.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dw_kernel.errors import ConfigError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent

Channel = Literal["zns", "email", "sms", "messenger", "zalo_oa"]
CHANNELS: frozenset[str] = frozenset({"zns", "email", "sms", "messenger", "zalo_oa"})
PURPOSE = "marketing"
# The floor's refusals, in the order they are asked (ADR-0124 decision 1), and
# the one the executor raises itself for a call naming more than one address.
REASONS: tuple[str, ...] = (
    "suppressed",
    "no_consent",
    "consent_withdrawn",
    "frequency_cap",
    "quiet_hours",
    "recipient_cap",
    "multiple_recipients",
)
# The window of decision 6 is a fixed civil time, not a tenant setting.
FLOOR_TIMEZONE = "Asia/Ho_Chi_Minh"
SENT = "marketing.sent"
REFUSED = "marketing.send_refused"


# ----------------------------------------------------------- addresses --


def normalize_address(channel: str, value: str) -> str:
    """One spelling of an address: an email trimmed and lowercased, anything
    else trimmed."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    cleaned = value.strip()
    return cleaned.lower() if channel == "email" else cleaned


def address_hash(tenant_id: uuid.UUID, channel: str, normalized: str) -> str:
    """sha256(tenant_id || channel || normalized address), hex: the same
    address hashes apart in two tenants."""
    return hashlib.sha256(f"{tenant_id}{channel}{normalized}".encode()).hexdigest()


# -------------------------------------------------------------- policy --


class _Window(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    count: int = Field(ge=1)
    hours: int = Field(ge=1)


class _Hours(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: time
    end: time
    timezone: str


class SendFloorPolicy(BaseModel):
    """`configs/policies/marketing_send@1.0.0.yaml` (ADR-0124 decision 6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = Field(pattern=r"^1\.0$")
    policy_id: str
    version: str
    status: str
    per_address: _Window
    sending_hours: _Hours
    max_recipients_per_run: int = Field(ge=1)

    def within_hours(self, at: datetime) -> bool:
        local = at.astimezone(ZoneInfo(FLOOR_TIMEZONE)).time()
        return self.sending_hours.start <= local <= self.sending_hours.end


def load_send_floor_policy(path: Path) -> SendFloorPolicy:
    try:
        policy = SendFloorPolicy.model_validate(yaml.safe_load(path.read_bytes()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"send floor policy {path.name} invalid: {exc}") from exc
    if policy.sending_hours.timezone != FLOOR_TIMEZONE:
        raise ConfigError(f"the floor's sending hours are {FLOOR_TIMEZONE} (ADR-0124 decision 6)")
    return policy


# ------------------------------------------------------- unsubscribe --


@dataclass(frozen=True)
class UnsubscribeClaim:
    tenant_id: uuid.UUID
    channel: str
    address_hash: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class UnsubscribeLinks:
    """A one-address opt-out link (ADR-0124 decision 5): a token signed with
    HMAC-SHA256 carrying the tenant, the channel, the address's hash and when it
    was issued, never the address; older than 400 days, it is refused."""

    secret: bytes
    base_url: str
    clock: UtcClock
    max_age: timedelta = timedelta(days=400)

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise ConfigError("UNSUBSCRIBE_SIGNING_SECRET must be at least 32 bytes")

    def token(self, tenant_id: uuid.UUID, channel: str, hashed: str) -> str:
        body = json.dumps(
            {
                "t": str(tenant_id),
                "c": channel,
                "h": hashed,
                "i": int(self.clock.now().timestamp()),
            },
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return f"{_b64(body)}.{_b64(signature)}"

    def link(self, tenant_id: uuid.UUID, channel: str, address: str) -> str:
        hashed = address_hash(tenant_id, channel, normalize_address(channel, address))
        return f"{self.base_url.rstrip('/')}/unsubscribe/{self.token(tenant_id, channel, hashed)}"

    def verify(self, token: str) -> UnsubscribeClaim | None:
        try:
            body_part, signature_part = token.split(".", 1)
            body, signature = _unb64(body_part), _unb64(signature_part)
        except (ValueError, TypeError):
            return None
        expected = hmac.new(self.secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            return None
        try:
            claims = json.loads(body)
            tenant = uuid.UUID(str(claims["t"]))
            channel, hashed, issued = str(claims["c"]), str(claims["h"]), int(claims["i"])
        except (ValueError, KeyError, TypeError):
            return None
        if channel not in CHANNELS or len(hashed) != 64:
            return None
        if self.clock.now().timestamp() - issued > self.max_age.total_seconds():
            return None
        return UnsubscribeClaim(tenant_id=tenant, channel=channel, address_hash=hashed)


# ------------------------------------------------------------- ports --


@dataclass(frozen=True)
class CurrentConsent:
    id: uuid.UUID
    state: Literal["granted", "withdrawn"]


@dataclass(frozen=True)
class LogRow:
    channel: str
    address_hash: str
    outcome: Literal["dispatching", "blocked"]
    tool_name: str
    tool_version: str
    blocked_reason: str | None = None
    idempotency_key: str | None = None
    run_id: uuid.UUID | None = None
    root_run_id: uuid.UUID | None = None
    consent_record_id: uuid.UUID | None = None


class SendFloorTx(Protocol):
    """One transaction of the floor, under the request's tenant and workspace."""

    async def lock(self, key: str) -> None: ...

    async def dispatching_consent(self, idempotency_key: str) -> uuid.UUID | None:
        """The consent record of this key's `dispatching` row, or None."""
        ...

    async def suppressed(self, channel: str, hashed: str) -> bool: ...

    async def current_consent(self, subject_ref: str, channel: str) -> CurrentConsent | None: ...

    async def sends_since(self, channel: str, hashed: str, since: datetime) -> int: ...

    async def run_recipients(self, root_run_id: uuid.UUID) -> int: ...

    async def run_has_recipient(
        self, root_run_id: uuid.UUID, channel: str, hashed: str
    ) -> bool: ...

    async def write_log(self, row_id: uuid.UUID, row: LogRow) -> None: ...

    async def audit(self, event: AuditEvent) -> None: ...


class SendFloorStorePort(Protocol):
    def transaction(self, scope: WorkScope) -> AbstractAsyncContextManager[SendFloorTx]: ...


class ConsentStorePort(Protocol):
    async def insert(self, scope: WorkScope, row: Mapping[str, Any]) -> None: ...


class SuppressionStorePort(Protocol):
    async def suppress(
        self, tenant_id: uuid.UUID, channel: str, hashed: str, *, source: str
    ) -> bool:
        """True when this call added the row."""
        ...


# ----------------------------------------------------------- the floor --


@dataclass(frozen=True)
class SendRequest:
    """One message a tool call would send: one address on one channel."""

    scope: WorkScope
    actor_id: uuid.UUID
    channel: str
    address: str
    idempotency_key: str
    tool_name: str
    tool_version: str
    run_id: uuid.UUID | None = None
    # The run whose recipients are counted (R3.8); a wf-lite run is its own root.
    root_run_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Admission:
    admitted: bool
    reason: str | None = None
    consent_record_id: uuid.UUID | None = None
    unsubscribe_url: str | None = None
    replay: bool = False

    @property
    def code(self) -> str:
        return f"blocked:{self.reason}"


@dataclass(frozen=True)
class MarketingSendPolicy:
    """Implements the runtime's `SendAdmissionPort`."""

    store: SendFloorStorePort
    policy: SendFloorPolicy
    links: UnsubscribeLinks
    clock: UtcClock
    ids: IdGenerator

    async def admit(self, request: SendRequest) -> Admission:
        scope, channel = request.scope, request.channel
        normalized = normalize_address(channel, request.address)
        hashed = address_hash(scope.tenant_id, channel, normalized)
        now = self.clock.now()
        async with self.store.transaction(scope) as tx:
            # Address first, then run: one order for every caller.
            await tx.lock(f"marketing:{scope.tenant_id}:{channel}:{hashed}")
            if request.root_run_id is not None:
                await tx.lock(f"marketing-run:{scope.tenant_id}:{request.root_run_id}")
            replayed = await tx.dispatching_consent(request.idempotency_key)
            reason, consent = await self._standing(tx, channel, normalized, hashed)
            if replayed is not None:
                if reason is not None:
                    await tx.audit(self._refused(request, hashed, reason, replay=True))
                    return Admission(admitted=False, reason=reason, replay=True)
                return self._admitted(request, normalized, replayed, replay=True)
            if reason is None:
                reason = await self._caps(tx, request, hashed, now)
            if reason is not None:
                await self._block(tx, request, hashed, reason)
                return Admission(admitted=False, reason=reason)
            assert consent is not None
            await tx.write_log(
                self.ids.new_uuid(),
                LogRow(
                    channel=channel,
                    address_hash=hashed,
                    outcome="dispatching",
                    tool_name=request.tool_name,
                    tool_version=request.tool_version,
                    idempotency_key=request.idempotency_key,
                    run_id=request.run_id,
                    root_run_id=request.root_run_id,
                    consent_record_id=consent.id,
                ),
            )
        return self._admitted(request, normalized, consent.id)

    async def refuse(self, request: SendRequest, reason: str) -> Admission:
        """A refusal the caller decided before the floor could (a call naming
        more than one address): the same row and event as the floor's own."""
        hashed = address_hash(
            request.scope.tenant_id,
            request.channel,
            normalize_address(request.channel, request.address),
        )
        async with self.store.transaction(request.scope) as tx:
            await self._block(tx, request, hashed, reason)
        return Admission(admitted=False, reason=reason)

    async def sent(self, request: SendRequest, admission: Admission) -> None:
        """R3.3: the send succeeded; its event names the consent it relied on."""
        hashed = address_hash(
            request.scope.tenant_id,
            request.channel,
            normalize_address(request.channel, request.address),
        )
        async with self.store.transaction(request.scope) as tx:
            await tx.audit(
                self._event(
                    request,
                    SENT,
                    {
                        "channel": request.channel,
                        "address_hash": hashed,
                        "consent_record_id": str(admission.consent_record_id),
                        "idempotency_key": request.idempotency_key,
                    },
                )
            )

    async def _standing(
        self, tx: SendFloorTx, channel: str, normalized: str, hashed: str
    ) -> tuple[str | None, CurrentConsent | None]:
        if await tx.suppressed(channel, hashed):
            return "suppressed", None
        consent = await tx.current_consent(normalized, channel)
        if consent is None:
            return "no_consent", None
        if consent.state != "granted":
            return "consent_withdrawn", None
        return None, consent

    async def _caps(
        self, tx: SendFloorTx, request: SendRequest, hashed: str, now: datetime
    ) -> str | None:
        window = self.policy.per_address
        since = now - timedelta(hours=window.hours)
        if await tx.sends_since(request.channel, hashed, since) >= window.count:
            return "frequency_cap"
        if not self.policy.within_hours(now):
            return "quiet_hours"
        root = request.root_run_id
        if (
            root is not None
            and not await tx.run_has_recipient(root, request.channel, hashed)
            and await tx.run_recipients(root) >= self.policy.max_recipients_per_run
        ):
            return "recipient_cap"
        return None

    async def _block(self, tx: SendFloorTx, request: SendRequest, hashed: str, reason: str) -> None:
        await tx.write_log(
            self.ids.new_uuid(),
            LogRow(
                channel=request.channel,
                address_hash=hashed,
                outcome="blocked",
                tool_name=request.tool_name,
                tool_version=request.tool_version,
                blocked_reason=reason,
                idempotency_key=request.idempotency_key,
                run_id=request.run_id,
                root_run_id=request.root_run_id,
            ),
        )
        await tx.audit(self._refused(request, hashed, reason, replay=False))

    def _admitted(
        self, request: SendRequest, normalized: str, consent_id: uuid.UUID, *, replay: bool = False
    ) -> Admission:
        return Admission(
            admitted=True,
            consent_record_id=consent_id,
            unsubscribe_url=self.links.link(request.scope.tenant_id, request.channel, normalized),
            replay=replay,
        )

    def _refused(
        self, request: SendRequest, hashed: str, reason: str, *, replay: bool
    ) -> AuditEvent:
        details: dict[str, object] = {
            "reason_code": reason,
            "channel": request.channel,
            "address_hash": hashed,
            "idempotency_key": request.idempotency_key,
        }
        if replay:
            details["replay"] = True
        return self._event(request, REFUSED, details)

    def _event(self, request: SendRequest, action: str, details: dict[str, object]) -> AuditEvent:
        return AuditEvent(
            id=self.ids.new_uuid(),
            tenant_id=TenantId(request.scope.tenant_id),
            workspace_id=WorkspaceId(request.scope.workspace_id),
            actor_id=UserId(request.actor_id),
            action=action,
            resource_type="tool",
            resource_id=f"{request.tool_name}@{request.tool_version}",
            occurred_at=self.clock.now(),
            run_id=request.run_id,
            policy_decision="deny" if action == REFUSED else "allow",
            details=details,
        )


# ------------------------------------------------------------ records --


@dataclass(frozen=True)
class ConsentLedger:
    """Records a person's consent for the data's receiver (leadcare/01): an
    append-only row under the caller's own tenant."""

    store: ConsentStorePort
    clock: UtcClock
    ids: IdGenerator

    def row(
        self,
        scope: WorkScope,
        *,
        subject: str,
        channel: str,
        state: Literal["granted", "withdrawn"],
        source: str,
        notice_version: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """The record as written, for a caller that writes it in a transaction
        of its own (the intake, with its work item; leadcare R2.13)."""
        now = self.clock.now()
        return {
            "id": self.ids.new_uuid(),
            "tenant_id": scope.tenant_id,
            "subject_ref": normalize_address(channel, subject),
            "purpose": PURPOSE,
            "channel": channel,
            "state": state,
            "captured_at": now,
            "source": source,
            "evidence_ref": evidence_ref,
            "notice_version": notice_version,
            "withdrawn_at": now if state == "withdrawn" else None,
        }

    async def record(
        self,
        scope: WorkScope,
        *,
        subject: str,
        channel: str,
        state: Literal["granted", "withdrawn"],
        source: str,
        notice_version: str,
        evidence_ref: str | None = None,
    ) -> uuid.UUID:
        row = self.row(
            scope,
            subject=subject,
            channel=channel,
            state=state,
            source=source,
            notice_version=notice_version,
            evidence_ref=evidence_ref,
        )
        await self.store.insert(scope, row)
        return uuid.UUID(str(row["id"]))


@dataclass(frozen=True)
class UnsubscribeService:
    """The public opt-out route's two halves (R3.4): `check` only reads the
    token, `confirm` writes the suppression, once, under the token's tenant."""

    links: UnsubscribeLinks
    store: SuppressionStorePort

    def check(self, token: str) -> UnsubscribeClaim | None:
        return self.links.verify(token)

    async def confirm(self, token: str) -> UnsubscribeClaim | None:
        claim = self.links.verify(token)
        if claim is None:
            return None
        await self.store.suppress(
            claim.tenant_id, claim.channel, claim.address_hash, source="unsubscribe_link"
        )
        return claim


__all__ = [
    "CHANNELS",
    "REASONS",
    "Admission",
    "ConsentLedger",
    "MarketingSendPolicy",
    "SendFloorPolicy",
    "SendRequest",
    "UnsubscribeLinks",
    "UnsubscribeService",
    "address_hash",
    "load_send_floor_policy",
    "normalize_address",
]
