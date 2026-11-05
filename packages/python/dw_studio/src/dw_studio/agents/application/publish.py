"""`AgentPublishHook`: what the `agent` kind does in the transaction that takes
one of its versions `live` (tenant-config R2.15; agent-lifecycle R5.5).

agent-lifecycle calls it at the `.decided` handler, in the publish
transaction; it changes no stage and writes no audit. The kind's one task
there, recording the version's data boundary through `ActorBoundaryPort`, is
agent-builder ticket 05's, with the derivation it needs. Until then a version
published has no `studio.actor_boundaries` row and its runs read no record
(record-access R6.5): closed while it is missing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from dw_studio.core.application.ports import ArtifactTx


@dataclass(frozen=True, slots=True)
class AgentPublishHook:
    async def __call__(self, tx: ArtifactTx, version_id: uuid.UUID) -> None:
        del tx, version_id
