"""The worker's own prompt, placed in front of what the harness wrote.

`deepagents` builds part of the system message itself. `SkillsMiddleware`
appends the skills catalogue - the only channel that tells a model which skills
exist - and `FilesystemMiddleware` appends the host-path routing for a
composite backend. Both are pinned OUTSIDE anything a caller passes in
`middleware=`, and outer middleware runs first, so by the time a caller's own
prompt middleware is reached those sections are already in `request`.

`dynamic_prompt` REPLACES the system message. Used for a worker prompt it
therefore deletes them on every model call, silently: nothing errors, the
prompt is complete on its own terms, and the only symptom is a model that never
uses a skill it was never told about. That is how `sales_chat` shipped a
drawing tool the assistant answered around for a week - `ui.present` was
offered and `generative-ui` was unreachable, so every answer came back as
prose.

Prepending is also the order `create_deep_agent` produces for its own
`system_prompt` parameter: the caller's text first, the harness sections
appended below it. That parameter is not usable for a prompt that names today's
date and the screen in view, because it is resolved once at build time and
these agents are compiled once per process - hence a middleware that renders
per call and keeps the same shape.

The text is a registry artifact, `(prompt_id, version)`, never a free callable:
a worker's wording is versioned like every other prompt, a tenant whose wording
differs gets its own artifact through `TenantOverlay`, and the version the
runner bills the loop under is the version rendered here. Only the per-call
VARIABLES come from the host. Whose override applies is read from the run's
`RunContext`, which the runner built from a verified context - never from the
request, and never from anything the model or a user wrote.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Final, cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.prompts import PromptRegistry, assemble_system_prompt
from dw_agent_runtime.studio_agent import RunNamesPort
from dw_kernel.errors import ConfigError, TenantContextMissingError

__all__ = ["ContainedAgentPrompt", "WorkerSystemPrompt"]

# The frame's clock reads Vietnam's time, which keeps no daylight saving.
_VIETNAM: Final = timezone(timedelta(hours=7))


class WorkerSystemPrompt(AgentMiddleware[Any, Any]):
    """Renders the worker prompt per model call and puts it above the rest."""

    def __init__(
        self,
        prompts: PromptRegistry,
        prompt_id: str,
        prompt_version: str,
        variables: Callable[[ModelRequest[Any]], dict[str, str]],
    ) -> None:
        super().__init__()
        # At build, not on the first call: an agent is compiled once per
        # process, and a pin that names nothing is a deploy that cannot answer.
        if not prompts.has(prompt_id, prompt_version):
            raise ConfigError(
                "agent prompt not registered",
                details={"prompt_id": prompt_id, "version": prompt_version},
            )
        self._prompts = prompts
        self._prompt_id = prompt_id
        self._prompt_version = prompt_version
        self._variables = variables

    def _render(self, request: ModelRequest[Any]) -> str:
        run_context = getattr(request.runtime, "context", None)
        if not isinstance(run_context, RunContext):
            # Whose wording to render is the run's tenant. A run that never
            # passed the boundary that resolves it gets nobody's.
            raise TenantContextMissingError("an agent prompt is rendered for a run's tenant")
        rendered = self._prompts.render(
            self._prompt_id,
            self._prompt_version,
            self._variables(request),
            tenant_id=run_context.tenant_id,
        )
        # The artifact's fixed part, then its per-call part.
        parts = (rendered.system.strip(), rendered.user.strip())
        return "\n\n".join(part for part in parts if part)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        appended = list(request.system_message.content_blocks) if request.system_message else []
        message = SystemMessage(
            content_blocks=[cast(Any, {"type": "text", "text": self._render(request)}), *appended]
        )
        return await handler(request.override(system_message=message))


class ContainedAgentPrompt(AgentMiddleware[Any, Any]):
    """A Studio agent's system message, per model call (agent-builder R2.1-R2.3,
    R1.12; ADR-0117 decision 4): the containment frame `frame_id@version`
    assembled at the platform layer with the company's instructions in their
    block (`assemble_system_prompt`), never a company's override of the frame.

    The frame's values are the run's: today's date and time from `clock`, the
    agent's name from its version, and the asking person's and workspace's
    names read for the run (`RunNamesPort`), each contained by the assembler.
    Placed above whatever the harness wrote, as `WorkerSystemPrompt` is."""

    def __init__(
        self,
        prompts: PromptRegistry,
        frame_id: str,
        frame_version: str,
        *,
        instructions: str,
        agent_name: str,
        names: RunNamesPort,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__()
        # At build: a frame nobody registered is a version that cannot answer.
        prompts.platform_artifact(frame_id, frame_version)
        self._prompts = prompts
        self._frame = (frame_id, frame_version)
        self._instructions = instructions
        self._agent_name = agent_name
        self._names = names
        self._clock = clock

    async def _render(self, request: ModelRequest[Any]) -> str:
        run_context = getattr(request.runtime, "context", None)
        if not isinstance(run_context, RunContext):
            raise TenantContextMissingError("an agent prompt is rendered for a run's tenant")
        names = await self._names.names(run_context)
        now = self._clock().astimezone(_VIETNAM)
        return assemble_system_prompt(
            self._prompts,
            *self._frame,
            instructions=self._instructions,
            variables={
                "current_date": now.date().isoformat(),
                "current_time": now.strftime("%H:%M"),
                "agent_name": self._agent_name,
                "user_display_name": names.person,
                "workspace_name": names.workspace,
                "locale": run_context.locale,
            },
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        appended = list(request.system_message.content_blocks) if request.system_message else []
        text = await self._render(request)
        message = SystemMessage(
            content_blocks=[cast(Any, {"type": "text", "text": text}), *appended]
        )
        return await handler(request.override(system_message=message))


def utc_now() -> datetime:
    """The frame's clock where nothing pins one."""
    return datetime.now(UTC)
