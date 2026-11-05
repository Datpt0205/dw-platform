"""How the wf-lite types run in a Studio run (workflow-engine/03): each a
`StepBody` over `EffectDoors`, so a step reaches the world only through the one
door its type declares, with the wrapper's key and the run's mode (R4.4, R4.5,
R4.7). A pack's run does not use these: its nodes keep wf-lite's own path, with
the Digital Worker's decision gate and the Validator's hand-off.

- `ai.llm@1` asks the `model` door with its prompt, inputs and output schema;
- `tool.call@1` asks the `tool` door; the tool is the one the run's manifest
  pinned, resolved by the door at call time, never here (R4.2);
- `logic.switch@1` and `human.approval@1` make no effect and answer `Routed`.
  An approval in a simulated run takes the decision its run's input gives the
  step (workflow-nodes R9.9); a live approval waits for a person, which needs
  the durable wait of workflow-engine/05, so until then it is refused, closed.

`time.wait@1` has no body yet: its wait is workflow-engine/05's too.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from dw_agent_runtime.wflite.doors import BodyResult, EffectDoors, Routed
from dw_kernel.errors import ConfigError

APPROVED = "approved"
REJECTED = "rejected"


async def llm(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    return await doors.call(
        "model",
        str(config["prompt"]),
        {
            "prompt": config["prompt"],
            "inputs": inputs.get("inputs") or {},
            "output_schema": config["output_schema"],
        },
    )


async def tool(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    raw = inputs.get("input")
    output = await doors.call(
        "tool", str(config["tool"]), {"input": dict(raw) if isinstance(raw, Mapping) else {}}
    )
    # The result whole, and its top-level fields beside it, as wf-lite's node.
    return {**output, "result": dict(output)}


async def switch(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    value = inputs.get("on")
    case = json.dumps(value) if isinstance(value, bool) else str(value)
    # The lane of the case; a case with no lane takes the type's default lane,
    # which the compiler knows from the IR (`KeyedPorts.default`).
    return Routed({"case": case}, f"cases.{case}")


async def approval(
    config: Mapping[str, Any], inputs: Mapping[str, Any], doors: EffectDoors
) -> BodyResult:
    if doors.run_mode == "live":
        raise ConfigError(
            "a live approval waits for a person, which this run cannot do yet",
            details={"reason_code": "approval_wait_unavailable"},
        )
    decision = doors.simulated_decision
    if decision not in (APPROVED, REJECTED):
        raise ConfigError(
            "a simulated approval takes the decision its run gives it",
            details={"reason_code": "approval_decision_missing"},
        )
    approved = decision == APPROVED
    return Routed(
        {"proposal": inputs.get("proposal"), "approved": approved, "comment": ""},
        APPROVED if approved else REJECTED,
    )
