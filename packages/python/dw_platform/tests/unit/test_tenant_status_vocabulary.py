"""No enum in dw_platform declares a tenant status the database refuses (org-and-principals R2.1).

`TenantStatus` once offered `suspended`, which `ck_tenants_status` never
allowed and nothing read: a value the code could hold and the row could not.
The allowed set is read from the migration that owns the CHECK, so the two
cannot drift apart silently.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from collections.abc import Callable
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[5]
_SRC = _REPO / "packages/python/dw_platform/src/dw_platform"
_MIGRATIONS = _REPO / "db/migrations/versions"
# Values only a tenant's status carries; `locked` and `active` are shared with
# other lifecycles (approval codes), so a name with "Tenant" catches the rest.
_TENANT_ONLY = {"offboarding", "offboarded"}


def _revision_chain() -> list[Path]:
    """Migration files in the order alembic applies them, walked through
    `down_revision` (a file's mtime says nothing on a fresh checkout)."""
    files: dict[str, tuple[Path, str | None]] = {}
    for path in _MIGRATIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.M)
        down = re.search(r"^down_revision\s*=\s*(?:[\"']([^\"']+)[\"']|None)", text, flags=re.M)
        if rev and down:
            files[rev.group(1)] = (path, down.group(1))
    children = {down: name for name, (_, down) in files.items()}
    chain: list[Path] = []
    step = children.get(None)
    while step is not None:
        chain.append(files[step][0])
        step = children.get(step)
    assert len(chain) == len(files), "migration history is not one linear chain"
    return chain


class _RecordingOp:
    """Stands in for `alembic.op`: keeps what `execute` is given, ignores the rest."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: object, *args: object, **kwargs: object) -> None:
        self.statements.append(str(sql))

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


def _upgrade_sql(path: Path) -> str:
    """The SQL a migration's `upgrade()` executes; its `downgrade()` is never read,
    so a downgrade that restores an older CHECK cannot win."""
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorder = _RecordingOp()
    module.op = recorder  # type: ignore[attr-defined]
    module.upgrade()
    return "\n".join(recorder.statements)


def allowed_tenant_statuses() -> set[str]:
    """The values of the newest `ck_tenants_status` an upgrade adds."""
    found: set[str] = set()
    for path in _revision_chain():
        if "ck_tenants_status" not in path.read_text(encoding="utf-8"):
            continue
        for match in re.finditer(
            r"ck_tenants_status\s+CHECK\s*\(\s*status\s+IN\s*\(([^)]*)\)\)", _upgrade_sql(path)
        ):
            found = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert found, "no migration adds ck_tenants_status"
    return found


def tenant_status_enums(root: Path) -> dict[str, set[str]]:
    """Every StrEnum under `root` that is a tenant status: named for one, or
    holding a value only a tenant's status has."""
    enums: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(getattr(b, "id", getattr(b, "attr", "")) == "StrEnum" for b in node.bases):
                continue
            values = {
                stmt.value.value
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            }
            if "Tenant" in node.name or values & _TENANT_ONLY:
                enums[f"{path.relative_to(root)}:{node.name}"] = values
    return enums


def test_no_enum_declares_a_tenant_status_the_database_refuses() -> None:
    allowed = allowed_tenant_statuses()
    wrong = {
        name: sorted(values - allowed)
        for name, values in tenant_status_enums(_SRC).items()
        if values - allowed
    }
    assert wrong == {}


def test_the_scan_names_an_enum_with_a_refused_status(tmp_path: Path) -> None:
    (tmp_path / "planted.py").write_text(
        "from enum import StrEnum\n\nclass TenantStatus(StrEnum):\n"
        "    ACTIVE = 'active'\n    SUSPENDED = 'suspended'\n",
        encoding="utf-8",
    )
    found = tenant_status_enums(tmp_path)
    assert found == {"planted.py:TenantStatus": {"active", "suspended"}}
    assert found["planted.py:TenantStatus"] - allowed_tenant_statuses() == {"suspended"}
