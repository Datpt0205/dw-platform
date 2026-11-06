"""Worker composition root: wires the knowledge ingest pipeline and the
wf-lite runtime from settings.

Mirrors the API's knowledge wiring but on the worker side, where the parse
layer lives. Only the composition root imports concrete adapters
(Clean/Hexagonal rule); consumers receive already-wired ports.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.model_stack import (
    ModelProviderConfig,
    ModelStack,
    build_model_resolver,
    build_model_stack,
)
from dw_agent_runtime.adapters.pack_tools import build_leadcare_tools, register_leadcare_tools
from dw_agent_runtime.adapters.release_manifest import read_release_manifest_ref
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.run_waits import SqlRunWaits
from dw_agent_runtime.adapters.span_step_recorder import TelemetryStepRecorder
from dw_agent_runtime.adapters.tool_claims import SqlToolClaims
from dw_agent_runtime.adapters.wflite_host import (
    build_run_starter,
    build_send_floor,
    build_tool_executor,
    build_wflite_ports,
    load_handoff_copy,
    register_workflows,
)
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.resolver import StaticPlanModelProfiles
from dw_agent_runtime.model.run_policy import load_worker_run_policy
from dw_agent_runtime.ports import BindingReviewPort, LimitsPort, RunControlPort
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tool_specs import ToolSpecRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.wflite.catalog import PackCatalog, ShippedToolSpecs
from dw_agent_runtime.wflite.node_wrapper import StudioNodePorts, StudioRunPorts, StudioWaits
from dw_agent_runtime.wflite.registry import build_node_registry
from dw_agent_runtime.wflite.starter import WorkflowRunStarter
from dw_agent_runtime.wflite.waits import WorkQueueRunWaits
from dw_connectors.egress import EgressClient, NoCatalogueHosts
from dw_kernel.ports import IdGenerator, SystemClock, UtcClock, Uuid7Generator
from dw_kernel.residency import Destination, ResidencyGate
from dw_knowledge.adapters.api_parsers import (
    DeepgramTranscriptParser,
    GatewayFileParser,
    PlaintextAttachmentParser,
)
from dw_knowledge.adapters.composite_parser import CompositeParser
from dw_knowledge.adapters.embedding_factory import build_metered_embeddings
from dw_knowledge.attachment_policy import load_attachment_policy
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ingest_jobs import IngestJobQueue, IngestJobStore
from dw_knowledge.metering import MeteredEmbeddings
from dw_knowledge.ports import (
    DocumentParserPort,
    ObjectStoragePort,
    UsageMeterPort,
    VectorIndexPort,
)
from dw_observability.telemetry import TelemetryPort
from dw_platform.adapters.persistence.connections_repo import SqlConnectionStore
from dw_platform.adapters.persistence.egress_allowlist_repo import SqlAllowedHosts
from dw_platform.adapters.persistence.held_run_alerts import SqlHeldRunAlerts
from dw_platform.adapters.persistence.live_scopes import SqlLiveScopes
from dw_platform.adapters.persistence.plan_model_profiles import (
    CachingPlanModelProfiles,
    SqlPlanModelProfiles,
)
from dw_platform.adapters.persistence.residency import SqlRouteClasses
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.connections import ConnectionUsability, NoConnectorCatalog
from dw_platform.application.work_queue import WorkQueue
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.cel.engine import CelCppEngine
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestEngines
from dw_studio.core.adapters.studio_runs import SqlStudioRunStore
from dw_studio.core.application.bindings import BindingStatus, platform_binding_types
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import platform_kinds
from dw_studio.lifecycle.adapters.store import SqlLifecycleStore
from dw_studio.lifecycle.application.service import LifecycleService
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.records.adapters.definition_store import object_store_of
from dw_studio.workflows.adapters.triggers import NoTriggerSubscriptions
from dw_usage.adapters.limits_sql import SqlLimits
from dw_usage.adapters.metering import SqlUsageMeter
from dw_usage.adapters.price_book_file import enforce_price_coverage, load_price_book
from dw_usage.adapters.sql import SqlUsageLedger
from dw_usage.application.recorder import LedgerUsageRecorder
from dw_worker.settings import WorkerSettings

if TYPE_CHECKING:
    from minio import Minio

    from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

# The image sets DW_REPO_ROOT=/app; outside a container the checkout root is
# four levels up from this file.
REPO_ROOT = Path(os.environ.get("DW_REPO_ROOT", str(Path(__file__).resolve().parents[4])))
CONFIGS = REPO_ROOT / "configs"
ATTACHMENT_POLICY = "attachment_ingest@1.1.0.yaml"
WORKER_RUN_POLICY = "worker_runs@1.0.0.yaml"
WFLITE_HANDOFF_COPY = "wflite_handoff.yaml"
# The platform's copy, the API's pin (`dw_api.bootstrap.paths.RUNTIME_COPY_CONFIG`).
RUNTIME_COPY = "runtime@1.6.0.yaml"


@dataclass
class IngestComponents:
    engine: AsyncEngine
    gateway: KnowledgeGateway
    job_store: IngestJobStore
    job_queue: IngestJobQueue
    parser: DocumentParserPort
    object_storage: ObjectStoragePort
    # The limits an ingestion's operation lease is taken from, before the file
    # is read (usage-and-limits R6.2): the gateway's embedder spends it.
    limits: LimitsPort


def _build_minio_client(settings: WorkerSettings) -> Minio:
    from minio import Minio

    assert settings.s3_endpoint_url is not None
    endpoint = settings.s3_endpoint_url.replace("http://", "").replace("https://", "")
    return Minio(
        endpoint,
        access_key=settings.s3_access_key or "",
        secret_key=settings.s3_secret_key or "",
        secure=settings.s3_endpoint_url.startswith("https://"),
    )


def build_object_storage(settings: WorkerSettings) -> ObjectStoragePort:
    """Public: a context's own lane may stage artifacts in the same bucket."""
    from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

    return MinioObjectStorageAdapter(
        client=_build_minio_client(settings), bucket=settings.s3_bucket
    )


