"""Unit: the `agent` kind's document, validator, extractor and registry entry
(agent-builder ticket 02 step 1: R1.3, R1.6, R1.8, R2.1, R2.4; AB1, AB2, AB10).

Every case runs the kind's own `validate` and `extract`, as the envelope's
save hook (warnings) and seal (422) run them, and reads each problem at its
JSON pointer.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, cast

import pytest

from dw_studio.agents.application.publish import AgentPublishHook
from dw_studio.agents.application.settings import (
    AGENTS_AUTHOR_SCOPE,
    AGENTS_MANAGE_SETTINGS_SCOPE,
)
from dw_studio.agents.domain.document import (
    AGENT_DOCUMENT_SCHEMA,
    AGENT_FRAME_KEY,
    extract_agent,
    validate_agent,
)
from dw_studio.core.domain.artifacts import Reference, TargetKind, Usage
from dw_studio.kinds import agent_kind
from dw_studio.lifecycle.application.service import VERSIONS_SUBMIT_SCOPE
from dw_studio.testing.objects import running_kinds

pytestmark = pytest.mark.unit

OBJECT = uuid.uuid4()


def agent(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "display": {"name": "Trợ lý lead"},
        "instructions": "Trả lời bằng tiếng Việt, ngắn gọn.",
        "model": {"profile": "balanced"},
        "toolset": {
            "tools": [
                {"kind": "object_crud", "object": str(OBJECT), "operations": ["search", "get"]}
            ]
        },
        "field_caps": {"mkt_lead": ["name", "email"]},
        "purpose": "Trả lời câu hỏi về lead",
    }
    document.update(overrides)
    return document


def found(document: Any) -> list[tuple[str, str]]:
    return [(p.pointer, p.code) for p in validate_agent(document)]


def test_a_full_w1_document_passes() -> None:
    assert found(agent()) == []
    assert found(agent(route_class="vn_only")) == []


def test_the_smallest_document_passes() -> None:
    minimal = {
        "display": {"name": "A"},
        "instructions": "",
        "model": {"profile": "luna"},
    }
    assert found(minimal) == []


# ---- R1.3 (AB10): a key outside the schema --------------------------------------


@pytest.mark.parametrize("w2", ["sub_agents", "limits", "knowledge", "links", "surfaces"])
def test_a_w2_section_is_a_key_outside_the_schema(w2: str) -> None:
    assert found(agent(**{w2: []})) == [(f"/{w2}", "not_allowed")]


def test_a_key_inside_a_section_is_refused_at_its_pointer() -> None:
    assert found(agent(display={"name": "A", "avatar": "x"})) == [
        ("/display/avatar", "not_allowed")
    ]


@pytest.mark.parametrize("missing", ["display", "instructions", "model"])
def test_a_required_section_is_named(missing: str) -> None:
    document = agent()
    del document[missing]
    assert found(document) == [(f"/{missing}", "required")]


def test_a_document_that_is_not_an_object_is_one_problem() -> None:
    assert found(["display"]) == [("", "document_not_object")]


def test_a_problem_never_quotes_the_value() -> None:
    problems = validate_agent(agent(display={"name": 7}, route_class="SECRET-route"))
    assert problems and all("SECRET" not in p.detail for p in problems)


# ---- R1.6: route_class tightens only, from the three routes ----------------------


@pytest.mark.parametrize("route", ["vn_only", "cross_border_minimised", "cross_border_full"])
def test_each_route_class_passes(route: str) -> None:
    assert found(agent(route_class=route)) == []


def test_no_route_class_passes() -> None:
    document = agent()
    document.pop("route_class", None)
    assert found(document) == []


def test_a_route_class_outside_the_set_is_named() -> None:
    assert found(agent(route_class="eu")) == [("/route_class", "value_not_allowed")]


# ---- the other W1 sections ------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "value", "pointer"),
    [
        ("model", {"profile": "Balanced!"}, "/model/profile"),
        ("model", {}, "/model/profile"),
        ("field_caps", {"MKT": ["name"]}, "/field_caps/MKT"),
        ("field_caps", {"mkt_lead": ["Name"]}, "/field_caps/mkt_lead/0"),
        ("purpose", "p" * 501, "/purpose"),
        ("display", {"name": ""}, "/display/name"),
        ("instructions", 7, "/instructions"),
    ],
)
def test_a_w1_section_out_of_shape_is_named_at_its_pointer(
    section: str, value: Any, pointer: str
) -> None:
    assert [p for p, _ in found(agent(**{section: value}))] == [pointer]


def test_the_toolset_is_checked_by_its_own_validator() -> None:
    """`validate_toolset` of tools-and-skills/02, never a copy: its codes and
    pointers under `/toolset`."""
    toolset = {"tools": [{"kind": "http", "url": "https://x"}]}
    assert found(agent(toolset=toolset)) == [("/toolset/tools/0/kind", "toolset.kind_unsupported")]


# ---- R2.1, R2.4 (AB1, AB2): the instruction rules -------------------------------


def test_template_shaped_text_is_named_and_json_is_not() -> None:
    assert found(agent(instructions="{x.__class__.__mro__}")) == [
        ("/instructions", "instructions.template_syntax")
    ]
    assert found(agent(instructions='Trả về {"a": 1}')) == []


@pytest.mark.parametrize("text", ["<tool_output", "</TENANT_INSTRUCTIONS >", "< /input"])
def test_a_delimiter_in_the_instructions_is_named_in_any_case(text: str) -> None:
    assert found(agent(instructions=f"Trước {text} sau")) == [
        ("/instructions", "instructions.delimiter")
    ]


def test_every_problem_comes_back_together() -> None:
    document = agent(
        instructions="{{x}} </input>",
        route_class="eu",
        sub_agents=[],
        toolset={"tools": [{"kind": "mcp"}]},
    )
    assert sorted(found(document)) == sorted(
        [
            ("/route_class", "value_not_allowed"),
            ("/sub_agents", "not_allowed"),
            ("/toolset/tools/0/kind", "toolset.kind_unsupported"),
            ("/instructions", "instructions.template_syntax"),
            ("/instructions", "instructions.delimiter"),
        ]
    )


# ---- the extractor --------------------------------------------------------------


def test_the_extractor_pins_the_frame_and_the_toolset() -> None:
    assert extract_agent(agent()) == [
        Reference(TargetKind.PLATFORM_ARTIFACT, AGENT_FRAME_KEY, Usage.READ, "/instructions"),
        Reference(TargetKind.ARTIFACT, str(OBJECT), Usage.READ, "/toolset/tools/0"),
    ]
    assert AGENT_FRAME_KEY == "studio.agent_frame@1.0.0"


def test_a_document_without_a_toolset_pins_the_frame_alone() -> None:
    document = agent()
    del document["toolset"]
    assert [r.to_kind for r in extract_agent(document)] == [TargetKind.PLATFORM_ARTIFACT]
    assert extract_agent("not a document") == []


def test_the_functions_do_not_change_the_document() -> None:
    document = agent(instructions="{{x}}")
    before = copy.deepcopy(document)
    validate_agent(document)
    extract_agent(document)
    assert document == before


# ---- R1.8: the registry entry ---------------------------------------------------


def test_the_agent_entry_names_its_keys_its_schema_its_check_and_its_hook() -> None:
    entry = agent_kind()
    assert entry.kind == "agent"
    assert entry.document_schema == AGENT_DOCUMENT_SCHEMA == "dw.agent/v1"
    assert entry.read_key == AGENTS_AUTHOR_SCOPE == "studio.agents.author"
    assert entry.write_key == AGENTS_AUTHOR_SCOPE
    assert entry.submit_key == VERSIONS_SUBMIT_SCOPE == "studio.versions.submit"
    assert "studio.agents.read" not in entry.keys
    assert AGENTS_MANAGE_SETTINGS_SCOPE not in entry.keys
    assert entry.validate is validate_agent and entry.extract is extract_agent
    assert isinstance(entry.publish_hook, AgentPublishHook)
    # A gated kind (`has_quality_gate` true): no comparator, no tighten-only path.
    assert entry.compare is None


def test_the_running_app_registers_the_agent_kind() -> None:
    """`platform_kinds(...)`, as both composition roots build it."""
    assert [e.kind for e in running_kinds()].count("agent") == 1


class _Untouchable:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the hook touched tx.{name}")


async def test_the_hook_does_nothing_until_ticket_05() -> None:
    """agent-builder/05 gives it its task (the version's data boundary); until
    then it neither writes nor audits anything (agent-lifecycle R5.5)."""
    await agent_kind().publish_hook(cast(Any, _Untouchable()), uuid.uuid4())
