"""`CelCppEngine`'s own parts, beside the contract suite: its compiled-program
cache (R3.7, WN36), its evaluator pool and its process limits (R3.4, WN12)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime

import pytest

from dw_kernel.expressions import (
    DW_CEL_LIBRARY,
    INT,
    CheckedExpression,
    ExpressionEnv,
    ExpressionError,
    ListType,
    object_type,
)
from dw_kernel.ids import TenantId
from dw_studio.core.adapters.cel import CelCppEngine
from dw_studio.core.adapters.cel.compiler import LruCache

pytestmark = pytest.mark.unit

TENANT_A = TenantId(uuid.UUID("00000000-0000-4000-8000-00000000000a"))
TENANT_B = TenantId(uuid.UUID("00000000-0000-4000-8000-00000000000b"))
TRIGGER = object_type("Trigger", {"amount": INT})
QUADRATIC_77 = "(" + "+".join(["xs"] * 19) + ").map(a, a+1).size()"


@pytest.fixture
def engine() -> Iterator[CelCppEngine]:
    adapter = CelCppEngine()
    yield adapter
    asyncio.run(adapter.aclose())


def checked(engine: CelCppEngine, source: str, env: ExpressionEnv) -> CheckedExpression:
    result = engine.check(source, env)
    assert isinstance(result, CheckedExpression), result
    return result


def test_two_tenants_never_share_a_compiled_program(engine: CelCppEngine) -> None:
    source = "trigger.amount > 1000000"
    for tenant in (TENANT_A, TENANT_B, None):
        checked(engine, source, ExpressionEnv(tenant, {"trigger": TRIGGER}, DW_CEL_LIBRARY))
    keys = engine.cached_program_keys()
    assert [key.tenant_id for key in keys] == [str(TENANT_A), str(TENANT_B), None]
    assert len({(key.library, key.env_hash, key.source_sha256) for key in keys}) == 1
    # The same tenant again is a hit, not a fourth entry.
    checked(engine, source, ExpressionEnv(TENANT_A, {"trigger": TRIGGER}, DW_CEL_LIBRARY))
    assert len(engine.cached_program_keys()) == 3


def test_the_env_hash_is_the_shape_not_the_tenant() -> None:
    a = ExpressionEnv(TENANT_A, {"trigger": TRIGGER, "n": INT}, DW_CEL_LIBRARY)
    b = ExpressionEnv(TENANT_B, {"n": INT, "trigger": TRIGGER}, DW_CEL_LIBRARY)
    assert a.env_hash() == b.env_hash()


def test_the_cache_is_bounded() -> None:
    cache: LruCache[str, int] = LruCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert cache.keys() == ["a", "c"]


async def test_check_runs_here_and_a_naive_datetime_never_reaches_the_pool(
    engine: CelCppEngine,
) -> None:
    env = ExpressionEnv(TENANT_A, {"trigger": TRIGGER}, DW_CEL_LIBRARY)
    result = checked(engine, "trigger.amount > 1", env)
    with pytest.raises(ValueError, match="zone"):
        await engine.evaluate(result, {"trigger": {"amount": 2}, "at": [datetime(2026, 1, 1)]})
    assert engine._pool._started is False
    assert engine._pool._context.get_start_method() == "spawn"


async def test_an_evaluator_that_dies_is_replaced(engine: CelCppEngine) -> None:
    env = ExpressionEnv(TENANT_A, {"n": INT}, DW_CEL_LIBRARY)
    result = checked(engine, "n + 1", env)
    assert await engine.evaluate(result, {"n": 1}) == 2
    for evaluator in list(engine._pool._free):
        assert evaluator is not None
        evaluator.process.kill()
        evaluator.process.join(5)
    # Each dead evaluator answers its one request `INTERNAL` and is replaced.
    died = ExpressionError("expression_error", "INTERNAL")
    assert await engine.evaluate(result, {"n": 1}) == died
    assert await engine.evaluate(result, {"n": 1}) == died
    answers = await asyncio.gather(*(engine.evaluate(result, {"n": n}) for n in range(4)))
    assert answers == [1, 2, 3, 4]


async def test_a_closed_engine_stops_its_evaluators() -> None:
    engine = CelCppEngine()
    env = ExpressionEnv(None, {"n": INT}, DW_CEL_LIBRARY)
    result = checked(engine, "n * 3", env)
    assert await engine.evaluate(result, {"n": 2}) == 6
    processes = [e.process for e in engine._pool._free if e is not None]
    assert len(processes) == 2
    await engine.aclose()
    assert all(not process.is_alive() for process in processes)
    with pytest.raises(RuntimeError, match="closed"):
        await engine.evaluate(result, {"n": 2})


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS exists on Linux only")
async def test_the_address_space_limit_stops_a_memory_bomb_in_the_evaluator(
    engine: CelCppEngine,
) -> None:
    # Measured in python:3.12-slim-bookworm: this peaks at 1.7 GB unlimited and
    # stops at the 512 MiB limit in about 0.8 s, before the clock.
    env = ExpressionEnv(TENANT_A, {"xs": ListType(INT)}, DW_CEL_LIBRARY)
    result = checked(engine, QUADRATIC_77, env)
    assert await engine.evaluate(result, {"xs": list(range(500))}) == ExpressionError(
        "expression_budget_exceeded", "RESOURCE_EXHAUSTED"
    )
    assert await engine.evaluate(result, {"xs": [1]}) == 19