def build_export_bucket(settings: WorkerSettings) -> MinioObjectStorageAdapter:
    """Tenant offboarding's export destination — the `dw-exports` bucket
    already used elsewhere, not a new one made for this feature. The adapter
    itself, not `ObjectStoragePort`: the lane uploads its bundle from a file in
    parts (`put_stream`), which no other caller of the port does."""
    from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

    return MinioObjectStorageAdapter(
        client=_build_minio_client(settings), bucket=settings.s3_bucket_exports
    )


def build_feedback_bucket(settings: WorkerSettings) -> ObjectStoragePort:
    """The same bucket `dw_api`'s feedback attachments live in — offboarding
    reads and deletes from it, `dw_knowledge`'s generic adapter is reused
    rather than depending on `dw_api`'s own (see
    `dw_worker.consumers.offboarding.BucketPort`'s docstring)."""
    from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

    return MinioObjectStorageAdapter(
        client=_build_minio_client(settings), bucket=settings.feedback_bucket
    )


def build_residency_gate(
    sessions: async_sessionmaker[AsyncSession], telemetry: TelemetryPort | None = None
) -> ResidencyGate:
    """The data route gate (compliance-pdpl R2.3): the class of a call outside
    a run read under RLS on `sessions`, a run's from what it pinned."""
    return ResidencyGate(classes=SqlRouteClasses(sessions), telemetry=telemetry)


def build_usage_meter(
    sessions: async_sessionmaker[AsyncSession], *, clock: UtcClock
) -> SqlUsageMeter:
    """The meter an embedding spends through (usage-and-limits R6.1, R6.2): the
    lease in force, on the limits, the ledger and the book every chat call of
    this process uses."""
    return SqlUsageMeter(
        limits=SqlLimits(sessions, clock=clock, ids=Uuid7Generator(clock)),
        ledger=SqlUsageLedger(sessions),
        pricing=load_price_book(),
        clock=clock,
    )


