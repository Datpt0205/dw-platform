"""A sub-agent is the same platform agent, narrowed — never a looser one.

`SubAgentMiddleware` gives the model a `task` tool that runs a second agent with
its own model, tools and prompt. Useful, and the shape of two escapes if the
platform hands it over unattended. Both were MEASURED on the pinned deepagents
rather than reasoned about, because a library's composition is a fact about the
outside world:

**What is already safe.** The sub-agent sees the caller's `RunContext` — same
tenant, same workspace, same scopes, same autonomy level. The context is graph
level, so it carries without being passed, and a `SubAgent` spec has no field
that could replace it. Inheriting *more* than the caller is not reachable from
here.

**What is NOT safe by default, and is the reason this module exists.** The
parent's middleware does not wrap the sub-agent's model call. Measured: with a
probe middleware on both, the order is parent, child, parent — the child's turn
runs inside the child's own stack alone. So the parent's spend ceiling does not
see a single token the sub-agent burns. A worker at a $2 ceiling could spawn a
sub-agent and spend without limit, and the ledger would read as if nothing
happened.

The fix is not a warning in a docstring. `sub_agent_spec` builds the child's
middleware from the parent's spec and hands it **the same ledger object**, so
parent turns and child turns spend against one ceiling. Its tools are built by
`platform_tools` from the parent's executor, so a sub-agent's side effect goes
through the same authorization, idempotency and audit as any other — a context
that passes raw LangChain tools here would be handing the model a way around the
executor, which is why this function takes tool DEFINITIONS and not tools.

`StateBackend`, deliberately: `SubAgentMiddleware` requires a backend, and every
other one reaches a filesystem. The platform installs no file tools (see
`agent_factory`), so a backend that lives in graph state keeps that true.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel

from dw_agent_runtime.adapters.langchain_tools import (
    OfferedToolsOnlyMiddleware,
    OneApprovalPerStepMiddleware,
    PlatformToolErrorsMiddleware,
    ScopedToolsMiddleware,
    platform_tools,
)
from dw_agent_runtime.adapters.run_budget import RunBudgetMiddleware
from dw_agent_runtime.contracts import ToolDefinition

if TYPE_CHECKING:
    from dw_agent_runtime.adapters.agent_factory import AgentSpec

__all__ = ["SubAgentSpec", "sub_agent_middleware", "sub_agent_spec"]


@dataclass(frozen=True)
class SubAgentSpec:
    """One narrower agent the main one may delegate to.

    `offered` is tool DEFINITIONS, not tools. The difference is the boundary: a
    definition is turned into a callable by `platform_tools`, which wraps it in
    the executor; a ready-made tool would be whatever the caller built, and the
    executor could be missing from it with nothing to say so.

    It must be a subset of what the parent offers. A sub-agent that can call a
    tool its caller cannot is a way to reach a tool by asking for it twice, and
    `sub_agent_spec` refuses it.
    """

    name: str
    description: str
    offered: Sequence[ToolDefinition]
    # Which model, and whose price — two questions, the same split
    # `CompactionSpec` uses. The object is built by the composition root, because
    # that is the only place that knows how to build one; the profile id is what
    # the turn is charged at. `None` on either means the parent's.
    model: BaseChatModel | None = None
    profile_id: str | None = None
    system_prompt: str | None = None


def sub_agent_spec(parent: AgentSpec, child: SubAgentSpec) -> dict[str, Any]:
    """The `SubAgent` dict to hand `SubAgentMiddleware`, built from the parent.

    Everything the platform guarantees for an agent is re-applied here rather
    than inherited, because none of it is inherited: the measurement in this
    module's docstring is that the parent's middleware does not run for a child
    turn.
    """
    parent_names = {definition.name for definition in parent.offered}
    extra = sorted({definition.name for definition in child.offered} - parent_names)
    if extra:
        raise ValueError(
            f"sub-agent {child.name!r} offers {extra}, which its caller does not. "
            "A sub-agent narrows a worker; it cannot widen one."
        )
    offered = list(child.offered)
    profile_id = child.profile_id or parent.profile_id
    middleware: list[AgentMiddleware[Any, Any]] = [
        OfferedToolsOnlyMiddleware(offered),
        ScopedToolsMiddleware(offered),
        OneApprovalPerStepMiddleware(offered, copy=parent.copy, approvals=parent.executor),
        PlatformToolErrorsMiddleware(offered, copy=parent.copy),
        # The SAME ledger object the parent holds — not a copy, not a fresh one.
        # This single argument is what keeps a delegated turn inside the ceiling
        # the run was given.
        RunBudgetMiddleware(parent.budget, parent.profiles, profile_id, parent.pricing),
    ]
    spec: dict[str, Any] = {
        "name": child.name,
        "description": child.description,
        "tools": platform_tools(
            offered,
            parent.registry,
            parent.executor,
            approval_type_prefix=parent.approval_type_prefix,
            copy=parent.copy,
        ),
        "middleware": middleware,
        "model": child.model if child.model is not None else parent.model,
    }
    if child.system_prompt is not None:
        spec["system_prompt"] = child.system_prompt
    return spec


def sub_agent_middleware(
    parent: AgentSpec, children: Sequence[SubAgentSpec]
) -> AgentMiddleware[Any, Any]:
    """The middleware that adds the `task` tool, with every child built safely."""
    from deepagents import CompiledSubAgent, SubAgent, SubAgentMiddleware
    from deepagents.backends import StateBackend

    # `cast`: `SubAgent` is a TypedDict whose optional keys are built here by
    # name. Constructing it as a literal would mean repeating the same branch on
    # `system_prompt` inside a dict display, which is how the two copies drift.
    built = cast(
        "list[SubAgent | CompiledSubAgent]",
        [sub_agent_spec(parent, child) for child in children],
    )
    return SubAgentMiddleware(backend=StateBackend(), subagents=built)
