"""Only the registered lanes set `app.worker_drain` (foundations-hardening R2.6, FH34).

The drain is the setting under which a connection reads and writes every
tenant's rows of the tables whose policy names it (the checkpoints, among
others, for reading too). A module of the API that set it, by its own string or
by a constant borrowed from a lane, would serve one tenant another's rows. So
the source is scanned, outside the frozen exemptions below, each with its
reason:

* a string literal naming the setting, docstrings aside;
* an import of a drain constant from an exempt module;
* outside `apps/worker`, an import of a whole exempt module, or of a class or
  function of one whose body uses its drain constant, directly or through
  another such name of the same module: calling it sets the drain as surely as
  the string does.

What this cannot see: a name built at run time ("app." + "worker_drain"), SQL
outside Python, a service in another language. Those are review's.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
SCANNED = ("packages", "apps")
DRAIN = "app.worker_drain"
WORKER = "apps/worker/"

# Frozen: a new entry is a decision, with its reason (R2.6). A `tests` directory
# is exempt below; migrations live under `db/`, which is not scanned.
EXEMPT: dict[str, str] = {
    "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint_retention.py": (
        "the checkpoint retention lane, which selects across tenants what to prune"
    ),
    "packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/spend_guard.py": (
        "the spend-guard retention lane (`SqlSpendGuardRetention`) only"
    ),
    "packages/python/dw_knowledge/src/dw_knowledge/ingest_jobs.py": (
        "the ingest lane's claim (`IngestJobQueue`) only; the API's store does not drain"
    ),
    "packages/python/dw_knowledge/src/dw_knowledge/retention.py": (
        "the knowledge retention lane, which purges deleted documents of every tenant"
    ),
    "packages/python/dw_memory/src/dw_memory/retention.py": (
        "the memory retention lane, which closes expired facts of every tenant"
    ),
    "packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py": (
        "the offboarding lane, which exports and purges one leaving tenant"
    ),
    "packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py": (
        "the outbox relay, which publishes every tenant's events"
    ),
}


def module_name(relative: str) -> str:
    """`packages/python/dw_x/src/dw_x/a/b.py` -> `dw_x.a.b`."""
    inside = relative.split("/src/", 1)[1] if "/src/" in relative else relative
    return inside.removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def violations(root: Path, exempt: dict[str, str]) -> list[str]:
    """Each module outside ``exempt`` that sets, or reaches what sets, the drain."""
    draining = {
        module_name(path): _draining_names(ast.parse((root / path).read_text(encoding="utf-8")))
        for path in exempt
        if (root / path).exists()
    }
    found = []
    for top in SCANNED:
        for path in sorted((root / top).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in exempt or "/tests/" in f"/{relative}" or "/.venv/" in relative:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for reason in _offences(tree, draining, beyond_worker=not relative.startswith(WORKER)):
                found.append(f"{relative}: {reason}")
    return found


def _offences(
    tree: ast.Module, draining: dict[str, tuple[set[str], set[str]]], *, beyond_worker: bool
) -> list[str]:
    docstrings = _docstrings(tree)
    offences = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and DRAIN in node.value
            and id(node) not in docstrings
        ):
            offences.append(f"names {DRAIN}")
        elif isinstance(node, ast.Import) and beyond_worker:
            offences += [
                f"imports {alias.name}"
                for alias in node.names
                if any(alias.name == m or alias.name.startswith(f"{m}.") for m in draining)
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                whole = f"{node.module}.{alias.name}"
                if whole in draining and beyond_worker:
                    offences.append(f"imports {whole}")
                elif node.module in draining:
                    constants, callables = draining[node.module]
                    if alias.name in constants or (beyond_worker and alias.name in callables):
                        offences.append(f"imports {whole}")
    return offences


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


def _draining_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """(the module's drain constants, its classes and functions that use them)."""
    constants = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
        and any(
            isinstance(leaf, ast.Constant) and isinstance(leaf.value, str) and DRAIN in leaf.value
            for leaf in ast.walk(node.value)
        )
    }
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    callables: set[str] = set()
    while True:
        reached = constants | callables
        grown = {
            node.name
            for node in definitions
            if any(isinstance(leaf, ast.Name) and leaf.id in reached for leaf in ast.walk(node))
        }
        if grown <= callables:
            return constants, callables
        callables |= grown