def build_embeddings(
    settings: WorkerSettings, residency: ResidencyGate, meter: UsageMeterPort
) -> MeteredEmbeddings:
    """Public because two lanes need it: knowledge ingestion, and the memory
    index. Built by `dw_knowledge`'s one builder, the one the API embeds
    questions with, so "which model embeds this deployment's text" has a
    single answer: the `embedding` route of the configured model profile, on
    the platform layer (an index has one width for every tenant). No run asks
    this resolver anything, so it lists no plan. Metered: every call held to
    the lease in force (usage-and-limits R6.1, R6.2).
    """
    models = build_model_resolver(
        model_provider_config(settings),
        profiles_dir=REPO_ROOT / "configs" / "models",
        plans=StaticPlanModelProfiles({}),
    )
    return build_metered_embeddings(
        settings.embedding_provider,
        models.platform_profile(settings.model_profile).embedding,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        profile_id=settings.model_profile,
        residency=residency,
        meter=meter,
    )


def build_vector_index(settings: WorkerSettings) -> VectorIndexPort:
    if settings.qdrant_url:
        from qdrant_client import AsyncQdrantClient

        from dw_knowledge.adapters.qdrant_index import QdrantVectorIndexAdapter

        return QdrantVectorIndexAdapter(
            client=AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key),
            collection=settings.qdrant_collection,
        )
    from dw_knowledge.adapters.memory_index import InMemoryVectorIndexAdapter

    return InMemoryVectorIndexAdapter()


def build_parser(settings: WorkerSettings, residency: ResidencyGate) -> DocumentParserPort:
    """Route by extension: plaintext in process, everything else to an API.

    Public because a context's own lane reads PDFs through the same parser: a
    report an agent fetches and the same report a person uploads must chunk
    identically, or a search returns two shapes of one document.

    Order matters only in that each parser answers `supports` for its own kinds;
    the policy is the single place that decides which kind a file is.
    """
    policy = load_attachment_policy(REPO_ROOT / "configs" / "policies" / ATTACHMENT_POLICY)
    parsers: list[DocumentParserPort] = [PlaintextAttachmentParser(policy=policy)]

    if settings.openai_base_url and settings.openai_api_key:
        parsers.append(
            GatewayFileParser(
                base_url=settings.openai_base_url,
                api_key=settings.openai_api_key,
                model=settings.extraction_model,
                policy=policy,
                residency=residency,
                destination=Destination(
                    name="document_extraction",
                    data_location=settings.extraction_data_location,
                    processor=settings.extraction_processor,
                ),
            )
        )
    if settings.deepgram_api_key:
        parsers.append(
            DeepgramTranscriptParser(
                api_key=settings.deepgram_api_key,
                policy=policy,
                residency=residency,
                destination=Destination(
                    name="transcription",
                    data_location=settings.transcription_data_location,
                    processor=settings.transcription_processor,
                ),
            )
        )
    # A missing key is not silently a missing format: CompositeParser raises
    # "no parser supports ..." and the job records that as its error, which is
    # what the upload status shows.
    return CompositeParser(parsers=parsers)


def build_ingest_components(settings: WorkerSettings) -> IngestComponents | None:
    """Return wired ingest components, or ``None`` if infra is not configured."""
    if not (settings.database_url and settings.s3_endpoint_url):
        return None

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    clock = SystemClock()
    id_generator = Uuid7Generator()
    storage = build_object_storage(settings)
    residency = build_residency_gate(session_factory)
    meter = build_usage_meter(session_factory, clock=clock)

    gateway = KnowledgeGateway(
        session_factory=session_factory,
        vector_index=build_vector_index(settings),
        embeddings=build_embeddings(settings, residency, meter),
        object_storage=storage,
        clock=clock,
        id_generator=id_generator,
    )
    job_store = IngestJobStore(
        session_factory=session_factory,
        clock=clock,
        id_generator=id_generator,
        retry_backoff_seconds=settings.ingest_retry_backoff_seconds,
    )
    return IngestComponents(
        engine=engine,
        gateway=gateway,
        job_store=job_store,
        job_queue=IngestJobQueue(session_factory=session_factory, clock=clock),
        parser=build_parser(settings, residency),
        object_storage=storage,
        limits=meter.limits,
    )


