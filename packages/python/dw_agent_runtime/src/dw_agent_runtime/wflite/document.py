"""The `dw.workflow/v1` document a pack ships (wf-lite R1; ADR-0112 decision 1).

A tree of steps: each step is `{id, type, config, description?}`, and a step
whose type has ports holds one lane per port, an ordered list of steps, inside
its `config` under the port's name (`approved`/`rejected` of a
`human.approval`, `cases`/`default` of a `logic.switch`). The tree is the whole
topology: no edges, no positions. The model refuses unknown keys anywhere it
knows the shape, so a misspelt key is an error, not an ignored line.

One model for every path (ADR-0112 Amendments 2026-11-03): a pack, a wf-ai
tenant version `+t<n>` and a Studio document. What one path needs and another
refuses (`key` and `version`; a step's `retry`, `timeout_s`, `on_error` and
`error_lane`) is optional here and decided per path by `validate.PathRules`,
so a row stored before a key existed still reads. Where a step's lanes sit is
read in one place, `wflite.ir` (workflow-engine R2.12).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dw_agent_runtime.contracts import _SEMVER_PATTERN

STEP_ID = r"^[a-z][a-z0-9_]{0,39}$"
STEP_TYPE = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*@[1-9][0-9]*$"
SCHEMA_ID = "dw.workflow/v1"

VariableType = Literal["string", "integer", "number", "boolean", "uuid"]
EffectLevel = Literal["none", "internal", "external", "critical"]
Level = Literal["A0", "A1", "A2", "A3", "A4"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


OnError = Literal["fail", "continue", "route"]
Backoff = Literal["fixed", "exponential"]


class Retry(_Strict):
    """A step's own retry (ADR-0112 decision 1); the delay is the node
    wrapper's (workflow-engine R4.23)."""

    max_attempts: int = Field(ge=1, le=5, strict=True)
    backoff: Backoff


class Step(_Strict):
    id: str = Field(pattern=STEP_ID)
    type: str = Field(pattern=STEP_TYPE)
    config: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    # Required or refused per path (`PathRules`), never defaulted here.
    retry: Retry | None = None
    # The ceiling of one run of the step's node, in seconds; time parked at a
    # wait does not count (workflow-engine R4).
    timeout_s: int | None = Field(default=None, ge=1, le=900, strict=True)
    on_error: OnError | None = None
    # The "Khi lỗi" lane: steps as written, parsed where the tree is lowered.
    error_lane: list[dict[str, Any]] | None = None


class Variable(_Strict):
    name: str = Field(pattern=STEP_ID)
    type: VariableType
    default: Any = None
    required: bool = False
    # Bounds of a number or integer (leadcare R3.8); a value outside them is
    # `parameter_invalid` at the start (wf-lite R6.2).
    minimum: float | None = None
    maximum: float | None = None


class DecisionClassDecl(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")
    effect_level: EffectLevel
    reversible: bool
    ceiling: Level


class WorkKindDecl(_Strict):
    kind: str = Field(min_length=1, max_length=120)
    # A file under the pack's `schemas/` directory.
    schema_: str = Field(alias="schema", pattern=r"^[A-Za-z0-9_.@-]+\.json$")


class WorkflowDocument(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["dw.workflow/v1"] = Field(alias="schema")
    # A pack's and a `+t<n>` version's own; Studio's envelope holds them
    # (ADR-0109 decision 1), so `PathRules` decides.
    key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    version: str | None = Field(default=None, pattern=_SEMVER_PATTERN)
    triggers: list[Step] = Field(min_length=1)
    steps: list[Step] = Field(min_length=1)
    variables: list[Variable] = Field(default_factory=list)
    decision_classes: list[DecisionClassDecl] = Field(default_factory=list)
    work_kinds: list[WorkKindDecl] = Field(default_factory=list)
