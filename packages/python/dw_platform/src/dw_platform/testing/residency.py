"""Residency gates for tests (compliance-pdpl ticket 03).

A run's model doors read the class the run pinned (`RunContext.route_class`),
so a test of a door needs no database: `run_gate()` is the real
`ResidencyGate` with a reader that refuses to be asked. `StaticRouteClasses`
answers a call outside a run from a mapping, and raises for a tenant or
workspace it does not hold, the way RLS hides a row.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from dw_kernel.errors import NotFoundError
from dw_kernel.residency import ResidencyGate, SpanPort

__all__ = ["StaticRouteClasses", "run_gate"]


class _RunScopesOnly:
    async def route_classes(
        self, tenant_id: UUID, workspace_id: UUID | None
    ) -> tuple[str, str | None]:
        raise NotImplementedError("not exercised by a run's door: its class is pinned")


def run_gate(telemetry: SpanPort | None = None) -> ResidencyGate:
    """The gate a run's doors hold in a test."""
    return ResidencyGate(classes=_RunScopesOnly(), telemetry=telemetry)


@dataclass
class StaticRouteClasses:
    """`RouteClassReader` from `tenants` (tenant -> class) and `workspaces`
    (workspace -> (tenant, class or None)); `asked` keeps every question."""

    tenants: Mapping[UUID, str]
    workspaces: Mapping[UUID, tuple[UUID, str | None]] = field(default_factory=dict)
    asked: list[tuple[UUID, UUID | None]] = field(default_factory=list)

    async def route_classes(
        self, tenant_id: UUID, workspace_id: UUID | None
    ) -> tuple[str, str | None]:
        self.asked.append((tenant_id, workspace_id))
        if tenant_id not in self.tenants:
            raise NotFoundError("tenant not readable")
        if workspace_id is None:
            return self.tenants[tenant_id], None
        owner, workspace_class = self.workspaces.get(workspace_id, (None, None))
        if owner != tenant_id:
            raise NotFoundError("workspace not readable")
        return self.tenants[tenant_id], workspace_class
