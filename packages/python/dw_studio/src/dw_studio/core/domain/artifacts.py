"""What a Studio artifact is, independent of where it is stored.

One envelope for every kind (ADR-0109 decisions 1-2, 4-5): an artifact with an
API name and an owning workspace, at most one unreleased version (a draft, or a
candidate awaiting its gate or its approval), and sealed versions numbered once
and never renumbered. The rules a row can break are the database's to refuse;
this module holds the vocabulary both sides use and the two pure functions the
seal and ticket 04's draft hash share (`definition_body`, `definition_hash`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from dw_kernel.canonical import content_hash
from dw_kernel.errors import DomainError

# 2 to 40 characters, a lower-case letter first (ADR-0107; R2.2). The database
# holds the same pattern in `ck_artifacts_api_name`.
API_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
# `dw.<area>/v<n>` (the `ck_artifact_versions_document_schema` CHECK).
DOCUMENT_SCHEMA: Final = re.compile(r"^dw\.[a-z_]+/v[0-9]+$")
# A label filters the list (`label=`); bounded so the column cannot become
# free storage (gate MEDIUM (c), 3/11/2026).
LABEL: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_LABELS: Final = 20

DEFINITION_MANIFEST_SCHEMA: Final = "dw.definition_manifest/v1"


class Stage(StrEnum):
    """`studio.artifact_versions.stage` (`ck_artifact_versions_stage`)."""

    DRAFT = "draft"
    EVALUATING = "evaluating"
    AWAITING_APPROVAL = "awaiting_approval"
    LIVE = "live"
    RETIRED = "retired"


# A candidate: sealed and on its way to `live` (ADR-0120 decision 1).
CANDIDATE_STAGES: Final = frozenset({Stage.EVALUATING, Stage.AWAITING_APPROVAL})
# A version whose use of another artifact stops that artifact's deletion (R3.3).
IN_USE_STAGES: Final = frozenset({Stage.EVALUATING, Stage.AWAITING_APPROVAL, Stage.LIVE})
# A version that was ever published: the API name is fixed from then on (R2.10).
PUBLISHED_STAGES: Final = frozenset({Stage.LIVE, Stage.RETIRED})


class TargetKind(StrEnum):
    """What a dependency points at (`ck_dependencies_to_kind`)."""

    ARTIFACT = "artifact"
    FIELD = "field"
    PICKLIST_VALUE = "picklist_value"
    PLATFORM_ARTIFACT = "platform_artifact"
    CONNECTOR = "connector"
    MCP_TOOL = "mcp_tool"
    BINDING = "binding"
    NODE_TYPE = "node_type"


class Usage(StrEnum):
    """How a version uses its target (`ck_dependencies_usage`)."""

    READ = "read"
    WRITE = "write"
    COMPARE = "compare"
    INVOKE = "invoke"
    BIND = "bind"
    DISPLAY = "display"


@dataclass(frozen=True, slots=True)
class Reference:
    """One use a document makes of something else, as a kind's `extract` finds
    it. For `artifact`, `to_key` is the target artifact's id as text, the id a
    pack and a copy carry (ADR-0109 decision 1); the seal resolves the version."""

    to_kind: TargetKind
    to_key: str
    usage: Usage
    path: str


@dataclass(frozen=True, slots=True)
class DocumentProblem:
    """One thing wrong with a document, at one JSON pointer (RFC 6901)."""

    pointer: str
    code: str
    detail: str


class DocumentInvalidError(DomainError):
    """A document a seal or a save refused, with every problem it found (422
    `validation_failed`, each problem one `errors[]` entry; R2.6)."""

    def __init__(self, message: str, problems: Sequence[DocumentProblem]) -> None:
        super().__init__(message, details={"problems": len(problems)})
        self.problems = tuple(problems)


@dataclass(frozen=True, slots=True, order=True)
class ClosureItem:
    """One pinned dependency of a sealed version: what the run manifest and the
    definition manifest name (ADR-0109 decision 4)."""

    kind: str
    key: str
    version: int | None
    content_hash: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "version": self.version,
            "content_hash": self.content_hash,
        }


def definition_body(
    kind: str, artifact_id: uuid.UUID, root_hash: str, closure: Iterable[ClosureItem]
) -> dict[str, Any]:
    """The `dw.definition_manifest/v1` body: the root and its closure, merged
    and ordered by `(kind, key)`, never the root's `version_no`, so a draft's
    provisional hash equals what the seal gives the same content (TC28)."""
    merged = sorted(set(closure), key=lambda item: (item.kind, item.key))
    return {
        "schema": DEFINITION_MANIFEST_SCHEMA,
        "root": {"kind": kind, "artifact_id": str(artifact_id), "content_hash": root_hash},
        "closure": [item.as_json() for item in merged],
    }


def definition_hash(body: dict[str, Any]) -> str:
    """The manifest's key: `dw_kernel.canonical` over the body, nothing else."""
    return content_hash(body)


def label_problems(labels: Sequence[str], *, at: str = "/labels") -> list[DocumentProblem]:
    problems: list[DocumentProblem] = []
    if len(labels) > MAX_LABELS:
        problems.append(DocumentProblem(at, "too_many_labels", f"at most {MAX_LABELS} labels"))
    problems.extend(
        DocumentProblem(f"{at}/{index}", "label_invalid", "a label is [a-z0-9][a-z0-9_-]{0,39}")
        for index, label in enumerate(labels)
        if not LABEL.fullmatch(label)
    )
    if len(set(labels)) != len(labels):
        problems.append(DocumentProblem(at, "label_repeated", "each label is named once"))
    return problems
