"""The one door of a Studio run, held by the source (workflow-engine ticket 02:
R3.5, R3.18, R3.19; WE1, WE50).

Three scans of `packages/*/src` and `apps/*/src` (tests are left out: a test
plants rows), each a function over plain text so the planted cases below show
it can fail:

- `studio_run_inserters`: a module that inserts into `platform.worker_runs`
  (`insert(worker_runs)`, `pg_insert(worker_runs)` or SQL text) and names
  `artifact_kind` is inserting a Studio run; only `run_intake.py` may;
- `door_bypasses`: only the door, and the transaction it delegates through,
  call `insert_queued_run`;
- `lane_forgeries`: only `RunLaneRegistry.requester` builds a
  `LaneRequester`, so a lane is one the composition root registered.

What this cannot see: SQL built at run time, a service in another language.
Those are review's; the CHECKs of revision 703be798341f still refuse a Studio
row without its manifest, principal, trigger kind and request key.
"""

from __future__ import annotations

import ast
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest

from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.application.access_context import AccessContext
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import (
    W1_TRIGGER_KINDS,
    LaneRequester,
    RunIntakeTx,
    RunLaneRegistry,
    RunRequestService,
)
from dw_studio.testing.bindings import unasked_pins
from dw_studio.testing.run_manifests import shipped_models
from dw_studio.workflows.testing.fakes import RecordingBoundaries

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
INTAKE = "packages/python/dw_studio/src/dw_studio/core/adapters/run_intake.py"
DOOR = "packages/python/dw_studio/src/dw_studio/core/application/run_request.py"
# The door's transaction delegates the write to `run_intake`.
TRANSACTION = "packages/python/dw_studio/src/dw_studio/core/adapters/artifact_store.py"

_SQL_INSERT = re.compile(r"insert\s+into\s+platform\.worker_runs\b", re.I)


