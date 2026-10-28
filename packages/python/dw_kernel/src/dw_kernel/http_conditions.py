"""Conditional writes: the ETag a versioned resource carries, and what a caller's
`If-Match` and `If-None-Match` say about it (app-standards R3; RFC 9110 13.1).

Pure on purpose: the header grammar and the comparison rule are facts about
HTTP, and both the API dependency and any non-HTTP caller that one day compares
a version read them from here rather than from a second parser.

The ETag of a resource that turned conditional writes on is its record version
in quotes, strong: `"7"`. Three things follow from that and are the whole rule:

* Comparison is strong. A weak tag (`W/"7"`) is a statement about a
  representation, not about the record, so it matches no version (R3.2).
* A write must name exactly one version. `*`, a list, a repeated header or a
  value that is not an entity-tag are all refused as 428, like a missing one
  (R3.3, R3.8): accepting `*` or "any of these" would let a write through that
  never said which version it read.
* Parsing is all this module does. The comparison itself is the conditional
  write (`UPDATE ... WHERE version = :v`), so two writers holding the same
  version cannot both pass (R3.9).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from dw_kernel.errors import PreconditionRequiredError, UnsupportedMediaTypeError

# RFC 9110 8.8.3: entity-tag = [ "W/" ] DQUOTE *etagc DQUOTE, where etagc
# excludes DQUOTE, so a list (`"6", "7"`) can never match as one tag.
_ENTITY_TAG: Final = re.compile(r'(W/)?"([\x21\x23-\x7e\x80-\xff]*)"')
# A version this platform could have minted: what `etag_of` writes.
_VERSION: Final = re.compile(r"[0-9]{1,18}")

MERGE_PATCH: Final = "application/merge-patch+json"
# RFC 7396 is the semantics; plain JSON is accepted as the same document,
# because a client that does not know the media type sends a patch anyway.
PATCH_MEDIA_TYPES: Final = frozenset({MERGE_PATCH, "application/json"})


def etag_of(version: int) -> str:
    """The strong ETag of a record at ``version``."""
    return f'"{version}"'


@dataclass(frozen=True, slots=True)
class ExpectedVersion:
    """The version an `If-Match` names.

    ``version`` is None when the tag can never equal a record version: a weak
    tag, or a strong one this platform did not mint. Such a write is still
    conditional, it just fails the comparison (412), unlike a header that names
    no single tag at all (428)."""

    version: int | None

    def matches(self, current: int) -> bool:
        return self.version is not None and self.version == current


def _refuse(reason: str) -> PreconditionRequiredError:
    return PreconditionRequiredError(
        "this write must name the version it read in one strong If-Match ETag",
        details={"header": "If-Match", "reason": reason},
    )


def parse_if_match(values: Sequence[str] | None) -> ExpectedVersion:
    """Every `If-Match` value the request carried, as one expected version.

    Raises :class:`PreconditionRequiredError` for no header, a repeated one,
    `*`, a list, or a value that is not one entity-tag.
    """
    if not values:
        raise _refuse("missing")
    if len(values) != 1:
        raise _refuse("repeated")
    # `*` is no entity-tag, so it is refused here with every other value that
    # names no single version.
    value = values[0].strip()
    match = _ENTITY_TAG.fullmatch(value)
    if match is None:
        raise _refuse("unparseable")
    weak, opaque = match.groups()
    if weak or not _VERSION.fullmatch(opaque):
        return ExpectedVersion(version=None)
    return ExpectedVersion(version=int(opaque))


def parse_if_none_match(values: Sequence[str] | None) -> bool:
    """True when a create says "only if nothing is there" (`If-None-Match: *`).

    A create is the only write that reads this header, and the only form it
    honours is `*` (R3.4); a tag list on a create names a version of something
    that should not exist yet, so it is refused rather than ignored."""
    if not values:
        return False
    if len(values) == 1 and values[0].strip() == "*":
        return True
    raise PreconditionRequiredError(
        "a create honours only If-None-Match: *",
        details={"header": "If-None-Match", "reason": "unsupported"},
    )


def require_patch_media_type(content_type: str | None) -> None:
    """Refuse a patch whose body is not a merge patch (415, R3.10): a JSON Patch
    (`application/json-patch+json`) applied as a merge patch would silently do
    something else entirely."""
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in PATCH_MEDIA_TYPES:
        raise UnsupportedMediaTypeError(
            "a patch is a JSON merge patch (application/merge-patch+json)",
            details={"accepted": sorted(PATCH_MEDIA_TYPES)},
        )


def apply_merge_patch(target: object, patch: object) -> object:
    """RFC 7396: a member set to null is removed, an absent one is kept, an
    object is merged member by member, and anything else replaces the target."""
    if not isinstance(patch, Mapping):
        return patch
    merged: dict[str, object] = dict(target) if isinstance(target, Mapping) else {}
    for name, value in patch.items():
        if value is None:
            merged.pop(name, None)
        else:
            merged[name] = apply_merge_patch(merged.get(name), value)
    return merged
