"""`TriggerActivationPort` before workflow-triggers/01 (workflow-engine
ticket 01, step 8).

Until that ticket there is no `studio.trigger_subscriptions`, and no trigger
kind of a Studio workflow can start a run, so a version going `live` has no
subscription to activate and none of a previous version to retire: the
port's contract holds with nothing to do. workflow-triggers/01 replaces this
at `build_studio` with its own adapter, which writes the subscriptions on the
publish transaction. Nothing calls the hook yet either: agent-lifecycle/04
does, from its `.decided` handler.
"""

from __future__ import annotations

import uuid

from dw_studio.core.application.ports import ArtifactTx


class NoTriggerSubscriptions:
    async def activate(self, tx: ArtifactTx, version_id: uuid.UUID) -> None:
        return None
