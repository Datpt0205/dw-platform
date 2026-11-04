"""The six reference workflows of discovery 14 and the variants that carry the
measurements of questions 7-9, as step-tree documents.

Faults are not part of a document: a run's input names them per step
(`faults`), so one document serves the clean run and the crash matrix.
"""

from __future__ import annotations

from typing import Any

from .doc import SrtDoc


def llm(step_id: str, seconds: float = 0.05, **extra: Any) -> dict[str, Any]:
    return {"id": step_id, "type": "ai.llm@1", "config": {"seconds": seconds, **extra}}


def send(step_id: str, provider: str, mode: str = "keyed", **extra: Any) -> dict[str, Any]:
    step: dict[str, Any] = {
        "id": step_id,
        "type": "tool.call@1",
        "config": {"provider": provider, "mode": mode, "input": {"lead": "{{ input.lead }}"}},
    }
    step.update(extra)
    return step


def write(step_id: str, **extra: Any) -> dict[str, Any]:
    step: dict[str, Any] = {"id": step_id, "type": "data.write@1", "config": {"input": {"v": 1}}}
    step.update(extra)
    return step


def approval(
    step_id: str, approved: list[Any], rejected: list[Any], **config: Any
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "human.approval@1",
        "config": {"approved": approved, "rejected": rejected, **config},
    }


def parallel(step_id: str, *lanes: list[Any]) -> dict[str, Any]:
    return {"id": step_id, "type": "logic.parallel@1", "config": {"lanes": list(lanes)}}


def loop(step_id: str, body: list[Any], max_iterations: int, **config: Any) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "logic.loop@1",
        "config": {"body": body, "max_iterations": max_iterations, **config},
    }


def switch(
    step_id: str, on: str, cases: dict[str, list[Any]], default: list[Any]
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "logic.switch@1",
        "config": {"on": on, "cases": cases, "default": default},
    }


def brk(step_id: str) -> dict[str, Any]:
    return {"id": step_id, "type": "logic.break@1", "config": {}}


def sub(step_id: str, workflow: str) -> dict[str, Any]:
    return {"id": step_id, "type": "flow.subworkflow@1", "config": {"workflow": workflow}}


def doc(key: str, steps: list[Any], max_steps: int = 500) -> SrtDoc:
    return SrtDoc.model_validate({"key": key, "steps": steps, "limits": {"max_steps": max_steps}})


# RW1: lead intake, the baseline.
RW1 = doc(
    "rw1",
    [
        llm("score", answer={"tier": "{{ input.tier }}"}),
        switch(
            "route",
            "{{ steps.score.tier }}",
            {"hot": [approval("approve", [send("email", "smtp", "none")], [write("note")])]},
            [write("nurture")],
        ),
        write("log"),
    ],
)

# RW2: purchase. Three lanes, a join, two approvers who must both approve, a
# PO with three attempts and an error lane that releases the budget.
RW2 = doc(
    "rw2",
    [
        parallel(
            "check",
            [send("budget", "erp", "keyed")],
            [llm("supplier", 0.2)],
            [llm("risk", 0.3, answer={"risk": "low"})],
        ),
        approval("approve2", [], [], assignees=["head", "cfo"], rule="all"),
        send(
            "po",
            "po",
            "keyed",
            retry={"max_attempts": 3, "backoff_s": 0.2},
            on_error="route",
            error_lane=[send("release", "erp", "keyed")],
        ),
        write("done"),
    ],
)

# RW2 for question 7: uneven lanes (1.0 s beside 3 x 0.3 s), a nested
# parallel, a switch inside a lane, and a parallel in a loop body.
RW2_Q7 = doc(
    "rw2_q7",
    [
        parallel(
            "uneven",
            [llm("long", 1.0)],
            [llm("s1", 0.3), llm("s2", 0.3), llm("s3", 0.3)],
            [
                llm("pick", 0.05, answer={"case": "b"}),
                switch(
                    "inlane",
                    "{{ steps.pick.case }}",
                    {"a": [llm("ca", 0.1)], "b": [llm("cb", 0.1)]},
                    [llm("cd", 0.1)],
                ),
            ],
            [parallel("nested", [llm("n1", 0.2)], [llm("n2", 0.4)])],
        ),
        write("after_uneven"),
        loop(
            "rounds",
            [parallel("inloop", [llm("l1", 0.1)], [llm("l2", 0.2)]), write("tally")],
            3,
            **{"while": {"iter_lt": 3}},
        ),
        write("end"),
    ],
)

# RW2 for T2: one lane waits out a 5 s backoff while the others go on.
RW2_T2 = doc(
    "rw2_t2",
    [
        parallel(
            "check",
            [send("budget", "erp", "keyed", retry={"max_attempts": 2, "backoff_s": 5.0})],
            [llm("a1", 0.3), llm("a2", 0.3), llm("a3", 0.3)],
            [llm("b1", 0.5), llm("b2", 0.5)],
        ),
        write("done"),
    ],
)

