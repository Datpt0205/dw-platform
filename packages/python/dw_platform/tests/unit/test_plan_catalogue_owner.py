"""No plan catalogue in code (usage-and-limits R1.1, UL1).

`platform.plan_limits` is the one owner of a plan's numbers. The drift it
closed was a dict, `DEFAULT_PLANS`, that the runtime read while the database
held the same plans with its own copy (failure-modes #2). So the source is
read with `ast`: the name `DEFAULT_PLANS` anywhere, or a call building a
`Plan` or a `PlanCaps` outside the adapter that reads the table, is a
second catalogue. A dict renamed and built of plain numbers is not seen; a
`PlanCaps` built from one is. The reader is `dw_usage`'s limits, which read
`platform.plan_limits` in the transaction that admits a run (usage-and-limits
ticket 03).

Every package under `packages/python/*/src` and `apps/*/src` is scanned at
the place Python imports it from, not only at its path in the tree, so a
copy of a package put first on the path (how `scripts/mutate.py` mutates a
`src/` file) is the copy scanned (failure-modes #0).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
_ROOTS = ("packages/python/*/src/*/__init__.py", "apps/*/src/*/__init__.py")
_BUILDERS = frozenset({"Plan", "PlanCaps"})
_NAME = "DEFAULT_PLANS"
# The one module that builds `PlanCaps`, from a row of the table.
OWNER = ("dw_usage", "adapters/limits_sql.py")


def offences(source: str) -> list[str]:
    """Each line of ``source`` that names the code catalogue or builds a plan."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            called = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if called in _BUILDERS:
                found.append(f"{node.lineno}: builds {called}")
        named = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else (node.asname or node.name)
            if isinstance(node, ast.alias)
            else None
        )
        if named == _NAME or (isinstance(node, ast.alias) and node.name == _NAME):
            found.append(f"{getattr(node, 'lineno', '?')}: names {_NAME}")
    return found


def packages(repo: Path) -> dict[str, Path]:
    """Each source package, by name, at the directory Python imports it from."""
    found: dict[str, Path] = {}
    for pattern in _ROOTS:
        for init in sorted(repo.glob(pattern)):
            name = init.parent.name
            spec = importlib.util.find_spec(name)
            locations = list(spec.submodule_search_locations or []) if spec else []
            found[name] = Path(locations[0]) if locations else init.parent
    return found


def violations(roots: dict[str, Path], owner: tuple[str, str] = OWNER) -> list[str]:
    result: list[str] = []
    for name, root in sorted(roots.items()):
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if (name, relative) == owner:
                continue
            result.extend(
                f"{name}/{relative}:{offence}"
                for offence in offences(path.read_text(encoding="utf-8"))
            )
    return result


def test_the_source_tree_holds_no_plan_catalogue() -> None:
    roots = packages(REPO)
    assert {"dw_platform", "dw_agent_runtime", "dw_api", "dw_worker"} <= roots.keys()
    assert violations(roots) == []


def test_the_owner_builds_plan_caps_and_is_the_only_exemption() -> None:
    owner = packages(REPO)["dw_usage"] / OWNER[1]
    assert offences(owner.read_text(encoding="utf-8")), "the adapter is where rows become limits"
    assert violations({"dw_usage": owner.parent}, owner=("dw_usage", "elsewhere.py"))


@pytest.mark.parametrize(
    "source",
    [
        "DEFAULT_PLANS: dict[str, object] = {}",
        "DEFAULT_PLANS = {'basic': 20}",
        "from dw_platform.application.entitlement import DEFAULT_PLANS",
        "import catalogue as DEFAULT_PLANS",
        "service(entitlement.DEFAULT_PLANS)",
        "x = Plan(plan_id='basic', name='Basic', features=frozenset())",
        "x = PlanCaps(plan_id='basic', periods={}, max_cost_usd_per_run=2)",
        "x = limits.PlanCaps(plan_id='basic')",
        "def build():\n    return {'basic': PlanCaps(**row)}",
    ],
)
def test_each_shape_of_a_second_catalogue_is_named(source: str) -> None:
    assert offences(source)


@pytest.mark.parametrize(
    "source",
    [
        "from dw_usage.domain.limits import PlanCaps",
        "def f(limits: PlanCaps) -> PlanCaps:\n    return limits",
        "PLANS_SEEN = {'basic'}",
        "plan = catalogue.limits('basic')",
    ],
)
def test_reading_a_plan_is_not_an_offence(source: str) -> None:
    assert offences(source) == []
