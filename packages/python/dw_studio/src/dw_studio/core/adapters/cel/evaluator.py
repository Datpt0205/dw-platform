"""What an evaluator process runs (workflow-nodes 01 step 2).

The binding holds the GIL for the whole of an evaluation, and its iteration
budget bounds iterations, not time: a 77-byte expression held a process 5.6 s
under the budget (FOG-50, ADR-0114 Amendments 2026-11-03). So no evaluation
runs in the caller's process; it runs here, where the caller can kill it.

Every failure leaves as an `ExpressionError` without the binding's text, which
can hold a value (`NOT_FOUND: Key not found in map : "nope"`).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import cast

from cel_expr_python import cel

from dw_kernel.expressions import (
    ERROR_STATUSES,
    ErrorStatus,
    ExpressionEnv,
    ExpressionError,
    JsonValue,
)
from dw_studio.core.adapters.cel.compiler import CompileError, Compiler
from dw_studio.core.adapters.cel.schema import (
    ActivationError,
    UnrepresentableResultError,
    binding_activation,
    json_size,
    to_json,
)

MAX_RESULT_BYTES = 256 * 1024
# Linux only: a 2 KiB expression can build a string of many MB before the size
# cap reads it (measured: an 8 MB concatenation in 23 ms). The limit kills the
# evaluator, never the caller. Windows has no such limit.
ADDRESS_SPACE_BYTES = 512 * 1024 * 1024

STARTED = "started"

_OUT_OF_MEMORY = ExpressionError("expression_budget_exceeded", "RESOURCE_EXHAUSTED")


@dataclass(frozen=True, slots=True)
class EvalRequest:
    source: str
    env: ExpressionEnv
    activation: Mapping[str, object]


def status_of(text: str) -> ErrorStatus:
    """The status a binding's error text begins with; `UNKNOWN` otherwise."""
    prefix = text.split(":", 1)[0].strip()
    return cast(ErrorStatus, prefix) if prefix in ERROR_STATUSES else "UNKNOWN"


def evaluate(compiler: Compiler, request: EvalRequest) -> JsonValue | ExpressionError:
    try:
        program, bound = compiler.compile(request.source, request.env)
    except CompileError:
        return ExpressionError("expression_error", "INVALID_ARGUMENT")
    try:
        data = binding_activation(bound.schema, request.env, request.activation)
    except ActivationError:
        return ExpressionError("expression_error", "INVALID_ARGUMENT")
    try:
        value = program.eval(data=data)
    except MemoryError:
        # The address-space limit stopped it (Linux): the 77-byte quadratic map
        # of WN12 peaks at 1.7 GB and is stopped here in about 0.8 s, before
        # the clock (measured in python:3.12-slim-bookworm).
        return _OUT_OF_MEMORY
    except RuntimeError as exc:
        if "Iteration budget exceeded" in str(exc):
            return ExpressionError("expression_budget_exceeded", "INTERNAL")
        return ExpressionError("expression_error", status_of(str(exc)))
    if value.type() == cel.Type.ERROR:
        return ExpressionError("expression_error", status_of(str(value.value())))
    try:
        result = to_json(value.plain_value())
        size = json_size(result)
    except MemoryError:
        return _OUT_OF_MEMORY
    except (UnrepresentableResultError, TypeError, ValueError):
        return ExpressionError("expression_error", "INVALID_ARGUMENT")
    if size > MAX_RESULT_BYTES:
        return ExpressionError("expression_budget_exceeded", "RESOURCE_EXHAUSTED")
    return result


def worker_main(conn: Connection) -> None:
    """The evaluator loop: acknowledge each request as it arrives, which
    starts the caller's clock, then answer it. `None` stops the loop."""
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))
    compiler = Compiler()
    while True:
        try:
            request = conn.recv()
        except (EOFError, OSError):
            return
        if request is None:
            return
        conn.send(STARTED)
        try:
            outcome = evaluate(compiler, request)
        except Exception:
            # A defect of this adapter, not of the expression: answered as
            # `INTERNAL`, and the evaluator stays up.
            outcome = ExpressionError("expression_error", "INTERNAL")
        conn.send(outcome)
