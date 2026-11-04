"""What the `Idempotency-Key` fingerprint of a connection write hashes
(connections-and-vault R5.1; R1.2): the body with every secret value dropped
and the field names kept, so the stored hash cannot be guessed back to a
password, and two sends differing only in a value are the same request.
"""

from __future__ import annotations

import json

import pytest

from dw_api.routes.v1.connections import _without_secret_values

pytestmark = pytest.mark.unit

CANARY = "canary-c04-fingerprint"


def _body(**secrets: str) -> bytes:
    return json.dumps(
        {"name": "Hộp thư", "external_account": "a@x.vn", "secrets": secrets}
    ).encode()


def test_the_values_are_dropped_and_the_names_kept() -> None:
    kept = _without_secret_values(_body(password=CANARY, api_key=CANARY))

    assert CANARY.encode() not in kept
    assert json.loads(kept)["secrets"] == ["api_key", "password"]
    assert json.loads(kept)["external_account"] == "a@x.vn"


def test_two_sends_differing_only_in_a_value_are_one_request() -> None:
    assert _without_secret_values(_body(password="one")) == _without_secret_values(
        _body(password="two")
    )
    assert _without_secret_values(_body(password="one")) != _without_secret_values(
        _body(api_key="one")
    )


@pytest.mark.parametrize(
    "body",
    [
        b"{not json " + CANARY.encode(),
        json.dumps({"secrets": CANARY}).encode(),
        json.dumps({"secrets": [CANARY]}).encode(),
    ],
)
def test_a_body_of_another_shape_never_carries_its_value_through(body: bytes) -> None:
    assert CANARY.encode() not in _without_secret_values(body)


def test_a_body_without_secrets_is_hashed_whole() -> None:
    body = json.dumps({"name": "Đổi tên"}).encode()

    assert json.loads(_without_secret_values(body)) == {"name": "Đổi tên"}
