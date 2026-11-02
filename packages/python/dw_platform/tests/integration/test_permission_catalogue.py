"""The permission catalogue against the code and the seeded grants
(tenant-rbac ticket 01: R1.1, R1.2, R1.6; RB2).

Four checks, each a function over plain data so the synthetic cases below can
show it fails, and one integration test running them on the migrated
catalogue and the real source tree:

(a) every key a seeded role or permission set grants has a row, `active` or
    `retired`, never `unassigned`;
(b) every key code checks has a row, `active` or `unassigned`, never
    `retired`. "Checks" is read with `ast` over `apps/*/src` and
    `packages/python/*/src`: the `action` of every `.require(...)` that has
    one, the first argument of `idempotent(`, the argument of `has_scope(`,
    the left side of `in`/`not in` against a name or attribute `scopes`, and
    every module string constant named `*_SCOPE`; each a string, or a module
    constant resolved through imports. A check function passed instead of a
    key is skipped (it calls `.require(` itself). Anything else that does not
    resolve fails, but for the transit points listed with their reasons;
    plus `required_scopes` of `configs/tools` and the web navigation's
    `scope`/`anyScope`;
(c) every `active` key has a check, but for the exceptions listed with
    their reasons;
(d) every `studio.*` key, in the catalogue or checked, is
    `studio.<area>.<verb>` with an area from the list below (R1.6).
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[5]

# Where a key reaches a check from its caller, so the key is not here to
# resolve: each (file, function) with its reason.
TRANSIT: Mapping[tuple[str, str], str] = {
    ("authorization.py", "holds_stamped_scope"): "the scope stamped on an approval row",
    ("authorization.py", "is_allowed"): "the authorization door, given its action by the caller",
    ("access_context.py", "has_scope"): "the context's own test, given its scope by the caller",
    ("idempotency.py", "_authorize"): "the key comes from the route's `idempotent(...)`",
}

# Active keys no `ast` reading sees checked, each with its reason.
UNCHECKED_ACTIVE: Mapping[str, str] = {
    "platform.admin": "held as the role `platform_admin`, which the authorization door reads",
}

# Studio's areas (R1.6): plural countable nouns, and five singular ones.
STUDIO_AREAS: Mapping[str, str] = {
    **dict.fromkeys(
        ("agents", "workflows", "objects", "versions", "bindings", "tools", "packs"),
        "plural countable noun",
    ),
    "evals": "plural countable noun",
    "publish": "an action",
    "lifecycle": "a process",
    "datahub": "a product name",
    "code": "an uncountable noun",
    "mcp": "a protocol name",
}


@dataclass
class Scan:
    keys: dict[str, set[str]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    def add(self, key: str, site: str) -> None:
        self.keys.setdefault(key, set()).add(site)


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def scan_sources(roots: Iterable[Path]) -> Scan:
    """(b)'s reading of the code: every key it checks, and every check whose
    key does not resolve, outside `TRANSIT`."""
    modules: dict[str, tuple[Path, ast.Module]] = {}
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            modules[_module_name(path, root)] = (path, ast.parse(path.read_text("utf-8")))
    consts: dict[str, dict[str, str]] = {}
    imports: dict[str, dict[str, tuple[str, str]]] = {}
    functions: dict[str, set[str]] = {}
    for name, (_, tree) in modules.items():
        found: dict[str, str] = {}
        imported: dict[str, tuple[str, str]] = {}
        defs: set[str] = set()
        for top in tree.body:
            value = getattr(top, "value", None)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                targets = (
                    top.targets
                    if isinstance(top, ast.Assign)
                    else [getattr(top, "target", None)]
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = value.value
            elif isinstance(top, ast.ImportFrom) and top.module:
                for alias in top.names:
                    imported[alias.asname or alias.name] = (top.module, alias.name)
            elif isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef):
                defs.add(top.name)
        consts[name], imports[name], functions[name] = found, imported, defs

    def lookup(
        module: str, name: str, table: Mapping[str, Mapping[str, object]]
    ) -> tuple[str, str] | None:
        seen: set[tuple[str, str]] = set()
        here: tuple[str, str] | None = (module, name)
        while here is not None and here not in seen:
            seen.add(here)
            if here[1] in table.get(here[0], {}):
                return here
            here = imports.get(here[0], {}).get(here[1])
        return None

    def resolve(module: str, expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name):
            at = lookup(module, expr.id, consts)
            if at is not None:
                return consts[at[0]][at[1]]
        return None

    def is_function(module: str, expr: ast.expr) -> bool:
        if isinstance(expr, ast.Lambda):
            return True
        if isinstance(expr, ast.Name):
            at = lookup(module, expr.id, {m: dict.fromkeys(d) for m, d in functions.items()})
            return at is not None
        return False

    scan = Scan()
    for module, (path, tree) in modules.items():
        spans = [
            (node.lineno, node.end_lineno or node.lineno, node.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]

        def enclosing(line: int, spans: list[tuple[int, int, str]] = spans) -> str:
            inside = [span for span in spans if span[0] <= line <= span[1]]
            return max(inside)[2] if inside else ""

        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id.endswith("_SCOPE")
                        and isinstance(stmt.value.value, str)
                    ):
                        scan.add(stmt.value.value, f"{path.name}:{stmt.lineno}")
        for node in ast.walk(tree):
            candidates: list[ast.expr] = []
            if isinstance(node, ast.Call):
                func = node.func
                called = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else func.id
                    if isinstance(func, ast.Name)
                    else ""
                )
                if called == "require":
                    candidates += [k.value for k in node.keywords if k.arg == "action"]
                elif called == "idempotent" and node.args:
                    candidates.append(node.args[0])
                elif called == "has_scope":
                    candidates += node.args[-1:] or [k.value for k in node.keywords]
            elif isinstance(node, ast.Compare):
                for op, right in zip(node.ops, node.comparators, strict=True):
                    named = (
                        right.attr
                        if isinstance(right, ast.Attribute)
                        else right.id
                        if isinstance(right, ast.Name)
                        else ""
                    )
                    if isinstance(op, ast.In | ast.NotIn) and named == "scopes":
                        candidates.append(node.left)
            for candidate in candidates:
                key = resolve(module, candidate)
                line = candidate.lineno
                site = f"{path.name}:{line}"
                if key is not None:
                    scan.add(key, site)
                elif is_function(module, candidate):
                    continue
                elif (path.name, enclosing(line)) not in TRANSIT:
                    scan.unresolved.append(f"{site} {ast.unparse(candidate)}")
    return scan


def scan_configs(repo: Path) -> Scan:
    """The keys tools and the web navigation name."""
    scan = Scan()
    for path in sorted((repo / "configs" / "tools").rglob("*.yaml")):
        for key in yaml.safe_load(path.read_text("utf-8")).get("required_scopes") or []:
            scan.add(str(key), path.name)
    registry = (repo / "apps" / "web" / "lib" / "nav" / "registry.ts").read_text("utf-8")
    for match in re.finditer(r"(?:scope|anyScope):\s*(\"[^\"]+\"|\[[^\]]*\])", registry):
        for key in re.findall(r"\"([^\"]+)\"", match.group(1)):
            scan.add(key, "nav/registry.ts")
    return scan


def catalogue_problems(
    catalogue: Mapping[str, str],
    granted: Iterable[str],
    checked: Iterable[str],
    unchecked_active: Mapping[str, str] = UNCHECKED_ACTIVE,
) -> list[str]:
    """(a), (b), (c): the catalogue is `{key: status}`."""
    problems: list[str] = []
    checked_set = set(checked)
    for key in sorted(set(granted)):
        if catalogue.get(key) not in ("active", "retired"):
            problems.append(f"(a) {key} is granted, catalogue says {catalogue.get(key)}")
    for key in sorted(checked_set):
        if catalogue.get(key) not in ("active", "unassigned"):
            problems.append(f"(b) {key} is checked, catalogue says {catalogue.get(key)}")
    for key, status in sorted(catalogue.items()):
        if status == "active" and key not in checked_set and key not in unchecked_active:
            problems.append(f"(c) {key} is active and nothing checks it")
    return problems


def studio_problems(keys: Iterable[str]) -> list[str]:
    """(d): `studio.<area>.<verb>`, the area from `STUDIO_AREAS`."""
    problems = []
    for key in sorted(set(keys)):
        if not key.startswith("studio."):
            continue
        parts = key.split(".")
        if len(parts) != 3 or parts[1] not in STUDIO_AREAS:
            problems.append(f"(d) {key} is not studio.<area>.<verb>")
    return problems


def _roots(repo: Path) -> list[Path]:
    return [*repo.glob("apps/*/src"), *repo.glob("packages/python/*/src")]


async def test_the_catalogue_matches_the_code_and_the_seeded_grants(
    db_urls: DatabaseUrls,
) -> None:
    """R1.1, R1.2, R1.6 (RB2) on the migrated catalogue and this tree."""
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            catalogue: dict[str, str] = {
                row.key: row.status
                for row in await conn.execute(
                    sa.text("SELECT key, status FROM platform.permissions")
                )
            }
            granted: set[str] = set()
            for table in ("platform.roles", "platform.permission_sets"):
                for (scopes,) in await conn.execute(sa.text(f"SELECT scopes FROM {table}")):
                    granted.update(scopes if isinstance(scopes, list) else json.loads(scopes))
    finally:
        await engine.dispose()
    code = scan_sources(_roots(REPO))
    configs = scan_configs(REPO)
    assert code.unresolved == []
    checked = set(code.keys) | set(configs.keys)
    assert catalogue_problems(catalogue, granted, checked) == []
    assert studio_problems(set(catalogue) | checked) == []
    # The anomalies keep the states the migration gives them (ticket step 3).
    assert {k: catalogue[k] for k in ("approvals.pending", "feedback.inbox")} == {
        "approvals.pending": "retired",
        "feedback.inbox": "retired",
    }
    assert {
        catalogue[k]
        for k in (
            "runs.cancel",
            "knowledge.publish_global",
            "crm.records.all.read",
            "platform.usage.read",
        )
    } == {"unassigned"}
    # Keys only a constant names are seen (gate B1).
    assert {"approvals.decide", "dw.manage", "platform.roles.read"} <= set(code.keys)


# ---- the checks can fail (R1.1, R1.2, R1.6) --------------------------------


def _tree(tmp: Path, files: Mapping[str, str]) -> Path:
    root = tmp / "src"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    return root


def test_a_key_checked_through_a_constant_imported_elsewhere_is_seen(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/keys.py": 'X_Y = "x.y"\n',
            "pkg/service.py": (
                "from pkg.keys import X_Y\n"
                "async def act(authz, ctx):\n"
                "    await authz.require(context=ctx, action=X_Y, resource_type='r')\n"
            ),
            "pkg/route.py": "R = idempotent('route.key', operation='POST /r')\n",
        },
    )
    scan = scan_sources([root])
    assert set(scan.keys) == {"x.y", "route.key"} and scan.unresolved == []
    assert catalogue_problems({"route.key": "active"}, [], scan.keys) == [
        "(b) x.y is checked, catalogue says None"
    ]


def test_a_check_whose_key_does_not_resolve_is_reported(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "pkg/a.py": (
                "def check(x): ...\n"
                "async def act(authz, ctx, k):\n"
                "    await authz.require(context=ctx, action=k + '.read', resource_type='r')\n"
                "    idempotent(check, operation='POST /x')\n"
            )
        },
    )
    scan = scan_sources([root])
    assert scan.keys == {} and len(scan.unresolved) == 1
    assert "k + '.read'" in scan.unresolved[0]


def test_each_catalogue_rule_fails_on_its_case() -> None:
    """(a) a granted key unassigned; (b) a checked key retired or missing;
    (c) an active key nothing checks, unless excepted."""
    assert catalogue_problems({"approvals.decide": "unassigned"}, ["approvals.decide"], []) == [
        "(a) approvals.decide is granted, catalogue says unassigned"
    ]
    assert catalogue_problems({"runs.cancel": "retired"}, [], ["runs.cancel"]) == [
        "(b) runs.cancel is checked, catalogue says retired"
    ]
    assert catalogue_problems({"x.y": "active"}, [], [], {}) == [
        "(c) x.y is active and nothing checks it"
    ]
    assert catalogue_problems({"x.y": "active"}, [], [], {"x.y": "a reason"}) == []


@pytest.mark.parametrize(
    ("key", "ok"),
    [
        ("studio.agents.settings.manage", False),
        ("studio.agent.read", False),
        ("studio.agents.manage_settings", True),
        ("studio.publish.approve", True),
        ("studio.datahub.manage", True),
    ],
)
def test_studio_keys_are_three_segments_with_a_listed_area(key: str, ok: bool) -> None:
    assert (studio_problems([key]) == []) is ok
    if not ok:
        assert key in studio_problems([key])[0]
