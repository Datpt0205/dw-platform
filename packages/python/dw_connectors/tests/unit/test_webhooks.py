"""The inbound signature module (connections-and-vault R4.1-R4.4; CV11).

`standardwebhooks`, the specification's reference library, is the oracle:
what it signs this module verifies, and what this module signs it verifies.
"""

from __future__ import annotations

import base64
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from standardwebhooks import Webhook

from dw_connectors.webhooks import (
    VERIFIERS,
    InboundMessage,
    VerifierKey,
    sign_standard_webhook,
    verify,
)

pytestmark = pytest.mark.unit

SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()
NEW_SECRET = "whsec_" + base64.b64encode(b"n" * 32).decode()
BODY = b'{"lead":{"email":"a@b.vn"}}'
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _signed(
    secret: str = SECRET, *, at: datetime = NOW, body: bytes = BODY, msg_id: str = "msg_1"
) -> InboundMessage:
    stamp = int(at.timestamp())
    return InboundMessage(
        headers={
            "Webhook-Id": msg_id,
            "Webhook-Timestamp": str(stamp),
            "Webhook-Signature": sign_standard_webhook(secret, msg_id, stamp, body),
        },
        body=body,
    )


def _key(secret: str = SECRET, version: int = 1, not_after: datetime | None = None) -> VerifierKey:
    return VerifierKey(secret=secret, version=version, not_after=not_after)


# -- R4.1: the reference library agrees, both ways ----------------------------------------


def test_a_message_the_reference_signs_is_verified() -> None:
    """R4.1: within the window, by the spec's own implementation."""
    now = datetime.now(UTC)
    signature = Webhook(SECRET).sign("msg_ref", now, BODY.decode())
    message = InboundMessage(
        headers={
            "webhook-id": "msg_ref",
            "webhook-timestamp": str(int(now.timestamp())),
            "webhook-signature": signature,
        },
        body=BODY,
    )

    verdict = verify("standard_webhooks_v1", message, [_key()], now=now)

    assert verdict.verified and verdict.key_version == 1


def test_what_this_module_signs_the_reference_verifies() -> None:
    now = datetime.now(UTC)
    message = _signed(at=now)

    Webhook(SECRET).verify(BODY, {k.lower(): v for k, v in message.headers.items()})


@pytest.mark.parametrize("skew", [timedelta(minutes=-4, seconds=-59), timedelta(minutes=4)])
def test_inside_five_minutes_either_way_is_verified(skew: timedelta) -> None:
    verdict = verify("standard_webhooks_v1", _signed(at=NOW + skew), [_key()], now=NOW)

    assert verdict.verified


# -- R4.2: what is refused ------------------------------------------------------------------


def test_one_byte_changed_is_refused() -> None:
    """R4.2 (CV11)."""
    message = _signed()
    tampered = InboundMessage(headers=message.headers, body=message.body.replace(b"a@", b"e@"))

    verdict = verify("standard_webhooks_v1", tampered, [_key()], now=NOW)

    assert not verdict.verified and verdict.reason == "signature_mismatch"


@pytest.mark.parametrize("skew", [timedelta(minutes=5, seconds=1), timedelta(minutes=-6)])
def test_a_timestamp_outside_five_minutes_is_refused(skew: timedelta) -> None:
    """R4.2 (CV11): the clock is the one handed in."""
    verdict = verify("standard_webhooks_v1", _signed(at=NOW + skew), [_key()], now=NOW)

    assert not verdict.verified and verdict.reason == "timestamp_out_of_window"


@pytest.mark.parametrize("missing", ["webhook-id", "webhook-timestamp", "webhook-signature"])
def test_a_missing_header_is_refused(missing: str) -> None:
    message = _signed()
    headers = {k: v for k, v in message.headers.items() if k.lower() != missing}

    verdict = verify(
        "standard_webhooks_v1", InboundMessage(headers, message.body), [_key()], now=NOW
    )

    assert not verdict.verified and verdict.reason == "signature_missing"


