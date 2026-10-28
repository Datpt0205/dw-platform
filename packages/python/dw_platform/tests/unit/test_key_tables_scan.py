"""Only the key stores read the key tables (app-standards R2.26, APS27).

A stored body belongs to its caller only because `HttpIdempotency.claim`
compares the caller before it answers; a module that reads
`platform.idempotency_keys` itself skips that comparison. And an effect key
deleted anywhere but by the purge, offboarding or its own store reopens an
effect for a second run. So the source is scanned: an import of the table
objects, or a string literal that is SQL naming either table, outside the
frozen exemptions below, each with its reason.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
SCANNED = ("packages", "apps")
TABLES = ("idempotency_keys", "effect_keys")
_SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|JOIN|TRUNCATE)\b", re.IGNORECASE)
_PERSISTENCE = "packages/python/dw_platform/src/dw_platform/adapters/persistence"

# Frozen: a new entry is a decision, with its reason (R2.26). Migrations live
# under `db/`, which is not scanned, and a `tests` directory is exempt below.
EXEMPT: dict[str, str] = {
    f"{_PERSISTENCE}/tables.py": "declares the table objects",
    f"{_PERSISTENCE}/idempotency_store.py": "the HTTP key store, which compares the caller",
    f"{_PERSISTENCE}/effect_key_store.py": "the effect key store and its purger",
    f"{_PERSISTENCE}/offboarding.py": "deletes a leaving tenant's rows; never reads them",
}


def violations(root: Path, exempt: dict[str, str]) -> list[str]:
    """Each module outside ``exempt`` that imports or queries a key table."""
    found = []
    for top in SCANNED:
        for path in sorted((root / top).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in exempt or "/tests/" in f"/{relative}" or "/.venv/" in relative:
                continue
            reason = _offence(path.read_text(encoding="utf-8"))
            if reason:
                found.append(f"{relative}: {reason}")
    return found


def _offence(source: str) -> str | None:
    if not any(table in source for table in TABLES):
        return None
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in TABLES
            and isinstance(node.value, ast.Name)
            and node.value.id == "tables"
        ):
            return f"reads tables.{node.attr}"
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in TABLES:
                    return f"imports {alias.name}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if any(table in text for table in TABLES) and _SQL.search(text):
                return "names a key table in SQL"
    return None


def test_only_the_exempt_modules_touch_the_key_tables() -> None:
    assert violations(REPO, EXEMPT) == []


def test_every_exemption_says_why_and_the_list_is_the_frozen_one() -> None:
    assert all(reason.strip() for reason in EXEMPT.values())
    assert set(EXEMPT) == {
        f"{_PERSISTENCE}/{name}"
        for name in ("tables.py", "idempotency_store.py", "effect_key_store.py", "offboarding.py")
    }


@pytest.mark.parametrize(
    ("source", "offence"),
    [
        ("from x import tables\nrows = tables.idempotency_keys.select()\n", "reads"),
        ('q = "SELECT response_body FROM platform.idempotency_keys"\n', "SQL"),
        ('q = "DELETE FROM platform.effect_keys WHERE true"\n', "SQL"),
        ("from dw_platform.adapters.persistence.tables import effect_keys\n", "imports"),
    ],
)
def test_a_planted_reader_is_named(tmp_path: Path, source: str, offence: str) -> None:
    module = tmp_path / "packages" / "probe" / "reader.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")

    [named] = violations(tmp_path, {})
    assert named.startswith("packages/probe/reader.py") and offence in named


def test_a_store_key_or_a_test_is_not_a_reader(tmp_path: Path) -> None:
    """The purger's registry key is a name, not SQL; a test may seed rows."""
    key = tmp_path / "apps" / "worker" / "main.py"
    key.parent.mkdir(parents=True)
    key.write_text('EFFECT_KEYS = "platform.effect_keys"\n', encoding="utf-8")
    seeded = tmp_path / "packages" / "x" / "tests" / "test_seed.py"
    seeded.parent.mkdir(parents=True)
    seeded.write_text('q = "INSERT INTO platform.effect_keys VALUES (1)"\n', encoding="utf-8")

    assert violations(tmp_path, {}) == []
