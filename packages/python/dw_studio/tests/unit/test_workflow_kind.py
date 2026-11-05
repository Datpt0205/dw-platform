"""Unit: Studio's `workflow` kind over the core's one validator (workflow-engine
ticket 01: R1.1, R1.3-R1.6, R1.8, R2.1, R2.2, R2.5, R2.10, R2.11, R2.14;
WE14, WE36).

Every case runs the kind's own `validate` (`WorkflowValidator` with
`STUDIO_RULES`) over the fixture step types of `dw_agent_runtime.testing`,
and reads each problem at its JSON pointer.
"""

from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from dw_agent_runtime.testing.workflow_types import fixture_node_registry, fixture_node_types
from dw_agent_runtime.wflite.validate import PACK_RULES, PathRules, validate
from dw_kernel.errors import ConflictError
from dw_studio.core.application.boundaries import FieldBoundary, ObjectBoundary
from dw_studio.core.domain.artifacts import Reference, TargetKind, Usage
from dw_studio.kinds import (
    WORKFLOWS_EDIT_SCOPE,
    WORKFLOWS_READ_SCOPE,
    workflow_kind,
)
from dw_studio.lifecycle.application.service import VERSIONS_SUBMIT_SCOPE
from dw_studio.testing.workflows import (
    FakeTriggerActivation,
    NoTools,
    studio_document,
    studio_step,
    workflow_entry,
)
from dw_studio.workflows.application.dependencies import WorkflowDependencies
from dw_studio.workflows.application.rules import STUDIO_RULES, WorkflowValidator
from dw_studio.workflows.testing.fakes import RecordingBoundaries

pytestmark = pytest.mark.unit

CHECK = WorkflowValidator(fixture_node_registry(), NoTools())
EXTRACT = WorkflowDependencies(fixture_node_registry())
CLASSES = [{"key": "lead.reply", "effect_level": "internal", "reversible": True, "ceiling": "A2"}]


def step(step_id: str, type_: str = "fixture.effect@1", **config: Any) -> dict[str, Any]:
    return studio_step(step_id, type_, **config)


def routed(step_id: str, lane: list[dict[str, Any]], **config: Any) -> dict[str, Any]:
    """A step that fails into `lane`."""
    return {**step(step_id, **config), "on_error": "route", "error_lane": lane}


def approval(
    step_id: str, approved: list[dict[str, Any]], rejected: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    config: dict[str, Any] = {"decision_class": "lead.reply", "proposal": "x", "approved": approved}
    if rejected is not None:
        config["rejected"] = rejected
    return step(step_id, "human.approval@1", **config)


def choice(step_id: str, yes: list[dict[str, Any]], no: list[dict[str, Any]]) -> dict[str, Any]:
    return step(step_id, "fixture.choice@1", on="x", yes=yes, no=no)


def document(*steps: dict[str, Any], source: str | None = None) -> dict[str, Any]:
    return {**studio_document(*steps, source=source), "decision_classes": CLASSES}


def found(doc: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.code, p.pointer) for p in CHECK(doc)]


def valid() -> dict[str, Any]:
    """Steps in a choice lane, both approval lanes and an error lane."""
    return document(
        choice("c", [step("y1")], []),
        approval("a", [routed("a1", [step("e1")])], []),
        step("last", note="{{ steps.c.case }}"),
    )


def test_a_tree_with_steps_in_choice_approval_and_error_lanes_passes() -> None:
    assert found(valid()) == []


def test_the_studio_rules_are_the_ticket_s() -> None:
    assert (
        PathRules(
            required_document_keys=frozenset(),
            refused_document_keys=frozenset({"key", "version"}),
            required_step_keys=frozenset({"retry", "timeout_s", "on_error"}),
            refused_step_keys=frozenset(),
            every_port_lane=True,
        )
        == STUDIO_RULES
    )


# ------------------------------------------------------------------ R1.1 --


@pytest.mark.parametrize("key", ["retry", "timeout_s", "on_error"])
def test_a_step_three_deep_without_its_policy_is_named(key: str) -> None:
    """In the error lane of a step in an approved lane."""
    doc = valid()
    del doc["steps"][1]["config"]["approved"][0]["error_lane"][0][key]
    assert found(doc) == [("wf.schema_invalid", f"/steps/1/config/approved/0/error_lane/0/{key}")]


@pytest.mark.parametrize(
    ("key", "value", "ok"),
    [
        ("timeout_s", 0, False),
        ("timeout_s", 901, False),
        ("timeout_s", 1, True),
        ("timeout_s", 900, True),
        ("retry", {"max_attempts": 0, "backoff": "fixed"}, False),
        ("retry", {"max_attempts": 6, "backoff": "fixed"}, False),
        ("retry", {"max_attempts": 1, "backoff": "exponential"}, True),
        ("retry", {"max_attempts": 5, "backoff": "fixed"}, True),
        ("retry", {"max_attempts": 2, "backoff": "linear"}, False),
        ("timeout_s", True, False),
        ("on_error", "incident", False),
    ],
)
def test_the_policy_bounds(key: str, value: Any, ok: bool) -> None:
    doc = document(step("one", **{}))
    doc["steps"][0][key] = value
    assert (found(doc) == []) is ok, found(doc)


