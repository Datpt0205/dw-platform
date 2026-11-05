"""Unit: the step tree in the wire form the assistant's model writes (wf-ai/05).

The base is the Marketing pack's `lead_care@1.0.0`. Two halves of one claim:
the wire form goes out under strict structured output (the schema the
Responses adapter sends keeps every field and uses nothing strict refuses), and
it reads back as exactly the document it was made from. The model's malformed
answers end in `ModelOutputInvalidError` after the real gateway's retries.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from dw_agent_runtime.adapters.mock_model import MockModelAdapter
from dw_agent_runtime.adapters.openai_responses import _to_strict_schema
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, RoutingModelGateway
from dw_agent_runtime.model.profiles import ModelProfileRegistry
from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.ports import ModelOutputInvalidError, ModelRequest
from dw_agent_runtime.testing.limits import OpenLimits
from dw_agent_runtime.testing.models import resolver as model_resolver
from dw_agent_runtime.testing.pricing import FlatPricing
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.wflite import assistant_wire
from dw_agent_runtime.wflite.assistant import (
    PROMPT_ID,
    PROMPT_VERSION,
    AssistantTurn,
    Bases,
    output_schemas,
)
from dw_agent_runtime.wflite.assistant_wire import from_wire, to_wire
from dw_agent_runtime.wflite.catalog import load_shipped_packs, load_yaml
from dw_agent_runtime.wflite.registry import build_node_registry
from dw_kernel.errors import DomainError
from dw_platform.testing.residency import run_gate

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[5]
CONFIGS = ROOT / "configs"
REGISTRY = build_node_registry()
PINNED = load_shipped_packs(CONFIGS).workflow("lead_care", "1.0.0")
assert PINNED is not None
BASE = PINNED.document.model_dump(by_alias=True, exclude_none=True)
SCHEMAS = output_schemas(Bases(PINNED, PINNED), REGISTRY)
WIRE_MODELS: list[type[BaseModel]] = [
    getattr(assistant_wire, name)
    for name in dir(assistant_wire)
    if isinstance(getattr(assistant_wire, name), type)
    and issubclass(getattr(assistant_wire, name), BaseModel)
    and getattr(assistant_wire, name).__module__ == assistant_wire.__name__
    and not name.startswith("_")
]


def round_trip(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Through JSON, as the model's answer travels."""
    wire = json.loads(json.dumps([s.model_dump() for s in to_wire(steps)]))
    turn = AssistantTurn.model_validate({"kind": "proposal", "plan": [], "steps": wire})
    return from_wire(turn.steps or [], SCHEMAS)


def _walk(node: Any) -> Any:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_the_answer_goes_out_strict_with_every_field() -> None:
    """R1.1 (strict): no `oneOf`, no `discriminator`, no list-valued `type`, and
    every field of every wire model, the switch's `default` lane included."""
    strict = _to_strict_schema(AssistantTurn.model_json_schema())
    assert {m.__name__ for m in WIRE_MODELS} >= {
        "Entry",
        "LlmStep",
        "ToolStep",
        "ApprovalStep",
        "WaitStep",
        "SwitchStep",
        "SwitchConfig",
        "WireCase",
    }
    for model in WIRE_MODELS:
        kept = strict["$defs"][model.__name__]
        assert list(kept["properties"]) == list(model.model_fields), model.__name__
        assert kept["required"] == list(model.model_fields)
    assert "default" in strict["$defs"]["SwitchConfig"]["properties"]
    for node in _walk(strict):
        assert "oneOf" not in node and "discriminator" not in node
        assert not isinstance(node.get("type"), list)


def test_the_shipped_workflow_reads_back_as_itself() -> None:
    """R1.1 (both ways): every row of the mapping on `lead_care@1.0.0`."""
    assert round_trip(copy.deepcopy(BASE["steps"])) == BASE["steps"]


def test_the_rows_lead_care_does_not_use_read_back_too() -> None:
    """R1.1 (both ways): `seconds`, a text proposal and input, no `min_confidence`,
    a switch with no `default`, empty lanes."""
    steps: list[dict[str, Any]] = [
        {"id": "w", "type": "time.wait@1", "config": {"seconds": 60}},
        {
            "id": "s",
            "type": "logic.switch@1",
            "description": "r",
            "config": {
                "on": "{{ steps.w.woke_at }}",
                "cases": {
                    "a": [
                        {
                            "id": "ok",
                            "type": "human.approval@1",
                            "config": {
                                "decision_class": "email.send",
                                "proposal": "{{ steps.w }}",
                                "approved": [],
                            },
                        }
                    ],
                    "b": [],
                },
            },
        },
        {
            "id": "t",
            "type": "tool.call@1",
            "config": {"tool": "x@1.0.0", "input": "{{ work }}", "decision_class": "d"},
        },
        {
            "id": "l",
            "type": "ai.llm@1",
            "config": {
                "prompt": "marketing.lead_score@1.0.0",
                "inputs": {},
                "output_schema": SCHEMAS["marketing.lead_score@1.0.0"],
            },
        },
    ]
    assert round_trip(copy.deepcopy(steps)) == steps


