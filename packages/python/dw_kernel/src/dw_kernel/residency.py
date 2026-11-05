"""The data route and the one gate every model call passes (ADR-0123; compliance-pdpl R2).

One owner for each fact of the residency decision:

- the three route classes, strictest first (`ROUTE_CLASSES`), which the
  migration's CHECKs write as literals and `test_residency_catalog.py` reads
  back from the catalog;
- `effective_route_class`, the strictest of the tenant's, the workspace's and
  the version's class, which a run pins at admission;
- `admits`, the rule of decision 3 (`vn_only` takes a `vn` destination only,
  `cross_border_minimised` too until the pseudonymiser exists, and
  `cross_border_full` takes both), with an undeclared location read as
  `foreign` (decision 5);
- `ResidencyGate`, which every adapter that sends content to a model holds by
  constructor injection and asks before it builds a request (decision 4).

The gate takes the class from the scope it is handed, never from an argument a
caller fills in: a run's class pinned on its `RunContext` (any object with a
`route_class`, read from the run row at admission and on resume), or, for a
call outside a run, the tenant and workspace of a verified context or of a job
row (`TenantRouteScope`), read under RLS through `RouteClassReader`. A row that
cannot be read, or a value outside the three, refuses (failure-modes #7).

Standard library only, like the rest of the kernel.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Final, Literal, Protocol, TypeVar, get_args
from uuid import UUID

from dw_kernel.errors import ConflictError, DomainError, PermissionDeniedError

__all__ = [
    "DATA_LOCATIONS",
    "PLATFORM_SCOPE",
    "RESIDENCY_REFUSED",
    "RESIDENCY_SPAN",
    "ROUTE_CLASSES",
    "ROUTE_CLASS_LOOSER_THAN_TENANT",
    "SECOND_PERSON_REQUIRED",
    "DataLocation",
    "Destination",
    "PinnedRouteClass",
    "ResidencyGate",
    "ResidencyRefusedError",
    "RouteClass",
    "RouteClassChange",
    "RouteClassReader",
    "RoutedDestination",
    "Scope",
    "SpanPort",
    "TenantRouteScope",
    "UnknownRouteClassError",
    "admits",
    "effective_route_class",
    "is_looser",
    "parse_route_class",
    "tenant_class_change",
    "workspace_class_change",
]

RouteClass = Literal["vn_only", "cross_border_minimised", "cross_border_full"]
DataLocation = Literal["vn", "foreign"]

# Strictest first: the order `effective_route_class` and the loosening rule read.
ROUTE_CLASSES: Final[tuple[RouteClass, ...]] = get_args(RouteClass)
DATA_LOCATIONS: Final[tuple[DataLocation, ...]] = get_args(DataLocation)

RESIDENCY_REFUSED: Final = "residency_refused"
SECOND_PERSON_REQUIRED: Final = "second_person_required"
ROUTE_CLASS_LOOSER_THAN_TENANT: Final = "route_class_looser_than_tenant"

# The span every check writes, refused or admitted (ADR-0123 decision 6).
RESIDENCY_SPAN: Final = "dw.residency.check"

_STRICTNESS: Final = {name: rank for rank, name in enumerate(ROUTE_CLASSES)}


class UnknownRouteClassError(DomainError):
    """A value that is not one of the three classes: never read as a loose one."""


class ResidencyRefusedError(PermissionDeniedError):
    """The gate refused a destination before anything was sent (spec R2.2).

    A refusal is a policy answer, not a provider failure: nothing retries it
    (it is no `InfrastructureError`, and it carries no HTTP status the model
    retry reads), nothing is recorded on the usage ledger, and a run that meets
    it ends `failed` with `reason_code` `residency_refused`."""

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message, details={"reason_code": RESIDENCY_REFUSED, **(details or {})})


def parse_route_class(value: object) -> RouteClass:
    for name in ROUTE_CLASSES:
        if value == name:
            return name
    raise UnknownRouteClassError(
        "not a data route class", details={"value": str(value)[:64], "allowed": list(ROUTE_CLASSES)}
    )


def effective_route_class(
    tenant_class: object, workspace_class: object | None, version_class: object | None
) -> RouteClass:
    """The strictest of the three (ADR-0123 decision 3). `None` for the
    workspace or the version tightens nothing; the tenant always has a class.
    A value outside the three raises `UnknownRouteClassError`.

    A child run takes the strictest of its parent's class and its own
    version's: `effective_route_class(parent_class, None, version_class)`."""
    classes = [parse_route_class(tenant_class)]
    classes.extend(parse_route_class(c) for c in (workspace_class, version_class) if c is not None)
    return min(classes, key=_STRICTNESS.__getitem__)


