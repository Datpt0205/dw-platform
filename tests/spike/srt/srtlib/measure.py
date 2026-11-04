"""The experiments of discovery 14. Each returns a JSON-able dict, written to
`<out>/<name>.json`; the worker logs land in `<out>/<name>/`.

    measure t1 t2 t3 t4 t5 t6 t7 t8 q1 q2 q3 q6 --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from .control import TERMINAL, Harness, Proc, read_log
from .db import TENANTS, reset, urls

Result = dict[str, Any]


def pct(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q / 100 * (len(ordered) - 1))))
    return round(ordered[k], 4)


def summary(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50": pct(values, 50),
        "p95": pct(values, 95),
        "p99": pct(values, 99),
        "max": round(max(values), 4) if values else None,
    }


def counts(trace: list[dict[str, Any]], kind: str | None = "step") -> dict[str, int]:
    found: Counter[str] = Counter()
    for row in trace:
        if kind is None or row["kind"] == kind:
            found[row["node"]] += 1
    return dict(found)


def before(trace: list[dict[str, Any]], first: str, then: str) -> bool:
    a = [r["started"] for r in trace if r["node"] == first]
    b = [r["started"] for r in trace if r["node"] == then]
    return bool(a and b and max(a) <= min(b))


def check(name: str, conditions: dict[str, bool], **data: Any) -> Result:
    return {"case": name, "pass": all(conditions.values()), "conditions": conditions, **data}


# ================================================================== T1 ==


async def t1(h: Harness) -> Result:
    """Golden traces of RW1-RW6 and the variants of questions 7-9 and 11,
    every resume on the other worker (`alternate`)."""
    h.start("w1")
    h.start("w2")
    cases: list[Result] = []

    async def finish(run: str, timeout: float = 120) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        await h.wait_for([run], timeout=timeout)
        return await h.run(run), await h.trace(run)

    # RW1, three paths.
    hot = await h.submit("rw1", run_input={"tier": "hot", "lead": "L1"}, alternate=True)
    cold = await h.submit("rw1", run_input={"tier": "cold", "lead": "L2"}, alternate=True)
    no = await h.submit("rw1", run_input={"tier": "hot", "lead": "L3"}, alternate=True)
    await h.decide(hot, True)
    await h.decide(no, False)
    for run, path in ((hot, "approved"), (cold, "default"), (no, "rejected")):
        row, trace = await finish(run)
        c = counts(trace)
        expect = {
            "approved": {"score": 1, "route": 1, "approve": 1, "email": 1, "log": 1},
            "default": {"score": 1, "route": 1, "nurture": 1, "log": 1},
            "rejected": {"score": 1, "route": 1, "approve": 1, "note": 1, "log": 1},
        }[path]
        workers = {r["worker"] for r in trace}
        cases.append(
            check(
                f"RW1 {path}",
                {
                    "completed": row["status"] == "completed",
                    "steps exactly": c == expect,
                    "order score<route<log": before(trace, "score", "route")
                    and before(trace, "route", "log"),
                    "resumed on the other worker": path == "default" or len(workers) == 2,
                    "email sent once": path != "approved"
                    or (await h.applied(run)).get("email") == 1,
                },
                steps=c,
                workers=sorted(workers),
            )
        )

    # RW2, approved by both, PO succeeds; and PO fails into the error lane.
    ok = await h.submit("rw2", run_input={"lead": "P1"}, alternate=True)
    err = await h.submit(
        "rw2",
        run_input={"lead": "P2", "faults": {"po": {"reject_times": 9, "code": "503"}}},
        alternate=True,
    )
    for run in (ok, err):
        wait = await h.open_wait(run)
        approvals = await h.rows(
            "SELECT assignee, status FROM srt.approvals WHERE wait_id = :w", w=wait["id"]
        )
        await h.decide(run, True)
        row, trace = await finish(run)
        c = counts(trace)
        applied = await h.applied(run)
        failing = run == err
        po = [r for r in trace if r["node"] == "po"]
        cases.append(
            check(
                f"RW2 {'error lane' if failing else 'ok'}",
                {
                    "completed": row["status"] == "completed",
                    "lanes once": all(c.get(s) == 1 for s in ("budget", "supplier", "risk")),
                    "join fired once": counts(trace, "join").get("join__check") == 1,
                    "two approvals under one wait": len(approvals) == 2,
                    "join before approval": before(trace, "join__check", "approve2"),
                    "po attempts": (po[0]["attempt"] == 3) if failing else (po[0]["attempt"] == 1),
                    "error lane only on failure": (c.get("release") == 1) == failing,
                    "budget applied once": applied.get("budget") == 1,
                    "po applied": applied.get("po", 0) == (0 if failing else 1),
                    "done once": c.get("done") == 1,
                },
                steps=c,
                applied=applied,
            )
        )

    # RW2 for question 7.
    q7 = await h.submit("rw2_q7", run_input={}, alternate=True)
    row, trace = await finish(q7)
    joins = counts(trace, "join")
    fork = next(r for r in trace if r["node"] == "par__uneven")
    join = next(r for r in trace if r["node"] == "join__uneven")
    lane_b_end = max(r["ended"] for r in trace if r["node"] in ("s1", "s2", "s3"))
    long_end = next(r["ended"] for r in trace if r["node"] == "long")
    inloop = sorted(r["iteration_path"] for r in trace if r["node"] == "join__inloop")
    tallies = sorted(r["iteration_path"] for r in trace if r["node"] == "tally")
    elapsed = float(join["started"]) - float(fork["ended"])
    cases.append(
        check(
            "RW2 q7 (uneven, nested, switch in lane, parallel in loop)",
            {
                "completed": row["status"] == "completed",
                "outer join once": joins.get("join__uneven") == 1,
                "nested join once": joins.get("join__nested") == 1,
                "loop join once per iteration": inloop == ["rounds=1", "rounds=2", "rounds=3"],
                "tally once per iteration": tallies == ["rounds=1", "rounds=2", "rounds=3"],
                "switch in lane took one case": counts(trace).get("cb") == 1
                and "ca" not in counts(trace),
                "lanes not lock-step (< 1.3 s)": elapsed < 1.3,
                "short lane finished before the long one": lane_b_end < long_end,
            },
            uneven_block_seconds=round(elapsed, 3),
            lane_of_three_ended_after=round(float(lane_b_end) - float(fork["ended"]), 3),
            long_lane_ended_after=round(float(long_end) - float(fork["ended"]), 3),
        )
    )

    # A lane fails with no error lane: the others are cancelled.
    bad = await h.submit("rw2_fail", run_input={"faults": {"bad": {"fail_times": 9}}})
    row, trace = await finish(bad)
    audits = await h.rows("SELECT action, details FROM srt.audit WHERE run_id = :r", r=bad)
    status = {r["node"]: r["status"] for r in trace}
    failed_at = next(r["ended"] for r in trace if r["node"] == "bad")
    cancelled_at = [r["ended"] for r in trace if r["status"] == "cancelled"]
    cases.append(
        check(
            "RW2 failing lane cancels the others",
            {
                "failed": row["status"] == "failed",
                "others cancelled": status.get("slow") == "cancelled"
                and status.get("other") == "cancelled",
                "studio.branch.cancelled audited twice": sum(
                    1 for a in audits if a["action"] == "studio.branch.cancelled"
                )
                == 2,
                "join never fired": "join__check" not in counts(trace, "join"),
                "later step never ran": "never" not in counts(trace),
            },
            cancel_latency_ms=[round((float(c) - float(failed_at)) * 1000) for c in cancelled_at],
            error=row["error"],
        )
    )

    # RW3: the map.
    rw3 = await h.submit("rw3", run_input={})
    row, trace = await finish(rw3, 300)
    items = [r for r in trace if r["node"] == "score_item"]
    cases.append(
        check(
            "RW3 map 100",
            {
                "completed": row["status"] == "completed",
                "100 items, each once": len(items) == 100
                and len({r["iteration_path"] for r in items}) == 100,
                "fan-in once": counts(trace, "join").get("mapjoin__items") == 1,
                "summary once, after the fan-in": counts(trace).get("summary") == 1
                and before(trace, "mapjoin__items", "summary"),
            },
        )
    )

    # RW4: rejected twice, approved the third time; and five rejections.
    rw4 = await h.submit("rw4", run_input={"lead": "D1"}, alternate=True)
    ids = [await h.decide(rw4, False), await h.decide(rw4, False), await h.decide(rw4, True)]
    row, trace = await finish(rw4)
    c = counts(trace)
    cases.append(
        check(
            "RW4 rework, break on approval",
            {
                "completed": row["status"] == "completed",
                "3 drafts, 3 reviews, 2 revisions": (
                    c.get("draft"),
                    c.get("review"),
                    c.get("revise"),
                )
                == (3, 3, 2),
                "break once, no escalation": counts(trace, "break").get("brk__ok") == 1
                and "escalate" not in c,
                "publish once": c.get("publish") == 1,
                "interrupt id per iteration": len(set(ids)) == 3,
                "resumes alternate": len({r["worker"] for r in trace}) == 2,
            },
            interrupt_ids=ids,
        )
    )
    rw4m = await h.submit("rw4", run_input={"lead": "D2"}, alternate=True)
    for _ in range(5):
        await h.decide(rw4m, False)
    row, trace = await finish(rw4m)
    c = counts(trace)
    cases.append(
        check(
            "RW4 max_iterations reached",
            {
                "completed": row["status"] == "completed",
                "5 drafts": c.get("draft") == 5,
                "escalate once (max_reached)": c.get("escalate") == 1,
                "publish once": c.get("publish") == 1,
            },
        )
    )

    # RW5: Zalo answers, or refuses for good and email goes.
    for label, faults in (
        ("zalo delivered", {}),
        ("zalo refused, email", {"zalo": {"reject_times": 9, "code": "400"}}),
    ):
        run = await h.submit("rw5", run_input={"faults": faults})
        row, trace = await finish(run)
        applied = await h.applied(run)
        cases.append(
            check(
                f"RW5 {label}",
                {
                    "completed": row["status"] == "completed",
                    "never both channels": not (applied.get("zalo") and applied.get("email")),
                    "exactly one channel": applied.get("zalo", 0) + applied.get("email", 0) == 1,
                },
                applied=applied,
            )
        )

    # RW6: three levels, the child waits for a person.
    rw6 = await h.submit("rw6", run_input={}, alternate=True)
    child = await _child_of(h, rw6)
    await h.decide(child, True)
    row, trace = await finish(rw6, 180)
    tree = await h.rows(
        "SELECT id::text, depth, status, parent_run_id::text FROM srt.runs WHERE root_run_id = :r"
        " ORDER BY depth",
        r=rw6,
    )
    steps_all = Counter[str]()
    for node in tree:
        steps_all.update(counts(await h.trace(node["id"])))
    cases.append(
        check(
            "RW6 sub-workflow 3 deep",
            {
                "completed": row["status"] == "completed",
                "three levels completed": [t["depth"] for t in tree] == [0, 1, 2]
                and all(t["status"] == "completed" for t in tree),
                "every step once": dict(steps_all)
                == {
                    "p1": 1,
                    "child": 1,
                    "p2": 1,
                    "c1": 1,
                    "c_ok": 1,
                    "grand": 1,
                    "c2": 1,
                    "g1": 1,
                    "g2": 1,
                },
            },
            steps=dict(steps_all),
        )
    )
    return {"cases": cases, "pass": all(c["pass"] for c in cases)}


async def _child_of(h: Harness, parent: str, timeout: float = 60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = await h.rows("SELECT id::text FROM srt.runs WHERE parent_run_id = :p", p=parent)
        if rows:
            return str(rows[0]["id"])
        await asyncio.sleep(0.2)
    raise TimeoutError(parent)


async def _q8(h: Harness) -> Result:
    """Question 8 on workers started with `recursion_limit` 8: the step
    counter stops the waiting loop, the recursion limit never does."""
    run = await h.submit("rw4_q8", run_input={}, alternate=True)
    ids = []
    for _ in range(10):
        row = await h.run(run)
        await h.wait_for([run], ("waiting", *TERMINAL))
        row = await h.run(run)
        if row["status"] != "waiting":
            break
        ids.append(await h.decide(run, True))
    await h.wait_for([run])
    row, trace = await h.run(run), await h.trace(run)
    works = [
        r["iteration_path"] for r in trace if r["node"] == "work" and r["status"] == "succeeded"
    ]
    written = await h.records(run)
    seqs = [r["seq"] for r in trace if r["kind"] == "step"]
    return check(
        "RW4 q8 (10 waits, max_steps 13, alternating workers)",
        {
            "stopped limit_exceeded": row["status"] == "failed"
            and row["error"] == "limit_exceeded",
            "stopped at step 14": max(seqs) == 14,
            "distinct interrupt ids": len(set(ids)) == len(ids) == 6,
            "one effect per iteration": sorted(written.values()) == [1] * len(written)
            and len(written) == 7,
            "after never ran": "after" not in counts(trace),
            "resumes alternate": len({r["worker"] for r in trace}) == 2,
        },
        iterations=works,
        steps_counted=max(seqs),
        waits=len(ids),
    )


async def t1_recursion(h: Harness) -> Result:
    """The loop of question 8 under `recursion_limit` 8 on both workers, and
    its control without waits."""
    args = ["--recursion-limit", "8"]
    h.start("w1", args=args)
    h.start("w2", args=args)
    q8 = await _q8(h)
    nowait = await h.submit("rw4_nowait", run_input={})
    await h.wait_for([nowait])
    row = await h.run(nowait)
    control = check(
        "control: the same loop without waits",
        {
            "recursion_limit stops it": row["status"] == "failed"
            and row["error"] == "recursion_limit"
        },
        error=row["error"],
        steps=row["steps_started"],
    )
    return {"cases": [q8, control], "pass": q8["pass"] and control["pass"]}


# ================================================================== T2 ==


async def t2(h: Harness) -> Result:
    h.start("w1")
    runs = []
    for _ in range(3):
        run = await h.submit(
            "rw2_t2", run_input={"faults": {"budget": {"reject_times": 1, "code": "503"}}}
        )
        await h.wait_for([run])
        runs.append(run)
    cases = []
    for run in runs:
        trace = await h.trace(run)
        budget = next(r for r in trace if r["node"] == "budget")
        window_start = float(budget["started"])
        others = [
            r
            for r in trace
            if r["kind"] == "step" and r["node"] != "budget" and r["status"] == "succeeded"
        ]
        within = [r for r in others if float(r["ended"]) <= window_start + 5.0]
        backoff_end = float(budget["ended"])
        cases.append(
            check(
                "RW2 T2",
                {
                    "budget retried after backoff": budget["attempt"] == 2
                    and backoff_end - window_start >= 5.0,
                    ">= 3 steps done in <= 5 s": len(within) >= 3,
                    "they finished during the backoff": all(
                        float(r["ended"]) < backoff_end for r in within
                    ),
                },
                done_in_5s=len(within),
                last_other_done_after=round(
                    max(float(r["ended"]) for r in others) - window_start, 3
                ),
                budget_done_after=round(backoff_end - window_start, 3),
            )
        )
    return {"cases": cases, "pass": all(c["pass"] for c in cases)}


# ================================================================== T3 ==

POINTS = ("K1", "K2", "T", "K4", "K5", "K6", "Sa", "Sb")


def _arm(point: str, step: str = "fx") -> tuple[dict[str, str], dict[str, Any]]:
    """The victim's environment and the run's faults for one cell."""
    if point == "T":
        return {}, {step: {"lose_times": 1}}
    if point == "K6":
        return {"SRT_CRASH": "start:after"}, {}
    if point in ("Sa", "Sb"):
        return {"SRT_STALL": f"{point}:{step}:130"}, {}
    return {"SRT_CRASH": f"{point}:{step}"}, {}


async def _matrix_batch(
    h: Harness,
    cells: list[tuple[str, str, str, dict[str, Any], dict[str, str], list[str]]],
    tag: str,
    survivor_args: Sequence[str] = (),
    settle: float = 240,
) -> list[dict[str, Any]]:
    """Each cell: (label, workflow, run id, run input, victim env, victim args).
    Victims claim their own run first; then two survivors take over."""
    victims: list[Proc] = []
    for label, _wf, run_id, _input, env, args in cells:
        victims.append(
            h.start(f"victim-{label}", env=env, args=["--only-run", run_id, *args], tag=tag)
        )
    await asyncio.sleep(8)  # interpreters up and listening
    for _label, workflow, run_id, run_input, _env, _args in cells:
        await h.submit(workflow, run_input=run_input, run_id=run_id)
    # Every victim has claimed (or already died) before a survivor exists.
    deadline = time.time() + 60
    while time.time() < deadline:
        claimed = await h.rows(
            "SELECT count(*) AS n FROM srt.runs"
            " WHERE id = ANY(CAST(:ids AS uuid[])) AND claims > 0",
            ids=[c[2] for c in cells],
        )
        if claimed[0]["n"] == len(cells):
            break
        await asyncio.sleep(0.5)
    survivors = [h.start(f"s{i}", args=survivor_args, tag=tag) for i in (1, 2)]
    ids = [c[2] for c in cells]
    with contextlib.suppress(TimeoutError):
        await h.wait_for(ids, ("completed", "failed", "waiting", "cancelled"), timeout=settle)
    # A stalled holder wakes at 130 s: wait for every victim to be gone.
    for proc in victims:
        try:
            proc.popen.wait(max(1.0, 200 - (time.time() - deadline)))
        except Exception:
            proc.kill()
    await asyncio.sleep(3)
    for proc in survivors:
        proc.stop(30)
    out = []
    for (label, _wf, run_id, _, _, _), proc in zip(cells, victims, strict=True):
        row = await h.run(run_id)
        trace = await h.trace(run_id)
        log = read_log(proc.log)
        waits = await h.rows("SELECT kind, status FROM srt.waits WHERE run_id = :r", r=run_id)
        executions = await h.rows(
            "SELECT status, error FROM platform.tool_executions WHERE run_id = :r"
            " ORDER BY started_at",
            r=run_id,
        )
        out.append(
            {
                "label": label,
                "run": run_id,
                "status": row["status"],
                "error": row["error"],
                "applied": await h.applied(run_id),
                "records": await h.records(run_id),
                "waits": waits,
                "executions": executions,
                "victim_exit": proc.popen.returncode,
                "victim_fence_rejected": max(
                    [e.get("fence_rejected", 0) for e in log if e["e"] == "run_ended"] or [0]
                ),
                "victim_outcome": [e.get("outcome") for e in log if e["e"] == "run_ended"],
                "steps_by_worker": Counter(f"{r['node']}@{r['worker'][:6]}" for r in trace),
            }
        )
    return out


async def t3(h: Harness, only: str | None = None) -> Result:
    """The crash matrix: K1-K6, S (stalled before and after `dispatched`) and
    T, against the three provider modes; the internal effect; RW5 under T and
    K4; and the control case with the dispatch log removed."""
    cells: list[tuple[str, str, str, dict[str, Any], dict[str, str], list[str]]] = []
    for mode in ("keyed", "lookup", "none"):
        for point in POINTS:
            env, faults = _arm(point)
            run_input = {"lead": "X", "faults": {"fx": {"mode": mode, **faults.get("fx", {})}}}
            cells.append((f"{mode}-{point}", "effect", str(uuid.uuid4()), run_input, env, []))
    # S again with a holder that cannot heartbeat (a partition from the
    # database, not from the provider): nothing cancels it when it wakes.
    for mode in ("keyed", "lookup", "none"):
        for point in ("Sa", "Sb"):
            env, _ = _arm(point)
            run_input = {"lead": "X", "faults": {"fx": {"mode": mode}}}
            cells.append(
                (
                    f"{mode}-{point}X",
                    "effect",
                    str(uuid.uuid4()),
                    run_input,
                    env,
                    ["--heartbeat", "1000"],
                )
            )
    # The same stall with the claim checked again right before the send.
    for mode in ("lookup", "none"):
        env = {**_arm("Sb")[0], "SRT_PRESEND": "1"}
        run_input = {"lead": "X", "faults": {"fx": {"mode": mode}}}
        cells.append(
            (f"{mode}-SbP", "effect", str(uuid.uuid4()), run_input, env, ["--heartbeat", "1000"])
        )
    for point in ("K1", "K5", "K6", "Sa"):
        env, _ = _arm(point)
        if point == "Sa":
            env = {"SRT_STALL": "K1:fx:130"}  # the stall sits where the internal door starts
        cells.append((f"internal-{point}", "internal", str(uuid.uuid4()), {}, env, []))
    for mode in ("keyed", "none"):
        for point in ("T", "K4"):
            env, faults = _arm(point, "zalo")
            run_input = {"faults": {"zalo": {"mode": mode, **faults.get("zalo", {})}}}
            cells.append((f"rw5-{mode}-{point}", "rw5", str(uuid.uuid4()), run_input, env, []))
    controls: list[tuple[str, str, str, dict[str, Any], dict[str, str], list[str]]] = [
        (
            "control-none-K4-no-dispatch-log",
            "effect",
            str(uuid.uuid4()),
            {"lead": "X", "faults": {"fx": {"mode": "none"}}},
            {"SRT_CRASH": "K4:fx"},
            ["--no-dispatch-log"],
        ),
        (
            "control-internal-K4-key-apart",
            "internal",
            str(uuid.uuid4()),
            {"internal": "separate"},
            {"SRT_CRASH": "K4:fx"},
            [],
        ),
    ]
    if only:
        cells = [c for c in cells if only in c[0]]
    results: list[dict[str, Any]] = []
    batches = [cells[i : i + 8] for i in range(0, len(cells), 8)]
    for n, batch in enumerate(batches):
        results += await _matrix_batch(h, batch, f"b{n}-")
    if not only:
        results += await _matrix_batch(
            h, controls[:1], "ctl0-", survivor_args=["--no-dispatch-log"]
        )
        results += await _matrix_batch(h, controls[1:], "ctl1-")
    for cell in results:
        cell["verdict"] = _t3_verdict(cell)
    return {
        "cells": results,
        "pass": all(c["verdict"]["pass"] for c in results if not c["label"].startswith("control")),
        "controls_red": all(
            not c["verdict"]["pass"] for c in results if c["label"].startswith("control")
        ),
    }


def _t3_verdict(cell: dict[str, Any]) -> dict[str, Any]:
    label = cell["label"]
    applied = cell["applied"]
    review = any(w["kind"] == "outcome_review" for w in cell["waits"])
    if label.startswith("internal") or label.startswith("control-internal"):
        dup = [k for k, n in cell["records"].items() if n > 1]
        return {"pass": not dup and cell["status"] == "completed", "duplicate_writes": dup}
    if label.startswith("rw5"):
        both = bool(applied.get("zalo")) and bool(applied.get("email"))
        return {"pass": not both and applied.get("zalo", 0) <= 1, "both_channels": both}
    mode, point = label.split("-")[0], label.split("-")[-1]
    if label.startswith("control"):
        mode, point = "none", "K4"
    n = applied.get("fx", 0)
    if mode in ("keyed", "lookup"):
        ok = n == 1 and cell["status"] == "completed"
        return {"pass": ok, "applied": n, "expect": "exactly 1 application, completed"}
    if point in ("T", "K4", "Sb", "SbX", "SbP"):
        return {
            # Sb: the stalled holder may never have sent (0) or sent once (1).
            "pass": (n == 1 or (point.startswith("Sb") and n == 0))
            and review
            and cell["status"] == "waiting",
            "applied": n,
            "outcome_review": review,
            "expect": "0 automatic resends, parked on outcome_review",
        }
    return {
        "pass": n == 1 and cell["status"] == "completed",
        "applied": n,
        "expect": "1, completed",
    }


# ================================================================== T4 ==


async def t4(h: Harness) -> Result:
    """A worker killed mid-run; an orderly stop; and parked runs resumed by
    the next compiler and back."""
    out: Result = {"kills": [], "orderly": [], "compiler": []}
    for n in range(4):
        victim = h.start(f"k{n}")
        await asyncio.sleep(5)
        runs = [
            await h.submit("rw2_t7", run_input={"faults": {"s5": {"seconds": 40.0}}})
            for _ in range(2)
        ]
        # Mid-run: the slow step 5 is running.
        deadline = time.time() + 60
        while time.time() < deadline:
            rows = await h.rows(
                "SELECT count(*) AS n FROM srt.run_steps WHERE run_id = ANY(CAST(:ids AS uuid[]))"
                " AND node = 's5' AND ended_at IS NULL",
                ids=runs,
            )
            if rows[0]["n"] == len(runs):
                break
            await asyncio.sleep(0.2)
        heir = h.start(f"heir{n}")  # already running when the other dies
        await asyncio.sleep(6 + n * 4.0)  # spread the kill over the heartbeat period
        killed_at = victim.kill()
        await h.wait_for(runs, timeout=200)
        for run in runs:
            trace = await h.trace(run)
            resumed = min(float(r["started"]) for r in trace if r["worker"] == f"heir{n}")
            row = await h.run(run)
            out["kills"].append(
                {
                    "run": run,
                    "resume_seconds": round(resumed - killed_at, 2),
                    "status": row["status"],
                    "attempt": row["attempt"],
                    "steps_rerun": [k for k, v in counts(trace).items() if v > 1],
                    "applied": await h.applied(run),
                }
            )
        heir.stop(30)
    # An orderly stop gives the lease back at once.
    w = h.start("orderly")
    await asyncio.sleep(5)
    run = await h.submit("rw2_t7", run_input={"faults": {"s5": {"seconds": 40.0}}})
    while not await h.rows("SELECT 1 FROM srt.run_steps WHERE run_id = :r AND node = 's5'", r=run):
        await asyncio.sleep(0.2)
    heir = h.start("orderly-heir")
    await asyncio.sleep(6)
    stopped_at = time.time()
    w.stop(60)
    await h.wait_for([run], timeout=120)
    trace = await h.trace(run)
    resumed = min(float(r["started"]) for r in trace if r["worker"] == "orderly-heir")
    row = await h.run(run)
    out["orderly"].append(
        {
            "resume_seconds": round(resumed - stopped_at, 2),
            "attempt": row["attempt"],
            "status": row["status"],
        }
    )
    heir.stop(30)
    # Compilers: park under one, resume under the other.
    h.start("c-w1")
    h.start("c-w2")
    for parked, resumed_with in (("c1", "c2"), ("c2", "c1"), ("c1", "c2-renamed")):
        run = await h.submit("rw4", run_input={}, compiler=parked)
        await h.open_wait(run)
        async with h.migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE srt.runs SET compiler = :c WHERE id = :r"),
                {"c": resumed_with, "r": run},
            )
        await h.decide(run, True)
        await h.wait_for([run])
        row = await h.run(run)
        trace = await h.trace(run)
        c = counts(trace)
        out["compiler"].append(
            {
                "parked_under": parked,
                "resumed_under": resumed_with,
                "status": row["status"],
                "error": row["error"],
                "publish_ran": c.get("publish") == 1,
                "resumed_node": [r["node"] for r in trace if r["kind"] == "resume"],
                "pass": row["status"] == "completed" and c.get("publish") == 1,
            }
        )
    resumes = [k["resume_seconds"] for k in out["kills"]]
    out["resume"] = summary(resumes)
    out["pass"] = (
        bool(resumes)
        and max(resumes) <= 90
        and all(k["status"] == "completed" for k in out["kills"])
        and all(c["pass"] for c in out["compiler"][:2])
    )
    return out


# ================================================================== T5 ==


async def _gaps(h: Harness, runs: Sequence[str]) -> dict[str, Any]:
    rows = await h.rows(
        "SELECT run_id::text AS run, node, kind, extract(epoch FROM started_at) AS s,"
        " extract(epoch FROM ended_at) AS e FROM srt.run_steps"
        " WHERE run_id = ANY(CAST(:ids AS uuid[])) ORDER BY run_id, started_at",
        ids=list(runs),
    )
    by_run: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)
    every: list[float] = []
    nodes: list[float] = []
    for steps in by_run.values():
        ended: list[float] = []
        for r in steps:
            start = float(r["s"])
            done = [e for e in ended if e <= start]
            if done:
                gap = start - max(done)
                every.append(gap)
                if r["node"] != "score_item":
                    nodes.append(gap)
            if r["e"] is not None:
                ended.append(float(r["e"]))
    return {"every_step": summary(every), "graph_nodes": summary(nodes)}


async def _rw3_load(
    h: Harness, label: str, saver: str, lot: int, pool: int, n: int, timeout: float
) -> Result:
    await reset(h.migrator)
    args = ["--lot", str(lot), "--pool", str(pool), "--max-concurrency", "10"]
    procs = [h.start(f"{label}-w{i}", args=args) for i in (1, 2)]
    await asyncio.sleep(6)
    started = time.time()
    runs: list[str] = []
    tenants: dict[str, str] = {}
    for i in range(n):
        tenant = "D" if i % 10 == 0 else "C"  # one company in ten is the quiet one
        run = await h.submit("rw3", tenant=tenant, run_input={}, saver=saver)
        runs.append(run)
        tenants[run] = tenant
    submitted = time.time()
    with contextlib.suppress(TimeoutError):
        await h.wait_for(runs, timeout=timeout, interval=2.0)
    ended = time.time()
    for p in procs:
        p.stop(60)
    rows = await h.rows(
        "SELECT id::text, status, error, tenant_id, extract(epoch FROM received_at) AS r,"
        " extract(epoch FROM finished_at) AS f FROM srt.runs WHERE id = ANY(CAST(:ids AS uuid[]))",
        ids=runs,
    )
    statuses = Counter(r["status"] for r in rows)
    first_steps = await h.rows(
        "SELECT run_id::text AS run, extract(epoch FROM min(started_at)) AS s FROM srt.run_steps"
        " WHERE run_id = ANY(CAST(:ids AS uuid[])) GROUP BY run_id",
        ids=runs,
    )
    received = {r["id"]: float(r["r"]) for r in rows}
    wait_by_tenant: dict[str, list[float]] = {"C": [], "D": []}
    for fs in first_steps:
        wait_by_tenant[tenants[fs["run"]]].append(float(fs["s"]) - received[fs["run"]])
    steps = await h.rows(
        "SELECT count(*) AS n FROM srt.run_steps WHERE run_id = ANY(CAST(:ids AS uuid[]))", ids=runs
    )
    size = await h.rows(
        "SELECT (SELECT coalesce(sum(pg_column_size(c.*)), 0) FROM platform.run_checkpoints c)"
        " + (SELECT coalesce(sum(pg_column_size(w.*)), 0) FROM platform.run_checkpoint_writes w)"
        " + (SELECT coalesce(sum(pg_column_size(c.*)), 0) FROM srt.cp c)"
        " + (SELECT coalesce(sum(pg_column_size(b.*)), 0) FROM srt.cp_blobs b)"
        " + (SELECT coalesce(sum(pg_column_size(w.*)), 0) FROM srt.cp_writes w) AS b"
    )
    return {
        "label": label,
        "saver": saver,
        "lot_per_worker": lot,
        "pool": pool,
        "runs": n,
        "statuses": dict(statuses),
        "errors": dict(Counter(r["error"] for r in rows if r["error"])),
        "submit_seconds": round(submitted - started, 1),
        "wall_seconds": round(ended - started, 1),
        "steps_recorded": steps[0]["n"],
        "steps_per_second": round(steps[0]["n"] / max(1.0, ended - submitted), 1),
        "gaps": await _gaps(h, runs[:: max(1, n // 200)]),
        "queue_wait_by_company": {k: summary(v) for k, v in wait_by_tenant.items()},
        "checkpoint_bytes": size[0]["b"],
        "checkpoint_bytes_per_run": round(size[0]["b"] / max(1, n)),
    }


async def t5(h: Harness) -> Result:
    n = int(os.environ.get("SRT_T5_RUNS", "1000"))
    cases = [
        await _rw3_load(h, "lane-current", "current", lot=8, pool=10, n=n, timeout=3600),
        await _rw3_load(h, "lane-blob", "blob", lot=8, pool=10, n=n, timeout=3600),
        await _rw3_load(h, "stress-current", "current", lot=500, pool=20, n=n, timeout=3600),
        await _rw3_load(h, "stress-blob", "blob", lot=500, pool=20, n=n, timeout=3600),
    ]
    return {"cases": cases}


# ================================================================== T6 ==


async def _latest_bytes(h: Harness, run: str) -> int:
    """What a resume reads: the newest checkpoint of each namespace and its writes."""
    rows = await h.rows(
        "WITH last AS (SELECT DISTINCT ON (checkpoint_ns) checkpoint_ns, checkpoint_id,"
        " pg_column_size(c.*) AS b FROM platform.run_checkpoints c WHERE thread_id = :r"
        " ORDER BY checkpoint_ns, checkpoint_id DESC)"
        " SELECT (SELECT coalesce(sum(b), 0) FROM last)"
        " + (SELECT coalesce(sum(pg_column_size(w.*)), 0)"
        " FROM platform.run_checkpoint_writes w JOIN last USING (checkpoint_ns, checkpoint_id)"
        " WHERE w.thread_id = :r) AS b",
        r=run,
    )
    return int(rows[0]["b"])


async def _bytes(h: Harness, run: str, saver: str) -> int:
    if saver in ("blob", "blobp"):
        rows = await h.rows(
            "SELECT (SELECT coalesce(sum(pg_column_size(c.*)), 0) FROM srt.cp c"
            " WHERE thread_id = :r)"
            " + (SELECT coalesce(sum(pg_column_size(b.*)), 0) FROM srt.cp_blobs b"
            " WHERE thread_id = :r)"
            " + (SELECT coalesce(sum(pg_column_size(w.*)), 0) FROM srt.cp_writes w"
            " WHERE thread_id = :r)"
            " AS b",
            r=run,
        )
    else:
        rows = await h.rows(
            "SELECT (SELECT coalesce(sum(pg_column_size(c.*)), 0) FROM platform.run_checkpoints c"
            " WHERE thread_id = :r) + (SELECT coalesce(sum(pg_column_size(w.*)), 0)"
            " FROM platform.run_checkpoint_writes w WHERE thread_id = :r) AS b",
            r=run,
        )
    return int(rows[0]["b"])


async def t6(h: Harness) -> Result:
    h.start("w1")
    out: Result = {"parked": [], "big": []}
    for workflow, run_input in (
        ("rw1", {"tier": "hot", "lead": "L"}),
        ("rw2", {"lead": "P"}),
        ("rw4", {}),
    ):
        for saver in ("current", "blob", "blobp"):
            run = await h.submit(workflow, run_input=run_input, saver=saver)
            await h.open_wait(run)
            size = await _bytes(h, run, saver)
            rows = await h.rows(
                "SELECT checkpoint_ns = '' AS root, count(*) AS n FROM platform.run_checkpoints"
                " WHERE thread_id = :r GROUP BY 1",
                r=run,
            )
            out["parked"].append(
                {
                    "workflow": workflow,
                    "saver": saver,
                    "bytes": size,
                    "latest_only_bytes": await _latest_bytes(h, run)
                    if saver == "current"
                    else None,
                    "checkpoints": {("root" if r["root"] else "lanes"): r["n"] for r in rows},
                    "pass": size <= 20 * 1024,
                }
            )
    for workflow, saver in (
        ("big20", "current"),
        ("big20", "blob"),
        ("big20", "blobp"),
        ("big20_60k", "current"),
        ("big20_60k", "blob"),
        ("big20_60k", "blobp"),
    ):
        run = await h.submit(workflow, run_input={}, saver=saver)
        await h.wait_for([run], timeout=300)
        size = await _bytes(h, run, saver)
        out["big"].append(
            {
                "workflow": workflow,
                "saver": saver,
                "status": (await h.run(run))["status"],
                "bytes": size,
                "mib": round(size / 1048576, 2),
                "pass": size <= 3 * 1024 * 1024,
            }
        )
    return out


# ================================================================== T7 ==


async def t7(h: Harness) -> Result:
    h.start("w1")
    h.start("w2")
    run = await h.submit(
        "rw2_t7", run_input={"faults": {"s7": {"until_fixed": True}}}, alternate=True
    )
    wait = await h.open_wait(run)
    parked = await h.run(run)
    before_trace = await h.trace(run)
    parked_worker = [r["worker"] for r in before_trace if r["node"] == "s7"][-1]
    await h.fix_provider("po")
    await h.resolve(run, "retry")
    await h.wait_for([run])
    row = await h.run(run)
    trace = await h.trace(run)
    c = counts(trace)
    applied = await h.applied(run)
    keys = await h.rows(
        "SELECT DISTINCT idempotency_key FROM platform.tool_executions WHERE run_id = :r"
        " AND tool_name = 'prov.send' AND idempotency_key LIKE :k",
        r=run,
        k=f"wf:{run}:s7:%",
    )
    s7 = [r for r in trace if r["node"] == "s7"]
    first_six = ("s1", "budget", "supplier", "risk", "s3", "s4", "s5", "s6")
    return check(
        "T7 / question 9: incident after a parallel block, then Chạy tiếp từ Bước lỗi",
        {
            "parked waiting on incident": parked["status"] == "waiting"
            and wait["kind"] == "incident",
            "completed after the retry": row["status"] == "completed",
            "same run id": row["id"] == parked["id"],
            "steps 1-6 once": all(c.get(s) == 1 for s in first_six),
            "join of the parallel once": counts(trace, "join").get("join__s2") == 1,
            "effects of 1-6 not resent": applied.get("budget") == 1
            and applied.get("s3") == 1
            and applied.get("s6") == 1,
            "s7 again, same key": len(s7) == 2 and len(keys) == 1,
            "s7 applied once": applied.get("s7") == 1,
            "s8-s10 once": all(c.get(s) == 1 for s in ("s8", "s9", "s10")),
            "resumed on the other worker": s7[-1]["worker"] != parked_worker,
        },
        steps=c,
        applied=applied,
        s7_attempts=[r["attempt"] for r in s7],
    )


# ================================================================== T8 ==


async def _cancel_case(h: Harness, label: str, workflow: str, mode: str) -> Result:
    root = await h.submit("rw6" if workflow == "rw6_wait" else workflow, run_input={})
    if workflow == "rw6_long":
        child = await _child_of(h, root)
        await h.decide(child, True)
        grand = await _child_of(h, child)
        await h.wait_for([grand], ("running",), timeout=60)
        while not await h.rows(
            "SELECT 1 FROM srt.run_steps WHERE run_id = :r AND node = 'g1'", r=grand
        ):
            await asyncio.sleep(0.2)
    elif workflow == "rw6_wait":
        child = await _child_of(h, root)
        await h.open_wait(child)
    else:
        while (
            len(
                await h.rows(
                    "SELECT 1 FROM srt.run_steps WHERE run_id = :r AND kind = 'step'", r=root
                )
            )
            < 3
        ):
            await asyncio.sleep(0.2)
    await asyncio.sleep(1.0)
    committed = await h.cancel(root)
    await asyncio.sleep(20 if mode == "heartbeat" else 8)
    tree = await h.rows(
        "SELECT id::text, status, extract(epoch FROM finished_at) AS f,"
        " extract(epoch FROM stopped_at) AS stopped FROM srt.runs WHERE root_run_id = :r",
        r=root,
    )
    waits = await h.rows(
        "SELECT w.kind, w.status, extract(epoch FROM w.closed_at) AS c FROM srt.waits w"
        " JOIN srt.runs r ON r.id = w.run_id WHERE r.root_run_id = :r",
        r=root,
    )
    approvals = await h.rows(
        "SELECT a.status FROM srt.approvals a JOIN srt.runs r ON r.id = a.run_id"
        " WHERE r.root_run_id = :r",
        r=root,
    )
    steps = await h.rows(
        "SELECT s.node, s.status, extract(epoch FROM s.ended_at) AS e FROM srt.run_steps s"
        " JOIN srt.runs r ON r.id = s.run_id WHERE r.root_run_id = :r AND s.kind = 'step'"
        " AND (s.ended_at IS NULL OR s.status = 'cancelled')",
        r=root,
    )
    stops = [float(s["e"]) - committed for s in steps if s["e"] is not None]
    still = [s["node"] for s in steps if s["e"] is None]
    tx_times = {round(float(r["f"]), 6) for r in tree} | {
        round(float(w["c"]), 6) for w in waits if w["status"] == "cancelled"
    }
    return check(
        f"T8 {label} ({mode})",
        {
            "every run cancelled": all(r["status"] == "cancelled" for r in tree),
            "every step stopped <= 5 s": not still and all(s <= 5.0 for s in stops),
            "no wait left open": all(w["status"] != "open" for w in waits),
            "approvals cancelled": all(a["status"] in ("cancelled", "approved") for a in approvals),
            "one transaction": len(tx_times) == 1,
        },
        runs=len(tree),
        waits=[(w["kind"], w["status"]) for w in waits],
        step_stop_seconds=[round(s, 3) for s in stops],
        running_after=still,
    )


async def t8(h: Harness) -> Result:
    cases = []
    for mode in ("notify", "heartbeat"):
        procs = [h.start(f"{mode}-w{i}", args=["--cancel", mode]) for i in (1, 2)]
        cases.append(await _cancel_case(h, "RW2 three lanes in 30 s steps", "rw2_long", mode))
        cases.append(
            await _cancel_case(h, "RW6 grandchild running, two child waits open", "rw6_long", mode)
        )
        if mode == "notify":
            cases.append(await _cancel_case(h, "RW6 child waiting on approval", "rw6_wait", mode))
        for p in procs:
            p.stop(30)
    return {"cases": cases, "pass": all(c["pass"] for c in cases if "(notify)" in c["case"])}


# ======================================================== question 1 ==


async def q1(h: Harness) -> Result:
    """The fence's cost (one more round trip or none) and its refusal."""
    from langgraph.checkpoint.base import empty_checkpoint
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from dw_agent_runtime.adapters.checkpoint import allowlisted_serializer

    from .compiler import LeaseLostError
    from .savers import FencedSaver

    engine = create_async_engine(h.urls.app, pool_size=2)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    serde = allowlisted_serializer(())
    tenant, workspace = (str(x) for x in TENANTS["A"])
    timings: dict[str, Result] = {}
    for variant in ("none", "select", "fused"):
        run = await h.submit("effect", status="running")
        async with h.migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE srt.runs SET lease_owner = 'w:1' WHERE id = :r"), {"r": run}
            )
        saver = FencedSaver(sessions, serde, variant)
        config: Any = {
            "configurable": {
                "thread_id": run,
                "tenant_id": tenant,
                "workspace_id": workspace,
                "checkpoint_ns": "",
                "srt_run": run,
                "srt_token": "w:1",
            }
        }
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {f"out__s{i}": {"text": "x" * 200} for i in range(10)}
        samples_put: list[float] = []
        samples_writes: list[float] = []
        for i in range(600):
            checkpoint = {**checkpoint, "id": str(uuid.uuid1())}
            t0 = time.perf_counter()
            config = await saver.aput(config, checkpoint, {"step": i}, {})
            t1 = time.perf_counter()
            await saver.aput_writes(config, [("out__s1", {"text": "y" * 200})], f"task{i}")
            t2 = time.perf_counter()
            if i >= 100:  # warm
                samples_put.append((t1 - t0) * 1000)
                samples_writes.append((t2 - t1) * 1000)
        timings[variant] = {
            "aput_ms": summary(samples_put),
            "aput_writes_ms": summary(samples_writes),
        }
    # Refusal: the lease moves, the old holder's writes are refused, the new
    # holder's go in. Then the race: the old holder's fence holds FOR SHARE
    # while the new claim waits on it in pg_locks.
    run = await h.submit("effect", status="running")
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE srt.runs SET lease_owner = 'old:1' WHERE id = :r"), {"r": run}
        )
    saver = FencedSaver(sessions, serde, "fused")
    base = {
        "thread_id": run,
        "tenant_id": tenant,
        "workspace_id": workspace,
        "checkpoint_ns": "",
        "srt_run": run,
    }
    old: Any = {"configurable": {**base, "srt_token": "old:1"}}
    new: Any = {"configurable": {**base, "srt_token": "new:1"}}
    ok_before = await saver.aput(old, {**empty_checkpoint(), "id": str(uuid.uuid1())}, {}, {})
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE srt.runs SET lease_owner = 'new:1' WHERE id = :r"), {"r": run}
        )
    refused = {}
    for name, call in (
        ("aput", lambda: saver.aput(old, {**empty_checkpoint(), "id": str(uuid.uuid1())}, {}, {})),
        ("aput_writes", lambda: saver.aput_writes(ok_before, [("x", 1)], "late")),
    ):
        try:
            await call()
            refused[name] = False
        except LeaseLostError:
            refused[name] = True
    accepted_new = await saver.aput(new, {**empty_checkpoint(), "id": str(uuid.uuid1())}, {}, {})
    # The race, with two sessions and pg_locks.
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE srt.runs SET lease_owner = 'old:2' WHERE id = :r"), {"r": run}
        )
    holder = await engine.connect()
    tx = await holder.begin()
    await holder.execute(
        sa.text(
            "SELECT set_config('app.tenant_id', :t, true),"
            " srt.lease_held(CAST(:r AS uuid), 'old:2')"
        ),
        {"t": tenant, "r": run},
    )

    async def takeover() -> float:
        t0 = time.perf_counter()
        async with h.migrator.begin() as conn:
            await conn.execute(
                sa.text("UPDATE srt.runs SET lease_owner = 'new:2' WHERE id = :r"), {"r": run}
            )
        return time.perf_counter() - t0

    claim = asyncio.create_task(takeover())
    waited = False
    for _ in range(50):
        await asyncio.sleep(0.1)
        locks = await h.rows(
            "SELECT count(*) AS n FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
            " WHERE NOT l.granted AND a.datname = current_database()"
        )
        if locks[0]["n"] > 0:
            waited = True
            break
    await holder.execute(
        sa.text(
            "INSERT INTO platform.run_checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id,"
            " task_id, idx, tenant_id, workspace_id, channel, type, value, task_path)"
            " VALUES (:r, '', 'race', 'old', 0, :t, :w, 'x', 'json', '\\x00', '')"
        ),
        {"r": run, "t": tenant, "w": workspace},
    )
    await tx.commit()
    await holder.close()
    blocked_for = await claim
    after = await h.rows("SELECT lease_owner FROM srt.runs WHERE id = :r", r=run)
    await engine.dispose()
    return {
        "timings_ms": timings,
        "round_trips_per_write": {"none": 2, "select": 3, "fused": 2},
        "stale_writes_refused": refused,
        "new_holder_accepted": accepted_new is not None,
        "race": {
            "takeover_waited_in_pg_locks": waited,
            "takeover_blocked_seconds": round(blocked_for, 3),
            "old_write_committed_before_takeover": True,
            "lease_after": after[0]["lease_owner"],
        },
        "pass": all(refused.values()) and waited,
    }