def test_a_step_of_a_prompt_outside_the_base_gets_no_output_schema() -> None:
    """The validator then says what is missing; nothing is invented."""
    steps = copy.deepcopy(BASE["steps"][:1])
    steps[0]["config"]["prompt"] = "marketing.other@1.0.0"
    assert "output_schema" not in round_trip(steps)[0]["config"]


def test_a_base_with_a_non_text_leaf_is_refused_by_name() -> None:
    """M1: a number in a tool's input has no wire form; refused, never changed."""
    steps = copy.deepcopy(BASE["steps"])
    steps[2]["config"]["approved"][2]["config"]["input"]["since"] = 7
    with pytest.raises(DomainError) as refused:
        to_wire(steps)
    assert refused.value.details["reason_code"] == "assistant_base_not_expressible"
    assert str(refused.value.details["path"]).endswith("input.since")


def _steps_with(change: str) -> list[dict[str, Any]]:
    wire = [s.model_dump() for s in to_wire(copy.deepcopy(BASE["steps"]))]
    approve = wire[2]["config"]
    if change == "entry_twice":
        approve["proposal"].append(dict(approve["proposal"][0]))
    elif change == "entries_overlap":
        approve["approved"][2]["config"]["input"].append({"key": "from.x", "value": "y"})
    elif change == "case_twice":
        switch = approve["approved"][3]["config"]
        switch["cases"].append(dict(switch["cases"][0]))
    return wire


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"kind": "question", "question": "q", "steps": []}, id="question_with_steps"),
        pytest.param({"kind": "proposal", "plan": ["p"], "steps": []}, id="proposal_empty"),
        pytest.param(
            {"kind": "proposal", "plan": ["p"], "steps": _steps_with("entry_twice")},
            id="entry_twice",
        ),
        pytest.param(
            {"kind": "proposal", "plan": ["p"], "steps": _steps_with("entries_overlap")},
            id="entries_overlap",
        ),
        pytest.param(
            {"kind": "proposal", "plan": ["p"], "steps": _steps_with("case_twice")},
            id="case_twice",
        ),
    ],
)
async def test_a_malformed_answer_is_invalid_after_the_gateways_retries(
    answer: dict[str, Any],
) -> None:
    """R1.7, R1.5: the real gateway validates into `AssistantTurn`, retries, and
    raises `ModelOutputInvalidError`."""
    adapter = MockModelAdapter()
    adapter.register_builder(PROMPT_ID, PROMPT_VERSION, lambda prompt: copy.deepcopy(answer))
    profiles = ModelProfileRegistry()
    profiles.load_directory(CONFIGS / "models")
    prompts = PromptRegistry()
    prompts.load_directory(CONFIGS / "prompts")
    gateway = RoutingModelGateway(
        limits=OpenLimits(),
        residency=run_gate(),
        models=model_resolver(profiles, "balanced"),
        prompts=prompts,
        adapters={"mock": adapter},
        usage_recorder=InMemoryUsageRecorder(),
        pricing=FlatPricing(),
        run_control=OpenRunControl(),
    )
    request = ModelRequest(
        task="wf_ai.workflow_edit",
        prompt_id=PROMPT_ID,
        prompt_version=PROMPT_VERSION,
        variables={"instruction": "x", "history": "[]", "base_document": "x", "node_types": "y"},
    )
    run = RunContext(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        worker_id="wf_ai",
        worker_version="1.0.0",
        channel="test",
        plan_id="p",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="t",
    )
    with pytest.raises(ModelOutputInvalidError):
        await gateway.generate_structured(request, AssistantTurn, run_context=run)
    assert len(adapter.calls) >= 2


async def test_the_prompt_shows_the_steps_in_the_form_the_model_writes() -> None:
    """The base document in the prompt is in wire form, so the model copies it."""
    from test_wflite_assistant import assistant, context

    a, gateway = assistant({"kind": "question", "question": "?"})
    await a.turn(context(), uuid.uuid4(), instruction="x", history=[])
    sent = load_yaml(gateway.requests[0].variables["base_document"])
    assert sent["steps"] == [s.model_dump(exclude_none=True) for s in to_wire(BASE["steps"])]
    assert {k: v for k, v in sent.items() if k != "steps"} == {
        k: v for k, v in BASE.items() if k != "steps"
    }
    assert "trigger.work_item@1" not in gateway.requests[0].variables["node_types"]


def test_an_output_schema_comes_from_the_pin_first_and_the_pack_otherwise() -> None:
    """wf-ai/05 step 1: the pinned document's own schema wins; a prompt only the
    pack's workflow uses still gets the pack's."""
    from dataclasses import replace

    pack = PINNED
    assert pack is not None  # the module-level assert does not narrow in here
    score, *rest = pack.document.steps
    own = {"type": "object", "properties": {"mine": {"type": "string"}}}
    draft = rest[0].model_copy(update={"config": {**rest[0].config, "output_schema": own}})
    pinned = replace(pack, document=pack.document.model_copy(update={"steps": [draft, *rest[1:]]}))
    found = output_schemas(Bases(pinned, pack), REGISTRY)
    assert found["marketing.lead_email_draft@1.0.0"] == own
    assert found["marketing.lead_score@1.0.0"] == score.config["output_schema"]