# The recorded answers the mock provider replays, the directory the API reads.
MOCK_MODEL_FIXTURES = REPO_ROOT / "evals" / "fixtures" / "mock_model"


def model_provider_config(settings: WorkerSettings) -> ModelProviderConfig:
    """This process's settings, read for the model builder the API uses too."""
    return ModelProviderConfig(
        provider=settings.model_provider,
        model_profile=settings.model_profile,
        profile=settings.profile,
        is_deployed=settings.is_deployed,
        openai_api_key=settings.openai_api_key or None,
        openai_base_url=settings.openai_base_url or None,
        openai_structured_mode=settings.openai_structured_mode,
        openai_strict_schema=settings.openai_strict_schema,
        outbound_allowed_hosts=tuple(settings.outbound_allowed_hosts),
    )


def build_model_stack_for(
    settings: WorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    clock: UtcClock,
    telemetry: TelemetryPort,
    run_control: RunControlPort,
) -> ModelStack:
    """The worker's model gateway, limits and usage recorders, built by the
    same `build_model_stack` the API builds its own with: the profiles, the
    shipped prompts, the limits on PostgreSQL. A chat command's model call
    therefore asks the same leases as a request's, priced by the same book and
    written to the same usage ledger (usage-and-limits R2.1, R3.1, R5.2); a
    deployed profile with a paid route the book does not price refuses to
    start (R2.3)."""
    # The one resolver every model door of this process asks (model-connections
    # R1.1), filtered by the plan catalogue, and reading a Studio run's models
    # from the engine its manifest pinned (R1.4): this process takes Studio
    # runs (workflow-engine/04; model-connections/02 MEDIUM (a)).
    models = build_model_resolver(
        model_provider_config(settings),
        profiles_dir=REPO_ROOT / "configs" / "models",
        plans=CachingPlanModelProfiles(SqlPlanModelProfiles(sessions), clock),
        pinned=SqlRunManifestEngines(sessions),
    )
    prompts = PromptRegistry()
    prompts.load_directory(REPO_ROOT / "configs" / "prompts")
    price_book = load_price_book()
    enforce_price_coverage(
        price_book,
        REPO_ROOT / "configs" / "models",
        at=clock.now(),
        is_deployed=settings.is_deployed,
    )
    return build_model_stack(
        model_provider_config(settings),
        models=models,
        prompts=prompts,
        session_factory=sessions,
        clock=clock,
        telemetry=telemetry,
        mock_fixtures_dir=MOCK_MODEL_FIXTURES,
        pricing=price_book,
        ledger=LedgerUsageRecorder(
            ledger=SqlUsageLedger(sessions),
            ids=Uuid7Generator(clock),
            clock=clock,
            telemetry=telemetry,
            price_book_version=price_book.version,
        ),
        run_control=run_control,
        residency=build_residency_gate(sessions, telemetry),
        # The process's one limits port, read in each transaction (R4.8).
        limits=SqlLimits(sessions, clock=clock, ids=Uuid7Generator(clock), telemetry=telemetry),
    )


@dataclass(frozen=True)
class WfLiteRuntime:
    """The workflows this process runs (wf-lite R6): the runner the `dw_work`
    lane starts runs on and the `dw_timers` lane resumes them on, and the tool
    registry a context registers its tools on, at the marked seam in
    `dw_worker.main`, as it does on the API's."""

    runner: LangGraphWorkflowRunner
    starter: WorkflowRunStarter
    tools: ToolRegistry
    # The process's one limits port, which the Studio runner admits with too
    # (workflow-engine/04).
    limits: LimitsPort


