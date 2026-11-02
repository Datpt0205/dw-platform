"""A tenant tool's JSON Schemas at the executor (tools-and-skills ticket 01:
R1.1-R1.3; TS2, TS3) and the profile `dw.tool-schema/v1` (ADR-0116 decision 3).

The executor is called directly: LangChain checks nothing for a dict schema,
so this is the only check there is.
"""

from __future__ import annotations

from typing import Any

import pytest
from fakes import NOW, FakeExecutionStore, FakeToolClaims, FakeUoWFactory
from pydantic import BaseModel
from test_executor import make_definition, make_run_context

from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tool_schema import check_profile, json_schema_behaviour
from dw_agent_runtime.tools import RegisteredTool, ToolPayload, ToolRegistry
from dw_kernel.errors import ConfigError, DomainError
from dw_kernel.ports import FixedClock, SequentialIdGenerator
from dw_platform.application.json_schema import TOOL_FORMATS, tool_problems

pytestmark = pytest.mark.unit

LEAD_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lead_id": {"type": "string", "format": "uuid"},
        "amount": {"type": "integer", "minimum": 0},
    },
    "required": ["lead_id", "amount"],
    "additionalProperties": False,
}
LEAD_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {"saved": {"type": "boolean"}},
    "required": ["saved"],
    "additionalProperties": False,
}
LEAD = "00000000-0000-4000-8000-000000000001"


class Spy:
    def __init__(self, answer: object = None) -> None:
        self.calls = 0
        self.answer = answer if answer is not None else {"saved": True}

    async def __call__(self, payload: BaseModel, run_context: RunContext) -> Any:
        self.calls += 1
        return self.answer


def tenant_tool_executor(spy: Spy) -> tuple[ToolExecutor, FakeExecutionStore]:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            # Internal: an output refused after an external call left is
            # `outcome_unknown` instead (runtime-hardening R6.12).
            make_definition(name="crm.save_amount", side_effect_level="internal"),
            json_schema_behaviour(LEAD_INPUT, LEAD_OUTPUT, spy),
        )
    )
    store = FakeExecutionStore()
    executor = ToolExecutor(
        registry=registry,
        execution_store=store,
        uow_factory=FakeUoWFactory(),
        clock=FixedClock(NOW),
        id_generator=SequentialIdGenerator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=FakeToolClaims(store),
        steps=build_tool_executor_steps(),
    )
    return executor, store


async def _call(executor: ToolExecutor, raw: dict[str, object]) -> BaseModel:
    return await executor.execute(
        name="crm.save_amount",
        version="1.0.0",
        raw_input=raw,
        run_context=make_run_context(),
        idempotency_key="k1",
    )


# --------------------------------------------------------------- R1.1, R1.3 --


async def test_an_input_its_schema_refuses_never_reaches_the_handler() -> None:
    """R1.1, R1.3 (TS2): a wrong type, a value under its minimum and a field
    outside the schema; `validation_failed` names each path and keyword and
    never a value."""
    spy = Spy()
    executor, store = tenant_tool_executor(spy)
    with pytest.raises(DomainError) as refused:
        await _call(executor, {"lead_id": 1, "amount": -5, "extra": "x"})
    assert refused.value.code == "validation_failed"
    errors: Any = refused.value.details["errors"]
    assert {"path": "lead_id", "keyword": "type"} in errors
    assert {"path": "amount", "keyword": "minimum"} in errors
    assert {"path": "(root)", "keyword": "additionalProperties"} in errors
    assert "-5" not in str(refused.value.details) and "'x'" not in str(refused.value.details)
    assert spy.calls == 0 and store.records == []


async def test_only_a_field_outside_the_schema_is_refused() -> None:
    """R1.3 (TS2)."""
    spy = Spy()
    executor, _ = tenant_tool_executor(spy)
    with pytest.raises(DomainError) as refused:
        await _call(executor, {"lead_id": LEAD, "amount": 5, "extra": "x"})
    assert refused.value.details["errors"] == [
        {"path": "(root)", "keyword": "additionalProperties"}
    ]
    assert spy.calls == 0


async def test_an_input_its_schema_accepts_runs() -> None:
    spy = Spy()
    executor, store = tenant_tool_executor(spy)
    output = await _call(executor, {"lead_id": LEAD, "amount": 5})
    assert isinstance(output, ToolPayload) and output.model_dump() == {"saved": True}
    assert spy.calls == 1 and store.records[-1]["status"] == "succeeded"


# --------------------------------------------------------------------- R1.2 --


