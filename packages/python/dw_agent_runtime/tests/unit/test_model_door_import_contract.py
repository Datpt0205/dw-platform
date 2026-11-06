"""usage-and-limits R6.1 (UL4; ADR-0121 decision 7): only a composition root
or a builder imports a concrete model door.

`lint-imports` on this checkout passes because nothing breaks the contract,
which says nothing about whether it can break. Each case runs the contract,
read from the root `pyproject.toml` as it stands, over a throwaway tree of
empty root packages holding the builders and composition roots it allows,
with one probe module planted, and requires the planted import to be reported
by name (the shape of `dw_studio`'s `test_cel_import_contracts.py`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[5]
CONTRACT = "Only a composition root imports a concrete model door"

ROUTING = "dw_agent_runtime.model.routing"
OPENAI_EMBEDDING = "dw_knowledge.adapters.openai_embedding"
HASH_EMBEDDING = "dw_knowledge.adapters.hash_embedding"
RERANK = "dw_knowledge.adapters.cohere_rerank"

# The doors themselves, and every import the contract allows.
ALLOWED = {
    ROUTING: "",
    OPENAI_EMBEDDING: "",
    HASH_EMBEDDING: "",
    RERANK: "",
    "dw_agent_runtime.adapters.model_stack": f"import {ROUTING}\n",
    "dw_knowledge.adapters.embedding_factory": (
        f"import {OPENAI_EMBEDDING}\nimport {HASH_EMBEDDING}\n"
    ),
    "dw_api.bootstrap.knowledge": f"import {RERANK}\n",
}


def _config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        config: dict[str, Any] = tomllib.load(handle)["tool"]["importlinter"]
    return config


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


def _write_config(path: Path, config: dict[str, Any]) -> None:
    (contract,) = [c for c in config["contracts"] if c["name"] == CONTRACT]
    lines = ["[tool.importlinter]"]
    lines.append(f"root_packages = {_toml_value(config['root_packages'])}")
    lines.append("include_external_packages = true")
    lines.append("[[tool.importlinter.contracts]]")
    lines += [f"{key} = {_toml_value(value)}" for key, value in contract.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tree(base: Path, root_packages: list[str], modules: dict[str, str]) -> None:
    for package in root_packages:
        # A dotted root (`tests.e2e.marketing_pilot`) is nested folders under
        # namespace packages, as it is in the checkout.
        folder = base.joinpath(*package.split("."))
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text("", encoding="utf-8")
    for dotted, body in modules.items():
        parts = dotted.split(".")
        for depth in range(1, len(parts)):
            folder = base.joinpath(*parts[:depth])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "__init__.py").touch()
        (base.joinpath(*parts[:-1]) / f"{parts[-1]}.py").write_text(body, encoding="utf-8")


def _lint(tmp_path: Path, probes: dict[str, str]) -> subprocess.CompletedProcess[str]:
    config = _config()
    _tree(tmp_path / "src", list(config["root_packages"]), {**ALLOWED, **probes})
    _write_config(tmp_path / "contracts.toml", config)
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "src")}
    command = (
        "import sys; from importlinter.cli import lint_imports_command; lint_imports_command()"
    )
    return subprocess.run(
        [sys.executable, "-c", command, "--config", "contracts.toml", "--no-cache"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_the_builders_and_the_composition_root_pass(tmp_path: Path) -> None:
    result = _lint(tmp_path, {})
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{CONTRACT} KEPT" in result.stdout


@pytest.mark.parametrize(
    ("probe", "door"),
    [
        ("dw_studio.workflows.probe", ROUTING),
        ("dw_api.routes.probe", ROUTING),
        ("dw_knowledge.gateway", OPENAI_EMBEDDING),
        ("dw_memory.adapters.probe", HASH_EMBEDDING),
        ("dw_worker.consumers.probe", RERANK),
        ("dw_agent_runtime.wflite.probe", ROUTING),
    ],
)
def test_a_concrete_door_imported_elsewhere_breaks_the_contract(
    tmp_path: Path, probe: str, door: str
) -> None:
    result = _lint(tmp_path, {probe: f"import {door}\n"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{CONTRACT} BROKEN" in result.stdout
    assert f"{probe} -> {door}" in result.stdout
