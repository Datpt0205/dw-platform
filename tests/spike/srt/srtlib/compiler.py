"""Option A of V4.34, prototyped: the step tree lowered to a LangGraph
`StateGraph` the way ADR-0112 decision 4 states it, with decision 5's node
wrapper. What wf-lite's `compile.py` already ships is followed as it is (a list
is a chain, a switch is a conditional edge whose lanes meet at a no-op merge
node, a wait is `interrupt()` on the first line of its own node); what
workflow-engine/03 and /06 have still to build is prototyped here:

- each lane of `logic.parallel@1` is a subgraph node with a state schema of its
  own, exporting only its own steps' channels, the lanes meeting at the join
  through one waiting edge (`add_edge([...], join)`);
- `logic.loop@1` is a bounded do-while cycle with its counter in `iter__<id>`,
  `logic.break@1` an edge to the loop's exit;
- `logic.map@1` is one `Send` per chunk of 20 items into a fan-in with
  `defer=True`;
- `flow.subworkflow@1` starts a child run, then waits in a node of its own;
- the wrapper owns the run-level step counter, retry with backoff, timeout,
  `on_error` (`fail`, `continue`, `route`, `incident`) and the park on
  `outcome_review`, which applies no `on_error`.

`compiler` names the version (T4): `c2` adds a channel and a no-op node in front
of nothing a parked run waits in, `c2-renamed` renames the wait nodes.
"""

from __future__ import annotations

import asyncio
import itertools
import operator
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send, interrupt

from dw_kernel.dispatch import NotDispatchedError, RejectedError

from .doc import SrtDoc, SrtStep, lanes, walk

CHUNK = 20
RETRYABLE_CODES = frozenset({"429", "503", "timeout_before_send"})


# ---------------------------------------------------------------- signals --


class LeaseLostError(Exception):
    """A fenced write found another holder: this process stops the run."""


class RunCancelledError(Exception):
    """The run was cancelled; the step stops."""


class LimitExceededError(Exception):
    """The run-level step counter passed `limits.max_steps` (decision 5)."""


class StepFailedError(Exception):
    def __init__(self, step_id: str, code: str) -> None:
        super().__init__(f"{code} at {step_id}")
        self.step_id = step_id
        self.code = code


class ParkError(Exception):
    """An attempt whose outcome is unknown and whose Action's `on_unknown` is
    `review`: the run parks on `outcome_review`, no `on_error` applies."""

    def __init__(self, kind: str, detail: Mapping[str, Any]) -> None:
        super().__init__(kind)
        self.kind = kind
        self.detail = dict(detail)


class TransientError(Exception):
    """A failure the wrapper may retry (a fake model's hiccup)."""


# ------------------------------------------------------------------ ports --


class StepRecord(Protocol):
    id: int
    seq: int | None
    status: str


class LanePort(Protocol):
    """What the wrapper writes to the run lane, every write fenced by the
    lease token (workflow-engine/04)."""

    async def step_started(
        self, ctx: RunCtx, node: str, step_id: str | None, kind: str, path: str, counted: bool
    ) -> StepRecord: ...

    async def step_ended(self, ctx: RunCtx, record_id: int, status: str, attempt: int) -> None: ...

    async def lease_ok(self, ctx: RunCtx) -> None: ...

    async def spawn_child(
        self, ctx: RunCtx, key: str, workflow: str, run_input: Mapping[str, Any]
    ) -> str: ...

    async def audit(self, ctx: RunCtx, action: str, details: Mapping[str, Any]) -> None: ...


