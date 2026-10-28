"""`If-Match`, `If-None-Match`, the ETag and the merge patch (app-standards R3)."""

from __future__ import annotations

import pytest

from dw_kernel.errors import ErrorCode, PreconditionRequiredError, UnsupportedMediaTypeError
from dw_kernel.http_conditions import (
    ExpectedVersion,
    apply_merge_patch,
    etag_of,
    parse_if_match,
    parse_if_none_match,
    require_patch_media_type,
)

pytestmark = pytest.mark.unit


def test_the_etag_of_a_version_is_the_version_in_quotes() -> None:
    assert etag_of(7) == '"7"'


def test_a_strong_etag_names_its_version() -> None:
    expected = parse_if_match(['"7"'])
    assert expected == ExpectedVersion(7)
    assert expected.matches(7)
    assert not expected.matches(6)


@pytest.mark.parametrize("value", ['W/"7"', '"abc"', '"7a"'])
def test_a_weak_or_foreign_etag_is_conditional_and_matches_no_version(value: str) -> None:
    # R3.2: `W/"7"` is a 412 at version 7, not a 428 and never a match.
    expected = parse_if_match([value])
    assert expected.version is None
    assert not expected.matches(7)


@pytest.mark.parametrize(
    "values",
    [None, [], ["*"], ['"6", "7"'], ['"6"', '"7"'], ["7"], ['"7'], [""]],
    ids=["absent", "empty", "wildcard", "list", "repeated", "unquoted", "open", "blank"],
)
def test_a_write_that_names_no_single_strong_tag_is_428(values: list[str] | None) -> None:
    # R3.3, R3.8: accepting `*` or a list would let through a write that never
    # said which version it read.
    with pytest.raises(PreconditionRequiredError) as raised:
        parse_if_match(values)
    assert raised.value.code is ErrorCode.PRECONDITION_REQUIRED


def test_if_none_match_star_is_the_only_form_a_create_honours() -> None:
    assert parse_if_none_match(None) is False
    assert parse_if_none_match(["*"]) is True
    with pytest.raises(PreconditionRequiredError):
        parse_if_none_match(['"7"'])
    with pytest.raises(PreconditionRequiredError):
        parse_if_none_match(["*", "*"])


@pytest.mark.parametrize(
    "content_type",
    ["application/merge-patch+json", "application/json", "Application/JSON; charset=utf-8"],
)
def test_a_merge_patch_comes_as_either_json_media_type(content_type: str) -> None:
    require_patch_media_type(content_type)


@pytest.mark.parametrize("content_type", ["application/json-patch+json", "text/plain", None])
def test_any_other_patch_media_type_is_415(content_type: str | None) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        require_patch_media_type(content_type)


def test_a_merge_patch_removes_nulls_merges_objects_and_keeps_the_rest() -> None:
    # R3.5, RFC 7396.
    target = {"a": 1, "b": {"c": 0, "d": 2}, "e": "kept"}
    patched = apply_merge_patch(target, {"a": None, "b": {"c": 1}})
    assert patched == {"b": {"c": 1, "d": 2}, "e": "kept"}
    assert target == {"a": 1, "b": {"c": 0, "d": 2}, "e": "kept"}, "the target is not changed"


def test_an_empty_merge_patch_changes_nothing() -> None:
    assert apply_merge_patch({"a": 1}, {}) == {"a": 1}


def test_a_merge_patch_replaces_what_is_not_an_object() -> None:
    assert apply_merge_patch({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}
    assert apply_merge_patch({"a": 1}, {"a": {"b": None}}) == {"a": {}}
