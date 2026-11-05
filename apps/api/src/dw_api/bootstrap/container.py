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
from dw_agent_runtime.adapters.run_control import SqlRunControl
from dw_agent_runtime.adapters.run_events import RunStateListener
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.wflite_host import RunTrailReader
from dw_agent_runtime.approval_codes import ApprovalViewService
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.model.gateway import RoutingModelGateway, UsageRecorderPort
from dw_agent_runtime.model.pricing import PricingPort
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import ModelResolver
from dw_agent_runtime.ports import LimitsPort
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tool_specs import ToolSpecRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.toolsets import ToolsetRegistry
from dw_agent_runtime.wflite.assistant import WorkflowAssistant
from dw_agent_runtime.wflite.drafts import WorkflowDrafts
from dw_agent_runtime.wflite.outline import WorkflowOutlineReader
from dw_agent_runtime.wflite.publish import WorkflowPublishing
from dw_api.bootstrap.studio import StudioContainer
from dw_api.health import HealthService
from dw_api.settings import ApiSettings
from dw_connectors.adapters.zalo_link import ZaloLinking
from dw_connectors.egress import EgressPort
from dw_connectors.inbound import InboundUpdateInboxPort
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.residency import ResidencyGate
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
from dw_platform.application.connection_admin import ConnectionService
from dw_platform.application.connections import ConnectionUsability
from dw_platform.application.control_switches import ControlSwitchService, PlatformFreezeService
from dw_platform.application.digital_workers import DigitalWorkerService
from dw_platform.application.dw_autonomy import DwAutonomyService
from dw_platform.application.effect_keys import EffectKeyPort
from dw_platform.application.egress_allowlist import EgressAllowlistService
from dw_platform.application.entitlement import PlanEntitlementService
from dw_platform.application.hierarchy import HierarchyService
from dw_platform.application.idempotency import HttpIdempotency
from dw_platform.application.identity_bootstrap import IdentityBootstrapPort
from dw_platform.application.intake import IntakeKeyReader, LeadIntake
from dw_platform.application.marketing_send import UnsubscribeService
from dw_platform.application.membership_admin import (
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
from dw_platform.application.rate_limit import RateLimiterPort
from dw_platform.application.role_admin import RoleAdminService
from dw_platform.application.role_assignments import RoleAssignmentService
from dw_platform.application.scorecard import ScorecardService
from dw_platform.application.secrets import SecretStore
from dw_platform.application.separation_of_duties import SeparationOfDutiesService
from dw_platform.application.service_principals import (
    ServicePrincipalBindingGuard,
    ServicePrincipalService,
)
from dw_platform.application.support_access import (
    StaffGrantsListPort,
    SupportAccessAuditPort,
    SupportAccessContextFactory,
    SupportGrantService,
    SupportScopeCatalog,
)
from dw_platform.application.tenant_members import TenantMembersService
from dw_platform.application.work_queue import WorkQueue
from dw_usage.application.limits import LimitPolicyService
from dw_usage.application.reads import UsageReads


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
    # The one answer to which model route a run's call takes
    # (model-connections R1.1): an `AgentSpec` takes it as `models`.
    models: ModelResolver
    prompts: PromptRegistry
    copy: RuntimeCopy
    gateway: RoutingModelGateway
    # ``None`` when no tool-calling provider is configured: a context that needs
    # one registers nothing rather than registering a graph that cannot run.
    chat_models: ChatModelFactory | None
    usage_meter: LangchainUsageMeter
    # The process's one limits port (usage-and-limits R5): an `AgentSpec` takes
    # it as `limits`, and `usage_recorder` as its `usage_recorder`, whose write
    # of a permitted call settles it into the run's lease.
    limits: LimitsPort
    usage_recorder: UsageRecorderPort
    # The price book every call is priced by (usage-and-limits R2.1); a context
    # building an `AgentSpec` passes this one.
    pricing: PricingPort
    # The process's one residency gate (compliance-pdpl R2.3): an `AgentSpec`
    # takes it as `residency`, and a context's own model door asks it.
    residency: ResidencyGate
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
    # Built past the database gate, over `platform.plan_limits`: no database, no
    # plan catalogue, so nothing answers a plan's limits (usage-and-limits 01).
    entitlement: PlanEntitlementService | None = None

    run_store: SqlWorkerRunStore | None = None
    # A run's usage and the company's usage summary (usage-and-limits R3.5,
    # R3.6), over the usage ledger; past the database gate.
    usage: UsageReads | None = None
    limits: LimitPolicyService | None = None
    # Holds one LISTEN connection for the process; started and stopped by the
    # app's lifespan, never by a request.
    run_events: RunStateListener | None = None
    # The freeze and the kill, asked at every door of this process (agent-
    # lifecycle R7); past the database gate. Listens from its first door on
    # and stops on shutdown.
    run_control: SqlRunControl | None = None
    # The company's freeze, set by one person and lifted by two (R7.10).
    control_switches: ControlSwitchService | None = None
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
    revoke_membership: RevokeMembershipHandler | None = None
    # A company's roles and who holds them (tenant-rbac ticket 03).
    role_admin: RoleAdminService | None = None
    role_assignments: RoleAssignmentService | None = None
    tenant_members: TenantMembersService | None = None
    admin_console: AdminConsoleService | None = None
    hierarchy: HierarchyService | None = None
    separation_of_duties: SeparationOfDutiesService | None = None
    # A company's service accounts (org-and-principals R6), and the one guard of
    # who may bind one as a run's principal: a context that binds declares its
    # own Protocol and is handed this object.
    service_principals: ServicePrincipalService | None = None
    service_principal_binding: ServicePrincipalBindingGuard | None = None
    # Digital Workers (digital-worker R1, R2): wired with the agent runtime,
    # whose tool register a DW's `allowed_tools` is checked against.
    digital_workers: DigitalWorkerService | None = None
    # A DW's scorecard and the raising and lowering of its earned levels
    # (digital-worker R7, R8); wired with `digital_workers`.
    dw_scorecard: ScorecardService | None = None
    dw_autonomy: DwAutonomyService | None = None
    # A DW's pinned workflow as its page draws it, with each decision class's
    # level and mode (digital-worker R9.2); wired with `digital_workers`.
    dw_workflows: WorkflowOutlineReader | None = None
    # The assistant that edits a DW's template workflow (wf-ai R1-R5); with
    # the runtime, whose model stack it calls through.
    workflow_assistant: WorkflowAssistant | None = None
    # A DW's workflow draft and its dry run (wf-ai R6.1, R6.2); with the runtime.
    workflow_drafts: WorkflowDrafts | None = None
    # Submitting and withdrawing a draft's publication (wf-ai R6.3-R6.10).
    workflow_publishing: WorkflowPublishing | None = None
    # The queue people and DWs share (digital-worker R3, R4); Postgres only.
    work_queue: WorkQueue | None = None
    # A work item's `trail`, read from its run (wf-lite R6.13); with the runtime.
    run_trails: RunTrailReader | None = None
    # The public opt-out door (ADR-0124 decision 5); None without a signing
    # secret, and the door answers 503.
    unsubscribe: UnsubscribeService | None = None
    # The signed lead intake and its key reader (leadcare R2); None without a
    # signing secret of 32 bytes, and the door answers 503.
    intake: LeadIntake | None = None
    intake_keys: IntakeKeyReader | None = None
    # Fields of an approval type's payload only some readers see, by type
    # (digital-worker R5.6: a `dw.decision`'s proposal).
    approval_masks: dict[str, ApprovalPayloadMask] = field(default_factory=dict)
    notifications: NotificationService | None = None
    # The credential broker (connections-and-vault R1); Postgres only. Its key
    # service is built ahead of the database gate, so a wrong `DW_KMS_PROVIDER`
    # fails at startup either way. `connections` seals through it.
    secret_store: SecretStore | None = None
    # The shared connections of a workspace (connections-and-vault R5, R1.15);
    # Postgres only. Enabling one again needs the approval flow as well.
    connections: ConnectionService | None = None
    # The one rule on using a connection (ADR-0115 decision 2); Postgres only.
    # Its callers arrive with tenant-config/05 (binding review, run admission)
    # and ticket 05 (before each egress call), each through its own Protocol.
    connection_usability: ConnectionUsability | None = None
    # The company's Allowed hosts (connections-and-vault R3.8-R3.12, R3.18);
    # Postgres only. Deciding a request needs the approval flow as well.
    egress_allowlist: EgressAllowlistService | None = None
    # The one client of tenant-directed traffic (R3; ADR-0115 decision 6);
    # Postgres only. Ticket 05's connection test and SMTP send read it.
    egress: EgressPort | None = None
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
    # The routes the `platform_admin` bypass does not open (tenant-rbac R3.16),
    # as (method, path template): `ROLE_ROUTES_WITHOUT_BYPASS`, set where the
    # routers are mounted. Empty opens every route to the bypass as before.
    no_platform_bypass_routes: frozenset[tuple[str, str]] = frozenset()
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
    # The process's one limiter for per-company rate limits (usage-and-limits
    # R7): Data Hub's source limit and custom-objects' duplicate check take it
    # by injection. `build_container` always sets it; `None` only in a test
    # container that wires none.
    rate_limiter: RateLimiterPort | None = None
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
    # The operators' freezes, on the same provisioner engine (R7.4).
    platform_freezes: PlatformFreezeService | None = None
    provisioner_engine: AsyncEngine | None = None

    # The plug-in kit. ``None`` on a host with no database or no object storage,
    # where no context could be wired anyway.
    runtime: RuntimeSeam | None = None
    # Studio (ADR-0100 decision 6): ``None`` without a database, and then no
    # route under `/api/v1/studio` is mounted (studio-skeleton R6.4).
    studio: StudioContainer | None = None

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
        if self.run_control is not None:
            await self.run_control.close()
        if self.qdrant_client is not None:
            await self.qdrant_client.close()
        for engine in (self.engine, self.provisioner_engine, *self._extra_engines):
            if engine is not None:
                await engine.dispose()
