"""R3.1 (studio-skeleton R5.6; ADR-0114 decision 2): only
`dw_studio.core.adapters.cel` imports the CEL binding, and the kernel never
does.

`lint-imports` on this checkout passes because nothing breaks the contracts,
which says nothing about whether they can break. Each case here runs the two
contracts, read from the root `pyproject.toml` as they stand, over a throwaway
tree of empty root packages with exactly one probe module planted, and
requires the planted import to be reported by name.
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
CEL_CONTRACT = "CEL binding only in dw_studio.core.adapters.cel"
KERNEL_CONTRACT = "Kernel is pure (stdlib only)"


def _config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        config: dict[str, Any] = tomllib.load(handle)["tool"]["importlinter"]
    return config


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


def _write_config(path: Path, config: dict[str, Any]) -> None:
    wanted = (CEL_CONTRACT, KERNEL_CONTRACT)
    contracts = [c for c in config["contracts"] if c["name"] in wanted]
    assert {c["name"] for c in contracts} == {CEL_CONTRACT, KERNEL_CONTRACT}
    lines = ["[tool.importlinter]"]
    lines += [f"{key} = {_toml_value(config[key])}" for key in ("root_packages",)]
    lines.append("include_external_packages = true")
    for contract in contracts:
        lines.append("[[tool.importlinter.contracts]]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in contract.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tree(base: Path, root_packages: list[str], modules: dict[str, str]) -> None:
    for package in root_packages:
        (base / package).mkdir(parents=True)
        (base / package / "__init__.py").write_text("", encoding="utf-8")
    for dotted, body in modules.items():
        parts = dotted.split(".")
        for depth in range(1, len(parts)):
            folder = base.joinpath(*parts[:depth])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "__init__.py").touch()
        (base.joinpath(*parts[:-1]) / f"{parts[-1]}.py").write_text(body, encoding="utf-8")


ALLOWED = {
    "dw_studio.core.adapters.cel.engine": "import cel_expr_python\n",
    "dw_studio.core.adapters.cel.library": "from cel_expr_python.ext import ext_strings\n",
    # A composition root builds the adapter: an indirect import, allowed.
    "dw_api.bootstrap.expressions": "from dw_studio.core.adapters.cel import engine\n",
}


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


def test_the_adapter_and_a_composition_root_pass(tmp_path: Path) -> None:
    result = _lint(tmp_path, {})
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{CEL_CONTRACT} KEPT" in result.stdout


@pytest.mark.parametrize(
    "probe",
    [
        "dw_studio.core.application.probe",
        "dw_studio.records.probe",
        "dw_platform.probe",
        "dw_api.routes.probe",
    ],
)
def test_the_binding_imported_outside_the_adapter_breaks_the_contract(
    tmp_path: Path, probe: str
) -> None:
    result = _lint(tmp_path, {probe: "import cel_expr_python.cel\n"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{CEL_CONTRACT} BROKEN" in result.stdout
    assert f"{probe} -> cel_expr_python" in result.stdout


def test_the_binding_imported_by_the_kernel_breaks_both_contracts(tmp_path: Path) -> None:
    result = _lint(tmp_path, {"dw_kernel.probe": "import cel_expr_python\n"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{KERNEL_CONTRACT} BROKEN" in result.stdout
    assert f"{CEL_CONTRACT} BROKEN" in result.stdout
    assert "dw_kernel.probe -> cel_expr_python" in result.stdout
