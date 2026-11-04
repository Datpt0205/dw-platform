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
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from dw_studio.core.application.service import ArtifactService
from dw_studio.kinds import platform_kinds
from dw_studio.records.adapters.definition_store import object_store_of

if TYPE_CHECKING:
    from dw_api.bootstrap.container import ApiContainer


@dataclass(frozen=True)
class StudioContainer:
    """What Studio hands the API: its services and its routers, in mount order."""

    kinds: ArtifactKindRegistry
    artifacts: ArtifactService
    routers: tuple[APIRouter, ...]
    # tenant-config 04: the door that accepts a Studio run (workflow-engine/02)
    # builds its manifest with this, in its own transaction, under the release
    # this process serves; a Studio run reads its manifest back through the
    # port, bound to the session of the run's transaction (workflow-engine/05).
    run_manifests: RunManifestBuilder
    pinned_manifests: Callable[[AsyncSession], RunManifestPort]


def build_studio(
    container: ApiContainer,
    settings: ApiSettings,
    *,
    kinds: Sequence[ArtifactKindEntry] | None = None,
) -> StudioContainer | None:
    if container.engine is None or not settings.database_url:
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
    artifacts = ArtifactService(SqlArtifactStore(sessions, ids), registry, clock, ids)

    # Imported here, not at the top: the routes import the container's
    # dependencies, which import this package.
    from dw_api.routes.v1.studio_artifacts import router as artifacts_router

    return StudioContainer(
        kinds=registry,
        artifacts=artifacts,
        routers=(artifacts_router,),
        run_manifests=RunManifestBuilder(registry, release_manifest_ref()),
        pinned_manifests=SqlRunManifestStore,
    )
