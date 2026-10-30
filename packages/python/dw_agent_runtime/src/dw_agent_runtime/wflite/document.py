"""The `dw.workflow/v1` document a pack ships (wf-lite R1; ADR-0112 decision 1).

A tree of steps: each step is `{id, type, config, description?}`, and a step
whose type has ports holds one lane per port, an ordered list of steps, inside
its `config` under the port's name (`approved`/`rejected` of a
`human.approval`, `cases`/`default` of a `logic.switch`). The tree is the whole
topology: no edges, no positions. The model refuses unknown keys anywhere it
knows the shape, so a misspelt key is an error, not an ignored line.
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


class Step(_Strict):
    id: str = Field(pattern=STEP_ID)
    type: str = Field(pattern=STEP_TYPE)
    config: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class Variable(_Strict):
    name: str = Field(pattern=STEP_ID)
    type: VariableType
    default: Any = None
    required: bool = False


class DecisionClassDecl(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,63}$")
    effect_level: EffectLevel
    reversible: bool
    ceiling: Level


class WorkKindDecl(_Strict):
    kind: str = Field(min_length=1, max_length=120)
    # A file under the pack's `schemas/` directory.
    schema_: str = Field(alias="schema", pattern=r"^[A-Za-z0-9_.-]+\.json$")


class WorkflowDocument(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["dw.workflow/v1"] = Field(alias="schema")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    version: str = Field(pattern=_SEMVER_PATTERN)
    triggers: list[Step] = Field(min_length=1)
    steps: list[Step] = Field(min_length=1)
    variables: list[Variable] = Field(default_factory=list)
    decision_classes: list[DecisionClassDecl] = Field(default_factory=list)
    work_kinds: list[WorkKindDecl] = Field(default_factory=list)
