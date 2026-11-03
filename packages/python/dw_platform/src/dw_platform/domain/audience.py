"""Who may find and open an agent: the `dw.audience/v1` document (ADR-0102 decision 7).

An audience is `any_of` a list of groups, each group `all_of` a list of typed
conditions: it matches when ONE group matches, and a group matches when EVERY
one of its conditions does. W1 knows one kind of condition,
`{"workspace_subtree": "<uuid>"}` (the W1 tree is flat, so a workspace's
subtree is the workspace itself); W2 adds kinds without changing the shape.
An audience decides who sees and invokes, and never widens data access.

This module owns the shape and every rule that needs no database: what a
document must look like, what makes one empty, the limit of 20 conditions
across the whole document, and the fixed wording of each refusal. Whether a
named workspace exists in the caller's tenant is asked by the application
(`dw_platform.application.audience`), and whether a person matches is
answered by PostgreSQL, `platform.audience_matches`, per call.

A refusal names where and what, never a value: a pointer (RFC 6901) built from
the document's own member names and indexes, a code, and a fixed sentence.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dw_kernel.errors import DomainError

AUDIENCE_SCHEMA = "dw.audience/v1"
MAX_CONDITIONS = 20
# The conditions W1 accepts; a one-member object naming another key is a kind
# this version does not know (`audience_condition_unsupported`), not a typo.
CONDITION_KINDS = frozenset({"workspace_subtree"})
# A document of ten thousand bad conditions is refused with this many problems.
MAX_PROBLEMS = 20

AudienceReason = Literal["audience_empty", "audience_invalid"]
AudienceProblemCode = Literal[
    "audience_empty",
    "audience_malformed",
    "audience_condition_unsupported",
    "audience_too_many_conditions",
    "audience_group_empty",
    "audience_workspace_unknown",
]

_DETAIL: dict[AudienceProblemCode, str] = {
    "audience_empty": "the audience names no condition",
    "audience_malformed": "the value does not have the dw.audience/v1 shape",
    "audience_condition_unsupported": "this kind of condition is not supported",
    "audience_too_many_conditions": f"an audience has at most {MAX_CONDITIONS} conditions",
    "audience_group_empty": "a group must name at least one condition",
    # One sentence for a workspace that does not exist and one of another
    # tenant: the answer must not tell them apart.
    "audience_workspace_unknown": "the workspace is not one of this company's",
}


@dataclass(frozen=True, slots=True)
class AudienceProblem:
    """One thing wrong with a document, located by a JSON pointer."""

    pointer: str
    code: AudienceProblemCode

    @property
    def detail(self) -> str:
        return _DETAIL[self.code]


class AudienceInvalidError(DomainError):
    """A `dw.audience/v1` document refused: 422 `validation_failed`, with
    `details.reason_code` and the problems, which the API turns into
    `errors[]`."""

    def __init__(self, reason_code: AudienceReason, problems: Sequence[AudienceProblem]) -> None:
        super().__init__(
            "the audience is not valid",
            details={"reason_code": reason_code},
        )
        self.reason_code: AudienceReason = reason_code
        self.problems: tuple[AudienceProblem, ...] = tuple(problems)


class WorkspaceSubtree(BaseModel):
    """Members of this workspace and of every workspace below it (W1: itself)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_subtree: UUID


class AudienceGroup(BaseModel):
    """A group matches when every one of its conditions matches."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    all_of: tuple[WorkspaceSubtree, ...]


class AudienceDocument(BaseModel):
    """A `dw.audience/v1` document: it matches when one group of `any_of` does.

    Built through `parse_audience`, which also holds the rules this shape
    cannot say (a condition at least, at most 20, no empty group). The member
    is `schema` on the wire; `schema_` here, because the name shadows an
    attribute of `BaseModel` (Pydantic warns, and `-W error` makes it fail).
    Validated by the alias only: a document spelling `schema_` is not one
    `platform.audience_matches` would read, so it must not pass here either."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_by_alias=True, validate_by_name=False
    )

    schema_: Literal["dw.audience/v1"] = Field(alias="schema")
    any_of: tuple[AudienceGroup, ...]

    def workspace_ids(self) -> frozenset[UUID]:
        return frozenset(c.workspace_subtree for g in self.any_of for c in g.all_of)

    def as_json(self) -> dict[str, Any]:
        """The wire form, as stored and as `platform.audience_matches` reads it."""
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """The shape, for a client that builds documents (agent-builder)."""
        return cls.model_json_schema(by_alias=True)


