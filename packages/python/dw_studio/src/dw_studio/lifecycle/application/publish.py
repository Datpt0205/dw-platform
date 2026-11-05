"""Publishing a version takes a second person, for every kind (agent-lifecycle
R5; ADR-0120 decisions 1-2; ticket 04).

- **The request.** A version moving to `awaiting_approval` opens a run-less
  `studio.publish.<kind>` request in the same transaction (`LifecycleService`,
  R5.1): stamped `studio.publish.approve`, in the component's owning
  workspace, its payload ids and codes only, `author_ids` among them. The
  prefix is strict at both composition roots, so the submitter is refused
  `second_person_required` before any guard runs (ADR-0104 decision 11); the
  guard here, registered for each kind of the registry, refuses every other
  author `author_cannot_approve` and a payload without `author_ids` (R5.2,
  R5.3).
- **The decision** is carried out by `review.PublishSettler` on the worker,
  and the candidate read by `review.CandidateReader`; this module holds what
  both and `LifecycleService` share: the names, the guard, the
  `studio.version.live` event and what changed between two documents.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from dw_agent_runtime.approval_flow import ApprovalDecisionGuard, RuleGuard
from dw_kernel.canonical import canonical_bytes
from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.outbox import OutboxEvent
from dw_studio.core.application.ports import VersionRow

# The prefix every publish request carries, strict at both composition roots
# (spec R5.2), and the stamp a decider must hold (R5.1, R5.4).
PUBLISH_PREFIX: Final = "studio.publish."
PUBLISH_APPROVE_SCOPE = "studio.publish.approve"

PUBLISHED: Final = "studio.version.published"
RETURNED_TO_DRAFT: Final = "studio.version.returned_to_draft"
CANDIDATE_READ: Final = "studio.version.candidate_read"

# ADR-0120 decision 2: a version that went live, ids only; no W1 reader
# (ticket 04 MEDIUM (a)), each kind's publish hook does its kind's part.
VERSION_LIVE: Final = "studio.version.live"
VERSION_LIVE_SCHEMA: Final = "1.0"

# The lane that carries out a publish decision, as `details.lane` names it.
SETTLING_LANE: Final = "outbox"

Path = Literal["approved", "tighten_only"]


def publish_approval_type(kind: str) -> str:
    return f"{PUBLISH_PREFIX}{kind}"


def author_ids(contributors: Sequence[uuid.UUID], submitted_by: uuid.UUID) -> list[str]:
    """Everyone who saved the version's draft, then its submitter, once each
    (R5.1): the guard refuses each of them."""
    return [str(person) for person in dict.fromkeys([*contributors, submitted_by])]


def payload_authors(request: ApprovalRequest) -> frozenset[str] | None:
    raw = request.payload.get("author_ids")
    if not isinstance(raw, list) or not raw or not all(isinstance(a, str) for a in raw):
        return None
    return frozenset(raw)


def require_not_author(request: ApprovalRequest, context: AccessContext) -> None:
    """R5.2, R5.3: no author decides their own version's publication, and a
    request that does not name its authors is not decided at all."""
    authors = payload_authors(request)
    if authors is None:
        raise ConflictError(
            "this publish request does not name its authors",
            details={"approval_id": str(request.id), "reason_code": "author_ids_missing"},
        )
    if str(context.principal_id) in authors:
        raise ConflictError(
            "an author of this version cannot decide its publication",
            details={"approval_id": str(request.id), "reason_code": "author_cannot_approve"},
        )


def publish_decision_guards(kinds: Iterable[str]) -> dict[str, ApprovalDecisionGuard]:
    """The guard under `studio.publish.<kind>` for each kind of the registry:
    `decision_guards` is keyed by the exact type, so a kind left out here
    would be decided by an author."""
    return {publish_approval_type(kind): RuleGuard(require_not_author) for kind in kinds}


def version_live(
    event_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    kind: str,
    version: VersionRow,
    actor_id: uuid.UUID,
    at: datetime,
) -> OutboxEvent:
    """`studio.version.live` v1, identifiers only: the outbox is drained by a
    dispatcher that serves every tenant."""
    return OutboxEvent(
        id=event_id,
        tenant_id=TenantId(tenant_id),
        workspace_id=WorkspaceId(workspace_id),
        event_type=VERSION_LIVE,
        schema_version=VERSION_LIVE_SCHEMA,
        aggregate_id=version.id,
        occurred_at=at,
        payload={
            "artifact_id": str(version.artifact_id),
            "version_id": str(version.id),
            "kind": kind,
        },
        actor_id=actor_id,
    )


# ---- what changed --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Change:
    """One difference at a JSON pointer (RFC 6901): `add` (no `before`),
    `remove` (no `after`) or `replace`. An array is one value at its pointer,
    compared whole (ticket 04 MEDIUM (b))."""

    path: str
    op: Literal["add", "remove", "replace"]
    before: Any = None
    after: Any = None


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def _key_order(key: str) -> bytes:
    # The canonical form's own order (RFC 8785: UTF-16 code units).
    return key.encode("utf-16-be")


def _differ(before: Any, after: Any, path: str, out: list[Change]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted({*before, *after}, key=_key_order):
            at = f"{path}/{_escape(key)}"
            if key not in before:
                out.append(Change(at, "add", after=after[key]))
            elif key not in after:
                out.append(Change(at, "remove", before=before[key]))
            else:
                _differ(before[key], after[key], at, out)
    elif canonical_bytes(before) != canonical_bytes(after):
        out.append(Change(path, "replace", before=before, after=after))


def document_changes(live: Any | None, candidate: Any) -> list[Change]:
    """What the candidate changes against the live document it was compared
    with, both in canonical form (`dw_kernel.canonical`), in its key order;
    with no live document, every top-level field is an `add` (R5.11)."""
    out: list[Change] = []
    if live is None:
        if isinstance(candidate, dict):
            for key in sorted(candidate, key=_key_order):
                out.append(Change(f"/{_escape(key)}", "add", after=candidate[key]))
        else:
            out.append(Change("", "add", after=candidate))
        return out
    _differ(live, candidate, "", out)
    return out


__all__ = [
    "CANDIDATE_READ",
    "PUBLISHED",
    "PUBLISH_APPROVE_SCOPE",
    "PUBLISH_PREFIX",
    "RETURNED_TO_DRAFT",
    "SETTLING_LANE",
    "VERSION_LIVE",
    "Change",
    "Path",
    "author_ids",
    "document_changes",
    "payload_authors",
    "publish_approval_type",
    "publish_decision_guards",
    "require_not_author",
    "version_live",
]
