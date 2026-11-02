"""`dw_kernel.canonical`: RFC 8785 bytes and one content hash (tenant-config
ticket 01: R1.1-R1.4, TC8).

`rfc8785` (dev only) is the reference the bytes are compared with; the
kernel itself imports nothing outside the standard library.
"""

from __future__ import annotations

import copy
import hashlib
import random
import unicodedata
from decimal import Decimal
from typing import Any

import pytest
import rfc8785

from dw_kernel.canonical import (
    HASH_PATTERN,
    MAX_DEPTH,
    MAX_SAFE_INTEGER,
    CanonicalError,
    canonical_bytes,
    content_hash,
    ensure_hashable,
    to_nfc,
)

pytestmark = pytest.mark.unit

# A key in U+E000-U+FFFF and one past the BMP: UTF-16 code units put the
# emoji (D83D DE00) first, code points put U+FF21 first (ticket 01, M2).
# Not RFC 8785's U+FB33, which NFC decomposes (a composition exclusion).
BMP_HIGH, ASTRAL = chr(0xFF21), chr(0x1F600)

_CHARS = [
    *"abcxyzABC019 ",
    *(chr(c) for c in range(0x00, 0x20)),
    *(chr(c) for c in (0x7F, 0x2028, 0x2029, 0xFFFF, 0xE000)),
    BMP_HIGH,
    ASTRAL,
    chr(0x1F9D1),
    '"',
    "\\",
    "/",
    *"ắằẳẵặđĐơưỡộ",
]


def _text(rng: random.Random) -> str:
    return unicodedata.normalize(
        "NFC", "".join(rng.choice(_CHARS) for _ in range(rng.randint(0, 8)))
    )


def _value(rng: random.Random, depth: int) -> Any:
    kind = rng.randrange(8 if depth < 3 else 5)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.choice(
            [0, -1, 1, MAX_SAFE_INTEGER, -MAX_SAFE_INTEGER, rng.randint(-(10**12), 10**12)]
        )
    if kind in (3, 4):
        return _text(rng)
    if kind in (5, 6):
        keys = {_text(rng) for _ in range(rng.randint(0, 5))}
        if rng.random() < 0.3:
            keys |= {BMP_HIGH + _text(rng), ASTRAL + _text(rng)}
        return {key: _value(rng, depth + 1) for key in keys}
    return [_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]


