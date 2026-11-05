"""Workflow documents, a tool register and a trigger port for the tests of
Studio's `workflow` kind (workflow-engine ticket 01).

- `studio_step` and `studio_document` build a `dw.workflow/v1` document on
  Studio's path: every step with its own `retry`, `timeout_s` and `on_error`,
  no `key` or `version`; the fixture types are
  `dw_agent_runtime.testing.workflow_types`.
- `NoTools` is a tool register that knows no tool: a document with no
  `tool.call` step never asks it.
- `FakeTriggerActivation` honours `TriggerActivationPort`'s contract: what a
  transaction activates is kept when the test says it committed and dropped
  when it rolled back; a version activated twice changes nothing; the
  version it replaces is retired; `fail` raises.
- `workflow_entry` is the `workflow` kind as `platform_kinds` builds it, over
  the fixture types and the fake, for a composition root's `kinds=`.
- `plant_holder` plants a member of a workspace holding the keys given, at
  workspace depth (`WORKFLOW_KEYS`: read, edit, test and submit).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from dw_agent_runtime.testing.workflow_types import fixture_node_registry
from dw_agent_runtime.tool_specs import ToolSpec
from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
)
from dw_studio.core.application.boundaries import ActorBoundaryPort
from dw_studio.core.application.ports import ArtifactTx
from dw_studio.core.application.registry import ArtifactKindEntry
from dw_studio.kinds import (
    WORKFLOWS_EDIT_SCOPE,
    WORKFLOWS_READ_SCOPE,
    WORKFLOWS_TEST_SCOPE,
    workflow_kind,
)
from dw_studio.lifecycle.application.service import VERSIONS_SUBMIT_SCOPE
from dw_studio.testing.world import Person
from dw_studio.workflows.testing.fakes import RecordingBoundaries

WORKFLOW_KEYS = (
    WORKFLOWS_READ_SCOPE,
    WORKFLOWS_EDIT_SCOPE,
    WORKFLOWS_TEST_SCOPE,
    VERSIONS_SUBMIT_SCOPE,
)

POLICY: Mapping[str, Any] = {
    "retry": {"max_attempts": 1, "backoff": "fixed"},
    "timeout_s": 60,
    "on_error": "fail",
}


def studio_step(step_id: str, type_: str = "fixture.effect@1", **config: Any) -> dict[str, Any]:
    """A step with Studio's required policy; `config` as given."""
    return {"id": step_id, "type": type_, "config": dict(config), **POLICY}


def studio_document(*steps: dict[str, Any], source: str | None = None) -> dict[str, Any]:
    """A Studio document over `steps`, its one trigger using `source`."""
    return {
        "schema": "dw.workflow/v1",
        "triggers": [
            {
                "id": "khi_co_lead",
                "type": "fixture.trigger@1",
                "config": {"source": source or str(uuid.uuid4())},
            }
        ],
        "steps": list(steps),
    }


class NoTools:
    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> ToolSpec:
        raise NotFoundError("tool spec not registered", details={"tool": name})


@dataclass
class FakeTriggerActivation:
    """`versions` names each version's artifact, which the real adapter
    reads from the version row."""

    versions: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    fail: bool = False
    # artifact -> the version whose subscriptions are active, once committed.
    active: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    retired: list[uuid.UUID] = field(default_factory=list)
    calls: list[tuple[object, uuid.UUID]] = field(default_factory=list)
    _pending: dict[int, dict[uuid.UUID, uuid.UUID]] = field(default_factory=dict)

    async def activate(self, tx: ArtifactTx, version_id: uuid.UUID) -> None:
        self.calls.append((tx, version_id))
        if self.fail:
            raise ConflictError("the subscriptions could not be written")
        self._pending.setdefault(id(tx), {})[self.versions[version_id]] = version_id

    def settle(self, tx: object, *, committed: bool) -> None:
        """The end of `tx`, as the test's transaction ended."""
        pending = self._pending.pop(id(tx), {})
        if not committed:
            return
        for artifact, version in pending.items():
            previous = self.active.get(artifact)
            if previous == version:
                continue
            if previous is not None:
                self.retired.append(previous)
            self.active[artifact] = version


def workflow_entry(
    triggers: FakeTriggerActivation | None = None, boundaries: ActorBoundaryPort | None = None
) -> ArtifactKindEntry:
    return workflow_kind(
        nodes=fixture_node_registry(),
        tools=NoTools(),
        triggers=triggers or FakeTriggerActivation(),
        boundaries=boundaries or RecordingBoundaries(),
    )


async def plant_holder(
    conn: AsyncConnection,
    tenant: PlantedTenant,
    keys: tuple[str, ...] = WORKFLOW_KEYS,
    workspace: uuid.UUID | None = None,
) -> Person:
    """A member of `workspace` (the tenant's main one) holding `keys` there."""
    workspace = workspace or tenant.main
    user = await plant_person(conn, tenant.tenant_id)
    membership = await plant_membership(conn, tenant.tenant_id, workspace, user)
    role = await plant_role(
        conn, tenant.tenant_id, f"workflows_{user.hex[:12]}", dict.fromkeys(keys, "workspace")
    )
    await assign(conn, tenant.tenant_id, workspace, membership, role)
    return Person(user, tenant.tenant_id, workspace)
