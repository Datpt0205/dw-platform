"""Test support for the `agent` kind (agent-builder ticket 02): a valid
`dw.agent/v1` document, a `dw.audience/v1` one, and the people of a company
at each depth of the two agent keys, planted as the migrator.

People of `tenant` (each a member of `workspace`, the tenant's main one unless
said otherwise):

- `author`: `studio.agents.author` and `studio.versions.submit`, who builds;
- `manager`: `studio.agents.manage_settings` alone, who never reads the
  definition (R1.11);
- `both`: the two agent keys;
- `elsewhere`: `studio.agents.manage_settings` in another workspace only;
- `nobody`: a member holding neither key;
- `owner`: an active human member, the accountable owner a body names.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from dw_platform.testing.rbac import PlantedTenant, plant_person
from dw_studio.agents.application.settings import (
    AGENTS_AUTHOR_SCOPE,
    AGENTS_MANAGE_SETTINGS_SCOPE,
)
from dw_studio.lifecycle.application.service import VERSIONS_SUBMIT_SCOPE
from dw_studio.testing.workflows import plant_holder
from dw_studio.testing.world import Person

AUTHOR_KEYS = (AGENTS_AUTHOR_SCOPE, VERSIONS_SUBMIT_SCOPE)


def agent_document(**overrides: Any) -> dict[str, Any]:
    """A W1 agent with no tool, so it seals in a company with no object."""
    document: dict[str, Any] = {
        "display": {"name": "Trợ lý lead"},
        "instructions": "Trả lời bằng tiếng Việt, ngắn gọn.",
        "model": {"profile": "balanced"},
        "purpose": "Trả lời câu hỏi về lead",
    }
    document.update(overrides)
    return document


def audience(*workspaces: uuid.UUID) -> dict[str, Any]:
    """Members of any one of `workspaces`; none is the empty audience."""
    return {
        "schema": "dw.audience/v1",
        "any_of": [{"all_of": [{"workspace_subtree": str(w)}]} for w in workspaces],
    }


async def plant_agent_people(
    conn: AsyncConnection, tenant: PlantedTenant, *, workspace: uuid.UUID | None = None
) -> dict[str, Person]:
    home = workspace or tenant.main
    other = next((w for w in tenant.workspaces if w != home), None)
    people = {
        "author": await plant_holder(conn, tenant, AUTHOR_KEYS, workspace=home),
        "manager": await plant_holder(
            conn, tenant, (AGENTS_MANAGE_SETTINGS_SCOPE,), workspace=home
        ),
        "both": await plant_holder(
            conn, tenant, (*AUTHOR_KEYS, AGENTS_MANAGE_SETTINGS_SCOPE), workspace=home
        ),
        "nobody": await plant_holder(conn, tenant, (), workspace=home),
    }
    if other is not None:
        people["elsewhere"] = await plant_holder(
            conn, tenant, (AGENTS_MANAGE_SETTINGS_SCOPE,), workspace=other
        )
    owner = await plant_person(conn, tenant.tenant_id)
    people["owner"] = Person(owner, tenant.tenant_id, home)
    return people
