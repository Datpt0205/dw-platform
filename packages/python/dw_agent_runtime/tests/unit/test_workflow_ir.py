"""Unit: one `dw.workflow/v1` in the core, lowered once to `WorkflowIR`, the
pack path's rules, and the platform caps (workflow-engine ticket 01: R1.1,
R2.1, R2.10, R2.11, R2.12; WE14).

The Studio path's rules (`STUDIO_RULES`) are `dw_studio`'s tests; here a pack
and a wf-ai proposal keep loading as they did, and the validator and the
compiler read the same IR.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import shutil
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.assistant import Bases, checked_proposal
from dw_agent_runtime.wflite.catalog import (
    PackCatalog,
    ShippedToolSpecs,
    load_shipped_packs,
    workflow_sha256,
)
from dw_agent_runtime.wflite.compile import compile_workflow
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.ir import (
    MAX_NESTING,
    MAX_TREE_STEPS,
    Join,
    Terminal,
    dominators,
    iter_lanes,
    lower,
    reachable,
)
from dw_agent_runtime.wflite.registry import NodeTypeSpec, build_node_registry, no_dependencies
from dw_agent_runtime.wflite.validate import (
    MESSAGES,
    PACK_RULES,
    STEP_POLICY_KEYS,
    PathRules,
    validate,
)
from dw_agent_runtime.wflite.versions import TenantVersion, tenant_pinned
from dw_kernel.errors import ConfigError

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIGS = REPO / "configs"
SHIPPED = load_shipped_packs(CONFIGS)
LEAD_CARE = SHIPPED.workflow("lead_care", "1.0.0")


class Tools:
    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> Any:
        return SimpleNamespace(
            side_effect_level="external" if name == "email.send" else "internal",
            output_fields=(),
        )


def pack(*steps: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {
        "schema": "dw.workflow/v1",
        "key": "probe",
        "version": "1.0.0",
        "triggers": [{"id": "intake", "type": "trigger.work_item@1", "config": {"kind": "x"}}],
        "steps": list(steps),
        **top,
    }


def wait(step_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": step_id, "type": "time.wait@1", "config": {"seconds": 5}, **extra}


def switch(step_id: str, inner: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "logic.switch@1",
        "config": {"on": "x", "cases": {"a": inner}, "default": []},
    }


def problems(
    document: dict[str, Any], rules: PathRules = PACK_RULES, **kw: Any
) -> list[tuple[str, str]]:
    return [
        (p.code, p.path)
        for p in validate(
            document,
            registry=kw.pop("registry", fixture_node_registry()),
            rules=rules,
            tools=Tools(),
            work_schemas={},
            **kw,
        )
    ]


def codes(document: dict[str, Any], rules: PathRules = PACK_RULES) -> list[str]:
    return [code for code, _ in problems(document, rules)]


def nested(depth: int) -> dict[str, Any]:
    """`depth` switches, each in the `a` case of the one before."""
    inner: list[dict[str, Any]] = [wait("leaf")]
    for level in range(depth - 1, 0, -1):
        inner = [switch(f"s{level}", inner)]
    return pack(*inner)


# ---------------------------------------------------------- R2.1: the spec --


@pytest.mark.parametrize("missing", ["block", "ends_run", "exits_loop", "dependencies"])
def test_a_type_that_forgets_one_of_the_four_cannot_be_built(missing: str) -> None:
    """R2.1: no default, so a type that forgot one is an error where it is
    built, never a silent `False`."""
    fields: dict[str, Any] = {
        "type": "probe@1",
        "config_schema": {"type": "object"},
        "output_schema": lambda config: {},
        "block": "none",
        "ends_run": False,
        "exits_loop": False,
        "dependencies": no_dependencies,
    }
    del fields[missing]
    with pytest.raises(TypeError, match=missing):
        NodeTypeSpec(**fields)


def test_the_six_wf_lite_types_declare_how_they_lower() -> None:
    shapes = {
        name: (spec.block, spec.ends_run, spec.exits_loop, spec.dependencies({}))
        for name, spec in build_node_registry().items()
    }
    assert shapes == {
        "trigger.work_item@1": ("none", False, False, ()),
        "ai.llm@1": ("none", False, False, ()),
        "tool.call@1": ("none", False, False, ()),
        "human.approval@1": ("choice", False, False, ()),
        "time.wait@1": ("none", False, False, ()),
        "logic.switch@1": ("choice", False, False, ()),
    }


# ------------------------------------------------------- the lanes and IR --


def test_a_lane_sits_where_its_type_says_and_the_error_lane_last() -> None:
    raw = {
        "id": "route",
        "type": "logic.switch@1",
        "config": {"on": "x", "cases": {"a/b": [], "c.d": []}, "default": []},
        "error_lane": [],
    }
    lanes = iter_lanes(raw, build_node_registry())
    assert [(lane.port, lane.path, lane.is_error) for lane in lanes] == [
        ("cases.a/b", "config/cases/a~1b", False),
        ("cases.c.d", "config/cases/c.d", False),
        ("default", "config/default", False),
        ("error_lane", "error_lane", True),
    ]


def test_a_case_value_with_a_slash_is_one_pointer_segment() -> None:
    """Gate MEDIUM (a): RFC 6901 escaping of a case value."""
    document = pack(
        {
            "id": "route",
            "type": "logic.switch@1",
            "config": {"on": "x", "cases": {"a/b": [{"id": "x", "type": "nope@1"}]}, "default": []},
        }
    )
    assert problems(document) == [("wf.unknown_type", "steps/0/config/cases/a~1b/0/type")]


def _ir(*steps: dict[str, Any]) -> Any:
    document = WorkflowDocument.model_validate(pack(*steps))
    return lower(document, fixture_node_registry())


def test_a_choice_lane_does_not_dominate_what_follows_the_block() -> None:
    ir = _ir(
        {
            "id": "c",
            "type": "fixture.choice@1",
            "config": {"on": "x", "yes": [wait("y")], "no": []},
        },
        wait("after"),
    )
    index = {placed.step.id: placed.index for placed in ir.steps}
    doms = dominators(ir)
    assert doms.dominates(index["c"], index["after"])
    assert doms.dominates(index["c"], index["y"])
    assert not doms.dominates(index["y"], index["after"])
    assert Join(index["c"]) in reachable(ir)
    assert ir.edges[Terminal.START] == (index["c"],)


def test_a_loop_body_returns_to_its_loop_and_a_break_leaves_it() -> None:
    ir = _ir(
        {
            "id": "lap",
            "type": "fixture.loop@1",
            "config": {
                "max_iterations": 3,
                "body": [wait("b1"), {"id": "out", "type": "fixture.break@1"}, wait("dead")],
            },
        }
    )
    index = {placed.step.id: placed.index for placed in ir.steps}
    assert index["lap"] in ir.edges[index["b1"]] or index["out"] in ir.edges[index["b1"]]
    assert ir.edges[index["out"]] == (Join(index["lap"]),)
    assert index["dead"] not in reachable(ir)


# ------------------------------------------------- R1.1: packs unchanged --


def test_every_shipped_pack_loads() -> None:
    assert {(p.key, p.version) for p in SHIPPED.all()} >= {("lead_care", "1.0.0")}


def test_lead_care_compiles_to_the_graph_it_compiled_to_before_the_ir() -> None:
    """R1.1, WE14: the node and edge sets recorded at the ticket's base
    commit, the join and wait nodes by name."""
    recorded = json.loads((FIXTURES / "lead_care_graph.json").read_text(encoding="utf-8"))
    assert LEAD_CARE is not None
    tools = SimpleNamespace(
        resolve=lambda name, version, tenant_id=None: SimpleNamespace(
            behaviour=SimpleNamespace(input_schema=lambda: {"type": "object"})
        )
    )
    graph = compile_workflow(LEAD_CARE, SimpleNamespace(tools=tools)).compile().get_graph()  # type: ignore[arg-type]
    assert sorted(graph.nodes) == recorded["nodes"]
    edges = sorted([e.source, e.target, bool(e.conditional)] for e in graph.edges)
    assert edges == recorded["edges"]


def test_a_tenant_version_stored_before_this_ticket_still_reads() -> None:
    """R1.1: `+t<n>` content as wf-ai stored it (a pack's dump with one
    description changed) reads through `tenant_pinned` and passes the pack
    path."""
    assert LEAD_CARE is not None
    content = json.loads((FIXTURES / "tenant_version_before_we01.json").read_text("utf-8"))
    stored = TenantVersion(
        dw_id=uuid.uuid4(),
        key="lead_care",
        version="1.0.0+t1",
        content=content,
        content_sha256=workflow_sha256(content),
        base_sha256="0" * 64,
        author_ids=(uuid.uuid4(),),
        approved_by=uuid.uuid4(),
        approval_id=uuid.uuid4(),
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    pinned = tenant_pinned(LEAD_CARE, stored)
    assert pinned.document.model_dump(by_alias=True, exclude_none=True) == content
    found = validate(
        content,
        registry=build_node_registry(),
        rules=PACK_RULES,
        tools=ShippedToolSpecs.load(CONFIGS / "tools"),
        work_schemas=LEAD_CARE.work_schemas,
    )
    assert found == []


# ------------------------------------------------- R1.1: the pack path --


def test_the_pack_rules_are_the_ticket_s() -> None:
    assert (
        PathRules(
            required_document_keys=frozenset({"key", "version"}),
            # A pack has no Binding set (tenant-config ticket 05).
            refused_document_keys=frozenset({"bindings"}),
            required_step_keys=frozenset(),
            refused_step_keys=frozenset({"retry", "timeout_s", "on_error", "error_lane"}),
            every_port_lane=False,
        )
        == PACK_RULES
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("retry", {"max_attempts": 2, "backoff": "fixed"}),
        ("timeout_s", 30),
        ("on_error", "fail"),
        ("error_lane", []),
    ],
)
def test_a_pack_step_with_a_policy_key_is_refused(key: str, value: Any) -> None:
    """R1.1: the wf-lite compiler runs none of the four yet (failure-modes #1)."""
    document = pack(switch("route", [wait("inner", **{key: value})]))
    assert ("wf.schema_invalid", f"steps/0/config/cases/a/0/{key}") in problems(document)


def test_a_pack_declaring_bindings_is_refused_and_no_dump_carries_them() -> None:
    """tenant-config ticket 05: a pack has no Binding set to give a binding a
    value, so the key is refused on its path; a Studio document's bindings
    are read by Studio's shape and never written back by a dump."""
    document = pack(wait("w"))
    document["bindings"] = [{"name": "x", "kind": "principal", "required": True}]
    assert ("wf.schema_invalid", "bindings") in problems(document)
    assert "bindings" not in WorkflowDocument.model_validate(document).model_dump(by_alias=True)


def test_a_pack_without_its_key_or_version_is_refused() -> None:
    document = pack(wait("w"))
    del document["key"], document["version"]
    assert problems(document) == [
        ("wf.schema_invalid", "key"),
        ("wf.schema_invalid", "version"),
    ]


def test_a_pack_with_on_error_does_not_load(tmp_path: Path) -> None:
    """R1.1: the catalog refuses it, naming the code."""
    root = tmp_path / "packs"
    shutil.copytree(FIXTURES / "packs", root)
    path = root / "sample" / "workflows" / "sample@1.0.0.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("    type: time.wait@1\n", "    type: time.wait@1\n    on_error: fail\n"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"wf.schema_invalid at steps/2/on_error"):
        PackCatalog.load(root, Tools())


def test_a_wf_ai_proposal_with_an_error_lane_is_refused() -> None:
    """R1.1: the assistant's proposal goes through the pack path."""
    assert LEAD_CARE is not None
    steps = copy.deepcopy(LEAD_CARE.document.model_dump(by_alias=True, exclude_none=True))["steps"]
    steps[0]["error_lane"] = []
    _, found = checked_proposal(
        Bases(LEAD_CARE, LEAD_CARE), steps, registry=build_node_registry(), tools=Tools()
    )
    assert ("wf.schema_invalid", "steps/0/error_lane") in [(p.code, p.path) for p in found]


@pytest.mark.parametrize("rules", [PACK_RULES, PathRules(*(frozenset(),) * 4, True)])
def test_a_trigger_with_a_policy_key_is_refused_on_every_path(rules: PathRules) -> None:
    document = pack(wait("w"))
    document["triggers"][0]["retry"] = {"max_attempts": 1, "backoff": "fixed"}
    assert ("wf.schema_invalid", "triggers/0/retry") in problems(document, rules)
    assert {"retry", "timeout_s", "on_error", "error_lane"} == STEP_POLICY_KEYS


@pytest.mark.parametrize("step_id", ["join__a", "wait__a"])
def test_a_step_id_the_compiler_names_its_own_nodes_with_is_refused(step_id: str) -> None:
    """A step `join__a` would be the join node of a step `a`."""
    assert problems(pack(wait(step_id))) == [("wf.schema_invalid", "steps/0/id")]


# ------------------------------------------------- R2.10: the two caps --


def test_five_hundred_steps_pass_and_the_five_hundred_and_first_is_named() -> None:
    assert codes(pack(*(wait(f"w{n}") for n in range(MAX_TREE_STEPS)))) == []
    over = pack(*(wait(f"w{n}") for n in range(MAX_TREE_STEPS + 1)))
    assert problems(over) == [("wf.limit_above_plan", f"steps/{MAX_TREE_STEPS}")]


def test_steps_in_lanes_count_toward_the_cap() -> None:
    """Every lane at every depth, error lanes included."""
    inner = [wait(f"i{n}") for n in range(MAX_TREE_STEPS - 1)]
    assert codes(pack(switch("route", inner))) == []
    assert codes(pack(switch("route", [*inner, wait("one_more")]))) == ["wf.limit_above_plan"]


def test_depth_ten_passes_and_depth_eleven_is_named() -> None:
    """R2.10: by nested switches alone."""
    assert codes(nested(MAX_NESTING)) == []
    found = problems(nested(MAX_NESTING + 1))
    assert [code for code, _ in found] == ["wf.limit_above_plan"]
    assert found[0][1].count("/config/cases/a/") == MAX_NESTING


def test_a_tree_nested_two_hundred_deep_is_one_problem_in_well_under_a_second() -> None:
    """R2.10: no RecursionError; the lowering stops at the cap."""
    started = time.perf_counter()
    found = codes(nested(200))
    assert time.perf_counter() - started < 1.0
    assert found == ["wf.limit_above_plan"]


# ----------------------------------------- R2.12, R2.11: one owner, one table --

_OWNED = {
    "class WorkflowDocument": r"^class WorkflowDocument\b",
    "def lower(": r"^def lower\(",
    "class NodeTypeSpec": r"^class NodeTypeSpec\b",
    "def compile_workflow": r"^def compile_workflow\b",
    "MESSAGES": r"^MESSAGES\b",
}


def _sources(roots: Iterable[Path], suffixes: tuple[str, ...] = (".py",)) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            parts = set(path.parts)
            if (
                path.suffix in suffixes
                and path.is_file()
                and not parts & {"node_modules", "tests", "__tests__", ".next", "__pycache__"}
            ):
                found.append(path)
    return found


def owners(roots: Iterable[Path]) -> dict[str, list[str]]:
    """Each one-owner name with every file that defines it."""
    found: dict[str, list[str]] = {name: [] for name in _OWNED}
    for path in _sources(roots):
        text = path.read_text(encoding="utf-8")
        for name, pattern in _OWNED.items():
            if re.search(pattern, text, re.MULTILINE):
                found[name].append(path.as_posix())
    return found


def _roots(repo: Path) -> list[Path]:
    return [repo / "packages", repo / "apps"]


def test_dw_workflow_v1_has_one_model_ir_validator_table_and_compiler() -> None:
    """R2.12 (WE14): each name once, in the core's `wflite`."""
    for name, files in owners(_roots(REPO)).items():
        assert len(files) == 1, (name, files)
        assert "dw_agent_runtime/wflite/" in files[0], (name, files)


def test_a_second_validator_in_studio_is_seen(tmp_path: Path) -> None:
    second = tmp_path / "packages" / "python" / "dw_studio" / "src" / "dw_studio" / "workflows"
    second.mkdir(parents=True)
    (second / "validator.py").write_text("MESSAGES = {}\ndef lower(doc):\n    ...\n")
    found = owners([tmp_path / "packages"])
    assert len(found["MESSAGES"]) == 1 and len(found["def lower("]) == 1


def lane_readers(roots: Iterable[Path]) -> set[str]:
    """Each file that calls `.lanes(`, or reads `error_lane` by attribute or
    by its string, or still names `_NOT_VALUES`."""
    found: set[str] = set()
    for path in _sources(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "lanes"
                )
                or (isinstance(node, ast.Attribute) and node.attr == "error_lane")
                or (isinstance(node, ast.Constant) and node.value == "error_lane")
                or (isinstance(node, ast.Name) and node.id == "_NOT_VALUES")
            ):
                found.add(path.name)
    return found