def is_looser(candidate: RouteClass, than: RouteClass) -> bool:
    return _STRICTNESS[candidate] > _STRICTNESS[than]


def admits(route_class: RouteClass, data_location: str | None) -> bool:
    """Decision 3. An undeclared or unknown location is `foreign` (decision 5).
    `cross_border_minimised` admits a foreign route only after pseudonymisation,
    which W1 does not have, so it admits `vn` only until then."""
    location = data_location if data_location in DATA_LOCATIONS else "foreign"
    if route_class == "cross_border_full":
        return True
    return location == "vn"


# ---- what the gate is asked about --------------------------------------------


class RoutedDestination(Protocol):
    """What the gate reads of a destination: a profile's `ModelRoute` satisfies
    it, and so does `Destination`, which an adapter with no route declares
    from its process settings."""

    @property
    def data_location(self) -> str | None: ...

    @property
    def processor(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Destination:
    """A destination that is not a model route (rerank, document extraction,
    transcription): declared in the process settings beside its URL, with no
    default, so an undeclared one is `None` and the gate reads it as foreign."""

    name: str
    data_location: str | None
    processor: str | None


class PinnedRouteClass(Protocol):
    """A run's scope: its class pinned at admission. `RunContext` satisfies it."""

    @property
    def route_class(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TenantRouteScope:
    """A call outside a run: the tenant and workspace of a verified
    `AccessContext`, or of a job row written from one. `workspace_id=None` is a
    tenant-wide job, which only the tenant's class governs; `tenant_id=None` is
    the platform's own evaluation, which runs `vn_only`."""

    tenant_id: UUID | None
    workspace_id: UUID | None


PLATFORM_SCOPE: Final = TenantRouteScope(tenant_id=None, workspace_id=None)

Scope = PinnedRouteClass | TenantRouteScope


class RouteClassReader(Protocol):
    """The tenant's and the workspace's class, read under the tenant's RLS.

    Raises when a row cannot be read (a workspace another tenant owns is a row
    RLS does not return): the gate refuses on any failure here."""

    async def route_classes(
        self, tenant_id: UUID, workspace_id: UUID | None
    ) -> tuple[str, str | None]: ...


class SpanPort(Protocol):
    """The slice of `TelemetryPort` the gate writes to."""

    def span(self, name: str, attributes: dict[str, object]) -> AbstractContextManager[None]: ...


D = TypeVar("D", bound=RoutedDestination)


@dataclass(frozen=True)
class ResidencyGate:
    """The one gate (ADR-0123 decision 4). Injected by constructor into every
    adapter that sends content to a model; never built by the adapter."""

    classes: RouteClassReader
    telemetry: SpanPort | None = None

    async def route_class(self, scope: Scope) -> RouteClass:
        """The class `scope` carries, or a refusal when it cannot be known."""
        if not isinstance(scope, TenantRouteScope):
            try:
                return parse_route_class(scope.route_class)
            except UnknownRouteClassError as exc:
                raise ResidencyRefusedError(
                    "the run's data route class is unreadable", details={"reason": "unknown_class"}
                ) from exc
        if scope.tenant_id is None:
            return "vn_only"
        try:
            tenant_class, workspace_class = await self.classes.route_classes(
                scope.tenant_id, scope.workspace_id
            )
            return effective_route_class(tenant_class, workspace_class, None)
        except Exception as exc:
            # Broad on purpose: whatever stopped the read, the class is unknown,
            # and an unknown class sends nothing (failure-modes #7).
            raise ResidencyRefusedError(
                "the data route class could not be read", details={"reason": "unreadable"}
            ) from exc

    async def check(self, scope: Scope, destination: RoutedDestination) -> None:
        """Refuse before anything is sent to a destination `scope` does not admit."""
        await self.admitted(scope, (destination,))

    async def admitted(self, scope: Scope, destinations: Sequence[D]) -> list[D]:
        """The destinations `scope` admits, in order, from one reading of the
        class: a door with fallbacks drops the refused ones before its first
        send, so a failing `vn` route never falls through to a `foreign` one.
        None admitted is a refusal."""
        route_class = await self.route_class(scope)
        kept = [d for d in destinations if admits(route_class, d.data_location)]
        for destination in destinations:
            self._record(route_class, destination, admitted=destination in kept)
        if not kept:
            first = destinations[0] if destinations else None
            raise ResidencyRefusedError(
                "Lộ trình dữ liệu của công ty không cho phép gửi tới nơi xử lý này",
                details={
                    "route_class": route_class,
                    "data_location": None if first is None else first.data_location,
                    "processor": None if first is None else first.processor,
                },
            )
        return kept

    def _record(
        self, route_class: RouteClass, destination: RoutedDestination, *, admitted: bool
    ) -> None:
        if self.telemetry is None:
            return
        attributes: dict[str, object] = {
            "dw.route_class": route_class,
            "dw.data_location": destination.data_location or "undeclared",
            "dw.processor": destination.processor or "undeclared",
            "dw.residency.admitted": admitted,
        }
        with self.telemetry.span(RESIDENCY_SPAN, attributes):
            pass


# ---- changing a class (spec R2.4, R2.7, R2.8) --------------------------------

RouteClassChange = Literal["unchanged", "tightened"]


def _second_person(scope: str, current: str | None, requested: str | None) -> ConflictError:
    return ConflictError(
        "nới Lộ trình dữ liệu cần người duyệt thứ hai",
        details={
            "reason_code": SECOND_PERSON_REQUIRED,
            "scope": scope,
            "from": current,
            "to": requested,
        },
    )


def tenant_class_change(current: object, requested: object) -> RouteClassChange:
    """One person tightens; loosening needs a second, which W1 does not have,
    so it is refused (ADR-0123, Amendments 2026-10-24)."""
    before, after = parse_route_class(current), parse_route_class(requested)
    if after == before:
        return "unchanged"
    if is_looser(after, before):
        raise _second_person("tenant", before, after)
    return "tightened"


def workspace_class_change(
    tenant_class: object, current: object | None, requested: object | None
) -> RouteClassChange:
    """A workspace class may only tighten its tenant's (422 otherwise, checked
    first), and `NULL` inherits. Going back to `NULL`, or to a looser class
    than the one it holds, is loosening and needs a second person."""
    tenant = parse_route_class(tenant_class)
    before = None if current is None else parse_route_class(current)
    after = None if requested is None else parse_route_class(requested)
    if after is not None and is_looser(after, tenant):
        raise DomainError(
            "Lộ trình của workspace không được lỏng hơn Lộ trình của công ty",
            details={
                "reason_code": ROUTE_CLASS_LOOSER_THAN_TENANT,
                "tenant": tenant,
                "requested": after,
            },
        )
    if after == before:
        return "unchanged"
    if after is None or (before is not None and is_looser(after, before)):
        raise _second_person("workspace", before, after)
    return "tightened"