def test_a_signature_by_another_key_is_refused_and_says_nothing_it_received() -> None:
    message = _signed(NEW_SECRET)

    verdict = verify("standard_webhooks_v1", message, [_key()], now=NOW)

    assert not verdict.verified and verdict.reason == "signature_mismatch"
    signature = message.headers["Webhook-Signature"]
    assert signature not in repr(verdict) and "msg_1" not in repr(verdict)


def test_a_timestamp_that_is_not_a_number_is_refused() -> None:
    message = _signed()
    headers = {**message.headers, "Webhook-Timestamp": "soon"}

    verdict = verify("standard_webhooks_v1", InboundMessage(headers, BODY), [_key()], now=NOW)

    assert verdict.reason == "timestamp_invalid"


# -- R4.3: a static token ----------------------------------------------------------------------


def test_the_right_token_is_verified_and_a_wrong_one_refused() -> None:
    keys = [_key("t0ken-value")]
    right = InboundMessage({"X-Webhook-Token": "t0ken-value"}, BODY)
    wrong = InboundMessage({"X-Webhook-Token": "t0ken-valuf"}, BODY)
    absent = InboundMessage({}, BODY)

    assert verify("static_header_token", right, keys, now=NOW).verified
    assert verify("static_header_token", wrong, keys, now=NOW).reason == "token_mismatch"
    assert verify("static_header_token", absent, keys, now=NOW).reason == "token_missing"


def test_the_token_is_compared_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """R4.3 (CV11): every key, through `hmac.compare_digest`, never `==`."""
    compared: list[tuple[Any, Any]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        compared.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    keys = [_key("first-token", 1), _key("second-token", 2)]

    verdict = verify(
        "static_header_token",
        InboundMessage({"x-webhook-token": "first-token"}, BODY),
        keys,
        now=NOW,
    )

    assert verdict.verified and verdict.key_version == 1
    assert compared == [(b"first-token", b"first-token"), (b"first-token", b"second-token")]


# -- R4.4: rotation ------------------------------------------------------------------------------


def test_during_a_rotation_both_the_old_key_and_the_new_one_verify() -> None:
    """R4.4: the old version lives until its `revoked_at`, 24 hours on."""
    keys = [_key(SECRET, 1, not_after=NOW + timedelta(hours=23)), _key(NEW_SECRET, 2)]

    old = verify("standard_webhooks_v1", _signed(SECRET), keys, now=NOW)
    new = verify("standard_webhooks_v1", _signed(NEW_SECRET), keys, now=NOW)

    assert (old.verified, old.key_version) == (True, 1)
    assert (new.verified, new.key_version) == (True, 2)


@pytest.mark.parametrize("scheme", sorted(VERIFIERS))
def test_a_key_past_its_not_after_is_no_key(scheme: str) -> None:
    """R4.4: dropped here, by the clock handed in, not by the caller."""
    secret = SECRET if scheme == "standard_webhooks_v1" else "old-token"
    expired = [_key(secret, 1, not_after=NOW - timedelta(seconds=1)), _key(NEW_SECRET, 2)]
    message = (
        _signed(SECRET)
        if scheme == "standard_webhooks_v1"
        else InboundMessage({"x-webhook-token": "old-token"}, BODY)
    )

    verdict = verify(scheme, message, expired, now=NOW)

    assert not verdict.verified


def test_a_key_at_its_not_after_has_ended() -> None:
    keys = [_key(SECRET, 1, not_after=NOW)]

    assert verify("standard_webhooks_v1", _signed(), keys, now=NOW).reason == "no_live_key"


@pytest.mark.parametrize(
    "scheme", ["standard_webhooks_v1a", "meta_x_hub_signature_256", "zalo_oa_zevent", "none"]
)
def test_a_scheme_w1_does_not_hold_is_refused(scheme: str) -> None:
    """R4.4: W2 brings these with their first reader."""
    verdict = verify(scheme, _signed(), [_key()], now=NOW)

    assert not verdict.verified and verdict.reason == "scheme_unknown"


def test_w1_holds_exactly_the_two_schemes_its_reader_uses() -> None:
    assert set(VERIFIERS) == {"standard_webhooks_v1", "static_header_token"}


def test_a_key_prints_no_secret() -> None:
    assert SECRET not in repr(_key())
