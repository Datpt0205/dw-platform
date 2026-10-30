"""What the composition root hands to the rest of the process.

Two objects, because they answer two different questions.

``ApiContainer`` is what a *route* needs: the platform services behind
``/api/v1/*``. Every stateful field is optional and ``None`` without the
infrastructure it needs, so an unconfigured host mounts fewer routers instead of
serving routers that fail per request.

``RuntimeSeam`` is what a *bounded context* needs to plug itself in: the
registries it registers graphs and tools on, the model gateway its workflows
call, and the shared primitives (session factory, clock, ids, telemetry) its
adapters take by injection. It exists so adding a context is a call against a
published object rather than an edit in the middle of this file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.chat_model import ChatModelFactory
from dw_agent_runtime.adapters.langchain_usage import LangchainUsageMeter
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.run_events import RunStateListener
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.approval_codes import ApprovalViewService
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.budget import RunBudgetLedger
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.model.gateway import RoutingModelGateway
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tool_specs import ToolSpecRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.toolsets import ToolsetRegistry
from dw_api.health import HealthService
from dw_api.settings import ApiSettings
from dw_connectors.adapters.zalo_link import ZaloLinking
from dw_connectors.inbound import InboundUpdateInboxPort
from dw_kernel.ports import IdGenerator, UtcClock
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ingest_jobs import IngestJobStore
from dw_knowledge.ports import ObjectStoragePort
from dw_memory.service import MemoryService
from dw_observability.telemetry import TelemetryPort
from dw_platform.application.access_context import AccessContext
from dw_platform.application.admin_console import AdminConsoleService
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.cache import CachePort
from dw_platform.application.channel_access import ChannelPreferencesPort
from dw_platform.application.digital_workers import DigitalWorkerService
from dw_platform.application.effect_keys import EffectKeyPort
from dw_platform.application.entitlement import PlanEntitlementService
from dw_platform.application.hierarchy import HierarchyService
from dw_platform.application.idempotency import HttpIdempotency
from dw_platform.application.identity_bootstrap import IdentityBootstrapPort
from dw_platform.application.membership_admin import (
    GrantMembershipHandler,
    RevokeMembershipHandler,
)
from dw_platform.application.notifications import NotificationService
from dw_platform.application.ports import (
    AccessContextFactoryPort,
    ApprovalPayloadMask,
    FeedbackAttachmentStoragePort,
    PlatformUnitOfWorkFactory,
    TokenVerifierPort,
    WorkspaceDirectoryPort,
)
from dw_platform.application.provisioning import ProvisioningService
from dw_platform.application.separation_of_duties import SeparationOfDutiesService
from dw_platform.application.support_access import (
    StaffGrantsListPort,
    SupportAccessAuditPort,
    SupportAccessContextFactory,
    SupportGrantService,
    SupportScopeCatalog,
)
from dw_platform.application.tenant_members import TenantMembersService
from dw_platform.application.work_queue import WorkQueue


@dataclass(frozen=True)
class RuntimeSeam:
    """The plug-in kit a bounded context is wired with.

    A context's ``register_*`` function takes this, registers its graphs on
    ``graphs``, its tools on ``tools``/``tool_specs``, loads its worker YAML on
    ``workers``, and builds its own adapters from ``session_factory``, ``clock``
    and ``ids``. Nothing in here is context-specific, which is the point: the
    same object serves every context and none of them appear in this package.
    """

    session_factory: async_sessionmaker[AsyncSession]
    clock: UtcClock
    ids: IdGenerator
    telemetry: TelemetryPort
    profiles: ModelProfileRegistry
    prompts: PromptRegistry
    copy: RuntimeCopy
    gateway: RoutingModelGateway
    # ``None`` when no tool-calling provider is configured: a context that needs
    # one registers nothing rather than registering a graph that cannot run.
    chat_models: ChatModelFactory | None
    usage_meter: LangchainUsageMeter
    # The process's one per-run spend ledger. A context building an `AgentSpec`
    # passes THIS one, never a new `RunBudgetLedger()`: the runner frees entries
    # in this instance, so spend recorded anywhere else is never bounded against
    # the gateway's and never freed.
    budget: RunBudgetLedger
    tools: ToolRegistry
    tool_executor: ToolExecutor
    tool_specs: ToolSpecRegistry
    toolsets: ToolsetRegistry
    graphs: GraphRegistry
    workers: WorkerRegistry
    knowledge: KnowledgeGateway
    memory: MemoryService


@dataclass
class ApiContainer:
    """Wired dependencies for the API process."""

    settings: ApiSettings
    engine: AsyncEngine | None
    health_service: HealthService
    token_verifier: TokenVerifierPort | None
    access_context_factory: AccessContextFactoryPort | None
    identity_bootstrap: IdentityBootstrapPort | None
    uow_factory: PlatformUnitOfWorkFactory | None
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService

    run_store: SqlWorkerRunStore | None = None
    # Holds one LISTEN connection for the process; started and stopped by the
    # app's lifespan, never by a request.
    run_events: RunStateListener | None = None
    runner: LangGraphWorkflowRunner | None = None
    approval_flow: ApproveAndResumeService | None = None
    # Opening an approval: the view receipt and, when asked, the code a
    # decision on Zalo needs (ADR 0007). Wired with `approval_flow`.
    approval_views: ApprovalViewService | None = None

    knowledge_gateway: KnowledgeGateway | None = None
    ingest_job_store: IngestJobStore | None = None
    object_storage: ObjectStoragePort | None = None
    memory_service: MemoryService | None = None
    tool_registry: ToolRegistry | None = None

    # Who works in this workspace — what turns an owner id into a person.
    workspace_directory: WorkspaceDirectoryPort | None = None
    grant_membership: GrantMembershipHandler | None = None
    revoke_membership: RevokeMembershipHandler | None = None
    tenant_members: TenantMembersService | None = None
    admin_console: AdminConsoleService | None = None
    hierarchy: HierarchyService | None = None
    separation_of_duties: SeparationOfDutiesService | None = None
    # Digital Workers (digital-worker R1, R2): wired with the agent runtime,
    # whose tool register a DW's `allowed_tools` is checked against.
    digital_workers: DigitalWorkerService | None = None
    # The queue people and DWs share (digital-worker R3, R4); Postgres only.
    work_queue: WorkQueue | None = None
    # Fields of an approval type's payload only some readers see, by type
    # (digital-worker R5.6: a `dw.decision`'s proposal).
    approval_masks: dict[str, ApprovalPayloadMask] = field(default_factory=dict)
    notifications: NotificationService | None = None
    # Customer-granted support access (ADR 0024). A context registers its
    # grantable scope sets and resource describers on the catalog at the seam
    # in `wiring.py`; `build_container` freezes it once wiring is done.
    support_catalog: SupportScopeCatalog = field(default_factory=SupportScopeCatalog)
    support_grants: SupportGrantService | None = None
    # The staff side (ticket 02): the support context built from a grant, its
    # `support.access` trail, and "my grants".
    support_access: SupportAccessContextFactory | None = None
    support_access_audit: SupportAccessAuditPort | None = None
    staff_grants: StaffGrantsListPort | None = None
    # (method, path template) a support context may reach; `wiring.py`'s
    # SUPPORT_ALLOWED_ROUTES. Empty refuses every support request.
    support_allowed_routes: frozenset[tuple[str, str]] = frozenset()
    # The signed-in user's own Zalo link. ``None`` unless the bot token and the
    # link secret are both set, and then /api/v1/zalo/* is not mounted.
    zalo_linking: ZaloLinking | None = None
    # The workspace the signed-in user's Zalo commands act in. Wired with
    # ``zalo_linking`` and ``None`` without it, like the routes that read it.
    channel_preferences: ChannelPreferencesPort | None = None
    # Where the Zalo webhook queues an accepted update for the worker. ``None``
    # unless ``settings.zalo_webhook_enabled``, and then the route is not mounted.
    zalo_webhook_inbox: InboundUpdateInboxPort | None = None
    cache: CachePort | None = None
    # Dedicated to the readiness probe — the runtime's own retrieval/memory
    # clients are built (and disposed) deeper inside `build_runtime`, only
    # when the full runtime is wired. Readiness must answer regardless, so
    # this one is constructed and closed independently.
    qdrant_client: AsyncQdrantClient | None = None
    feedback_storage: FeedbackAttachmentStoragePort | None = None
    # Replay protection for mutating routes that carry an `Idempotency-Key`.
    # ``None`` without a database, where the routes that use it are not mounted
    # either — and where the dependency degrades to a pass-through rather than
    # refusing a header the API advertises.
    idempotency: HttpIdempotency | None = None
    # The effect half of an idempotent request (app-standards R2.16).
    effect_keys: EffectKeyPort | None = None

    # Platform provisioning: absent unless a provisioner connection is set —
    # then /api/v1/platform/* is mounted. Its engine is a second role with no
    # grant on any business schema, disposed on shutdown.
    provisioning: ProvisioningService | None = None
    provisioner_engine: AsyncEngine | None = None

    # The plug-in kit. ``None`` on a host with no database or no object storage,
    # where no context could be wired anyway.
    runtime: RuntimeSeam | None = None

    _extra_engines: list[AsyncEngine] = field(default_factory=list)

    def run_context_for(self, context: AccessContext, run_id: uuid.UUID) -> RunContext:
        return RunContext(
            run_id=run_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.principal_id,
            worker_id="lookup",
            worker_version="0.0.0",
            channel="web",
            plan_id=context.plan_id,
            roles=context.roles,
            scopes=context.scopes,
            clearance=context.clearance,
            # Carry the record-visibility roll-up into the run so a context's
            # reads narrow to the same subtree the REST path does.
            record_visibility=context.record_visibility,
            visible_owners=context.visible_owners,
            trace_id=f"api-{run_id.hex[:12]}",
        )

    async def shutdown(self) -> None:
        if self.run_events is not None:
            await self.run_events.stop()
        if self.qdrant_client is not None:
            await self.qdrant_client.close()
        for engine in (self.engine, self.provisioner_engine, *self._extra_engines):
            if engine is not None:
                await engine.dispose()
