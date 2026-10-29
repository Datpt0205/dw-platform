"""The purge order is derived from foreign keys, never declared.

foundations-hardening R11.4, R11.5, R11.8.

`order_purge_steps` is a pure function of the steps and the catalog's foreign
keys, so the cases the catalog can produce are written here as rows; the
integration suite runs the same cases against real constraints.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import pytest

from dw_platform.adapters.persistence.offboarding import (
    OffboardingPurgeStep,
    OffboardingPurgeSteps,
    OffboardingRefusedError,
    order_purge_steps,
)

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Fk:
    conname: str
    referencing: str
    referenced: str
    confdeltype: str


async def _noop(_session: object, _tenant: uuid.UUID) -> None:
    return None


def _step(name: str, *tables: str) -> OffboardingPurgeStep:
    return OffboardingPurgeStep(name=name, tables=frozenset(tables or (name,)), run=_noop)


def _names(steps: list[OffboardingPurgeStep]) -> list[str]:
    return [s.name for s in steps]


def test_a_restrict_edge_runs_the_referencing_step_first_against_name_order() -> None:
    # Names sort the other way round from the edge: only the derivation can get this right.
    steps = [_step("t.a_parent"), _step("t.z_child")]
    fks = [_Fk("fk_child_parent", "t.z_child", "t.a_parent", "r")]
    assert _names(order_purge_steps(steps, fks)) == ["t.z_child", "t.a_parent"]


def test_a_no_action_edge_orders_like_restrict() -> None:
    steps = [_step("t.a_parent"), _step("t.z_child")]
    fks = [_Fk("fk_child_parent", "t.z_child", "t.a_parent", "a")]
    assert _names(order_purge_steps(steps, fks)) == ["t.z_child", "t.a_parent"]


def test_a_cascade_edge_orders_nothing() -> None:
    steps = [_step("t.a_parent"), _step("t.z_child")]
    fks = [_Fk("fk_child_parent", "t.z_child", "t.a_parent", "c")]
    assert _names(order_purge_steps(steps, fks)) == ["t.a_parent", "t.z_child"]


def test_an_edge_reached_through_cascade_is_carried_to_the_step_that_cascades() -> None:
    # t.c_only loses rows only by CASCADE from t.y_source; it RESTRICTs t.b_target.
    steps = [_step("t.b_target"), _step("t.y_source")]
    fks = [
        _Fk("fk_c_source", "t.c_only", "t.y_source", "c"),
        _Fk("fk_c_target", "t.c_only", "t.b_target", "r"),
    ]
    assert _names(order_purge_steps(steps, fks)) == ["t.y_source", "t.b_target"]


def test_an_edge_inside_one_step_orders_nothing() -> None:
    steps = [_step("fn.purge_both", "t.one", "t.two")]
    fks = [_Fk("fk_two_one", "t.two", "t.one", "r")]
    assert _names(order_purge_steps(steps, fks)) == ["fn.purge_both"]


def test_a_cycle_refuses_and_names_its_foreign_keys() -> None:
    steps = [_step("t.left"), _step("t.right")]
    fks = [
        _Fk("fk_left_right", "t.left", "t.right", "r"),
        _Fk("fk_right_left", "t.right", "t.left", "r"),
    ]
    with pytest.raises(OffboardingRefusedError) as refused:
        order_purge_steps(steps, fks)
    assert "fk_left_right" in str(refused.value)
    assert "fk_right_left" in str(refused.value)


def test_unconnected_steps_keep_name_order() -> None:
    steps = [_step("t.b"), _step("t.a"), _step("t.c")]
    assert _names(order_purge_steps(steps, [])) == ["t.a", "t.b", "t.c"]


def test_registering_two_steps_for_one_table_is_refused() -> None:
    registry = OffboardingPurgeSteps()
    registry.register(_step("fn.first", "t.shared"))
    with pytest.raises(ValueError, match=re.escape("t.shared")):
        registry.register(_step("fn.second", "t.shared", "t.other"))


def test_registering_a_name_twice_is_refused() -> None:
    registry = OffboardingPurgeSteps()
    registry.register(_step("fn.first", "t.one"))
    with pytest.raises(ValueError, match=re.escape("fn.first")):
        registry.register(_step("fn.first", "t.two"))
