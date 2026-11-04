"""A pool of evaluator processes with a wall clock per evaluation
(workflow-nodes R3.4, WN12; ADR-0114 decision 4).

- Processes start with `spawn`, never `fork`: the caller has threads.
- The pool starts on its first evaluation, all of its processes at once.
- A request waits in FIFO order for a free process. The clock starts when the
  process acknowledges the request, so neither the wait nor a process's start
  counts against it.
- Past the clock, the caller kills the process, starts a replacement and
  answers `expression_budget_exceeded` (`DEADLINE_EXCEEDED`). A process that
  dies for another reason is replaced too, and that evaluation answers
  `expression_error` (`INTERNAL`).

The caller waits on a thread of the pool's own, so its event loop keeps
running while an evaluation holds an evaluator; the pool has exactly one
thread per process, so a thread that runs always finds a free process and the
executor's queue is the FIFO queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

from dw_kernel.expressions import ExpressionError, JsonValue
from dw_studio.core.adapters.cel.evaluator import STARTED, EvalRequest, worker_main

_DEADLINE = ExpressionError("expression_budget_exceeded", "DEADLINE_EXCEEDED")
_DIED = ExpressionError("expression_error", "INTERNAL")

# How long a process may take to start and take its request; generous, since
# it is the import of the binding on a busy host, and it is not the clock.
_START_TIMEOUT_S = 60.0
_STOP_TIMEOUT_S = 2.0


@dataclass(slots=True)
class _Evaluator:
    process: BaseProcess
    conn: Connection


class EvaluatorPool:
    def __init__(self, size: int, wall_clock_s: float) -> None:
        if size < 1:
            raise ValueError("an evaluator pool needs at least one process")
        self._size = size
        self._wall_clock_s = wall_clock_s
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._free: list[_Evaluator | None] = []
        self._started = False
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="dw-cel-eval")

    async def run(self, request: EvalRequest) -> JsonValue | ExpressionError:
        if self._closed:
            raise RuntimeError("the evaluator pool is closed")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._run_blocking, request)

    async def aclose(self) -> None:
        """Stop every evaluator; an evaluation in flight finishes first."""
        with self._lock:
            self._closed = True
            idle, self._free = self._free, []
        loop = asyncio.get_running_loop()
        # In-flight evaluations finish and stop their evaluators in `_give`.
        await loop.run_in_executor(None, self._executor.shutdown, True)
        for evaluator in idle:
            if evaluator is not None:
                await loop.run_in_executor(None, self._stop, evaluator)

    # -- on the pool's threads ------------------------------------------------

    def _run_blocking(self, request: EvalRequest) -> JsonValue | ExpressionError:
        evaluator = self._take()
        outcome: JsonValue | ExpressionError = _DIED
        try:
            if evaluator is None:
                evaluator = self._spawn()
            evaluator.conn.send(request)
            if not evaluator.conn.poll(_START_TIMEOUT_S) or evaluator.conn.recv() != STARTED:
                raise EOFError("the evaluator did not take the request")
            if not evaluator.conn.poll(self._wall_clock_s):
                outcome = _DEADLINE
                raise TimeoutError
            outcome = evaluator.conn.recv()
        except (EOFError, OSError, TimeoutError):
            # `outcome` stays `_DIED` unless the clock ran out. Either way the
            # process is gone and a replacement takes its place.
            if evaluator is not None:
                self._kill(evaluator)
            evaluator = None if self._closed else self._spawn()
        finally:
            self._give(evaluator)
        return outcome

    def _take(self) -> _Evaluator | None:
        with self._lock:
            if not self._started:
                self._started = True
                self._free = [self._spawn() for _ in range(self._size)]
            return self._free.pop(0) if self._free else None

    def _give(self, evaluator: _Evaluator | None) -> None:
        with self._lock:
            if not self._closed:
                self._free.append(evaluator)
                return
        if evaluator is not None:
            self._stop(evaluator)

    def _spawn(self) -> _Evaluator:
        parent, child = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=worker_main, args=(child,), name="dw-cel-evaluator", daemon=True
        )
        process.start()
        child.close()
        return _Evaluator(process, parent)

    @staticmethod
    def _kill(evaluator: _Evaluator) -> None:
        evaluator.process.kill()
        evaluator.process.join(_STOP_TIMEOUT_S)
        evaluator.conn.close()

    @classmethod
    def _stop(cls, evaluator: _Evaluator) -> None:
        with contextlib.suppress(OSError, ValueError):
            evaluator.conn.send(None)
        evaluator.process.join(_STOP_TIMEOUT_S)
        if evaluator.process.is_alive():
            cls._kill(evaluator)
        else:
            evaluator.conn.close()
