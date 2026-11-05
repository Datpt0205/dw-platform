"""Unit: the one step-type registry (workflow-nodes ticket 02, steps 1-3:
R1.1, R1.4, R1.5; WN15; ADR-0112 decision 2).

The registry is the platform core's (`dw_agent_runtime.wflite.registry`);
these tests live with its owner, workflow-nodes, and read it from Studio's
side: one registry, every field with a named reader, the outputs and the
ports it declares as data.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.testing.workflow_types import fixture_node_registry, fixture_node_types
from dw_agent_runtime.wflite import registry as registry_module
from dw_agent_runtime.wflite.catalog import PackCatalog, ShippedToolSpecs
from dw_agent_runtime.wflite.registry import (
    ERROR_OUTPUT,
    NodeTypeSpec,
    build_node_registry,
    catalogue_document,
    catalogue_hash,
    registry_of,
    step_output_schema,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]

# ------------------------------------------------- R1.1: one registry --

_OWNERS = re.compile(r"^(class NodeTypeSpec\b|def build_node_registry\b)", re.MULTILINE)


def registry_definitions(roots: Iterable[Path]) -> list[str]:
    """Each file that defines a `NodeTypeSpec` or a `build_node_registry`."""
    return sorted(
        path.relative_to(root).as_posix()
        for root in roots
        for path in root.rglob("*.py")
        if _OWNERS.search(path.read_text(encoding="utf-8"))
    )


def test_there_is_one_registry_and_it_is_the_cores() -> None:
    found = registry_definitions([REPO / "packages", REPO / "apps"])
    assert found == ["python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py"]


def test_a_second_registry_in_studio_is_seen(tmp_path: Path) -> None:
    second = tmp_path / "python" / "dw_studio" / "src" / "dw_studio" / "workflows"
    second.mkdir(parents=True)
    (second / "node_registry.py").write_text(
        "class NodeTypeSpec:\n    ...\n\ndef build_node_registry():\n    ...\n", encoding="utf-8"
    )
    assert registry_definitions([tmp_path]) == [
        "python/dw_studio/src/dw_studio/workflows/node_registry.py"
    ]


def test_a_type_registered_twice_is_refused_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    six = registry_module._wf_lite_types()
    switch = next(spec for spec in six if spec.type == "logic.switch@1")
    monkeypatch.setattr(registry_module, "_wf_lite_types", lambda: (*six, switch))
    with pytest.raises(ValueError, match=r"logic\.switch@1"):
        build_node_registry()


def test_the_fixture_registry_refuses_a_duplicate_too() -> None:
    with pytest.raises(ValueError, match=r"fixture\.stop@1"):
        registry_of((*fixture_node_types(), fixture_node_types()[5]))
    assert set(build_node_registry()) <= set(fixture_node_registry())


def test_the_pack_path_still_builds_six_types() -> None:
    assert sorted(build_node_registry()) == [
        "ai.llm@1",
        "human.approval@1",
        "logic.switch@1",
        "time.wait@1",
        "tool.call@1",
        "trigger.work_item@1",
    ]


def test_every_shipped_pack_still_loads() -> None:
    tools = ShippedToolSpecs.load(REPO / "configs" / "tools")
    loaded = PackCatalog.load(REPO / "configs" / "packs", tools)
    assert loaded.all(), "configs/packs ships at least one workflow"


# ------------------------------------------- R1.4 (WN15): every field read --

# Each field of `NodeTypeSpec` and one reader of it, `<module>:<qualname>`.
# A field joins the class with its first reader, in the same change.
READERS: dict[str, str] = {
    "type": "dw_agent_runtime.wflite.registry:registry_of",
    "label_vi": "dw_agent_runtime.wflite.registry:_catalogue_entry",
    "config_schema": "dw_agent_runtime.wflite.validate:_Check._config",
    "output": "dw_agent_runtime.wflite.registry:NodeTypeSpec.output_schema",
    "ports": "dw_agent_runtime.wflite.registry:NodeTypeSpec.lanes",
    "block": "dw_agent_runtime.wflite.ir:_Lowering.wire",
    "ends_run": "dw_agent_runtime.wflite.ir:_Lowering.wire",
    "exits_loop": "dw_agent_runtime.wflite.ir:_Lowering.wire",
    "dependencies": "dw_studio.workflows.application.dependencies:WorkflowDependencies.__call__",
    "side_effect_level": "dw_agent_runtime.wflite.registry:_catalogue_entry",
    "is_trigger": "dw_agent_runtime.wflite.validate:_Check._trigger",
    "effect_door": "dw_agent_runtime.wflite.node_wrapper:StudioNode._attempt",
    "body": "dw_agent_runtime.wflite.node_wrapper:StudioNode.__init__",
    "record_uses": "dw_studio.workflows.application.boundary:derive_workflow_boundary",
}


def reader_source(reader: str) -> str:
    module_name, _, qualname = reader.partition(":")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    return inspect.getsource(target)


def test_every_field_has_a_row_and_every_row_a_field() -> None:
    assert {field.name for field in dataclasses.fields(NodeTypeSpec)} == set(READERS)


@pytest.mark.parametrize(("field", "reader"), sorted(READERS.items()))
def test_each_named_reader_reads_its_field(field: str, reader: str) -> None:
    assert f".{field}" in reader_source(reader), f"{reader} does not read .{field}"


def test_a_field_nobody_reads_is_seen() -> None:
    """WN15's negative: a field added without a row makes the first test red,
    and a row naming a reader that does not read it makes the second red."""

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class Wider(NodeTypeSpec):
        capability_labels: tuple[str, ...] = ()

    assert {field.name for field in dataclasses.fields(Wider)} != set(READERS)
    assert ".capability_labels" not in reader_source(READERS["label_vi"])


# --------------------------------------------------- R1.5: a step's error --


@pytest.mark.parametrize("on_error", ["continue", "route"])
def test_a_step_that_goes_on_after_failing_publishes_error(on_error: Any) -> None:
    spec = build_node_registry()["tool.call@1"]
    schema = step_output_schema(spec, {}, on_error)
    assert schema["properties"]["error"] == ERROR_OUTPUT
    assert ERROR_OUTPUT["properties"] == {"code": {"type": "string"}, "message": {"type": "string"}}
    # The type's own output is still there.
    assert "result" in schema["properties"]


@pytest.mark.parametrize("on_error", ["fail", None])
def test_a_step_that_stops_on_failure_publishes_no_error(on_error: Any) -> None:
    spec = build_node_registry()["tool.call@1"]
    assert "error" not in step_output_schema(spec, {}, on_error)["properties"]


def test_error_joins_an_output_taken_from_the_config() -> None:
    spec = build_node_registry()["ai.llm@1"]
    config = {"output_schema": {"type": "object", "properties": {"score": {"type": "integer"}}}}
    schema = step_output_schema(spec, config, "route")
    assert set(schema["properties"]) == {"score", "error"}
    # The step's own config is not changed by it.
    assert set(config["output_schema"]["properties"]) == {"score"}


# --------------------------------- R1.2, R1.5: outputs and ports as data --


def test_the_outputs_and_lanes_are_computed_from_the_declarations() -> None:
    nodes = build_node_registry()
    approval, switch, llm = nodes["human.approval@1"], nodes["logic.switch@1"], nodes["ai.llm@1"]
    assert approval.lanes({"approved": [{"id": "a"}]}) == {
        "approved": [{"id": "a"}],
        "rejected": [],
    }
    assert switch.lanes({"cases": {"hot": [{"id": "h"}], "cold": "x"}}) == {
        "cases.hot": [{"id": "h"}],
        "cases.cold": [],
    }
    assert switch.lanes({"cases": {}, "default": [{"id": "d"}]}) == {"default": [{"id": "d"}]}
    assert llm.output_schema({}) == {"type": "object", "properties": {}}
    assert llm.output_schema({"output_schema": {"type": "object"}}) == {"type": "object"}


def _entry(document: dict[str, Any], name: str) -> dict[str, Any]:
    return next(entry for entry in document["types"] if entry["type"] == name)


def test_the_catalogue_names_the_ports_and_the_error() -> None:
    document = catalogue_document(build_node_registry())
    assert [entry["type"] for entry in document["types"]] == sorted(build_node_registry())

    approval = _entry(document, "human.approval@1")
    assert approval["ports"] == {
        "kind": "fixed",
        "ports": [
            {"name": "approved", "label_vi": "Duyệt"},
            {"name": "rejected", "label_vi": "Từ chối"},
        ],
    }
    switch = _entry(document, "logic.switch@1")
    assert switch["ports"] == {
        "kind": "keyed",
        "key": "cases",
        "default": {"name": "default", "label_vi": "Khác"},
    }
    llm = _entry(document, "ai.llm@1")
    assert llm["output"] == {"kind": "config", "key": "output_schema"}
    assert approval["error"] == {"on_error": ["continue", "route"], "schema": dict(ERROR_OUTPUT)}
    assert {entry["side_effect_level"] for entry in document["types"]} == {"none"}
    assert all(entry["label_vi"] for entry in document["types"])


def test_the_catalogue_hash_moves_with_a_schema() -> None:
    nodes = build_node_registry()
    changed = dict(nodes)
    changed["time.wait@1"] = dataclasses.replace(
        nodes["time.wait@1"], config_schema={"type": "object"}
    )
    assert catalogue_hash(nodes) == catalogue_hash(build_node_registry())
    assert catalogue_hash(changed) != catalogue_hash(nodes)
