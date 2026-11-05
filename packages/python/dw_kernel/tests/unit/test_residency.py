"""The residency decision, one owner per fact (compliance-pdpl R2.2, R2.4, R2.7;
ADR-0123 decisions 3-5): the strictest class wins, `vn_only` takes only `vn`,
an undeclared location is foreign, and a class only tightens with one person."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager, nullcontext

import pytest

from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.residency import (
    PLATFORM_SCOPE,
    RESIDENCY_SPAN,
    ROUTE_CLASSES,
    Destination,
    ResidencyGate,
    ResidencyRefusedError,
    RouteClass,
    TenantRouteScope,
    UnknownRouteClassError,
    admits,
    effective_route_class,
    tenant_class_change,
    workspace_class_change,
)

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()
VN = Destination("rerank", "vn", "fpt_cloud")
FOREIGN = Destination("rerank", "foreign", "openai")
UNDECLARED = Destination("transcription", None, None)


class _Reader:
    def __init__(self, tenant_class: str, workspace_class: str | None = None) -> None:
        self.answer = (tenant_class, workspace_class)
        self.asked: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    async def route_classes(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID | None
    ) -> tuple[str, str | None]:
        self.asked.append((tenant_id, workspace_id))
        return self.answer


class _Unreadable:
    async def route_classes(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID | None
    ) -> tuple[str, str | None]:
        raise LookupError("RLS returned no row")


class _Spans:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, object]]] = []

    def span(self, name: str, attributes: dict[str, object]) -> AbstractContextManager[None]:
        self.spans.append((name, dict(attributes)))
        return nullcontext()


class _Run:
    """A run's scope: its class pinned at admission."""

    def __init__(self, route_class: str) -> None:
        self.route_class = route_class


def test_the_classes_are_listed_strictest_first() -> None:
    assert ROUTE_CLASSES == ("vn_only", "cross_border_minimised", "cross_border_full")


@pytest.mark.parametrize(
    ("tenant", "workspace", "version", "expected"),
    [
        ("cross_border_full", None, None, "cross_border_full"),
        ("cross_border_full", "cross_border_minimised", None, "cross_border_minimised"),
        ("cross_border_full", None, "vn_only", "vn_only"),
        ("vn_only", "cross_border_full", "cross_border_full", "vn_only"),
        ("cross_border_minimised", "cross_border_full", None, "cross_border_minimised"),
    ],
)
def test_the_strictest_of_the_three_wins(
    tenant: str, workspace: str | None, version: str | None, expected: str
) -> None:
    assert effective_route_class(tenant, workspace, version) == expected


@pytest.mark.parametrize(
    ("tenant", "workspace", "version"),
    [("open", None, None), ("vn_only", "VN_ONLY", None), ("vn_only", None, "")],
)
def test_a_value_outside_the_three_is_an_error_never_a_loose_class(
    tenant: str, workspace: str | None, version: str | None
) -> None:
    with pytest.raises(UnknownRouteClassError):
        effective_route_class(tenant, workspace, version)


@pytest.mark.parametrize(
    ("route_class", "location", "admitted"),
    [
        ("vn_only", "vn", True),
        ("vn_only", "foreign", False),
        ("vn_only", None, False),
        ("vn_only", "VN", False),
        # Refused abroad until the pseudonymiser exists (W2).
        ("cross_border_minimised", "vn", True),
        ("cross_border_minimised", "foreign", False),
        ("cross_border_full", "foreign", True),
        ("cross_border_full", None, True),
    ],
)
def test_admits(route_class: RouteClass, location: str | None, admitted: bool) -> None:
    assert admits(route_class, location) is admitted


async def test_a_run_s_pinned_class_is_read_without_asking_the_database() -> None:
    reader = _Reader("cross_border_full")
    gate = ResidencyGate(classes=reader)

    with pytest.raises(ResidencyRefusedError) as refused:
        await gate.check(_Run("vn_only"), FOREIGN)

    assert refused.value.details["reason_code"] == "residency_refused"
    assert reader.asked == []


async def test_an_unknown_pinned_class_refuses() -> None:
    with pytest.raises(ResidencyRefusedError):
        await ResidencyGate(classes=_Reader("vn_only")).check(_Run("anywhere"), VN)


async def test_a_call_outside_a_run_reads_the_tenant_and_the_workspace() -> None:
    reader = _Reader("cross_border_full", "vn_only")
    gate = ResidencyGate(classes=reader)
    scope = TenantRouteScope(tenant_id=TENANT, workspace_id=WORKSPACE)

    await gate.check(scope, VN)
    with pytest.raises(ResidencyRefusedError):
        await gate.check(scope, FOREIGN)

    assert reader.asked == [(TENANT, WORKSPACE), (TENANT, WORKSPACE)]


