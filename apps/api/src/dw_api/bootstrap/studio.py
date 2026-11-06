"""Studio, composed above the context seams (ADR-0100 decision 6).

`build_studio` runs in `build_container` once the database is wired, after the
runtime seam is set when there is one and before the context seam, and returns
`None` without a database, so a host without one mounts no Studio route at all
(studio-skeleton R6.4). It is the one place that names a Studio adapter; each
capability's router joins the group here, and `mount_studio` in `dw_api.main`
mounts the group and its gate.

Without `kinds=` the app registers `platform_kinds(...)` of `dw_studio.kinds`,
never anything from settings or the environment: a kind that exists only in
a test reaches an app only through a test that passes `studio_kinds=`
(tenant-config R2.15). Their hooks get their stores from `object_store_of`,
over the session of the publish transaction (custom-objects ticket 02).

The stage machine (agent-lifecycle ticket 03) mounts one submit and withdraw
route per segment of `SUBMIT_SEGMENTS`, retire under `RETIRE_SEGMENTS` alone,
unless a test names its own `segments=` (to put a test kind under one); its
submit asks the process's one `SqlRunControl` (ticket 01), runs the per-kind
checks of `_SUBMIT_CHECKS` and asks `BindingStatus` (tenant-config ticket 05)
whether every required binding has an approved value. A publish request
(ticket 04) is decided under the guard `publish_decision_guards` registers for
every kind of the registry, by a loop and never a list, on the approval flow
`bootstrap.runtime` builds (its `studio.publish.` prefix is strict in
`wiring.py`); the decision is carried out on the worker, and the reviewer
reads the candidate through `CandidateReader`.
A kill and the request to revive (ticket 05) mount under `KILL_SEGMENTS`
alone, never a test's `segments=`: a switch kills an agent or a workflow,
`ck_control_switches_scope_type`.

The one door a Studio run is created through (workflow-engine ticket 02),
`RunRequestService`, takes two tables frozen here: `_RUN_KEYS`, the key a
person must hold to ask for each `(artifact_kind, trigger_kind)`, each a
`*_SCOPE` constant of the capability that owns the kind, so the permission
catalogue test reads it as a check; and `_RUN_LANES`, the lanes that may ask,
each with its trigger kinds.

The `workflow` kind (workflow-engine ticket 01) is checked against the step
types built here, `build_node_registry()`, and the platform layer of the tool
register: the runtime seam's when it is wired, the shipped specs otherwise,
as the worker reads them. The step-type catalogue (workflow-nodes ticket 02)
answers from that same registry, built once. Its publish hook activates trigger subscriptions
through `NoTriggerSubscriptions` until workflow-triggers/01 wires its own.

Bindings (tenant-config ticket 05): `binding_set`, Studio's one kind of
`ConfigKindRegistry`, with the W1 value checks of `platform_binding_types`
over the process's one `ConnectionUsability`; `ConfigVersionService` behind
the bindings routes; `ConfigVersionDecisions` as the `config.version` guard of
the approval flow (its prefix is strict in `bootstrap.runtime`); the door's
`BindingPins`; `BindingStatus`, the `PublishBindingsCheck` agent-lifecycle/04
asks; and the connections' dependents answered from approved Binding sets.
Without the connection rule (no database) Studio is not built at all.

Records (custom-objects ticket 03): one `RecordService` over `SqlRecordStore`,
the field decision of field-security/01 (`FieldAccessService` over
`SqlFieldSecurityInputs`, wired here and nowhere else), the process's one
`RateLimiterPort` from the container and the schema projector. A person's
request reaches it through `record_door`, whose transactions open in
`user_session` (record-access/03): tenant, principal, the actor `user` and the
reach door, bound before the service's first statement. A workflow step's
`RecordsPort` (workflow-nodes/04) and an agent's `ObjectDataPort`
(`RecordObjectData`, tools-and-skills/03) take this same service, each with
its run's door: the object tools' door is `agent_record_session`, wired with
`ObjectToolGenerator` where agent-builder/03 takes a Studio agent run.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.checkpoint_serde import checkpoint_serializer
from dw_agent_runtime.adapters.model_stack import build_model_resolver
from dw_agent_runtime.adapters.studio_resume import StudioResumeChecks, WorkflowEngineFacts
from dw_agent_runtime.ports import RunManifestPort
from dw_agent_runtime.wflite.catalog import ShippedToolSpecs
from dw_agent_runtime.wflite.registry import NodeTypeSpec, build_node_registry
from dw_agent_runtime.wflite.validate import ToolSpecLookup
from dw_api.bootstrap.models import model_provider_config
from dw_api.bootstrap.paths import MODEL_PROFILES_DIR, TOOL_SPECS_DIR, release_manifest_ref
from dw_api.settings import ApiSettings
from dw_kernel.errors import NotFoundError
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.audience_workspaces import SqlAudienceWorkspaces
from dw_platform.adapters.persistence.config_versions_repo import SqlConfigVersionStore
from dw_platform.adapters.persistence.plan_model_profiles import (
    CachingPlanModelProfiles,
    SqlPlanModelProfiles,
)
from dw_platform.application.access_context import AccessContext
from dw_platform.application.audience import AudienceValidator
from dw_platform.application.config_versions import (
    CONFIG_VERSION,
    ConfigKindRegistry,
    ConfigVersionDecisions,
    ConfigVersionService,
)
from dw_studio.agents.adapters.settings_store import SqlAgentSettingsStore
from dw_studio.agents.application.settings import AgentSettingsService
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.cel.engine import CelCppEngine
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.adapters.run_bindings import SqlRunBindings
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestEngines, SqlRunManifestStore
from dw_studio.core.adapters.studio_runs import SqlResumeCheckStore
from dw_studio.core.application.bindings import (
    BindingConnectionDependents,
    BindingPins,
    BindingSets,
    BindingsReader,
    BindingStatus,
    platform_binding_types,
)
from dw_studio.core.application.boundaries import ActorBoundaryPort
from dw_studio.core.application.field_access import FieldAccessService
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.resume_check import ResumeCheckService
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import RunLaneRegistry, RunRequestService
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import (
    WORKFLOW_KIND,
    WORKFLOWS_TEST_SCOPE,
    object_live_check,
    platform_kinds,
    run_boundary_derivers,
    run_pinnable_steps,
)
from dw_studio.lifecycle.adapters.store import SqlKillStore, SqlLifecycleStore
from dw_studio.lifecycle.application.kill import KILL_SEGMENTS, KillSwitchService
from dw_studio.lifecycle.application.ports import SubmitCheck
from dw_studio.lifecycle.application.publish import publish_decision_guards
from dw_studio.lifecycle.application.review import CandidateReader
from dw_studio.lifecycle.application.service import SUBMIT_SEGMENTS, LifecycleService
from dw_studio.records.adapters.actor_boundaries import SqlActorBoundaries
from dw_studio.records.adapters.definition_store import (
    SqlObjectDefinitionReader,
    object_store_of,
)
from dw_studio.records.adapters.record_store import SqlRecordStore
from dw_studio.records.adapters.user_session import user_session
from dw_studio.records.application.record_service import RecordDoor, RecordService
from dw_studio.records.application.schema_projector import ObjectSchemaProjector
from dw_studio.records.domain.document import OBJECT_KIND
from dw_studio.submit_checks import workflow_capability_check
from dw_studio.workflows.adapters.triggers import NoTriggerSubscriptions

if TYPE_CHECKING:
    from dw_api.bootstrap.container import ApiContainer

# Each kind's submit checks (agent-lifecycle R2.7), one entry per kind: the
# `object` kind's comparison with its live version (custom-objects/06, R2.4);
# the Capability analysis (compliance-pdpl/05) and the workflow's reviewer
# check (workflow-nodes R9.5) register here when they ship.
_SUBMIT_CHECKS: Mapping[str, Sequence[SubmitCheck]] = MappingProxyType(
    {OBJECT_KIND: (object_live_check,)}
)

# The key a person holds, at the run's workspace, to ask for a run of each
# (artifact_kind, trigger_kind) (workflow-engine R3.17); a pair with no entry
# is refused. `workflow`'s `manual` joins with workflow-triggers/01, `agent`'s
# `chat` with agent-builder.
_RUN_KEYS: Mapping[tuple[str, str], str] = MappingProxyType(
    {(WORKFLOW_KIND, "test"): WORKFLOWS_TEST_SCOPE}
)

# The lanes that ask for runs, each with the trigger kinds it may ask for
# (workflow-engine R3.18, R3.19): the inbound lane of workflow-triggers acts
# on its own for a data-hub event; the quality gate of agent-lifecycle carries
# out the submitter's decision. Only this registry issues a `LaneRequester`.
_RUN_LANES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"studio_inbound": ("datahub",), "studio_gate": ("eval",)}
)


@dataclass(frozen=True)
class StudioContainer:
    """What Studio hands the API: its services and its routers, in mount order."""

    kinds: ArtifactKindRegistry
    artifacts: ArtifactService
    # agent-builder 02: an agent's settings beside its versions, every write
    # through org-and-principals' audience validator.
    agent_settings: AgentSettingsService
    # agent-lifecycle 03: the one writer of a version's stage, and the route
    # segment of each kind it submits, withdraws and retires.
    lifecycle: LifecycleService
    segments: Mapping[str, str]
    # agent-lifecycle 04: the candidate of a pending publish request, read by
    # the person who may decide it.
    candidates: CandidateReader
    # agent-lifecycle 05: a component's kill and the request to revive it,
    # under the route segment of each kind a switch can kill.
    kill_switches: KillSwitchService
    kill_segments: Mapping[str, str]
    routers: tuple[APIRouter, ...]
    # tenant-config 04: the door that accepts a Studio run (workflow-engine/02)
    # builds its manifest with this, in its own transaction, under the release
    # this process serves; a Studio run reads its manifest back through the
    # port, bound to the session of the run's transaction (workflow-engine/05).
    run_manifests: RunManifestBuilder
    pinned_manifests: Callable[[AsyncSession], RunManifestPort]
    # workflow-engine 02: the one door of a Studio run, and the registry that
    # issues a lane its requester.
    run_requests: RunRequestService
    run_lanes: RunLaneRegistry
    # tenant-config 05: proposals of a Binding set and their reads; the
    # publish check agent-lifecycle/04 asks; a run's pinned connections.
    config_versions: ConfigVersionService
    bindings: BindingsReader
    binding_status: BindingStatus
    run_bindings: SqlRunBindings
    # workflow-nodes 02: the one step registry the `workflow` kind validates
    # against and the catalogue route publishes.
    node_types: Mapping[str, NodeTypeSpec]
    # record-access 04: where a version's data boundary is recorded in its
    # publish transaction and a `simulate` run's provisional one in its run
    # door's; the `agent` and `workflow` publish hooks (agent-builder/05,
    # workflow-engine/03) and the run door's derivations (workflow-engine/03)
    # take it from here.
    actor_boundaries: ActorBoundaryPort
    # custom-objects 03: the one record service, and the door a person's
    # request reaches it through.
    records: RecordService
    record_door: Callable[[AccessContext], RecordDoor]
    # workflow-engine 05: `POST /runs/{run_id}/resume-check` (R6.39).
    resume_checks: ResumeCheckService


def _profile_locations(models: Any) -> Callable[[str], tuple[str | None, ...] | None]:
    """Where each route of a platform model profile processes (ADR-0123
    decision 5), from the process's one resolver; None for a profile it does
    not register, which the analysis reads as foreign."""

    def locations(profile_id: str) -> tuple[str | None, ...] | None:
        try:
            profile = models.platform_profile(profile_id)
        except NotFoundError:
            return None
        return tuple(route.get("data_location") for route in profile.pinned_routes().values())

    return locations


def build_studio(
    container: ApiContainer,
    settings: ApiSettings,
    *,
    kinds: Sequence[ArtifactKindEntry] | None = None,
    segments: Mapping[str, str] | None = None,
) -> StudioContainer | None:
    if (
        container.engine is None
        or not settings.database_url
        or container.run_control is None
        or container.connection_usability is None
        or container.connections is None
        or container.rate_limiter is None
    ):
        return None
    # From the runtime seam's when it is wired; the database's own otherwise,
    # because the envelope needs Postgres and nothing else (R6.1).
    runtime = container.runtime
    sessions = (
        runtime.session_factory
        if runtime is not None
        else async_sessionmaker(container.engine, class_=AsyncSession, expire_on_commit=False)
    )
    clock = runtime.clock if runtime is not None else SystemClock()
    ids = runtime.ids if runtime is not None else Uuid7Generator()
    tools: ToolSpecLookup = (
        runtime.tool_specs if runtime is not None else ShippedToolSpecs.load(TOOL_SPECS_DIR)
    )
    node_types = build_node_registry()
    actor_boundaries = SqlActorBoundaries()
    registry = ArtifactKindRegistry(
        platform_kinds(
            object_store_of,
            clock=clock,
            ids=ids,
            nodes=node_types,
            tools=tools,
            triggers=NoTriggerSubscriptions(),
            boundaries=actor_boundaries,
            # The one `ExpressionEngine` adapter (ADR-0114); here it types a
            # workflow's `outcomes[]` conditions at submit (workflow-engine R1.9).
            expressions=CelCppEngine(),
        )
        if kinds is None
        else kinds
    )
    store = SqlArtifactStore(sessions, ids)
    artifacts = ArtifactService(store, registry, clock, ids)

    segments = SUBMIT_SEGMENTS if segments is None else MappingProxyType(dict(segments))
    # A run's models are pinned by the resolver its calls then ask
    # (model-connections R1.4): the runtime's, or one of the same build when
    # this process wires Studio without a runtime.
    models = (
        runtime.models
        if runtime is not None
        else build_model_resolver(
            model_provider_config(settings),
            profiles_dir=MODEL_PROFILES_DIR,
            plans=CachingPlanModelProfiles(SqlPlanModelProfiles(sessions), clock),
            pinned=SqlRunManifestEngines(sessions),
        )
    )
    # The engine facts a run pins (workflow-engine R6.7), of the same step
    # registry the kinds validate against.
    run_manifests = RunManifestBuilder(
        registry, release_manifest_ref(), models, WorkflowEngineFacts(node_types)
    )
    run_lanes = RunLaneRegistry(_RUN_LANES)

    usability = container.connection_usability
    binding_types = platform_binding_types(usability)
    binding_status = BindingStatus(store, binding_types)
    # A workflow's capability analysis at its submit (compliance-pdpl R4,
    # ticket 05), over this process's step registry and tool register, a model
    # step on the deployment's default profile.
    submit_checks: Mapping[str, Sequence[SubmitCheck]] = {
        **_SUBMIT_CHECKS,
        WORKFLOW_KIND: (
            workflow_capability_check(
                registry=node_types,
                tools=tools,
                ids=ids,
                profile_locations=_profile_locations(models),
                default_profile=getattr(models, "default_profile", None),
            ),
        ),
    }
    lifecycle = LifecycleService(
        SqlLifecycleStore(store),
        artifacts,
        container.run_control,
        # The platform kinds' checks: a test's own kinds (`kinds=`) are not them.
        submit_checks if kinds is None else {},
        clock,
        bindings=binding_status,
    )
    config_kinds = ConfigKindRegistry([BindingSets(store, registry, binding_types, usability)])
    config_store = SqlConfigVersionStore(sessions)
    if container.approval_flow is not None:
        # Asked before a `config.version` decision is written (R8.9, R8.17).
        # And no author decides their own version's publication (agent-lifecycle
        # R5.2, R5.3): one guard per kind of the registry.
        container.approval_flow.decision_guards = {
            **container.approval_flow.decision_guards,
            CONFIG_VERSION: ConfigVersionDecisions(config_kinds, config_store),
            **publish_decision_guards(registry.kinds),
        }
    # A connection is in use while an approved Binding set binds it (R3.7).
    container.connections = dataclasses.replace(
        container.connections, dependents_port=BindingConnectionDependents(store, registry)
    )

    records = RecordService(
        SqlRecordStore(),
        FieldAccessService(SqlFieldSecurityInputs()),
        container.rate_limiter,
        ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
        clock,
        ids,
    )

    def record_door(context: AccessContext) -> RecordDoor:
        return RecordDoor(lambda: user_session(sessions, context))

    # Imported here, not at the top: the routes import the container's
    # dependencies, which import this package.
    from dw_api.routes.v1.studio_agents import router as agents_router
    from dw_api.routes.v1.studio_artifacts import router as artifacts_router
    from dw_api.routes.v1.studio_bindings import router as bindings_router
    from dw_api.routes.v1.studio_kill import kill_router
    from dw_api.routes.v1.studio_lifecycle import lifecycle_router
    from dw_api.routes.v1.studio_node_types import router as node_types_router
    from dw_api.routes.v1.studio_publish_approvals import router as publish_approvals_router
    from dw_api.routes.v1.studio_records import router as records_router

    return StudioContainer(
        kinds=registry,
        artifacts=artifacts,
        agent_settings=AgentSettingsService(
            SqlAgentSettingsStore(store),
            AudienceValidator(SqlAudienceWorkspaces(sessions)),
            clock,
            ids,
        ),
        lifecycle=lifecycle,
        segments=segments,
        candidates=CandidateReader(lifecycle),
        kill_switches=KillSwitchService(SqlKillStore(store), artifacts, clock, ids),
        kill_segments=KILL_SEGMENTS,
        routers=(
            artifacts_router,
            agents_router,
            bindings_router,
            lifecycle_router(segments),
            kill_router(KILL_SEGMENTS),
            node_types_router,
            publish_approvals_router,
            records_router,
        ),
        run_manifests=run_manifests,
        pinned_manifests=SqlRunManifestStore,
        run_requests=RunRequestService(
            store,
            registry,
            run_manifests,
            _RUN_KEYS,
            run_lanes,
            clock,
            ids,
            bindings=BindingPins(binding_types, usability),
            boundaries=actor_boundaries,
            boundary_derivers=run_boundary_derivers(node_types),
            pinnable=run_pinnable_steps(node_types),
        ),
        run_lanes=run_lanes,
        config_versions=ConfigVersionService(config_kinds, config_store, clock, ids),
        bindings=BindingsReader(store, registry),
        binding_status=binding_status,
        run_bindings=SqlRunBindings(sessions),
        node_types=node_types,
        actor_boundaries=actor_boundaries,
        records=records,
        record_door=record_door,
        # workflow-engine 05: the resume check of a blocked Studio run, its
        # five checks read from the run's checkpoint with this process's step
        # registry, its switches the container's.
        resume_checks=ResumeCheckService(
            SqlResumeCheckStore(sessions, ids, clock),
            StudioResumeChecks(
                SqlAlchemyCheckpointSaver(sessions, checkpoint_serializer()),
                node_types,
                container.run_control,
            ),
            clock,
        ),
    )
