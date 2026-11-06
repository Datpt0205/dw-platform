"""What a Studio agent run needs of the `agent` kind (agent-builder ticket 03;
spec R3.1, R3.3; ADR-0109 decision 6; ADR-0117 decisions 5, 6).

Two ports carry a turn in and out of the graph by run id, so the content of a
conversation never enters `worker_runs.input` or `result`:
`AgentTurnPort` reads the turn's messages, `AgentReplyPort` takes the final
answer. agent-builder/04 satisfies both for `trigger_kind=chat` over
`studio.conversation_messages`; agent-lifecycle for its `test` and `eval`
trials. Each is registered by the trigger kinds it answers.

`pinned_content_hash` is the hash gate's one computation: the `dw.definition_manifest/v1`
body of the root's content and the closure the manifest pinned, hashed by the
very functions the seal and the run manifest use (`definition_body`,
`definition_hash`; tenant-config/04), never a hash of the document alone.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from dw_agent_runtime.studio_agent import AgentMessage
from dw_kernel.canonical import content_hash
from dw_studio.core.domain.artifacts import ClosureItem, definition_body, definition_hash


class AgentTurnPort(Protocol):
    async def turn(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> Sequence[AgentMessage]:
        """The run's turn, the history then the question, read under
        ``tenant_id``."""
        ...


class AgentReplyPort(Protocol):
    async def reply(self, tenant_id: uuid.UUID, run_id: uuid.UUID, text: str) -> None:
        """The run's final answer, written where its caller reads it."""
        ...


def pinned_content_hash(
    kind: str, artifact_id: uuid.UUID, document: Any, body: Mapping[str, Any]
) -> str:
    """The definition hash of ``document`` as the root of the manifest
    ``body``: what a seal gives this content with this closure, and what a
    draft's provisional hash is (TC28)."""
    closure: list[ClosureItem] = [ClosureItem.from_json(item) for item in body["closure"]]
    return definition_hash(definition_body(kind, artifact_id, content_hash(document), closure))


__all__ = ["AgentReplyPort", "AgentTurnPort", "pinned_content_hash"]
