"""The Studio kinds of the running app (tenant-config R2.15; custom-objects
ticket 02 step 4).

A module of `dw_studio`, not a sub-package: the registry the app runs with
needs each capability's entry, and "Studio core imports no capability" keeps
that list out of `dw_studio.core`. It names no adapter either: what a kind's
hook needs from storage arrives as a factory the composition root builds from
the core's SQL adapter and the capability's, over one session (`CLAUDE.md`:
only a composition root imports a concrete adapter).

`build_studio(..., kinds=None)` and every other composition root that runs a
publish hook register exactly `platform_kinds(...)`, and a test-only kind
reaches an app only through `kinds=` (`studio_kinds=` of `create_app`).
"""

from __future__ import annotations

from collections.abc import Callable

from dw_kernel.ports import IdGenerator, UtcClock
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.records.application.metadata import MetadataService
from dw_studio.records.application.ports import ObjectDefinitionStore
from dw_studio.records.domain.document import OBJECT_DOCUMENT_SCHEMA, OBJECT_KIND
from dw_studio.records.domain.rules import extract_object, validate_object

# The read, write and submit key of the `object` kind, tenant depth only
# (custom-objects R1.3; tenant-config R2.11, R2.12, R2.15). Which roles hold
# it is tenant-rbac's.
OBJECTS_MANAGE_SCOPE = "studio.objects.manage"


def object_kind(
    object_store: Callable[[ArtifactTx], ObjectDefinitionStore],
    *,
    clock: UtcClock,
    ids: IdGenerator,
) -> ArtifactKindEntry:
    return ArtifactKindEntry(
        kind=OBJECT_KIND,
        document_schema=OBJECT_DOCUMENT_SCHEMA,
        read_key=OBJECTS_MANAGE_SCOPE,
        write_key=OBJECTS_MANAGE_SCOPE,
        submit_key=OBJECTS_MANAGE_SCOPE,
        publish_hook=MetadataService(object_store, clock, ids).apply,
        validate=validate_object,
        extract=extract_object,
    )


def platform_kinds(
    object_store: Callable[[ArtifactTx], ObjectDefinitionStore],
    *,
    clock: UtcClock,
    ids: IdGenerator,
) -> tuple[ArtifactKindEntry, ...]:
    """Every kind of `studio.artifact_kinds`, one entry each; the
    composition-root test holds the two equal."""
    return (object_kind(object_store, clock=clock, ids=ids),)
