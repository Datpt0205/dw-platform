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

The stage machine (agent-lifecycle ticket 03) mounts one submit, withdraw and
retire route per segment of `SUBMIT_SEGMENTS`, unless a test names its own
`segments=` (to put a test kind under one); its submit asks the process's one
`SqlRunControl` (ticket 01) and runs the per-kind checks of `_SUBMIT_CHECKS`.

The one door a Studio run is created through (workflow-engine ticket 02),
`RunRequestService`, takes two tables frozen here: `_RUN_KEYS`, the key a
person must hold to ask for each `(artifact_kind, trigger_kind)`, each a
`*_SCOPE` constant of the capability that owns the kind, so the permission
catalogue test reads it as a check; and `_RUN_LANES`, the lanes that may ask,
each with its trigger kinds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.ports import RunManifestPort
from dw_api.bootstrap.paths import release_manifest_ref
from dw_api.settings import ApiSettings
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.adapters.artifact_store import SqlArtifactStore
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.run_manifests import RunManifestBuilder
from dw_studio.core.application.run_request import RunLaneRegistry, RunRequestService
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import platform_kinds
from dw_studio.lifecycle.adapters.store import SqlLifecycleStore
from dw_studio.lifecycle.application.ports import SubmitCheck
from dw_studio.lifecycle.application.service import SUBMIT_SEGMENTS, LifecycleService
from dw_studio.records.adapters.definition_store import object_store_of

if TYPE_CHECKING:
    from dw_api.bootstrap.container import ApiContainer

# Each kind's submit checks (agent-lifecycle R2.7), one entry per kind: the
# Capability analysis (compliance-pdpl/05) and the workflow's reviewer check
# (workflow-nodes R9.5) register here when they ship.
_SUBMIT_CHECKS: Mapping[str, Sequence[SubmitCheck]] = {}

# The key a person holds, at the run's workspace, to ask for a run of each
# (artifact_kind, trigger_kind) (workflow-engine R3.17); a pair with no entry
# is refused. `workflow`'s (`test` -> `studio.workflows.test`) joins with that
# kind and its key in workflow-engine/01, `manual` with workflow-triggers/01,
# `agent`'s `chat` with agent-builder.
_RUN_KEYS: Mapping[tuple[str, str], str] = MappingProxyType({})

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
    # agent-lifecycle 03: the one writer of a version's stage, and the route
    # segment of each kind it submits, withdraws and retires.
    lifecycle: LifecycleService
    segments: Mapping[str, str]
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


def build_studio(
    container: ApiContainer,
    settings: ApiSettings,
    *,
    kinds: Sequence[ArtifactKindEntry] | None = None,
    segments: Mapping[str, str] | None = None,
) -> StudioContainer | None:
    if container.engine is None or not settings.database_url or container.run_control is None:
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
    registry = ArtifactKindRegistry(
        platform_kinds(object_store_of, clock=clock, ids=ids) if kinds is None else kinds
    )
    store = SqlArtifactStore(sessions, ids)
    artifacts = ArtifactService(store, registry, clock, ids)
    lifecycle = LifecycleService(
        SqlLifecycleStore(store), artifacts, container.run_control, _SUBMIT_CHECKS, clock
    )

    segments = SUBMIT_SEGMENTS if segments is None else MappingProxyType(dict(segments))
    run_manifests = RunManifestBuilder(registry, release_manifest_ref())
    run_lanes = RunLaneRegistry(_RUN_LANES)

    # Imported here, not at the top: the routes import the container's
    # dependencies, which import this package.
    from dw_api.routes.v1.studio_artifacts import router as artifacts_router
    from dw_api.routes.v1.studio_lifecycle import lifecycle_router

    return StudioContainer(
        kinds=registry,
        artifacts=artifacts,
        lifecycle=lifecycle,
        segments=segments,
        routers=(artifacts_router, lifecycle_router(segments)),
        run_manifests=run_manifests,
        pinned_manifests=SqlRunManifestStore,
        run_requests=RunRequestService(
            store, registry, run_manifests, _RUN_KEYS, run_lanes, clock, ids
        ),
        run_lanes=run_lanes,
    )