class DoorPort(Protocol):
    async def external(
        self, ctx: RunCtx, step: SrtStep, key: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    async def internal(
        self, ctx: RunCtx, step: SrtStep, key: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]: ...


class CrashPort(Protocol):
    def at(self, point: str, step_id: str, ctx: RunCtx) -> None: ...


@dataclass
class RunCtx:
    run_id: str
    tenant_id: str
    workspace_id: str
    token: str
    worker: str
    lane: LanePort
    door: DoorPort
    crash: CrashPort
    run_input: dict[str, Any]
    max_steps: int
    depth: int
    compiler: str
    started: float = field(default_factory=time.perf_counter)


# ------------------------------------------------------------------- refs --


def resolve(value: Any, state: Mapping[str, Any], item: int | None = None) -> Any:
    if isinstance(value, Mapping):
        return {k: resolve(v, state, item) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, state, item) for v in value]
    if isinstance(value, str) and value.strip().startswith("{{"):
        inner = value.strip()[2:-2].strip()
        parts = inner.split(".")
        if parts[0] == "input":
            return (state.get("input") or {}).get(parts[1])
        if parts[0] == "steps":
            found = state.get(f"out__{parts[1]}") or {}
            return found.get(parts[2]) if len(parts) > 2 else found
        if parts[0] == "iter":
            return state.get(f"iter__{parts[1]}", 0)
        if parts[0] == "item":
            return item
    return value


def holds(condition: Mapping[str, Any], state: Mapping[str, Any], loop: str) -> bool:
    if "iter_lt" in condition:
        return int(state.get(f"iter__{loop}", 0)) < int(condition["iter_lt"])
    value = resolve(condition.get("ref"), state)
    if "eq" in condition:
        return bool(value == condition["eq"])
    if "ne" in condition:
        return bool(value != condition["ne"])
    return bool(condition.get("always", True))


# --------------------------------------------------------------- lowering --


Node = Callable[..., Awaitable[dict[str, Any]]]


