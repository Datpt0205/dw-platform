"""`CelCppEngine`: the one `ExpressionEngine`, on `cel-expr-python==0.1.3`
(ADR-0114 decision 2; workflow-nodes 01).

`check` runs in the caller's process (a compile costs about 317 µs, measured);
`evaluate` never does, because the binding holds the GIL while it evaluates:
it goes to an `EvaluatorPool` of two spawned processes under a 1 s clock.

A composition root builds one engine per process and calls `aclose()` at
shutdown; none does yet, because nothing reads the engine yet
(failure-modes #1): ticket 03 wires it for the API, workflow-engine for the
worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from dw_kernel.expressions import (
    CheckedExpression,
    ExpressionEnv,
    ExpressionError,
    ExpressionIssue,
    JsonValue,
)
from dw_studio.core.adapters.cel.compiler import (
    CACHE_ENTRIES,
    CompileError,
    Compiler,
    ProgramKey,
    require_library,
)
from dw_studio.core.adapters.cel.evaluator import EvalRequest
from dw_studio.core.adapters.cel.pool import EvaluatorPool
from dw_studio.core.adapters.cel.schema import result_type

POOL_SIZE = 2
WALL_CLOCK_S = 1.0


class CelCppEngine:
    def __init__(
        self,
        *,
        pool_size: int = POOL_SIZE,
        wall_clock_s: float = WALL_CLOCK_S,
        cache_entries: int = CACHE_ENTRIES,
    ) -> None:
        self._compiler = Compiler(cache_entries)
        self._pool = EvaluatorPool(pool_size, wall_clock_s)

    def check(self, source: str, env: ExpressionEnv) -> CheckedExpression | list[ExpressionIssue]:
        try:
            program, bound = self._compiler.compile(source, env)
        except CompileError as failed:
            return failed.issues
        found = result_type(program.return_type(), bound.schema)
        if found is None:
            return [
                ExpressionIssue(
                    "other",
                    None,
                    None,
                    None,
                    f"the result type {program.return_type().name()} has no JSON form; "
                    "unwrap an optional with orValue() or value()",
                )
            ]
        return CheckedExpression(source, env, found)

    async def evaluate(
        self, checked: CheckedExpression, activation: Mapping[str, object]
    ) -> JsonValue | ExpressionError:
        require_library(checked.env)
        _refuse_naive_datetimes(activation)
        return await self._pool.run(EvalRequest(checked.source, checked.env, dict(activation)))

    async def aclose(self) -> None:
        await self._pool.aclose()

    def cached_program_keys(self) -> list[ProgramKey]:
        """The compiled-program cache of this (the caller's) process, oldest
        first: what R3.7's test reads."""
        return self._compiler.program_keys()


def _refuse_naive_datetimes(value: object) -> None:
    """A naive `datetime` is read in the host's zone by the binding (measured:
    01:30 naive gives `getHours()` 18 on a UTC+7 host and 1 in a UTC
    container), so it is a programming error, refused before it is sent."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("an activation datetime must carry its zone")
    elif isinstance(value, Mapping):
        for item in value.values():
            _refuse_naive_datetimes(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _refuse_naive_datetimes(item)
