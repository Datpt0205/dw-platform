"""What the `workflow` kind's publish hook asks of the rest of the platform,
declared here by its consumer (CLAUDE.md, Non-negotiable architecture)."""

from __future__ import annotations

import uuid
from typing import Protocol

from dw_studio.core.application.ports import ArtifactTx


class TriggerActivationPort(Protocol):
    """The trigger subscriptions of a workflow version that goes `live`
    (workflow-engine R1.6; ADR-0109 decision 1). workflow-triggers/01
    satisfies it by writing `studio.trigger_subscriptions`.

    - After the call, the artifact's `active` subscriptions are exactly the
      version's, and those of the version it replaces are `retired`.
    - A second call for the same version changes nothing: the outbox may
      deliver `.decided` again.
    - Everything happens on `tx`, the publish transaction agent-lifecycle/04
      opens and hands the hook, so the version and its subscriptions commit
      or roll back together; an error is raised, never swallowed, and rolls
      the publish back.
    """

    async def activate(self, tx: ArtifactTx, version_id: uuid.UUID) -> None: ...
