"""The `dw_work` lane's run starter for wf-lite (wf-lite R6.2, R6.9, R6.14).

Before a DW's run starts, its pinned workflow must be shipped, its parameters
must match the document's `variables[]`, and every decision class the document
uses must be on the DW, not loosened there: the same effect level, a ceiling
no higher, and never reversible where the document says it is not. Any of
these refuses the start with its code, and the lane fails the work item with
it; nothing runs.

The run is the lane's request, acting as the DW's principal within its tools
(`run_context_for`), pinned to the document's sha256 (`definition_hash`), and
started with the claim's run id, so a claim returned and taken again starts
the same run (digital-worker R3.14).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from dw_agent_runtime.digital_worker_context import run_context_for, tool_scopes
from dw_agent_runtime.executor import DigitalWorkerBoundaryPort
from dw_agent_runtime.ports import WorkflowRunnerPort
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.wflite.catalog import PackCatalog
from dw_agent_runtime.wflite.document import DecisionClassDecl, Variable
from dw_kernel.autonomy import AUTONOMY_LEVELS, FAIL_CLOSED_LEVEL, is_autonomy_level
from dw_kernel.errors import DomainError
from dw_platform.application.work_queue import Claimed, DwLookupPort, WorkScope
from dw_platform.domain.digital_worker import DecisionClass


class TenantRunFactsPort(Protocol):
    async def facts(self, tenant_id: uuid.UUID) -> tuple[str, str]:
        """The tenant's plan id and autonomy ceiling."""
        ...


def _refused(code: str, **details: object) -> DomainError:
    return DomainError(f"the run cannot start: {code}", details={"reason_code": code, **details})


def _uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return isinstance(value, str)


_TYPES: Mapping[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "uuid": _uuid,
}


def checked_parameters(variables: Sequence[Variable], given: Mapping[str, Any]) -> dict[str, Any]:
    """R6.2: the DW's parameters as the document declares them, defaults
    filled; `parameter_invalid` for an unknown name, a missing required one or
    a value of the wrong type."""
    declared = {v.name: v for v in variables}
    unknown = sorted(set(given) - set(declared))
    if unknown:
        raise _refused("parameter_invalid", unknown=unknown)
    params: dict[str, Any] = {}
    for variable in variables:
        if variable.name in given:
            value = given[variable.name]
        elif variable.default is not None:
            value = variable.default
        elif variable.required:
            raise _refused("parameter_invalid", missing=variable.name)
        else:
            continue
        if not _TYPES[variable.type](value):
            raise _refused("parameter_invalid", name=variable.name, expected=variable.type)
        if variable.type in ("integer", "number") and (
            (variable.minimum is not None and value < variable.minimum)
            or (variable.maximum is not None and value > variable.maximum)
        ):
            raise _refused("parameter_invalid", name=variable.name, outside="bounds")
        params[variable.name] = value
    return params


def check_decision_classes(
    declared: Sequence[DecisionClassDecl], on_dw: Sequence[DecisionClass]
) -> None:
    """R6.2, R6.9: every class the document uses is on the DW, and the DW does
    not loosen it."""
    mine = {c.key: c for c in on_dw}
    for cls in declared:
        found = mine.get(cls.key)
        if found is None:
            raise _refused("decision_class_missing", decision_class=cls.key)
        looser = (
            found.effect_level != cls.effect_level
            or AUTONOMY_LEVELS.index(found.ceiling) > AUTONOMY_LEVELS.index(cls.ceiling)
            or (found.reversible and not cls.reversible)
        )
        if looser:
            raise _refused("decision_class_mismatch", decision_class=cls.key)


@dataclass(frozen=True)
class WorkflowRunStarter:
    """Implements the lane's `DigitalWorkerRunStarter`."""

    catalog: PackCatalog
    workers: DwLookupPort
    boundary: DigitalWorkerBoundaryPort
    tenants: TenantRunFactsPort
    tools: ToolRegistry
    runner: WorkflowRunnerPort

    async def start(self, claimed: Claimed) -> None:
        item = claimed.item
        scope = WorkScope(tenant_id=item.tenant_id, workspace_id=item.workspace_id)
        worker = await self.workers.digital_worker(scope, item.dw_id)
        if worker is None:
            raise _refused("dw_missing")
        config = worker.configuration
        pinned = self.catalog.workflow(config.workflow_key, config.workflow_version)
        if pinned is None:
            raise _refused(
                "workflow_not_loaded",
                workflow=f"{config.workflow_key}@{config.workflow_version}",
            )
        document = pinned.document
        params = checked_parameters(document.variables, config.parameters)
        check_decision_classes(document.decision_classes, config.decision_classes)
        boundary = await self.boundary.boundary(
            tenant_id=item.tenant_id,
            workspace_id=item.workspace_id,
            principal_id=worker.principal_user_id,
        )
        plan_id, ceiling = await self.tenants.facts(item.tenant_id)
        run_context = run_context_for(
            worker,
            run_id=claimed.run_id,
            membership_scopes=boundary.scopes if boundary is not None else frozenset(),
            tool_scopes=tool_scopes(self.tools.all_definitions(), config.allowed_tools),
            plan_id=plan_id,
            trace_id=str(claimed.run_id),
            autonomy_ceiling=ceiling if is_autonomy_level(ceiling) else FAIL_CLOSED_LEVEL,  # type: ignore[arg-type]
            subject_ref=f"work_item:{item.id}",
        ).model_copy(update={"definition_hash": pinned.sha256})
        await self.runner.start(
            run_context=run_context,
            input_payload={
                "work": dict(item.payload),
                "params": params,
                "dw_id": str(item.dw_id),
                "work_item_id": str(item.id),
                "definition_hash": pinned.sha256,
                "trail": [],
            },
        )