def build_wflite_runtime(
    settings: WorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    packs: PackCatalog,
    queue: WorkQueue,
    clock: UtcClock,
    ids: IdGenerator,
    telemetry: TelemetryPort,
    run_control: RunControlPort,
) -> WfLiteRuntime:
    """The runner, executor and nodes the API builds for the same graphs
    (`dw_agent_runtime.adapters.wflite_host`): a run this process pauses on an
    approval resumes there, and one the API's decision runs on to a timer
    resumes here, from the same checkpoint.

    No usage meter: it bills an agent loop's LangChain calls, and a workflow's
    model calls go through the gateway, which records its own usage into the
    usage ledger, each call settled into its run's lease."""
    stack = build_model_stack_for(
        settings, sessions, clock=clock, telemetry=telemetry, run_control=run_control
    )
    tools = ToolRegistry()
    approval_policy = AutonomyApprovalPolicy()
    executor = build_tool_executor(
        tools=tools,
        session_factory=sessions,
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        approval_policy=approval_policy,
        telemetry=telemetry,
        clock=clock,
        ids=ids,
        send_admission=build_send_floor(
            session_factory=sessions,
            policies=CONFIGS / "policies",
            signing_secret=settings.unsubscribe_signing_secret.get_secret_value(),
            web_url=settings.public_web_url,
            clock=clock,
            ids=ids,
        ),
        run_control=run_control,
    )
    # The Marketing pack's tools, as the API registers them (leadcare R3).
    tool_specs = ToolSpecRegistry(copy=load_runtime_copy(CONFIGS / "copy" / RUNTIME_COPY))
    tool_specs.load_directory(CONFIGS / "tools")
    register_leadcare_tools(
        tools,
        tool_specs,
        build_leadcare_tools(
            session_factory=sessions,
            queue=queue,
            clock=clock,
            handoffs=CONFIGS / "copy" / "leadcare_handoff.yaml",
            is_deployed=settings.is_deployed,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            mailbox_url=settings.mailbox_api_url,
        ),
    )
    graphs = GraphRegistry()
    workers = WorkerRegistry(graph_registry=graphs)
    # The packs' graphs now; a tenant's published version on its run's first
    # use, at its start or its timer's resume (wf-ai R6.5).
    tenant_graphs = register_workflows(
        packs,
        build_wflite_ports(
            session_factory=sessions,
            gateway=stack.gateway,
            executor=executor,
            tools=tools,
            queue=queue,
            recommendations=load_handoff_copy(CONFIGS / "copy" / WFLITE_HANDOFF_COPY),
            clock=clock,
            ids=ids,
        ),
        graphs=graphs,
        workers=workers,
        session_factory=sessions,
    )
    policy = load_worker_run_policy(CONFIGS / "policies" / WORKER_RUN_POLICY)
    runner = LangGraphWorkflowRunner(
        worker_registry=workers,
        graph_registry=graphs,
        checkpoint_saver=SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
        run_store=SqlWorkerRunStore(
            sessions, stale_run_after_seconds=policy.stale_run_after_seconds
        ),
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        clock=clock,
        id_generator=ids,
        # The same limits the API's runner admits a run with: the plan's caps
        # and the company's policies, read where the run begins (R4.1, R5.1).
        limits=stack.limits,
        approval_policy=approval_policy,
        run_control=run_control,
        release_manifest_ref=read_release_manifest_ref(REPO_ROOT),
        telemetry=telemetry,
        run_waits=WorkQueueRunWaits(queue),
        run_graphs=tenant_graphs,
    )
    return WfLiteRuntime(
        runner=runner,
        starter=build_run_starter(
            catalog=packs, session_factory=sessions, tools=tools, runner=runner
        ),
        tools=tools,
        limits=stack.limits,
    )


