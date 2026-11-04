"""The `workflow` kind's publish hook (workflow-engine R1.6; ADR-0109
decision 1; agent-lifecycle R5.5).

agent-lifecycle runs it in the transaction that takes a version `live` and
hands it that transaction; the hook activates the version's trigger
subscriptions on it, so both commit or roll back together. It changes no
stage and writes no `studio.version.published`: those are the lifecycle's.
workflow-engine/03 adds the `ActorBoundaryPort` call (R1.7) here.
"""

from __future__ import annotations

import uuid

from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import PublishHook
from dw_studio.workflows.application.ports import TriggerActivationPort


def workflow_publish_hook(triggers: TriggerActivationPort) -> PublishHook:
    async def publish(tx: ArtifactTx, version_id: uuid.UUID) -> None:
        await triggers.activate(tx, version_id)

    return publish
