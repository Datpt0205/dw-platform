"""The audience validator: one call a consumer makes before it stores a
`dw.audience/v1` document (org-and-principals R8.1, R8.2; agent-builder R1.5).

The shape and its rules are the domain's (`parse_audience`); what only the
database knows, whether each named workspace is one of the caller's company,
is asked here through `AudienceWorkspacesPort`, once per document, and only
for a document that is otherwise valid: an empty or malformed one never
reaches the database. A workspace of another tenant is refused with the same
code and sentence as one that does not exist.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from dw_platform.application.access_context import AccessContext
from dw_platform.domain.audience import (
    AudienceDocument,
    AudienceInvalidError,
    AudienceProblem,
    condition_pointers,
    parse_audience,
)

__all__ = ["AudienceValidator", "AudienceWorkspacesPort"]


class AudienceWorkspacesPort(Protocol):
    async def known(self, context: AccessContext, ids: frozenset[UUID]) -> frozenset[UUID]:
        """The subset of ``ids`` that are workspaces of ``context``'s tenant."""
        ...


class AudienceValidator:
    def __init__(self, workspaces: AudienceWorkspacesPort) -> None:
        self._workspaces = workspaces

    async def validate(
        self, context: AccessContext, document: object, *, at: str = ""
    ) -> AudienceDocument:
        """``document`` as a checked `AudienceDocument`, or `AudienceInvalidError`
        whose pointers start with ``at`` (the document's place in the request)."""
        parsed = parse_audience(document, at=at)
        known = await self._workspaces.known(context, parsed.workspace_ids())
        unknown = [
            AudienceProblem(pointer, "audience_workspace_unknown")
            for pointer, workspace_id in condition_pointers(parsed, at=at)
            if workspace_id not in known
        ]
        if unknown:
            raise AudienceInvalidError("audience_invalid", unknown)
        return parsed