@pytest.mark.parametrize("key", ["key", "version"])
def test_a_studio_document_naming_its_own_key_or_version_is_refused(key: str) -> None:
    """The envelope holds them (ADR-0109 decisions 1, 2)."""
    doc = valid()
    doc[key] = "lead_care" if key == "key" else "1.0.0"
    assert found(doc) == [("wf.schema_invalid", f"/{key}")]


def test_a_studio_trigger_with_a_policy_key_is_refused() -> None:
    doc = valid()
    doc["triggers"][0]["timeout_s"] = 30
    assert found(doc) == [("wf.schema_invalid", "/triggers/0/timeout_s")]


# ------------------------------------------------------------- R1.8, WE36 --


def test_edges_at_the_root_are_refused() -> None:
    doc = valid()
    doc["edges"] = [{"from": "c", "to": "a"}]
    assert found(doc) == [("wf.schema_invalid", "/edges")]


@pytest.mark.parametrize(
    "where",
    [
        lambda d: d["steps"][2],
        lambda d: d["steps"][1]["config"]["approved"][0]["error_lane"][0],
    ],
    ids=["top", "nested"],
)
def test_a_position_on_a_step_is_refused(where: Any) -> None:
    doc = valid()
    where(doc)["position"] = {"x": 10, "y": 20}
    codes = [code for code, _ in found(doc)]
    assert codes == ["wf.schema_invalid"]


def test_a_lane_the_type_does_not_declare_is_refused() -> None:
    """`expired` on `human.approval@1` is W2's."""
    doc = valid()
    doc["steps"][1]["config"]["expired"] = []
    assert [code for code, _ in found(doc)] == ["wf.config_invalid"]
    assert found(doc)[0][1] == "/steps/1/config"


def test_an_error_lane_without_route_and_route_without_a_lane_are_refused() -> None:
    doc = document(
        {**step("fails"), "error_lane": [step("handler")]},
        {**step("routes"), "on_error": "route"},
    )
    assert found(doc) == [
        ("wf.schema_invalid", "/steps/0/error_lane"),
        ("wf.schema_invalid", "/steps/1/on_error"),
    ]


# ------------------------------------------------------------------ R2.1 --


def test_a_step_after_a_stop_in_its_lane_is_unreachable() -> None:
    doc = document(choice("c", [step("s", "fixture.stop@1"), step("dead")], []))
    assert found(doc) == [("wf.unreachable_node", "/steps/0/config/yes/1")]


def test_a_step_after_a_break_in_a_loop_body_is_unreachable() -> None:
    loop = step(
        "lap",
        "fixture.loop@1",
        max_iterations=3,
        body=[step("b"), step("out", "fixture.break@1"), step("dead")],
        max_reached=[],
    )
    assert found(document(loop, step("after"))) == [
        ("wf.unreachable_node", "/steps/0/config/body/2")
    ]


# ------------------------------------------------------------------ R2.2 --


def test_a_switch_without_its_default_lane_is_not_total() -> None:
    doc = document(step("route", "logic.switch@1", on="x", cases={"a": []}))
    assert found(doc) == [("wf.router_not_total", "/steps/0/config")]


def test_an_approval_needs_its_rejected_lane_on_studio_and_not_on_a_pack() -> None:
    doc = document(approval("a", [step("x")]))
    assert found(doc) == [("wf.router_not_total", "/steps/0/config")]
    doc["steps"][0]["config"]["rejected"] = []
    assert found(doc) == []
    as_pack = copy.deepcopy(doc)
    as_pack.update(key="probe", version="1.0.0")
    del as_pack["steps"][0]["config"]["rejected"]
    for raw in (as_pack["steps"][0], as_pack["steps"][0]["config"]["approved"][0]):
        for key in ("retry", "timeout_s", "on_error"):
            raw.pop(key)
    pack_problems = validate(
        as_pack,
        registry=fixture_node_registry(),
        rules=PACK_RULES,
        tools=NoTools(),
        work_schemas={},
    )
    assert pack_problems == []


def test_a_loop_needs_its_body_and_not_its_max_reached_lane() -> None:
    loop = step("lap", "fixture.loop@1", max_iterations=2)
    assert found(document(loop)) == [("wf.router_not_total", "/steps/0/config")]
    loop["config"]["body"] = [step("b")]
    assert found(document(loop)) == []


