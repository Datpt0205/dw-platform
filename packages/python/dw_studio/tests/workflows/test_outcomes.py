"""A workflow's `outcomes[]`: checked at submit, reached at the end
(workflow-engine/04: R1.9, R5.24; H-14; ADR-0112 Amendments 2026-11-04).

The core's `check_outcomes` and `reached_outcomes` over the real
`CelCppEngine`, through Studio's validator where the check is a submit's.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.outcomes import reached_outcomes
from dw_agent_runtime.wflite.validate import PACK_RULES, validate
from dw_studio.core.adapters.cel import CelCppEngine
from dw_studio.testing.workflows import NoTools, studio_document, studio_step
from dw_studio.workflows.application.rules import WorkflowValidator

pytestmark = pytest.mark.unit

REGISTRY = fixture_node_registry()


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[CelCppEngine]:
    adapter = CelCppEngine()
    yield adapter
    await adapter.aclose()


def doc(*outcomes: dict[str, Any], variables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`tim` on every path, `them` only on the `yes` lane of `chon`."""
    document = studio_document(
        studio_step("tim"),
        studio_step(
            "chon", "fixture.choice@1", on="x", yes=[studio_step("them")], no=[studio_step("bo")]
        ),
    )
    document["outcomes"] = list(outcomes)
    if variables is not None:
        document["variables"] = variables
    return document


def outcome(name: str, when: str) -> dict[str, Any]:
    return {"name": name, "when": when}


def problems(engine: CelCppEngine, document: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.pointer, p.code) for p in WorkflowValidator(REGISTRY, NoTools(), engine)(document)]


# ---- R1.9: the model and the check at submit ----------------------------------------------


def test_r1_9_two_outcomes_of_one_name_are_a_model_error_at_the_second(
    engine: CelCppEngine,
) -> None:
    found = problems(engine, doc(outcome("lead_new", "true"), outcome("lead_new", "false")))
    assert found == [("/outcomes/1/name", "wf.schema_invalid")]


def test_r1_9_a_condition_that_is_not_a_boolean_is_a_type_mismatch(engine: CelCppEngine) -> None:
    found = problems(engine, doc(outcome("lead_new", "'yes'")))
    assert found == [("/outcomes/0/when", "wf.type_mismatch")]


def test_r1_9_two_named_boolean_outcomes_check(engine: CelCppEngine) -> None:
    document = doc(
        outcome("lead_new", "has(steps.tim) && steps.tim.done == true"),
        outcome("lead_duplicate", "!has(steps.tim)"),
    )
    assert problems(engine, document) == []


@pytest.mark.parametrize("name", ["Lead", "1lead", "a" * 41, ""])
def test_r1_9_an_outcome_is_named_as_a_step_id_is(engine: CelCppEngine, name: str) -> None:
    found = problems(engine, doc(outcome(name, "true")))
    assert [code for _, code in found] == ["wf.schema_invalid"]


def test_a_pack_refuses_outcomes() -> None:
    document = {**doc(outcome("x", "true")), "key": "pack_x", "version": "1.0.0"}
    found = validate(
        document, registry=REGISTRY, rules=PACK_RULES, tools=NoTools(), work_schemas={}
    )
    assert ("outcomes", "wf.schema_invalid") in {(p.path, p.code) for p in found}


# ---- R5.24, R2.5: what a condition may name -------------------------------------------------


@pytest.mark.parametrize("when", ["steps.them.done == true", "has(steps.them)", "!has(steps.bo)"])
def test_r5_24_a_step_of_a_branch_lane_does_not_dominate_the_end_even_inside_has(
    engine: CelCppEngine, when: str
) -> None:
    found = problems(engine, doc(outcome("lead_new", when)))
    assert found == [("/outcomes/0/when", "wf.ref_not_dominating")]


def test_r5_24_a_branch_value_reaches_a_condition_through_a_variable(engine: CelCppEngine) -> None:
    document = doc(
        outcome("lead_new", "params.is_new"),
        variables=[{"name": "is_new", "type": "boolean"}],
    )
    assert problems(engine, document) == []


def test_a_name_no_step_has_is_an_unknown_reference(engine: CelCppEngine) -> None:
    assert problems(engine, doc(outcome("x", "has(steps.khong_co)"))) == [
        ("/outcomes/0/when", "wf.ref_unknown")
    ]
    assert problems(engine, doc(outcome("x", "nothing == 1"))) == [
        ("/outcomes/0/when", "wf.ref_unknown")
    ]


def test_a_condition_that_does_not_parse_says_so(engine: CelCppEngine) -> None:
    assert problems(engine, doc(outcome("x", "1 +"))) == [
        ("/outcomes/0/when", "wf.expression_invalid")
    ]


# ---- R5.24: reached at the end ---------------------------------------------------------------


async def reached(
    engine: CelCppEngine, document: dict[str, Any], state: dict[str, Any]
) -> list[str]:
    parsed = WorkflowDocument.model_validate(document)
    return await reached_outcomes(parsed, REGISTRY, engine, state)


async def test_r5_24_the_outcomes_whose_condition_holds_in_the_documents_order(
    engine: CelCppEngine,
) -> None:
    document = doc(
        outcome("lead_duplicate", "has(steps.tim) && steps.tim.done == false"),
        outcome("lead_new", "has(steps.tim) && steps.tim.done == true"),
        outcome("touched", "has(steps.tim)"),
    )
    state = {"out__tim": {"done": True}, "work": {}}
    assert await reached(engine, document, state) == ["lead_new", "touched"]


async def test_r5_24_a_failed_runs_outcomes_read_its_last_state(engine: CelCppEngine) -> None:
    document = doc(outcome("lead_new", "has(steps.tim)"), outcome("untouched", "!has(steps.tim)"))
    assert await reached(engine, document, {"work": {}}) == ["untouched"]


async def test_r5_24_a_condition_that_errors_is_not_reached_and_the_rest_are(
    engine: CelCppEngine,
) -> None:
    document = doc(outcome("broken", "steps.tim.missing == 1"), outcome("ok", "true"))
    state = {"out__tim": {"done": True}}
    assert await reached(engine, document, state) == ["ok"]


async def test_r5_24_a_document_without_outcomes_reaches_none(engine: CelCppEngine) -> None:
    assert await reached(engine, doc(), {"out__tim": {"done": True}}) == []
