"""A Studio agent run's seams (agent-builder ticket 03; spec R3; ADR-0117
decision 5).

A Studio agent run is taken like any Studio run (`run_studio`, workflow-
engine/03): its row, its manifest and its pinned document read under its
tenant. What differs is what is compiled and how a turn goes in and out, and
those are the ports here, declared by the runtime so that the platform core
never imports `dw_studio`:

- `StudioAgentPort`, satisfied by `dw_studio.agents.adapters.StudioGraphSource`:
  whether the agent is on (R3.8), the build of the pinned version behind the
  hash gate (R3.3), and the turn read and the reply written by run id, so a
  conversation's content never enters `worker_runs.input` or `result`
  (ADR-0117 decision 6);
- `AgentCompilerPort`, satisfied by `adapters.studio_agents.StudioAgentCompiler`:
  the LangChain assembly, injected into the source at the composition root,
  since `dw_studio` imports no LangChain;
- `ToolKindsLoaderPort`, satisfied at the composition root by the `object_crud`
  generator (tools-and-skills/03): the sources and factories of a run's tools,
  loaded for the run's company;
- `AgentThreadsPort`: a finished agent run's checkpoints gone at once, since its
  thread is its own (`thread_id = run_id`), never waiting for retention.

The graph is cached by the runner, in its one LRU of `GRAPH_CACHE_SIZE`, under
`(tenant_id, agent_version_id, pinned_hash)` (R3.1, R3.2): a draft keeps its id
when edited and changes its hash, so a new run never takes the old content's
graph.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import StudioRun
from dw_agent_runtime.tool_kinds import PinnedToolSource, ToolKindFactory, ToolsetEntry

__all__ = [
    "AGENT_DISABLED",
    "AGENT_KIND",
    "AGENT_RECURSION_LIMIT",
    "AGENT_TOOL_APPROVAL_PREFIX",
    "AGENT_TURN_UNWIRED",
    "APPROVAL_WAIT_UNAVAILABLE",
    "DEFINITION_MISMATCH",
    "DRAFT_OUTSIDE_SIMULATE",
    "ENABLED_TRIGGERS",
    "AgentBlueprint",
    "AgentCompilerPort",
    "AgentMessage",
    "AgentRefusedError",
    "AgentThreadsPort",
    "BuiltAgent",
    "LoadedToolKinds",
    "RunNames",
    "RunNamesPort",
    "StudioAgentPort",
    "StudioAgentPorts",
    "ToolKindsLoaderPort",
    "agent_cache_key",
]

AGENT_KIND: Final = "agent"

# The run ends `failed` with one of these before any step runs (workflow-engine
# R5.9's list of a run's end codes): the pinned content's hash differs from what
# the run pinned, a draft in a run that does not simulate (R3.3), the agent off
# for a trigger that reads `enabled` (R3.8).
DEFINITION_MISMATCH: Final = "definition_mismatch"
DRAFT_OUTSIDE_SIMULATE: Final = "draft_outside_simulate"
AGENT_DISABLED: Final = "agent_disabled"
# No turn port for the run's trigger yet (agent-builder/04 brings `chat`,
# agent-lifecycle the trials): closed, never a run with no question.
AGENT_TURN_UNWIRED: Final = "agent_turn_unwired"
# A tool call that waits for a person, in a runner with no Studio wait for an
# agent yet (workflow-engine/05 brings the wait): the run ends, never a guess.
APPROVAL_WAIT_UNAVAILABLE: Final = "approval_wait_unavailable"

# The trigger kinds whose run reads the agent's `enabled` and settings row
# (R3.8): a person's chat and, in W2, a workflow's agent node and a linked
# agent. A `simulate` or `eval` run of the builder or the quality gate does not.
ENABLED_TRIGGERS: Final = frozenset({"chat", "agent_node", "agent_link"})

# The behavioural limit of R3.6 in W1, with the run's cost ceiling of
# `LimitsMiddleware`: steps of one turn. The document's `limits` are W2.
AGENT_RECURSION_LIMIT: Final = 50

# What a Studio agent's gated tool call raises its approval under.
AGENT_TOOL_APPROVAL_PREFIX: Final = "studio.agent.tool."


class AgentRefusedError(Exception):
    """The run cannot run this agent; `code` is the run's end code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """One message of a turn: the question and the history before it."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class AgentBlueprint:
    """What a version's compiled agent is built from: its company, the
    version, the document's W1 sections and the run's pinned answers. The
    content has passed the hash gate."""

    tenant_id: UUID
    version_id: UUID
    # The hash the run pinned and the content was checked against.
    pinned_hash: str
    profile_id: str
    agent_name: str
    instructions: str
    toolset: tuple[ToolsetEntry, ...]
    resolver: PinnedResolver
    # The containment frame the version pinned (`studio.agent_frame@<semver>`).
    frame_id: str
    frame_version: str


@dataclass(frozen=True)
class BuiltAgent:
    """A compiled agent and whether its version is a draft, which only a
    `simulate` run may run (R3.3), asked at every take, a cache hit too."""

    graph: Any
    draft: bool


class AgentCompilerPort(Protocol):
    async def compile(self, blueprint: AgentBlueprint) -> Any:
        """The version's agent compiled with the runner's checkpointer."""
        ...


class StudioAgentPort(Protocol):
    async def enabled(self, tenant_id: UUID, artifact_id: UUID) -> bool:
        """A settings row says `enabled = true` for a component not deleted."""
        ...

    async def build(self, taken: StudioRun) -> BuiltAgent:
        """The pinned version compiled, or `AgentRefusedError` with
        `definition_mismatch` when its content hashes to anything but
        `taken.pinned_hash`. Called on a cache miss only."""
        ...

    async def turn(self, taken: StudioRun) -> Sequence[AgentMessage]:
        """The run's turn: the history and the question, oldest first."""
        ...

    async def reply(self, taken: StudioRun, text: str) -> None:
        """The run's final answer, where its caller reads it."""
        ...


@dataclass(frozen=True)
class LoadedToolKinds:
    """A run's tool kinds: `kind -> source` and `kind -> factory`."""

    sources: Mapping[str, PinnedToolSource]
    factories: Mapping[str, ToolKindFactory]


class ToolKindsLoaderPort(Protocol):
    async def load(self, tenant_id: UUID, entries: Sequence[ToolsetEntry]) -> LoadedToolKinds:
        """Each kind's source and factory for ``entries``, for ``tenant_id``,
        the company the run says."""
        ...


class AgentThreadsPort(Protocol):
    async def forget(self, tenant_id: UUID, thread_id: UUID) -> None:
        """The thread's checkpoints deleted, when the run that is the thread
        has ended and none on it still waits; nothing otherwise."""
        ...


@dataclass(frozen=True, slots=True)
class RunNames:
    """Whom a run's frame says is asking, and in which workspace."""

    person: str
    workspace: str


class RunNamesPort(Protocol):
    async def names(self, run: RunContext) -> RunNames:
        """The display names of the run's principal and workspace, read under
        the run's tenant."""
        ...


@dataclass(frozen=True)
class StudioAgentPorts:
    """What a runner that runs Studio agents needs (`run_studio`)."""

    source: StudioAgentPort
    threads: AgentThreadsPort


def agent_cache_key(taken: StudioRun) -> tuple[str, ...]:
    """The graph's key in the runner's one cache (R3.1, R3.2): the company,
    the version and the hash the manifest pinned, never the version alone."""
    return (AGENT_KIND, str(taken.tenant_id), str(taken.artifact_version_id), taken.pinned_hash)
