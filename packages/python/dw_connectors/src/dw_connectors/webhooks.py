"""Inbound signature verification, and Standard Webhooks signing
(connections-and-vault R4; ADR-0115 decision 8).

Pure: no I/O, no clock of its own. Every inbound door verifies through
`verify(scheme, message, keys, now=...)`, which drops a key past its
`not_after` (the version's `revoked_at`, 24 hours after a rotation, V4.20)
before any verifier sees it, so that hour is decided here and by no caller
(R4.4), and answers `rejected` for a scheme `VERIFIERS` does not hold.

W1's table holds the two schemes workflow-triggers R5.2 uses:

- `standard_webhooks_v1`: Standard Webhooks 1.0, HMAC-SHA256 over
  `{webhook-id}.{webhook-timestamp}.{body}` with the base64 key after `whsec_`,
  any `v1,` entry of `webhook-signature` matching, the timestamp within
  ±5 minutes of `now` (R4.1, R4.2);
- `static_header_token`: one header compared whole, in constant time (R4.3).

`standard_webhooks_v1a`, `meta_x_hub_signature_256` and `zalo_oa_zevent` join
with their first reader in W2 (spec "Ngoài phạm vi"). A refusal names its
reason and never repeats a value it received.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol

__all__ = [
    "TIMESTAMP_TOLERANCE",
    "VERIFIERS",
    "InboundMessage",
    "SignatureVerifier",
    "StandardWebhooksV1",
    "StaticHeaderToken",
    "Verdict",
    "VerifierKey",
    "sign_standard_webhook",
    "verify",
]

TIMESTAMP_TOLERANCE: Final = timedelta(minutes=5)
_SECRET_PREFIX: Final = "whsec_"

RejectReason = Literal[
    "scheme_unknown",
    "no_live_key",
    "signature_missing",
    "signature_mismatch",
    "timestamp_invalid",
    "timestamp_out_of_window",
    "token_missing",
    "token_mismatch",
]


@dataclass(frozen=True)
class InboundMessage:
    """The exact bytes received and their headers, names in any case."""

    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


@dataclass(frozen=True)
class VerifierKey:
    """One version of a signing secret. `not_after` is the version's
    `revoked_at`: None while it is current."""

    secret: str = field(repr=False)
    version: int
    not_after: datetime | None = None


@dataclass(frozen=True)
class Verdict:
    """`verified` with the key version that matched, or `rejected` with why."""

    verified: bool
    reason: RejectReason | None = None
    key_version: int | None = None

    @classmethod
    def accept(cls, key: VerifierKey) -> Verdict:
        return cls(verified=True, key_version=key.version)

    @classmethod
    def reject(cls, reason: RejectReason) -> Verdict:
        return cls(verified=False, reason=reason)


class SignatureVerifier(Protocol):
    def check(
        self, message: InboundMessage, keys: Sequence[VerifierKey], *, now: datetime
    ) -> Verdict:
        """Against keys `verify` has already found live."""
        ...


def _hmac_key(secret: str) -> bytes | None:
    encoded = secret.removeprefix(_SECRET_PREFIX)
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _signature(key: bytes, msg_id: str, timestamp: str, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")


def sign_standard_webhook(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    """The `webhook-signature` value of one key (`v1,<base64>`), for an
    outbound delivery and for a test's own message."""
    key = _hmac_key(secret)
    if key is None:
        raise ValueError("a Standard Webhooks secret is base64 after 'whsec_'")
    return f"v1,{_signature(key, msg_id, str(timestamp), body)}"


@dataclass(frozen=True)
class StandardWebhooksV1:
    """Standard Webhooks 1.0, symmetric (`v1`)."""

    def check(
        self, message: InboundMessage, keys: Sequence[VerifierKey], *, now: datetime
    ) -> Verdict:
        msg_id = message.header("webhook-id")
        timestamp = message.header("webhook-timestamp")
        signatures = message.header("webhook-signature")
        if not msg_id or not timestamp or not signatures:
            return Verdict.reject("signature_missing")
        try:
            sent_at = int(timestamp)
        except ValueError:
            return Verdict.reject("timestamp_invalid")
        if abs(now.timestamp() - sent_at) > TIMESTAMP_TOLERANCE.total_seconds():
            return Verdict.reject("timestamp_out_of_window")
        offered = [
            value
            for version, _, value in (entry.partition(",") for entry in signatures.split())
            if version == "v1" and value
        ]
        for key in keys:
            secret = _hmac_key(key.secret)
            if secret is None:
                continue
            expected = _signature(secret, msg_id, timestamp, message.body).encode("ascii")
            if any(
                hmac.compare_digest(expected, sig.encode("ascii", "replace")) for sig in offered
            ):
                return Verdict.accept(key)
        return Verdict.reject("signature_mismatch")


@dataclass(frozen=True)
class StaticHeaderToken:
    """A provider that sends a fixed token in one header. Which header is the
    inbound door's to say (workflow-triggers/02); `x-webhook-token` until then."""

    header: str = "x-webhook-token"

    def check(
        self, message: InboundMessage, keys: Sequence[VerifierKey], *, now: datetime
    ) -> Verdict:
        token = message.header(self.header)
        if not token:
            return Verdict.reject("token_missing")
        received = token.encode("utf-8")
        matched: VerifierKey | None = None
        # Every key compared, each in constant time, whichever matches.
        for key in keys:
            if hmac.compare_digest(received, key.secret.encode("utf-8")) and matched is None:
                matched = key
        return Verdict.accept(matched) if matched else Verdict.reject("token_mismatch")


VERIFIERS: Final[Mapping[str, SignatureVerifier]] = {
    "standard_webhooks_v1": StandardWebhooksV1(),
    "static_header_token": StaticHeaderToken(),
}


def verify(
    scheme: str,
    message: InboundMessage,
    keys: Sequence[VerifierKey],
    *,
    now: datetime,
) -> Verdict:
    """The one door: an unknown scheme is refused, and a key past its
    `not_after` is not a key."""
    verifier = VERIFIERS.get(scheme)
    if verifier is None:
        return Verdict.reject("scheme_unknown")
    live = [key for key in keys if key.not_after is None or now < key.not_after]
    if not live:
        return Verdict.reject("no_live_key")
    return verifier.check(message, live, now=now)