def sources(root: Path = REPO) -> dict[str, str]:
    found: dict[str, str] = {}
    for top in ("packages", "apps"):
        for path in sorted((root / top).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if "/src/" not in relative or "/tests/" in relative or "/.venv/" in relative:
                continue
            found[relative] = path.read_text(encoding="utf-8")
    return found


def _calls(tree: ast.AST) -> Iterator[tuple[str, ast.Call]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            yield name, node


def _named(node: ast.AST, name: str) -> bool:
    return (isinstance(node, ast.Name) and node.id == name) or (
        isinstance(node, ast.Attribute) and node.attr == name
    )


def _inserts_runs(tree: ast.AST) -> bool:
    for name, call in _calls(tree):
        if name in {"insert", "pg_insert"} and call.args and _named(call.args[0], "worker_runs"):
            return True
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _SQL_INSERT.search(node.value)
        for node in ast.walk(tree)
    )


def _names_artifact_kind(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "artifact_kind":
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "artifact_kind" in node.value
        ):
            return True
        if _named(node, "artifact_kind"):
            return True
    return False


def studio_run_inserters(found: Mapping[str, str]) -> list[str]:
    """Each module but `run_intake.py` that inserts a Studio run."""
    return [
        path
        for path, text in sorted(found.items())
        if path != INTAKE and _inserts_runs(tree := ast.parse(text)) and _names_artifact_kind(tree)
    ]


def door_bypasses(found: Mapping[str, str]) -> list[str]:
    """Each module but the door and its transaction that writes the run row."""
    return [
        path
        for path, text in sorted(found.items())
        if path not in {DOOR, TRANSACTION, INTAKE}
        and any(name == "insert_queued_run" for name, _ in _calls(ast.parse(text)))
    ]


def lane_forgeries(found: Mapping[str, str]) -> list[str]:
    """Each module but the registry's that builds a `LaneRequester`."""
    return [
        path
        for path, text in sorted(found.items())
        if path != DOOR and any(name == "LaneRequester" for name, _ in _calls(ast.parse(text)))
    ]


# ---- the repository -----------------------------------------------------------


def test_r3_5_only_the_door_inserts_a_studio_run() -> None:
    found = sources()
    assert INTAKE in found and DOOR in found, "the scan does not see the door"
    assert studio_run_inserters(found) == []
    assert door_bypasses(found) == []
    assert lane_forgeries(found) == []


# ---- the checks can fail: planted modules --------------------------------------

_PLANTED = "packages/python/dw_x/src/dw_x/sneaky.py"


@pytest.mark.parametrize(
    "text",
    [
        "from t import worker_runs\n"
        "async def go(s):\n"
        "    row = {'status': 'queued', 'artifact_kind': 'workflow'}\n"
        "    await s.execute(pg_insert(worker_runs).values(**row))\n",
        "from t import tables\n"
        "async def go(s):\n"
        "    await s.execute(sa.insert(tables.worker_runs).values(artifact_kind=k))\n",
        'Q = "INSERT INTO platform.worker_runs (id, status, artifact_kind)"\n',
    ],
)
def test_r3_5_a_planted_studio_insert_is_named(text: str) -> None:
    assert studio_run_inserters({_PLANTED: text}) == [_PLANTED]


def test_r3_5_a_code_runs_insert_is_not_a_studio_run() -> None:
    text = (
        "async def go(s):\n"
        "    await s.execute(sa.insert(worker_runs).values(status='running', run_mode='live'))\n"
    )
    assert studio_run_inserters({_PLANTED: text}) == []


def test_r3_5_a_planted_caller_of_the_row_write_is_named() -> None:
    text = "async def go(tx, run):\n    await tx.insert_queued_run(run)\n"
    assert door_bypasses({_PLANTED: text}) == [_PLANTED]


def test_r3_18_a_planted_lane_requester_is_named() -> None:
    text = "def forge(t):\n    return LaneRequester('studio_gate', t)\n"
    assert lane_forgeries({_PLANTED: text}) == [_PLANTED]


# ---- the registry and the door's tables -------------------------------------------

LANES = {"studio_inbound": ("datahub",), "studio_gate": ("eval",)}


def test_r3_19_the_registry_issues_only_what_it_lists() -> None:
    lanes = RunLaneRegistry(LANES)
    tenant = uuid.uuid4()
    assert lanes.requester("studio_gate", tenant) == LaneRequester("studio_gate", tenant)
    assert lanes.may_request(lanes.requester("studio_gate", tenant), "eval")
    assert not lanes.may_request(lanes.requester("studio_gate", tenant), "datahub")
    assert not lanes.may_request(LaneRequester("studio_rogue", tenant), "eval")
    with pytest.raises(KeyError):
        lanes.requester("studio_rogue", tenant)


@pytest.mark.parametrize(
    "bad",
    [
        {"studio_gate": ("manual",)},  # a person's kind
        {"studio_gate": ("schedule",)},  # outside W1
        {"studio_gate": ()},
        {"Bad-Lane": ("eval",)},  # not a worker registry name
    ],
)
def test_r3_19_a_registry_refuses_what_no_lane_may_ask(bad: Mapping[str, tuple[str, ...]]) -> None:
    with pytest.raises(ValueError):
        RunLaneRegistry(bad)


def test_the_w1_set_is_the_checks() -> None:
    """The CHECK's own set is compared with this one on the catalog
    (`test_worker_run_columns.py`); here, the five kinds by name."""
    assert {"chat", "manual", "test", "eval", "datahub"} == W1_TRIGGER_KINDS


def test_the_door_keeps_its_own_frozen_run_key_table() -> None:
    keys = {("fixture", "test"): "fixture.artifacts.run"}
    registry = ArtifactKindRegistry(())
    door = RunRequestService(
        store=_NoStore(),
        registry=registry,
        manifests=RunManifestBuilder(registry, "sha256:" + "0" * 64, shipped_models()),
        run_keys=keys,
        lanes=RunLaneRegistry(LANES),
        clock=SystemClock(),
        ids=Uuid7Generator(),
        bindings=unasked_pins(),
        boundaries=RecordingBoundaries(),
        boundary_derivers={},
        pinnable={},
    )
    keys[("fixture", "manual")] = "fixture.artifacts.run"
    assert ("fixture", "manual") not in door.run_keys
    with pytest.raises(TypeError):
        door.run_keys[("x", "y")] = "z"  # type: ignore[index]


class _NoStore:
    def for_person(self, context: AccessContext) -> AbstractAsyncContextManager[RunIntakeTx]:
        raise NotImplementedError("not exercised by the table test")

    def for_lane(self, lane: LaneRequester) -> AbstractAsyncContextManager[RunIntakeTx]:
        raise NotImplementedError("not exercised by the table test")
