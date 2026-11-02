"""Test support for a DW's pinned workflow: the packs alone, no tenant
version (wf-ai R6.16).

`InMemoryTenantVersions` honours `TenantVersionsPort`: a version is found
only under the scope and DW it was put for, so a test that pins another
DW's or another tenant's version sees it not shipped, as the SQL store does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from dw_agent_runtime.wflite.catalog import PackCatalog
from dw_agent_runtime.wflite.versions import PinnedWorkflows, TenantVersion
from dw_platform.application.work_queue import WorkScope


@dataclass
class InMemoryTenantVersions:
    """Implements ``TenantVersionsPort``."""

    _rows: list[tuple[WorkScope, TenantVersion]] = field(default_factory=list)

    def put(self, scope: WorkScope, version: TenantVersion) -> None:
        self._rows.append((scope, version))

    async def of_dw(self, scope: WorkScope, dw_id: uuid.UUID, version: str) -> TenantVersion | None:
        return next(
            (v for s, v in self._rows if s == scope and v.dw_id == dw_id and v.version == version),
            None,
        )

    async def by_content(
        self, scope: WorkScope, *, key: str, version: str, content_sha256: str
    ) -> TenantVersion | None:
        return next(
            (
                v
                for s, v in self._rows
                if s == scope
                and v.key == key
                and v.version == version
                and v.content_sha256 == content_sha256
            ),
            None,
        )


def packs_only(catalog: PackCatalog) -> PinnedWorkflows:
    """A DW's pin read from the packs, with no tenant version anywhere."""
    return PinnedWorkflows(catalog=catalog, versions=InMemoryTenantVersions())


__all__ = ["InMemoryTenantVersions", "packs_only"]
