"""The step-tree document the spike runs: wf-lite's `Step`, extended in place by
the keys ADR-0112 decision 1 adds and its Amendments of 2026-11-03 place on the
step (`retry`, `timeout_s`, `on_error`, `error_lane`), as workflow-engine/01
will. Lanes stay inside `config` under their port's name, as wf-lite has them.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dw_agent_runtime.wflite.document import Step


class Retry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=5)
    backoff_s: float = 1.0
    exponential: bool = False


class SrtStep(Step):
    retry: Retry | None = None
    timeout_s: float | None = None
    on_error: Literal["fail", "continue", "route", "incident"] = "fail"
    error_lane: list[dict[str, Any]] = Field(default_factory=list)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = 500


class SrtDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    steps: list[SrtStep]
    limits: Limits = Limits()


BLOCK_PORTS: Mapping[str, tuple[str, ...]] = {
    "logic.switch@1": (),  # cases.* and default, from config
    "human.approval@1": ("approved", "rejected"),
    "logic.loop@1": ("body", "max_reached"),
    "logic.map@1": ("body",),
}


def lanes(step: SrtStep) -> dict[str, list[SrtStep]]:
    """Every lane a step holds, by port, its error lane under `error`."""
    config = step.config
    found: dict[str, list[Any]] = {}
    if step.type == "logic.switch@1":
        for value, lane in (config.get("cases") or {}).items():
            found[f"cases.{value}"] = list(lane)
        found["default"] = list(config.get("default") or [])
    elif step.type == "logic.parallel@1":
        for i, lane in enumerate(config.get("lanes") or []):
            found[f"lane{i}"] = list(lane)
    else:
        for port in BLOCK_PORTS.get(step.type, ()):
            found[port] = list(config.get(port) or [])
    if step.error_lane:
        found["error"] = list(step.error_lane)
    return {port: [SrtStep.model_validate(raw) for raw in lane] for port, lane in found.items()}


def walk(steps: list[SrtStep]) -> Iterator[SrtStep]:
    for step in steps:
        yield step
        for lane in lanes(step).values():
            yield from walk(lane)
