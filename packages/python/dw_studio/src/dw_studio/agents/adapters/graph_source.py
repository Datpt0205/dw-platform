"""`StudioGraphSource`: an agent version for its run (agent-builder ticket 03;
spec R3.1-R3.3, R3.8; ADR-0109 decisions 6, 8; ADR-0117 decision 5).

`StudioAgentPort` of `dw_agent_runtime.studio_agent`, injected into the
worker's runner (`LangGraphWorkflowRunner.studio_agents`), which caches what
`build` returns under `(tenant_id, agent_version_id, pinned_hash)` in its one
LRU and asks `build` only on a miss.

`build` reads the run's manifest again under the run's tenant (RLS), through
`PinnedResolver.load`, and passes the hash gate before anything is compiled:
the pinned root's content hashed with the closure the manifest pinned, by the
seal's own functions (`pinned_content_hash`), must equal the hash the run
pinned. A sealed version edited outside the platform (the migrator's role)
fails `definition_mismatch`; a draft edited since the run pinned it is refused
by `load` itself, which `take` already met first and left `blocked`
`incompatible_resume` (decision 8). The content that passed is what the graph
is compiled from, so a later hit runs exactly what the manifest pinned.
Whether the version is a draft rides with the graph, for the runner's mode
check at every take (R3.3: a draft runs only in `simulate`).

`enabled` reads the agent's settings row, for the runs that read it (R3.8): no
row, `enabled = false` or a component deleted is off.

`turn` and `reply` go to the ports registered for the run's trigger kind
(`AgentTurnPort`, `AgentReplyPort`); a trigger with none is
`agent_turn_unwired`, never a run with no question.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import StudioRun
from dw_agent_runtime.studio_agent import (
    AGENT_TURN_UNWIRED,
    DEFINITION_MISMATCH,
    AgentBlueprint,
    AgentCompilerPort,
    AgentMessage,
    AgentRefusedError,
    BuiltAgent,
)
from dw_kernel.errors import ConfigError
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.agents.adapters.tables import agent_settings
from dw_studio.agents.application.runtime import (
    AgentReplyPort,
    AgentTurnPort,
    pinned_content_hash,
)
from dw_studio.agents.domain.document import (
    AGENT_FRAME_ID,
    AGENT_FRAME_VERSION,
    AGENT_KIND,
    AgentDocument,
)
from dw_studio.core.adapters.run_manifest_store import SqlRunManifestStore
from dw_studio.core.adapters.tables import artifacts
from dw_studio.core.domain.artifacts import Stage
from dw_studio.core.domain.toolset import parse_toolset

_ENABLED = (
    sa.select(agent_settings.c.enabled)
    .select_from(
        agent_settings.join(
            artifacts,
            sa.and_(
                artifacts.c.tenant_id == agent_settings.c.tenant_id,
                artifacts.c.id == agent_settings.c.artifact_id,
            ),
        )
    )
    .where(artifacts.c.deleted_at.is_(None), artifacts.c.kind == AGENT_KIND)
)


def _mismatch(message: str) -> AgentRefusedError:
    return AgentRefusedError(DEFINITION_MISMATCH, message)


@dataclass(frozen=True)
class StudioGraphSource:
    session_factory: async_sessionmaker[AsyncSession]
    compiler: AgentCompilerPort
    # By trigger kind: agent-builder/04 registers `chat`, agent-lifecycle its
    # trials; a kind not here refuses its run `agent_turn_unwired`.
    turns: Mapping[str, AgentTurnPort]
    replies: Mapping[str, AgentReplyPort]

    async def enabled(self, tenant_id: uuid.UUID, artifact_id: uuid.UUID) -> bool:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            found = await session.scalar(
                _ENABLED.where(agent_settings.c.artifact_id == artifact_id)
            )
        return found is True

    async def build(self, taken: StudioRun) -> BuiltAgent:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=taken.tenant_id)
        ) as session:
            try:
                resolver = await PinnedResolver.load(
                    SqlRunManifestStore(session), taken.run_manifest_hash
                )
            except ConfigError as exc:
                if exc.details.get("reason") != "pinned_version_changed":
                    raise
                raise _mismatch("the draft changed after the run pinned it") from exc
        root = resolver.root
        version = root.artifact
        if (
            version is None
            or root.kind != AGENT_KIND
            or version.id != taken.artifact_version_id
            or root.content_hash != taken.pinned_hash
        ):
            raise _mismatch("the manifest does not pin this run's agent version")
        if (
            pinned_content_hash(root.kind, version.artifact_id, version.document, resolver.body)
            != taken.pinned_hash
        ):
            raise _mismatch("the agent version's content is not what the run pinned")
        document = AgentDocument.model_validate(version.document)
        toolset = () if document.toolset is None else parse_toolset(document.toolset).tools
        graph = await self.compiler.compile(
            AgentBlueprint(
                tenant_id=taken.tenant_id,
                version_id=version.id,
                pinned_hash=taken.pinned_hash,
                profile_id=document.model.profile,
                agent_name=document.display.name,
                instructions=document.instructions,
                toolset=tuple(toolset),
                resolver=resolver,
                frame_id=AGENT_FRAME_ID,
                frame_version=AGENT_FRAME_VERSION,
            )
        )
        return BuiltAgent(graph=graph, draft=version.stage == Stage.DRAFT.value)

    async def turn(self, taken: StudioRun) -> Sequence[AgentMessage]:
        port = self.turns.get(taken.trigger_kind)
        if port is None:
            raise _unwired(taken)
        return await port.turn(taken.tenant_id, taken.run_id)

    async def reply(self, taken: StudioRun, text: str) -> None:
        port = self.replies.get(taken.trigger_kind)
        if port is None:
            raise _unwired(taken)
        await port.reply(taken.tenant_id, taken.run_id, text)


def _unwired(taken: StudioRun) -> AgentRefusedError:
    return AgentRefusedError(
        AGENT_TURN_UNWIRED, f"no turn port for trigger kind {taken.trigger_kind!r}"
    )