class Lowering:
    def __init__(self, doc: SrtDoc, compiler: str = "c1") -> None:
        self.doc = doc
        self.compiler = compiler
        self.steps = {s.id: s for s in walk(doc.steps)}
        self.loops_of: dict[str, list[str]] = {}
        self.map_of: dict[str, str] = {}
        self._enclose(doc.steps, [])
        self.root_keys = self._keys()

    # ------------------------------------------------------------- shape --

    def _enclose(self, steps: Sequence[SrtStep], loops: list[str]) -> None:
        for step in steps:
            self.loops_of[step.id] = list(loops)
            for port, lane in lanes(step).items():
                inner = (
                    [*loops, step.id] if step.type == "logic.loop@1" and port == "body" else loops
                )
                if step.type == "logic.map@1":
                    for s in lane:
                        self.map_of[s.id] = step.id
                self._enclose(lane, inner)

    def _keys(self) -> dict[str, Any]:
        keys: dict[str, Any] = {"input": dict}
        if self.compiler.startswith("c2"):
            keys["engine_note"] = str  # an additive channel of the next compiler
        for step in self.steps.values():
            keys[f"out__{step.id}"] = dict
            keys[f"park__{step.id}"] = dict
            keys[f"err__{step.id}"] = bool
            if step.type == "logic.loop@1":
                keys[f"iter__{step.id}"] = int
            if step.type == "logic.map@1":
                keys[f"map__{step.id}"] = Annotated[list, operator.add]
        return keys

    def _owned(self, steps: Sequence[SrtStep]) -> dict[str, Any]:
        owned: dict[str, Any] = {}
        for step in walk(list(steps)):
            for prefix in ("out__", "park__", "err__", "iter__"):
                key = f"{prefix}{step.id}"
                if key in self.root_keys:
                    owned[key] = self.root_keys[key]
        return owned

    def _wait_name(self, step_id: str) -> str:
        return f"waitnode__{step_id}" if self.compiler == "c2-renamed" else f"wait__{step_id}"

    # ------------------------------------------------------------- build --

    def build(self) -> StateGraph:  # type: ignore[type-arg]
        state = TypedDict("RootState", self.root_keys, total=False)  # type: ignore[misc]
        graph: StateGraph = StateGraph(state, context_schema=RunCtx)  # type: ignore[type-arg,arg-type]
        first = self.chain(graph, self.doc.steps, END, loop_exit=None)
        if self.compiler.startswith("c2"):
            graph.add_node("engine__c2", self._record("engine__c2", "noop", {"engine_note": "c2"}))
            graph.add_edge(START, "engine__c2")
            graph.add_edge("engine__c2", first)
        else:
            graph.add_edge(START, first)
        return graph

    def chain(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        steps: Sequence[SrtStep],
        exit_node: str,
        *,
        loop_exit: str | None,
    ) -> str:
        if not steps:
            return exit_node
        blocks: list[tuple[str, str | None]] = []
        for step in steps:
            blocks.append(self.block(g, step, loop_exit=loop_exit))
            if blocks[-1][1] is None:  # a break: what follows it in the list never runs
                break
        for (_, last), (first, _) in itertools.pairwise(blocks):
            if last is not None:
                g.add_edge(last, first)
        if blocks[-1][1] is not None:
            g.add_edge(blocks[-1][1], exit_node)
        return blocks[0][0]

    def block(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
        *,
        loop_exit: str | None,
    ) -> tuple[str, str | None]:
        kind = step.type
        if kind == "logic.switch@1":
            return self._switch(g, step, loop_exit)
        if kind == "human.approval@1":
            return self._approval(g, step, loop_exit)
        if kind == "logic.parallel@1":
            return self._parallel(g, step)
        if kind == "logic.loop@1":
            return self._loop(g, step)
        if kind == "logic.map@1":
            return self._map(g, step)
        if kind == "logic.break@1":
            assert loop_exit is not None, "wf.break_outside_loop"
            name = f"brk__{step.id}"
            g.add_node(name, self._record(name, "break", {}, step_id=step.id))
            g.add_edge(name, loop_exit)
            return name, None
        if kind == "flow.subworkflow@1":
            return self._subworkflow(g, step)
        return self._simple(g, step, loop_exit)

    # -------------------------------------------------------- the blocks --

    def _simple(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
        loop_exit: str | None,
    ) -> tuple[str, str | None]:
        g.add_node(step.id, self.wrap(step, self._impl(step)))
        can_park = step.type == "tool.call@1" or step.on_error == "incident"
        if not can_park and step.on_error != "route":
            return step.id, step.id
        after = f"after__{step.id}"
        hold = self._wait_name(step.id)
        fail = f"fail__{step.id}"
        g.add_node(after, self._record(after, "merge", {}))
        error_first = (
            self.chain(g, lanes(step).get("error", []), after, loop_exit=loop_exit)
            if step.on_error == "route"
            else after
        )
        targets = sorted({after, hold, error_first})

        def route(state: Mapping[str, Any]) -> str:
            if state.get(f"park__{step.id}"):
                return hold
            if state.get(f"err__{step.id}"):
                return error_first
            return after

        g.add_conditional_edges(step.id, route, targets)
        g.add_node(hold, self._hold(step))
        g.add_node(fail, self._fail(step))
        g.add_edge(fail, END)

        def after_hold(state: Mapping[str, Any]) -> str:
            action = (state.get(f"out__{step.id}") or {}).get("_resolution")
            if action in ("retry", "resend"):
                return step.id
            if action == "received":
                return after
            return fail

        g.add_conditional_edges(hold, after_hold, sorted({step.id, after, fail}))
        return step.id, after

    def _switch(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
        loop_exit: str | None,
    ) -> tuple[str, str | None]:
        join = f"join__{step.id}"
        g.add_node(step.id, self.wrap(step, self._choose(step)))
        g.add_node(join, self._record(join, "merge", {}))
        targets = {
            port: self.chain(g, lane, join, loop_exit=loop_exit)
            for port, lane in lanes(step).items()
            if port != "error"
        }

        def route(state: Mapping[str, Any]) -> str:
            case = str((state.get(f"out__{step.id}") or {}).get("case"))
            return targets.get(f"cases.{case}", targets.get("default", join))

        g.add_conditional_edges(step.id, route, sorted({*targets.values(), join}))
        return step.id, join

    def _approval(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
        loop_exit: str | None,
    ) -> tuple[str, str | None]:
        wait, join = self._wait_name(step.id), f"join__{step.id}"
        config = step.config

        async def ask(
            state: Mapping[str, Any], ctx: RunCtx, path: str, attempt: int
        ) -> dict[str, Any]:
            return {
                "asked": {
                    "wait": "approval",
                    "step_id": step.id,
                    "assignees": list(config.get("assignees") or ["approver"]),
                    "rule": config.get("rule", "any"),
                    "path": path,
                }
            }

        g.add_node(step.id, self.wrap(step, ask))
        g.add_node(wait, self._wait(step, "approval"))
        g.add_node(join, self._record(join, "merge", {}))
        approved = self.chain(g, lanes(step).get("approved", []), join, loop_exit=loop_exit)
        rejected = self.chain(g, lanes(step).get("rejected", []), join, loop_exit=loop_exit)
        g.add_edge(step.id, wait)

        def after_wait(state: Mapping[str, Any]) -> str:
            decided = (state.get(f"out__{step.id}") or {}).get("approved")
            return approved if decided else rejected

        g.add_conditional_edges(wait, after_wait, sorted({approved, rejected}))
        return step.id, join

    def _parallel(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
    ) -> tuple[str, str | None]:
        fork, join = f"par__{step.id}", f"join__{step.id}"
        g.add_node(fork, self._record(fork, "fork", {}, step_id=step.id))
        g.add_node(join, self._record(join, "join", {}, step_id=step.id))
        names = []
        for port, lane in lanes(step).items():
            if port == "error":
                continue
            name = f"lane__{step.id}__{port}"
            g.add_node(name, self._lane_graph(lane).compile())
            g.add_edge(fork, name)
            names.append(name)
        g.add_edge(names, join)  # one waiting edge from the end of every lane
        return fork, join

    def _lane_graph(self, steps: Sequence[SrtStep]) -> StateGraph:  # type: ignore[type-arg]
        # The lane's state: the parent's last-value channels to read, never a
        # reducer key (it would add the parent's values again, ADR-0112
        # Context), and only its own steps' channels go back up.
        readable = {k: v for k, v in self.root_keys.items() if not k.startswith("map__")}
        state = TypedDict("LaneState", readable, total=False)  # type: ignore[misc]
        out = TypedDict("LaneOut", self._owned(steps), total=False)  # type: ignore[misc]
        sub: StateGraph = StateGraph(state, input_schema=state, output_schema=out)  # type: ignore[type-arg]
        first = self.chain(sub, steps, END, loop_exit=None)
        sub.add_edge(START, first)
        return sub

    def _loop(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
    ) -> tuple[str, str | None]:
        start, again = f"loopin__{step.id}", f"loopnext__{step.id}"
        check, out = f"loopend__{step.id}", f"loopout__{step.id}"
        counter = f"iter__{step.id}"
        maximum = int(step.config["max_iterations"])
        condition = step.config.get("while") or {"always": True}
        g.add_node(start, self._record(start, "loop", {counter: 1}, step_id=step.id))
        g.add_node(again, self._record(again, "loop", {}, step_id=step.id, bump=counter))
        g.add_node(check, self._record(check, "loop_check", {}))
        g.add_node(out, self._record(out, "merge", {}))
        body = self.chain(g, lanes(step).get("body", []), check, loop_exit=out)
        g.add_edge(start, body)
        g.add_edge(again, body)
        reached_lane = lanes(step).get("max_reached", [])
        fail = f"fail__{step.id}"
        reached = self.chain(g, reached_lane, out, loop_exit=None) if reached_lane else fail
        if not reached_lane:
            g.add_node(fail, self._fail(step, "loop_limit_reached"))
            g.add_edge(fail, END)

        def route(state: Mapping[str, Any]) -> str:
            if not holds(condition, state, step.id):
                return out
            if int(state.get(counter, 0)) >= maximum:
                return reached
            return again

        g.add_conditional_edges(check, route, sorted({out, again, reached}))
        return start, out

    def _map(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
    ) -> tuple[str, str | None]:
        fan, chunk, join = f"map__{step.id}", f"mapchunk__{step.id}", f"mapjoin__{step.id}"
        count = int(step.config.get("count", 100))
        body = lanes(step)["body"][0]
        impl = self._impl(body)
        g.add_node(fan, self._record(fan, "fork", {}, step_id=step.id))

        def sends(state: Mapping[str, Any]) -> list[Send]:
            return [
                Send(chunk, {"input": state.get("input"), "_chunk": [lo, min(lo + CHUNK, count)]})
                for lo in range(0, count, CHUNK)
            ]

        g.add_conditional_edges(fan, sends, [chunk])
        wrap_item = self.wrap(body, impl)

        async def run_chunk(arg: Mapping[str, Any], runtime: Runtime[RunCtx]) -> dict[str, Any]:
            lo, hi = arg["_chunk"]
            results = []
            for item in range(lo, hi):
                update = await wrap_item({**arg, "_item": item}, runtime)
                results.append(update.get(f"out__{body.id}"))
            return {f"map__{step.id}": results}

        g.add_node(chunk, run_chunk)  # type: ignore[arg-type]
        g.add_node(join, self._record(join, "join", {}, step_id=step.id), defer=True)
        g.add_edge(chunk, join)
        return fan, join

    def _subworkflow(
        self,
        g: StateGraph,  # type: ignore[type-arg]
        step: SrtStep,
    ) -> tuple[str, str | None]:
        wait = self._wait_name(step.id)

        async def start(
            state: Mapping[str, Any], ctx: RunCtx, path: str, attempt: int
        ) -> dict[str, Any]:
            key = f"wf:{ctx.run_id}:{step.id}:{path}"
            child = await ctx.lane.spawn_child(
                ctx, key, str(step.config["workflow"]), resolve(step.config.get("input", {}), state)
            )
            return {"asked": {"wait": "child_run", "step_id": step.id, "child_run_id": child}}

        g.add_node(step.id, self.wrap(step, start))
        g.add_node(wait, self._wait(step, "child_run"))
        g.add_edge(step.id, wait)
        return step.id, wait

    # --------------------------------------------------------- the nodes --

    def _impl(
        self, step: SrtStep
    ) -> Callable[[Mapping[str, Any], RunCtx, str, int], Awaitable[dict[str, Any]]]:
        config = step.config

        if step.type == "ai.llm@1":

            async def llm(
                state: Mapping[str, Any], ctx: RunCtx, path: str, attempt: int
            ) -> dict[str, Any]:
                faults = (ctx.run_input.get("faults") or {}).get(step.id) or {}
                seconds = float(faults.get("seconds", config.get("seconds", 0.0)))
                if seconds:
                    await asyncio.sleep(seconds)
                if attempt <= int(faults.get("fail_times", 0)):
                    raise TransientError("model hiccup")
                size = int(config.get("size", 64))
                answer = resolve(config.get("answer", {}), state)
                # Incompressible text: TOAST would shrink a run of one letter
                # to nothing and hide what a real answer costs (T6).
                text = secrets.token_urlsafe(size)[:size]
                return {**(answer if isinstance(answer, dict) else {}), "text": text}

            return llm

        if step.type == "tool.call@1":

            async def tool(
                state: Mapping[str, Any], ctx: RunCtx, path: str, attempt: int
            ) -> dict[str, Any]:
                key = f"wf:{ctx.run_id}:{step.id}:{path}"
                payload = resolve(config.get("input", {}), state)
                return await ctx.door.external(ctx, step, key, payload)

            return tool

        if step.type == "data.write@1":

            async def write(
                state: Mapping[str, Any], ctx: RunCtx, path: str, attempt: int
            ) -> dict[str, Any]:
                key = f"wf:{ctx.run_id}:{step.id}:{path}"
                payload = resolve(config.get("input", {}), state)
                return await ctx.door.internal(ctx, step, key, payload)

            return write

        raise ValueError(f"no node for {step.type}")

    def _choose(
        self, step: SrtStep
    ) -> Callable[[Mapping[str, Any], RunCtx, str, int], Awaitable[dict[str, Any]]]:
        async def choose(
            state: Mapping[str, Any], ctx: RunCtx, path: str, attempt: int
        ) -> dict[str, Any]:
            value = resolve(step.config["on"], state)
            return {"case": str(value).lower() if isinstance(value, bool) else str(value)}

        return choose

    def _path(self, step: SrtStep, state: Mapping[str, Any]) -> str:
        parts = [f"{loop}={state.get(f'iter__{loop}', 0)}" for loop in self.loops_of[step.id]]
        if "_item" in state:
            parts.append(f"{self.map_of.get(step.id, 'map')}#{state['_item']}")
        return "/".join(parts)

    def wrap(
        self,
        step: SrtStep,
        impl: Callable[[Mapping[str, Any], RunCtx, str, int], Awaitable[dict[str, Any]]],
    ) -> Node:
        attempts = step.retry.max_attempts if step.retry else 1
        backoff = step.retry.backoff_s if step.retry else 0.0
        exponential = bool(step.retry and step.retry.exponential)

        async def wrapped(state: Mapping[str, Any], runtime: Runtime[RunCtx]) -> dict[str, Any]:
            ctx = runtime.context
            path = self._path(step, state)
            record = await ctx.lane.step_started(ctx, step.id, step.id, "step", path, True)
            if record.status == "cancelled":
                raise RunCancelledError(ctx.run_id)
            if record.seq is not None and record.seq > ctx.max_steps:
                await ctx.lane.step_ended(ctx, record.id, "limit_exceeded", 0)
                raise LimitExceededError(f"{record.seq} > {ctx.max_steps}")
            ctx.crash.at("start", step.id, ctx)
            attempt = 0
            failure = "step_failed"
            try:
                while attempt < attempts:
                    attempt += 1
                    try:
                        coro = impl(state, ctx, path, attempt)
                        output = await (
                            asyncio.wait_for(coro, step.timeout_s) if step.timeout_s else coro
                        )
                    except ParkError as park:
                        await ctx.lane.step_ended(ctx, record.id, park.kind, attempt)
                        return {
                            f"park__{step.id}": {
                                "wait": park.kind,
                                "step_id": step.id,
                                **park.detail,
                            }
                        }
                    except (NotDispatchedError, TransientError, TimeoutError) as exc:
                        failure = type(exc).__name__
                    except RejectedError as exc:
                        failure = f"rejected:{exc.provider_code}"
                        if exc.provider_code not in RETRYABLE_CODES:
                            break
                    else:
                        ctx.crash.at("K5", step.id, ctx)
                        await ctx.lane.step_ended(ctx, record.id, "succeeded", attempt)
                        update: dict[str, Any] = {f"out__{step.id}": output}
                        if f"park__{step.id}" in self.root_keys:
                            update[f"park__{step.id}"] = {}
                            update[f"err__{step.id}"] = False
                        if "asked" in output:
                            update[f"out__{step.id}"] = {}
                            update[f"park__{step.id}"] = output["asked"]
                        return update
                    if attempt < attempts:
                        await ctx.lane.lease_ok(ctx)
                        await asyncio.sleep(backoff * (2 ** (attempt - 1) if exponential else 1))
            except (GraphBubbleUp, LeaseLostError, RunCancelledError, LimitExceededError):
                raise
            except asyncio.CancelledError:
                await asyncio.shield(_cancelled(ctx, record.id, attempt, step.id))
                raise
            await ctx.lane.step_ended(ctx, record.id, "failed", attempt)
            error = {"status": "error", "error": failure}
            if step.on_error == "continue":
                return {f"out__{step.id}": error}
            if step.on_error == "route":
                return {f"out__{step.id}": error, f"err__{step.id}": True}
            if step.on_error == "incident" and ctx.run_input.get("mode", "live") == "live":
                return {
                    f"park__{step.id}": {"wait": "incident", "step_id": step.id, "error": failure}
                }
            raise StepFailedError(step.id, failure)

        return wrapped

    def _hold(self, step: SrtStep) -> Node:
        """An incident or an outcome review: `interrupt()` first (decision 4)."""

        async def hold(state: Mapping[str, Any], runtime: Runtime[RunCtx]) -> dict[str, Any]:
            decision = interrupt(state.get(f"park__{step.id}") or {})
            ctx = runtime.context
            record = await ctx.lane.step_started(
                ctx, self._wait_name(step.id), step.id, "resume", self._path(step, state), False
            )
            await ctx.lane.step_ended(ctx, record.id, "resumed", 0)
            action = str((decision or {}).get("action", "end"))
            out = dict((decision or {}).get("output") or {})
            return {f"out__{step.id}": {**out, "_resolution": action}, f"park__{step.id}": {}}

        return hold

    def _wait(self, step: SrtStep, kind: str) -> Node:
        """A wait for a person or a child run: `interrupt()` first."""

        async def wait(state: Mapping[str, Any], runtime: Runtime[RunCtx]) -> dict[str, Any]:
            decision = interrupt(state.get(f"park__{step.id}") or {"wait": kind})
            ctx = runtime.context
            record = await ctx.lane.step_started(
                ctx, self._wait_name(step.id), step.id, "resume", self._path(step, state), False
            )
            await ctx.lane.step_ended(ctx, record.id, "resumed", 0)
            if kind == "child_run":
                if (decision or {}).get("child_status") != "completed":
                    raise StepFailedError(step.id, "child_run_failed")
                return {
                    f"out__{step.id}": dict(decision.get("result") or {}),
                    f"park__{step.id}": {},
                }
            return {
                f"out__{step.id}": {"approved": bool((decision or {}).get("approved"))},
                f"park__{step.id}": {},
            }

        return wait

    def _fail(self, step: SrtStep, code: str = "step_failed") -> Node:
        async def fail(state: Mapping[str, Any]) -> dict[str, Any]:
            raise StepFailedError(step.id, code)

        return fail

    def _record(
        self,
        name: str,
        kind: str,
        update: Mapping[str, Any],
        *,
        step_id: str | None = None,
        bump: str | None = None,
    ) -> Node:
        """A compiler node: no step of its own, recorded so a golden trace
        sees the join fire and the loop turn."""

        async def node(state: Mapping[str, Any], runtime: Runtime[RunCtx]) -> dict[str, Any]:
            ctx = runtime.context
            out = dict(update)
            if bump is not None:
                out[bump] = int(state.get(bump, 0)) + 1
            path = ""
            if step_id is not None and step_id in self.loops_of:
                inner = {**state, **out}
                parts = [
                    f"{loop}={inner.get(f'iter__{loop}', 0)}" for loop in self.loops_of[step_id]
                ]
                if kind == "loop":
                    parts.append(f"{step_id}={inner.get(f'iter__{step_id}', 0)}")
                path = "/".join(parts)
            record = await ctx.lane.step_started(ctx, name, step_id, kind, path, False)
            await ctx.lane.step_ended(ctx, record.id, "succeeded", 0)
            return out

        return node


async def _cancelled(ctx: RunCtx, record_id: int, attempt: int, step_id: str) -> None:
    """A step stopped by a sibling lane's failure or by the run's cancel:
    its row, and `studio.branch.cancelled` (ADR-0112 decision 11)."""
    try:
        await ctx.lane.step_ended(ctx, record_id, "cancelled", attempt)
        await ctx.lane.audit(ctx, "studio.branch.cancelled", {"step_id": step_id})
    except BaseException as exc:
        print(f"cancelled-step bookkeeping failed: {exc!r}", flush=True)


def interrupt_of(result: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The one pending wait of a run that paused, `(interrupt id, value)`."""
    found = result.get("__interrupt__") if isinstance(result, Mapping) else None
    if not found:
        return None
    first = found[0]
    return str(first.id), dict(first.value or {})
