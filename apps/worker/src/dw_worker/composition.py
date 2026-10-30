"""Worker composition root: wires the knowledge ingest pipeline and the
wf-lite runtime from settings.

Mirrors the API's knowledge wiring but on the worker side, where the parse
layer lives. Only the composition root imports concrete adapters
(Clean/Hexagonal rule); consumers receive already-wired ports.
"""

from __future__ import annotations

import os
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
    build_model_stack,
)
from dw_agent_runtime.adapters.release_manifest import read_release_manifest_ref
from dw_agent_runtime.adapters.run_store import SqlWorkerRunStore
from dw_agent_runtime.adapters.spend_guard import SqlSpendGuardStore
from dw_agent_runtime.adapters.wflite_host import (
    build_run_starter,
    build_tool_executor,
    build_wflite_ports,
    load_handoff_copy,
    register_workflows,
)
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.model.run_policy import load_worker_run_policy
from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
from dw_agent_runtime.tools import ToolRegistry
from dw_agent_runtime.wflite.catalog import PackCatalog
from dw_agent_runtime.wflite.starter import WorkflowRunStarter
from dw_agent_runtime.wflite.waits import WorkQueueRunWaits
from dw_kernel.ports import IdGenerator, SystemClock, UtcClock, Uuid7Generator
from dw_knowledge.adapters.api_parsers import (
    DeepgramTranscriptParser,
    GatewayFileParser,
    PlaintextAttachmentParser,
)
from dw_knowledge.adapters.composite_parser import CompositeParser
from dw_knowledge.adapters.embedding_factory import build_embeddings as shared_build_embeddings
from dw_knowledge.attachment_policy import load_attachment_policy
from dw_knowledge.gateway import KnowledgeGateway
from dw_knowledge.ingest_jobs import IngestJobQueue, IngestJobStore
from dw_knowledge.ports import DocumentParserPort, EmbeddingPort, ObjectStoragePort, VectorIndexPort
from dw_observability.telemetry import TelemetryPort
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.application.entitlement import DEFAULT_PLANS, PlanEntitlementService
from dw_platform.application.work_queue import WorkQueue
from dw_worker.settings import WorkerSettings

if TYPE_CHECKING:
    from minio import Minio

# The image sets DW_REPO_ROOT=/app; outside a container the checkout root is
# four levels up from this file.
REPO_ROOT = Path(os.environ.get("DW_REPO_ROOT", str(Path(__file__).resolve().parents[4])))
CONFIGS = REPO_ROOT / "configs"
ATTACHMENT_POLICY = "attachment_ingest@1.1.0.yaml"
WORKER_RUN_POLICY = "worker_runs@1.0.0.yaml"
WFLITE_HANDOFF_COPY = "wflite_handoff.yaml"


@dataclass
class IngestComponents:
    engine: AsyncEngine
    gateway: KnowledgeGateway
    job_store: IngestJobStore
    job_queue: IngestJobQueue
    parser: DocumentParserPort
    object_storage: ObjectStoragePort


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


def build_export_bucket(settings: WorkerSettings) -> ObjectStoragePort:
    """Tenant offboarding's export destination — the `dw-exports` bucket
    already used elsewhere, not a new one made for this feature."""
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


def build_embeddings(settings: WorkerSettings) -> EmbeddingPort:
    """Public because two lanes need it: knowledge ingestion, and the memory
    index. Built by `dw_knowledge`'s one builder, the one the API embeds
    questions with, so "which model embeds this deployment's text" has a
    single answer: the `embedding` route of the configured model profile.
    """
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    return shared_build_embeddings(
        settings.embedding_provider,
        profiles.resolve(settings.model_profile).embedding,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        profile_id=settings.model_profile,
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


def build_parser(settings: WorkerSettings) -> DocumentParserPort:
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
            )
        )
    if settings.deepgram_api_key:
        parsers.append(DeepgramTranscriptParser(api_key=settings.deepgram_api_key, policy=policy))
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

    gateway = KnowledgeGateway(
        session_factory=session_factory,
        vector_index=build_vector_index(settings),
        embeddings=build_embeddings(settings),
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
        parser=build_parser(settings),
        object_storage=storage,
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
) -> ModelStack:
    """The worker's model gateway, spend ledger and usage recorders, built by
    the same `build_model_stack` the API builds its own with: the profiles,
    the shipped prompts, the daily spend guard. A chat command's model call
    therefore spends against the same per-run ceiling and the same daily
    guard as a request's."""
    profiles = ModelProfileRegistry()
    profiles.load_directory(REPO_ROOT / "configs" / "models")
    prompts = PromptRegistry()
    prompts.load_directory(REPO_ROOT / "configs" / "prompts")
    return build_model_stack(
        model_provider_config(settings),
        profiles=profiles,
        prompts=prompts,
        session_factory=sessions,
        clock=clock,
        telemetry=telemetry,
        mock_fixtures_dir=MOCK_MODEL_FIXTURES,
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


def build_wflite_runtime(
    settings: WorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    packs: PackCatalog,
    queue: WorkQueue,
    clock: UtcClock,
    ids: IdGenerator,
    telemetry: TelemetryPort,
) -> WfLiteRuntime:
    """The runner, executor and nodes the API builds for the same graphs
    (`dw_agent_runtime.adapters.wflite_host`): a run this process pauses on an
    approval resumes there, and one the API's decision runs on to a timer
    resumes here, from the same checkpoint.

    No usage meter: it bills an agent loop's LangChain calls, and a workflow's
    model calls go through the gateway, which records its own usage into the
    daily spend guard."""
    stack = build_model_stack_for(settings, sessions, clock=clock, telemetry=telemetry)
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
    )
    graphs = GraphRegistry()
    workers = WorkerRegistry(graph_registry=graphs)
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
        # The same plan catalog the API's runner refuses a run's start with.
        allowance=PlanEntitlementService(DEFAULT_PLANS),
        budget=stack.budget,
        approval_policy=approval_policy,
        release_manifest_ref=read_release_manifest_ref(REPO_ROOT),
        telemetry=telemetry,
        spend_store=SqlSpendGuardStore(session_factory=sessions),
        run_waits=WorkQueueRunWaits(queue),
    )
    register_workflows(
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
    )
    return WfLiteRuntime(
        runner=runner,
        starter=build_run_starter(
            catalog=packs, session_factory=sessions, tools=tools, runner=runner
        ),
        tools=tools,
    )
