"""LangGraph implementation of ``WorkflowRunnerPort``.

Responsibilities:
- compile registered graphs with the tenant-aware checkpoint saver;
- persist run lifecycle in platform.worker_runs;
- map LangGraph interrupts to platform ApprovalRequests (pause);
- resume a durable run from its checkpoint after approval — including after a
  full process restart, since all state lives in PostgreSQL;
- run a Studio run taken from its `queued` row (`run_studio`, workflow-engine/03),
  its graph compiled from the document its manifest pinned; a Studio agent's
  run past dispatch goes its own way (`_run_agent`, agent-builder/03).

Every compiled graph of the process, a code worker's, a tenant's wf-lite
version's and a Studio version's, sits in one LRU of `GRAPH_CACHE_SIZE`
(workflow-engine R4.2), so a process that meets many versions holds a bounded
number of graphs.

LangGraph never leaks outside this adapter (import-linter enforced).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal, cast

from langgraph.store.base import BaseStore
from langgraph.types import Command

from dw_agent_runtime.adapters.checkpoint import (
    FENCE_RUN_ID,
    FENCE_TOKEN,
    SqlAlchemyCheckpointSaver,
)
from dw_agent_runtime.adapters.langchain_usage import LangchainUsageMeter
from dw_agent_runtime.adapters.run_store import (
    TERMINAL_STATUSES,
    RunStatus,
    SqlWorkerRunStore,
)
from dw_agent_runtime.adapters.studio_resume import build_facts, parked_interrupts
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy, lower_autonomy
from dw_agent_runtime.context import access_context_from_run
from dw_agent_runtime.contracts import RunArtifact, RunContext, WorkerDefinition
from dw_agent_runtime.leases import LEASE_BEAT_SECONDS, beating, run_holder
from dw_agent_runtime.ports import (
    LimitsPort,
    RunControlPort,
    RunGraphsPort,
    RunLease,
    RunWaitsPort,
    StudioLeaseLostError,
    StudioRun,
    StudioRunBlocked,
)
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.run_control import HOLDING_REASONS, RunControlDoor, RunHaltedError
from dw_agent_runtime.studio_agent import (
    AGENT_DISABLED,
    AGENT_KIND,
    AGENT_RECURSION_LIMIT,
    APPROVAL_WAIT_UNAVAILABLE,
    DRAFT_OUTSIDE_SIMULATE,
    ENABLED_TRIGGERS,
    AgentRefusedError,
    BuiltAgent,
    StudioAgentPort,
    StudioAgentPorts,
    agent_cache_key,
)
from dw_agent_runtime.studio_dispatch import (
    RUN_DEADLINE,
    TEMPORARY_HOLD,
    BindingReviewAlert,
    Ended,
    Held,
    PrincipalInactiveAlert,
    StudioAdmission,
)

# The lane a Studio run is admitted in (ADR-0113 decision 3), whose name a
# refusal's audit stands under.
from dw_agent_runtime.studio_lane import LANE as _STUDIO_LANE
from dw_agent_runtime.wflite.compile import COMPILER_VERSION, StudioWorkflow, compile_workflow
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.node_wrapper import (
    RunDeadlineExceededError,
    StudioRunContext,
    StudioRunFailedError,
    StudioRunPorts,
)
from dw_agent_runtime.wflite.outcomes import reached_outcomes
from dw_agent_runtime.wflite.resume import ResumeVerdict, check_resume
from dw_kernel.errors import (
    ConfigError,
    ConflictError,
    EntitlementDeniedError,
    InfrastructureError,
    NotFoundError,
)
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.limits import LIMIT_EXCEEDED, LimitExceededError, spending_under
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.residency import RESIDENCY_REFUSED, ResidencyRefusedError
from dw_observability.metrics import DW_RUN_DURATION_SECONDS, DW_RUN_TOTAL
from dw_observability.semconv import invoke_workflow_span_name
from dw_observability.telemetry import NullTelemetry, TelemetryPort
from dw_platform.application.ports import PlatformUnitOfWorkFactory
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent, lane_audit_event

logger = logging.getLogger(__name__)

# How long Stop waits for a cancelled run to record itself. Settling is one row
# write and one audit row; past this the request answers and the reaper covers
# a run that never settled.
_CANCEL_SETTLE_SECONDS = 10
_ERROR_MESSAGE_LIMIT = 500

# Enough to absorb a slow reader on a normal turn without letting an absent one
# accumulate a whole run's tokens: a turn streams a few hundred chunks, and a
# reader that has fallen this far behind is not coming back.
_STREAM_BACKLOG_LIMIT = 256

# Compiled graphs a process keeps (workflow-engine R4.2): the least recently
# used goes first.
GRAPH_CACHE_SIZE: Final = 256
# Why a Studio run taken again is `blocked` (workflow-engine R6.5, R6.8).
INCOMPATIBLE_RESUME: Final = "incompatible_resume"
EMPTY_RESUME: Final = "empty_resume"
# A run held because its principal's scopes could not be read (R6.12).
SCOPES_UNAVAILABLE: Final = "principal_scopes_unavailable"
_DURABILITIES: Final = frozenset({"sync", "async", "exit"})


class ResumeInterrupted(Exception):  # noqa: N818 - names what the row records
    """What a resumed run's row says when the resume was cancelled (R9.1)."""