def test_a_step_that_fails_without_an_error_lane_is_total() -> None:
    assert found(document(step("x"))) == []


# ------------------------------------------------------------------ R2.5 --


def test_after_a_choice_a_step_of_one_lane_does_not_dominate() -> None:
    doc = document(choice("c", [step("y1")], []), step("after", note="{{ steps.y1.done }}"))
    assert found(doc) == [("wf.ref_not_dominating", "/steps/1/config/note")]


def test_after_a_failing_step_its_error_lane_does_not_dominate() -> None:
    doc = document(routed("f", [step("handler")]), step("after", note="{{ steps.handler.done }}"))
    assert found(doc) == [("wf.ref_not_dominating", "/steps/1/config/note")]


def test_an_error_lane_nested_in_an_approved_lane_is_lowered() -> None:
    """WE14: a lowering that skipped the error lane would see no problem."""
    doc = document(
        approval(
            "a",
            [routed("a1", [step("e1")]), step("a2", note="{{ steps.e1.done }}")],
            [],
        )
    )
    assert found(doc) == [("wf.ref_not_dominating", "/steps/0/config/approved/1/config/note")]


def test_a_step_before_the_block_dominates() -> None:
    doc = document(step("before"), choice("c", [step("y", note="{{ steps.before.done }}")], []))
    assert found(doc) == []


# ----------------------------------------------- R2.10, R2.11, R2.14 --


def test_a_studio_tree_nested_past_the_cap_is_named() -> None:
    inner: list[dict[str, Any]] = [step("leaf")]
    for level in range(11, 1, -1):
        inner = [choice(f"c{level}", inner, [])]
    assert [code for code, _ in found(document(*inner))] == ["wf.limit_above_plan"]


def test_six_problems_at_six_depths_come_back_together() -> None:
    doc = document(
        step("one", "foo.bar@1"),
        choice(
            "c",
            [
                {**step("two"), "timeout_s": 0},
                choice(
                    "c2",
                    [
                        routed("three", [step("four", "fixture.effect@1", nope=1)]),
                        step(
                            "c3",
                            "fixture.choice@1",
                            on="x",
                            yes=[step("five", note="{{ steps.zzz.done }}")],
                        ),
                    ],
                    [],
                ),
            ],
            [],
        ),
        step("six", "fixture.stop@1"),
        step("seven"),
    )
    assert sorted(found(doc)) == sorted(
        [
            ("wf.schema_invalid", "/steps/1/config/yes/0/timeout_s"),
            ("wf.router_not_total", "/steps/1/config/yes/1/config/yes/1/config"),
            ("wf.unknown_type", "/steps/0/type"),
            ("wf.config_invalid", "/steps/1/config/yes/1/config/yes/0/error_lane/0/config"),
            ("wf.ref_unknown", "/steps/1/config/yes/1/config/yes/1/config/yes/0/config/note"),
            ("wf.unreachable_node", "/steps/3"),
        ]
    )


def test_an_unregistered_type_keeps_wf_lite_s_code() -> None:
    """R2.14: `wf.unknown_type`, never a second code."""
    assert found(document(step("x", "foo.bar@1"))) == [("wf.unknown_type", "/steps/0/type")]


def test_a_document_that_is_not_an_object_is_one_problem() -> None:
    assert found([]) == [("wf.schema_invalid", "")]  # type: ignore[arg-type]


# ------------------------------------------------------------------ R1.3 --


def test_every_step_at_every_depth_is_extracted() -> None:
    """A trigger's data source and an object read by a step in the error lane
    of a step in an approved lane: both `artifact` rows, and one `node_type`
    row per type, the nested one included."""
    source, obj = str(uuid.uuid4()), str(uuid.uuid4())
    doc = document(
        approval("a", [routed("a1", [step("read", "fixture.object@1", object=obj)])], []),
        source=source,
    )
    refs = EXTRACT(doc)
    assert refs == [
        Reference(TargetKind.NODE_TYPE, "fixture.trigger@1", Usage.INVOKE, "/triggers/0/type"),
        Reference(TargetKind.ARTIFACT, source, Usage.READ, "/triggers/0/config/source"),
        Reference(TargetKind.NODE_TYPE, "human.approval@1", Usage.INVOKE, "/steps/0/type"),
        Reference(
            TargetKind.NODE_TYPE,
            "fixture.effect@1",
            Usage.INVOKE,
            "/steps/0/config/approved/0/type",
        ),
        Reference(
            TargetKind.NODE_TYPE,
            "fixture.object@1",
            Usage.INVOKE,
            "/steps/0/config/approved/0/error_lane/0/type",
        ),
        Reference(
            TargetKind.ARTIFACT,
            obj,
            Usage.READ,
            "/steps/0/config/approved/0/error_lane/0/config/object",
        ),
    ]


