"""The worker's chat-command seam (channels Z5, ADR 0007).

The platform worker hosts no graph, so it has no runner to resume a decided run
on and registers no decide command itself; a context that hosts its graph here
builds one with `build_channel_decision_command` over its runner and hands it to
`build_channel_commands`, which puts it first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.langgraph_runner import LangGraphWorkflowRunner
from dw_agent_runtime.channel_decisions import ChannelDecisionCommand
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_observability.telemetry import NullTelemetry
from dw_platform.application.approval_codes import ApprovalSubjectVersions
from dw_worker.main import build_channel_commands, build_channel_decision_command
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit


@dataclass
class _Runner:
    """Stands in for the runner a context hosts its graph on; its store and its
    telemetry, which the decision service records approval waits on, are read."""

    run_store: Any = field(default_factory=object)
    telemetry: Any = field(default_factory=NullTelemetry)


def _decision_command(secret: str) -> ChannelDecisionCommand:
    return build_channel_decision_command(
        WorkerSettings(approval_code_secret=secret),  # type: ignore[call-arg]
        cast(async_sessionmaker[AsyncSession], object()),
        runner=cast(LangGraphWorkflowRunner, _Runner()),
        subjects=ApprovalSubjectVersions(),
        strict_approval_prefixes=frozenset({"purchasing."}),
        ids=Uuid4Generator(),
        clock=SystemClock(),
    )


def test_the_platform_worker_registers_no_chat_command_of_its_own() -> None:
    assert build_channel_commands().commands() == []


def test_a_decide_command_is_asked_first() -> None:
    decisions = _decision_command("a-code-secret-of-32-bytes-or-so")
    assert [name for name, _ in build_channel_commands(decisions).commands()] == [
        "approval_decision"
    ]


def test_the_decide_command_resumes_on_the_contexts_runner_with_its_strict_prefixes() -> None:
    decisions = _decision_command("a-code-secret-of-32-bytes-or-so")
    flow = decisions.service.approval_flow
    assert flow.strict_approval_prefixes >= {"purchasing."}
    assert decisions.service.key is not None


def test_without_a_code_secret_the_command_still_answers_but_holds_no_key() -> None:
    """It answers "not enabled" rather than let the words reach a model."""
    assert _decision_command("").service.key is None