async def test_an_unreadable_row_refuses() -> None:
    gate = ResidencyGate(classes=_Unreadable())
    with pytest.raises(ResidencyRefusedError) as refused:
        await gate.check(TenantRouteScope(tenant_id=TENANT, workspace_id=WORKSPACE), VN)
    assert refused.value.details["reason"] == "unreadable"


async def test_a_strange_value_in_the_row_refuses() -> None:
    gate = ResidencyGate(classes=_Reader("everywhere"))
    with pytest.raises(ResidencyRefusedError):
        await gate.check(TenantRouteScope(tenant_id=TENANT, workspace_id=None), VN)


async def test_the_platform_s_own_evaluation_runs_vn_only() -> None:
    gate = ResidencyGate(classes=_Unreadable())
    await gate.check(PLATFORM_SCOPE, VN)
    with pytest.raises(ResidencyRefusedError):
        await gate.check(PLATFORM_SCOPE, FOREIGN)


async def test_an_undeclared_destination_is_foreign() -> None:
    gate = ResidencyGate(classes=_Reader("vn_only"))
    with pytest.raises(ResidencyRefusedError) as refused:
        await gate.check(_Run("vn_only"), UNDECLARED)
    assert refused.value.details["data_location"] is None


async def test_admitted_keeps_the_admitted_destinations_in_order() -> None:
    gate = ResidencyGate(classes=_Reader("vn_only"))
    assert await gate.admitted(_Run("vn_only"), [FOREIGN, VN, UNDECLARED, VN]) == [VN, VN]
    with pytest.raises(ResidencyRefusedError):
        await gate.admitted(_Run("vn_only"), [FOREIGN, UNDECLARED])


async def test_every_check_writes_a_span_with_identifiers_only() -> None:
    spans = _Spans()
    gate = ResidencyGate(classes=_Reader("vn_only"), telemetry=spans)

    await gate.admitted(_Run("vn_only"), [VN, FOREIGN])

    assert spans.spans == [
        (
            RESIDENCY_SPAN,
            {
                "dw.route_class": "vn_only",
                "dw.data_location": "vn",
                "dw.processor": "fpt_cloud",
                "dw.residency.admitted": True,
            },
        ),
        (
            RESIDENCY_SPAN,
            {
                "dw.route_class": "vn_only",
                "dw.data_location": "foreign",
                "dw.processor": "openai",
                "dw.residency.admitted": False,
            },
        ),
    ]


# ---- changing a class ---------------------------------------------------------


def test_one_person_tightens_a_tenant() -> None:
    assert tenant_class_change("cross_border_full", "vn_only") == "tightened"
    assert tenant_class_change("vn_only", "vn_only") == "unchanged"


@pytest.mark.parametrize("requested", ["cross_border_minimised", "cross_border_full"])
def test_loosening_a_tenant_needs_a_second_person(requested: str) -> None:
    with pytest.raises(ConflictError) as refused:
        tenant_class_change("vn_only", requested)
    assert refused.value.details["reason_code"] == "second_person_required"


def test_a_workspace_tightens_from_inheriting() -> None:
    assert workspace_class_change("cross_border_full", None, "vn_only") == "tightened"
    assert workspace_class_change("vn_only", None, "vn_only") == "tightened"
    assert workspace_class_change("vn_only", "vn_only", "vn_only") == "unchanged"
    assert workspace_class_change("vn_only", None, None) == "unchanged"


@pytest.mark.parametrize(
    ("tenant", "current", "requested"),
    [
        ("vn_only", "vn_only", None),
        ("cross_border_full", "vn_only", None),
        ("cross_border_full", "vn_only", "cross_border_full"),
        ("cross_border_full", "vn_only", "cross_border_minimised"),
    ],
)
def test_loosening_a_workspace_or_going_back_to_null_needs_a_second_person(
    tenant: str, current: str, requested: str | None
) -> None:
    with pytest.raises(ConflictError) as refused:
        workspace_class_change(tenant, current, requested)
    assert refused.value.details["reason_code"] == "second_person_required"


def test_a_workspace_looser_than_its_tenant_is_invalid_before_any_loosening_check() -> None:
    with pytest.raises(DomainError) as refused:
        workspace_class_change("vn_only", "vn_only", "cross_border_full")
    assert not isinstance(refused.value, ConflictError)
    assert refused.value.details["reason_code"] == "route_class_looser_than_tenant"