@pytest.mark.parametrize(
    "answer",
    [{"saved": True, "secret": "x"}, {"saved": "yes"}],
    ids=["a_field_outside", "a_wrong_type"],
)
async def test_an_output_its_schema_refuses_never_reaches_the_model(answer: object) -> None:
    """R1.2 (TS3): `validation_failed` with `reason_code` `tool_output_invalid`,
    a `failed` row, and no output handed back."""
    spy = Spy(answer)
    executor, store = tenant_tool_executor(spy)
    with pytest.raises(DomainError) as refused:
        await _call(executor, {"lead_id": LEAD, "amount": 5})
    assert refused.value.code == "validation_failed"
    assert refused.value.details["reason_code"] == "tool_output_invalid"
    assert spy.calls == 1
    assert store.records[-1]["status"] == "failed" and store.records[-1]["output"] is None


# ------------------------------------------------------------ the validator --


def test_the_format_list_is_closed_and_each_format_is_checked() -> None:
    """ADR-0116 decision 3: only these formats, each one really checked."""
    assert frozenset({"email", "uuid", "date", "date-time", "phone_vn", "tax_code_vn"}) == (
        TOOL_FORMATS
    )

    def problems_of(fmt: str, value: str) -> list[Any]:
        schema = {"type": "string", "format": fmt}
        return tool_problems(schema, value)

    for fmt, good, bad in [
        ("phone_vn", "0912 345 678", "12345"),
        ("phone_vn", "+84912345678", "0112345678"),
        ("phone_vn", "024 3826 1234", "02438261"),
        ("tax_code_vn", "0101234567", "01012345"),
        ("tax_code_vn", "0101234567-001", "0101234567-1"),
        ("tax_code_vn", "001099012345", "00109901234X"),
        ("date-time", "2026-11-02T10:00:00+07:00", "2026-11-02T10:00:00"),
        ("date", "2026-11-02", "02/11/2026"),
        ("uuid", LEAD, "not-a-uuid"),
    ]:
        assert problems_of(fmt, good) == [], (fmt, good)
        assert [p.keyword for p in problems_of(fmt, bad)] == ["format"], (fmt, bad)


def test_a_reference_is_never_fetched() -> None:
    """An empty `referencing.Registry()`: a remote `$ref` cannot resolve."""
    schema = {"$ref": "https://example.com/schema.json"}
    with pytest.raises(Exception, match=r"example.com"):
        tool_problems(schema, {})


# -------------------------------------------------------------- the profile --


def test_a_schema_inside_the_profile_is_accepted() -> None:
    check_profile(LEAD_INPUT)
    nested = {
        "type": "object",
        "properties": {
            "a": {
                "type": "object",
                "properties": {
                    "b": {
                        "type": "object",
                        "properties": {
                            "c": {
                                "type": "object",
                                "properties": {"d": {"type": "string"}},
                                "additionalProperties": False,
                            }
                        },
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }
    check_profile(nested)  # five levels, the root counted


def _closed(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": False}


@pytest.mark.parametrize(
    ("schema", "rule"),
    [
        ({"type": "array"}, "root_not_object"),
        ({"type": "object", "properties": {}}, "object_not_closed"),
        (_closed(a={"type": "object", "properties": {}}), "object_not_closed"),
        (_closed(a={"$ref": "#/$defs/x"}), "keyword:$ref"),
        (_closed(a={"allOf": [{"type": "string"}]}), "keyword:allOf"),
        (_closed(a={"oneOf": [{"type": "string"}]}), "keyword:oneOf"),
        (_closed(a={"not": {"type": "string"}}), "keyword:not"),
        (_closed(a={"if": {"type": "string"}}), "keyword:if"),
        (_closed(a={"type": "string", "pattern": "^(a+)+$"}), "keyword:pattern"),
        (_closed(a={"type": "string", "format": "ipv4"}), "format_unknown"),
        (
            _closed(a=_closed(b=_closed(c=_closed(d=_closed(e={"type": "string"}))))),
            "too_deep",
        ),
        (_closed(**{f"f{i}": {"type": "string"} for i in range(101)}), "too_many_properties"),
    ],
)
def test_a_schema_outside_the_profile_is_refused(schema: dict[str, Any], rule: str) -> None:
    """ADR-0116 decision 3: root object, closed objects, at most five levels
    and 100 properties, no `$ref`, `allOf`, `oneOf`, `not`, conditional or
    `pattern`, a closed format list."""
    with pytest.raises(ConfigError) as refused:
        check_profile(schema)
    assert refused.value.details["rule"] == rule


def test_exactly_one_hundred_properties_is_accepted() -> None:
    check_profile(_closed(**{f"f{i}": {"type": "string"} for i in range(100)}))


def test_a_behaviour_is_never_built_from_a_schema_outside_the_profile() -> None:
    with pytest.raises(ConfigError):
        json_schema_behaviour({"type": "object", "properties": {}}, LEAD_OUTPUT, Spy())
