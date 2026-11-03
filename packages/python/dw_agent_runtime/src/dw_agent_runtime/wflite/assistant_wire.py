"""The step tree as the workflow assistant's model writes it (wf-ai/05).

A `dw.workflow/v1` step keeps its config as free-form maps (`inputs`, a tool's
`input`, a switch's `cases`), and strict structured output cannot send a map
whose keys are not known ahead: the Responses adapter refuses the schema before
the call (`_to_strict_schema`), so the assistant never answered on a real model.
Here each step type of `build_node_registry()` but the trigger is a closed model
with typed fields: a map is a list of `{key, value}` entries, a switch's cases a
list of `{value, steps}`, and an `ai.llm@1` step sends no `output_schema` (it is
copied back from the base). A plain `Union`, not a discriminated one, because a
discriminator is emitted as `oneOf` and `discriminator`, which strict refuses.

`to_wire` (document to wire) builds what the prompt shows; `from_wire` (wire to
document) runs before every check of the platform, which see only the document.
They are the one converter, in both directions, so the two cannot drift: a test
holds `from_wire(to_wire(steps)) == steps` on the shipped workflow.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, TypeAdapter, field_validator

from dw_kernel.errors import DomainError


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entry(_Closed):
    """One leaf of a map: `key` is its dotted path (`to.user`), `value` text."""

    key: str
    value: str


def _checked_entries(entries: list[Entry]) -> list[Entry]:
    """A list that reads back as one map: no empty path part, no key twice, and
    no key that is another's parent (`to` and `to.user`). A ValueError, so the
    gateway retries and then raises `ModelOutputInvalidError` (R1.5)."""
    keys = [entry.key for entry in entries]
    for key in keys:
        if any(not part for part in key.split(".")):
            raise ValueError(f"an entry key has an empty part: {key!r}")
    twice = sorted({key for key in keys if keys.count(key) > 1})
    if twice:
        raise ValueError(f"an entry key is given twice: {twice}")
    for key in keys:
        for other in keys:
            if other.startswith(f"{key}."):
                raise ValueError(f"entry keys overlap: {key} and {other}")
    return entries


Entries = Annotated[list[Entry], AfterValidator(_checked_entries)]

# The output schema an `ai.llm@1` prompt answers in, by prompt id (from the base).
OutputSchemas = Mapping[str, Mapping[str, Any]]


def _not_expressible(path: str, why: str) -> DomainError:
    return DomainError(
        "the workflow cannot be shown to the assistant",
        details={"reason_code": "assistant_base_not_expressible", "path": path, "why": why},
    )


def _entries(value: Any, path: str, prefix: str = "") -> list[dict[str, str]]:
    """A document map as wire entries; only text leaves have a wire form (M1)."""
    if not isinstance(value, Mapping) or (prefix and not value):
        raise _not_expressible(path, "not a map of text")
    out: list[dict[str, str]] = []
    for key, leaf in value.items():
        if not isinstance(key, str) or not key or "." in key:
            raise _not_expressible(path, f"key {key!r}")
        if isinstance(leaf, Mapping):
            out += _entries(leaf, f"{path}.{key}", f"{prefix}{key}.")
        elif isinstance(leaf, str):
            out.append({"key": f"{prefix}{key}", "value": leaf})
        else:
            raise _not_expressible(f"{path}.{key}", "a leaf that is not text")
    return out


def _nested(entries: Sequence[Entry]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entry in entries:
        *parents, last = entry.key.split(".")
        node = out
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = entry.value
    return out


def _map_or_text(value: Any, path: str) -> str | list[dict[str, str]]:
    return value if isinstance(value, str) else _entries(value, path)


def _text_or_nested(value: str | list[Entry]) -> str | dict[str, Any]:
    return value if isinstance(value, str) else _nested(value)


class _Config(_Closed):
    @classmethod
    def wire(cls, config: Mapping[str, Any], path: str) -> dict[str, Any]:
        raise NotImplementedError

    def document(self, schemas: OutputSchemas) -> dict[str, Any]:
        raise NotImplementedError


class LlmConfig(_Config):
    prompt: str
    inputs: Entries
    min_confidence: float | str | None = None

    @classmethod
    def wire(cls, config: Mapping[str, Any], path: str) -> dict[str, Any]:
        out = {
            "prompt": config.get("prompt"),
            "inputs": _entries(config.get("inputs", {}), f"{path}.inputs"),
        }
        if config.get("min_confidence") is not None:
            out["min_confidence"] = config["min_confidence"]
        return out

    def document(self, schemas: OutputSchemas) -> dict[str, Any]:
        out: dict[str, Any] = {"prompt": self.prompt, "inputs": _nested(self.inputs)}
        if self.prompt in schemas:
            out["output_schema"] = copy.deepcopy(dict(schemas[self.prompt]))
        if self.min_confidence is not None:
            out["min_confidence"] = self.min_confidence
        return out


class ToolConfig(_Config):
    tool: str
    decision_class: str
    input: str | Entries

    @classmethod
    def wire(cls, config: Mapping[str, Any], path: str) -> dict[str, Any]:
        return {
            "tool": config.get("tool"),
            "decision_class": config.get("decision_class"),
            "input": _map_or_text(config.get("input"), f"{path}.input"),
        }

    def document(self, schemas: OutputSchemas) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "input": _text_or_nested(self.input),
            "decision_class": self.decision_class,
        }


class ApprovalConfig(_Config):
    decision_class: str
    proposal: str | Entries
    locked_fields: list[str] | None = None
    approved: list[WireStep] | None = None
    rejected: list[WireStep] | None = None

    @classmethod
    def wire(cls, config: Mapping[str, Any], path: str) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision_class": config.get("decision_class"),
            "proposal": _map_or_text(config.get("proposal"), f"{path}.proposal"),
        }
        if config.get("locked_fields") is not None:
            out["locked_fields"] = list(config["locked_fields"])
        for lane in ("approved", "rejected"):
            if config.get(lane) is not None:
                out[lane] = _steps_to_wire(config[lane], f"{path}.{lane}")
        return out

    def document(self, schemas: OutputSchemas) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision_class": self.decision_class,
            "proposal": _text_or_nested(self.proposal),
        }
        if self.locked_fields is not None:
            out["locked_fields"] = list(self.locked_fields)
        if self.approved is not None:
            out["approved"] = from_wire(self.approved, schemas)
        if self.rejected is not None:
            out["rejected"] = from_wire(self.rejected, schemas)
        return out


class WaitConfig(_Config):
    # Both or neither is the wf-lite validator's `oneOf` problem, not the wire's.
    seconds: int | None = None
    seconds_param: str | None = None

    @classmethod
    def wire(cls, config: Mapping[str, Any], path: str) -> dict[str, Any]:
        return {k: config[k] for k in ("seconds", "seconds_param") if config.get(k) is not None}

    def document(self, schemas: OutputSchemas) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class WireCase(_Closed):
    value: str
    steps: list[WireStep]


class SwitchConfig(_Config):
    on: str
    cases: list[WireCase]
    # Absent is still `wf.router_not_total` (wf-lite R3.3).
    default: list[WireStep] | None = None

    @field_validator("cases")
    @classmethod
    def _one_lane_per_value(cls, cases: list[WireCase]) -> list[WireCase]:
        values = [case.value for case in cases]
        if len(set(values)) != len(values):
            raise ValueError("a case value is given twice")
        return cases

    @classmethod
    def wire(cls, config: Mapping[str, Any], path: str) -> dict[str, Any]:
        cases = config.get("cases")
        if not isinstance(cases, Mapping):
            raise _not_expressible(f"{path}.cases", "not a map of lanes")
        out: dict[str, Any] = {
            "on": config.get("on"),
            "cases": [
                {"value": value, "steps": _steps_to_wire(steps, f"{path}.cases.{value}")}
                for value, steps in cases.items()
            ],
        }
        if config.get("default") is not None:
            out["default"] = _steps_to_wire(config["default"], f"{path}.default")
        return out

    def document(self, schemas: OutputSchemas) -> dict[str, Any]:
        out: dict[str, Any] = {
            "on": self.on,
            "cases": {case.value: from_wire(case.steps, schemas) for case in self.cases},
        }
        if self.default is not None:
            out["default"] = from_wire(self.default, schemas)
        return out


class LlmStep(_Closed):
    id: str
    type: Literal["ai.llm@1"]
    description: str | None = None
    config: LlmConfig


class ToolStep(_Closed):
    id: str
    type: Literal["tool.call@1"]
    description: str | None = None
    config: ToolConfig


class ApprovalStep(_Closed):
    id: str
    type: Literal["human.approval@1"]
    description: str | None = None
    config: ApprovalConfig


class WaitStep(_Closed):
    id: str
    type: Literal["time.wait@1"]
    description: str | None = None
    config: WaitConfig


class SwitchStep(_Closed):
    id: str
    type: Literal["logic.switch@1"]
    description: str | None = None
    config: SwitchConfig


# Plain on purpose: `Field(discriminator=...)` is emitted as `oneOf`.
WireStep = LlmStep | ToolStep | ApprovalStep | WaitStep | SwitchStep

for _model in (ApprovalConfig, WireCase, SwitchConfig):
    _model.model_rebuild()

_CONFIGS: Mapping[str, type[_Config]] = {
    "ai.llm@1": LlmConfig,
    "tool.call@1": ToolConfig,
    "human.approval@1": ApprovalConfig,
    "time.wait@1": WaitConfig,
    "logic.switch@1": SwitchConfig,
}
_STEPS: TypeAdapter[list[WireStep]] = TypeAdapter(list[WireStep])


def _steps_to_wire(steps: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        raise _not_expressible(path, "not a list of steps")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(steps):
        here = f"{path}/{i}"
        config_type = _CONFIGS.get(str(raw.get("type"))) if isinstance(raw, Mapping) else None
        if config_type is None or not isinstance(raw.get("config"), Mapping):
            raise _not_expressible(here, "not a step of a wire type")
        step: dict[str, Any] = {"id": raw.get("id"), "type": raw["type"]}
        if raw.get("description") is not None:
            step["description"] = raw["description"]
        step["config"] = config_type.wire(raw["config"], f"{here}/config")
        out.append(step)
    return out


def to_wire(steps: Sequence[Mapping[str, Any]]) -> list[WireStep]:
    """A document's step tree in the form the model writes back (no `output_schema`)."""
    return _STEPS.validate_python(_steps_to_wire(list(steps), "steps"))


def from_wire(steps: Sequence[WireStep], schemas: OutputSchemas) -> list[dict[str, Any]]:
    """The model's step tree as document steps; an `ai.llm@1` step gets the
    output schema of its prompt from `schemas`, and none when the base has no
    step using that prompt (then `wf.prompt_not_in_base` says why)."""
    out: list[dict[str, Any]] = []
    for step in steps:
        document: dict[str, Any] = {"id": step.id, "type": step.type}
        if step.description is not None:
            document["description"] = step.description
        document["config"] = step.config.document(schemas)
        out.append(document)
    return out


__all__ = [
    "ApprovalConfig",
    "Entry",
    "LlmConfig",
    "OutputSchemas",
    "SwitchConfig",
    "ToolConfig",
    "WaitConfig",
    "WireCase",
    "WireStep",
    "from_wire",
    "to_wire",
]