def test_the_rfc_8785_examples_without_numbers() -> None:
    """R1.1: the key-order example of 3.2.3 (its U+FB33, which NFC decomposes,
    swapped for U+FF21) and the 3.2.2 example without
    `numbers`, byte for byte."""
    order = {
        "€": "Euro Sign",
        "\r": "Carriage Return",
        BMP_HIGH: "Fullwidth Latin Capital Letter A",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "ö": "Latin Small Letter O With Diaeresis",
    }
    expected_order = ["\r", "1", "\u0080", "ö", "€", "\U0001f600", BMP_HIGH]
    assert list(rfc8785_keys(canonical_bytes(order))) == expected_order
    literals = {"literals": [None, True, False], "string": '€$\u000f\nA\'B"\\\\"/'}
    assert canonical_bytes(literals) == (
        b'{"literals":[null,true,false],"string":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )


def rfc8785_keys(raw: bytes) -> list[str]:
    import json

    return list(json.loads(raw))


def test_the_bytes_match_the_reference_on_20_000_documents() -> None:
    """R1.1 (TC8): control characters, U+007F, U+2028, U+FFFF, keys past the
    BMP beside keys in U+E000-U+FFFF, Vietnamese, quotes and backslashes in
    keys and values, integers to ±(2^53-1)."""
    rng = random.Random(8785)
    astral_pairs = 0
    for _ in range(20_000):
        document = {"d": _value(rng, 0), BMP_HIGH: 1, ASTRAL: _text(rng)}
        astral_pairs += 1
        assert canonical_bytes(document) == rfc8785.dumps(document)
    assert astral_pairs == 20_000


def test_the_hash_is_sha256_of_the_canonical_bytes() -> None:
    document: Any = {"b": [1, "đ"], "a": None}
    found = content_hash(document)
    assert HASH_PATTERN.fullmatch(found)
    assert found == "sha256:" + hashlib.sha256(rfc8785.dumps(document)).hexdigest()


def _refused(value: Any) -> CanonicalError:
    with pytest.raises(CanonicalError) as refused:
        content_hash(value)
    return refused.value


@pytest.mark.parametrize("bad", [1.0, 0.5, float("nan"), float("inf"), float("-inf")])
def test_any_float_is_refused_with_no_hash(bad: float) -> None:
    """R1.2 (TC8): a non-integer travels as a decimal string."""
    error = _refused({"a": bad})
    assert error.details == {"reason": "float_forbidden", "pointer": "/a"}
    assert error.code == "validation_failed"


def test_integers_are_held_to_the_safe_range() -> None:
    """R1.3 (TC8)."""
    for ok in (MAX_SAFE_INTEGER, -MAX_SAFE_INTEGER):
        assert HASH_PATTERN.fullmatch(content_hash([ok]))
    for bad in (2**53, -(2**53)):
        assert _refused([bad]).details == {"reason": "integer_out_of_range", "pointer": "/0"}


def test_text_not_in_nfc_is_refused_in_values_and_keys() -> None:
    """R1.4 (TC8): the hash refuses, it does not repair; without the check
    the two forms would hash differently."""
    nfc = unicodedata.normalize("NFC", "Ngưỡng điểm")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    assert _refused({"x": nfd}).details == {"reason": "not_nfc", "pointer": "/x"}
    assert _refused({nfd: 1}).details["reason"] == "not_nfc"
    assert HASH_PATTERN.fullmatch(content_hash({nfc: nfc}))
    assert rfc8785.dumps({nfc: 1}) != rfc8785.dumps({nfd: 1})


@pytest.mark.parametrize(
    ("value", "reason", "pointer"),
    [
        ({1: "x"}, "key_not_string", ""),
        ({"a": ["\ud800"]}, "lone_surrogate", "/a/0"),
        ({"\udfff": 1}, "lone_surrogate", "/\udfff"),
        ({"a": Decimal("1.5")}, "type_forbidden", "/a"),
        ({"a": b"x"}, "type_forbidden", "/a"),
        ({"a": (1, 2)}, "type_forbidden", "/a"),
        ({"a/b": {"c~d": 1.5}}, "float_forbidden", "/a~1b/c~0d"),
    ],
)
def test_every_other_refusal_has_its_code_and_pointer(
    value: Any, reason: str, pointer: str
) -> None:
    error = _refused(value)
    assert error.details == {"reason": reason, "pointer": pointer}
    assert "1.5" not in str(error.details)


def test_a_self_referencing_or_too_deep_value_is_refused_not_overflowed() -> None:
    looped: dict[str, Any] = {}
    looped["self"] = looped
    assert _refused(looped).details["reason"] == "depth_exceeded"
    deep: Any = 1
    for _ in range(MAX_DEPTH + 1):
        deep = [deep]
    assert _refused(deep).details["reason"] == "depth_exceeded"
    with pytest.raises(CanonicalError):
        to_nfc(looped)


def test_ensure_hashable_writes_nothing() -> None:
    document = {"b": [{"z": 1, "a": 2}], "a": "x"}
    before = copy.deepcopy(document)
    ensure_hashable(document)
    canonical_bytes(document)
    assert document == before and list(document) == ["b", "a"]


def test_to_nfc_repairs_a_copy_that_hashes_as_the_nfc_document() -> None:
    """R1.4 (TC8): nested NFD keys and values, in objects and lists."""
    nfc = {"Ngưỡng": ["điểm", {"Độ": "ẵ"}], "ok": 1}
    nfd: Any = {
        unicodedata.normalize("NFD", "Ngưỡng"): [
            unicodedata.normalize("NFD", "điểm"),
            {unicodedata.normalize("NFD", "Độ"): unicodedata.normalize("NFD", "ẵ")},
        ],
        "ok": 1,
    }
    before = copy.deepcopy(nfd)
    repaired = to_nfc(nfd)
    assert content_hash(repaired) == content_hash(nfc)
    assert nfd == before


def test_two_keys_one_after_nfc_are_refused_not_chosen() -> None:
    """R1.4 (TC8): picking either key would drop the other's value."""
    clash = {"x": {unicodedata.normalize("NFC", "é"): 1, unicodedata.normalize("NFD", "é"): 2}}
    with pytest.raises(CanonicalError) as refused:
        to_nfc(clash)
    assert refused.value.details == {"reason": "nfc_key_collision", "pointer": "/x"}
