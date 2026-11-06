"""The capability analysis of a workflow at its submit (compliance-pdpl ticket
05: R2.6, R4.1, R4.2, R4.4, R4.8; CP6, CP12, CP14, CP26; ADR-0125).

Pure: documents lowered over the fixture step types and three test types
(`test.web@1` reads the web, A; `test.lead@1` reads a lead's object, B;
`test.send@1` has an `external` effect by its type, C), a label table of the
test's own and facts written by hand. The submit's transaction, the stored
row and the lookup under RLS are `test_capability_db.py`'s.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.registry import build_node_registry, registry_of
from dw_studio.workflows.application.capability import (
    EVERY_LABEL,
    EXTERNAL,
    PRIVATE,
    RESIDENCY_REFUSED,
    TOOL_UNCLASSIFIED,
    TRIFECTA_PATH_UNAPPROVED,
    UNTRUSTED,
    CapabilityFacts,
    LabelTable,
    ToolClasses,
    capability_analysis,
)
from dw_studio.workflows.application.capability_check import (
    child_labels,
    platform_label_table,
    tool_labels,
    tool_ref,
)

pytestmark = pytest.mark.unit

_EFFECT = fixture_node_registry()["fixture.effect@1"]
TYPES = (
    dataclasses.replace(_EFFECT, type="test.web@1", side_effect_level="none"),
    dataclasses.replace(_EFFECT, type="test.lead@1", side_effect_level="none"),
    dataclasses.replace(_EFFECT, type="test.send@1", side_effect_level="external"),
    dataclasses.replace(_EFFECT, type="test.child@1", side_effect_level="none"),
    dataclasses.replace(_EFFECT, type="test.model@1", side_effect_level="none"),
)
REGISTRY = registry_of((*fixture_node_registry().values(), *TYPES))


def _none(*_: Any) -> frozenset[Any]:
    return frozenset()


def _lead(step: Any, spec: Any, facts: CapabilityFacts) -> frozenset[Any]:
    return frozenset({PRIVATE}) if facts.personal_objects.get("lead", True) else frozenset()


TABLE = LabelTable(
    rules={
        "test.web@1": lambda *_: frozenset({UNTRUSTED}),
        "test.lead@1": _lead,
        "test.send@1": _none,
        "test.child@1": child_labels,
        "test.model@1": _none,
        "tool.call@1": tool_labels,
        "human.approval@1": _none,
        "fixture.parallel@1": _none,
        "fixture.loop@1": _none,
        "fixture.trigger@1": _none,
    },
    internal_triggers=frozenset({"fixture.trigger@1"}),
    gates=frozenset({"human.approval@1"}),
    tool_of={"tool.call@1": tool_ref},
    profile_of={"test.model@1": lambda step: "balanced"},
    source_of=lambda step: step.config.get("source"),
)
FACTS = CapabilityFacts(personal_objects={"lead": True}, personal_sources={"nguon": False})


def s(step_id: str, type_: str, **config: Any) -> dict[str, Any]:
    return {"id": step_id, "type": type_, "config": dict(config)}


def doc(*steps: dict[str, Any], source: str = "nguon") -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "schema": "dw.workflow/v1",
            "triggers": [{"id": "khi", "type": "fixture.trigger@1", "config": {"source": source}}],
            "steps": list(steps),
        }
    )


def approve(step_id: str, approved: list[Any], rejected: list[Any] | None = None) -> dict[str, Any]:
    return s(step_id, "human.approval@1", approved=approved, rejected=rejected or [])


def refusal(document: WorkflowDocument, facts: CapabilityFacts = FACTS) -> Any:
    return capability_analysis(document, REGISTRY, TABLE, facts).refusal


WEB, LEAD, SEND = s("web", "test.web@1"), s("lead", "test.lead@1"), s("gui", "test.send@1")


# ---- R4.1: the labels -------------------------------------------------------------


def test_r4_1_an_unknown_type_carries_every_label() -> None:
    found = capability_analysis(doc(s("x", "test.nobody@1")), REGISTRY, TABLE, FACTS)
    assert found.labels["x"] == EVERY_LABEL


def test_r4_1_a_type_without_an_entry_carries_every_label() -> None:
    found = capability_analysis(doc(s("x", "fixture.stop@1")), REGISTRY, TABLE, FACTS)
    assert found.labels["x"] == EVERY_LABEL


def test_r4_1_effect_comes_from_the_types_own_side_effect_level() -> None:
    found = capability_analysis(doc(SEND), REGISTRY, TABLE, FACTS)
    assert found.labels["gui"] == {EXTERNAL}


@pytest.mark.parametrize(
    ("classes", "labels"),
    [
        (
            ToolClasses("untrusted", frozenset({"personal"}), "external"),
            {UNTRUSTED, PRIVATE, EXTERNAL},
        ),
        (ToolClasses("untrusted", frozenset({"personal"}), "none"), {UNTRUSTED, PRIVATE}),
        (ToolClasses("trusted", frozenset({"internal"}), "none"), set()),
        (ToolClasses("trusted", frozenset({"basic"}), "none"), {PRIVATE}),
        (ToolClasses("trusted", frozenset(), "none"), {PRIVATE}),
    ],
)
def test_r4_1_a_tool_steps_labels_are_its_tools_three_classifications(
    classes: ToolClasses, labels: set[str]
) -> None:
    step = s("goi", "tool.call@1", tool="email.send@1.0.0", input={}, decision_class="x")
    facts = dataclasses.replace(FACTS, tools={"email.send@1.0.0": classes})
    assert capability_analysis(doc(step), REGISTRY, TABLE, facts).labels["goi"] == labels


@pytest.mark.parametrize(("personal", "labels"), [(True, {PRIVATE}), (False, set())])
def test_r4_1_reading_an_object_is_private_by_its_fields(personal: bool, labels: set[str]) -> None:
    facts = dataclasses.replace(FACTS, personal_objects={"lead": personal})
    assert capability_analysis(doc(LEAD), REGISTRY, TABLE, facts).labels["lead"] == labels


def test_r4_1_an_external_trigger_with_a_personal_source_is_a_and_b() -> None:
    table = dataclasses.replace(TABLE, internal_triggers=frozenset())
    facts = dataclasses.replace(FACTS, personal_sources={"nguon": True})
    found = capability_analysis(doc(SEND), REGISTRY, table, facts)
    assert found.labels["trigger:khi"] == {UNTRUSTED, PRIVATE}
    assert found.refusal is not None and found.refusal[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_1_every_platform_type_has_an_entry_in_the_platform_table() -> None:
    """The registry and the table compared: a type registered without an
    entry would reach the analysis only through the unknown-type net."""
    missing = set(build_node_registry()) - set(platform_label_table("balanced").rules)
    assert missing == set(), f"no label entry for {sorted(missing)}"


# ---- R4.2: where the trifecta needs a person ----------------------------------------


def test_r4_2_web_lead_send_without_an_approval_is_refused_with_its_path() -> None:
    assert refusal(doc(WEB, LEAD, SEND)) == (TRIFECTA_PATH_UNAPPROVED, (("web", "lead", "gui"),))


def test_r4_2_lead_then_web_then_send_is_refused_too() -> None:
    assert refusal(doc(LEAD, WEB, SEND))[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_2_web_lead_then_approval_and_send_in_its_approved_lane_passes() -> None:
    assert refusal(doc(WEB, LEAD, approve("duyet", [SEND]))) is None


def test_r4_2_an_approval_before_the_data_does_not_gate_the_send() -> None:
    assert refusal(doc(approve("duyet", [WEB, LEAD, SEND])))[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_2_a_send_in_the_rejected_lane_is_not_gated() -> None:
    assert refusal(doc(WEB, LEAD, approve("duyet", [], [SEND])))[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_2_a_and_b_on_two_parallel_lanes_joining_before_the_send_is_refused() -> None:
    lanes = s("song_song", "fixture.parallel@1", branches={"a": [WEB], "b": [LEAD]})
    assert refusal(doc(lanes, SEND))[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_2_an_approval_on_one_lane_only_does_not_gate_the_join() -> None:
    lanes = s(
        "song_song",
        "fixture.parallel@1",
        branches={"a": [WEB, approve("duyet", [])], "b": [LEAD]},
    )
    assert refusal(doc(lanes, SEND))[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_1_a_loops_back_edge_makes_a_later_read_an_ancestor() -> None:
    """`[send, web, lead]` in a loop's body: the next round's send sees what
    this round read."""
    loop = s("lap", "fixture.loop@1", max_iterations=3, body=[SEND, WEB, LEAD])
    assert refusal(doc(loop))[0] == TRIFECTA_PATH_UNAPPROVED


def test_r4_2_the_pilot_workflow_without_its_approval_is_refused() -> None:
    """The marketing pilot's shape (marketing-pilot/03): a Data Hub trigger
    carrying a personal field, a model scoring the lead, the send."""
    table = dataclasses.replace(TABLE, internal_triggers=frozenset())
    facts = dataclasses.replace(
        FACTS,
        personal_sources={"nguon": True},
        tools={"email.send@1.0.0": ToolClasses("trusted", frozenset({"personal"}), "external")},
    )
    score = s("cham_diem", "test.model@1")
    send = s("gui", "tool.call@1", tool="email.send@1.0.0", input={}, decision_class="x")
    found = capability_analysis(doc(score, send), REGISTRY, table, facts)
    assert found.refusal is not None and found.refusal[0] == TRIFECTA_PATH_UNAPPROVED
    gated = capability_analysis(doc(score, approve("duyet", [send])), REGISTRY, table, facts)
    assert gated.refusal is None


# ---- R4.4: an unclassified tool ---------------------------------------------------------


def test_r4_4_a_tool_missing_a_classification_refuses_the_submit_first() -> None:
    step = s("goi", "tool.call@1", tool="crm.lookup@1.0.0", input={}, decision_class="x")
    facts = dataclasses.replace(
        FACTS, tools={"crm.lookup@1.0.0": ToolClasses(None, frozenset({"none"}), "none")}
    )
    assert refusal(doc(WEB, LEAD, SEND, step), facts) == (TOOL_UNCLASSIFIED, (("goi",),))
    assert refusal(doc(step), FACTS) == (TOOL_UNCLASSIFIED, (("goi",),))


# ---- R2.6: a personal field on a route abroad -----------------------------------------


def residency(route_class: str, locations: tuple[str | None, ...]) -> CapabilityFacts:
    return dataclasses.replace(
        FACTS, route_class=route_class, model_locations={"balanced": locations}
    )


def test_r2_6_a_private_ancestor_of_a_foreign_model_step_is_refused() -> None:
    found = refusal(
        doc(LEAD, s("soan", "test.model@1")), residency("cross_border_full", ("foreign",))
    )
    assert found == (RESIDENCY_REFUSED, (("lead", "soan"),))


@pytest.mark.parametrize(
    "locations", [("vn", "foreign"), ("vn", None), ()], ids=["fallback", "undeclared", "missing"]
)
def test_r2_6_any_route_not_declared_vn_is_foreign(locations: tuple[str | None, ...]) -> None:
    found = refusal(doc(LEAD, s("soan", "test.model@1")), residency("cross_border_full", locations))
    assert found is not None and found[0] == RESIDENCY_REFUSED


def test_r2_6_every_route_in_vn_passes_and_vn_only_does_not_run_the_check() -> None:
    model = s("soan", "test.model@1")
    assert refusal(doc(LEAD, model), residency("cross_border_full", ("vn", "vn"))) is None
    assert refusal(doc(LEAD, model), residency("vn_only", ("foreign",))) is None


def test_r2_6_a_profile_the_closure_does_not_describe_is_foreign() -> None:
    facts = dataclasses.replace(FACTS, route_class="cross_border_full", model_locations={})
    assert refusal(doc(LEAD, s("soan", "test.model@1")), facts)[0] == RESIDENCY_REFUSED


def test_r2_6_runs_before_the_trifecta() -> None:
    facts = residency("cross_border_full", ("foreign",))
    found = refusal(doc(WEB, LEAD, s("soan", "test.model@1"), SEND), facts)
    assert found is not None and found[0] == RESIDENCY_REFUSED


# ---- R4.8: a child version's labels -------------------------------------------------------


def child(version: str = "11111111-1111-1111-1111-111111111111") -> dict[str, Any]:
    return s("con", "test.child@1", version_id=version)


def test_r4_8_a_child_with_an_effect_after_a_and_b_needs_an_approval() -> None:
    facts = dataclasses.replace(
        FACTS, assessments={"11111111-1111-1111-1111-111111111111": frozenset({EXTERNAL})}
    )
    assert refusal(doc(WEB, LEAD, child()), facts) == (
        TRIFECTA_PATH_UNAPPROVED,
        (("web", "lead", "con"),),
    )
    assert refusal(doc(WEB, LEAD, approve("duyet", [child()])), facts) is None


def test_r4_8_a_child_with_no_assessment_row_carries_every_label() -> None:
    found = capability_analysis(doc(child()), REGISTRY, TABLE, FACTS)
    assert found.labels["con"] == EVERY_LABEL


def test_r4_8_a_child_with_no_effect_of_its_own_carries_what_its_row_says() -> None:
    facts = dataclasses.replace(
        FACTS, assessments={"11111111-1111-1111-1111-111111111111": frozenset()}
    )
    assert capability_analysis(doc(child()), REGISTRY, TABLE, facts).labels["con"] == set()
