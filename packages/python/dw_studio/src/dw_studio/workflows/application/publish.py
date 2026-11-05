"""The `workflow` kind's publish hook (workflow-engine R1.6, R1.7; ADR-0109
decision 1; agent-lifecycle R5.5; record-access R6.7).

agent-lifecycle runs it in the transaction that takes a version `live` and
hands it that transaction; the hook activates the version's trigger
subscriptions on it, then records the version's data boundary on it
(`ActorBoundaryPort.record`, derived by `derive_workflow_boundary`), so the
version, its subscriptions and its boundary commit or roll back together; no
transaction of its own. It changes no stage and writes no
`studio.version.published`: those are the lifecycle's.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_kernel.errors import ConfigError, NotFoundError
from dw_studio.core.application.boundaries import ActorBoundaryPort
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import PublishHook
from dw_studio.workflows.application.boundary import derive_workflow_boundary
from dw_studio.workflows.application.ports import TriggerActivationPort


def workflow_publish_hook(
    triggers: TriggerActivationPort,
    boundaries: ActorBoundaryPort,
    registry: Mapping[str, NodeTypeSpec],
) -> PublishHook:
    async def publish(tx: ArtifactTx, version_id: uuid.UUID) -> None:
        await triggers.activate(tx, version_id)
        found = await tx.root_version(version_id)
        if found is None:
            raise NotFoundError("version not found")
        version = found.version
        if version.definition_hash is None:
            raise ConfigError(
                "a version goes live sealed", details={"reason": "version_not_sealed"}
            )
        boundary = derive_workflow_boundary(version.document, registry)
        await boundaries.record(
            tx.session,
            "workflow",
            version.id,
            version.definition_hash,
            boundary.objects,
            boundary.fields,
        )

    return publish