_LANE_ROOTS = [
    REPO / "packages" / "python" / "dw_agent_runtime" / "src" / "dw_agent_runtime" / "wflite",
    REPO / "packages" / "python" / "dw_studio" / "src" / "dw_studio",
]


def test_only_the_ir_reads_where_a_lane_sits() -> None:
    """R2.12: `.lanes(` and `error_lane` in `wflite/ir.py` alone."""
    assert lane_readers(_LANE_ROOTS) == {"ir.py"}


def test_a_lane_read_in_the_compiler_is_seen(tmp_path: Path) -> None:
    (tmp_path / "compile.py").write_text("def f(spec, c):\n    return spec.lanes(c)\n")
    (tmp_path / "other.py").write_text("def g(step):\n    return step.error_lane\n")
    assert lane_readers([tmp_path]) == {"compile.py", "other.py"}


_CODE = re.compile(r"[\"'](wf\.[a-z_]+)[\"']")


def wf_codes(roots: Iterable[Path]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in _sources(roots, (".py", ".ts", ".tsx")):
        for code in _CODE.findall(path.read_text(encoding="utf-8")):
            found.setdefault(code, set()).add(path.name)
    return found


def test_every_wf_code_in_the_source_is_in_the_one_table() -> None:
    """R2.11: and every entry has both its Vietnamese and English words."""
    unknown = {
        code: files for code, files in wf_codes(_roots(REPO)).items() if code not in MESSAGES
    }
    assert unknown == {}
    assert all(vi.strip() and en.strip() for vi, en in MESSAGES.values())
    assert {"wf.unreachable_node", "wf.limit_above_plan", "wf.unknown_type"} <= set(MESSAGES)
    assert "wf.unknown_node_type" not in MESSAGES


def test_a_code_outside_the_table_is_seen(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text('CODE = "wf.made_up"\n')
    assert wf_codes([tmp_path]) == {"wf.made_up": {"x.py"}}
