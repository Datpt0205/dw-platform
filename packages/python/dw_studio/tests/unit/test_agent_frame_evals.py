"""Unit: the agent frame's eval dataset and its graders (agent-builder ticket 02
step 6; R2.1, R1.12; AB1, AB16).

The dataset runs green through the eval composition root's grader table, as
`scripts/run_evals.py --smoke` runs it, and each grader turns red when the
assembler loses the guard it grades.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from dw_agent_runtime.model import prompts
from dw_evals.dataset import CaseCategory
from dw_evals.runner import load_dataset, run_dataset

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
DATASET = REPO / "evals" / "datasets" / "studio_agent_frame@1.0.0.json"


def grader_table() -> dict[str, Any]:
    """The eval composition root's own table, loaded from the script."""
    spec = importlib.util.spec_from_file_location("run_evals", REPO / "scripts" / "run_evals.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    table: dict[str, Any] = module.grader_table()
    return table


def failed(report: Any) -> list[str]:
    return sorted(result.case_id for result in report.results if not result.passed)


def test_the_dataset_passes_with_full_security_coverage() -> None:
    dataset = load_dataset(DATASET)
    report = run_dataset(dataset, REPO, grader_table())
    assert report.ok, [(r.case_id, r.details) for r in report.results if not r.passed]
    assert {c.category for c in dataset.cases} >= {
        CaseCategory.PROMPT_INJECTION,
        CaseCategory.CROSS_TENANT_ATTACK,
        CaseCategory.MISSING_EVIDENCE,
    }
    assert all(c.grader.startswith("studio.agent_frame.") for c in dataset.cases)


def test_an_assembler_that_stops_escaping_fails_the_injection_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prompts, "escape_delimiters", lambda text: text)
    report = run_dataset(load_dataset(DATASET), REPO, grader_table())
    assert failed(report) == [
        "af-sec-injection-closing-variants",
        "af-sec-injection-in-instructions",
    ]


def test_an_assembler_reading_an_override_fails_the_override_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = prompts.PromptRegistry.render

    def any_tenant(self: Any, *args: Any, **kwargs: Any) -> Any:
        tenants = list(self._prompts._tenants)
        return real(self, *args, **{**kwargs, "tenant_id": tenants[0] if tenants else None})

    monkeypatch.setattr(prompts.PromptRegistry, "render", any_tenant)
    report = run_dataset(load_dataset(DATASET), REPO, grader_table())
    assert failed(report) == ["af-sec-cross-tenant-override"]