def test_only_the_registered_lanes_set_the_drain() -> None:
    assert violations(REPO, EXEMPT) == []


def test_every_exemption_says_why_and_still_sets_the_drain() -> None:
    """A reason per entry, and no entry left behind by a lane that moved."""
    assert all(reason.strip() for reason in EXEMPT.values())
    for path in EXEMPT:
        constants, _ = _draining_names(ast.parse((REPO / path).read_text(encoding="utf-8")))
        assert constants, f"{path} no longer sets {DRAIN}; drop it from EXEMPT"


def test_the_apis_ingest_store_is_not_a_draining_name() -> None:
    """The API builds `IngestJobStore` to enqueue; only the worker's queue drains."""
    path = "packages/python/dw_knowledge/src/dw_knowledge/ingest_jobs.py"
    _, callables = _draining_names(ast.parse((REPO / path).read_text(encoding="utf-8")))
    assert "IngestJobQueue" in callables
    assert "IngestJobStore" not in callables


_INGEST = "packages/python/dw_knowledge/src/dw_knowledge/ingest_jobs.py"


def _planted(root: Path, where: str, source: str) -> None:
    """A copy of the real ingest module beside one planted module."""
    exempt = root / _INGEST
    exempt.parent.mkdir(parents=True, exist_ok=True)
    exempt.write_text((REPO / _INGEST).read_text(encoding="utf-8"), encoding="utf-8")
    module = root / where
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "from sqlalchemy import text\n"
        "SET = text(\"SELECT set_config('app.worker_drain', 'on', true)\")\n",
        "from dw_knowledge.ingest_jobs import _SET_WORKER_DRAIN\n",
        "from sqlalchemy import text\n"
        "SET = text(\"SELECT set_config(:k, 'on', true)\")\n"
        "PARAMS = {'k': 'app.worker_drain'}\n",
        "from dw_knowledge.ingest_jobs import IngestJobQueue\n",
        "import dw_knowledge.ingest_jobs\n",
        "from dw_knowledge import ingest_jobs\n",
    ],
    ids=["own string", "lane constant", "parameter", "draining class", "module", "module by name"],
)
def test_a_planted_api_module_is_named(tmp_path: Path, source: str) -> None:
    _planted(tmp_path, "apps/api/src/dw_api/routes/v1/probe.py", source)

    [named] = violations(tmp_path, {_INGEST: "the lane"})
    assert named.startswith("apps/api/src/dw_api/routes/v1/probe.py")


def test_the_worker_a_docstring_a_test_and_the_apis_store_are_not_offences(
    tmp_path: Path,
) -> None:
    _planted(
        tmp_path,
        "apps/worker/src/dw_worker/composition.py",
        "import dw_knowledge.ingest_jobs\nfrom dw_knowledge.ingest_jobs import IngestJobQueue\n",
    )
    _planted(
        tmp_path,
        "apps/api/src/dw_api/bootstrap/runtime.py",
        '"""Never sets app.worker_drain."""\n'
        "from dw_knowledge.ingest_jobs import EnqueueIngestCommand, IngestJobStore\n",
    )
    _planted(
        tmp_path,
        "apps/api/tests/unit/test_probe.py",
        "q = \"SELECT set_config('app.worker_drain', 'on', true)\"\n",
    )

    assert violations(tmp_path, {_INGEST: "the lane"}) == []


def test_the_worker_may_not_borrow_a_lanes_constant_either(tmp_path: Path) -> None:
    """The worker hosts the lanes; it does not get to set the drain itself."""
    _planted(
        tmp_path,
        "apps/worker/src/dw_worker/consumers/probe.py",
        "from dw_knowledge.ingest_jobs import _SET_WORKER_DRAIN\n",
    )

    [named] = violations(tmp_path, {_INGEST: "the lane"})
    assert named.startswith("apps/worker/src/dw_worker/consumers/probe.py")
