import pickle
import uuid

import pytest

from dw_kernel.expressions import (
    BOOL,
    DW_CEL_LIBRARY,
    ERROR_STATUSES,
    INT,
    STRING,
    ExpressionEnv,
    ListType,
    MapType,
    OptionalType,
    describe,
    object_type,
)
from dw_kernel.ids import TenantId

pytestmark = pytest.mark.unit

A = TenantId(uuid.UUID("00000000-0000-4000-8000-00000000000a"))
B = TenantId(uuid.UUID("00000000-0000-4000-8000-00000000000b"))


def test_describe_is_canonical() -> None:
    first = object_type("Lead", {"phone": STRING, "score": INT})
    second = object_type("Lead", {"score": INT, "phone": STRING})
    assert first == second
    assert describe(first) == "object Lead{phone: string, score: int}"
    assert describe(ListType(MapType(OptionalType(BOOL)))) == "list[map[string, optional[bool]]]"


def test_env_hash_is_sorted_by_name_and_leaves_out_the_tenant() -> None:
    one = ExpressionEnv(A, {"b": INT, "a": STRING}, DW_CEL_LIBRARY)
    two = ExpressionEnv(B, {"a": STRING, "b": INT}, DW_CEL_LIBRARY)
    assert one.env_hash() == two.env_hash()
    assert list(one.variables) == ["a", "b"]
    other = ExpressionEnv(A, {"a": STRING, "b": BOOL}, DW_CEL_LIBRARY)
    assert other.env_hash() != one.env_hash()


def test_an_object_of_the_same_name_and_another_shape_hashes_apart() -> None:
    one = ExpressionEnv(A, {"x": object_type("Lead", {"a": INT})}, DW_CEL_LIBRARY)
    two = ExpressionEnv(A, {"x": object_type("Lead", {"a": STRING})}, DW_CEL_LIBRARY)
    assert one.env_hash() != two.env_hash()


def test_an_env_crosses_a_process_boundary_whole() -> None:
    env = ExpressionEnv(A, {"x": object_type("Lead", {"a": INT})}, DW_CEL_LIBRARY)
    copy = pickle.loads(pickle.dumps(env))
    assert copy == env
    assert copy.env_hash() == env.env_hash()
    assert copy.tenant_id == A


def test_the_variables_are_frozen() -> None:
    env = ExpressionEnv(None, {"a": INT}, DW_CEL_LIBRARY)
    with pytest.raises(TypeError):
        env.variables["b"] = INT  # type: ignore[index]


def test_the_library_pins_a_minor_version() -> None:
    assert DW_CEL_LIBRARY == "dw.cel/v1.0"
    assert "DEADLINE_EXCEEDED" in ERROR_STATUSES
    assert "UNIMPLEMENTED" not in ERROR_STATUSES
