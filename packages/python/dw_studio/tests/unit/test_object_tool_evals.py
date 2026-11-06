"""Unit: the object tools' eval dataset and its graders (tools-and-skills
ticket 03 step 6; R6.8).

The dataset runs green through the eval composition root's grader table, as
`scripts/run_evals.py --smoke` runs it, with full security coverage; each
grader turns red when what it grades loses its guard.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.model import prompts
from dw_evals.dataset import CaseCategory
from dw_evals.runner import load_dataset, run_dataset
from dw_studio.records.application.object_tools import ObjectToolView
from dw_studio.testing import object_tool_evals

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
DATASET = REPO / "evals" / "datasets" / "studio_object_tools@1.0.0.json"


def grader_table() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("run_evals", REPO / "scripts" / "run_evals.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    table: dict[str, Any] = module.grader_table()
    return table


def failed(report: Any) -> list[str]:
    return sorted(result.case_id for result in report.results if not result.passed)


def report() -> Any:
    return run_dataset(load_dataset(DATASET), REPO, grader_table())


def test_the_dataset_passes_with_full_security_coverage() -> None:
    dataset = load_dataset(DATASET)
    result = report()
    assert result.ok, [(r.case_id, r.details) for r in result.results if not r.passed]
    assert {c.category for c in dataset.cases} >= {
        CaseCategory.PROMPT_INJECTION,
        CaseCategory.CROSS_TENANT_ATTACK,
        CaseCategory.MISSING_EVIDENCE,
    }
    assert all(c.grader.startswith("studio.object_tools.") for c in dataset.cases)


def test_a_description_that_stops_escaping_fails_the_description_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One escape for both blocks (ADR-0010): the closing tag in an output
    goes red with the descriptions."""
    monkeypatch.setattr(prompts, "escape_untrusted", lambda value: value)
    assert failed(report()) == [
        "ot-sec-closing-tag-in-output",
        "ot-sec-injection-in-field-description",
        "ot-sec-injection-in-object-description",
    ]


def test_an_output_left_unwrapped_fails_the_output_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """The grader is handed an output whose injected text sits outside its block."""
    real = prompts.contain_tool_output

    def leaky(output: Any, definition: Any, execution_id: Any, **kwargs: Any) -> Any:
        contained = real(output, definition, execution_id, **kwargs)
        return contained._replace(content=f"{contained.content}\n{output}")

    monkeypatch.setattr(prompts, "contain_tool_output", leaky)
    assert failed(report()) == [
        "ot-sec-closing-tag-in-output",
        "ot-sec-injection-in-record-value",
    ]


def test_a_door_that_answers_another_companys_record_fails_the_cross_tenant_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def leaks(self: Any, run: Any, api_name: str, record_id: uuid.UUID, fields: Any) -> Any:
        return {"id": str(record_id), "name": "Nguyễn Thị Bình"}

    monkeypatch.setattr(object_tool_evals._OneCompany, "get", leaks)
    assert failed(report()) == ["ot-sec-cross-tenant-record"]


def test_a_view_that_keeps_a_hidden_field_fails_the_boundary_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = ObjectToolView.view
    monkeypatch.setattr(
        ObjectToolView,
        "view",
        lambda self, readable: real(self, self.visible),
    )
    assert failed(report()) == ["ot-boundary-hidden-field"]
