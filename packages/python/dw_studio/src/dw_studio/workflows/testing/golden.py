"""Golden traces of the W1 core's execution rules (workflow-engine R7.1, WE45;
V4.34).

Each `GoldenCase` is a reference document with how its `tool` door answers,
the decisions of its approvals and its input, and the trace it must give on
every runner a test registers (`GoldenRunner`): the nodes run, in their order,
joins included (`join__<id>` is a join firing), and how the run ended. This
ticket records the sequential block, `logic.switch`, an approval's decision
lanes and try/catch, `outcome_unknown` never entering an error lane among
them; workflow-engine/05, /06 and /09 add their rules' cases (lanes cancelled
and loop counts arrive with parallel lanes and loops).

Nothing here runs a graph: Studio never imports LangGraph (ADR-0112
Amendments 2026-11-03). A runner is the test's: on LangGraph it is
`dw_agent_runtime.testing.studio_runs.langgraph_trace`, the compiler
`LangGraphWorkflowRunner` runs. `compare` names the first difference.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from dw_agent_runtime.wflite.ir import ERROR_LANE
from dw_kernel.dispatch import NotDispatchedError, OutcomeUnknownError
from dw_kernel.run_mode import RunMode


@dataclass(frozen=True)
class GoldenTrace:
    nodes: tuple[str, ...]
    # None when the run completed; the failure code otherwise.
    failed: str | None = None
    # The status of each of the run's waits at the end, in the order they
    # opened (workflow-engine/05); a runner with no store sees none.
    waits: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoldenCase:
    name: str
    document: Mapping[str, Any]
    expected: GoldenTrace
    # How the `tool` door answers, call by call; the last answer repeats.
    tool_script: Sequence[Mapping[str, Any] | BaseException] = ({"done": True},)
    approval_decisions: Mapping[str, str] = field(default_factory=dict)
    run_mode: RunMode = "live"
    # The run's input, `{{ work.<name> }}` to its steps.
    work: Mapping[str, Any] = field(default_factory=dict)


class GoldenRunner(Protocol):
    name: str

    async def run(self, case: GoldenCase) -> GoldenTrace: ...


def compare(expected: GoldenTrace, observed: GoldenTrace) -> list[str]:
    """Every difference, first the end, then the first node out of place."""
    problems: list[str] = []
    if expected.failed != observed.failed:
        problems.append(f"the run ended {observed.failed!r}, not {expected.failed!r}")
    for index, (want, got) in enumerate(zip(expected.nodes, observed.nodes, strict=False)):
        if want != got:
            problems.append(f"node {index} is {got!r}, not {want!r}")
            break
    if len(expected.nodes) != len(observed.nodes):
        problems.append(f"{len(observed.nodes)} nodes ran, not {len(expected.nodes)}")
    if expected.waits != observed.waits:
        problems.append(f"the waits ended {observed.waits!r}, not {expected.waits!r}")
    return problems


def _step(
    step_id: str, type_: str, *, on_error: str = "fail", attempts: int = 1, **config: Any
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": type_,
        "config": dict(config),
        "retry": {"max_attempts": attempts, "backoff": "fixed"},
        "timeout_s": 30,
        "on_error": on_error,
    }


def _send(step_id: str, **policy: Any) -> dict[str, Any]:
    return _step(step_id, "fixture.effect@1", **policy)


def _catching(step: dict[str, Any], lane: list[dict[str, Any]]) -> dict[str, Any]:
    return {**step, ERROR_LANE: lane}


def _document(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "dw.workflow/v1",
        "triggers": [{"id": "khi_chay", "type": "fixture.trigger@1", "config": {"source": "x"}}],
        "steps": list(steps),
    }


CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        "sequential",
        _document(_send("a"), _send("b"), _send("c")),
        GoldenTrace(("a", "b", "c")),
    ),
    GoldenCase(
        "switch takes the matching lane once, then the step after the block",
        _document(
            _step(
                "re",
                "logic.switch@1",
                on="{{ work.kenh }}",
                cases={"email": [_send("gui_email")], "zalo": [], "sms": [_send("gui_sms")]},
                default=[],
            ),
            _send("sau"),
        ),
        GoldenTrace(("re", "gui_sms", "join__re", "sau")),
        work={"kenh": "sms"},
    ),
    GoldenCase(
        "an approval's rejected lane, empty, goes straight to the step after",
        _document(
            _step(
                "duyet",
                "human.approval@1",
                decision_class="lead.send",
                proposal={"x": 1},
                approved=[_send("gui")],
                rejected=[],
            ),
            _send("sau"),
        ),
        GoldenTrace(("duyet", "join__duyet", "sau")),
        approval_decisions={"duyet": "rejected"},
        run_mode="simulate",
    ),
    GoldenCase(
        "try/catch: an exhausted step routes to its error lane and rejoins",
        _document(
            _catching(_send("goi", on_error="route", attempts=2), [_send("bao_loi")]),
            _send("sau"),
        ),
        GoldenTrace(("goi", "bao_loi", "join__goi", "sau")),
        tool_script=(NotDispatchedError("down"), NotDispatchedError("down"), {"done": True}),
    ),
    GoldenCase(
        "outcome_unknown never enters the error lane",
        _document(
            _catching(_send("goi", on_error="route", attempts=3), [_send("bao_loi")]),
            _send("sau"),
        ),
        GoldenTrace((), "outcome_unknown"),
        tool_script=(OutcomeUnknownError("may have been applied"),),
    ),
)


# workflow-engine/05 (R6.13, R7.1; V4.34): a run cancelled while it waits has
# its wait cancelled in the same transaction. A trace of the database's
# trigger, so it runs on a runner with the real store
# (`dw_studio/tests/integration/test_run_waits_db.py`); `failed` is the run's
# status, `cancelled`. The node trace is the steps recorded: `truoc` done, `cho`
# waiting.
CANCELLED_WHILE_WAITING = GoldenCase(
    "a run cancelled while it waits cancels its wait in the same transaction",
    _document(_send("truoc"), _step("cho", "fixture.wait@1")),
    GoldenTrace(("truoc", "cho"), "cancelled", waits=("cancelled",)),
)