# RW2 for question 9 and T7: ten steps, the PO at step 7 with `incident`; a
# parallel block before it.
RW2_T7 = doc(
    "rw2_t7",
    [
        write("s1"),
        parallel(
            "s2", [send("budget", "erp", "keyed")], [llm("supplier", 0.1)], [llm("risk", 0.1)]
        ),
        send("s3", "crm", "keyed"),
        write("s4"),
        llm("s5", 0.05),
        send("s6", "crm", "keyed"),
        send("s7", "po", "keyed", retry={"max_attempts": 3, "backoff_s": 0.2}, on_error="incident"),
        write("s8"),
        send("s9", "crm", "keyed"),
        write("s10"),
    ],
)

# RW2 with a lane that fails and no error lane: the others are cancelled.
RW2_FAIL = doc(
    "rw2_fail",
    [
        parallel(
            "check",
            [llm("slow", 3.0)],
            [llm("bad", 0.3, retry={"max_attempts": 1})],
            [llm("other", 3.0)],
        ),
        write("never"),
    ],
)

# RW2 for T8: three lanes each in a 30 s step, cancelled midway.
RW2_LONG = doc(
    "rw2_long",
    [parallel("check", [llm("x1", 30.0)], [llm("x2", 30.0)], [llm("x3", 30.0)]), write("never")],
)

# RW3: a map of 100 items, one model call each (1 KB), then a summary.
RW3 = doc(
    "rw3",
    [
        {
            "id": "items",
            "type": "logic.map@1",
            "config": {
                "count": 100,
                "max_parallel": 10,
                "body": [llm("score_item", 0.0, size=1024)],
            },
        },
        llm("summary", 0.0, size=1024),
    ],
)

# RW4: draft, review, revise on rejection; five iterations at most; a wait in
# the body; `logic.break` on approval.
RW4 = doc(
    "rw4",
    [
        loop(
            "rework",
            [
                llm("draft", 0.05),
                approval("review", [brk("ok")], [llm("revise", 0.05)]),
            ],
            5,
            max_reached=[send("escalate", "smtp", "none")],
        ),
        send("publish", "crm", "keyed"),
    ],
)

# RW4 for question 8: ten iterations, an approval in each, an effect in each,
# and `limits.max_steps` below what ten iterations need (2 steps each).
RW4_Q8 = doc(
    "rw4_q8",
    [
        loop(
            "ten",
            [write("work"), approval("gate", [], [])],
            10,
            **{"while": {"iter_lt": 10}},
        ),
        write("after"),
    ],
    max_steps=13,
)

# The same loop without waits, the control: `recursion_limit` alone stops it.
RW4_NOWAIT = doc(
    "rw4_nowait",
    [loop("ten", [write("work"), llm("think", 0.0)], 10, **{"while": {"iter_lt": 10}})],
)

# RW5: Zalo, and on failure email; never both.
RW5 = doc(
    "rw5",
    [
        send("zalo", "zalo", "keyed", on_error="route", error_lane=[send("email", "smtp", "none")]),
        write("logged"),
    ],
)

# RW6: a parent, a child with a wait, a grandchild (three levels).
RW6 = doc("rw6", [llm("p1", 0.05), sub("child", "rw6_child"), write("p2")])
RW6_CHILD = doc(
    "rw6_child",
    [llm("c1", 0.05), approval("c_ok", [], []), sub("grand", "rw6_grand"), write("c2")],
)
RW6_GRAND = doc("rw6_grand", [llm("g1", 0.05), write("g2")])
RW6_GRAND_LONG = doc("rw6_grand_long", [llm("g1", 30.0), write("g2")])
RW6_CHILD_LONG = doc(
    "rw6_child_long",
    [llm("c1", 0.05), approval("c_ok", [], []), sub("grand", "rw6_grand_long"), write("c2")],
)
RW6_LONG = doc("rw6_long", [llm("p1", 0.05), sub("child", "rw6_child_long"), write("p2")])

# T3 / question 10: one effect between two steps, the matrix's subject.
EFFECT = doc("effect", [write("before"), send("fx", "crm", "keyed"), write("after")])
INTERNAL = doc("internal", [write("before"), write("fx"), write("after")])

# T6: twenty steps with large outputs, and a parked run.
BIG20 = doc("big20", [llm(f"b{i:02}", 0.0, size=100 * 1024) for i in range(20)])
BIG20_60K = doc("big20_60k", [llm(f"b{i:02}", 0.0, size=60 * 1024) for i in range(20)])

# Question 2: a short workflow behind the Data Hub endpoint.
INTAKE = doc("intake", [llm("first", 0.02), write("stored")])

WORKFLOWS: dict[str, SrtDoc] = {
    d.key: d
    for d in (
        RW1,
        RW2,
        RW2_Q7,
        RW2_T2,
        RW2_T7,
        RW2_FAIL,
        RW2_LONG,
        RW3,
        RW4,
        RW4_Q8,
        RW4_NOWAIT,
        RW5,
        RW6,
        RW6_CHILD,
        RW6_GRAND,
        RW6_GRAND_LONG,
        RW6_CHILD_LONG,
        RW6_LONG,
        EFFECT,
        INTERNAL,
        BIG20,
        BIG20_60K,
        INTAKE,
    )
}