# ======================================================== question 2 ==


async def _arrivals(h: Harness, rate: float, seconds: float) -> tuple[list[str], list[float]]:
    runs: list[str] = []
    latencies: list[float] = []
    started = time.perf_counter()
    n = int(rate * seconds)
    for i in range(n):
        due = started + i / rate
        delay = due - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        t0 = time.perf_counter()
        runs.append(await h.submit("intake", tenant="AB"[i % 2], run_input={}, priority=1))
        latencies.append((time.perf_counter() - t0) * 1000)
    return runs, latencies


async def q2(h: Harness) -> Result:
    out = []
    for notify in (True, False):
        for rate in (20.0, 60.0):
            await reset(h.migrator)
            args = [] if notify else ["--no-notify"]
            procs = [
                h.start(f"q2-{'n' if notify else 'p'}{int(rate)}-w{i}", args=args) for i in (1, 2)
            ]
            await asyncio.sleep(6)
            runs, two_xx = await _arrivals(h, rate, 60.0)
            await h.wait_for(runs, timeout=600, interval=1.0)
            rows = await h.rows(
                "SELECT extract(epoch FROM min(s.started_at) - r.received_at) AS d FROM srt.runs r"
                " JOIN srt.run_steps s ON s.run_id = r.id WHERE r.id = ANY(CAST(:ids AS uuid[]))"
                " GROUP BY r.id, r.received_at",
                ids=runs,
            )
            for p in procs:
                p.stop(30)
            out.append(
                {
                    "wake": "NOTIFY + 1 s poll" if notify else "1 s poll only",
                    "rate_per_s": rate,
                    "runs": len(runs),
                    "two_xx_ms": summary(two_xx),
                    "to_first_step_s": summary([float(r["d"]) for r in rows]),
                }
            )
    return {"cases": out}


