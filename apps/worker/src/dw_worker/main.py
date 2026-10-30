"""Worker main loop: runs registered consumers and keeps the heartbeat fresh.

The loop is the whole of this module's job. Each consumer is an ``async``
callable that does one tick of work and returns; the loop decides how often to
call it, catches what it raises, and stops every one of them on a single
shutdown event. A consumer that sleeps inside itself would be a consumer the
shutdown event cannot wake, so cadence is declared on the registry instead.

## Plugging in a bounded context

``build_registry`` wires only the platform lanes. A context adds its own at the
marked seam: build its components from settings, then
``registry.register("<name>", consumer, interval_seconds=...)``. If it owns job
queues, append a ``ReapTarget`` for each so abandoned rows are settled here
rather than in a second sweeper; if it has retention rules, satisfy
``RetentionPrunePort``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dw_agent_runtime.adapters.checkpoint_retention import SqlCheckpointRetention
from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.adapters.spend_guard import SqlSpendGuardRetention
from dw_agent_runtime.adapters.tool_claim_retention import SqlToolClaimRetention
from dw_agent_runtime.approval_flow import ApproveAndResumeService
from dw_agent_runtime.channel_decisions import (
    ChannelApprovalDecisionService,
    ChannelDecisionCommand,
)
from dw_connectors.adapters.zalo_bot import ZaloBotClient
from dw_connectors.adapters.zalo_inbound import ZaloInbound
from dw_connectors.adapters.zalo_link import link_help
from dw_connectors.inbound import ChannelCommandRegistry, InboundRouter
from dw_connectors.ports import ChatSenderPort
from dw_kernel.ports import IdGenerator, SystemClock, UtcClock, Uuid7Generator
from dw_knowledge.adapters.evidence_store import SqlEvidenceStore
from dw_knowledge.retention import SqlKnowledgeRetention
from dw_memory.policy import MemoryWritePolicy
from dw_memory.retention import SqlMemoryRetention
from dw_memory.service import MemoryService
from dw_observability.logs import configure_json_logging
from dw_observability.otel import build_telemetry
from dw_observability.telemetry import TelemetryPort
from dw_platform.adapters.persistence.approval_codes import (
    SqlApprovalCodeRetention,
    SqlApprovalCodeStore,
)
from dw_platform.adapters.persistence.channel_deliveries import (
    SqlChannelDeliveryRetention,
    SqlChannelOutbox,
)
from dw_platform.adapters.persistence.channel_inbound import (
    SqlChannelInboundLedger,
    SqlChannelInboundRetention,
    SqlChannelUpdateQueue,
)
from dw_platform.adapters.persistence.channel_preferences import SqlChannelPreferences
from dw_platform.adapters.persistence.digital_workers_repo import (
    SqlDigitalWorkerRepository,
    SqlDwMembershipCheck,
)
from dw_platform.adapters.persistence.effect_key_store import (
    EFFECT_KEYS,
    SqlEffectKeyRetention,
)
from dw_platform.adapters.persistence.idempotency_store import (
    IDEMPOTENCY_KEYS,
    SqlIdempotencyKeyRetention,
)
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.notifications import SqlNotificationRetention
from dw_platform.adapters.persistence.offboarding import (
    OffboardingPurgeSteps,
    SqlTenantOffboarding,
)
from dw_platform.adapters.persistence.outbox_drain import SqlOutboxDrain
from dw_platform.adapters.persistence.partition_maintenance import SqlPartitionMaintenance
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory
from dw_platform.adapters.persistence.work_queue_repo import SqlWorkQueueRepository
from dw_platform.adapters.persistence.zalo_link_repo import (
    SqlChannelLinkNonceRetention,
    SqlZaloLink,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.approval_codes import ApprovalSubjectVersions, DecisionCodeKey
from dw_platform.application.authorization import ScopeAuthorizationService
from dw_platform.application.channel_access import LinkedUserAccess
from dw_platform.application.work_queue import InMemoryWorkKindSchemas, WorkQueue
from dw_platform.retention_policy import RetentionPurgerRegistry, load_retention_policy
from dw_worker.composition import (
    build_embeddings,
    build_export_bucket,
    build_feedback_bucket,
    build_ingest_components,
    build_object_storage,
    build_vector_index,
)
from dw_worker.consumers import ConsumerRegistry
from dw_worker.consumers.channel_delivery import build_channel_delivery_consumer
from dw_worker.consumers.dw_work import INTERVAL_SECONDS as DW_WORK_INTERVAL_SECONDS
from dw_worker.consumers.dw_work import RecordingRunStarter, build_dw_work_consumer
from dw_worker.consumers.ingest import build_ingest_consumer
from dw_worker.consumers.memory import memory_handlers
from dw_worker.consumers.offboarding import INTERVAL_SECONDS as OFFBOARDING_INTERVAL_SECONDS
from dw_worker.consumers.offboarding import TenantOffboardingLane, build_offboarding_consumer
from dw_worker.consumers.outbox import EventHandler, build_outbox_consumer
from dw_worker.consumers.reaper import INTERVAL_SECONDS as REAP_INTERVAL_SECONDS
from dw_worker.consumers.reaper import ReapTarget, build_reaper_consumer
from dw_worker.consumers.retention import INTERVAL_SECONDS as RETENTION_INTERVAL_SECONDS
from dw_worker.consumers.retention import RetentionPrunePort, build_retention_consumer
from dw_worker.consumers.zalo_poll import build_zalo_poll_consumer
from dw_worker.consumers.zalo_webhook import INTERVAL_SECONDS as ZALO_WEBHOOK_INTERVAL_SECONDS
from dw_worker.consumers.zalo_webhook import build_zalo_webhook_consumer
from dw_worker.health import beat
from dw_worker.settings import WorkerSettings

if TYPE_CHECKING:
    from dw_memory.adapters.qdrant_ranker import QdrantMemoryRanker

logger = logging.getLogger("dw_worker")


def _build_worker_telemetry(settings: WorkerSettings) -> TelemetryPort:
    return build_telemetry(
        service_name="dw-worker",
        langfuse_enabled=settings.langfuse_enabled,
        langfuse_host=settings.langfuse_host,
        langfuse_public_key=settings.langfuse_public_key,
        langfuse_secret_key=settings.langfuse_secret_key,
        otel_endpoint=settings.otel_endpoint,
    )


def _build_memory_vectors(settings: WorkerSettings) -> QdrantMemoryRanker | None:
    """The memory ranker's store: written by the outbox handler, purged by
    supersession, retention and offboarding. One instance for all four, so
    the collection that is written is the collection that is purged.

    Imported inside the function so a deployment without Qdrant need not have
    the client installed to boot — the same rule the knowledge index follows."""
    if not settings.qdrant_url:
        return None
    from qdrant_client import AsyncQdrantClient

    from dw_memory.adapters.qdrant_ranker import QdrantMemoryRanker

    return QdrantMemoryRanker(
        client=AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key),
        embedder=build_embeddings(settings),
    )


def build_channel_decision_command(
    settings: WorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    runner: LangGraphWorkflowRunner,
    subjects: ApprovalSubjectVersions,
    strict_approval_prefixes: frozenset[str] = frozenset(),
    ids: IdGenerator,
    clock: UtcClock,
) -> ChannelDecisionCommand:
    """`DUYỆT <mã>` / `KHÔNG <mã> <lý do>` from a linked chat (ADR 0007, channels Z5).

    The decision goes through this process's own `ApproveAndResumeService`,
    over `runner`: the one that hosts the graph the approval belongs to, so a
    decided run resumes here from its checkpoint. A context passes its strict
    prefixes and registers its subject-version port on `subjects`, the way it
    does in the API's `wiring.py`; a type no context answers for is never
    decided by chat (no version, no decision). Without
    `DW_APPROVAL_CODE_SECRET` the command still answers a decision, with
    "not enabled", so the words never reach a model.
    """
    flow = ApproveAndResumeService(
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        runner=runner,
        run_store=runner.run_store,
        clock=clock,
        id_generator=ids,
        telemetry=runner.telemetry,
    )
    flow.strict_approval_prefixes |= strict_approval_prefixes
    secret = settings.approval_code_secret.get_secret_value()
    return ChannelDecisionCommand(
        ChannelApprovalDecisionService(
            approval_flow=flow,
            authorization=ScopeAuthorizationService(),
            store=SqlApprovalCodeStore(sessions),
            subjects=subjects,
            access=LinkedUserAccess(
                preferences=SqlChannelPreferences(sessions),
                lookup=SqlMembershipLookup(sessions),
            ),
            key=DecisionCodeKey(secret.encode()) if secret else None,
            clock=clock,
            ids=ids,
        )
    )


def build_channel_commands(
    decisions: ChannelDecisionCommand | None = None,
) -> ChannelCommandRegistry[AccessContext]:
    """What a linked person can ask for through a chat, in the order it is asked.

    The seam a context plugs its chat commands into. Order is policy, not
    convenience: the decide command first (`build_channel_decision_command`:
    a reply to a pending decision is never re-read as a new request, nor shown
    to a model), then an open conversation (a product's draft), then intent
    classification. The platform worker hosts no graph, so it has no runner to
    resume a decided run on and registers no decide command itself: a context
    that hosts its graph here builds one over its runner and passes it in.
    Empty is a working state: a linked person is told "Mình chưa xử lý được
    tin này". Each command declares its own scope ceiling; the router builds
    its context from the person's membership cut to that ceiling.
    """
    commands = ChannelCommandRegistry[AccessContext]()
    if decisions is not None:
        commands.register("approval_decision", decisions)
    return commands


def build_zalo_inbound(
    settings: WorkerSettings,
    sessions: async_sessionmaker[AsyncSession],
    bot: ChatSenderPort,
    clock: UtcClock,
    commands: ChannelCommandRegistry[AccessContext],
) -> ZaloInbound:
    """The Zalo update entry over this deployment's database: the link flow for
    ``/start``/``/stop``, the inbound router for everything else.

    One construction, so both lanes here and any test of them run the same
    wiring: the poll lane feeds it what ``getUpdates`` returns, the webhook
    drain (Z3) what the API's webhook queued.
    """
    zalo_link = SqlZaloLink(sessions)
    return ZaloInbound(
        link_secret=settings.zalo_link_secret.get_secret_value(),
        store=zalo_link,
        sender=bot,
        clock=clock,
        product_name=settings.product_name,
        router=InboundRouter(
            identities=zalo_link,
            ledger=SqlChannelInboundLedger(sessions),
            access=LinkedUserAccess(
                preferences=SqlChannelPreferences(sessions),
                lookup=SqlMembershipLookup(sessions),
            ),
            commands=commands,
            sender=bot,
            unlinked_reply=link_help(settings.product_name),
            settings_url=f"{settings.public_web_url.rstrip('/')}/settings",
        ),
    )


def build_retention_purgers(
    session_factory: async_sessionmaker[AsyncSession],
) -> RetentionPurgerRegistry:
    """Store key -> the purger that carries out its retention term, frozen here.

    The ticket that creates a store registers its purger in this function, in
    the same change as the store's fragment (telemetry-and-audit H-35), and the
    retention lane runs every entry. `platform.audit_events` is purged by DROP
    PARTITION in the `partitions` lane instead, and
    `test_every_purged_fragment_has_its_purger` holds a fragment whose purger is
    a lane's to an entry here.
    """
    purgers = RetentionPurgerRegistry()
    purgers.register(EFFECT_KEYS, SqlEffectKeyRetention(session_factory).purge)
    purgers.register(IDEMPOTENCY_KEYS, SqlIdempotencyKeyRetention(session_factory).purge)
    return purgers.freeze()


def build_registry(settings: WorkerSettings) -> ConsumerRegistry:
    """Wire the lanes this process hosts, skipping any whose infra is absent."""
    registry = ConsumerRegistry()
    clock = SystemClock()
    # Uuid7: a memory id that sorts by when it was learned makes the
    # keyset page over `created_at` stable without a second column.
    ids = Uuid7Generator()
    telemetry = _build_worker_telemetry(settings)

    # Every queue this process wired, with the window its jobs deserve. A queue
    # this host did not wire stays absent rather than being reaped with a
    # guessed window: the rows still exist and another process owns them, and
    # two reapers disagreeing about what counts as stale is worse than one that
    # is silent.
    reap_targets: list[ReapTarget] = []
    # What this deployment considers expired. ``None`` means nothing is pruned,
    # which is the correct default: deleting rows on a schedule nobody asked for
    # is not a safe guess.
    # What this deployment considers expired. No longer `None`: memory carries a
    # `retention_policy` per row and, until now, nothing read it — a lifecycle
    # commitment that a compliance review reads as a promise and that expired
    # nothing. The rules are a versioned artifact, not a constant, because the
    # question it answers ("how long do you keep our data") gets asked about the
    # past as well as the present.
    # Two lanes, not one: memory expires items on a per-class schedule and
    # knowledge expires documents somebody deleted, and a pass that failed would
    # otherwise take the other's work down with it.
    retention: RetentionPrunePort | None = None
    knowledge_retention: RetentionPrunePort | None = None
    partitions: RetentionPrunePort | None = None
    # Run checkpoints of finished threads, on the same policy file's
    # `checkpoints` terms. Its own lane for the same reason memory and knowledge
    # have theirs: a failing pass must not take the others down with it.
    checkpoint_retention: RetentionPrunePort | None = None
    # Tool claims past `expires_at` (runtime-hardening R6.7): nothing left to
    # guard, so no term; its own lane, like every pruner.
    tool_claims_retention: RetentionPrunePort | None = None
    # The spend guard's own housekeeping (Ops hardening Phase 3) — a technical
    # constant, not a legal term, so it is not on retention_policy's cadence
    # or file; see SqlSpendGuardRetention's docstring.
    spend_guard_retention: RetentionPrunePort | None = None
    # The in-app inbox's own bound: 90 days, the database's constant.
    notifications_retention: RetentionPrunePort | None = None
    # One-time channel link nonces: a day past expiry, then gone.
    channel_link_nonces_retention: RetentionPrunePort | None = None
    # Inbound chat message ids: seven days, then gone (INBOUND_MESSAGE_RETENTION).
    channel_inbound_messages_retention: RetentionPrunePort | None = None
    # Single-use decision codes: a day, then gone (the database's constant).
    approval_codes_retention: RetentionPrunePort | None = None
    # The Zalo self-link poll: only with a database, a bot token, a link secret
    # and ZALO_UPDATES_MODE=poll.
    zalo_poll_consumer: Callable[[], Awaitable[None]] | None = None
    # The Zalo webhook drain: the same, in webhook mode, never beside the poll.
    zalo_webhook_consumer: Callable[[], Awaitable[None]] | None = None
    # Notifications out through linked Zalo chats (ADR 0006): a database and a
    # bot token, polled or webhooked alike.
    channel_delivery_consumer: Callable[[], Awaitable[None]] | None = None
    # Channel deliveries: 90 days, never a pending one, the database's constant.
    channel_deliveries_retention: RetentionPrunePort | None = None
    # Ops hardening Phase 4. Needs object storage too, not just a database -
    # export/purge touch three buckets and the vector index alongside Postgres.
    offboarding_consumer: Callable[[], Awaitable[None]] | None = None
    # Digital Workers take their work (digital-worker R3.6). The starter
    # records the call until wf-lite/02 wires the workflow engine.
    dw_work_consumer: Callable[[], Awaitable[None]] | None = None

    if settings.database_url:
        # ---- transactional outbox ----------------------------------------
        # Handlers are keyed by event type. A context registers its own here;
        # an event with no handler is left in the table rather than dropped, so
        # adding the handler later drains the backlog.
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        dw_work_consumer = build_dw_work_consumer(
            WorkQueue(
                repo=SqlWorkQueueRepository(sessions),
                workers=SqlDigitalWorkerRepository(sessions),
                people=SqlDwMembershipCheck(sessions),
                # No pack declares a schema until wf-lite/01; nothing is let in.
                schemas=InMemoryWorkKindSchemas({}),
                authz=ScopeAuthorizationService(),
                clock=clock,
                id_generator=ids,
            ),
            RecordingRunStarter(),
        )
        # Remembering runs here rather than on the request that produced the
        # fact: a run that stops to decide what is worth keeping is a run someone
        # is waiting on. The handler is idempotent because the outbox delivers at
        # least once — see `dw_worker.consumers.memory`.
        # Absent without Qdrant, and absent is survivable: the memory is stored
        # and recalled either way, it simply sorts with the ones nothing has an
        # opinion about — and there are no points to purge.
        memory_vectors = _build_memory_vectors(settings)
        handlers: dict[str, EventHandler] = dict(
            memory_handlers(
                MemoryService(
                    session_factory=sessions,
                    policy=MemoryWritePolicy(),
                    clock=clock,
                    id_generator=ids,
                    evidence_store=SqlEvidenceStore(clock=clock),
                    # A superseded memory's point goes with it.
                    vector_purge=memory_vectors,
                ),
                # Writes the vector that lets a later recall order a long list.
                memory_vectors,
            )
        )
        # Pinned by filename, like every other versioned artifact here: the
        # answer to a retention question has to name the version that gave it.
        # One file read once — the two sweeps are two halves of one commitment,
        # and a build where they disagreed would be a build that answers the
        # compliance question two ways.
        # The pinned file and fragment set, from `dw_platform.retention_policy`'s
        # own constants: the terms loader and the policy tests read the same pin.
        retention_policy = load_retention_policy()
        retention = SqlMemoryRetention(
            session_factory=sessions,
            policy=retention_policy,
            clock=clock,
            vector_index=memory_vectors,
        )
        # Not retention in the sense of deleting: mostly it CREATES next
        # month's partitions, which is what keeps rows out of the DEFAULT one.
        # It shares the lane's port and cadence because it is the same kind of
        # slow housekeeping and answers the same policy file.
        partitions = SqlPartitionMaintenance(
            session_factory=sessions, policy=retention_policy, clock=clock
        )
        knowledge_retention = SqlKnowledgeRetention(
            session_factory=sessions,
            policy=retention_policy,
            clock=clock,
            # Deleting the rows without the points would leave the text of a
            # deleted document in the only store that can still return it.
            vector_index=build_vector_index(settings),
        )
        checkpoint_retention = SqlCheckpointRetention(
            session_factory=sessions, policy=retention_policy, clock=clock
        )
        tool_claims_retention = SqlToolClaimRetention(session_factory=sessions)
        spend_guard_retention = SqlSpendGuardRetention(session_factory=sessions, clock=clock)
        notifications_retention = SqlNotificationRetention(session_factory=sessions)
        channel_link_nonces_retention = SqlChannelLinkNonceRetention(session_factory=sessions)
        channel_inbound_messages_retention = SqlChannelInboundRetention(session_factory=sessions)
        approval_codes_retention = SqlApprovalCodeRetention(session_factory=sessions)
        # Rows are queued whether or not this host sends them, so they are
        # pruned whether or not it does.
        channel_deliveries_retention = SqlChannelDeliveryRetention(
            session_factory=sessions,
            pending_expiry=timedelta(days=retention_policy.channel_deliveries.pending_expiry_days),
        )
        if settings.zalo_send_enabled:
            channel_delivery_consumer = build_channel_delivery_consumer(
                SqlChannelOutbox(sessions),
                channel="zalo",
                address_of=SqlZaloLink(sessions).zalo_id_for,
                sender=ZaloBotClient(bot_token=settings.zalo_bot_token.get_secret_value()),
                web_url=settings.public_web_url,
            )
        # One bot, one reader (ADR 0008): poll mode polls, webhook mode drains
        # what the API's webhook queued. Both feed the same inbound entry.
        if settings.zalo_poll_enabled or settings.zalo_webhook_drain_enabled:
            bot = ZaloBotClient(bot_token=settings.zalo_bot_token.get_secret_value())
            inbound = build_zalo_inbound(settings, sessions, bot, clock, build_channel_commands())
            if settings.zalo_poll_enabled:
                zalo_poll_consumer = build_zalo_poll_consumer(bot, inbound)
            else:
                zalo_webhook_consumer = build_zalo_webhook_consumer(
                    SqlChannelUpdateQueue(sessions), inbound
                )
        if settings.s3_endpoint_url:
            offboarding_consumer = build_offboarding_consumer(
                TenantOffboardingLane(
                    # The one place the purge registry is built (R11.4): a context
                    # that deletes its tables its own way registers its step here.
                    store=SqlTenantOffboarding(
                        session_factory=sessions, steps=OffboardingPurgeSteps()
                    ),
                    artifacts=build_object_storage(settings),
                    exports=build_export_bucket(settings),
                    attachments=build_feedback_bucket(settings),
                    vector_index=build_vector_index(settings),
                    memory_vectors=memory_vectors,
                    clock=clock,
                )
            )
        registry.register(
            "outbox",
            build_outbox_consumer(
                SqlOutboxDrain(sessions, clock),
                handlers,
                batch_size=settings.outbox_batch_size,
                max_attempts=settings.outbox_max_attempts,
                telemetry=telemetry,
                clock=clock,
            ),
        )

    # ---- knowledge ingestion ---------------------------------------------
    # Needs a database and object storage both; without either, files are
    # staged by nobody and this lane would spin on an empty queue.
    ingest = build_ingest_components(settings)
    if ingest is not None:
        registry.register(
            "ingest",
            build_ingest_consumer(ingest, batch_size=settings.ingest_batch_size),
        )

    # ---- BOUNDED CONTEXT LANES REGISTER HERE -----------------------------
    # build_<context>_components(settings) → registry.register(...), and append
    # a ReapTarget per job queue the context owns.

    # ---- channels ----------------------------------------------------------
    # The Zalo self-link poll. Its own long-poll paces it; the interval only
    # spaces retries after a failed tick.
    if zalo_poll_consumer is not None:
        registry.register("zalo_link_poll", zalo_poll_consumer)
        logger.info("zalo link poll registered")
    if zalo_webhook_consumer is not None:
        registry.register(
            "zalo_webhook_drain",
            zalo_webhook_consumer,
            interval_seconds=ZALO_WEBHOOK_INTERVAL_SECONDS,
        )
        logger.info("zalo webhook drain registered")
    # In-app notifications out through linked chats. Claims rows with
    # SKIP LOCKED and holds no lease, so it needs no ReapTarget: a row a dead
    # worker held is pending again the moment its transaction ends.
    if channel_delivery_consumer is not None:
        registry.register(
            "channel_delivery",
            channel_delivery_consumer,
            interval_seconds=settings.channel_delivery_interval_seconds,
        )

    # The DW lane holds no lease either: a claim a dead worker made is returned
    # by the lane itself after 15 minutes without a run (R3.14).
    if dw_work_consumer is not None:
        registry.register("dw_work", dw_work_consumer, interval_seconds=DW_WORK_INTERVAL_SECONDS)

    # ---- periodic repair --------------------------------------------------
    # Registered last because both sweeps act on what everything above created,
    # and both are skipped when there is nothing for them to act on.
    if reap_targets:
        registry.register(
            "reaper",
            build_reaper_consumer(reap_targets, clock, telemetry),
            interval_seconds=REAP_INTERVAL_SECONDS,
        )
    if retention is not None:
        registry.register(
            "retention",
            build_retention_consumer(retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if knowledge_retention is not None:
        registry.register(
            "retention_knowledge",
            build_retention_consumer(knowledge_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if partitions is not None:
        registry.register(
            "partitions",
            build_retention_consumer(partitions),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if checkpoint_retention is not None:
        registry.register(
            "checkpoint_retention",
            build_retention_consumer(checkpoint_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if tool_claims_retention is not None:
        registry.register(
            "tool_claims_retention",
            build_retention_consumer(tool_claims_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if spend_guard_retention is not None:
        registry.register(
            "spend_guard_retention",
            build_retention_consumer(spend_guard_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if notifications_retention is not None:
        registry.register(
            "notifications_retention",
            build_retention_consumer(notifications_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if channel_link_nonces_retention is not None:
        registry.register(
            "channel_link_nonces_retention",
            build_retention_consumer(channel_link_nonces_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if channel_inbound_messages_retention is not None:
        registry.register(
            "channel_inbound_messages_retention",
            build_retention_consumer(channel_inbound_messages_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if channel_deliveries_retention is not None:
        registry.register(
            "channel_deliveries_retention",
            build_retention_consumer(channel_deliveries_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if approval_codes_retention is not None:
        registry.register(
            "approval_codes_retention",
            build_retention_consumer(approval_codes_retention),
            interval_seconds=RETENTION_INTERVAL_SECONDS,
        )
    if offboarding_consumer is not None:
        registry.register(
            "offboarding", offboarding_consumer, interval_seconds=OFFBOARDING_INTERVAL_SECONDS
        )
    return registry


async def run_worker(
    settings: WorkerSettings,
    registry: ConsumerRegistry,
    shutdown_event: asyncio.Event,
) -> None:
    logger.info("worker starting, consumers=%s", sorted(registry.all()))

    async def heartbeat_loop() -> None:
        while not shutdown_event.is_set():
            beat(settings.heartbeat_file)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=settings.heartbeat_interval_seconds
                )

    async def consumer_loop(name: str) -> None:
        consumer = registry.all()[name]
        interval = registry.interval_for(name, settings.poll_interval_seconds)
        while not shutdown_event.is_set():
            try:
                await consumer()
            except Exception:
                # Broad on purpose: one lane's bad tick must not take the
                # process down and stop every other lane with it.
                logger.exception("consumer %s failed; backing off", name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)

    tasks = [asyncio.create_task(heartbeat_loop(), name="heartbeat")]
    tasks.extend(
        asyncio.create_task(consumer_loop(name), name=f"consumer:{name}") for name in registry.all()
    )
    await shutdown_event.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("worker stopped cleanly")


def main() -> None:
    # Identifier-only JSON lines (spec R1.5): no rendered arguments, no free text.
    configure_json_logging(logging.INFO)
    settings = WorkerSettings()
    settings.validate_for_profile()
    # A background thread, not the asyncio loop: prometheus_client's server
    # predates asyncio support and reads the global REGISTRY per request, so
    # starting it before the loop exists is fine — there is nothing to race.
    # No setting gates this off: metrics are wired unconditionally now (Ops
    # hardening Phase 5, see `dw_observability.otel`), and a scrape target
    # nobody points Prometheus at costs nothing.
    from prometheus_client import start_http_server

    start_http_server(settings.metrics_port)
    registry = build_registry(settings)
    shutdown_event = asyncio.Event()

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):  # Windows lacks add_signal_handler
                loop.add_signal_handler(sig, shutdown_event.set)
        await run_worker(settings, registry, shutdown_event)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
