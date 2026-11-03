"""``scripts/eval_wf_ai.py``: one case's failure is a line, the code's failure stops the run.

Never calls a model: the gateway is a fake that answers from the mock fixture,
in the wire form a model writes, or raises what a case sets (wf-ai R1.5, wf-ai/05).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from dw_agent_runtime.ports import ModelOutputInvalidError, ModelRequest
from dw_agent_runtime.testing.wf_ai import fixture_answer
from dw_api.bootstrap.paths import MOCK_MODEL_FIXTURES
from dw_kernel.errors import ConfigError, InfrastructureError

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_script() -> ModuleType:  # scripts/ is not on the path; load by file
    path = REPO_ROOT / "scripts" / "eval_wf_ai.py"
    spec = importlib.util.spec_from_file_location("eval_wf_ai_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


class ScriptedGateway:
    """Raises the error set for an instruction, else answers the fixture."""

    def __init__(self, errors: dict[str, Exception]) -> None:
        self.errors = errors

    async def generate_structured(
        self, request: ModelRequest, output_type: type[Any], *, run_context: Any
    ) -> Any:
        error = self.errors.get(str(request.variables["instruction"]))
        if error is not None:
            raise error
        return output_type.model_validate(fixture_answer(MOCK_MODEL_FIXTURES))


def dataset(tmp_path: Path, *ids: str) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"id": i, "instruction": i, "history": [], "expect": "wf_ai.frozen"})
            for i in ids
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "error", [ModelOutputInvalidError("bad"), InfrastructureError("provider down")]
)
async def test_a_case_whose_answer_fails_is_a_fail_line_and_the_run_goes_on(
    tmp_path: Path, error: Exception
) -> None:
    lines: list[str] = []
    code = await script.run(
        ScriptedGateway({"first": error}), dataset(tmp_path, "first", "second"), lines.append
    )
    assert code == 1
    assert lines[0] == f"FAIL first: {type(error).__name__}"
    assert lines[1].startswith("ok   second: steps only, gates kept (kind=proposal,")
    assert "publishable=True" in lines[1] and "codes=-" in lines[1]


async def test_a_schema_the_adapter_refuses_stops_the_run(tmp_path: Path) -> None:
    lines: list[str] = []
    with pytest.raises(ConfigError):
        await script.run(
            ScriptedGateway({"first": ConfigError("strict cannot express a map")}),
            dataset(tmp_path, "first", "second"),
            lines.append,
        )
    assert lines == []