def test_the_fixture_types_that_use_something_say_so() -> None:
    uses = {
        spec.type: spec.dependencies({"source": "s", "object": "o"})
        for spec in fixture_node_types()
    }
    assert [d.to_key for d in uses["fixture.trigger@1"]] == ["s"]
    assert [d.to_key for d in uses["fixture.object@1"]] == ["o"]


def test_a_document_that_does_not_read_uses_nothing() -> None:
    assert EXTRACT({"schema": "dw.workflow/v1", "steps": "nope"}) == []


# ------------------------------------------------------------- R1.4, R1.5 --


def test_the_workflow_entry_names_its_keys_its_schema_and_its_check() -> None:
    entry = workflow_entry()
    assert (entry.kind, entry.document_schema) == ("workflow", "dw.workflow/v1")
    assert entry.keys == (WORKFLOWS_READ_SCOPE, WORKFLOWS_EDIT_SCOPE, VERSIONS_SUBMIT_SCOPE)
    assert entry.keys == (
        "studio.workflows.read",
        "studio.workflows.edit",
        "studio.versions.submit",
    )
    assert isinstance(entry.validate, WorkflowValidator)
    assert isinstance(entry.extract, WorkflowDependencies)
    assert [p.code for p in entry.validate(document(step("x", "foo.bar@1")))] == ["wf.unknown_type"]


# ------------------------------------------------------------------ R1.6 --


class Tx:
    """A transaction as the publish hook sees it: its session, passed through
    to the boundary port, and the version it publishes (a sealed one, of a
    document that touches no record unless a test gives it one)."""

    def __init__(self, document: Any = None) -> None:
        self.session = object()
        self.document = document if document is not None else studio_document(studio_step("a"))

    async def root_version(self, version_id: uuid.UUID) -> Any:
        version = SimpleNamespace(
            id=version_id, document=self.document, definition_hash="sha256:" + "d" * 64
        )
        return SimpleNamespace(kind="workflow", version=version)


async def test_the_hook_activates_the_version_once_on_the_transaction_it_was_handed() -> None:
    artifact, v1, v2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fake = FakeTriggerActivation(versions={v1: artifact, v2: artifact})
    hook = workflow_kind(
        nodes=fixture_node_registry(),
        tools=NoTools(),
        triggers=fake,
        boundaries=RecordingBoundaries(),
    ).publish_hook

    tx = Tx()
    await hook(tx, v1)  # type: ignore[arg-type]
    assert fake.calls == [(tx, v1)]
    fake.settle(tx, committed=True)
    assert fake.active == {artifact: v1}

    again = Tx()
    await hook(again, v1)  # type: ignore[arg-type]
    fake.settle(again, committed=True)
    assert fake.active == {artifact: v1} and fake.retired == []

    rolled = Tx()
    await hook(rolled, v2)  # type: ignore[arg-type]
    fake.settle(rolled, committed=False)
    assert fake.active == {artifact: v1}

    nxt = Tx()
    await hook(nxt, v2)  # type: ignore[arg-type]
    fake.settle(nxt, committed=True)
    assert fake.active == {artifact: v2} and fake.retired == [v1]


async def test_the_hook_records_the_versions_boundary_on_the_publish_transaction() -> None:
    """R1.7: after the triggers, on the session the hook was handed, the
    boundary `derive_workflow_boundary` finds at any depth: an error lane's
    `create` and a root step's `read` of one object, one row with both flags."""
    version = uuid.uuid4()
    fake = FakeTriggerActivation(versions={version: uuid.uuid4()})
    boundaries = RecordingBoundaries()
    hook = workflow_entry(fake, boundaries).publish_hook
    tx = Tx(
        studio_document(
            {
                **studio_step("doc", "fixture.records@1", object="mkt_lead", command="read"),
                "error_lane": [
                    studio_step(
                        "tao",
                        "fixture.records@1",
                        object="mkt_lead",
                        command="create",
                        writes=["ghi_chu"],
                    )
                ],
            }
        )
    )
    await hook(tx, version)  # type: ignore[arg-type]
    assert fake.calls == [(tx, version)]
    ((call, session, kind, version_id, definition, objects, fields),) = boundaries.calls
    assert (call, session, kind, version_id) == ("record", tx.session, "workflow", version)
    assert definition == "sha256:" + "d" * 64
    assert objects == (ObjectBoundary("mkt_lead", True, True, False, False, False),)
    assert fields == (FieldBoundary("mkt_lead", "ghi_chu", "edit"),)


async def test_a_port_that_fails_fails_the_hook() -> None:
    fake = FakeTriggerActivation(versions={}, fail=True)
    hook = workflow_entry(fake, RecordingBoundaries()).publish_hook
    with pytest.raises(ConflictError):
        await hook(Tx(), uuid.uuid4())  # type: ignore[arg-type]
