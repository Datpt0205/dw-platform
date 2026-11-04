"""Architecture, read from the syntax tree (connections-and-vault R3.6, R3.13;
CV9, CV26).

- R3.6: `httpx.AsyncClient(` and `httpx.Client(` only in the egress package and
  the operator-configured adapters listed below, over `packages/python/*/src`
  and `apps/*/src`. `scripts/` is not scanned: an operator runs those by hand.
- R3.13: the egress package declares no error class of its own, and
  `dw_connectors` never imports `dw_agent_runtime`, which depends on it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
EGRESS = REPO / "packages/python/dw_connectors/src/dw_connectors/egress"
CONNECTORS = REPO / "packages/python/dw_connectors/src"

# The adapters an operator configures, each reaching one fixed provider URL
# that `ensure_allowed_outbound_url` checked at startup; never a tenant's.
RAW_CLIENTS = frozenset(
    {
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py",
        "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_responses.py",
        "packages/python/dw_connectors/src/dw_connectors/adapters/zalo_bot.py",
        "packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py",
        "packages/python/dw_knowledge/src/dw_knowledge/adapters/cohere_rerank.py",
        "packages/python/dw_knowledge/src/dw_knowledge/adapters/openai_embedding.py",
        # The development mailbox the mail tests read; never deployed.
        "packages/python/dw_connectors/src/dw_connectors/adapters/mailpit_mailbox.py",
    }
)
_CLIENTS = frozenset({"AsyncClient", "Client"})


def _sources() -> Iterable[Path]:
    for root in (*REPO.glob("packages/python/*/src"), *REPO.glob("apps/*/src")):
        yield from root.rglob("*.py")


def raw_client_calls(source: str) -> list[int]:
    """The lines of every `httpx.AsyncClient(`/`httpx.Client(` call, the
    module's own aliases of either included (`from httpx import AsyncClient as C`)."""
    tree = ast.parse(source)
    aliases = {"httpx"}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name == "httpx"}
        elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
            names |= {a.asname or a.name for a in node.names if a.name in _CLIENTS}
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _CLIENTS
            and isinstance(func.value, ast.Name)
            and func.value.id in aliases
        ) or (isinstance(func, ast.Name) and func.id in names):
            lines.append(node.lineno)
    return lines


def test_no_module_but_egress_and_the_listed_adapters_builds_a_raw_client() -> None:
    """R3.6 (CV9)."""
    found = []
    for path in _sources():
        relative = path.relative_to(REPO).as_posix()
        if relative in RAW_CLIENTS or path.is_relative_to(EGRESS):
            continue
        found += [f"{relative}:{line}" for line in raw_client_calls(path.read_text("utf-8"))]
    assert found == []


def test_every_listed_adapter_still_exists() -> None:
    """A row for a file that is gone is a hole waiting for its name."""
    assert [p for p in RAW_CLIENTS if not (REPO / p).is_file()] == []


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nhttpx.AsyncClient()\n",
        "import httpx as h\nh.Client(timeout=1)\n",
        "from httpx import AsyncClient\nAsyncClient()\n",
        "from httpx import Client as C\nC()\n",
    ],
)
def test_the_scan_sees_each_spelling(source: str) -> None:
    """R3.6: a new module with any of these turns the scan red."""
    assert raw_client_calls(source) == [2]


def test_the_scan_ignores_what_is_not_a_client() -> None:
    source = "import httpx\nhttpx.URL('x')\nhttpx.AsyncHTTPTransport()\n"
    assert raw_client_calls(source) == []


def _error_classes(source: str) -> list[str]:
    suffixes = ("Error", "Exception")
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Name) and base.id.endswith(suffixes))
            or (isinstance(base, ast.Attribute) and base.attr.endswith(suffixes))
            for base in node.bases
        )
    ]


def test_egress_declares_no_error_class_of_its_own() -> None:
    """R3.13 (CV26): the kernel's three, nothing else."""
    declared = {path.name: _error_classes(path.read_text("utf-8")) for path in EGRESS.rglob("*.py")}
    assert {name: found for name, found in declared.items() if found} == {}


def test_the_class_scan_sees_one() -> None:
    assert _error_classes("class Late(DWError):\n    pass\n") == ["Late"]


def _imports(path: Path) -> Iterable[str]:
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_connectors_never_import_the_agent_runtime() -> None:
    """R3.13: the runtime depends on this package, so the reverse is a cycle."""
    importing = sorted(
        path.relative_to(REPO).as_posix()
        for path in CONNECTORS.rglob("*.py")
        if any(m.split(".")[0] == "dw_agent_runtime" for m in _imports(path))
    )
    assert importing == []
