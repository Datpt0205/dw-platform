"""`dw.toolset/v1`, the toolset an agent version embeds (tools-and-skills
ticket 02: R4.3, R4.5; ADR-0116 decision 6, amended 2026-11-04).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_studio.core.domain.artifacts import DocumentInvalidError, Reference, TargetKind, Usage
from dw_studio.core.domain.toolset import (
    ConnectorActionEntry,
    ObjectCrudEntry,
    ToolsetSpec,
    extract_toolset,
    parse_toolset,
    validate_toolset,
)

pytestmark = pytest.mark.unit

LEAD = "00000000-0000-4000-8000-0000000000a1"


def objects(count: int, operations: tuple[str, ...] = ("search", "get")) -> list[dict[str, Any]]:
    return [
        {"kind": "object_crud", "object": str(uuid.UUID(int=n + 1)), "operations": list(operations)}
        for n in range(count)
    ]


def action(name: str = "email.send", binding: str = "hop_thu") -> dict[str, Any]:
    return {
        "kind": "connector_action",
        "connector": "smtp@1.0.0",
        "action": name,
        "binding": binding,
    }


def codes(toolset: Any) -> list[tuple[str, str]]:
    return [(p.pointer, p.code) for p in validate_toolset(toolset)]


# ------------------------------------------------------------------- R4.5 --


def test_forty_tools_are_taken_and_forty_one_are_too_many() -> None:
    """R4.5: twenty object entries of two operations are forty tools; one
    action more is forty-one. Counted by entry, both would pass."""
    assert codes({"tools": objects(20)}) == []

    assert codes({"tools": [*objects(20), action()]}) == [("/toolset/tools", "too_many_tools")]


def test_an_object_entry_counts_a_tool_per_enabled_operation() -> None:
    assert codes({"tools": objects(40, ("search",))}) == []
    assert codes({"tools": objects(21)}) == [("/toolset/tools", "too_many_tools")]


def test_a_kind_outside_w1_is_unsupported_at_its_kind() -> None:
    problems = codes({"tools": [{"kind": "http", "url": "https://example.vn"}, {"kind": 5}]})

    assert problems == [
        ("/toolset/tools/0/kind", "toolset.kind_unsupported"),
        ("/toolset/tools/1/kind", "toolset.kind_unsupported"),
    ]


def test_two_entries_giving_one_tool_are_a_duplicate() -> None:
    lead = {"kind": "object_crud", "object": LEAD, "operations": ["search"]}
    both = {"kind": "object_crud", "object": LEAD, "operations": ["get", "search"]}

    assert codes({"tools": [lead, both]}) == [("/toolset/tools/1", "toolset.duplicate_tool")]
    assert codes({"tools": [action(binding="a"), action(binding="b")]}) == [
        ("/toolset/tools/1", "toolset.duplicate_tool")
    ]


def test_every_problem_is_returned_at_once() -> None:
    problems = codes(
        {
            "tools": [
                {"kind": "object_crud", "object": "khong-phai-id", "operations": []},
                {"kind": "connector_action", "connector": "smtp", "action": "send"},
                {"kind": "mcp"},
            ],
            "skills": [],
        }
    )

    assert ("/toolset/skills", "not_allowed") in problems
    assert ("/toolset/tools/0/object", "wrong_type") in problems
    assert ("/toolset/tools/0/operations", "too_short") in problems
    assert ("/toolset/tools/1/connector", "value_not_allowed") in problems
    assert ("/toolset/tools/1/action", "value_not_allowed") in problems
    assert ("/toolset/tools/1/binding", "required") in problems
    assert ("/toolset/tools/2/kind", "toolset.kind_unsupported") in problems


def test_an_operation_outside_search_and_get_is_refused() -> None:
    entry = {"kind": "object_crud", "object": LEAD, "operations": ["search", "delete"]}

    assert codes({"tools": [entry]}) == [("/toolset/tools/0/operations/1", "value_not_allowed")]


def test_a_toolset_that_is_not_an_object_is_one_problem() -> None:
    assert codes([]) == [("/toolset", "wrong_type")]
    assert codes({"tools": {}}) == [("/toolset/tools", "wrong_type")]


# ------------------------------------------------------------------- R4.3 --


def test_an_action_whose_tool_name_passes_64_characters_is_refused_at_seal() -> None:
    """R4.3: `x.` + 61 letters is 64 characters as `x__...`; one more is 65."""
    at_64 = "x." + "a" * 61
    at_65 = "x." + "a" * 62

    assert codes({"tools": [action(at_64)]}) == []
    assert codes({"tools": [action(at_65)]}) == [("/toolset/tools/0/action", "tool_name_too_long")]


# -------------------------------------------------------------- extraction --


def test_an_object_and_an_action_give_exactly_three_references() -> None:
    """R4.5: the object is read, the connector invoked, the binding bound,
    each at its entry's pointer; no version is in the document."""
    toolset = {
        "tools": [{"kind": "object_crud", "object": LEAD, "operations": ["search"]}, action()]
    }

    assert extract_toolset(toolset) == [
        Reference(TargetKind.ARTIFACT, LEAD, Usage.READ, "/toolset/tools/0"),
        Reference(TargetKind.CONNECTOR, "smtp@1.0.0", Usage.INVOKE, "/toolset/tools/1"),
        Reference(TargetKind.BINDING, "hop_thu", Usage.BIND, "/toolset/tools/1"),
    ]


def test_an_entry_that_does_not_parse_gives_no_reference() -> None:
    assert extract_toolset({"tools": [{"kind": "http"}, {"kind": "object_crud"}]}) == []
    assert extract_toolset(None) == []


def test_a_parsed_toolset_reads_as_its_document_does() -> None:
    document = {"tools": [{"kind": "object_crud", "object": LEAD, "operations": ["get"]}, action()]}

    spec = parse_toolset(document)

    assert isinstance(spec, ToolsetSpec)
    assert isinstance(spec.tools[0], ObjectCrudEntry)
    assert isinstance(spec.tools[1], ConnectorActionEntry)
    assert spec.tools[0].pin() == ("artifact", LEAD)
    assert spec.tools[1].pin() == ("connector", "smtp@1.0.0")
    assert spec.tools[1].tool_name() == "email__send"
    assert validate_toolset(spec) == []
    assert extract_toolset(spec) == extract_toolset(document)


def test_parse_refuses_what_validate_refuses() -> None:
    with pytest.raises(DocumentInvalidError) as caught:
        parse_toolset({"tools": [*objects(20), action()]})

    assert [p.code for p in caught.value.problems] == ["too_many_tools"]
