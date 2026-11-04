"""`ArtifactKindRegistry`: what each Studio kind is, registered at the
composition root (tenant-config R2.15; ADR-0100 decision 6, ADR-0109 decision 1).

A kind's spec registers one entry with every field named, none defaulted: the
document schema, the read, write and submit keys its routes check (from the
one permission catalogue, `studio.<area>.<verb>`, tenant-rbac R1.6), its
publish hook, and two pure functions over a document: `validate` returns every
problem with its JSON pointer, `extract` every use it makes of something else.

The quality-gate flag is not here: it is `studio.artifact_kinds.has_quality_gate`
alone, a column with no DEFAULT (R2.14). The kinds the running app registers
are `dw_studio.kinds.platform_kinds(...)`, outside the core, which imports no
capability (custom-objects ticket 02); a kind that exists only in a test
reaches an app only through a composition root's `kinds=`, never from settings
or the environment.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from dw_studio.core.domain.artifacts import DOCUMENT_SCHEMA, DocumentProblem, Reference

if TYPE_CHECKING:
    from dw_studio.core.application.ports import ArtifactTx

PublishHook = Callable[["ArtifactTx", uuid.UUID], Awaitable[None]]
"""What a kind's spec runs in the transaction that takes one of its versions
`live` (the version id): agent-lifecycle calls it at the `.decided` handler and
on the tighten-only branch (agent-lifecycle R2.9, R5.5). It changes no stage
and writes no `studio.version.published`; `seal` never calls it."""

Validate = Callable[[Any], Sequence[DocumentProblem]]
Extract = Callable[[Any], Sequence[Reference]]


@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactKindEntry:
    """One kind. Every field is required: a kind that forgot a key or its hook
    cannot be constructed (R2.15)."""

    kind: str
    document_schema: str
    read_key: str
    write_key: str
    submit_key: str
    publish_hook: PublishHook
    validate: Validate
    extract: Extract

    def __post_init__(self) -> None:
        if not DOCUMENT_SCHEMA.fullmatch(self.document_schema):
            raise ValueError(f"{self.kind}: document_schema {self.document_schema!r}")
        for name in ("kind", "read_key", "write_key", "submit_key"):
            if not getattr(self, name).strip():
                raise ValueError(f"{self.kind or '?'}: {name} is blank")

    @property
    def keys(self) -> tuple[str, str, str]:
        return (self.read_key, self.write_key, self.submit_key)


class ArtifactKindRegistry:
    """Every registered kind, by name; built once at the composition root."""

    def __init__(self, entries: Sequence[ArtifactKindEntry]) -> None:
        by_kind: dict[str, ArtifactKindEntry] = {}
        for entry in entries:
            if entry.kind in by_kind:
                raise ValueError(f"kind {entry.kind!r} registered twice")
            by_kind[entry.kind] = entry
        self._entries: Mapping[str, ArtifactKindEntry] = MappingProxyType(by_kind)

    def get(self, kind: str) -> ArtifactKindEntry | None:
        return self._entries.get(kind)

    def __iter__(self) -> Iterator[ArtifactKindEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self._entries)
