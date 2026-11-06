"""The `workflow` kind's capability check as agent-lifecycle/03's `SubmitCheck`
(compliance-pdpl R4, ticket 05): the composition root registers what
`workflow_capability_check` builds in its table of per-kind submit checks.

Beside `kinds.py`, where the capabilities meet: `workflows` and `lifecycle`
never import each other, so the check's own refusal becomes the submit's
`SubmitRefusal` here, its code, every problem and `details.paths` unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.validate import ToolSpecLookup
from dw_kernel.ports import IdGenerator
from dw_studio.core.application.ports import ArtifactTx, VersionRow
from dw_studio.core.domain.artifacts import ClosureItem
from dw_studio.lifecycle.application.ports import SubmitRefusal
from dw_studio.workflows.adapters.capability import (
    ProfileLocations,
    SqlCapabilityFacts,
    SqlVersionAssessments,
)
from dw_studio.workflows.application.capability import LabelTable
from dw_studio.workflows.application.capability_check import (
    WorkflowCapabilityCheck,
    platform_label_table,
)


@dataclass(frozen=True)
class CapabilitySubmitCheck:
    """A `SubmitCheck` over `WorkflowCapabilityCheck`."""

    check: WorkflowCapabilityCheck

    async def __call__(
        self, tx: ArtifactTx, version: VersionRow, closure: Sequence[ClosureItem]
    ) -> SubmitRefusal | None:
        found = await self.check(tx, version, closure)
        if found is None:
            return None
        return SubmitRefusal(found.reason_code, found.detail, found.errors, dict(found.details))


def workflow_capability_check(
    *,
    registry: Mapping[str, NodeTypeSpec],
    tools: ToolSpecLookup,
    ids: IdGenerator,
    profile_locations: ProfileLocations,
    default_profile: str | None,
    table: LabelTable | None = None,
) -> CapabilitySubmitCheck:
    """The check over the platform's label table (`table=` is a test's own,
    for its fixture types), the run's default model profile the one a model
    step is pinned to (a workflow's kind names no profile of its own)."""
    store = SqlVersionAssessments(ids)
    return CapabilitySubmitCheck(
        WorkflowCapabilityCheck(
            registry=registry,
            table=table if table is not None else platform_label_table(default_profile),
            facts=SqlCapabilityFacts(
                registry=registry,
                tools=tools,
                assessments=store,
                profile_locations=profile_locations,
                model_profiles=() if default_profile is None else (default_profile,),
            ),
            assessments=store,
        )
    )