def _publish(queue: asyncio.Queue[tuple[str, Any]], item: tuple[str, Any]) -> None:
    """Hand an event to the reader without ever blocking the run on it.

    A run outlives its reader by design, so a client that closes its tab leaves
    nobody draining. Dropping the oldest display chunk is safe -- the transcript
    is the record of what was said, not this queue -- and it keeps the newest
    output, which is what a reconnecting reader wants.
    """
    if queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
    queue.put_nowait(item)


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of graph state to JSON-storable data."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if not str(k).startswith("__")}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class LangGraphWorkflowRunner:
    """Implements ``WorkflowRunnerPort`` on LangGraph + PostgreSQL."""

    worker_registry: WorkerRegistry
    graph_registry: GraphRegistry
    checkpoint_saver: SqlAlchemyCheckpointSaver
    run_store: SqlWorkerRunStore
    uow_factory: PlatformUnitOfWorkFactory
    clock: UtcClock
    id_generator: IdGenerator
    # Every hard limit on the scope chain (usage-and-limits R4.1, R5.1;
    # ADR-0121 decision 6): asked here, where a run begins and where it goes on
    # after a wait, and nowhere else. Injected, never defaulted: a default would
    # be "unlimited", the one bug in this file a customer finds before we do.
    limits: LimitsPort
    # Whose version is stamped on every run. The SAME instance the executor and
    # the agent's middleware decide with, so the stamp names the rules that
    # were actually applied.
    approval_policy: AutonomyApprovalPolicy
    # The freeze, the kill and the run's principal and company, asked where a
    # run starts and resumes (agent-lifecycle R7, R9). Injected, never
    # defaulted, as `limits` is: a default would be a door left open.
    run_control: RunControlPort
    store: BaseStore | None = None
    release_manifest_ref: str | None = None
    telemetry: TelemetryPort = field(default_factory=NullTelemetry)
    # F6: what the graph's model calls cost. None keeps old wirings valid;
    # a run under None simply stays off the ledger, as every run did before.
    usage_meter: LangchainUsageMeter | None = None
    # How often a running tree's lease is beaten (R5.9); a test shortens it.
    lease_beat_seconds: float = LEASE_BEAT_SECONDS
    # A Digital Worker's work item follows its run: waiting, resumed, finished
    # (wf-lite R6.3, R6.5, R6.7). None keeps every wiring that predates it.
    run_waits: RunWaitsPort | None = None
    # A tenant's published workflow is registered on its run's first use
    # (wf-ai R6.5). None keeps every wiring that predates it.
    run_graphs: RunGraphsPort | None = None
    # What a Studio run needs (workflow-engine/03); None for a runner that runs
    # none, whose `run_studio` refuses.
    studio: StudioRunPorts | None = None
    # What a Studio agent's run needs (agent-builder/03): its graph source and
    # its finished thread's checkpoints. None refuses such a run
    # `agent_runtime_unwired`.
    studio_agents: StudioAgentPorts | None = None
    _compiled: OrderedDict[tuple[str, ...], Any] = field(default_factory=OrderedDict)
    # Holds a reference to every in-flight streamed run; without one the task is
    # garbage-collectable mid-run.
    _running: set[asyncio.Task[None]] = field(default_factory=set)
    # The streamed run each thread has in flight in THIS process, so a reader
    # who presses Stop can end the run itself and not only their own view of it.
    _by_thread: dict[uuid.UUID, asyncio.Task[None]] = field(default_factory=dict)

    def _span_attributes(
        self,
        run_context: RunContext,
        run_id: uuid.UUID,
        graph_version: str,
        worker: WorkerDefinition | None = None,
    ) -> dict[str, object]:
        """Safe identifiers only — never prompt/content payloads (section 21.2).

        Every artifact version the run resolved, not only the graph's. A trace
        that says which worker ran but not which prompt bundle or toolset it ran
        under cannot answer the question traces exist for: "this lead scored
        differently last week — what changed?" `CLAUDE.md` section Observability asks
        for all of them, and they cost one string each.
        """
        attributes: dict[str, object] = {
            "dw.tenant_id": str(run_context.tenant_id),
            "dw.workspace_id": str(run_context.workspace_id),
            "dw.run_id": str(run_id),
            "dw.worker_id": run_context.worker_id,
            "dw.worker_version": run_context.worker_version,
            "dw.graph_version": graph_version,
            "dw.trace_id": run_context.trace_id,
            "dw.release_manifest_ref": self.release_manifest_ref,
            # What woke the run, so a spike in runs can be traced to its cause
            # rather than to a count.
            "dw.channel": run_context.channel,
            # The mode the run runs in, as its row records it (tenant-config R4.3).
            "dw.run_mode": run_context.run_mode,
        }
        if run_context.subject_ref:
            attributes["dw.subject_ref"] = run_context.subject_ref
        if worker is not None:
            attributes["dw.prompt_bundle_version"] = worker.prompt_bundle_version
            attributes["dw.toolset_version"] = worker.toolset_version
            attributes["dw.policy_version"] = worker.policy_version
            attributes["dw.model_profile"] = worker.default_model_profile
        return attributes

    @contextlib.contextmanager
    def _invocation(self, run_context: RunContext, attributes: dict[str, object]) -> Iterator[None]:
        """One pass of the graph, a start or a resume: its span and its duration.

        The duration is this pass, not the run: a run that waits a day for an
        approval is two passes, and the wait is `dw_approval_wait_seconds`'s.
        `status` is whether the pass raised; the run's own status is
        `dw_run_total`'s.
        """
        started = time.monotonic()
        status = "error"
        with self.telemetry.span(invoke_workflow_span_name(run_context.worker_id), attributes):
            try:
                yield
                status = "ok"
            finally:
                self.telemetry.record_histogram(
                    DW_RUN_DURATION_SECONDS,
                    time.monotonic() - started,
                    {"worker": run_context.worker_id, "status": status},
                )

    def hosts(self, *, worker_id: str, worker_version: str, graph_version: str) -> bool:
        try:
            self.graph_registry.resolve(worker_id, graph_version)
            self.worker_registry.resolve(worker_id, worker_version)
        except NotFoundError:
            return False
        return True

    async def _ensure_graph(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID, worker_id: str, worker_version: str
    ) -> None:
        if self.run_graphs is not None:
            await self.run_graphs.ensure(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                worker_id=worker_id,
                worker_version=worker_version,
            )

    def _cached(self, key: tuple[str, ...], build: Callable[[], Any]) -> Any:
        """The one cache of compiled graphs, least recently used out first."""
        if key in self._compiled:
            self._compiled.move_to_end(key)
            return self._compiled[key]
        graph = build()
        self._compiled[key] = graph
        while len(self._compiled) > GRAPH_CACHE_SIZE:
            self._compiled.popitem(last=False)
        return graph

    def _graph(self, worker_id: str, graph_version: str) -> Any:
        def build() -> Any:
            factory = self.graph_registry.resolve(worker_id, graph_version)
            return factory().compile(checkpointer=self.checkpoint_saver, store=self.store)

        return self._cached((worker_id, graph_version), build)

    def _studio_graph(self, studio: StudioRunPorts, taken: StudioRun) -> Any:
        """A Studio version's graph, under `(tenant, version, pinned hash,
        COMPILER_VERSION)`: a draft edited since keeps its id and changes its
        hash, so a new run never takes the old content's graph (R4.2)."""
        key = (
            "studio",
            str(taken.tenant_id),
            str(taken.artifact_version_id),
            taken.pinned_hash,
            COMPILER_VERSION,
        )

        def build() -> Any:
            workflow = StudioWorkflow(
                WorkflowDocument.model_validate(taken.document), taken.pinned_hash, studio.registry
            )
            return compile_workflow(workflow, studio.nodes).compile(
                checkpointer=self.checkpoint_saver
            )

        return self._cached(key, build)

    def _config(
        self,
        run_context: RunContext,
        run_id: uuid.UUID,
        recursion_limit: int,
        callbacks: list[Any] | None = None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "recursion_limit": recursion_limit,
            "configurable": {
                "thread_id": str(run_context.thread_id or run_id),
                "tenant_id": str(run_context.tenant_id),
                "workspace_id": str(run_context.workspace_id),
            },
        }
        if callbacks:
            # Parent-level callbacks propagate to every model call in the
            # graph, subgraphs included — the one seam that meters them all.
            config["callbacks"] = callbacks
        return config

    @contextlib.asynccontextmanager
    async def _metered(
        self, run_context: RunContext, worker: WorkerDefinition
    ) -> AsyncIterator[list[Any] | None]:
        if self.usage_meter is None:
            yield None
            return
        prompt_id, prompt_version = _loop_prompt(worker)
        async with self.usage_meter.track(
            run_context,
            profile_id=worker.default_model_profile,
            task="agent_loop",
            prompt_id=prompt_id,
            prompt_version=prompt_version,
        ) as callbacks:
            yield list(callbacks)

    def _with_autonomy(self, run_context: RunContext, worker: WorkerDefinition) -> RunContext:
        """Resolve the level this run runs at — once, here, where the run begins.

        The lower of what the worker was built for and what its tenant allows. A
        tenant can hold a worker below its design and never lift it above.

        Only at start. `resume` does not come through here: a paused run carries
        the level it started with, replayed from its row by the approval flow, so
        a ceiling lowered while it waited does not rewrite what it was allowed.
        """
        return run_context.model_copy(
            update={
                "autonomy_level": lower_autonomy(
                    worker.autonomy_level, run_context.autonomy_ceiling
                ),
                "approval_policy_version": self.approval_policy.policy_version,
            }
        )

    async def _admit(self, run_context: RunContext) -> RunLease:
        """The tree's lease, taken where the run begins (usage-and-limits R4.1,
        R5.1; ADR-0121 decision 6).

        Here rather than at the API, because the API is not the only door: a
        worker reacting to an inbound event starts runs nobody clicked. A root
        is admitted; a child run, and an attempt of a gate run, spends against
        the lease of its root or its gate run and is never admitted again
        (R5.6). A refusal is audited `limits.refused` in the run's actor's name
        on this inline path and raised: nothing was reserved, no row written.
        """
        if run_context.lease_root != run_context.run_id:
            return self.limits.lease(run_context)
        try:
            return await self.limits.admit(run_context)
        except LimitExceededError as refused:
            await self._audit(
                run_context, "limits.refused", str(run_context.run_id), details=refused.details
            )
            raise

    async def _release(self, run_context: RunContext, run_id: uuid.UUID, reason: str) -> None:
        """Give the tree's lease back when the run ends or waits (R5.3; failure-
        modes #6): only by the run that took it, and at a wait only when no
        other run of its tree still runs, since they share it. A release that
        fails is logged: the lease expires and the reaper settles it."""
        if run_context.lease_root != run_id:
            return
        try:
            if reason == "paused" and await self.run_store.tree_running(
                run_context.tenant_id, run_context.lease_root, except_run_id=run_id
            ):
                return
            await self.limits.lease(run_context).release(reason)
        except Exception:
            logger.exception("could not release a run's lease", extra={"run_id": str(run_id)})

    @contextlib.asynccontextmanager
    async def _beating(self, lease: RunLease, run_context: RunContext) -> AsyncIterator[None]:
        """The lease's heartbeat for as long as this process runs a run of its
        tree (R5.9), stopped on every way out so a finished run beats nothing;
        and the lease in force for the doors that take no run context (an
        embedding, a rerank), which spend against it (usage-and-limits R6.2)."""
        with spending_under(run_holder(run_context)):
            async with beating(lease, self.lease_beat_seconds):
                yield

    async def start(
        self,
        *,
        run_context: RunContext,
        input_payload: dict[str, Any],
    ) -> uuid.UUID:
        await self._ensure_graph(
            run_context.tenant_id,
            run_context.workspace_id,
            run_context.worker_id,
            run_context.worker_version,
        )
        worker = self.worker_registry.resolve(run_context.worker_id, run_context.worker_version)
        run_context = self._with_autonomy(run_context, worker.definition)
        lease = await self._admit(run_context)
        graph = self._graph(worker.definition.worker_id, worker.definition.graph_version)

        # Admission: the row and the context carry the run's data route class
        # from here on (compliance-pdpl R2.1).
        try:
            run_context = await self.run_store.create(
                run_context,
                worker=worker.definition,
                input_payload=input_payload,
                release_manifest_ref=self.release_manifest_ref,
            )
        except BaseException:
            # No run, so nothing will ever spend the lease or release it.
            await self._release(run_context, run_context.run_id, "failed")
            raise
        await self._audit(
            run_context,
            "run.started",
            str(run_context.run_id),
            details={"run_mode": run_context.run_mode},
        )

        attributes = self._span_attributes(
            run_context,
            run_context.run_id,
            worker.definition.graph_version,
            worker.definition,
        )
        with self._invocation(run_context, attributes):
            try:
                await self.run_control.require_open(run_context, door=RunControlDoor.START)
                async with (
                    self._beating(lease, run_context),
                    self._metered(run_context, worker.definition) as callbacks,
                ):
                    state = await graph.ainvoke(
                        input_payload,
                        self._config(
                            run_context,
                            run_context.run_id,
                            worker.definition.recursion_limit,
                            callbacks,
                        ),
                        context=run_context,
                        **_durability(run_context),
                    )
            except Exception as exc:
                await self._fail(run_context, run_context.run_id, exc)
                raise
        await self._handle_outcome(run_context, run_context.run_id, state)
        return run_context.run_id

    async def run_studio(
        self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, lease_token: str
    ) -> RunStatus:
        """Run a Studio run the `studio_runs` lane claimed under `lease_token`
        until it ends, waits or is held (workflow-engine/03 step 2, /04 step 3).

        Everything comes from the run's row, its manifest and its pinned
        document, read under the run's tenant by `StudioRunStorePort.take`;
        nothing is inserted (R3.5). A draft whose content changed since the
        run pinned it is left `blocked` and nothing is compiled (R6.14).

        A run taken again (it has a `deadline_at`: after a wait, or an
        orphan after a crash) is first held to its deadline: at or past it,
        the run ends `cancelled` `deadline_exceeded` and nothing else runs
        (R6.16). Then dispatch, the one place a Studio run is admitted for
        every `trigger_kind` (`StudioAdmission`, R5.9-R5.19, R5.25): a refusal
        holds the run `queued` or ends it, as the refusal table says, with no
        model call. A run taken again then passes the five checks of
        ADR-0109 decision 8 (`check_resume`, R6.7): one that fails leaves it
        `blocked` `incompatible_resume`, a resume with nothing to resume with
        `blocked` `empty_resume` (R6.5, R6.8), audited, nothing run. Its
        scopes are its principal's now (`LiveScopesPort`, R6.12), never the
        ones it began with; a principal no longer a member, or a port that
        cannot say, holds it `queued`.

        A run that passes gets its `deadline_at` at its first take (R5.22),
        and runs with the `durability` the manifest's `engine` pinned (R4.25)
        and a `recursion_limit` that covers every node once (R4.1), resuming
        each pending interrupt by its LangGraph id with its wait's resolution
        (R6.4). A run that stops at an interrupt parks (`waiting`, or `queued`
        when its wait was decided first) with its checkpoints compacted
        (R6.1, R6.11); the waits it resumed are `consumed` in the write that
        parks or ends it, after their node's checkpoint went on. Every write
        names the claim: checkpoints through the saver's fence, the row
        through the store's (R5.5), and a claim another worker took over
        raises `StudioLeaseLostError`, writing nothing. A run that ends
        `completed` or `failed` after its graph ran records the `outcomes[]`
        it reached in the same write (R5.24). Called by the `studio_runs` lane
        (`dw_agent_runtime.studio_lane`) and nothing else."""
        studio = self.studio
        if studio is None:
            raise ConfigError(
                "this runner runs no Studio run", details={"reason": "studio_not_wired"}
            )
        runs = studio.nodes.runs
        taken = await runs.take(tenant_id, run_id, lease_token=lease_token)
        if isinstance(taken, StudioRunBlocked):
            return RunStatus.BLOCKED
        durability = taken.engine.get("durability")
        if durability not in _DURABILITIES:
            # Closed: a manifest without its engine section runs nothing.
            await runs.finish(
                tenant_id,
                run_id,
                "failed",
                lease_token=lease_token,
                error={"code": "engine_unpinned"},
            )
            return RunStatus.FAILED
        again = taken.deadline_at is not None
        if taken.deadline_at is not None and self.clock.now() >= taken.deadline_at:
            # R6.16: before dispatch and before any check, nothing runs.
            await runs.cancel_past_deadline(tenant_id, run_id, lease_token=lease_token)
            return RunStatus.CANCELLED
        run = _studio_run_context(taken)
        verdict = await StudioAdmission(
            run_control=self.run_control,
            binding_review=studio.binding_review,
            limits=self.limits,
        ).decide(taken, run)
        if isinstance(verdict, Held):
            await self._hold_studio(studio, taken, run, verdict, lease_token)
            return RunStatus.QUEUED
        if isinstance(verdict, Ended):
            if verdict.refusal is not None:
                await self._lane_audit(run, "limits.refused", details=verdict.refusal.details)
            await runs.finish(
                tenant_id, run_id, verdict.status, lease_token=lease_token, error=verdict.error
            )
            return RunStatus(verdict.status)
        lease = verdict.lease
        if taken.artifact_kind == AGENT_KIND:
            return await self._run_agent(taken, run, lease, lease_token, durability)
        resume = ResumeVerdict()
        if again:
            resume = await self._resume_verdict(studio, taken)
            reason = (
                INCOMPATIBLE_RESUME if resume.failed else EMPTY_RESUME if resume.empty else None
            )
            if reason is not None:
                await self._release(run, run_id, "paused")
                await runs.block(
                    tenant_id,
                    run_id,
                    lease_token=lease_token,
                    reason_code=reason,
                    details={"checks": list(resume.failed)} if resume.failed else None,
                )
                self.telemetry.add_metric(
                    DW_RUN_TOTAL,
                    1,
                    {"worker": f"studio:{taken.artifact_kind}", "status": "blocked"},
                )
                return RunStatus.BLOCKED
        scopes = await self._live_scopes(studio, taken)
        if scopes is None:
            await self._release(run, run_id, "paused")
            await self._hold_studio(
                studio, taken, run, Held(SCOPES_UNAVAILABLE, TEMPORARY_HOLD), lease_token
            )
            return RunStatus.QUEUED
        run = run.model_copy(update={"scopes": scopes})
        deadline_at = await runs.admitted(
            tenant_id, run_id, lease_token=lease_token, deadline=RUN_DEADLINE
        )
        graph = self._studio_graph(studio, taken)
        decisions = taken.input.get("approval_decisions")
        context = StudioRunContext(
            run=run,
            deadline_at=deadline_at,
            pinned_results=taken.pinned_results,
            approval_decisions=(
                {str(k): str(v) for k, v in decisions.items()}
                if isinstance(decisions, dict)
                else {}
            ),
            lease_token=lease_token,
        )
        config: dict[str, Any] = {
            "recursion_limit": len(graph.nodes) + 1,
            "configurable": {
                "thread_id": str(taken.thread_id),
                "tenant_id": str(taken.tenant_id),
                "workspace_id": str(taken.workspace_id),
                FENCE_RUN_ID: str(run_id),
                FENCE_TOKEN: lease_token,
            },
        }

        async def end(
            status: Literal["completed", "failed"],
            *,
            error: dict[str, Any] | None = None,
            state: dict[str, Any] | None = None,
        ) -> RunStatus:
            await self._release(run, run_id, status)
            if state is None:
                state = dict((await graph.aget_state(config)).values)
            outcomes = await reached_outcomes(
                WorkflowDocument.model_validate(taken.document),
                studio.registry,
                studio.expressions,
                state,
                tenant_id=TenantId(tenant_id),
            )
            await runs.finish(
                tenant_id,
                run_id,
                status,
                lease_token=lease_token,
                error=error,
                result=None if error is not None else _jsonable(state),
                outcomes=outcomes,
                consumed=resume.consumed,
            )
            return RunStatus(status)

        try:
            payload: Any
            if resume.resume:
                # R6.4: each pending interrupt by its id, never by position.
                payload = Command(resume=dict(resume.resume))
            else:
                snapshot = await graph.aget_state(config)
                work = {k: v for k, v in taken.input.items() if k != "approval_decisions"}
                payload = None if snapshot.next else {"work": work}
            async with self._beating(lease, run):
                state = await graph.ainvoke(payload, config, context=context, durability=durability)
        except (StudioLeaseLostError, asyncio.CancelledError):
            # Another worker holds the run now, or this one is shutting down
            # and the lane hands the claim back: the row, the money lease and
            # the checkpoint are the next holder's (R5.5, R5.6).
            raise
        except RunDeadlineExceededError:
            await self._release(run, run_id, "cancelled")
            return RunStatus.CANCELLED
        except StudioRunFailedError as failed:
            return await end("failed", error={"code": failed.code, "step_id": failed.step_id})
        except RunHaltedError as halted:
            await self._release(run, run_id, "cancelled")
            await runs.finish(
                tenant_id,
                run_id,
                "cancelled",
                lease_token=lease_token,
                error={"code": halted.reason.value, "door": halted.door.value},
            )
            return RunStatus.CANCELLED
        except ResidencyRefusedError:
            # A policy refusal before anything was sent, not a step's failure:
            # no error lane takes it (compliance-pdpl R2.2).
            return await end("failed", error={"code": RESIDENCY_REFUSED})
        except LimitExceededError as stopped:
            # A limit spent mid-run stops it at the next call or step boundary
            # (R5.5, R6.3): no error lane, no retry, no cheaper model. The lane
            # that ran it says so, as itself (usage-and-limits/04 step 2).
            await self._lane_audit(run, LIMIT_STOPPED, details=_limit_stopped(stopped))
            # `error.code`, as a refusal at the queue writes it (studio_dispatch).
            return await end("failed", error={**stopped.details, "code": LIMIT_EXCEEDED})
        except Exception as exc:
            logger.exception("a Studio run failed", extra={"run_id": str(run_id)})
            return await end("failed", error={"code": "step_failed", "type": type(exc).__name__})
        if isinstance(state, dict) and state.get("__interrupt__"):
            # R6.1, R6.11: the run waits where it stopped.
            await self._release(run, run_id, "paused")
            parked = await runs.park(
                tenant_id,
                run_id,
                lease_token=lease_token,
                thread_id=taken.thread_id,
                consumed=resume.consumed,
            )
            return RunStatus(parked)
        return await end("completed", state=state)

    async def _resume_verdict(self, studio: StudioRunPorts, taken: StudioRun) -> ResumeVerdict:
        """The five checks of a run taken again (R6.7), on its pinned
        `engine`, its pinned document under this build's registry, the
        interrupts its checkpoint has pending and its waits not yet used."""
        parked = await parked_interrupts(
            self.checkpoint_saver,
            thread_id=taken.thread_id,
            tenant_id=taken.tenant_id,
            workspace_id=taken.workspace_id,
        )
        return check_resume(
            taken.engine, taken.document, build_facts(studio.registry), parked, taken.waits
        )

    async def _live_scopes(self, studio: StudioRunPorts, taken: StudioRun) -> frozenset[str] | None:
        """What the run's principal holds now in the run's workspace (R6.12);
        None, holding the run, when it is no longer a member or the port
        cannot say. No port: no scopes, never the ones stamped at the start."""
        if studio.live_scopes is None:
            return frozenset()
        try:
            return await studio.live_scopes.scopes(
                taken.tenant_id, taken.workspace_id, taken.run_as_principal_id
            )
        except Exception:
            logger.warning(
                "a Studio run's scopes could not be read",
                exc_info=True,
                extra={"run_id": str(taken.run_id)},
            )
            return None

    async def _run_agent(
        self,
        taken: StudioRun,
        run: RunContext,
        lease: RunLease,
        lease_token: str,
        durability: str,
    ) -> RunStatus:
        """A Studio agent's run past dispatch (agent-builder/03; spec R3).

        Before any model or tool call: a `chat` run (and W2's agent node and
        linked agent) of an agent that is off ends `agent_disabled` (R3.8);
        the graph comes from the one cache under `(tenant, version, pinned
        hash)`, built behind the hash gate on a miss (`definition_mismatch`,
        R3.1-R3.3); a draft's graph runs only in `simulate`, asked at every
        take (`draft_outside_simulate`). The turn goes in and the reply out
        through the source, by run id, never through the row (ADR-0117
        decision 6). A tool call that waits for a person ends the run
        `approval_wait_unavailable` until a Studio agent's wait exists. On
        every way the run ends here its thread's checkpoints go
        (`AgentThreadsPort`); a run taken over by another worker, or shut
        down, keeps them for its next holder."""
        assert self.studio is not None  # `run_studio` refuses a runner without it
        runs = self.studio.nodes.runs
        run = agent_run_context(run)
        agents = self.studio_agents
        tenant_id, run_id = taken.tenant_id, taken.run_id

        async def end(
            status: Literal["completed", "failed", "cancelled"],
            error: dict[str, Any] | None = None,
        ) -> RunStatus:
            await self._release(run, run_id, status)
            await runs.finish(tenant_id, run_id, status, lease_token=lease_token, error=error)
            if agents is not None:
                try:
                    await agents.threads.forget(tenant_id, taken.thread_id)
                except Exception:
                    # The retention lane deletes them on its term.
                    logger.warning(
                        "a finished agent run's checkpoints stayed",
                        exc_info=True,
                        extra={"run_id": str(run_id)},
                    )
            return RunStatus(status)

        if agents is None:
            return await end("failed", {"code": "agent_runtime_unwired"})
        try:
            if taken.trigger_kind in ENABLED_TRIGGERS and not await agents.source.enabled(
                tenant_id, taken.artifact_id
            ):
                raise AgentRefusedError(AGENT_DISABLED, "the agent is off")
            built = await self._agent_graph(agents.source, taken)
            if built.draft and taken.run_mode != "simulate":
                raise AgentRefusedError(DRAFT_OUTSIDE_SIMULATE, "a draft runs only simulated")
        except AgentRefusedError as refused:
            return await end("failed", {"code": refused.code})
        await runs.admitted(tenant_id, run_id, lease_token=lease_token, deadline=RUN_DEADLINE)
        graph = built.graph
        config: dict[str, Any] = {
            "recursion_limit": AGENT_RECURSION_LIMIT,
            "configurable": {
                "thread_id": str(taken.thread_id),
                "tenant_id": str(tenant_id),
                "workspace_id": str(taken.workspace_id),
                FENCE_RUN_ID: str(run_id),
                FENCE_TOKEN: lease_token,
            },
        }
        try:
            snapshot = await graph.aget_state(config)
            payload: dict[str, Any] | None = None
            if not snapshot.next:
                turn = await agents.source.turn(taken)
                payload = {"messages": [{"role": m.role, "content": m.content} for m in turn]}
            async with self._beating(lease, run):
                state = await graph.ainvoke(payload, config, context=run, durability=durability)
            if isinstance(state, dict) and state.get("__interrupt__"):
                return await end("failed", {"code": APPROVAL_WAIT_UNAVAILABLE})
            await agents.source.reply(taken, _final_text(state))
        except (StudioLeaseLostError, asyncio.CancelledError):
            raise
        except AgentRefusedError as refused:
            return await end("failed", {"code": refused.code})
        except RunHaltedError as halted:
            return await end("cancelled", {"code": halted.reason.value, "door": halted.door.value})
        except ResidencyRefusedError:
            return await end("failed", {"code": RESIDENCY_REFUSED})
        except LimitExceededError as stopped:
            await self._lane_audit(run, LIMIT_STOPPED, details=_limit_stopped(stopped))
            return await end("failed", {**stopped.details, "code": LIMIT_EXCEEDED})
        except EntitlementDeniedError as denied:
            # `model_profile_unavailable` (model-connections R1.5), before a send.
            return await end("failed", {"code": str(denied.details.get("reason_code", "denied"))})
        except ConfigError as exc:
            # `key_not_pinned`, `graph_mismatch`: closed on a gap, never a guess.
            return await end("failed", {"code": str(exc.details.get("reason", "config_error"))})
        except Exception as exc:
            logger.exception("a Studio agent run failed", extra={"run_id": str(run_id)})
            return await end("failed", {"code": "step_failed", "type": type(exc).__name__})
        return await end("completed")

    async def _agent_graph(self, source: StudioAgentPort, taken: StudioRun) -> BuiltAgent:
        """The agent of `(tenant, version, pinned hash)` from the one cache;
        on a miss, built by the source behind its hash gate (R3.1, R3.3)."""
        key = agent_cache_key(taken)
        cached = self._compiled.get(key)
        if cached is not None:
            self._compiled.move_to_end(key)
            return cast(BuiltAgent, cached)
        built = await source.build(taken)
        return cast(BuiltAgent, self._cached(key, lambda: built))

    async def _hold_studio(
        self,
        studio: StudioRunPorts,
        taken: StudioRun,
        run: RunContext,
        held: Held,
        lease_token: str,
    ) -> None:
        """A run the refusal table holds: back to `queued`, due later, and the
        people who can lift the hold told (R5.20, R5.21). The audit of a spent
        limit is written once per period, since the run is next due when the
        period resets (usage-and-limits M11). A notice that fails is logged:
        the run is held anyway, and its next take tells again, the inbox's
        UNIQUE key keeping it to one notice (gate MEDIUM (c))."""
        if held.refusal is not None:
            await self._lane_audit(run, "limits.refused", details=held.refusal.details)
        await studio.nodes.runs.hold(
            taken.tenant_id,
            taken.run_id,
            lease_token=lease_token,
            delay=held.delay,
            until=held.until,
        )
        try:
            match held.alert:
                case PrincipalInactiveAlert(principal_id=principal):
                    await studio.alerts.principal_inactive(
                        taken.tenant_id, workspace_id=taken.workspace_id, principal_id=principal
                    )
                case BindingReviewAlert(principal_id=principal, grants_changed_at=at):
                    await studio.alerts.binding_needs_review(
                        taken.tenant_id,
                        workspace_id=taken.workspace_id,
                        artifact_id=taken.artifact_id,
                        principal_id=principal,
                        grants_changed_at=at,
                    )
        except Exception:
            logger.warning(
                "a held run's notice failed", exc_info=True, extra={"run_id": str(taken.run_id)}
            )

    async def stream(
        self,
        *,
        run_context: RunContext,
        input_payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Same lifecycle as ``start``, but the caller sees progress as it happens.

        Awaiting this claims the thread and starts the run; the iterator it
        returns only observes. Claiming eagerly is what lets a refused claim
        reach the caller as a 409 — inside the iterator it would arrive after
        the response headers had already been written.

        The graph runs on its own task, so a client closing its tab does not
        stop it mid-step and strand a paused checkpoint nobody can approve.
        Use ``drain`` to wait for runs whose reader left before shutting down.
        """
        worker = self.worker_registry.resolve(run_context.worker_id, run_context.worker_version)
        run_context = self._with_autonomy(run_context, worker.definition)
        lease = await self._admit(run_context)
        graph = self._graph(worker.definition.worker_id, worker.definition.graph_version)

        # Admission: the row and the context carry the run's data route class
        # from here on (compliance-pdpl R2.1).
        try:
            run_context = await self.run_store.create(
                run_context,
                worker=worker.definition,
                input_payload=input_payload,
                release_manifest_ref=self.release_manifest_ref,
            )
        except BaseException:
            await self._release(run_context, run_context.run_id, "failed")
            raise
        await self._audit(
            run_context,
            "run.started",
            str(run_context.run_id),
            details={"run_mode": run_context.run_mode},
        )
        # Before the run's task exists: a refused start reaches the caller as
        # a 409, with the run already recorded `cancelled` and its reason.
        try:
            await self.run_control.require_open(run_context, door=RunControlDoor.START)
        except RunHaltedError as halted:
            await self._fail(run_context, run_context.run_id, halted)
            raise

        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=_STREAM_BACKLOG_LIMIT)
        task = asyncio.create_task(
            self._drive(
                run_context=run_context,
                lease=lease,
                graph=graph,
                worker=worker.definition,
                input_payload=input_payload,
                config=self._config(
                    run_context, run_context.run_id, worker.definition.recursion_limit
                ),
                attributes=self._span_attributes(
                    run_context, run_context.run_id, worker.definition.graph_version
                ),
                queue=queue,
            )
        )
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        thread_id = run_context.thread_id
        if thread_id is not None:
            self._by_thread[thread_id] = task

            def _forget(done: asyncio.Task[None]) -> None:
                # Only if it is still ours: a later turn on the same thread may
                # already have taken the slot.
                if self._by_thread.get(thread_id) is done:
                    del self._by_thread[thread_id]

            task.add_done_callback(_forget)
        return self._forward(queue)

    async def cancel_thread(self, thread_id: uuid.UUID) -> bool:
        """End the streamed run in flight on this thread, if this process holds it.

        The graph runs on its own task precisely so that a reader closing a tab
        does not strand a half-finished step - which also meant Stop only closed
        the browser's connection while the run kept calling tools and could
        still raise an approval card for work the person had just abandoned.

        Cancelling the task is the path shutdown already takes: `_drive` records
        the run as cancelled and releases the thread. This waits for that to
        land, so a turn sent right after Stop is not refused as still in flight.
        The next turn starts cleanly even if the cancel caught a tool call
        half-answered, because the agent patches dangling tool calls before it
        runs.

        False when nothing is running here - the turn already ended, or another
        process holds it.
        """
        task = self._by_thread.get(thread_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.wait({task}, timeout=_CANCEL_SETTLE_SECONDS)
        return True

    async def _forward(
        self, queue: asyncio.Queue[tuple[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        while True:
            kind, payload = await queue.get()
            if kind == "end":
                return
            if kind == "error":
                raise cast(Exception, payload)
            yield cast(dict[str, Any], payload)

    async def _drive(
        self,
        *,
        run_context: RunContext,
        lease: RunLease,
        graph: Any,
        worker: WorkerDefinition,
        input_payload: dict[str, Any],
        config: dict[str, Any],
        attributes: dict[str, Any],
        queue: asyncio.Queue[tuple[str, Any]],
    ) -> None:
        try:
            with self._invocation(run_context, attributes):
                async with (
                    self._beating(lease, run_context),
                    self._metered(run_context, worker) as callbacks,
                ):
                    run_config = {**config, "callbacks": callbacks} if callbacks else config
                    async for chunk in graph.astream(
                        input_payload,
                        run_config,
                        context=run_context,
                        stream_mode=["messages", "updates"],
                        subgraphs=True,
                        version="v2",
                    ):
                        _publish(queue, ("chunk", chunk))
                await self._settle_stream(run_context, graph, config)
        except asyncio.CancelledError as exc:
            # A CancelledError is a BaseException, so the handler below never saw
            # it: shutdown left the row at `running` while the reader was told
            # the stream had finished.
            #
            # uncancel() first, or the very next await here is cancelled again
            # and the run is left half-settled with its reader still waiting on
            # a queue nothing will ever be put into. The reader is told either
            # way, hence the finally.
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            try:
                await self._fail(
                    run_context,
                    run_context.run_id,
                    exc,
                    status=RunStatus.CANCELLED,
                    event="run.cancelled",
                )
            finally:
                _publish(queue, ("error", exc))
            raise
        except Exception as exc:
            # A `finally`, for the same reason the branch above grew one.
            # `_fail` writes to the database and `_audit` turns ANY failure
            # there into an `InfrastructureError`, so a blip while recording
            # the failure used to skip the line below - and the reader was left
            # awaiting a queue nothing would ever be put into again. The run
            # was over; the browser was never told, and never would be.
            try:
                await self._fail(run_context, run_context.run_id, exc)
            except Exception:
                # Recording the failure failed too. The row may be stranded at
                # `running` and the reaper settles that; what must not ALSO
                # fail is telling the reader, which the `finally` guarantees.
                # Logged rather than swallowed: this is a database in trouble,
                # not a condition the caller can act on.
                logger.exception(
                    "could not record a failed run", extra={"run_id": str(run_context.run_id)}
                )
            finally:
                _publish(queue, ("error", exc))
        else:
            _publish(queue, ("end", None))

    async def drain(self) -> None:
        """Wait for runs still settling after their reader disconnected.

        Keyed on `done()` rather than on the set emptying, and that is the
        whole of it. A task leaves `_running` through a done-callback, which
        the loop runs via `call_soon`; awaiting a `gather` whose children have
        ALREADY finished does not suspend, so the old `while self._running`
        never gave that callback a turn. It span - at full CPU, with the event
        loop wedged so not even a timeout could fire.

        The window is small but ordinary: a reader is handed the failure the
        instant `_publish` puts it, one step before `_drive` returns, so any
        `drain()` right after a failed turn could land inside it. Measured on
        shutdown, which is exactly where it hurts - the process would not stop,
        so the orchestrator killed it, and a kill is what strands runs at
        `running` and locks a conversation behind `uq_worker_runs_active_thread`.

        A finished task has settled, whether or not its callback has run yet,
        so waiting on the unfinished ones answers the question this asks.
        """
        while pending := tuple(task for task in self._running if not task.done()):
            await asyncio.gather(*pending, return_exceptions=True)

    async def resume(
        self,
        *,
        run_context: RunContext,
        run_id: uuid.UUID,
        resume_payload: dict[str, Any],
    ) -> None:
        record = await self.run_store.get(run_context, run_id)
        if record.status not in (RunStatus.WAITING_APPROVAL, RunStatus.WAITING_TIMER):
            raise ConflictError(
                "run is not waiting",
                details={"run_id": str(run_id), "status": record.status.value},
            )
        await self._ensure_graph(
            run_context.tenant_id, run_context.workspace_id, record.worker_id, record.worker_version
        )
        if not self.hosts(
            worker_id=record.worker_id,
            worker_version=record.worker_version,
            graph_version=record.graph_version,
        ):
            raise ConflictError(
                "this service does not run the graph that owns the approval",
                details={
                    "run_id": str(run_id),
                    "worker_id": record.worker_id,
                    "worker_version": record.worker_version,
                    "graph_version": record.graph_version,
                },
            )
        graph = self._graph(record.worker_id, record.graph_version)
        worker = self.worker_registry.resolve(record.worker_id, record.worker_version)

        # Before the run leaves its wait (agent-lifecycle R7.14, R9): under a
        # freeze, or with the switch state unreadable, it stays in its wait,
        # unchanged, and the timer lane tries again at its next tick ("keep
        # paused runs paused", ADR-0120 decision 7); a kill, an inactive
        # principal or company cancels it.
        try:
            await self.run_control.require_open(run_context, door=RunControlDoor.RESUME)
        except RunHaltedError as halted:
            if halted.reason not in HOLDING_REASONS:
                await self._fail(run_context, run_id, halted)
            raise

        # The lease again, here where the run goes on, never in the decision's
        # transaction (ADR-0113 decisions 3, 4; usage-and-limits R5.3): money
        # spent after a wait is new spend, so a spent period ends the run
        # `failed` with `limit_exceeded`, and the decision that resumed it
        # stands and is answered as usual. `runs` is not counted again.
        try:
            lease = await self._take_again(run_context)
        except LimitExceededError as refused:
            await self._fail(run_context, run_id, refused)
            return

        # The run leaves its wait only while it is still in it (runtime-
        # hardening R9.2): of two resumes, one runs the graph and the other is
        # refused here, before it audits or moves the work item.
        await self.run_store.begin_resume(run_context, run_id, waiting=record.status)
        try:
            await self._audit(run_context, "run.resumed", str(run_id))
            waits = self._waits_for(run_context)
            if waits is not None:
                await waits.resumed(run_context, run_id)
            attributes = self._span_attributes(
                run_context, run_id, record.graph_version, worker.definition
            )
            with self._invocation(run_context, attributes):
                async with (
                    self._beating(lease, run_context),
                    self._metered(run_context, worker.definition) as callbacks,
                ):
                    state = await graph.ainvoke(
                        Command(resume=resume_payload),
                        self._config(
                            run_context, run_id, worker.definition.recursion_limit, callbacks
                        ),
                        context=run_context,
                        **_durability(run_context),
                    )
        except BaseException as exc:
            # Past `begin_resume` the run is `running`; whatever stops it here,
            # a cancellation included, it is recorded `failed` rather than left
            # `running` for a reader to wait on (R9.1). A process killed
            # outright leaves it `running`, for the thread claim's reaper.
            if isinstance(exc, asyncio.CancelledError):
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
                await self._fail(run_context, run_id, ResumeInterrupted("the resume was cancelled"))
            else:
                await self._fail(run_context, run_id, exc)
            raise
        await self._handle_outcome(run_context, run_id, state)

    async def _take_again(self, run_context: RunContext) -> RunLease:
        """`limits.resume` for a root going on after a wait; a child or a gate
        attempt finds its root's lease as it is (R5.6)."""
        if run_context.lease_root != run_context.run_id:
            return self.limits.lease(run_context)
        try:
            return await self.limits.resume(run_context)
        except LimitExceededError as refused:
            await self._audit(
                run_context, "limits.refused", str(run_context.run_id), details=refused.details
            )
            raise

    async def _settle_stream(
        self, run_context: RunContext, graph: Any, config: dict[str, Any]
    ) -> None:
        """Give a streamed run its terminal status, however the stream ended."""
        record = await self.run_store.get(run_context, run_context.run_id)
        if record.status in TERMINAL_STATUSES:
            return
        snapshot = await graph.aget_state(config)
        state = dict(snapshot.values)
        if snapshot.interrupts:
            state["__interrupt__"] = list(snapshot.interrupts)
        await self._handle_outcome(run_context, run_context.run_id, state)

    async def _fail(
        self,
        run_context: RunContext,
        run_id: uuid.UUID,
        exc: BaseException,
        *,
        status: RunStatus = RunStatus.FAILED,
        event: str = "run.failed",
    ) -> None:
        """Record why a run stopped, so it cannot sit at `running` for ever.

        A door's refusal (`RunHaltedError`, agent-lifecycle R7.1) is a
        cancellation whatever the caller passed, with its reason on the row's
        `error` and on the `run.cancelled` audit, where the run's screen and
        the `studio_runs` lane read it."""
        error: dict[str, Any] = {
            "type": type(exc).__name__,
            "message": str(exc)[:_ERROR_MESSAGE_LIMIT],
        }
        details: dict[str, Any] | None = None
        if isinstance(exc, RunHaltedError):
            status, event = RunStatus.CANCELLED, "run.cancelled"
            error["reason_code"] = exc.reason.value
            details = {"reason_code": exc.reason.value, "door": exc.door.value}
        elif isinstance(exc, ResidencyRefusedError):
            # `failed`, with the gate's reason on the row and the audit
            # (compliance-pdpl R2.2): nothing was sent.
            error["reason_code"] = RESIDENCY_REFUSED
            details = {"reason_code": RESIDENCY_REFUSED}
        elif isinstance(exc, LimitExceededError):
            # `failed` with `limit_exceeded`, the metric and the scope (R5.5).
            error.update(exc.details)
            details = {"reason_code": LIMIT_EXCEEDED, **exc.details}
        # Released before the row says so, on every way a run ends (failure-
        # modes #6): a release that fails leaves it to the reaper.
        await self._release(run_context, run_id, status.value)
        await self.run_store.set_status(run_context, run_id, status, error=error)
        await self._audit(run_context, event, str(run_id), details=details)
        if isinstance(exc, LimitExceededError):
            # In the run's actor's name on this path, as the end audit above
            # is (usage-and-limits/04 step 2; gate 4/11/2026 (d)).
            await self._audit(run_context, LIMIT_STOPPED, str(run_id), details=_limit_stopped(exc))
        self.telemetry.add_metric(
            DW_RUN_TOTAL, 1, {"worker": run_context.worker_id, "status": status.value}
        )
        waits = self._waits_for(run_context)
        if waits is not None:
            await waits.finished(run_context, run_id, failed=True)

    async def _handle_outcome(
        self, run_context: RunContext, run_id: uuid.UUID, state: dict[str, Any]
    ) -> None:
        interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
        if interrupts:
            distinct = list(
                {getattr(item, "id", None) or id(item): item for item in interrupts}.values()
            )
            if len(distinct) > 1:
                # One run row holds one approval, and resume carries no interrupt
                # id - so a second pause would get no card and could take the
                # first one's decision. `OneApprovalPerStepMiddleware` prevents
                # it; if it ever happens anyway the run ends as failed, visibly,
                # rather than parking on a guess.
                await self._fail(
                    run_context,
                    run_id,
                    ConflictError(
                        "a step paused on more than one approval",
                        details={"pauses": len(distinct)},
                    ),
                )
                return
            first = distinct[0]
            payload = first.value if hasattr(first, "value") else first
            if not isinstance(payload, dict):
                payload = {"value": _jsonable(payload)}
            if payload.get("wait") == "timer":
                await self._park_on_timer(run_context, run_id, payload)
                return
            try:
                approval_id = await self._create_approval(run_context, run_id, payload)
            except Exception:
                # The pause could not be recorded (a malformed `required_scope`
                # refused by its CHECK, ADR 0004). `start` and `resume` call this
                # outside their own failure handling, so without this the row
                # stayed `running` over a checkpoint no request points at. Ended
                # as failed, visibly, like the double pause above. The driver's
                # text (SQL, constraint name) stays in the server log: the run's
                # `error` is returned as is by `GET /runs/{id}`.
                logger.exception(
                    "could not record an approval request", extra={"run_id": str(run_id)}
                )
                await self._fail(
                    run_context,
                    run_id,
                    InfrastructureError("the approval request could not be recorded"),
                )
                return
            await self.run_store.set_status(
                run_context,
                run_id,
                RunStatus.WAITING_APPROVAL,
                approval_request_id=approval_id,
            )
            await self._audit(
                run_context,
                "run.waiting_approval",
                str(run_id),
                details={"approval_request_id": str(approval_id)},
            )
            self.telemetry.add_metric(
                DW_RUN_TOTAL,
                1,
                {"worker": run_context.worker_id, "status": "waiting_approval"},
            )
            waits = self._waits_for(run_context)
            if waits is not None:
                await waits.waiting(run_context, run_id, kind="approval")
            await self._release(run_context, run_id, "paused")
            return

        await self._release(run_context, run_id, "completed")
        await self.run_store.set_status(
            run_context, run_id, RunStatus.COMPLETED, result=_jsonable(state)
        )
        await self._audit(run_context, "run.completed", str(run_id))
        self.telemetry.add_metric(
            DW_RUN_TOTAL, 1, {"worker": run_context.worker_id, "status": "completed"}
        )
        waits = self._waits_for(run_context)
        if waits is not None:
            await waits.finished(run_context, run_id, failed=False)

    def _waits_for(self, run_context: RunContext) -> RunWaitsPort | None:
        """The work item's port, for a run that acts as a principal only."""
        return self.run_waits if run_context.run_as_principal_id is not None else None

    async def _park_on_timer(
        self, run_context: RunContext, run_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        """A `time.wait` (wf-lite R6.5): no approval, the run `waiting_timer`
        and its work item `waiting_timer` until `wake_at`."""
        try:
            wake_at = datetime.fromisoformat(str(payload["wake_at"]))
        except (KeyError, ValueError) as exc:
            await self._fail(
                run_context, run_id, ConflictError("a timer wait without a valid wake_at")
            )
            raise ConflictError("a timer wait without a valid wake_at") from exc
        await self.run_store.set_status(run_context, run_id, RunStatus.WAITING_TIMER)
        await self._audit(
            run_context, "run.waiting_timer", str(run_id), details={"wake_at": wake_at.isoformat()}
        )
        self.telemetry.add_metric(
            DW_RUN_TOTAL, 1, {"worker": run_context.worker_id, "status": "waiting_timer"}
        )
        waits = self._waits_for(run_context)
        if waits is not None:
            await waits.waiting(run_context, run_id, kind="timer", wake_at=wake_at)
        # A wait gives the lease back (R5.3): what the run spent stays on the
        # tree's settled leases, so pausing resets no ceiling.
        await self._release(run_context, run_id, "paused")

    async def _create_approval(
        self, run_context: RunContext, run_id: uuid.UUID, payload: dict[str, Any]
    ) -> uuid.UUID:
        """Raise the approval request a paused run waits on.

        `payload` is the interrupt value a graph node wrote, from code and the
        tenant's policy, never from model output: a tool call's own arguments
        travel nested under `payload["payload"]` (`_ask_human`), so no model can
        set a top-level key such as `required_scope`.

        `required_scope` (ADR 0004) is passed through exactly as the node wrote
        it, neither coerced nor dropped: its shape has one owner, the CHECK on
        the column, and a malformed or non-string value fails this INSERT so the
        run ends failed instead of raising a request nobody could rightly decide.
        """
        approval = ApprovalRequest(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            approval_type=str(payload.get("approval_type", "workflow.review")),
            requested_by=UserId(run_context.actor_id),
            reason=str(payload.get("reason", "workflow requested human review")),
            payload=_jsonable(payload),
            run_id=run_id,
            required_scope=payload.get("required_scope"),
        )
        context = access_context_from_run(run_context)
        async with self.uow_factory(context) as uow:
            await uow.approvals.add(approval)
            await uow.commit()
        return approval.id

    async def _audit(
        self,
        run_context: RunContext,
        action: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        context = access_context_from_run(run_context)
        event = AuditEvent(
            id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            actor_id=UserId(run_context.actor_id),
            action=action,
            resource_type="worker_run",
            resource_id=resource_id,
            run_id=run_context.run_id,
            trace_id=run_context.trace_id,
            details=details or {},
            occurred_at=self.clock.now().astimezone(UTC),
        )
        try:
            async with self.uow_factory(context) as uow:
                await uow.audit.append(event)
                await uow.commit()
        except Exception as exc:
            raise InfrastructureError(
                "failed to write audit event", details={"action": action}
            ) from exc

    async def _lane_audit(
        self, run_context: RunContext, action: str, *, details: dict[str, Any]
    ) -> None:
        """An audit event of the `studio_runs` lane about a run it was handed,
        as itself (ADR 0011): the lane, not a person, met the refusal."""
        event = lane_audit_event(
            lane=_STUDIO_LANE,
            event_id=self.id_generator.new_uuid(),
            tenant_id=TenantId(run_context.tenant_id),
            workspace_id=WorkspaceId(run_context.workspace_id),
            action=action,
            resource_type="worker_run",
            resource_id=str(run_context.run_id),
            occurred_at=self.clock.now().astimezone(UTC),
            details=details,
            run_id=run_context.run_id,
        )
        try:
            async with self.uow_factory(access_context_from_run(run_context)) as uow:
                await uow.audit.append(event)
                await uow.commit()
        except Exception as exc:
            raise InfrastructureError(
                "failed to write audit event", details={"action": action}
            ) from exc


# What a run stopped by a limit is audited as (usage-and-limits/04 step 2).
LIMIT_STOPPED: Final = "run.limit_stopped"


def _limit_stopped(stopped: LimitExceededError) -> dict[str, Any]:
    """`run.limit_stopped`'s details: the reason, the metric that was spent
    and the scope that spent it, which is what tells a child's own behavioural
    limit from its tree's spent month."""
    return {
        "reason_code": LIMIT_EXCEEDED,
        "metric": stopped.details["metric"],
        "scope_type": stopped.details["scope_type"],
    }


def _loop_prompt(worker: WorkerDefinition) -> tuple[str, str]:
    """The versioned artifact a run's unclaimed model spend is billed under.

    An agent loop: the prompt its worker pins, which is the one
    `WorkerSystemPrompt` renders. A plain graph has no loop prompt - its nodes
    bill their own prompts through inner trackers - so what is left over was
    produced by the graph, and is named by the graph's version rather than by a
    version that names nothing.
    """
    if worker.agent_prompt_id is not None and worker.agent_prompt_version is not None:
        return worker.agent_prompt_id, worker.agent_prompt_version
    return f"graph:{worker.worker_id}", worker.graph_version


def agent_run_context(run: RunContext) -> RunContext:
    """A Studio agent's run as its tools see it: a person's own run (the
    principal is whoever asked) is no Digital Worker's, so it carries no
    `run_as_principal_id`, which `ToolExecutor` reads as a DW's boundary
    (digital-worker R6.1); a run a lane asks for in a service principal's
    name keeps it. Whom the run acts as is unchanged (`actor_id`, and
    `run_principal` for the record session)."""
    if run.run_as_principal_id is not None and run.run_as_principal_id == run.requested_by:
        return run.model_copy(update={"run_as_principal_id": None})
    return run


def _final_text(state: Any) -> str:
    """The agent's last message, the turn's answer."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    if isinstance(content, str):
        return content
    return "".join(
        str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
    )


def _studio_run_context(taken: StudioRun) -> RunContext:
    """The run's context from its row: who it acts as, its mode, its manifest
    and its tenant's plan read where it was taken, never a caller's."""
    version = "0.0.0+draft" if taken.version_no is None else f"{taken.version_no}.0.0"
    return RunContext(
        run_id=taken.run_id,
        thread_id=taken.thread_id,
        # Pinned on the row at admission (`RunRequestService`), read, never
        # recomputed, on a start and on a resume alike (compliance-pdpl R2.1).
        route_class=taken.data_route_class,
        tenant_id=taken.tenant_id,
        workspace_id=taken.workspace_id,
        actor_id=taken.run_as_principal_id,
        requested_by=taken.requested_by,
        run_as_principal_id=taken.run_as_principal_id,
        run_manifest_hash=taken.run_manifest_hash,
        artifact_id=taken.artifact_id,
        # The version and the hash it pinned, stamped here at every take; a
        # Studio agent's model selection reads both (agent-builder R3.1).
        artifact=RunArtifact(
            kind=taken.artifact_kind,
            artifact_id=taken.artifact_id,
            version_id=taken.artifact_version_id,
        ),
        definition_hash=taken.pinned_hash.removeprefix("sha256:"),
        # A child spends its root's lease; a root its own (usage-and-limits R5.6).
        root_run_id=taken.root_run_id,
        worker_id=f"studio:{taken.artifact_kind}:{taken.artifact_version_id}",
        worker_version=version,
        channel="studio",
        plan_id=taken.plan_id,
        roles=frozenset(),
        scopes=frozenset(),
        trace_id=taken.trace_id,
        run_mode=taken.run_mode,
    )


def _durability(run_context: RunContext) -> dict[str, Any]:
    """A wf-lite run checkpoints each step before the next one starts (R6.8):
    a step that sent an email is on disk before the step after it runs, so a
    process that dies in between resumes after the send, not before it. Runs
    of code graphs keep LangGraph's default."""
    return {"durability": "sync"} if run_context.definition_hash is not None else {}
