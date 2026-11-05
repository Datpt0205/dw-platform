"""Who sets the record settings, and who builds the tenant-wide registry
(record-access ticket 03, gates (e), (f), (g), (p); ticket 04, gate (g);
ADR-0105 decisions 5 and 6).

`app.workspace_scope = 'tenant'` opens every row of the bound tenant, Studio
records included; `app.actor_kind` is what the record policies admit a
transaction by, and `app.boundary_id` and `app.run_mode` what bound an agent or
a workflow to its run's boundaries. Each has one setter in `tenant_session.py`:
`tenant_wide_scope` the first, `bind_actor` the other three. The source under
`packages/`, `apps/`, `db/migrations/` and `scripts/` is scanned for any other
way of setting one:

* `set_config('<setting>'`, or the setting's name quoted anywhere but inside
  `current_setting(` (a bind parameter naming it);
* `SET`, `SET LOCAL`, `SET SESSION`, and so `ALTER ROLE ... SET` and
  `ALTER DATABASE ... SET`;
* `-c <setting>=` in connection options or `PGOPTIONS`, plain or URL-encoded.

And the calls: `bind_actor(` only from the modules listed with the kinds they
bind; `TenantWideScopeRegistry(` only at the worker's composition root. A
`tests` directory is exempt: a test sets a setting to show what a policy does
with it, and never runs in a deployed process. Each other exemption below
carries its reason.

What this cannot see: a name built at run time, a service in another language.
Those are review's, and the catalog tests of `test_rls_coverage.py` are the
database's half.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
SCANNED = ("packages", "apps", "db/migrations", "scripts")
SETTINGS = ("app.workspace_scope", "app.actor_kind", "app.boundary_id", "app.run_mode")
SETTER = "packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py"

# Frozen: a new entry is a decision, with its reason.
EXEMPT: dict[str, str] = {
    "scripts/bench_records_storage/": (
        "the record-storage bench runs its own measuring database (custom-objects/01,"
        " record-access/01), not the application's, and sets the settings to measure policies"
    ),
}

# Who may call `bind_actor`, with which kinds, and why. `workflow` has no
# production binder yet: the workflow runner's module joins with its own line
# when workflow-engine builds it (record-access ticket 04, step 4).
ACTOR_BINDERS: dict[str, tuple[frozenset[str], str]] = {
    "packages/python/dw_studio/src/dw_studio/records/adapters/user_session.py": (
        frozenset({"user"}),
        "the transaction of an authenticated Studio request, the one door of `user`",
    ),
    "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/record_session.py": (
        frozenset({"agent"}),
        "the transaction of a Studio object tool's call, the one door of `agent` (ticket 04)",
    ),
    "packages/python/dw_studio/src/dw_studio/testing/records.py": (
        frozenset({"user", "agent", "workflow"}),
        "the test helper binding a test's connection as those doors do (gate (p))",
    ),
}

# Where `TenantWideScopeRegistry(` may be called: the worker's composition root.
REGISTRY_BUILDERS: dict[str, str] = {
    "apps/worker/src/dw_worker/main.py": "the worker's composition root (ADR-0105 decision 5)",
}

_NAME = "|".join(re.escape(s) for s in SETTINGS)
_SETTER_FORMS = (
    re.compile(rf"set_config\s*\(\s*['\"]({_NAME})['\"]", re.IGNORECASE),
    re.compile(rf"\bSET\s+(?:LOCAL\s+|SESSION\s+)?['\"]?({_NAME})\b", re.IGNORECASE),
    re.compile(rf"-c\s*['\"]?({_NAME})\s*=", re.IGNORECASE),
    re.compile(rf"({_NAME})%3D", re.IGNORECASE),
    re.compile(rf"['\"]({_NAME})['\"]"),
)
_READ = re.compile(r"current_setting\s*\(\s*$", re.IGNORECASE)


def _exempt(relative: str, extra: dict[str, str]) -> bool:
    return any(relative.startswith(prefix) for prefix in (*EXEMPT, *extra))


def _sources(root: Path) -> list[tuple[str, Path]]:
    found = []
    for top in SCANNED:
        base = root / top
        if not base.exists():
            continue
        for path in sorted([*base.rglob("*.py"), *base.rglob("*.sql")]):
            relative = path.relative_to(root).as_posix()
            if "/tests/" in f"/{relative}" or "/.venv/" in relative or "__pycache__" in relative:
                continue
            found.append((relative, path))
    return found


def setter_violations(root: Path, extra: dict[str, str] | None = None) -> list[str]:
    """Each place outside `tenant_session.py` that sets either setting."""
    extra = extra or {}
    found = []
    for relative, path in _sources(root):
        if relative == SETTER or _exempt(relative, extra):
            continue
        text = path.read_text(encoding="utf-8")
        named: set[str] = set()
        for form in _SETTER_FORMS:
            for match in form.finditer(text):
                if _READ.search(text[max(0, match.start() - 40) : match.start()]):
                    continue
                named.add(match.group(1).lower())
        found += [f"{relative}: sets {name}" for name in sorted(named)]
    return found


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def call_violations(
    root: Path,
    binders: dict[str, tuple[frozenset[str], str]],
    builders: dict[str, str],
) -> list[str]:
    found = []
    for relative, path in _sources(root):
        if not relative.endswith(".py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree, "bind_actor"):
            kinds = [
                arg.value
                for arg in call.args[1:2]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            allowed = binders.get(relative)
            if allowed is None:
                found.append(f"{relative}: calls bind_actor")
            elif len(kinds) != 1 or kinds[0] not in allowed[0]:
                found.append(f"{relative}: binds {kinds or 'a computed kind'}")
        if _calls(tree, "TenantWideScopeRegistry") and relative not in builders:
            found.append(f"{relative}: builds TenantWideScopeRegistry")
    return found


def test_only_tenant_session_sets_the_scope_and_the_actor_kind() -> None:
    assert setter_violations(REPO) == []


def test_only_the_listed_modules_bind_an_actor_or_build_the_registry() -> None:
    assert call_violations(REPO, ACTOR_BINDERS, REGISTRY_BUILDERS) == []


def test_every_exemption_says_why_and_is_still_there() -> None:
    for path, reason in EXEMPT.items():
        assert reason.strip() and (REPO / path).exists(), path
    for path, (kinds, reason) in ACTOR_BINDERS.items():
        assert reason.strip() and kinds and (REPO / path).exists(), path
    for path, reason in REGISTRY_BUILDERS.items():
        assert reason.strip() and (REPO / path).exists(), path
    setter = (REPO / SETTER).read_text(encoding="utf-8")
    assert "set_config('app.workspace_scope', 'tenant', true)" in setter
    assert "set_config('app.actor_kind', :kind, true)" in setter
    assert "set_config('app.boundary_id', :boundary, true)" in setter
    assert "set_config('app.run_mode', :mode, true)" in setter


def _plant(root: Path, where: str, source: str) -> None:
    path = root / where
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "q = \"SELECT set_config('app.workspace_scope', 'tenant', true)\"\n",
        "q = \"SELECT set_config( 'app.actor_kind', 'user', false)\"\n",
        "q = \"SET LOCAL app.workspace_scope = 'tenant'\"\n",
        'q = "SET app.actor_kind TO user"\n',
        "q = \"ALTER ROLE dw_app SET app.workspace_scope = 'tenant'\"\n",
        "q = \"ALTER DATABASE dw SET app.actor_kind = 'user'\"\n",
        'dsn = "postgresql://h/db?options=-c%20app.workspace_scope%3Dtenant"\n',
        "env = {'PGOPTIONS': '-c app.actor_kind=user'}\n",
        "params = {'k': 'app.workspace_scope', 'v': 'tenant'}\n",
        "q = \"SELECT set_config('app.boundary_id', :b, true)\"\n",
        "q = \"SET LOCAL app.run_mode = 'simulate'\"\n",
        "env = {'PGOPTIONS': '-c app.boundary_id=x'}\n",
    ],
    ids=[
        "set_config",
        "set_config spaced",
        "SET LOCAL",
        "SET",
        "ALTER ROLE",
        "ALTER DATABASE",
        "DSN options",
        "PGOPTIONS",
        "parameter",
        "boundary set_config",
        "run mode SET LOCAL",
        "boundary PGOPTIONS",
    ],
)
def test_each_form_of_a_setter_is_named(tmp_path: Path, source: str) -> None:
    _plant(tmp_path, "apps/api/src/dw_api/probe.py", source)
    [named] = setter_violations(tmp_path)
    assert named.startswith("apps/api/src/dw_api/probe.py: sets app.")


def test_a_setter_in_a_migration_or_sql_file_is_named(tmp_path: Path) -> None:
    _plant(
        tmp_path,
        "db/migrations/versions/probe.py",
        "op.execute(\"SET LOCAL app.workspace_scope = 'tenant'\")\n",
    )
    _plant(tmp_path, "scripts/probe.sql", "SELECT set_config('app.actor_kind', 'user', true);\n")
    assert sorted(setter_violations(tmp_path)) == [
        "db/migrations/versions/probe.py: sets app.workspace_scope",
        "scripts/probe.sql: sets app.actor_kind",
    ]


def test_reads_tests_and_exempt_paths_are_not_setters(tmp_path: Path) -> None:
    _plant(
        tmp_path,
        "db/migrations/versions/read.py",
        "P = \"(SELECT current_setting('app.workspace_scope', true)) = 'tenant'\"\n"
        "A = \"SELECT current_setting( 'app.actor_kind', true)\"\n",
    )
    _plant(
        tmp_path,
        "packages/python/dw_x/tests/test_probe.py",
        "q = \"SELECT set_config('app.workspace_scope', 'tenant', true)\"\n",
    )
    _plant(
        tmp_path,
        "scripts/bench_records_storage/records_bench/db.py",
        "q = \"SELECT set_config('app.actor_kind', 'user', true)\"\n",
    )
    assert setter_violations(tmp_path) == []


def test_a_binder_or_a_builder_outside_its_list_is_named(tmp_path: Path) -> None:
    _plant(
        tmp_path,
        "packages/python/dw_platform/src/dw_platform/adapters/probe.py",
        "async def f(s):\n    await bind_actor(s, 'user')\n",
    )
    _plant(
        tmp_path,
        "apps/api/src/dw_api/bootstrap/probe.py",
        "from x import TenantWideScopeRegistry as R\nimport x\nREG = x.TenantWideScopeRegistry()\n",
    )
    _plant(
        tmp_path,
        "packages/python/dw_studio/src/dw_studio/records/adapters/user_session.py",
        "async def f(s):\n    await bind_actor(s, 'agent')\n",
    )
    _plant(
        tmp_path,
        "apps/worker/src/dw_worker/main.py",
        "REG = TenantWideScopeRegistry()\n",
    )
    # Ticket 04 (R6.3, RA18): `agent` from a module outside the list, `workflow`
    # from the runtime's tool session, which binds `agent` only.
    _plant(
        tmp_path,
        "packages/python/dw_studio/src/dw_studio/workflows/adapters/probe.py",
        "async def f(s, r):\n    await bind_actor(s, 'agent', run_id=r)\n",
    )
    _plant(
        tmp_path,
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/record_session.py",
        "async def f(s, r):\n    await bind_actor(s, 'workflow', run_id=r)\n",
    )
    assert sorted(call_violations(tmp_path, ACTOR_BINDERS, REGISTRY_BUILDERS)) == [
        "apps/api/src/dw_api/bootstrap/probe.py: builds TenantWideScopeRegistry",
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/record_session.py:"
        " binds ['workflow']",
        "packages/python/dw_platform/src/dw_platform/adapters/probe.py: calls bind_actor",
        "packages/python/dw_studio/src/dw_studio/records/adapters/user_session.py: binds ['agent']",
        "packages/python/dw_studio/src/dw_studio/workflows/adapters/probe.py: calls bind_actor",
    ]
