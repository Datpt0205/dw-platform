"""Every metric `ALL_METRICS` declares is emitted somewhere in `src/` (spec R1.3, TA3).

Seven names sat in `metrics.py` with no emitter, so a dashboard built on them
would have read zero for ever (`failure-modes.md` #1). A grep for the name does
not find that, because the declaration is itself a hit; this asks the syntax
tree for a call whose first argument is the constant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dw_observability import metrics
from dw_observability.metrics import ALL_METRICS

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
EMITTERS = frozenset({"add_metric", "set_gauge", "record_histogram"})


def _source_files() -> list[Path]:
    roots = [
        *(REPO_ROOT / "packages" / "python").glob("*/src"),
        *(REPO_ROOT / "apps").glob("*/src"),
    ]
    return [path for root in roots for path in root.rglob("*.py")]


def emitted_metric_names(files: list[Path]) -> set[str]:
    """Values of the metric constants passed first to an emitting call."""
    by_constant = {
        name: value
        for name, value in vars(metrics).items()
        if isinstance(value, str) and name.isupper()
    }
    found: set[str] = set()
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in EMITTERS
                and node.args
            ):
                continue
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in by_constant:
                found.add(by_constant[first.id])
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def test_every_declared_metric_is_emitted() -> None:
    unemitted = sorted(set(ALL_METRICS) - emitted_metric_names(_source_files()))
    assert unemitted == [], f"declared in ALL_METRICS and emitted by nothing in src/: {unemitted}"


def test_the_rates_and_the_node_failure_counter_are_gone() -> None:
    """Removed until something emits them; workflow-engine/03 brings back
    `dw_node_failure_total` with its emitter."""
    assert {
        "dw_node_failure_total",
        "dw_retrieval_hit_rate",
        "dw_human_intervention_rate",
        "dw_task_success_rate",
    } & set(ALL_METRICS) == set()


def test_a_declared_name_with_no_emitter_is_found(tmp_path: Path) -> None:
    """The check itself can fail: a module emitting one of two names leaves the other."""
    source = tmp_path / "emitter.py"
    source.write_text(
        "from dw_observability.metrics import DW_RUN_TOTAL\n"
        "def f(t):\n"
        "    t.add_metric(DW_RUN_TOTAL, 1, {})\n",
        encoding="utf-8",
    )
    assert emitted_metric_names([source]) == {"dw_run_total"}
