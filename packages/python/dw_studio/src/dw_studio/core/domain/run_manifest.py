"""`dw.run_manifest/v1`: what one Studio run pinned (tenant-config R6.1, R6.8;
ADR-0109 decisions 6-8).

`extra="forbid"` at every level, so a key nobody reads (a secret version, a
setting) cannot ride in: the body holds no secret, and ticket 05 adds
`bindings`, by name. Its key is `content_hash` of `as_body()` through
`dw_kernel.canonical`, nothing else.

- `root`: the version the run starts from, by row id for every root;
  `version_no` is null and `stage` is `draft` exactly when that row was a draft
  at receipt, and `definition_hash` is then the provisional hash the seal would
  give the same content (TC28).
- `closure`: the root's direct dependencies only, verbatim from its definition
  manifest (or from the body `definition_body` builds for a draft); a child run
  has a manifest of its own (decision 9).
- `engine`: `durability` is `sync` and nothing else, with no default here; the
  builder sets it for every root (R6.8, TC32). The per-kind pins of decision 8
  join it in workflow-engine/05 with their readers.
- `bindings` (ticket 05; R7.4, V4.35): only when the root's closure declares
  one: the approved Binding set's id, and for each name a connection's id, a
  principal's id or a variable's `content_hash`. No secret version and no
  value: a call resolves its connection's latest unrevoked secret when it is
  made, and connections-and-vault records the version it used.
"""

from __future__ import annotations

import uuid
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dw_kernel.canonical import HASH_PATTERN
from dw_kernel.run_mode import RunMode
from dw_studio.core.domain.artifacts import TargetKind

RUN_MANIFEST_SCHEMA: Final = "dw.run_manifest/v1"
_HASH: Final = HASH_PATTERN.pattern


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RootSection(_Strict):
    kind: str = Field(min_length=1)
    artifact_id: uuid.UUID
    version_id: uuid.UUID
    version_no: int | None = Field(ge=1)
    definition_hash: str = Field(pattern=_HASH)
    stage: Literal["draft"] | None = None

    @model_validator(mode="after")
    def _number_iff_sealed(self) -> RootSection:
        if (self.version_no is None) != (self.stage == "draft"):
            raise ValueError("version_no is null exactly when the root is a draft")
        return self


class ClosureEntry(_Strict):
    kind: TargetKind
    key: str
    version: int | None
    content_hash: str | None = Field(pattern=_HASH)


class EngineSection(_Strict):
    durability: Literal["sync"]


class BoundValue(_Strict):
    """One binding's pin: exactly the field its kind carries."""

    kind: Literal["connection", "variable", "principal"]
    connection_id: uuid.UUID | None = None
    principal_id: uuid.UUID | None = None
    content_hash: str | None = Field(default=None, pattern=_HASH)

    @model_validator(mode="after")
    def _one_field(self) -> BoundValue:
        held = {
            "connection": self.connection_id,
            "principal": self.principal_id,
            "variable": self.content_hash,
        }
        if held[self.kind] is None or sum(v is not None for v in held.values()) != 1:
            raise ValueError(f"a {self.kind} binding pins its own field and no other")
        return self


class BindingsSection(_Strict):
    config_version_id: uuid.UUID | None
    values: dict[str, BoundValue]


class RunManifest(_Strict):
    schema_: Literal["dw.run_manifest/v1"] = Field(alias="schema")
    release_manifest_ref: str = Field(min_length=1)
    run_mode: RunMode
    root: RootSection
    closure: tuple[ClosureEntry, ...]
    engine: EngineSection
    bindings: BindingsSection | None = None

    def as_body(self) -> dict[str, Any]:
        """The stored body: JSON values, `root.stage` only for a draft root,
        `bindings` only for a root that declares one, each pin its one field."""
        body = self.model_dump(mode="json", by_alias=True)
        if body["root"]["stage"] is None:
            del body["root"]["stage"]
        if body["bindings"] is None:
            del body["bindings"]
        else:
            for name, pin in body["bindings"]["values"].items():
                body["bindings"]["values"][name] = {k: v for k, v in pin.items() if v is not None}
        return body