def _pointer(at: str, path: Sequence[object]) -> str:
    return at + "".join("/" + str(step).replace("~", "~0").replace("/", "~1") for step in path)


@dataclass(frozen=True, slots=True)
class _Condition:
    path: tuple[object, ...]
    value: object


def _groups(raw: object) -> Iterator[tuple[int, list[object] | None]]:
    """Each group of `any_of` that is an object, with its `all_of` when that is
    a list. Read before Pydantic, so it tolerates any value."""
    any_of = raw.get("any_of") if isinstance(raw, dict) else None
    if not isinstance(any_of, list):
        return
    for i, group in enumerate(any_of):
        if isinstance(group, dict):
            all_of = group.get("all_of")
            yield i, cast(list[object], all_of) if isinstance(all_of, list) else None


def _conditions(raw: object) -> list[_Condition]:
    return [
        _Condition(("any_of", i, "all_of", j), value)
        for i, all_of in _groups(raw)
        for j, value in enumerate(all_of or ())
    ]


def _unsupported(condition: _Condition) -> bool:
    value = condition.value
    return isinstance(value, dict) and len(value) == 1 and next(iter(value)) not in CONDITION_KINDS


def _shaped(
    raw: object, at: str, skip: list[tuple[object, ...]]
) -> tuple[AudienceDocument | None, list[AudienceProblem]]:
    """The document, or Pydantic's refusals as pointers: without the ones inside
    a condition of an unsupported kind (already named), and never with a value
    or a member name the caller made up, so an unexpected member is located at
    its parent object."""
    try:
        return AudienceDocument.model_validate(raw), []
    except ValidationError as exc:
        found: list[AudienceProblem] = []
        for error in exc.errors():
            loc = tuple(error["loc"])
            if any(loc[: len(prefix)] == prefix for prefix in skip):
                continue
            if error["type"] == "extra_forbidden" and loc:
                loc = loc[:-1]
            problem = AudienceProblem(_pointer(at, loc), "audience_malformed")
            if problem not in found:
                found.append(problem)
        return None, found


def parse_audience(raw: object, *, at: str = "") -> AudienceDocument:
    """The document `raw` holds, or `AudienceInvalidError`.

    `audience_empty` when no condition is named anywhere (an empty `any_of`, or
    only empty groups) and nothing else is wrong; `audience_invalid` with the
    problems otherwise, the document-wide one first. Each pointer starts with
    `at`, the document's place in the caller's request (`/audience`). A
    condition object of one member whose key is not a known kind is
    `audience_condition_unsupported`, decided here before Pydantic, whose
    `extra="forbid"` would call it malformed."""
    conditions = _conditions(raw)
    unsupported = [c for c in conditions if _unsupported(c)]
    document, malformed = _shaped(raw, at, [c.path for c in unsupported])
    problems = [
        AudienceProblem(_pointer(at, c.path), "audience_condition_unsupported") for c in unsupported
    ] + malformed
    if not conditions and not problems:
        raise AudienceInvalidError(
            "audience_empty", [AudienceProblem(_pointer(at, ("any_of",)), "audience_empty")]
        )
    if conditions:
        # An empty group is true for everyone; beside a real group it would
        # open the agent to the whole company.
        problems += [
            AudienceProblem(_pointer(at, ("any_of", i, "all_of")), "audience_group_empty")
            for i, all_of in _groups(raw)
            if all_of == []
        ]
    if len(conditions) > MAX_CONDITIONS:
        problems.insert(
            0,
            AudienceProblem(
                _pointer(at, conditions[MAX_CONDITIONS].path), "audience_too_many_conditions"
            ),
        )
    if problems or document is None:
        raise AudienceInvalidError("audience_invalid", problems[:MAX_PROBLEMS])
    return document


def condition_pointers(document: AudienceDocument, *, at: str = "") -> Iterator[tuple[str, UUID]]:
    """Each condition's pointer and the workspace it names, in document order."""
    for i, group in enumerate(document.any_of):
        for j, condition in enumerate(group.all_of):
            yield _pointer(at, ("any_of", i, "all_of", j)), condition.workspace_subtree
