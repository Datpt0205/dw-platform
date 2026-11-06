"""This build's engine facts, and a Studio run's pending interrupts read from
its checkpoint (workflow-engine R6.4, R6.7; ADR-0109 decision 8).

`build_facts` is what this process runs: the step-type registry it was given,
the saver's checkpoint format and the formats it reads, and the installed
LangGraph's `major.minor`. `WorkflowEngineFacts` hands the manifest builder
the five facts of a root's document (the builder's `EngineFactsPort`, wired at
the composition root), and `StudioResumeChecks` runs the five checks of a run
outside the runner (`POST /runs/{run_id}/resume-check`, R6.39): both go
through `wflite.resume`, the one computation of each fact.

`parked_interrupts` reads the interrupts a checkpoint has pending from the
saver, without compiling a graph: each waiting node's interrupt value names
its wait and its node (`StudioNode.resume_wait`).
"""

from __future__ import annotations

import importlib.metadata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import WRITES_IDX_MAP

from dw_agent_runtime.adapters.checkpoint import (
    CHECKPOINT_FORMAT,
    READABLE_CHECKPOINT_FORMATS,
    SqlAlchemyCheckpointSaver,
)
from dw_agent_runtime.ports import StudioRun
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.resume import (
    BuildFacts,
    Parked,
    ResumeVerdict,
    check_resume,
    engine_facts,
)

# The pending write a paused task leaves (LangGraph keeps the name private and
# reserves it a slot of its own in `WRITES_IDX_MAP`).
_INTERRUPT = "__interrupt__"
assert _INTERRUPT in WRITES_IDX_MAP


def langgraph_version() -> str:
    """The installed LangGraph, `major.minor.patch`."""
    return importlib.metadata.version("langgraph")


def build_facts(registry: Mapping[str, NodeTypeSpec]) -> BuildFacts:
    return BuildFacts(
        registry=registry,
        checkpoint_format=CHECKPOINT_FORMAT,
        checkpoint_formats=READABLE_CHECKPOINT_FORMATS,
        langgraph=langgraph_version(),
    )


@dataclass(frozen=True)
class WorkflowEngineFacts:
    """`EngineFactsPort` of the manifest builder: the five facts of a root's
    document under this build, none for a root that is not a workflow."""

    registry: Mapping[str, NodeTypeSpec]

    def facts(self, document: Mapping[str, Any]) -> Mapping[str, Any]:
        return engine_facts(document, build_facts(self.registry))


def _config(thread_id: uuid.UUID, tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> RunnableConfig:
    return cast(
        RunnableConfig,
        {
            "configurable": {
                "thread_id": str(thread_id),
                "checkpoint_ns": "",
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
            }
        },
    )


async def parked_interrupts(
    saver: SqlAlchemyCheckpointSaver,
    *,
    thread_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> list[Parked]:
    """The interrupts the thread's latest checkpoint has pending."""
    found = await saver.aget_tuple(_config(thread_id, tenant_id, workspace_id))
    if found is None:
        return []
    parked: list[Parked] = []
    for _task, channel, value in found.pending_writes or ():
        if channel != _INTERRUPT:
            continue
        for item in value if isinstance(value, list | tuple) else (value,):
            payload = getattr(item, "value", None)
            payload = payload if isinstance(payload, Mapping) else {}
            interrupt_id, node = payload.get("interrupt_id"), payload.get("node")
            parked.append(
                Parked(
                    langgraph_id=str(getattr(item, "id", "")),
                    interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
                    node=node if isinstance(node, str) else None,
                )
            )
    return parked


@dataclass(frozen=True)
class StudioResumeChecks:
    """The five checks of a Studio run, run where no graph is compiled (the
    API's `resume-check`): its checkpoint read through the saver."""

    saver: SqlAlchemyCheckpointSaver
    registry: Mapping[str, NodeTypeSpec]

    async def verdict(self, run: StudioRun) -> ResumeVerdict:
        parked = await parked_interrupts(
            self.saver,
            thread_id=run.thread_id,
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
        )
        return check_resume(run.engine, run.document, build_facts(self.registry), parked, run.waits)