# ======================================================== question 3 ==


async def q3(h: Harness) -> Result:
    """The platform's outbox drain (FIFO by `occurred_at`) behind a 100,000
    record import, and the per-company prototype; then the run lane behind
    10,000 queued runs of another company."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from dw_kernel.ports import SystemClock
    from dw_platform.adapters.persistence.outbox_drain import SqlOutboxDrain

    events = int(os.environ.get("SRT_Q3_EVENTS", "100000"))
    queued_runs = int(os.environ.get("SRT_Q3_RUNS", "10000"))
    c_t, c_w = TENANTS["C"]
    d_t, d_w = TENANTS["D"]
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM platform.outbox_events WHERE event_type = 'srt.record_event'")
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.outbox_events (id, tenant_id, workspace_id, event_type,"
                " schema_version, aggregate_id, occurred_at) SELECT gen_random_uuid(), :t, :w,"
                " 'srt.record_event', '1', gen_random_uuid(), clock_timestamp()"
                " FROM generate_series(1, :n)"
            ),
            {"t": c_t, "w": c_w, "n": events},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.outbox_events (id, tenant_id, workspace_id, event_type,"
                " schema_version, aggregate_id, occurred_at) VALUES (gen_random_uuid(), :t, :w,"
                " 'srt.record_event', '1', gen_random_uuid(), clock_timestamp())"
            ),
            {"t": d_t, "w": d_w},
        )
        await conn.execute(
            sa.text("INSERT INTO srt.outbox (tenant_id) SELECT :t FROM generate_series(1, :n)"),
            {"t": c_t, "n": events},
        )
        await conn.execute(sa.text("INSERT INTO srt.outbox (tenant_id) VALUES (:t)"), {"t": d_t})
    engine = create_async_engine(h.urls.app, pool_size=4)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    drain = SqlOutboxDrain(sessions, SystemClock())
    started = time.perf_counter()
    batches = 0
    d_at: float | None = None
    processed = 0
    while d_at is None and time.perf_counter() - started < 1800:
        claimed = await drain.claim_batch(
            event_types=["srt.record_event"], limit=100, max_attempts=5
        )
        if not claimed:
            break
        batches += 1
        for event in claimed:
            await drain.mark_processed(event.id)
            processed += 1
            if str(event.tenant_id) == str(d_t):
                d_at = time.perf_counter() - started
    fifo = {
        "events_ahead": events,
        "batches_until_company_d": batches,
        "events_processed_until_d": processed,
        "seconds_until_company_d": round(d_at, 1) if d_at is not None else None,
    }
    # The per-company prototype: scopes first, a batch per company.
    started = time.perf_counter()
    fair_d = None
    cycles = 0
    while fair_d is None and cycles < 100:
        cycles += 1
        async with sessions() as session, session.begin():
            tenants = list(
                (await session.execute(sa.text("SELECT srt.outbox_scopes_due(10)"))).scalars()
            )
        for tenant in tenants:
            async with sessions() as session, session.begin():
                await session.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
                )
                got = (
                    await session.execute(
                        sa.text(
                            "UPDATE srt.outbox SET processed_at = now() WHERE id IN (SELECT id FROM"
                            " srt.outbox WHERE processed_at IS NULL ORDER BY id LIMIT 50 FOR UPDATE"
                            " SKIP LOCKED) RETURNING tenant_id"
                        )
                    )
                ).all()
            if any(r.tenant_id == d_t for r in got):
                fair_d = time.perf_counter() - started
    await engine.dispose()
    # The run lane: 10,000 queued runs of C, then one of D, two workers up.
    await reset(h.migrator)
    procs = [h.start(f"q3-w{i}") for i in (1, 2)]
    await asyncio.sleep(8)
    async with h.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO srt.runs (id, tenant_id, workspace_id, workflow, status, priority,"
                " received_at, available_at) SELECT gen_random_uuid(), :t, :w, 'intake',"
                " 'queued', 1,"
                " clock_timestamp(), clock_timestamp() FROM generate_series(1, :n)"
            ),
            {"t": c_t, "w": c_w, "n": queued_runs},
        )
    d_run = await h.submit("intake", tenant="D", run_input={}, priority=1)
    await h.wait_for([d_run], timeout=300)
    claim = await h.rows(
        "WITH d AS (SELECT min(s.started_at) AS first, r.received_at FROM srt.runs r"
        " JOIN srt.run_steps s ON s.run_id = r.id WHERE r.id = :r GROUP BY r.received_at)"
        " SELECT extract(epoch FROM d.first - d.received_at) AS d,"
        " (SELECT count(DISTINCT s.run_id) FROM srt.run_steps s WHERE s.tenant_id = :c"
        "  AND s.started_at < d.first) AS c_done FROM d",
        r=d_run,
        c=c_t,
    )
    for p in procs:
        p.stop(60)
    return {
        "platform_outbox_fifo": fifo,
        "per_company_outbox": {"cycles": cycles, "seconds_until_company_d": round(fair_d or -1, 3)},
        "run_lane": {
            "queued_ahead_for_c": queued_runs,
            "d_first_step_after_s": round(float(claim[0]["d"]), 3),
            "c_runs_claimed_by_then": claim[0]["c_done"],
        },
    }


# ======================================================== question 6 ==


async def q6(h: Harness) -> Result:
    from .manifest import measure

    return await measure(h, int(os.environ.get("SRT_Q6_ROOTS", "1000")))


EXPERIMENTS: dict[str, Callable[[Harness], Awaitable[Result]]] = {
    "t1": t1,
    "t1r": t1_recursion,
    "t2": t2,
    "t3": t3,
    "t4": t4,
    "t5": t5,
    "t6": t6,
    "t7": t7,
    "t8": t8,
    "q1": q1,
    "q2": q2,
    "q3": q3,
    "q6": q6,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser("measure")
    parser.add_argument("names", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--only")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = list(EXPERIMENTS) if args.names == ["all"] else args.names

    async def go() -> None:
        for name in names:
            shutil.rmtree(out / name, ignore_errors=True)
            h = Harness(urls(), out / name)
            await reset(h.migrator)
            started = time.time()
            try:
                if name == "t3" and args.only:
                    result = await t3(h, args.only)
                else:
                    result = await EXPERIMENTS[name](h)
            finally:
                h.stop_all()
                await h.dispose()
            result["_seconds"] = round(time.time() - started, 1)
            (out / f"{name}.json").write_text(json.dumps(result, indent=1, default=str), "utf-8")
            print(
                name,
                "pass" if result.get("pass") else "see json",
                result["_seconds"],
                "s",
                flush=True,
            )

    asyncio.run(go())
    return 0
