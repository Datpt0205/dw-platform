"""A Digital Worker's draft of its workflow, and its dry run (wf-ai R6.1, R6.2,
R6.7, R6.9, R6.12).

Saving takes a step tree, never a document: the server rebuilds the document
from the DW's own pin and runs the assistant's one check on it
(`checked_proposal`), so what a caller sends is not trusted to have passed the
assistant (R6.1, R6.7; WAI13). One draft per DW; each save names who saved,
and everyone who saved since the last publish stays on it, since none of them
may decide its publication (R6.4). A simulation runs the stored draft, never a
body, and replaces the DW's last one.

Only the DW's Business or Technical Owner reads, saves or simulates
(`require_owner`). Every write carries its audit row and its effect key into
the store's one transaction (R6.12, R6.15). Its review, the diff against the
DW's pin, the tree and the last simulation, is also its Validator's, who
decides its publication (R7.2); anyone else who reads the DW is refused.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.wflite.assistant import (
    DwOwnerPort,
    base_raw,
    bases_of,
    checked_proposal,
    outline_of,
)
from dw_agent_runtime.wflite.catalog import workflow_sha256
from dw_agent_runtime.wflite.compile import ToolModelsPort
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.outline import DwReaderPort, OutlineStep, StepChange, diff_steps
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.simulate import SimulationResult, simulate
from dw_agent_runtime.wflite.validate import ToolSpecLookup
from dw_agent_runtime.wflite.versions import PinnedWorkflowsPort, base_sha256
from dw_kernel.errors import DomainError, NotFoundError, PermissionDeniedError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent


@dataclass(frozen=True, slots=True)
class Draft:
    dw_id: uuid.UUID
    content: Mapping[str, Any]
    content_sha256: str
    base_sha256: str
    saved_by: uuid.UUID
    author_ids: tuple[uuid.UUID, ...]
    state: Literal["draft", "submitted"]
    reason: str | None
    updated_at: datetime
    # The publish approval a submitted draft waits on (wf-ai R6.4).
    approval_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Simulation:
    content_sha256: str
    outcome: Literal["passed", "failed"]
    trail: tuple[Mapping[str, Any], ...]
    tool_calls: tuple[Mapping[str, Any], ...]
    failed_step: str | None
    error: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DraftReview:
    """What the person deciding a publication reads (R7.2): the draft, its
    last simulation, what it changes against the DW's pin now, its tree,
    and whether that pin is still the base the draft was made from."""

    draft: Draft
    simulation: Simulation | None
    diff: tuple[StepChange, ...]
    outline: tuple[OutlineStep, ...]
    base_current: bool


class DraftStorePort(Protocol):
    async def get(self, scope: WorkScope, dw_id: uuid.UUID) -> Draft | None: ...

    async def save(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        *,
        content: Mapping[str, Any],
        content_sha256: str,
        base_sha256: str,
        saved_by: uuid.UUID,
        audit: AuditEvent,
        effect: PendingEffect | None,
    ) -> Draft:
        """One transaction: the effect key, the upsert, the audit row. 409
        `draft_submitted` while the draft waits for its decision (R6.8)."""
        ...

    async def simulation(self, scope: WorkScope, dw_id: uuid.UUID) -> Simulation | None: ...

    async def record_simulation(
        self,
        scope: WorkScope,
        dw_id: uuid.UUID,
        result: Simulation,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None,
    ) -> Simulation:
        """One transaction; refused when the draft is submitted (R6.8) or no
        longer holds the content simulated (`draft_changed`)."""
        ...


RunContextFactory = Callable[[AccessContext, uuid.UUID], RunContext]


def draft_not_found() -> NotFoundError:
    return NotFoundError(
        "this digital worker has no workflow draft", details={"reason_code": "draft_not_found"}
    )


@dataclass(frozen=True)
class WorkflowDrafts:
    workers: DwOwnerPort
    readers: DwReaderPort
    workflows: PinnedWorkflowsPort
    store: DraftStorePort
    registry: Mapping[str, NodeTypeSpec]
    specs: ToolSpecLookup
    tools: ToolModelsPort
    run_context: RunContextFactory
    recommendations: Mapping[str, str]
    clock: UtcClock
    id_generator: IdGenerator

    async def save(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        steps: Sequence[Any],
        *,
        effect: PendingEffect | None = None,
    ) -> Draft:
        worker = await self.workers.require_owner(context, dw_id)
        bases = await bases_of(self.workflows, worker)
        content, problems = checked_proposal(bases, steps, registry=self.registry, tools=self.specs)
        if problems:
            raise DomainError(
                "the draft does not pass the platform's checks",
                details={
                    "reason_code": "draft_not_publishable",
                    "problems": [p.as_dict() for p in problems],
                },
            )
        sha = workflow_sha256(content)
        return await self.store.save(
            WorkScope.of(context),
            dw_id,
            content=content,
            content_sha256=sha,
            base_sha256=base_sha256(bases.pinned),
            saved_by=context.principal_id,
            audit=self._event(context, dw_id, "dw.workflow.draft_saved", {"content_sha256": sha}),
            effect=effect,
        )

    async def get(
        self, context: AccessContext, dw_id: uuid.UUID
    ) -> tuple[Draft, Simulation | None]:
        await self.workers.require_owner(context, dw_id)
        scope = WorkScope.of(context)
        draft = await self.store.get(scope, dw_id)
        if draft is None:
            raise draft_not_found()
        return draft, await self.store.simulation(scope, dw_id)

    async def review(self, context: AccessContext, dw_id: uuid.UUID) -> DraftReview:
        """R7.2: for the DW's Validator, Business Owner or Technical Owner; 403
        `not_dw_person` for anyone else who reads the DW, 404 for who does not."""
        worker = await self.readers.get(context, dw_id)
        people = worker.people
        if context.principal_id not in {
            people.validator_id,
            people.technical_owner_id,
            people.business_owner_id,
        }:
            raise PermissionDeniedError(
                "only the digital worker's people review its draft",
                details={"reason_code": "not_dw_person"},
            )
        scope = WorkScope.of(context)
        draft = await self.store.get(scope, dw_id)
        if draft is None:
            raise draft_not_found()
        bases = await bases_of(self.workflows, worker)
        steps = draft.content.get("steps")
        return DraftReview(
            draft=draft,
            simulation=await self.store.simulation(scope, dw_id),
            diff=tuple(
                diff_steps(
                    base_raw(bases.pinned)["steps"],
                    steps if isinstance(steps, list) else [],
                    self.registry,
                )
            ),
            outline=outline_of(draft.content, self.registry),
            base_current=base_sha256(bases.pinned) == draft.base_sha256,
        )

    async def simulate(
        self, context: AccessContext, dw_id: uuid.UUID, *, effect: PendingEffect | None = None
    ) -> Simulation:
        worker = await self.workers.require_owner(context, dw_id)
        scope = WorkScope.of(context)
        draft = await self.store.get(scope, dw_id)
        if draft is None:
            raise draft_not_found()
        bases = await bases_of(self.workflows, worker)
        pinned = replace(
            bases.pinned,
            document=WorkflowDocument.model_validate(dict(draft.content)),
            sha256=draft.content_sha256,
        )
        result: SimulationResult = await simulate(
            pinned,
            worker=worker,
            tools=self.tools,
            registry=self.registry,
            run_context=self.run_context(context, uuid.uuid4()),
            clock=self.clock,
            recommendations=self.recommendations,
        )
        simulation = Simulation(
            content_sha256=draft.content_sha256,
            outcome=result.outcome,
            trail=result.trail,
            tool_calls=result.tool_calls,
            failed_step=result.failed_step,
            error=result.error,
            created_at=self.clock.now(),
        )
        return await self.store.record_simulation(
            scope,
            dw_id,
            simulation,
            audit=self._event(
                context,
                dw_id,
                "dw.workflow.simulated",
                {"content_sha256": draft.content_sha256, "outcome": result.outcome},
            ),
            effect=effect,
        )

    def _event(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        action: str,
        details: Mapping[str, object],
    ) -> AuditEvent:
        return AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(context.tenant_id),
            workspace_id=WorkspaceId(context.workspace_id),
            actor_id=UserId(context.principal_id),
            action=action,
            resource_type="digital_worker",
            resource_id=str(dw_id),
            occurred_at=self.clock.now(),
            details=dict(details),
        )


__all__ = [
    "Draft",
    "DraftReview",
    "DraftStorePort",
    "Simulation",
    "WorkflowDrafts",
    "draft_not_found",
]
