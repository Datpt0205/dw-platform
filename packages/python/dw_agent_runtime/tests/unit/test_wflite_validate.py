"""Unit: the `dw.workflow/v1` document, its six step types, the one-pass
validator and the pack catalog (wf-lite R1-R4; WFL1-WFL8, WFL19, WFL20, WFL24).

Every code has a red case here, and the fixture pack, which uses all six
types, is the green one.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

from dw_agent_runtime.tool_specs import ToolSpec
from dw_agent_runtime.wflite.catalog import PackCatalog, load_yaml
from dw_agent_runtime.wflite.registry import build_node_registry
from dw_agent_runtime.wflite.validate import validate
from dw_kernel.errors import ConfigError, NotFoundError

pytestmark = pytest.mark.unit

PACKS = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
SAMPLE = PACKS / "sample" / "workflows" / "sample@1.0.0.yaml"
LEAD_SCHEMA = json.loads((PACKS / "sample" / "schemas" / "lead.json").read_text(encoding="utf-8"))


def _spec(name: str, side_effect: str) -> ToolSpec:
    return ToolSpec.model_validate(
        {
            "schema_version": "1.0",
            "name": name,
            "version": "1.0.0",
            "summary": name,
            "when_to_use": "x",
            "when_not_to_use": "x",
            "returns": "x",
            "required_scopes": [],
            "side_effect_level": side_effect,
            "approval_policy": "conditional",
            "timeout_seconds": 10,
            "max_retries": 0,
            "idempotent": True,
            "data_classification": ["internal"],
            **(
                {"sends_message": True, "message": {"channel": "email", "recipient_fields": ["to"]}}
                if name == "email.send"
                else {"sends_message": False}
            ),
        }
    )


class Tools:
    specs: ClassVar[dict[tuple[str, str], ToolSpec]] = {
        ("email.send", "1.0.0"): _spec("email.send", "external"),
        ("lead.note", "1.0.0"): _spec("lead.note", "internal"),
    }

    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> ToolSpec:
        found = self.specs.get((name, version))
        if found is None:
            raise NotFoundError("tool spec not registered")
        return found


def sample() -> dict[str, Any]:
    loaded: dict[str, Any] = load_yaml(SAMPLE.read_text(encoding="utf-8"))
    return loaded


def codes(document: dict[str, Any], **kw: Any) -> list[str]:
    return [
        p.code
        for p in validate(
            document,
            registry=build_node_registry(),
            tools=Tools(),
            work_schemas={"lead.new": LEAD_SCHEMA},
            **kw,
        )
    ]


def step(document: dict[str, Any], step_id: str) -> dict[str, Any]:
    """The step `step_id`, wherever it sits in the tree."""

    def find(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
        for s in steps:
            if s["id"] == step_id:
                return s
            config = s.get("config", {})
            lanes = [config.get("approved"), config.get("rejected"), config.get("default")]
            lanes += list((config.get("cases") or {}).values())
            for lane in lanes:
                if isinstance(lane, list):
                    found = find(lane)
                    if found is not None:
                        return found
        return None

    found = find(document["steps"])
    assert found is not None, step_id
    return found


# --------------------------------------------------------------- R1, R2 --


def test_the_sample_pack_loads_pinned_to_its_bytes() -> None:
    """R1.1, R1.4."""
    catalog = PackCatalog.load(PACKS, Tools())
    pinned = catalog.workflow("sample", "1.0.0")
    assert pinned is not None
    assert pinned.sha256 == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    assert catalog.schema(workflow_key="sample", workflow_version="1.0.0", kind="lead.new") == (
        LEAD_SCHEMA
    )
    assert catalog.schema(workflow_key="sample", workflow_version="1.0.0", kind="other") is None
    assert catalog.schema(workflow_key="nope", workflow_version="1.0.0", kind="lead.new") is None


def test_the_valid_sample_has_no_problem() -> None:
    assert codes(sample(), file_key=("sample", "1.0.0")) == []


def test_the_registry_has_the_six_types_and_no_more() -> None:
    """R2.1."""
    assert set(build_node_registry()) == {
        "trigger.work_item@1",
        "ai.llm@1",
        "tool.call@1",
        "human.approval@1",
        "time.wait@1",
        "logic.switch@1",
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(extra=1),  # an unknown top-level key
        lambda d: d.pop("steps"),  # a required key missing
    ],
    ids=["unknown-key", "no-steps"],
)
def test_a_malformed_document_is_refused(change: Any) -> None:
    """WFL1."""
    document = sample()
    change(document)
    assert set(codes(document)) == {"wf.schema_invalid"}


def test_a_document_whose_version_is_not_its_file_name_is_refused() -> None:
    """WFL1: `a@1.0.0` holding `version: 1.0.1`."""
    document = sample()
    document["version"] = "1.0.1"
    assert codes(document, file_key=("sample", "1.0.0")) == ["wf.schema_invalid"]


def test_step_ids_are_unique_and_lowercase() -> None:
    """R1.3."""
    document = sample()
    step(document, "send")["id"] = "draft"
    assert "wf.duplicate_step_id" in codes(document)
    document = sample()
    step(document, "wait_reply")["id"] = "Score"
    assert "wf.schema_invalid" in codes(document)


def test_an_unknown_type_and_a_bad_config_are_named() -> None:
    """WFL2."""
    document = sample()
    step(document, "wait_reply")["type"] = "http.request@1"
    assert codes(document) == ["wf.unknown_type"]
    document = sample()
    del step(document, "draft")["config"]["prompt"]
    assert "wf.config_invalid" in codes(document)


def test_every_problem_is_reported_in_one_pass() -> None:
    """R3.1: three different faults, three codes."""
    document = sample()
    step(document, "wait_reply")["type"] = "http.request@1"
    del step(document, "route")["config"]["default"]
    step(document, "send")["config"]["tool"] = "email.blast@1.0.0"
    assert sorted(codes(document)) == [
        "wf.router_not_total",
        "wf.tool_unknown",
        "wf.unknown_type",
    ]


# -------------------------------------------------------------------- R3 --


def test_a_reference_into_another_lane_does_not_dominate() -> None:
    """WFL3: the default lane names a step of the `true` case; before the
    switch is fine."""
    document = sample()
    step(document, "route")["config"]["default"] = [
        {
            "id": "note_other",
            "type": "tool.call@1",
            "config": {
                "tool": "lead.note@1.0.0",
                "input": {"text": "{{ steps.note_sent.result }}"},
                "decision_class": "lead.note",
            },
        }
    ]
    assert codes(document) == ["wf.ref_not_dominating"]
    step(document, "note_other")["config"]["input"] = {"text": "{{ steps.draft.body }}"}
    assert codes(document) == []


def test_a_reference_after_the_block_into_its_lane_does_not_dominate() -> None:
    document = sample()
    step(document, "wait_reply")["config"] = {"seconds": 60}
    step(document, "note_sent")["config"]["input"] = {"text": "{{ steps.send.result }}"}
    assert codes(document) == ["wf.ref_not_dominating"]


def test_an_unknown_field_or_step_is_named() -> None:
    """WFL24."""
    document = sample()
    step(document, "note_sent")["config"]["input"] = {"text": "{{ steps.draft.khong_co }}"}
    assert codes(document) == ["wf.ref_unknown"]
    step(document, "note_sent")["config"]["input"] = {"text": "{{ steps.khong_co.body }}"}
    assert codes(document) == ["wf.ref_unknown"]


def test_a_switch_without_a_default_is_not_total() -> None:
    """WFL4."""
    document = sample()
    del step(document, "route")["config"]["default"]
    assert codes(document) == ["wf.router_not_total"]


def test_an_unknown_tool_and_an_undeclared_class_are_named() -> None:
    """WFL5."""
    document = sample()
    step(document, "note_sent")["config"]["tool"] = "crm.delete@1.0.0"
    assert codes(document) == ["wf.tool_unknown"]
    document = sample()
    step(document, "note_sent")["config"]["decision_class"] = "lead.score"
    assert codes(document) == ["wf.decision_class_undeclared"]


def test_parameters_and_work_fields_must_be_declared() -> None:
    """WFL20 (R3.6)."""
    document = sample()
    step(document, "draft")["config"]["inputs"]["x"] = "{{ params.khong_co }}"
    assert codes(document) == ["wf.param_undeclared"]
    document = sample()
    step(document, "draft")["config"]["inputs"]["x"] = "{{ work.khong_co }}"
    assert codes(document) == ["wf.ref_unknown"]


def test_a_reference_replaces_a_whole_value() -> None:
    """WFL20 (R3.7)."""
    document = sample()
    step(document, "draft")["config"]["inputs"]["greeting"] = "Chào {{ work.name }}"
    assert codes(document) == ["wf.config_invalid"]


def test_a_confidence_floor_needs_a_confidence_to_read() -> None:
    """WFL20 (R3.8)."""
    document = sample()
    schema = step(document, "draft")["config"]["output_schema"]
    del schema["properties"]["confidence"]
    schema["required"].remove("confidence")
    assert codes(document) == ["wf.config_invalid"]


# -------------------------------------------------------------------- R4 --


def _external_send(input_value: Any = "{{ steps.approve_send.proposal }}") -> dict[str, Any]:
    return {
        "id": "send_again",
        "type": "tool.call@1",
        "config": {
            "tool": "email.send@1.0.0",
            "input": input_value,
            "decision_class": "email.first_touch",
        },
    }


@pytest.mark.parametrize(
    "place",
    ["top-level", "other-lane", "after-gate", "rejected-lane"],
)
def test_an_outward_effect_outside_its_approved_lane_is_refused(place: str) -> None:
    """WFL7: no gate, a gate of another lane, after the gate, its rejected lane."""
    document = sample()
    send = _external_send()
    if place == "top-level":
        document["steps"].insert(0, _external_send("{{ work.email }}"))
    elif place == "other-lane":
        step(document, "route")["config"]["cases"]["true"].append(send)
    elif place == "after-gate":
        document["steps"].append(send)
    else:
        step(document, "approve_send")["config"]["rejected"].append(send)
    assert "wf.hitl_gate_missing" in codes(document)


def test_an_outward_effect_nested_in_its_approved_lane_passes() -> None:
    document = sample()
    step(document, "approve_send")["config"]["approved"].append(
        {
            "id": "inner_route",
            "type": "logic.switch@1",
            "config": {
                "on": "{{ work.source }}",
                "cases": {"web": [_external_send()]},
                "default": [],
            },
        }
    )
    assert codes(document) == []


@pytest.mark.parametrize(
    "given",
    ["{{ steps.draft.subject }}", {"to": "{{ steps.draft.to }}"}],
    ids=["a-field-of-the-draft", "a-composed-object"],
)
def test_a_gated_effect_takes_exactly_what_was_approved(given: Any) -> None:
    """WFL19."""
    document = sample()
    step(document, "send")["config"]["input"] = given
    assert codes(document) == ["wf.unapproved_input"]


def test_a_tool_beyond_its_class_is_refused() -> None:
    """WFL8: an external tool declared under an internal class."""
    document = sample()
    step(document, "note_sent")["config"]["tool"] = "email.send@1.0.0"
    found = codes(document)
    assert "wf.effect_above_class" in found


# ------------------------------------------------------------- catalog --


def test_one_bad_file_refuses_the_catalog_and_names_it(tmp_path: Path) -> None:
    """WFL6 (R3.5) at the catalog: the error names the file and the code."""
    root = tmp_path / "packs"
    shutil.copytree(PACKS, root)
    bad = copy.deepcopy(sample())
    del step(bad, "route")["config"]["default"]
    bad["version"] = "1.0.1"
    path = root / "sample" / "workflows" / "sample@1.0.1.yaml"
    path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError) as refused:
        PackCatalog.load(root, Tools())
    assert "sample@1.0.1.yaml" in refused.value.message
    assert "wf.router_not_total" in refused.value.message


def test_a_missing_schema_file_is_named(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    shutil.copytree(PACKS, root)
    (root / "sample" / "schemas" / "lead.json").unlink()
    with pytest.raises(ConfigError, match=r"no schema file lead\.json"):
        PackCatalog.load(root, Tools())


def test_no_packs_is_an_empty_catalog(tmp_path: Path) -> None:
    assert PackCatalog.load(tmp_path / "absent", Tools()).all() == []


def test_on_and_yes_are_strings_to_the_catalog() -> None:
    """PyYAML's YAML 1.1 booleans would turn the switch's `on:` into `True`."""
    text = "\n".join(["on: x", "yes: 1", "flag: true"])
    assert load_yaml(text) == {"on": "x", "yes": 1, "flag": True}
