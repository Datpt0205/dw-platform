"""The run context of a Digital Worker's run (digital-worker R1.4; ADR-0103
decisions 4-5, ADR 0011).

A DW's run is asked for by the `dw_work` lane, which stands as itself
(`system_actor('dw_work')`), and acts as the DW's service principal. Its reach
is the principal's membership scopes cut to what the DW's allowed tools need:
a principal holding more than its tools use does not hand the rest to the run,
and a tool the principal cannot use stays unusable. No role stands in for a
scope here, so the context carries none.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_kernel.autonomy import FAIL_CLOSED_LEVEL, AutonomyLevel
from dw_platform.domain.audit import system_actor
from dw_platform.domain.digital_worker import DigitalWorker

LANE = "dw_work"
CHANNEL = "dw_work"


def tool_scopes(definitions: Iterable[ToolDefinition], allowed: Iterable[str]) -> frozenset[str]:
    """The union of `required_scopes` of the tools named in `allowed`."""
    names = set(allowed)
    return frozenset(scope for d in definitions if d.name in names for scope in d.required_scopes)


def run_context_for(
    worker: DigitalWorker,
    *,
    run_id: uuid.UUID,
    membership_scopes: frozenset[str],
    tool_scopes: frozenset[str],
    plan_id: str,
    trace_id: str,
    autonomy_ceiling: AutonomyLevel = FAIL_CLOSED_LEVEL,
    subject_ref: str | None = None,
) -> RunContext:
    config = worker.configuration
    return RunContext(
        run_id=run_id,
        tenant_id=worker.tenant_id,
        workspace_id=worker.workspace_id,
        actor_id=worker.principal_user_id,
        requested_by=system_actor(LANE).value,
        run_as_principal_id=worker.principal_user_id,
        worker_id=config.workflow_key,
        worker_version=config.workflow_version,
        channel=CHANNEL,
        plan_id=plan_id,
        roles=frozenset(),
        scopes=membership_scopes & tool_scopes,
        trace_id=trace_id,
        autonomy_ceiling=autonomy_ceiling,
        subject_ref=subject_ref,
    )
