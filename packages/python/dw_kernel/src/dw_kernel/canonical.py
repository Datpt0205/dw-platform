"""The one canonical hash of Studio's documents: RFC 8785 (JCS) bytes, sha256
(tenant-config R1, TC8; ADR-0109 decision 3).

Studio's hashes (the `studio.*` version envelope's content hash, definition
manifests, run manifests) come from here and nowhere else. It hashes the
value the application has already checked, as data: never `jsonb::text`,
never `json.dumps(sort_keys=True)`, whose key order is code points rather
than RFC 8785's UTF-16 code units, and which takes floats JCS would print
differently.

The document is refused, with a code and a JSON pointer and never its value,
rather than quietly repaired: a float of any kind (a non-integer travels as a
decimal string), an integer outside ±(2^53-1), a string or key not in NFC, a
key that is not a string, a lone surrogate, any other type, and a nesting
deeper than `MAX_DEPTH` (a self-referencing value among them). `to_nfc` is
the edge's repair, called before the check, never by the hash.

Not here, on purpose (ticket 01 step 4): the executor's `canonical_hash`
(idempotency keys of runs in flight), the release manifest's `manifest_ref`,
`dw_kernel.pagination.canonical_json` and the DW workflow hash built on it.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from dw_kernel.errors import DomainError

HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_SAFE_INTEGER = 2**53 - 1
# Deeper than any document a person builds; a self-referencing value stops
# here with a code instead of a RecursionError.
MAX_DEPTH = 64


class CanonicalError(DomainError):
    """A value that has no canonical form. `details`: `reason` and `pointer`
    (RFC 6901), never the value itself. A 422 `validation_failed`, as every
    `DomainError`."""


def _pointer(path: Sequence[str | int]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)


def _refuse(reason: str, path: Sequence[str | int]) -> CanonicalError:
    return CanonicalError(
        f"the document has no canonical form: {reason}",
        details={"reason": reason, "pointer": _pointer(path)},
    )


def _check_text(text: str, path: Sequence[str | int]) -> None:
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        raise _refuse("lone_surrogate", path)
    if not unicodedata.is_normalized("NFC", text):
        raise _refuse("not_nfc", path)


def _check(value: Any, path: list[str | int]) -> None:
    if len(path) > MAX_DEPTH:
        raise _refuse("depth_exceeded", path)
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise _refuse("integer_out_of_range", path)
        return
    if isinstance(value, float):
        raise _refuse("float_forbidden", path)
    if isinstance(value, str):
        _check_text(value, path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _refuse("key_not_string", path)
            _check_text(key, [*path, key])
            _check(item, [*path, key])
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check(item, [*path, index])
        return
    raise _refuse("type_forbidden", path)


def ensure_hashable(value: Any) -> None:
    """Raise `CanonicalError` unless `value` is a document `canonical_bytes`
    takes: dicts with string keys, lists, strings, integers in ±(2^53-1),
    booleans and None, every string and key in NFC."""
    _check(value, [])


def _utf16(key: str) -> bytes:
    # Big-endian UTF-16 compares byte for byte as its code units do (RFC 8785
    # 3.2.3), which differs from code points past the BMP.
    return key.encode("utf-16-be")


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value, key=_utf16)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    """The RFC 8785 serialization of a checked document, UTF-8."""
    ensure_hashable(value)
    # `json.dumps` escapes exactly what JCS escapes once nothing is ASCII-
    # escaped: the quote, the backslash and U+0000-U+001F (short forms where
    # JSON has them, else lowercase `\\u00xx`); everything else is literal.
    return json.dumps(
        _sorted(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    """`sha256:` and the 64 hex digits of the document's canonical bytes."""
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _nfc(value: Any, path: list[str | int]) -> Any:
    if len(path) > MAX_DEPTH:
        raise _refuse("depth_exceeded", path)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            normal = unicodedata.normalize("NFC", key) if isinstance(key, str) else key
            if normal in out:
                # Two keys one after NFC: picking either drops a value unseen.
                raise _refuse("nfc_key_collision", path)
            out[normal] = _nfc(item, [*path, normal])
        return out
    if isinstance(value, list):
        return [_nfc(item, [*path, index]) for index, item in enumerate(value)]
    return value


def to_nfc(value: Any) -> Any:
    """A new copy of `value` with every string and key in NFC, for the API's
    edge before the document is checked; the input is not changed. Two keys
    of one object that become one are refused (`nfc_key_collision`)."""
    return _nfc(value, [])


__all__ = [
    "HASH_PATTERN",
    "MAX_DEPTH",
    "MAX_SAFE_INTEGER",
    "CanonicalError",
    "canonical_bytes",
    "content_hash",
    "ensure_hashable",
    "to_nfc",
]