def build_studio_runner(
    sessions: async_sessionmaker[AsyncSession],
    *,
    limits: LimitsPort,
    run_control: RunControlPort,
    binding_review: BindingReviewPort,
    clock: UtcClock,
    ids: IdGenerator,
    telemetry: TelemetryPort,
) -> LangGraphWorkflowRunner:
    """The runner the `studio_runs` lane runs Studio runs on (workflow-engine
    R5.1): the one step registry the API validates against, the run store and
    checkpoint saver fenced by the lane's claim, the process's limits and
    switches, the one `ExpressionEngine` for `outcomes[]`, and who is told of a
    held run. No effect door is wired yet: each joins with the ticket that
    builds it (workflow-nodes 04-08), and a step that needs one ends its run
    `effect_door_unwired` until then, never a send through a guess."""
    graphs = GraphRegistry()
    policy = load_worker_run_policy(CONFIGS / "policies" / WORKER_RUN_POLICY)
    nodes = StudioNodePorts(
        doors={},
        claims=SqlToolClaims(sessions),
        run_control=run_control,
        runs=SqlStudioRunStore(sessions, ids, clock),
        recorder=TelemetryStepRecorder(telemetry, clock),
        telemetry=telemetry,
        clock=clock,
        # A waiting step's wait, in a transaction of the run's tenant
        # (workflow-engine R6.1).
        waits=StudioWaits(SqlPlatformUnitOfWorkFactory(sessions), SqlRunWaits(ids)),
    )
    return LangGraphWorkflowRunner(
        worker_registry=WorkerRegistry(graph_registry=graphs),
        graph_registry=graphs,
        checkpoint_saver=SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
        run_store=SqlWorkerRunStore(
            sessions, stale_run_after_seconds=policy.stale_run_after_seconds
        ),
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        clock=clock,
        id_generator=ids,
        limits=limits,
        approval_policy=AutonomyApprovalPolicy(),
        run_control=run_control,
        release_manifest_ref=read_release_manifest_ref(REPO_ROOT),
        telemetry=telemetry,
        studio=StudioRunPorts(
            nodes=nodes,
            registry=build_node_registry(),
            binding_review=binding_review,
            alerts=SqlHeldRunAlerts(sessions),
            expressions=CelCppEngine(),
            # The run's principal's scopes now, at every take (R6.12).
            live_scopes=SqlLiveScopes(sessions),
        ),
    )


def build_studio_kinds(
    *, clock: UtcClock, ids: IdGenerator, kinds: Sequence[ArtifactKindEntry] | None = None
) -> ArtifactKindRegistry:
    """The worker's `ArtifactKindRegistry`: exactly `platform_kinds(...)`, built
    as the API's `build_studio` builds it, so a publish hook runs here as it
    would there (agent-lifecycle ticket 04 step 0). `kinds=` is a test's door,
    never settings or the environment (tenant-config R2.15)."""
    if kinds is not None:
        return ArtifactKindRegistry(kinds)
    return ArtifactKindRegistry(
        platform_kinds(
            object_store_of,
            clock=clock,
            ids=ids,
            nodes=build_node_registry(),
            tools=ShippedToolSpecs.load(CONFIGS / "tools"),
            triggers=NoTriggerSubscriptions(),
            boundaries=SqlActorBoundaries(),
            expressions=CelCppEngine(),
        )
    )


def build_studio_lifecycle(
    sessions: async_sessionmaker[AsyncSession],
    registry: ArtifactKindRegistry,
    *,
    run_control: RunControlPort,
    clock: UtcClock,
    ids: IdGenerator,
) -> LifecycleService:
    """The one writer of a version's stage, as the publish handler needs it
    (agent-lifecycle R5.5): the process's run controls and the bindings check
    over the same connection rule as the API's (`NoConnectorCatalog`). The
    worker submits nothing, so no per-kind submit check is wired."""
    store = SqlArtifactStore(sessions, ids)
    usability = ConnectionUsability(
        store=SqlConnectionStore(sessions), catalog=NoConnectorCatalog()
    )
    return LifecycleService(
        SqlLifecycleStore(store),
        ArtifactService(store, registry, clock, ids),
        run_control,
        {},
        clock,
        bindings=BindingStatus(store, platform_binding_types(usability)),
    )


def build_egress_client(
    settings: WorkerSettings,
    session_factory: async_sessionmaker[AsyncSession],
    telemetry: TelemetryPort,
) -> EgressClient:
    """The egress client as the worker composes it (connections-and-vault R3;
    ADR-0115 decision 6): `allow_private` and `require_https` from the profile
    and from nothing else, as the API's `build_egress_client` sets them. The
    send lanes of ticket 05 take it from here."""
    return EgressClient(
        allowed_hosts=SqlAllowedHosts(session_factory),
        catalogue=NoCatalogueHosts(),
        allow_private=not settings.is_deployed,
        require_https=settings.is_deployed,
        telemetry=telemetry,
    )
