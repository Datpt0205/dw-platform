"""`make check-model`'s comparison of declared and probed capability flags
(model-connections ticket 02: R2.5).

The probe itself calls the gateway with the key in `.env`, so it does not run
in CI; what it concludes from a probe is this pure function, tested here on
probes written by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from dw_agent_runtime.model.profiles import ModelCapabilities

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_model_gateway", REPO_ROOT / "scripts" / "check_model_gateway.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_model_gateway"] = module
    spec.loader.exec_module(module)
    return module


def test_a_declaration_the_probe_agrees_with_reports_nothing() -> None:
    compare = _script().compare_capabilities
    declared = ModelCapabilities(strict_tools=True, numeric_bounds=False)
    assert compare(declared, {"strict_tools": True, "numeric_bounds": False}) == []


def test_each_flag_the_probe_contradicts_is_one_line_with_both_values() -> None:
    compare = _script().compare_capabilities
    declared = ModelCapabilities(strict_tools=True)
    lines = compare(declared, {"strict_tools": False, "numeric_bounds": True})
    assert lines == [
        "numeric_bounds: declared False, measured True",
        "strict_tools: declared True, measured False",
    ]


def test_an_undeclared_flag_reads_as_unsupported() -> None:
    compare = _script().compare_capabilities
    assert compare(ModelCapabilities(), {"strict_tools": False}) == []
    assert compare(ModelCapabilities(), {"strict_tools": True}) == [
        "strict_tools: declared False, measured True"
    ]


def test_the_probe_names_what_it_does_not_probe() -> None:
    script = _script()
    assert set(script.PROBED_FLAGS) == {"strict_tools", "numeric_bounds"}
    assert script.NOT_PROBED == ("max_strict_tools",)
    assert set(script.PROBED_FLAGS) <= set(ModelCapabilities.model_fields)
