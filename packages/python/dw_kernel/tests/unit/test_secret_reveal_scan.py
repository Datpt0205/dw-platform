"""Only the listed modules call `Secret.reveal()` (connections-and-vault R1.2, CV4).

A `Secret` prints as a mask; `reveal()` is the one way to its value, so every
module that calls it is a place the value exists in the clear. The source of
`packages/` and `apps/` is scanned, tests aside, for any use of an attribute
named `reveal` (a call, or a reference handed on to be called later) and for the
string `"reveal"` outside docstrings (`getattr(secret, "reveal")`), outside the
frozen allowlist below. Each entry is a decision with its reason: the credential
broker now; the egress client (ticket 03) and the connection's first outbound
call (ticket 05) add theirs.

What this cannot see: a name built at run time, or code outside Python. Those
are review's.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
SCANNED = ("packages", "apps")
NAME = "reveal"

# Frozen: a new entry is a decision, with its reason.
ALLOWED: dict[str, str] = {
    "packages/python/dw_platform/src/dw_platform/application/secrets.py": (
        "the credential broker, which seals a value under the tenant's key"
    ),
}


def _docstrings(tree: ast.Module) -> set[int]:
    owners = [tree] + [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    return {
        id(owner.body[0].value)
        for owner in owners
        if owner.body
        and isinstance(owner.body[0], ast.Expr)
        and isinstance(owner.body[0].value, ast.Constant)
        and isinstance(owner.body[0].value.value, str)
    }


def _offences(tree: ast.Module) -> list[str]:
    docstrings = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == NAME:
            found.append(f"line {node.lineno}: uses .{NAME}")
        elif isinstance(node, ast.Constant) and node.value == NAME and id(node) not in docstrings:
            found.append(f"line {node.lineno}: names {NAME!r}")
    return found


def violations(root: Path, allowed: dict[str, str]) -> list[str]:
    found = []
    for top in SCANNED:
        for path in sorted((root / top).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if (
                relative in allowed
                or "/tests/" in f"/{relative}"
                or "/.venv/" in relative
                or "/node_modules/" in relative
            ):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found += [f"{relative}: {offence}" for offence in _offences(tree)]
    return found


def test_only_the_allowed_modules_reveal_a_secret() -> None:
    assert violations(REPO, ALLOWED) == []


def test_every_allowed_module_still_reveals_and_says_why() -> None:
    """No entry left behind by a module that stopped needing it."""
    for path, reason in ALLOWED.items():
        assert reason.strip()
        assert _offences(ast.parse((REPO / path).read_text(encoding="utf-8"))), (
            f"{path} no longer reveals a secret; drop it from ALLOWED"
        )


@pytest.mark.parametrize(
    "source",
    [
        "def send(secret):\n    return secret.reveal()\n",
        "def later(secret):\n    return secret.reveal\n",
        "def sneak(secret):\n    return getattr(secret, 'reveal')()\n",
    ],
    ids=["call", "reference", "getattr"],
)
def test_a_planted_module_is_named(tmp_path: Path, source: str) -> None:
    planted = tmp_path / "apps/api/src/dw_api/routes/v1/probe.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(source, encoding="utf-8")

    [named] = violations(tmp_path, ALLOWED)
    assert named.startswith("apps/api/src/dw_api/routes/v1/probe.py")


def test_a_docstring_a_test_and_an_allowed_module_are_not_offences(tmp_path: Path) -> None:
    sources = {
        "packages/python/dw_x/src/dw_x/doc.py": '"""Call `reveal` only from the broker."""\n',
        "packages/python/dw_x/tests/unit/test_x.py": "def t(s):\n    return s.reveal()\n",
        "packages/python/dw_x/src/dw_x/broker.py": "def b(s):\n    return s.reveal()\n",
    }
    for relative, source in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    assert violations(tmp_path, {"packages/python/dw_x/src/dw_x/broker.py": "the probe"}) == []
