"""A document's `outcomes[]`: checked at submit, reached at the run's end
(workflow-engine R1.9, R5.24; ADR-0112 decision 1 and Amendments 2026-11-04;
H-14).

One module owns what a condition may name, so the check at submit and the
evaluation at the end read the same environment (`outcome_env`):

- `steps`: an object of the steps that dominate the document's end on its
  `WorkflowIR`, each the step's output (`dyn`). A step in a lane of a block
  does not dominate the end, so naming it is `wf.ref_not_dominating`, inside
  `has()` too (R2.5): its value reaches a condition through a variable.
- `params`: the document's declared variables, typed.
- `work`: the run's input (`dyn`).

A condition must type as `bool` (or `dyn`, decided at the end): anything else
is `wf.type_mismatch` (R2.6). At the end, a condition that does not evaluate
to `true` (false, an error, a value that is not a boolean) is not reached;
the names reached keep the document's order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dw_agent_runtime.wflite.document import Step, WorkflowDocument
from dw_agent_runtime.wflite.ir import Terminal, WorkflowIR, dominators, join_path, lower
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.validate import Problem
from dw_kernel.expressions import (
    BOOL,
    DOUBLE,
    DW_CEL_LIBRARY,
    DYN,
    INT,
    STRING,
    CheckedExpression,
    ExpressionEngine,
    ExpressionEnv,
    ExprType,
    MapType,
    describe,
    object_type,
)
from dw_kernel.ids import TenantId

__all__ = ["check_outcomes", "outcome_env", "reached_outcomes"]

_VARIABLE_TYPES: Mapping[str, ExprType] = {
    "string": STRING,
    "integer": INT,
    "number": DOUBLE,
    "boolean": BOOL,
    "uuid": STRING,
}
_CONDITION_TYPES = frozenset({describe(BOOL), describe(DYN)})


def _all_steps(ir: WorkflowIR) -> dict[int, Step]:
    return {placed.index: placed.step for placed in ir.steps}


def _dominating(document: WorkflowDocument, registry: Mapping[str, NodeTypeSpec]) -> list[str]:
    ir = lower(document, registry)
    tree = dominators(ir)
    return [
        step.id
        for index, step in sorted(_all_steps(ir).items())
        if tree.dominates(index, Terminal.END)
    ]


def outcome_env(
    document: WorkflowDocument,
    registry: Mapping[str, NodeTypeSpec],
    tenant_id: TenantId | None = None,
) -> ExpressionEnv:
    """What an `outcomes[]` condition of `document` may name."""
    return ExpressionEnv(
        tenant_id,
        {
            "steps": object_type("steps", dict.fromkeys(_dominating(document, registry), DYN)),
            "params": object_type(
                "params", {v.name: _VARIABLE_TYPES[v.type] for v in document.variables}
            ),
            "work": MapType(DYN),
        },
        DW_CEL_LIBRARY,
    )


def check_outcomes(
    document: WorkflowDocument,
    registry: Mapping[str, NodeTypeSpec],
    engine: ExpressionEngine,
) -> list[Problem]:
    """Every problem of `document`'s conditions, at `outcomes/<i>/when`."""
    if not document.outcomes:
        return []
    env = outcome_env(document, registry)
    every_step = {step.id for step in _all_steps(lower(document, registry)).values()}
    found: list[Problem] = []
    for index, outcome in enumerate(document.outcomes):
        path = join_path("outcomes", index, "when")
        checked = engine.check(outcome.when, env)
        if isinstance(checked, CheckedExpression):
            if describe(checked.result_type) not in _CONDITION_TYPES:
                found.append(Problem.of(path, "wf.type_mismatch", "bool"))
            continue
        for issue in checked:
            if issue.kind == "undefined_field" and issue.name in every_step:
                found.append(Problem.of(path, "wf.ref_not_dominating", issue.name))
            elif issue.kind in ("undefined_field", "undeclared_reference"):
                found.append(Problem.of(path, "wf.ref_unknown", issue.name or ""))
            elif issue.kind == "other" and "*error*" in issue.message:
                # Follows from an issue already reported (a missing field).
                continue
            else:
                found.append(Problem.of(path, "wf.expression_invalid", issue.kind))
    return found


async def reached_outcomes(
    document: WorkflowDocument,
    registry: Mapping[str, NodeTypeSpec],
    engine: ExpressionEngine,
    state: Mapping[str, Any],
    *,
    tenant_id: TenantId | None = None,
) -> list[str]:
    """The names of `document`'s outcomes whose condition is `true` over a
    run's final `state` (its step outputs, `work` and `params`), in the
    document's order. A condition that fails to check or to evaluate is not
    reached; the run ends either way."""
    if not document.outcomes:
        return []
    env = outcome_env(document, registry, tenant_id)
    steps = {
        step_id: dict(output)
        for step_id in _dominating(document, registry)
        if isinstance(output := state.get(f"out__{step_id}"), Mapping)
    }
    activation = {
        "steps": steps,
        "params": dict(state.get("params") or {}),
        "work": dict(state.get("work") or {}),
    }
    reached: list[str] = []
    for outcome in document.outcomes:
        checked = engine.check(outcome.when, env)
        if not isinstance(checked, CheckedExpression):
            continue
        try:
            value = await engine.evaluate(checked, activation)
        except Exception:
            # A state the engine refuses (a value it cannot carry) reaches
            # nothing; the run still ends.
            continue
        if value is True:
            reached.append(outcome.name)
    return reached
