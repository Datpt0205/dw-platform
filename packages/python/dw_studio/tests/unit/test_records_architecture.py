"""The records' two source rules (custom-objects ticket 03 steps 1 and 8; R5.6,
R5.9; CO10; ADR-0107 decision 3).

- SQL naming `studio.records` (or `studio.record_write_keys`) lives only in
  `dw_studio.records.adapters`, so every record write goes through
  RecordService's store: a string literal outside it that names the table is
  a second write path (R5.6, CO10). Module paths (`dw_studio.records`) and
  docstrings are prose, not SQL, and are not read.
- No module of `dw_studio.records` sets an `app.*` setting: the door binds the
  transaction (`bind_tenant`, `bind_actor`), the service only runs in it
  (gate (c), R5.9).

Each rule is shown to fail on a module planted in a temporary tree.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
SCANNED = ("packages/python", "apps")
RECORDS = "packages/python/dw_studio/src/dw_studio/records"
TABLE_SQL = re.compile(r"(?<![\w.])studio\.record(?:s|_write_keys)\b")
SETTER = re.compile(r"set_config\(\s*'app\.")

# Frozen: an entry is a decision, with its reason.
SQL_ALLOWED: dict[str, str] = {
    f"{RECORDS}/adapters/": "the records adapter: the one place a record statement is written",
    "packages/python/dw_studio/src/dw_studio/testing/": (
        "test fixtures plant records as the migrator, past the policies; never in a process"
    ),
}


def _strings(tree: ast.AST) -> Iterable[str]:
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.value


def _sources(root: Path, scanned: Iterable[str]) -> Iterable[tuple[str, Path]]:
    for base in scanned:
        for path in sorted((root / base).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if "/tests/" in f"/{relative}" or "/.venv/" in relative:
                continue
            yield relative, path


def record_sql_outside_adapter(root: Path, scanned: Iterable[str] = SCANNED) -> list[str]:
    found = []
    for relative, path in _sources(root, scanned):
        if any(relative.startswith(prefix) for prefix in SQL_ALLOWED):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(TABLE_SQL.search(text) for text in _strings(tree)):
            found.append(relative)
    return found


def settings_set_in_records(root: Path, records: str = RECORDS) -> list[str]:
    return [
        relative
        for relative, path in _sources(root, (records,))
        if SETTER.search(path.read_text(encoding="utf-8"))
    ]


def test_r5_6_co10_only_the_records_adapter_names_the_table() -> None:
    assert record_sql_outside_adapter(REPO) == []


def test_r5_9_gate_c_no_records_module_sets_a_setting() -> None:
    assert settings_set_in_records(REPO) == []


def test_the_rules_name_a_planted_module(tmp_path: Path) -> None:
    """A planted SQL string outside the adapter, and a planted setter inside
    the records package, are each named; a docstring and a module path are not."""
    package = tmp_path / RECORDS
    (package / "adapters").mkdir(parents=True)
    (package / "application").mkdir(parents=True)
    (package / "adapters" / "fine.py").write_text(
        'Q = "SELECT * FROM studio.records"\n', encoding="utf-8"
    )
    (package / "application" / "prose.py").write_text(
        '"""Reads studio.records through the adapter."""\nimport dw_studio.records\n',
        encoding="utf-8",
    )
    (package / "application" / "sneaky.py").write_text(
        "Q = \"UPDATE studio.records SET name = 'x'\"\n"
        "S = \"SELECT set_config('app.actor_kind', 'user', true)\"\n",
        encoding="utf-8",
    )
    (tmp_path / "apps" / "x").mkdir(parents=True)
    (tmp_path / "apps" / "x" / "keys.py").write_text(
        'K = "DELETE FROM studio.record_write_keys"\n', encoding="utf-8"
    )

    assert record_sql_outside_adapter(tmp_path, ("packages/python", "apps")) == [
        f"{RECORDS}/application/sneaky.py",
        "apps/x/keys.py",
    ]
    assert settings_set_in_records(tmp_path) == [f"{RECORDS}/application/sneaky.py"]
